"""
chain.py — Dual-RPC connections, ABI loader, contract factories, Multicall3 helper.

ABIs are stored as JSON in data/abis/ and loaded via load_abi().
Patterns established here match the existing scripts exactly:
  - w3_read  → pulsechainstats.com (less congested for queries)
  - w3_submit → pulsechain.com     (reliable for TX submission)
  - safe()   → error-tolerant view call (returns None on failure)
  - multicall() → batch N reads into ONE RPC round-trip via Multicall3
"""
import json
import os
import logging
from typing import Any
from web3 import Web3

from .config import (
    SUBMIT_RPC, READ_RPC,
    JOEY_WALLET, AFFECTION, WPLS, GIBS_LAU, GIBS_QING,
    FORNAX, FOMALHAUTE, CHO, WM,
    PULSEX_V1_ROUTER, PULSEX_V1_FACTORY, PULSEX_V2_FACTORY, NINEMM_FACTORY,
    MULTICALL3,
)

log = logging.getLogger(__name__)

# ── ABI loader ─────────────────────────────────────────────────────────────
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def load_abi(name: str) -> list:
    """Load ABI from data/abis/{name}.json"""
    path = os.path.join(_DATA_DIR, "abis", f"{name}.json")
    with open(path) as f:
        return json.load(f)


# ── RPC connections ───────────────────────────────────────────────────────
w3_submit = Web3(Web3.HTTPProvider(SUBMIT_RPC, request_kwargs={"timeout": 60}))
w3_read   = Web3(Web3.HTTPProvider(READ_RPC,   request_kwargs={"timeout": 30}))

if not w3_read.is_connected():
    log.warning("Read RPC unavailable — falling back to submit RPC for reads")
    w3_read = w3_submit

# ── ABIs (loaded from JSON) ──────────────────────────────────────────────
ERC20_ABI     = load_abi("erc20")
PURCHASE_ABI  = ERC20_ABI + load_abi("purchase")
QING_ABI      = PURCHASE_ABI + load_abi("qing")
ROUTER_ABI    = load_abi("router")
FACTORY_ABI   = load_abi("factory")
PAIR_ABI      = load_abi("pair")
META_ABI      = load_abi("meta")
CHEON_ABI     = load_abi("cheon")
DSS_ABI       = load_abi("dss")
MULTICALL3_ABI = load_abi("multicall3")
TGSV7_ABI     = load_abi("tgsv7")
TGSV5_ABI     = load_abi("tgsv5")

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

def tgsv7_contract(w3=None) -> Any:
    from .config import TGSV7
    if not TGSV7:
        raise EnvironmentError("TGSV7_ADDRESS not set in .env")
    w3 = w3 or w3_read
    return w3.eth.contract(address=Web3.to_checksum_address(TGSV7), abi=TGSV7_ABI)

def tgsv5_contract(w3=None) -> Any:
    from .config import TGSV5
    if not TGSV5:
        raise EnvironmentError("TGSV5_ADDRESS not set in .env")
    w3 = w3 or w3_read
    return w3.eth.contract(address=Web3.to_checksum_address(TGSV5), abi=TGSV5_ABI)

# ── safe() — error-tolerant view call ────────────────────────────────────
def safe(contract, fn: str, *args) -> Any | None:
    """Call a view function; return None on any error (no raise)."""
    try:
        return getattr(contract.functions, fn)(*args).call()
    except Exception:
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
    mc = w3_read.eth.contract(address=MULTICALL3, abi=MULTICALL3_ABI)

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

    try:
        results = mc.functions.aggregate3(encoded_calls).call()
    except Exception as exc:
        log.warning("Multicall3 failed (%s) — falling back to individual calls", exc)
        return [safe(c, fn, *a) for c, fn, a in calls]

    decoded = []
    for i, (success, return_data) in enumerate(results):
        if not success or not return_data:
            decoded.append(None)
            continue
        try:
            result = fn_objects[i].call.__self__._decode_transaction_data(return_data)
            decoded.append(result[0] if len(result) == 1 else result)
        except Exception:
            decoded.append(None)
    return decoded

# ── Balance snapshot (Multicall3 powered) ─────────────────────────────────
def snapshot_balances() -> dict:
    """
    Read all key balances in ONE RPC call.
    Returns dict with keys: pls, affection, gibs, wm, fornax, fomalhaute, cho
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

    pls = w3_read.eth.get_balance(JOEY_WALLET)

    return {
        "pls":        pls,
        "affection":  results[0] or 0,
        "gibs":       results[1] or 0,
        "wm":         results[2] or 0,
        "fornax":     results[3] or 0,
        "fomalhaute": results[4] or 0,
        "cho":        results[5] or 0,
    }
