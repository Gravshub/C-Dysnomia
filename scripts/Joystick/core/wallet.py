"""
wallet.py — Account loader and local nonce tracker.

Local nonce management avoids re-fetching from chain between consecutive TXs in a cycle,
preventing "nonce already used" races when multiple TXs are queued back-to-back.

Usage:
    from Joystick.core.wallet import account, next_nonce, pls_balance
"""
import os
import logging
from web3 import Web3
from eth_account import Account as EthAccount
from eth_account.signers.local import LocalAccount

from .config import JOEY_WALLET, CHAIN_ID
from .chain import w3_submit, w3_read, get_submit_pool, get_read_pool

log = logging.getLogger(__name__)

# ── Account ───────────────────────────────────────────────────────────────────
def _load_account() -> LocalAccount:
    key = os.getenv("DYSNOMIA_PRIVATE_KEY", "")
    if not key:
        raise EnvironmentError("DYSNOMIA_PRIVATE_KEY not set. Run: source .env")
    acct = EthAccount.from_key(key)
    if acct.address.lower() != JOEY_WALLET.lower():
        raise ValueError(
            f"Key resolves to {acct.address}, expected {JOEY_WALLET}. "
            "Check DYSNOMIA_PRIVATE_KEY in .env"
        )
    log.info("Wallet loaded: %s", acct.address)
    return acct

# Module-level account — loaded once, cached for the process lifetime
try:
    account: LocalAccount = _load_account()
except EnvironmentError:
    account = None  # Dry-run / read-only mode — no key set
    log.warning("No DYSNOMIA_PRIVATE_KEY — wallet in read-only mode (dry-run only)")

# ── Local nonce tracker ───────────────────────────────────────────────────────
_nonce: int | None = None

def reset_nonce() -> None:
    """Force a fresh nonce fetch from chain. Call at start of each cycle."""
    global _nonce
    _nonce = None

def next_nonce() -> int:
    """
    Return the next nonce to use, incrementing the local counter.
    Fetches from chain on first call or after reset_nonce().
    Never re-fetches mid-cycle — safe for back-to-back TXs.
    """
    global _nonce
    if _nonce is None:
        _nonce = get_submit_pool().call(
            lambda w3: w3.eth.get_transaction_count(JOEY_WALLET, "pending"))
        log.debug("Nonce fetched from chain: %d", _nonce)
    n = _nonce
    _nonce += 1
    return n

def peek_nonce() -> int:
    """Read current nonce without incrementing."""
    global _nonce
    if _nonce is None:
        _nonce = get_submit_pool().call(
            lambda w3: w3.eth.get_transaction_count(JOEY_WALLET, "pending"))
    return _nonce

# ── Balance helpers ───────────────────────────────────────────────────────────
def pls_balance() -> int:
    """Native PLS balance in wei."""
    return get_read_pool().call(lambda w3: w3.eth.get_balance(JOEY_WALLET))

def fmt_pls(wei: int) -> str:
    """Format wei as human-readable PLS string."""
    return f"{wei / 1e18:.4f} PLS"
