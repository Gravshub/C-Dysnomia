"""
anvil_helpers.py — Anvil fork state manipulation utilities.

Provides functions to:
  - Communicate with Anvil's special RPC methods
  - Fund addresses with PLS
  - Impersonate any address
  - Manipulate ERC20 balances via storage slots
  - Snapshot/revert for test isolation
  - Skew Uniswap V2 pair reserves for arb testing
"""
import requests
import logging
from web3 import Web3

log = logging.getLogger(__name__)

ANVIL_URL = "http://127.0.0.1:8545"


def anvil_rpc(method: str, params: list | None = None, url: str = ANVIL_URL) -> dict:
    """Raw JSON-RPC call to Anvil."""
    r = requests.post(url, json={
        "jsonrpc": "2.0", "id": 1,
        "method": method,
        "params": params or [],
    }, timeout=10)
    data = r.json()
    if "error" in data:
        log.warning("Anvil RPC error: %s → %s", method, data["error"])
    return data


# ── Account Management ──────────────────────────────────────────────────────

def set_balance(addr: str, wei: int, url: str = ANVIL_URL) -> dict:
    """Set native PLS balance for any address."""
    return anvil_rpc("anvil_setBalance", [addr, hex(wei)], url)


def impersonate(addr: str, url: str = ANVIL_URL) -> dict:
    """Allow sending TXs as `addr` without private key."""
    return anvil_rpc("anvil_impersonateAccount", [addr], url)


def stop_impersonate(addr: str, url: str = ANVIL_URL) -> dict:
    """Stop impersonating address."""
    return anvil_rpc("anvil_stopImpersonatingAccount", [addr], url)


# ── Block Control ───────────────────────────────────────────────────────────

def mine_block(url: str = ANVIL_URL) -> dict:
    """Mine a single block."""
    return anvil_rpc("evm_mine", [], url)


def mine_blocks(n: int, url: str = ANVIL_URL) -> None:
    """Mine N blocks."""
    for _ in range(n):
        mine_block(url)


# ── Snapshot / Revert ───────────────────────────────────────────────────────

def snapshot(url: str = ANVIL_URL) -> str:
    """Take EVM snapshot, return snapshot ID."""
    return anvil_rpc("evm_snapshot", [], url)["result"]


def revert(snap_id: str, url: str = ANVIL_URL) -> dict:
    """Revert to a previous snapshot."""
    return anvil_rpc("evm_revert", [snap_id], url)


# ── Storage Manipulation ───────────────────────────────────────────────────

def set_storage(addr: str, slot: str, value: str, url: str = ANVIL_URL) -> dict:
    """Set arbitrary storage slot. slot and value are hex strings."""
    # Anvil expects 32-byte padded hex for both
    slot_padded = "0x" + slot.replace("0x", "").zfill(64)
    val_padded = "0x" + value.replace("0x", "").zfill(64)
    return anvil_rpc("anvil_setStorageAt", [addr, slot_padded, val_padded], url)


def set_erc20_balance(
    token: str,
    holder: str,
    amount: int,
    balance_slot: int = 0,
    url: str = ANVIL_URL,
) -> None:
    """
    Set ERC20 balance for a holder by writing to the balanceOf mapping slot.

    Standard Solidity mapping storage: keccak256(abi.encode(holder, slot))
    The `balance_slot` is the storage slot index of the `balanceOf` mapping
    in the token contract. Common values:
      - OpenZeppelin ERC20: slot 0 (balances) or slot 51 (upgradeable)
      - Vyper: varies
      - Dysnomia tokens: typically slot 0 or 1

    If this doesn't work for a specific token, use the brute-force approach:
    try slots 0-10 and check which one changes balanceOf.
    """
    # keccak256(abi.encode(address, uint256))
    encoded = (
        bytes.fromhex(holder.replace("0x", "").zfill(64)) +
        balance_slot.to_bytes(32, "big")
    )
    storage_key = Web3.keccak(encoded).hex()
    value_hex = hex(amount)
    set_storage(token, storage_key, value_hex, url)


def find_balance_slot(token: str, holder: str, w3: Web3, max_slot: int = 20) -> int | None:
    """
    Brute-force find the storage slot for balanceOf mapping.
    Sets a known balance, reads back via balanceOf, checks if it matches.
    Returns the slot number or None if not found.
    """
    test_amount = 123456789 * 10**18
    original_balance = w3.eth.call({
        "to": Web3.to_checksum_address(token),
        "data": "0x70a08231" + holder.lower().replace("0x", "").zfill(64),
    })

    for slot in range(max_slot):
        snap_id = snapshot()
        try:
            set_erc20_balance(token, holder, test_amount, balance_slot=slot)
            result = w3.eth.call({
                "to": Web3.to_checksum_address(token),
                "data": "0x70a08231" + holder.lower().replace("0x", "").zfill(64),
            })
            read_back = int(result.hex(), 16)
            if read_back == test_amount:
                revert(snap_id)
                return slot
        except Exception:
            pass
        revert(snap_id)

    return None


# ── Uniswap V2 Reserve Manipulation ────────────────────────────────────────

def skew_v2_reserves(
    pair_addr: str,
    new_reserve0: int,
    new_reserve1: int,
    url: str = ANVIL_URL,
) -> None:
    """
    Directly set Uniswap V2 pair reserves by writing to storage slot 8.

    Uniswap V2 pair storage layout:
      slot 0-7: various (factory, token0, token1, etc.)
      slot 8: packed (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast)

    WARNING: This does NOT update the pair's token balances — only the cached reserves.
    For a complete manipulation, also transfer tokens to/from the pair and call sync().
    For testing arb detection, skewing reserves is sufficient since simulate()
    reads reserves via getReserves() which reads slot 8.
    """
    import time
    ts = int(time.time()) & 0xFFFFFFFF  # uint32

    # Pack: reserve0 (112 bits) | reserve1 (112 bits) | timestamp (32 bits)
    # Storage is little-endian packed: timestamp is highest bits
    packed = (ts << 224) | (new_reserve1 << 112) | new_reserve0
    set_storage(pair_addr, "0x08", hex(packed), url)


def read_reserves(pair_addr: str, w3: Web3) -> tuple[int, int, int]:
    """Read current reserves from a Uniswap V2 pair."""
    pair = w3.eth.contract(
        address=Web3.to_checksum_address(pair_addr),
        abi=[{
            "constant": True, "inputs": [], "name": "getReserves",
            "outputs": [
                {"name": "", "type": "uint112"},
                {"name": "", "type": "uint112"},
                {"name": "", "type": "uint32"},
            ],
            "type": "function",
        }],
    )
    return pair.functions.getReserves().call()


# ── Compound Helpers ────────────────────────────────────────────────────────

def setup_joey_funded(joey_addr: str, pls_amount: int = 2_000_000, url: str = ANVIL_URL):
    """Fund Joey and impersonate him."""
    set_balance(joey_addr, pls_amount * 10**18, url)
    impersonate(joey_addr, url)
    log.info("Joey funded with %d PLS and impersonated", pls_amount)


def setup_tgsv8_funded(tgsv8_addr: str, pls_amount: int = 10_000, url: str = ANVIL_URL):
    """Fund TGSv8 with native PLS for operations."""
    set_balance(tgsv8_addr, pls_amount * 10**18, url)
    log.info("TGSv8 funded with %d PLS", pls_amount)


def deposit_token_to_tgsv8(
    token: str,
    tgsv8: str,
    amount: int,
    holder: str,
    w3: Web3,
    url: str = ANVIL_URL,
) -> None:
    """
    Transfer ERC20 tokens to TGSv8 by impersonating a holder.
    Used to seed TGSv8 with OZZY, WM, AFFECTION, etc. for testing.
    """
    impersonate(holder, url)
    # Build transfer TX
    tx = {
        "from": Web3.to_checksum_address(holder),
        "to": Web3.to_checksum_address(token),
        "data": (
            "0xa9059cbb"  # transfer(address,uint256)
            + tgsv8.lower().replace("0x", "").zfill(64)
            + hex(amount)[2:].zfill(64)
        ),
        "gas": 100_000,
        "gasPrice": w3.eth.gas_price,
    }
    tx_hash = w3.eth.send_transaction(tx)
    w3.eth.wait_for_transaction_receipt(tx_hash)
    stop_impersonate(holder, url)
