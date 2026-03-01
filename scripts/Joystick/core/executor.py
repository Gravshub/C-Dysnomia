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
from .chain import w3_submit
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

    Returns:
        TxReceipt on success, None on dry_run
    Raises:
        SimulationFailed if eth_call predicts revert
        GasTooHigh if gas price exceeds ceiling
        AssertionError if TX reverts on-chain
    """
    log.info("→ %s", label)

    # Step 1: eth_call simulation (free — always run unless skip_simulate)
    if not skip_simulate:
        try:
            result = simulate(fn_call)
            log.debug("  Simulation OK: %s", result)
        except SimulationFailed as exc:
            log.error("  Simulation FAILED: %s", exc)
            raise

    if dry_run:
        log.info("  [dry-run] TX not sent: %s", label)
        return None

    if wallet.account is None:
        raise EnvironmentError("No wallet loaded — set DYSNOMIA_PRIVATE_KEY")

    # Step 2: Gas price ceiling
    gas_price = w3_submit.eth.gas_price
    if gas_price > GAS_PRICE_CEIL:
        raise GasTooHigh(
            f"Gas price {gas_price / 1e9:.1f} Gwei > ceiling "
            f"{GAS_PRICE_CEIL / 1e9:.0f} Gwei — skipping cycle"
        )

    # Step 3: estimate_gas (abort if fails)
    gas_est = estimate_gas(fn_call)
    gas_limit = int(gas_est * gas_mult)
    cost_pls = gas_est * gas_price / 1e18
    log.info("  Gas: %d  Gwei: %.2f  Cost: %.4f PLS", gas_est, gas_price / 1e9, cost_pls)

    # Step 4: Build TX with local nonce
    tx_params: dict[str, Any] = {
        "from":     JOEY_WALLET,
        "nonce":    wallet.next_nonce(),
        "gas":      gas_limit,
        "gasPrice": gas_price,
        "chainId":  CHAIN_ID,
    }
    if value > 0:
        tx_params["value"] = value

    tx = fn_call.build_transaction(tx_params)

    # Step 5: Sign, submit, wait
    signed  = wallet.account.sign_transaction(tx)
    tx_hash = w3_submit.eth.send_raw_transaction(signed.raw_transaction)
    log.info("  TX: 0x%s", tx_hash.hex())

    try:
        receipt = w3_submit.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    except TimeExhausted:
        log.error("  Receipt timeout — TX 0x%s may still be pending", tx_hash.hex())
        raise

    status = receipt["status"]
    log.info(
        "  %s  Block: %d  Gas used: %d",
        "✓ OK" if status == 1 else "✗ REVERTED",
        receipt["blockNumber"],
        receipt["gasUsed"],
    )

    assert status == 1, f"{label} REVERTED — tx: 0x{tx_hash.hex()}"

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
) -> TxReceipt | None:
    """
    Approve spender to spend amount of token_contract.
    Skips the TX if allowance is already sufficient (idempotent).
    """
    from .chain import safe
    current = safe(token_contract, "allowance", JOEY_WALLET, spender) or 0
    if current >= amount:
        log.debug("  Allowance sufficient (%.4f) — skipping approve", current / 1e18)
        return None
    return send_tx(
        token_contract.functions.approve(spender, amount),
        f"Approve {label}",
        dry_run=dry_run,
    )
