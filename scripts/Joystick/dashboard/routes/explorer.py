"""
/explorer — Generic PulseChain address + transaction explorer.
Query any address or TX hash, get back basic on-chain info.
"""

import logging
import re
from fastapi import APIRouter, Query
from web3 import Web3
from eth_abi import decode as abi_decode

from ..chain_reader import get_reader, SEL_SYMBOL, SEL_DECIMALS, SEL_OWNER, SEL_BALANCE_OF
from .. import config

router = APIRouter()
logger = logging.getLogger("joystick.routes.explorer")

# Common selectors for probing unknown contracts
SEL_NAME = Web3.keccak(text="name()")[:4]
SEL_TOTAL_SUPPLY = Web3.keccak(text="totalSupply()")[:4]

# TX hash regex: 0x + 64 hex chars
_TX_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
# Address regex: 0x + 40 hex chars
_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _safe_str(data: bytes) -> str:
    """Try to decode ABI-encoded string from return data."""
    if len(data) < 64:
        return ""
    try:
        (s,) = abi_decode(["string"], data)
        return s
    except Exception:
        # Might be bytes32-encoded name (some old tokens)
        try:
            raw = data[0:32]
            return raw.rstrip(b"\x00").decode("utf-8", errors="replace").strip()
        except Exception:
            return ""


def _safe_uint(data: bytes) -> int:
    """Try to decode uint256 from return data."""
    if len(data) < 32:
        return 0
    try:
        (v,) = abi_decode(["uint256"], data)
        return v
    except Exception:
        return 0


def _safe_addr(data: bytes) -> str:
    """Try to decode address from return data."""
    if len(data) < 32:
        return ""
    try:
        (a,) = abi_decode(["address"], data)
        return a
    except Exception:
        return ""


def _query_address(address: str) -> dict:
    """Query an address — detect if EOA or contract, probe ERC20."""
    reader = get_reader()
    w3 = reader.w3
    addr = Web3.to_checksum_address(address)

    # Basic info
    pls_wei = reader.get_pls_balance(addr)
    code = w3.eth.get_code(addr)
    is_contract = len(code) > 0

    result = {
        "type": "address",
        "address": addr,
        "pls_balance": round(pls_wei / 1e18, 6),
        "pls_balance_wei": str(pls_wei),
        "is_contract": is_contract,
        "code_size": len(code) if is_contract else 0,
    }

    if not is_contract:
        # EOA — check nonce
        try:
            result["nonce"] = w3.eth.get_transaction_count(addr)
        except Exception:
            pass
        return result

    # Contract — probe for ERC20 + owner
    calls = [
        (addr, SEL_NAME),          # 0
        (addr, SEL_SYMBOL),        # 1
        (addr, SEL_DECIMALS),      # 2
        (addr, SEL_TOTAL_SUPPLY),  # 3
        (addr, SEL_OWNER),         # 4
    ]
    results = reader._multicall(calls)

    name = _safe_str(results[0][1]) if results[0][0] else ""
    symbol = _safe_str(results[1][1]) if results[1][0] else ""
    decimals = _safe_uint(results[2][1]) if results[2][0] else None
    total_supply_raw = _safe_uint(results[3][1]) if results[3][0] else None
    owner = _safe_addr(results[4][1]) if results[4][0] else ""

    if name:
        result["name"] = name
    if symbol:
        result["symbol"] = symbol
    if decimals is not None and results[2][0]:
        result["decimals"] = decimals
    if total_supply_raw is not None and results[3][0]:
        d = decimals if decimals else 18
        result["total_supply"] = round(total_supply_raw / (10 ** d), 6)
        result["total_supply_raw"] = str(total_supply_raw)
    if owner and owner != "0x" + "0" * 40:
        result["owner"] = owner

    # Is it an ERC20?
    result["is_erc20"] = bool(symbol and decimals is not None and results[3][0])

    # Check Joey wallet balance of this token (if ERC20)
    if result["is_erc20"]:
        try:
            from eth_abi import encode as abi_encode
            joey = Web3.to_checksum_address(config.JOEY_WALLET)
            bal_calldata = SEL_BALANCE_OF + abi_encode(["address"], [joey])
            bal_results = reader._multicall([(addr, bal_calldata)])
            if bal_results[0][0]:
                joey_bal = _safe_uint(bal_results[0][1])
                d = decimals if decimals else 18
                result["joey_balance"] = round(joey_bal / (10 ** d), 6)
        except Exception:
            pass

    return result


def _query_tx(tx_hash: str) -> dict:
    """Query a transaction hash — return receipt + basic details."""
    reader = get_reader()
    w3 = reader.w3

    result = {"type": "transaction", "hash": tx_hash}

    # Fetch TX object
    try:
        tx = w3.eth.get_transaction(tx_hash)
    except Exception as e:
        result["error"] = f"Transaction not found: {e}"
        return result

    result["from"] = tx.get("from", "")
    result["to"] = tx.get("to", "")
    result["value_pls"] = round(tx.get("value", 0) / 1e18, 6)
    result["gas_limit"] = tx.get("gas", 0)
    result["gas_price_beats"] = round(tx.get("gasPrice", 0) / 1e9, 2)
    result["nonce"] = tx.get("nonce", 0)
    result["block"] = tx.get("blockNumber", 0)

    # Input data summary
    input_data = tx.get("input", b"")
    if isinstance(input_data, (bytes, bytearray)):
        input_hex = input_data.hex()
    else:
        input_hex = str(input_data)
    if input_hex and input_hex != "0x":
        result["method_selector"] = "0x" + input_hex[:8] if not input_hex.startswith("0x") else input_hex[:10]
        result["input_size"] = len(input_hex) // 2
    else:
        result["method_selector"] = None
        result["input_size"] = 0

    # Fetch receipt
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        result["status"] = "success" if receipt.get("status") == 1 else "reverted"
        result["gas_used"] = receipt.get("gasUsed", 0)
        gas_price = tx.get("gasPrice", 0)
        result["gas_cost_pls"] = round((receipt.get("gasUsed", 0) * gas_price) / 1e18, 6)
        result["log_count"] = len(receipt.get("logs", []))
    except Exception:
        result["status"] = "pending"

    return result


@router.get("/explorer")
async def explore(
    q: str = Query(..., min_length=10, description="Address (0x + 40 hex) or TX hash (0x + 64 hex)"),
):
    """Query any PulseChain address or transaction hash."""
    q = q.strip()

    try:
        if _TX_RE.match(q):
            return _query_tx(q)
        elif _ADDR_RE.match(q):
            return _query_address(q)
        else:
            return {"error": "Invalid input. Provide a 0x-prefixed address (42 chars) or TX hash (66 chars)."}
    except Exception as e:
        logger.error(f"Explorer query failed for {q}: {e}")
        return {"error": str(e)}
