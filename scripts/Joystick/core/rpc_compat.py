"""
rpc_compat.py — Drop-in RPC provider for standalone scripts.

Usage in standalone scripts:
    # INSTEAD OF:
    # w3 = Web3(Web3.HTTPProvider("https://rpc.pulsechain.com"))

    # DO:
    from Joystick.core.rpc_compat import w3, w3_read, w3_submit

Simple Web3 instances (no pool overhead) with basic connection fallback.
"""
from web3 import Web3

_READ_ENDPOINTS = [
    "https://rpc-pulsechain.g4mm4.io",
    "https://rpc.pulsechain.com",
    "https://pulsechain-rpc.publicnode.com",
    "https://rpc.pulsechainstats.com",
]

_SUBMIT_ENDPOINTS = [
    "https://rpc.pulsechain.com",
    "https://rpc-pulsechain.g4mm4.io",
    "https://pulsechain-rpc.publicnode.com",
]


def _connect(endpoints: list[str], timeout: int = 30) -> Web3:
    """Try each endpoint in order, return the first that responds."""
    for url in endpoints:
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": timeout}))
        try:
            w3.eth.block_number  # quick health check
            return w3
        except Exception:
            continue
    raise ConnectionError("All PulseChain RPCs unreachable")


w3_read   = _connect(_READ_ENDPOINTS, timeout=30)
w3_submit = _connect(_SUBMIT_ENDPOINTS, timeout=60)
w3 = w3_submit  # backward compat alias
