"""
/canopy — Parity Scope endpoint.

Returns Maria leaf tokens ranked by parity percentage
(DEX price vs backing value).

Caches results for 60s to avoid hammering the RPC with
repeated Multicall3 batches.
"""

import json
import logging
import math
import os
import time
from pathlib import Path

from eth_abi import decode as abi_decode, encode as abi_encode
from fastapi import APIRouter
from web3 import Web3

from ..chain_reader import get_reader
from ..models import CanopyToken, CanopyResponse
from .. import config

router = APIRouter()
logger = logging.getLogger("joystick.routes.canopy")

# ─── Selectors ────────────────────────────────────────────────────────
SEL_MULTIPLIER    = bytes.fromhex("1b3ed722")   # multiplier()
SEL_TOTAL_SUPPLY  = bytes.fromhex("18160ddd")   # totalSupply()
SEL_GET_RESERVES  = bytes.fromhex("0902f1ac")   # getReserves()
SEL_TOKEN0        = bytes.fromhex("0dfe1681")   # token0()
SEL_GET_PAIR      = bytes.fromhex("e6a43905")   # getPair(address,address)

# ─── Cache ────────────────────────────────────────────────────────────
_cache: dict = {"data": None, "ts": 0}
CACHE_TTL = 60  # seconds

# ─── Seed data ────────────────────────────────────────────────────────
_SEED_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "canopy_tokens.json")


def _load_seed_tokens() -> list[dict]:
    """Load token list from canopy_tokens.json seed file."""
    path = Path(_SEED_FILE).resolve()
    if not path.exists():
        logger.warning(f"Seed file not found: {path}")
        return []
    try:
        with open(path) as f:
            tokens = json.load(f)
        return tokens if isinstance(tokens, list) else []
    except Exception as e:
        logger.warning(f"Failed to load seed file: {e}")
        return []


def _decode_uint(ok: bool, data: bytes) -> int:
    if ok and len(data) >= 32:
        try:
            (v,) = abi_decode(["uint256"], data)
            return v
        except Exception:
            pass
    return 0


def _decode_address(ok: bool, data: bytes) -> str | None:
    if ok and len(data) >= 32:
        try:
            (a,) = abi_decode(["address"], data)
            if a != "0x" + "0" * 40:
                return a
        except Exception:
            pass
    return None


def _decode_reserves(ok: bool, data: bytes) -> tuple[int, int] | None:
    if ok and len(data) >= 96:
        try:
            r0, r1, _ = abi_decode(["uint112", "uint112", "uint32"], data)
            return r0, r1
        except Exception:
            pass
    return None


def _price_from_reserves(r0: int, r1: int, token0_lower: str, target_lower: str) -> tuple[float, float]:
    """Returns (price_pls_per_token, wpls_liquidity_human)."""
    if token0_lower == target_lower:
        # token0 = target, token1 = WPLS
        price = (r1 / r0) if r0 > 0 else 0
        liq = r1 / 1e18
    else:
        # token0 = WPLS, token1 = target
        price = (r0 / r1) if r1 > 0 else 0
        liq = r0 / 1e18
    return price, liq


def _build_canopy() -> CanopyResponse:
    """Build the full canopy response via Multicall3 batched reads."""
    seeds = _load_seed_tokens()
    if not seeds:
        return CanopyResponse(tokens=[], total_scanned=0, cached=False)

    reader = get_reader()
    wpls = Web3.to_checksum_address(config.WPLS)
    factory_v2 = Web3.to_checksum_address(config.PULSEX_V2_FACTORY)

    # ── Phase 1: Find V2 pairs for all tokens + parents ───────────────
    # Collect unique parent addresses
    parent_set = {s.get("parent_address", "").lower() for s in seeds if s.get("parent_address")}
    parent_list = sorted(parent_set)

    phase1_calls = []
    # Token/WPLS pairs
    for seed in seeds:
        addr = Web3.to_checksum_address(seed["address"])
        phase1_calls.append((factory_v2, SEL_GET_PAIR + abi_encode(["address", "address"], [addr, wpls])))
    # Parent/WPLS pairs
    for pa in parent_list:
        pa_cs = Web3.to_checksum_address(pa)
        phase1_calls.append((factory_v2, SEL_GET_PAIR + abi_encode(["address", "address"], [pa_cs, wpls])))

    p1_results = reader._multicall(phase1_calls)

    # Decode token pairs
    token_pairs = {}  # index -> pair address or None
    for i in range(len(seeds)):
        token_pairs[i] = _decode_address(*p1_results[i])

    # Decode parent pairs
    parent_pairs = {}  # parent_lower -> pair address
    for j, pa in enumerate(parent_list):
        idx = len(seeds) + j
        addr = _decode_address(*p1_results[idx])
        if addr:
            parent_pairs[pa] = addr

    # ── Phase 2: Batch multiplier + supply + reserves ─────────────────
    phase2_calls = []
    # Per-token: multiplier, totalSupply, [reserves, token0] if pair exists
    token_call_offsets = []  # (start_idx, has_pair) per token
    for i, seed in enumerate(seeds):
        start = len(phase2_calls)
        addr = Web3.to_checksum_address(seed["address"])
        phase2_calls.append((addr, SEL_MULTIPLIER))
        phase2_calls.append((addr, SEL_TOTAL_SUPPLY))
        pair = token_pairs.get(i)
        if pair:
            phase2_calls.append((pair, SEL_GET_RESERVES))
            phase2_calls.append((pair, SEL_TOKEN0))
            token_call_offsets.append((start, True))
        else:
            token_call_offsets.append((start, False))

    # Parent pair reserves
    parent_call_offsets = {}  # parent_lower -> start_idx
    for pa, pair_addr in parent_pairs.items():
        parent_call_offsets[pa] = len(phase2_calls)
        phase2_calls.append((pair_addr, SEL_GET_RESERVES))
        phase2_calls.append((pair_addr, SEL_TOKEN0))

    # Cap at 800 calls
    if len(phase2_calls) > 800:
        phase2_calls = phase2_calls[:800]

    p2_results = reader._multicall(phase2_calls)

    def _safe(idx):
        if idx < len(p2_results):
            return p2_results[idx]
        return (False, b"")

    # ── Phase 3: Decode parent prices ─────────────────────────────────
    parent_prices = {}
    for pa, pair_addr in parent_pairs.items():
        off = parent_call_offsets.get(pa)
        if off is None:
            continue
        reserves = _decode_reserves(*_safe(off))
        token0 = _decode_address(*_safe(off + 1))
        if reserves is None or token0 is None:
            continue
        pa_cs = Web3.to_checksum_address(pa)
        price, _ = _price_from_reserves(reserves[0], reserves[1], token0.lower(), pa_cs.lower())
        parent_prices[pa] = price

    # ── Phase 4: Decode per-token and compute parity ──────────────────
    canopy_tokens = []
    for i, seed in enumerate(seeds):
        off, has_pair = token_call_offsets[i]
        multiplier = max(_decode_uint(*_safe(off)), 1)
        total_supply = _decode_uint(*_safe(off + 1))

        if total_supply == 0:
            continue

        dex_price_pls = 0.0
        liquidity_pls = 0.0

        if has_pair:
            reserves = _decode_reserves(*_safe(off + 2))
            token0 = _decode_address(*_safe(off + 3))
            if reserves and token0:
                token_cs = Web3.to_checksum_address(seed["address"])
                dex_price_pls, liquidity_pls = _price_from_reserves(
                    reserves[0], reserves[1], token0.lower(), token_cs.lower()
                )

        parent_lower = (seed.get("parent_address") or "").lower()
        parent_price = parent_prices.get(parent_lower, 0)
        backing_pls = multiplier * parent_price
        parity_pct = (dex_price_pls / backing_pls * 100) if backing_pls > 0 else 0
        score = abs(parity_pct - 100) * math.sqrt(max(liquidity_pls, 0)) if parity_pct > 0 else 0

        canopy_tokens.append(CanopyToken(
            address=seed["address"],
            symbol=seed.get("symbol", "???"),
            parent_symbol=seed.get("parent_symbol"),
            parent_address=seed.get("parent_address"),
            multiplier=multiplier,
            dex_price_pls=float(f"{dex_price_pls:.12g}"),
            backing_pls=float(f"{backing_pls:.12g}"),
            parity_pct=round(parity_pct, 2),
            liquidity_pls=round(liquidity_pls, 2),
            pair_address=token_pairs.get(i),
            score=round(score, 2),
        ))

    canopy_tokens.sort(key=lambda t: -t.score)

    return CanopyResponse(
        tokens=canopy_tokens,
        total_scanned=len(seeds),
        cached=False,
    )


@router.get("/canopy", response_model=CanopyResponse)
async def get_canopy():
    """Parity Scope — Maria leaf token parity rankings.

    Returns tokens ranked by their deviation from backing parity,
    weighted by liquidity depth. Cached for 60s.
    """
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < CACHE_TTL:
        resp = _cache["data"]
        resp.cached = True
        return resp

    try:
        resp = _build_canopy()
        _cache["data"] = resp
        _cache["ts"] = now
        return resp
    except Exception as e:
        logger.error(f"Canopy build failed: {e}", exc_info=True)
        return CanopyResponse(tokens=[], total_scanned=0, cached=False)
