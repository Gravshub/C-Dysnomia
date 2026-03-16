"""
executor.py — Universal TX sender.

Pipeline for every on-chain write in Joystick:
  1. eth_call simulation      — catches reverts for free
  2. Gas price ceiling check  — skips congested cycles
  3. estimate_gas()           — aborts if TX would revert
  4. Build TX with local nonce — no chain round-trips mid-cycle
  5. Sign, submit, wait, verify receipt
  6. Parse Transfer events    — log exact amounts received

Established from tx_lau_arb.py send_tx() and tx_full_beat_flow.py send_tx() patterns.
"""
import time
import logging
from typing import Any

from web3.types import TxReceipt
from web3.exceptions import TimeExhausted

from .config import JOEY_WALLET, CHAIN_ID, GAS_MULT, GAS_PRICE_CEIL
from .chain import w3_submit, get_submit_pool
from .simulator import simulate, estimate_gas, SimulationFailed, GasTooHigh
from . import wallet

log = logging.getLogger(__name__)

# ERC20 Transfer event signature (keccak256)
TRANSFER_SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def send_tx(
    fn_call,
    label: str,
    *,
    dry_run: bool = False,
    gas_mult: float = GAS_MULT,
    value: int = 0,
    skip_simulate: bool = False,
    wallet_ctx=None,
) -> TxReceipt | None:
    """
    Universal TX sender. Always simulates before sending.

    Args:
        fn_call:       Web3 contract function call object
        label:         Human-readable name for logging
        dry_run:       If True, simulate only — no TX sent
        gas_mult:      Safety multiplier on gas estimate (default 1.3x)
        value:         Native PLS value to send with TX (for payable functions)
        skip_simulate: Skip eth_call pre-check (use only if .call() would fail
                       due to msg.value or state requirements)
        wallet_ctx:    Optional WalletConfig for multi-wallet support.
                       If None, uses Joey's wallet (backward compat).

    Returns:
        TxReceipt on success, None on dry_run
    Raises:
        SimulationFailed if eth_call predicts revert
        GasTooHigh if gas price exceeds ceiling
        AssertionError if TX reverts on-chain
    """
    # Resolve wallet context
    if wallet_ctx is not None:
        tx_from = wallet_ctx.address
        tx_account = wallet_ctx.account
    else:
        tx_from = JOEY_WALLET
        tx_account = wallet.account

    log.info("→ %s [%s]", label, tx_from[:10])

    # Step 1: eth_call simulation (free — always run unless skip_simulate)
    if not skip_simulate:
        try:
            result = simulate(fn_call, from_address=tx_from)
            log.debug("  Simulation OK: %s", result)
        except SimulationFailed as exc:
            log.error("  Simulation FAILED: %s", exc)
            raise

    if dry_run:
        log.info("  [dry-run] TX not sent: %s", label)
        return None

    if tx_account is None:
        raise EnvironmentError("No wallet loaded — set DYSNOMIA_PRIVATE_KEY")

    # Step 2: Gas price ceiling
    gas_price = get_submit_pool().call(lambda w3: w3.eth.gas_price)
    if gas_price > GAS_PRICE_CEIL:
        raise GasTooHigh(
            f"Gas price {gas_price / 1e9:.1f} Gwei > ceiling "
            f"{GAS_PRICE_CEIL / 1e9:.0f} Gwei — skipping cycle"
        )

    # Step 3: estimate_gas (abort if fails)
    gas_est = estimate_gas(fn_call, from_address=tx_from, value=value)
    gas_limit = int(gas_est * gas_mult)
    cost_pls = gas_est * gas_price / 1e18
    log.info("  Gas: %d  Gwei: %.2f  Cost: %.4f PLS", gas_est, gas_price / 1e9, cost_pls)

    # Step 4: Build TX with local nonce
    # Use wallet_ctx's nonce if available, else fall back to Joey's global nonce
    if wallet_ctx is not None:
        from .wallet_manager import WalletNonce as _WN
        # wallet_ctx doesn't carry its own nonce tracker — use the global one
        # The WalletManager handles nonce tracking externally
        nonce = wallet.next_nonce()  # fallback
    else:
        nonce = wallet.next_nonce()

    tx_params: dict[str, Any] = {
        "from":     tx_from,
        "nonce":    nonce,
        "gas":      gas_limit,
        "gasPrice": gas_price,
        "chainId":  CHAIN_ID,
    }
    if value > 0:
        tx_params["value"] = value

    tx = fn_call.build_transaction(tx_params)

    # Step 5: Sign, submit via pool (auto-retry + failover + privacy tier)
    signed  = tx_account.sign_transaction(tx)
    pool = get_submit_pool()
    tx_hash_hex = pool.send_raw(signed.raw_transaction)
    if tx_hash_hex is None:
        # TX already in mempool — try to get receipt anyway
        tx_hash_hex = signed.hash.hex()
    log.info("  TX: 0x%s", tx_hash_hex)

    # Wait for receipt — use read pool (reliable indexing) not submit pool
    from .chain import get_read_pool
    tx_hash_bytes = bytes.fromhex(tx_hash_hex.replace("0x", ""))
    try:
        receipt = get_read_pool().call(
            lambda w3: w3.eth.wait_for_transaction_receipt(tx_hash_bytes, timeout=300)
        )
    except TimeExhausted:
        log.error("  Receipt timeout — TX 0x%s may still be pending", tx_hash_hex)
        raise

    status = receipt["status"]
    log.info(
        "  %s  Block: %d  Gas used: %d",
        "✓ OK" if status == 1 else "✗ REVERTED",
        receipt["blockNumber"],
        receipt["gasUsed"],
    )

    assert status == 1, f"{label} REVERTED — tx: 0x{tx_hash_hex}"

    # Step 6: Log Transfer events for exact amounts
    _log_transfers(receipt)

    return receipt


def _log_transfers(receipt: TxReceipt) -> None:
    """Parse ERC20 Transfer events from receipt and log exact amounts moved."""
    for log_entry in receipt.get("logs", []):
        topics = log_entry.get("topics", [])
        if not topics:
            continue
        sig = topics[0].hex() if hasattr(topics[0], "hex") else topics[0]
        if sig.lower() == TRANSFER_SIG[2:].lower() and len(topics) >= 3:
            try:
                from_addr = "0x" + topics[1].hex()[-40:]
                to_addr   = "0x" + topics[2].hex()[-40:]
                amount    = int(log_entry["data"].hex(), 16)
                log.debug(
                    "  Transfer: %s → %s  amount: %.6f",
                    from_addr[:10], to_addr[:10], amount / 1e18
                )
            except Exception:
                pass


def approve_if_needed(
    token_contract,
    spender: str,
    amount: int,
    label: str,
    *,
    dry_run: bool = False,
    wallet_ctx=None,
) -> TxReceipt | None:
    """
    Approve spender to spend amount of token_contract.
    Skips the TX if allowance is already sufficient (idempotent).
    """
    from .chain import safe
    owner_addr = wallet_ctx.address if wallet_ctx else JOEY_WALLET
    current = safe(token_contract, "allowance", owner_addr, spender) or 0
    if current >= amount:
        log.debug("  Allowance sufficient (%.4f) — skipping approve", current / 1e18)
        return None
    return send_tx(
        token_contract.functions.approve(spender, amount),
        f"Approve {label}",
        dry_run=dry_run,
        wallet_ctx=wallet_ctx,
    )
