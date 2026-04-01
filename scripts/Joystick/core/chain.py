"""
chain.py — RPC pools, ABI loader, contract factories, Multicall3 helper.

ABIs are stored as JSON in data/abis/ and loaded via load_abi().

RPC connections use health-scored provider pools (rpc_provider.py):
  - _read_pool   → rotates across G4MM4, PulseChain, PublicNode, PCStats
  - _submit_pool → Tier 1 only (PulseChain, G4MM4, PublicNode) for TX privacy
  - safe()       → auto-retry + failover on every view call
  - multicall()  → batch N reads via Multicall3 with pool failover
"""
import json
import os
import logging
import time

from .log_names import get_logger
from typing import Any
from eth_abi import decode as abi_decode
from web3 import Web3
import requests

from .config import (
    JOEY_WALLET, AFFECTION, WPLS, GIBS_LAU, GIBS_QING,
    FORNAX, FOMALHAUTE, CHO, WM,
    PULSEX_V1_ROUTER, PULSEX_V1_FACTORY, PULSEX_V2_FACTORY, NINEMM_FACTORY,
    MULTICALL3, MULTI_AFFECTION,
)
from .rpc_provider import build_default_pools, RPCAllProvidersDown

log = get_logger(__name__)

# ── ABI loader ─────────────────────────────────────────────────────────────
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


_ABI_DIR = os.path.join(_DATA_DIR, "abis")
_last_blockscout_fetch: float = 0.0

_BLOCKSCOUT_V2_URL = "https://api.scan.pulsechain.com/api/v2/smart-contracts/{address}"


def fetch_abi_blockscout(address: str) -> list | None:
    """
    Download ABI from BlockScout for a verified contract.

    Uses: https://api.scan.pulsechain.com/api/v2/smart-contracts/{address}
    Returns: ABI list if contract is verified, None otherwise.
    Caches successful fetches to data/abis/{address}.json.

    Rate limited: 1 request per second max, 3 retries with backoff.
    """
    global _last_blockscout_fetch

    addr_lc = address.lower()
    # Check cache first
    cache_path = os.path.join(_ABI_DIR, f"{addr_lc}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                return json.load(f)
        except Exception:
            pass

    url = _BLOCKSCOUT_V2_URL.format(address=Web3.to_checksum_address(address))

    for attempt in range(3):
        # Rate limit: 1 req/sec
        elapsed = time.time() - _last_blockscout_fetch
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _last_blockscout_fetch = time.time()

        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 404:
                log.debug("BlockScout: contract %s not verified (404)", addr_lc[:10])
                return None
            resp.raise_for_status()
            data = resp.json()
            abi = data.get("abi")
            if not abi:
                log.debug("BlockScout: %s has no ABI (not verified?)", addr_lc[:10])
                return None

            # Cache via atomic write
            tmp_path = cache_path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(abi, f)
            os.replace(tmp_path, cache_path)
            log.info("BlockScout: cached ABI for %s (%d entries)", addr_lc[:10], len(abi))
            return abi

        except requests.RequestException as exc:
            if attempt < 2:
                log.debug("BlockScout: retry %d for %s: %s", attempt + 1, addr_lc[:10], exc)
                time.sleep(2 * (attempt + 1))
            else:
                log.warning("BlockScout: failed to fetch ABI for %s after 3 attempts: %s",
                            addr_lc[:10], exc)
                return None

    return None


def load_abi(name: str) -> list:
    """Load ABI by name. Falls back to BlockScout if name looks like an address."""
    path = os.path.join(_ABI_DIR, f"{name}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)

    # If name looks like an address, try BlockScout
    if name.startswith("0x") and len(name) == 42:
        abi = fetch_abi_blockscout(name)
        if abi:
            return abi

    raise FileNotFoundError(f"No ABI for {name}")


def load_contract_dynamic(address: str):
    """
    Load a contract with auto-ABI resolution.

    Priority:
      1. Cached ABI in data/abis/{address}.json
      2. BlockScout verified ABI (fetched + cached)
      3. Fallback to ERC20_ABI (basic interface)
    """
    addr = Web3.to_checksum_address(address)
    try:
        abi = load_abi(address.lower())
    except FileNotFoundError:
        abi = None

    if not abi:
        # ERC20_ABI is loaded below — use deferred reference
        abi = _get_erc20_abi()
        log.debug("Using ERC20 fallback ABI for %s", addr[:10])

    return w3_read.eth.contract(address=addr, abi=abi)


def _get_erc20_abi():
    """Deferred ERC20 ABI reference (avoids circular load order)."""
    return ERC20_ABI


# ── RPC pools ──────────────────────────────────────────────────────────────
_read_pool, _submit_pool = build_default_pools()

# Backward compat aliases — point at the best current provider.
# For critical paths, use _read_pool.call() or _submit_pool.send_raw() directly.
w3_read   = _read_pool.get_w3()
w3_submit = _submit_pool.get_w3()


def get_read_pool():
    """Access the read RPCPool for pool.call() usage."""
    return _read_pool


def get_submit_pool():
    """Access the submit RPCPool for pool.send_raw() usage."""
    return _submit_pool


def rpc_health() -> None:
    """Print health report for all RPC providers."""
    for label, pool in [("READ POOL", _read_pool), ("SUBMIT POOL", _submit_pool)]:
        print(f"\n  -- {label} --")
        for r in pool.health_report():
            status = "OK" if r["healthy"] else "DOWN"
            print(f"    [{status:4s}] {r['name']:12s}  {r['latency_ms']:6.0f}ms  "
                  f"err={r['error_rate']}%  score={r['score']}")
    print()

# ── ABIs (loaded from JSON) ──────────────────────────────────────────────
ERC20_ABI     = load_abi("erc20")
PURCHASE_ABI  = ERC20_ABI + load_abi("purchase")
QING_ABI      = PURCHASE_ABI + load_abi("qing")
ROUTER_ABI    = load_abi("router")
FACTORY_ABI   = load_abi("factory")
PAIR_ABI      = load_abi("pair")
META_ABI      = load_abi("meta")
CHEON_ABI     = load_abi("cheon")
# DSS ABI — DEPRECATED FOR MINTING. Kept for VOID Chat broadcast only.
# See config.py DSS deprecation note for full context.
DSS_ABI       = load_abi("dss")
MULTICALL3_ABI = load_abi("multicall3")
TGSV8_ABI     = load_abi("tgsv8")
TGSV8PLUS_ABI = load_abi("tgsv8plus")
MULTI_AFF_ABI = load_abi("multi_affection")

# ── Contract factory helpers ──────────────────────────────────────────────
def erc20(address: str) -> Any:
    return w3_read.eth.contract(address=Web3.to_checksum_address(address), abi=ERC20_ABI)

def purchasable(address: str) -> Any:
    return w3_read.eth.contract(address=Web3.to_checksum_address(address), abi=PURCHASE_ABI)

def qing(address: str) -> Any:
    return w3_read.eth.contract(address=Web3.to_checksum_address(address), abi=QING_ABI)

def router_contract(w3=None) -> Any:
    w3 = w3 or w3_read
    return w3.eth.contract(address=PULSEX_V1_ROUTER, abi=ROUTER_ABI)

def factory_contract(address: str) -> Any:
    return w3_read.eth.contract(address=Web3.to_checksum_address(address), abi=FACTORY_ABI)

def pair_contract(address: str) -> Any:
    return w3_read.eth.contract(address=Web3.to_checksum_address(address), abi=PAIR_ABI)

def tgsv8_contract(w3=None) -> Any:
    from .config import TGSV8
    if not TGSV8:
        raise EnvironmentError("TGSV8_ADDRESS not set in .env")
    w3 = w3 or w3_read
    return w3.eth.contract(address=Web3.to_checksum_address(TGSV8), abi=TGSV8_ABI)

def tgsv8plus_contract(w3=None) -> Any | None:
    """Return TGSv8+ contract instance. Returns None if address not configured."""
    from .config import TGSV8PLUS
    if not TGSV8PLUS:
        return None
    _w3 = w3 or w3_read
    return _w3.eth.contract(
        address=Web3.to_checksum_address(TGSV8PLUS),
        abi=TGSV8PLUS_ABI,
    )

_HUB_ABI = None

def _load_hub_abi():
    global _HUB_ABI
    if _HUB_ABI is None:
        _HUB_ABI = load_abi("joystick_hub")
    return _HUB_ABI


def joystick_hub(w3=None) -> Any:
    """Return JoystickHub contract instance (merged ABI -- all modules)."""
    from .config import JOYSTICK_HUB
    if not JOYSTICK_HUB:
        raise ValueError("JOYSTICK_HUB_ADDRESS not set in env")
    return (w3 or w3_read).eth.contract(
        address=Web3.to_checksum_address(JOYSTICK_HUB),
        abi=_load_hub_abi(),
    )


def multi_affection_contract(w3=None) -> Any:
    """Multi AFFECTION batch minter (Helios's deployed contract)."""
    _w3 = w3 or w3_read
    return _w3.eth.contract(
        address=Web3.to_checksum_address(MULTI_AFFECTION),
        abi=MULTI_AFF_ABI,
    )

# ── safe() — error-tolerant view call with RPC failover ─────────────────
def safe(contract, fn: str, *args) -> Any | None:
    """Call a view function with automatic retry + RPC failover.
    Returns None on any error (contract reverts or all RPCs down)."""
    def _do_call(w3):
        c = w3.eth.contract(address=contract.address, abi=contract.abi)
        return getattr(c.functions, fn)(*args).call()
    try:
        return _read_pool.call(_do_call)
    except RPCAllProvidersDown:
        log.error("All read RPCs down for safe(%s.%s)", contract.address[:10], fn)
        return None
    except Exception as exc:
        log.debug("safe(%s.%s) failed: %s", contract.address[:10], fn, exc)
        return None

# ── Multicall3 batch reads ────────────────────────────────────────────────
def multicall(calls: list[tuple[Any, str, list]]) -> list[Any | None]:
    """
    Batch multiple view calls into one RPC round-trip via Multicall3.

    calls: list of (contract, function_name, args_list)
    Returns: list of decoded results (None for failed calls)

    Example:
        results = multicall([
            (affection_contract, "balanceOf", [JOEY_WALLET]),
            (gibs_lau_contract,  "balanceOf", [JOEY_WALLET]),
        ])
        aff_bal, gibs_bal = results
    """
    encoded_calls = []
    fn_objects = []
    for contract, fn_name, args in calls:
        fn = getattr(contract.functions, fn_name)(*args)
        fn_objects.append(fn)
        encoded_calls.append({
            "target": contract.address,
            "allowFailure": True,
            "callData": fn._encode_transaction_data(),
        })

    def _do_multicall(w3):
        mc = w3.eth.contract(address=MULTICALL3, abi=MULTICALL3_ABI)
        return mc.functions.aggregate3(encoded_calls).call()

    try:
        results = _read_pool.call(_do_multicall)
    except Exception as exc:
        log.warning("Multicall3 failed (%s) — falling back to individual calls", exc)
        return [safe(c, fn, *a) for c, fn, a in calls]

    decoded = []
    for i, (success, return_data) in enumerate(results):
        if not success or not return_data:
            decoded.append(None)
            continue
        try:
            output_types = [o['type'] for o in fn_objects[i].abi['outputs']]
            result = abi_decode(output_types, return_data)
            decoded.append(result[0] if len(result) == 1 else result)
        except Exception:
            decoded.append(None)
    return decoded

# ── Batch reserve reads (Multicall3 powered) ──────────────────────────────
# getReserves() selector: keccak256("getReserves()")[:4] = 0x0902f1ac
_GET_RESERVES_SELECTOR = bytes.fromhex("0902f1ac")


def multicall3_batch_reserves(
    pair_addresses: list[tuple[str, str]],
    batch_size: int = 1500,
) -> dict[str, tuple[int, int, int, int]]:
    """
    Batch getReserves() on known V1+V2 pair addresses via Multicall3.

    pair_addresses: list of (v1_pair_addr, v2_pair_addr) tuples.
    Returns: dict keyed by index → (v1_r0, v1_r1, v2_r0, v2_r1).
    Pairs with zero address or failed calls return (0, 0, 0, 0).

    2 sub-calls per token pair (V1 + V2 getReserves) → 2N total calls,
    batched into ceil(2N / batch_size) Multicall3 aggregate3 RPCs.
    """
    ZERO = "0x" + "0" * 40

    # Build flat call list: [v1_reserves_0, v2_reserves_0, v1_reserves_1, v2_reserves_1, ...]
    encoded_calls = []
    call_map = []  # (pair_index, dex) where dex=0 is V1, dex=1 is V2
    for i, (v1_pair, v2_pair) in enumerate(pair_addresses):
        for dex, pair_addr in [(0, v1_pair), (1, v2_pair)]:
            if not pair_addr or pair_addr == ZERO:
                call_map.append((i, dex, False))
                continue
            call_map.append((i, dex, True))
            encoded_calls.append({
                "target": Web3.to_checksum_address(pair_addr),
                "allowFailure": True,
                "callData": _GET_RESERVES_SELECTOR,
            })

    # Execute in batches
    raw_results = []
    call_idx = 0
    for batch_start in range(0, len(encoded_calls), batch_size):
        batch = encoded_calls[batch_start:batch_start + batch_size]

        def _do_mc(w3, b=batch):
            mc = w3.eth.contract(address=MULTICALL3, abi=MULTICALL3_ABI)
            return mc.functions.aggregate3(b).call()

        try:
            batch_results = _read_pool.call(_do_mc)
            raw_results.extend(batch_results)
        except Exception as exc:
            log.warning("multicall3_batch_reserves batch failed: %s", exc)
            raw_results.extend([(False, b"") for _ in batch])

    # Decode results back into per-pair reserves
    results: dict[int, list[int]] = {}
    raw_idx = 0
    for i, dex, valid in call_map:
        if i not in results:
            results[i] = [0, 0, 0, 0]
        if not valid:
            continue
        success, return_data = raw_results[raw_idx]
        raw_idx += 1
        if success and len(return_data) >= 64:
            try:
                r0, r1, _ = abi_decode(["uint112", "uint112", "uint32"], return_data)
                if dex == 0:
                    results[i][0] = r0
                    results[i][1] = r1
                else:
                    results[i][2] = r0
                    results[i][3] = r1
            except Exception:
                pass

    return {i: tuple(v) for i, v in results.items()}


# ── Balance snapshot (Multicall3 powered) ─────────────────────────────────
def snapshot_balances(extra_wallets: list[str] | None = None) -> dict:
    """
    Read all key balances in ONE RPC call.
    Returns dict with keys: pls, affection, gibs, wm, fornax, fomalhaute, cho

    If extra_wallets is provided, also includes pls_minter, pls_seller etc.
    for each additional wallet address.
    """
    aff_c  = erc20(AFFECTION)
    gibs_c = erc20(GIBS_LAU)
    wm_c   = erc20(WM)
    for_c  = erc20(FORNAX)
    fom_c  = erc20(FOMALHAUTE)
    cho_c  = erc20(CHO)

    results = multicall([
        (aff_c,  "balanceOf", [JOEY_WALLET]),
        (gibs_c, "balanceOf", [JOEY_WALLET]),
        (wm_c,   "balanceOf", [JOEY_WALLET]),
        (for_c,  "balanceOf", [GIBS_LAU]),
        (fom_c,  "balanceOf", [GIBS_LAU]),
        (cho_c,  "balanceOf", [GIBS_LAU]),
    ])

    pls = _read_pool.call(lambda w3: w3.eth.get_balance(JOEY_WALLET))

    snap = {
        "pls":        pls,
        "affection":  results[0] or 0,
        "gibs":       results[1] or 0,
        "wm":         results[2] or 0,
        "fornax":     results[3] or 0,
        "fomalhaute": results[4] or 0,
        "cho":        results[5] or 0,
    }

    # Extra wallet PLS balances (for multi-wallet mode)
    if extra_wallets:
        role_names = ["minter", "seller"]
        for i, addr in enumerate(extra_wallets):
            key = f"pls_{role_names[i]}" if i < len(role_names) else f"pls_extra_{i}"
            try:
                snap[key] = _read_pool.call(
                    lambda w3, a=addr: w3.eth.get_balance(a))
            except Exception:
                snap[key] = 0

    return snap
