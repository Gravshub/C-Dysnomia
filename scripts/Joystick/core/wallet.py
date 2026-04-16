"""
wallet.py — Account loader and local nonce tracker.

Local nonce management avoids re-fetching from chain between consecutive TXs in a cycle,
preventing "nonce already used" races when multiple TXs are queued back-to-back.

Usage:
    from Joystick.core.wallet import account, next_nonce, pls_balance
"""
import os
import logging
import threading

from .log_names import get_logger
from web3 import Web3
from eth_account import Account as EthAccount
from eth_account.signers.local import LocalAccount

from .config import JOEY_WALLET, CHAIN_ID
from .chain import w3_submit, w3_read, get_submit_pool, get_read_pool

log = get_logger(__name__)

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
# Lock protects fetch-or-increment races when multi-wallet execution runs TXs
# concurrently via asyncio.gather() / ThreadPoolExecutor.
_nonce_lock = threading.Lock()

def reset_nonce() -> None:
    """Force a fresh nonce fetch from chain. Call at start of each cycle."""
    global _nonce
    with _nonce_lock:
        _nonce = None

def next_nonce() -> int:
    """
    Return the next nonce to use, incrementing the local counter.
    Fetches from chain on first call or after reset_nonce().
    Never re-fetches mid-cycle — safe for back-to-back TXs.
    """
    global _nonce
    with _nonce_lock:
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
    with _nonce_lock:
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


# ── Per-wallet nonce tracker (used by WalletManager) ──────────────────────────
class WalletNonce:
    """
    Per-wallet nonce tracker for multi-wallet mode.
    Same pattern as the module-level _nonce but per-instance.
    Used by wallet_manager.py — not by existing engine code.
    """

    def __init__(self, address: str, submit_pool=None):
        self.address = address
        self._submit_pool = submit_pool or get_submit_pool()
        self._nonce: int | None = None
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._nonce = None

    def next(self) -> int:
        with self._lock:
            if self._nonce is None:
                self._nonce = self._submit_pool.call(
                    lambda w3: w3.eth.get_transaction_count(self.address, "pending"))
                log.debug("WalletNonce(%s) fetched: %d", self.address[:10], self._nonce)
            n = self._nonce
            self._nonce += 1
            return n

    def peek(self) -> int:
        with self._lock:
            if self._nonce is None:
                self._nonce = self._submit_pool.call(
                    lambda w3: w3.eth.get_transaction_count(self.address, "pending"))
            return self._nonce
