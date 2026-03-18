"""
simulator.py — Free eth_call simulation with human-readable revert decoding.

Every TX in Joystick goes through simulate() before estimate_gas() and send.
A revert at simulation stage costs zero gas and gives an actionable error message.

Revert decoding covers:
  - Standard Error(string):  0x08c379a0 — most Solidity requires/reverts
  - Panic(uint256):          0x4e487b71 — array out of bounds, div by zero, etc.
  - Custom errors:           4-byte selector lookup in KNOWN_ERRORS
"""
import re
import logging

from .log_names import get_logger
from typing import Any
from web3.exceptions import ContractLogicError

from .config import JOEY_WALLET

log = get_logger(__name__)

# ── Known custom error selectors (add as discovered) ─────────────────────────
KNOWN_ERRORS: dict[str, str] = {
    "08c379a0": "Error(string)",
    "4e487b71": "Panic(uint256)",
    "3e4f4c8e": "MarketRateCanOnlyBeIncreased",
    "f2b4f8a9": "ReentrantCall",
    "d0d04f60": "NotOwner",
    "82b42900": "ContractPaused",
    "8baa579f": "RHOCallFailed",
}

PANIC_CODES = {
    0x01: "assert failed",
    0x11: "arithmetic overflow/underflow",
    0x12: "division or modulo by zero",
    0x21: "invalid enum conversion",
    0x22: "storage byte array encoding",
    0x31: "pop on empty array",
    0x32: "array index out of bounds",
    0x41: "too much memory allocated",
    0x51: "zero-initialized function pointer called",
}

# ── Exceptions ────────────────────────────────────────────────────────────────
class SimulationFailed(Exception):
    """Raised when eth_call simulation predicts a revert."""

class GasTooHigh(Exception):
    """Raised when current gas price exceeds configured ceiling."""

# ── Revert decoder ───────────────────────────────────────────────────────────
def decode_revert(error: Exception) -> str:
    """
    Convert a ContractLogicError into a human-readable revert reason.
    Returns a plain string describing the revert.
    """
    msg = str(error)

    # Extract hex payload from error message
    hex_match = re.search(r'0x([0-9a-fA-F]+)', msg)
    if not hex_match:
        return f"Revert (no data): {msg[:200]}"

    hex_data = hex_match.group(1).lower()
    if len(hex_data) < 8:
        return f"Revert (short data): 0x{hex_data}"

    selector = hex_data[:8]

    # Standard Error(string)
    if selector == "08c379a0" and len(hex_data) >= 136:
        try:
            payload = bytes.fromhex(hex_data[8:])
            # ABI: offset(32 bytes) + length(32 bytes) + string data
            str_len = int.from_bytes(payload[32:64], "big")
            text = payload[64:64 + str_len].decode("utf-8", errors="replace")
            return f"Revert: {text}"
        except Exception:
            pass

    # Panic(uint256)
    if selector == "4e487b71" and len(hex_data) >= 72:
        try:
            code = int(hex_data[8:72], 16)
            desc = PANIC_CODES.get(code, f"code 0x{code:02x}")
            return f"Panic: {desc}"
        except Exception:
            pass

    # Known custom error
    name = KNOWN_ERRORS.get(selector)
    if name:
        return f"Custom error: {name} (0x{selector})"

    return f"Unknown revert: 0x{hex_data[:40]}..."


# ── simulate() ───────────────────────────────────────────────────────────────
def simulate(fn_call, gas: int = 5_000_000, from_address: str | None = None) -> Any:
    """
    Run fn_call as a free eth_call (no gas spent, no on-chain effect).
    Raises SimulationFailed with a decoded human-readable reason on revert.
    Returns the decoded return value on success.

    Always called before estimate_gas() and send_tx() to catch reverts early.

    Args:
        from_address: Override the sender address for simulation.
                      Defaults to JOEY_WALLET for backward compat.
    """
    sender = from_address or JOEY_WALLET
    try:
        return fn_call.call({"from": sender, "gas": gas})
    except ContractLogicError as exc:
        reason = decode_revert(exc)
        log.debug("Simulation failed: %s", reason)
        raise SimulationFailed(reason) from exc
    except Exception as exc:
        raise SimulationFailed(f"eth_call error: {exc}") from exc


# ── estimate_gas() ────────────────────────────────────────────────────────────
def estimate_gas(fn_call, from_address: str | None = None, value: int = 0) -> int:
    """
    Estimate gas for fn_call. Raises SimulationFailed if estimation fails
    (which almost always means the TX would revert on-chain).

    Args:
        from_address: Override the sender address. Defaults to JOEY_WALLET.
        value: Native PLS value for payable functions (in wei).
    """
    sender = from_address or JOEY_WALLET
    params: dict = {"from": sender}
    if value > 0:
        params["value"] = value
    try:
        return fn_call.estimate_gas(params)
    except ContractLogicError as exc:
        reason = decode_revert(exc)
        raise SimulationFailed(f"Gas estimation failed (would revert): {reason}") from exc
    except Exception as exc:
        raise SimulationFailed(f"Gas estimation error: {exc}") from exc
