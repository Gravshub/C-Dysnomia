"""
scanner.py — QING token discovery with TTL cache.

Discovers all 272 QING tokens via MAP contract events (Blockscout fallback),
resolves each to its underlying LAU/Asset token, and caches for CACHE_TTL seconds
to avoid re-scanning on every bot cycle.

Discovery sources (in priority order):
  1. MAP contract event scan via Blockscout internal-tx API (fast, off-chain)
  2. SEED_LAUS from config.py (always included as baseline)

Cache: JSON file at /tmp/joystick_qing_cache.json with timestamp.
"""
import json
import time
import logging

from ..core.log_names import get_logger
import os
from typing import Iterator

import requests
from web3 import Web3

from ..core.config import (
    MAP_ADDR, WPLS, AFFECTION, PDAI, PULSEX_V1_FACTORY, PULSEX_V2_FACTORY,
    NINEMM_FACTORY, SEED_LAUS, CACHE_TTL,
)
from ..core.chain import (
    purchasable, pair_contract, factory_contract, safe, erc20, PAIR_ABI, QING_ABI, w3_read
)

log = get_logger(__name__)

_JOYSTICK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE  = os.path.join(_JOYSTICK_DIR, "data", "arb_routes.json")
BLOCKSCOUT  = "https://scan.pulsechain.com/api"
FACTORIES   = [
    ("PulseX V1", PULSEX_V1_FACTORY),
    ("PulseX V2", PULSEX_V2_FACTORY),
    ("9mm",       NINEMM_FACTORY),
]
PAYMENT_TOKENS = [AFFECTION, PDAI]

# Populated by scan_tokens() via route_auditor — gates _enrich_token payment loop
_active_payment_filter: set = set()


# ── Cache helpers ─────────────────────────────────────────────────────────────
def _load_cache(allow_stale: bool = False) -> list[dict] | None:
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
        age = time.time() - data.get("timestamp", 0)
        if age < CACHE_TTL:
            log.debug("Scanner cache hit: %d tokens, age %.0fs", len(data["tokens"]), age)
            return data["tokens"]
        # Stale cache grace: return old data rather than triggering 4,600+ RPC calls
        if allow_stale and age < CACHE_TTL * 2:
            # Warn (not info) because stale prices on thin pools can be
            # actively exploitable per Heart's Law — operators should know
            # they are trading on aged snapshots.
            log.warning("Scanner cache STALE (%.0fs > TTL %.0fs) — prices may be "
                        "manipulable on thin pools; refresh when capacity allows",
                        age, CACHE_TTL)
            return data["tokens"]
    except Exception as exc:
        log.debug("Cache load failed: %s", exc)
    return None


def _save_cache(tokens: list[dict]) -> None:
    try:
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"timestamp": time.time(), "tokens": tokens}, f)
        os.replace(tmp, CACHE_FILE)
    except Exception as exc:
        log.debug("Cache save failed: %s", exc)
        try:
            os.remove(CACHE_FILE + ".tmp")
        except OSError:
            pass


# ── Blockscout MAP QING discovery ─────────────────────────────────────────────
def _fetch_qings_blockscout() -> list[str]:
    """
    Fetch all QING addresses created by MAP via Blockscout internal tx API.
    Returns list of QING addresses. Falls back to empty list on failure.
    """
    qings = []
    page = 1
    try:
        while True:
            resp = requests.get(
                BLOCKSCOUT,
                params={
                    "module": "account",
                    "action": "txlistinternal",
                    "address": MAP_ADDR,
                    "page": page,
                    "offset": 100,
                },
                timeout=15,
            )
            data = resp.json()
            if data.get("status") != "1" or not data.get("result"):
                break
            for tx in data["result"]:
                # Internal txs from MAP = contract deployments (QING contracts)
                contract_addr = tx.get("contractAddress", "")
                if contract_addr and contract_addr != "0x" + "0" * 40:
                    qings.append(Web3.to_checksum_address(contract_addr))
            if len(data["result"]) < 100:
                break
            page += 1
    except Exception as exc:
        log.warning("Blockscout QING fetch failed: %s", exc)

    log.info("Discovered %d QINGs from Blockscout", len(qings))
    return qings


# ── DEX pair lookup ───────────────────────────────────────────────────────────
def _find_best_pair(token_addr: str) -> dict | None:
    """
    Check all DEX factories for a token/WPLS pair.
    Returns dict with pair info or None if no pair found.
    """
    for name, factory_addr in FACTORIES:
        factory = factory_contract(factory_addr)
        pair_addr = safe(factory, "getPair", token_addr, WPLS)
        if not pair_addr or pair_addr == "0x" + "0" * 40:
            continue
        pair = pair_contract(pair_addr)
        reserves = safe(pair, "getReserves")
        if not reserves:
            continue
        t0 = safe(pair, "token0")
        t1 = safe(pair, "token1")
        if t0 is None or t1 is None:
            continue
        token_addr_cs = Web3.to_checksum_address(token_addr)
        if t0.lower() == token_addr_cs.lower():
            r_token, r_wpls = reserves[0], reserves[1]
        else:
            r_token, r_wpls = reserves[1], reserves[0]
        if r_token == 0 or r_wpls == 0:
            # Skip empty or half-empty pools. r_wpls==0 makes spot_price==0
            # which silently deprioritises the pair instead of excluding it,
            # and empty/near-empty WPLS reserves are where thin-pool price
            # manipulation hides.
            continue
        # Spot price: WPLS per token (in wei)
        spot_price = r_wpls * 10**18 // r_token
        return {
            "dex":       name,
            "pair":      pair_addr,
            "r_token":   r_token,
            "r_wpls":    r_wpls,
            "spot_pls":  spot_price,
        }
    return None


# ── Token enrichment ──────────────────────────────────────────────────────────
def _enrich_token(label: str, token_addr: str) -> dict | None:
    """
    Build a full token record with market rate, DEX pair info, and profit estimate.
    Returns None if the token has no usable market rate or DEX pair.
    """
    token = purchasable(token_addr)

    # Find the best payment token market rate
    best_rate = None
    best_payment = None
    for payment_addr in PAYMENT_TOKENS:
        # Skip unfunded payment routes (checked by route_auditor)
        if _active_payment_filter and payment_addr not in _active_payment_filter:
            continue
        rate = safe(token, "GetMarketRate", payment_addr)
        if rate and rate > 0:
            best_rate = rate
            best_payment = payment_addr
            break

    if not best_rate:
        return None

    self_bal = safe(token, "balanceOf", token_addr) or 0
    if self_bal == 0:
        return None  # Nothing to purchase

    pair_info = _find_best_pair(token_addr)
    if not pair_info:
        return None  # No DEX pair — can't sell

    sym = safe(token, "symbol") or "?"

    return {
        "label":    label,
        "address":  token_addr,
        "symbol":   sym,
        "self_bal": self_bal,
        "rate":     best_rate,
        "payment":  best_payment,
        **pair_info,
    }


# ── Public interface ──────────────────────────────────────────────────────────
def scan_tokens(force: bool = False, max_tokens: int | None = None) -> list[dict]:
    """
    Return enriched list of arb-eligible tokens, sorted by spot PLS price descending.

    Uses TTL cache. Set force=True to bypass cache.
    Merges MAP QING discovery with SEED_LAUS.

    Args:
        max_tokens: If set, cap the number of tokens enriched on cache miss.
                    Prioritizes SEED_LAUS first, then extras. Reduces RPC blast
                    from 4,600+ calls (272 tokens) to ~850 (50 tokens).
    """
    if not force:
        cached = _load_cache(allow_stale=(max_tokens is not None))
        if cached is not None:
            return cached

    log.info("Running fresh token scan (cache miss or force)")

    from .route_auditor import audit_payment_routes, discover_extra_tokens

    # Gate payment tokens by actual balance
    global _active_payment_filter
    audit = audit_payment_routes()
    _active_payment_filter = set(audit["funded_addresses"])
    if not _active_payment_filter:
        log.warning("No funded payment routes — scan will return empty")
        return []

    # Gather all token addresses to check
    all_tokens: dict[str, str] = {}  # address → label

    # Always include seed list
    for label, addr in SEED_LAUS:
        all_tokens[addr.lower()] = label

    # Expand token pool with data file discoveries
    extra_tokens = discover_extra_tokens()
    for label, addr in extra_tokens:
        if addr.lower() not in all_tokens:
            all_tokens[addr.lower()] = label

    # Discover QINGs from MAP → resolve to their Asset (LAU) tokens
    qing_addrs = _fetch_qings_blockscout()
    for qing_addr in qing_addrs:
        qing_c = w3_read.eth.contract(address=qing_addr, abi=QING_ABI)
        asset = safe(qing_c, "Asset")
        if asset and asset != "0x" + "0" * 40:
            asset_cs = Web3.to_checksum_address(asset)
            if asset_cs.lower() not in all_tokens:
                all_tokens[asset_cs.lower()] = f"QING-{qing_addr[:8]}"

    log.info("Scan pool: %d tokens (%d seed + %d QING + %d data)",
             len(all_tokens), len(SEED_LAUS), len(qing_addrs), len(extra_tokens))

    # Cap enrichment on cache miss to limit RPC blast
    if max_tokens is not None and len(all_tokens) > max_tokens:
        # Prioritize SEED_LAUS (always included), then take remaining from extras
        seed_addrs = {addr.lower() for _, addr in SEED_LAUS}
        seed_items = [(a, l) for a, l in all_tokens.items() if a in seed_addrs]
        extra_items = [(a, l) for a, l in all_tokens.items() if a not in seed_addrs]
        remaining = max_tokens - len(seed_items)
        capped = dict(seed_items + extra_items[:max(0, remaining)])
        log.info("Capping enrichment: %d → %d tokens (max_tokens=%d)",
                 len(all_tokens), len(capped), max_tokens)
        all_tokens = capped

    results = []
    for addr, label in all_tokens.items():
        record = _enrich_token(label, Web3.to_checksum_address(addr))
        if record:
            results.append(record)

    # Sort by spot PLS price descending (highest arb potential first)
    results.sort(key=lambda r: r["spot_pls"], reverse=True)

    _save_cache(results)
    log.info("Scan complete: %d arb-eligible tokens found", len(results))
    return results


def invalidate_cache() -> None:
    """Force next scan_tokens() call to re-discover from chain."""
    try:
        os.remove(CACHE_FILE)
    except FileNotFoundError:
        pass
