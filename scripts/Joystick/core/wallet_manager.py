"""
wallet_manager.py — Multi-wallet configuration, per-wallet nonce tracking, sweep logic.

3-Wallet Pipeline:
  Joey   — identity + orchestrator (chatAndClaim, Beat, LAU, admin)
  Minter — production (BuyWith*, mintWM, claimTreasury, batchMintAndClaim)
  Seller — liquidation + arb (atomicArb, swapExact, swapTokensForNative)

All three wallets operate on TGSv8 via its built-in auth system (setAuth).
Minter produces tokens into TGSv8's balance. Seller sells them out.

Graceful degradation: If MINTER_PRIVATE_KEY or SELLER_PRIVATE_KEY is not set,
that wallet is disabled. Bot falls back to single-wallet mode (Joey only).
"""
import logging

from .log_names import get_logger
import os
from dataclasses import dataclass
from enum import Enum

from eth_account import Account as EthAccount
from eth_account.signers.local import LocalAccount
from web3 import Web3

from .config import JOEY_WALLET, CHAIN_ID

log = get_logger(__name__)


class WalletRole(Enum):
    JOEY   = "joey"
    MINTER = "minter"
    SELLER = "seller"


@dataclass
class WalletConfig:
    """Configuration for a single wallet in the pipeline."""
    role:        WalletRole
    address:     str               # checksum address
    private_key: str               # raw hex key
    gas_floor:   int               # in wei
    account:     LocalAccount      # eth_account signing object


class WalletNonce:
    """Per-wallet nonce tracker. Mirrors wallet.py pattern but per-instance."""

    def __init__(self, address: str, submit_pool):
        self.address = address
        self._submit_pool = submit_pool
        self._nonce: int | None = None

    def reset(self) -> None:
        """Force a fresh nonce fetch from chain next call."""
        self._nonce = None

    def next(self) -> int:
        """Return next nonce, incrementing local counter. Fetches from chain on first call."""
        if self._nonce is None:
            self._nonce = self._submit_pool.call(
                lambda w3: w3.eth.get_transaction_count(self.address, "pending"))
            log.debug("Nonce fetched for %s: %d", self.address[:10], self._nonce)
        n = self._nonce
        self._nonce += 1
        return n

    def peek(self) -> int:
        """Read current nonce without incrementing."""
        if self._nonce is None:
            self._nonce = self._submit_pool.call(
                lambda w3: w3.eth.get_transaction_count(self.address, "pending"))
        return self._nonce


class WalletManager:
    """
    Manages all 3 wallets in the pipeline.

    Loads wallet keys from env vars. Disabled wallets (missing keys) return None.
    Provides per-wallet nonce tracking, balance snapshots, and sweep logic.
    """

    def __init__(self):
        from .chain import get_submit_pool, get_read_pool

        self._submit_pool = get_submit_pool()
        self._read_pool = get_read_pool()
        self._nonces: dict[WalletRole, WalletNonce] = {}

        # Joey — always loaded (required)
        self.joey = self._load_wallet(
            WalletRole.JOEY,
            "DYSNOMIA_PRIVATE_KEY",
            JOEY_WALLET,
            int(os.getenv("PLS_GAS_FLOOR", "100000")) * 10**18,
        )

        # Minter — optional
        self.minter = self._load_optional_wallet(
            WalletRole.MINTER,
            "MINTER_PRIVATE_KEY",
            os.getenv("MINTER_WALLET", ""),
            int(os.getenv("MINTER_GAS_FLOOR", "30000")) * 10**18,
        )

        # Seller — optional
        self.seller = self._load_optional_wallet(
            WalletRole.SELLER,
            "SELLER_PRIVATE_KEY",
            os.getenv("SELLER_WALLET", ""),
            int(os.getenv("SELLER_GAS_FLOOR", "30000")) * 10**18,
        )

        # Sweep config
        self._sweep_threshold = int(os.getenv("SWEEP_THRESHOLD", "500000")) * 10**18

        if not self.is_multi_wallet:
            log.warning("👤 Single-wallet mode — Minter/Seller not configured")

    @property
    def is_multi_wallet(self) -> bool:
        """True if at least one worker wallet is configured."""
        return self.minter is not None or self.seller is not None

    def _load_wallet(
        self, role: WalletRole, env_key: str, expected_address: str, gas_floor: int
    ) -> WalletConfig | None:
        """Load a required wallet from env."""
        key = os.getenv(env_key, "")
        if not key:
            return None
        acct = EthAccount.from_key(key)
        if expected_address and acct.address.lower() != expected_address.lower():
            log.warning(
                "%s key resolves to %s, expected %s",
                role.value, acct.address, expected_address,
            )
        config = WalletConfig(
            role=role,
            address=Web3.to_checksum_address(acct.address),
            private_key=key,
            gas_floor=gas_floor,
            account=acct,
        )
        self._nonces[role] = WalletNonce(config.address, self._submit_pool)
        log.info("👛 %s wallet loaded: %s", role.value.upper(), config.address)
        return config

    def _load_optional_wallet(
        self, role: WalletRole, env_key: str, expected_address: str, gas_floor: int
    ) -> WalletConfig | None:
        """Load an optional wallet — returns None if env var not set."""
        key = os.getenv(env_key, "")
        if not key:
            log.info("🏜️ %s not set — %s wallet disabled", env_key, role.value)
            return None
        acct = EthAccount.from_key(key)
        address = Web3.to_checksum_address(acct.address)
        if expected_address:
            expected = Web3.to_checksum_address(expected_address)
            if address.lower() != expected.lower():
                log.warning(
                    "%s key resolves to %s, expected %s",
                    role.value, address, expected,
                )
        config = WalletConfig(
            role=role,
            address=address,
            private_key=key,
            gas_floor=gas_floor,
            account=acct,
        )
        self._nonces[role] = WalletNonce(config.address, self._submit_pool)
        log.info("👛 %s wallet loaded: %s", role.value.upper(), config.address)
        return config

    def get_wallet(self, role: WalletRole) -> WalletConfig | None:
        """Get wallet config by role."""
        if role == WalletRole.JOEY:
            return self.joey
        elif role == WalletRole.MINTER:
            return self.minter
        elif role == WalletRole.SELLER:
            return self.seller
        return None

    def get_wallet_for_engine(self, engine_wallet_role: str) -> WalletConfig | None:
        """Get the appropriate wallet for an engine's wallet_role string.
        Falls back to Joey if the target wallet is not configured."""
        role_map = {
            "joey": WalletRole.JOEY,
            "minter": WalletRole.MINTER,
            "seller": WalletRole.SELLER,
        }
        role = role_map.get(engine_wallet_role, WalletRole.JOEY)
        wallet = self.get_wallet(role)
        if wallet is None:
            # Fall back to Joey in single-wallet mode
            return self.joey
        return wallet

    def get_nonce(self, role: WalletRole) -> WalletNonce | None:
        """Get nonce tracker for a wallet role."""
        return self._nonces.get(role)

    def reset_all_nonces(self) -> None:
        """Reset nonces for all active wallets."""
        for nonce in self._nonces.values():
            nonce.reset()

    def snapshot_all_balances(self) -> dict:
        """Get PLS balances for all active wallets in one shot."""
        result = {}
        wallets = [("joey", self.joey)]
        if self.minter:
            wallets.append(("minter", self.minter))
        if self.seller:
            wallets.append(("seller", self.seller))

        for name, w in wallets:
            if w is None:
                continue
            try:
                bal = self._read_pool.call(
                    lambda w3, addr=w.address: w3.eth.get_balance(addr))
                result[f"pls_{name}"] = bal
            except Exception:
                result[f"pls_{name}"] = 0
        return result

    def check_sweep(self) -> bool:
        """Check if Seller PLS balance exceeds sweep threshold."""
        if not self.seller:
            return False
        try:
            bal = self._read_pool.call(
                lambda w3: w3.eth.get_balance(self.seller.address))
            return bal > self._sweep_threshold
        except Exception:
            return False

    def execute_sweep(self, dry_run: bool = False) -> dict | None:
        """
        Sweep excess PLS from Seller to Joey.
        Seller keeps gas_floor amount, sends the rest.
        Returns TX receipt dict or None.
        """
        if not self.seller or not self.joey:
            return None

        try:
            bal = self._read_pool.call(
                lambda w3: w3.eth.get_balance(self.seller.address))
        except Exception:
            return None

        sweep_amount = bal - self.seller.gas_floor
        if sweep_amount <= 0:
            return None

        if dry_run:
            log.info("[dry-run] Would sweep %.4f PLS from Seller to Joey",
                     sweep_amount / 1e18)
            return None

        gas_price = self._submit_pool.call(lambda w3: w3.eth.gas_price)
        gas_limit = 21000  # Simple PLS transfer
        gas_cost = gas_price * gas_limit
        send_amount = sweep_amount - gas_cost
        if send_amount <= 0:
            return None

        nonce_tracker = self._nonces.get(WalletRole.SELLER)
        if not nonce_tracker:
            return None

        tx = {
            "to": self.joey.address,
            "value": send_amount,
            "gas": gas_limit,
            "gasPrice": gas_price,
            "nonce": nonce_tracker.next(),
            "chainId": CHAIN_ID,
        }

        signed = self.seller.account.sign_transaction(tx)
        tx_hash = self._submit_pool.send_raw(signed.raw_transaction)
        log.info("Sweep TX: 0x%s (%.4f PLS Seller → Joey)",
                 tx_hash, send_amount / 1e18)

        try:
            tx_hash_bytes = bytes.fromhex(tx_hash.replace("0x", ""))
            receipt = self._submit_pool.call(
                lambda w3: w3.eth.wait_for_transaction_receipt(tx_hash_bytes, timeout=120))
            if receipt["status"] == 1:
                log.info("Sweep OK: %.4f PLS transferred", send_amount / 1e18)
            else:
                log.error("Sweep REVERTED")
            return dict(receipt)
        except Exception as exc:
            log.error("Sweep receipt timeout: %s", exc)
            return None

    def wallet_status_lines(self) -> list[str]:
        """Return status lines for --wallet-status display."""
        lines = []
        wallets = [
            ("JOEY", self.joey),
            ("MINTER", self.minter),
            ("SELLER", self.seller),
        ]
        for label, w in wallets:
            if w is None:
                lines.append(f"  🏜️ {label:8s}  [NOT CONFIGURED]")
                continue
            try:
                bal = self._read_pool.call(
                    lambda w3, addr=w.address: w3.eth.get_balance(addr))
                bal_pls = bal / 1e18
            except Exception:
                bal_pls = 0.0
            nonce = self._nonces.get(w.role)
            nonce_val = nonce.peek() if nonce else "?"
            lines.append(
                f"  👛 {label:8s}  {w.address}  "
                f"{bal_pls:>12,.1f} PLS  nonce={nonce_val}"
            )
        return lines
