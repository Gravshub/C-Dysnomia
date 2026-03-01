"""
chain.py — Dual-RPC connections, all shared ABIs, contract factories, Multicall3 helper.

Patterns established here match the existing scripts exactly:
  - w3_read  → pulsechainstats.com (less congested for queries)
  - w3_submit → pulsechain.com     (reliable for TX submission)
  - safe()   → error-tolerant view call (returns None on failure)
  - multicall() → batch N reads into ONE RPC round-trip via Multicall3
"""
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

# ── RPC connections ───────────────────────────────────────────────────────────
w3_submit = Web3(Web3.HTTPProvider(SUBMIT_RPC, request_kwargs={"timeout": 60}))
w3_read   = Web3(Web3.HTTPProvider(READ_RPC,   request_kwargs={"timeout": 30}))

if not w3_read.is_connected():
    log.warning("Read RPC unavailable — falling back to submit RPC for reads")
    w3_read = w3_submit

# ── ABIs ─────────────────────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "name": "allowance", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "transfer", "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "name",        "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol",      "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals",    "outputs": [{"type": "uint8"}],  "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSupply", "outputs": [{"type": "uint256"}],"stateMutability": "view", "type": "function"},
]

# Extends ERC20 with Dysnomia Purchase mechanics
PURCHASE_ABI = ERC20_ABI + [
    {"inputs": [{"name": "_t", "type": "address"}, {"name": "_a", "type": "uint256"}],
     "name": "Purchase", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "_a", "type": "address"}], "name": "GetMarketRate",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

QING_ABI = PURCHASE_ABI + [
    {"inputs": [{"name": "UserToken", "type": "address"}], "name": "Join",
     "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "_t", "type": "address"}, {"name": "_a", "type": "uint256"}],
     "name": "Redeem", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "Waat",    "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "Entropy", "outputs": [{"type": "uint64"}],  "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "Asset",   "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

ROUTER_ABI = [
    {"inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}],
     "name": "getAmountsOut", "outputs": [{"name": "amounts", "type": "uint256[]"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "amountOutMin", "type": "uint256"},
                {"name": "path", "type": "address[]"}, {"name": "to", "type": "address"},
                {"name": "deadline", "type": "uint256"}],
     "name": "swapExactTokensForTokens", "outputs": [{"name": "amounts", "type": "uint256[]"}],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "amountOutMin", "type": "uint256"},
                {"name": "path", "type": "address[]"}, {"name": "to", "type": "address"},
                {"name": "deadline", "type": "uint256"}],
     "name": "swapExactTokensForETH", "outputs": [{"name": "amounts", "type": "uint256[]"}],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "amountOutMin", "type": "uint256"}, {"name": "path", "type": "address[]"},
                {"name": "to", "type": "address"}, {"name": "deadline", "type": "uint256"}],
     "name": "swapExactETHForTokens", "outputs": [{"name": "amounts", "type": "uint256[]"}],
     "stateMutability": "payable", "type": "function"},
    {"inputs": [{"name": "factory", "type": "address"}, {"name": "tokenA", "type": "address"},
                {"name": "tokenB", "type": "address"}],
     "name": "addLiquidity", "outputs": [{"name": "amountA", "type": "uint256"},
                                         {"name": "amountB", "type": "uint256"},
                                         {"name": "liquidity", "type": "uint256"}],
     "stateMutability": "nonpayable", "type": "function"},
]

FACTORY_ABI = [
    {"inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"}],
     "name": "getPair", "outputs": [{"name": "pair", "type": "address"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"}],
     "name": "createPair", "outputs": [{"name": "pair", "type": "address"}],
     "stateMutability": "nonpayable", "type": "function"},
]

PAIR_ABI = [
    {"inputs": [], "name": "getReserves",
     "outputs": [{"name": "_reserve0", "type": "uint112"}, {"name": "_reserve1", "type": "uint112"},
                 {"name": "_blockTimestampLast", "type": "uint32"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token0", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

META_ABI = [
    {"inputs": [{"name": "QingWaat", "type": "uint256"}], "name": "Beat",
     "outputs": [{"name": "Dione", "type": "uint256"}, {"name": "Charge", "type": "uint256"},
                 {"name": "Deimos", "type": "uint256"}, {"name": "Yeo", "type": "uint256"}],
     "stateMutability": "nonpayable", "type": "function"},
]

CHEON_ABI = [
    {"inputs": [{"name": "Qing", "type": "address"}], "name": "Su",
     "outputs": [{"name": "Charge", "type": "uint256"}, {"name": "Hypobar", "type": "uint256"},
                 {"name": "Epibar", "type": "uint256"}],
     "stateMutability": "nonpayable", "type": "function"},
]

DSS_ABI = [
    {"inputs": [{"name": "_text", "type": "string"}], "name": "chatAndClaimWithMultiplier",
     "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [], "name": "multiplier",
     "outputs": [{"type": "uint64"}], "stateMutability": "view", "type": "function"},
]

MULTICALL3_ABI = [
    {"inputs": [{"components": [{"name": "target", "type": "address"},
                                {"name": "allowFailure", "type": "bool"},
                                {"name": "callData", "type": "bytes"}],
                 "name": "calls", "type": "tuple[]"}],
     "name": "aggregate3",
     "outputs": [{"components": [{"name": "success", "type": "bool"},
                                 {"name": "returnData", "type": "bytes"}],
                  "name": "returnData", "type": "tuple[]"}],
     "stateMutability": "view", "type": "function"},
]

# ── Contract factory helpers ──────────────────────────────────────────────────
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

# ── safe() — error-tolerant view call ────────────────────────────────────────
def safe(contract, fn: str, *args) -> Any | None:
    """Call a view function; return None on any error (no raise)."""
    try:
        return getattr(contract.functions, fn)(*args).call()
    except Exception:
        return None

# ── Multicall3 batch reads ────────────────────────────────────────────────────
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

# ── Balance snapshot (Multicall3 powered) ─────────────────────────────────────
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
