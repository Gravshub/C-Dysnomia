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

from .log_names import get_logger
from typing import Any

from web3.types import TxReceipt
from web3.exceptions import TimeExhausted

from .config import (
    JOEY_WALLET, CHAIN_ID, GAS_MULT, GAS_PRICE_CEIL,
    GAS_PRICE_FLOOR_MULT, GAS_PRIORITY_FEE,
)
from .chain import w3_submit, get_submit_pool
from .simulator import simulate, estimate_gas, SimulationFailed, GasTooHigh
from . import wallet

log = get_logger(__name__)

# ── EIP-1559 Gas Strategy ────────────────────────────────────────────────────
# PulseChain supports EIP-1559 (Type 2) transactions. Legacy gasPrice TXs
# overpay when base fee drops and underpay when it spikes. EIP-1559 sets a
# ceiling (maxFeePerGas) and a tip (maxPriorityFeePerGas). You only pay
# base_fee + tip; the ceiling protects against block-to-block variance.
#
# Bot recon (2026-04-02) showed we were paying 106% above network floor:
#   - BOT3 (Loop Machine): avg 811K Beats (8% above floor) — 0% revert rate
#   - BOT2 (Farmer):       avg 1.06M Beats (41% above floor) — 0% revert rate
#   - JOYSTICK (old):      avg 1.54M Beats (106% above floor) — 2% revert rate
# PulseChain has no MEV infrastructure. Floor + small fixed tip is sufficient.
#
# Tiers adjust the priority tip multiplier above the fixed base tip:
#   slow:     1x fixed tip    — lands in 3-5 blocks
#   standard: 2x fixed tip    — lands in 1-3 blocks
#   fast:     4x fixed tip    — next block
#   urgent:   8x fixed tip    — priority inclusion
#
# maxFeePerGas = baseFee * GAS_PRICE_FLOOR_MULT + priority_fee
# This gives ~12% headroom above base for block-to-block variance.

_GAS_TIER_TIP_MULT = {"slow": 1, "standard": 2, "fast": 4, "urgent": 8}

# Fixed priority fee in Impulses (wei), configured via GAS_PRIORITY_FEE.
# Default 50K Beats — BOT3 proves sub-100K tips get included on PulseChain.
_PRIORITY_FEE_WEI = GAS_PRIORITY_FEE * 10**9  # Convert Beats → Impulses


def build_gas_params(tier: str = "fast", w3=None) -> dict:
    """Return EIP-1559 Type 2 gas parameters for the given speed tier.

    Uses baseFeePerGas from latest block header. Falls back to legacy
    eth_gasPrice if baseFeePerGas is unavailable (with warning).
    """
    _w3 = w3 or get_submit_pool().call(lambda w: w)

    try:
        block = _w3.eth.get_block("latest")
        base_fee = block["baseFeePerGas"]
    except (KeyError, Exception) as exc:
        # Fallback: EIP-1559 not available or block read failed
        log.warning("build_gas_params: baseFeePerGas unavailable (%s), falling back to eth_gasPrice", exc)
        gas_price = _w3.eth.gas_price
        return {
            "maxFeePerGas": gas_price,
            "maxPriorityFeePerGas": min(gas_price // 10, _PRIORITY_FEE_WEI),
            "type": 2,
        }

    tip_mult = _GAS_TIER_TIP_MULT.get(tier, 4)
    priority_fee = _PRIORITY_FEE_WEI * tip_mult

    # maxFeePerGas: base_fee * floor_mult + priority_fee
    # GAS_PRICE_FLOOR_MULT default 1.12 gives 12% headroom above current base
    max_fee = int(base_fee * GAS_PRICE_FLOOR_MULT) + priority_fee

    return {
        "maxFeePerGas": max_fee,
        "maxPriorityFeePerGas": priority_fee,
        "type": 2,
    }

# ERC20 Transfer event signature (keccak256)
TRANSFER_SIG = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _reset_nonce_for(wallet_ctx) -> None:
    """Force nonce re-fetch from chain for the wallet that just failed."""
    if wallet_ctx is not None and hasattr(wallet_ctx, 'nonce_tracker') and wallet_ctx.nonce_tracker:
        wallet_ctx.nonce_tracker.reset()
        log.info("  Nonce reset for %s (will re-fetch from chain)", wallet_ctx.address[:10])
    else:
        wallet.reset_nonce()
        log.info("  Nonce reset for Joey (will re-fetch from chain)")


def submit_tx_nowait(
    fn_call,
    label: str,
    *,
    dry_run: bool = False,
    gas_mult: float = GAS_MULT,
    value: int = 0,
    skip_simulate: bool = False,
    fixed_gas: int = 0,
    gas_tier: str = "fast",
    wallet_ctx=None,
) -> str | None:
    """
    Sign and submit a TX without waiting for receipt. Returns tx_hash hex string.

    Use this for back-to-back TX pipelines where you need to submit multiple
    TXs with sequential nonces before waiting for receipts. This prevents MEV
    bots from sniping state between TXs (e.g., E2 primeGibs → mintLPAndSell).

    Args:
        fixed_gas: If >0, skip estimate_gas and use this as gas limit directly.
                   Use when the TX depends on state from a prior unconfirmed TX.

    Returns None on dry_run. Raises on simulation failure or gas ceiling.
    """
    if wallet_ctx is not None:
        tx_from = wallet_ctx.address
        tx_account = wallet_ctx.account
    else:
        tx_from = JOEY_WALLET
        tx_account = wallet.account

    log.info("📤 %s [%s] (no-wait)", label, tx_from[:10])

    if not skip_simulate:
        try:
            simulate(fn_call, from_address=tx_from)
        except SimulationFailed as exc:
            log.error("  Simulation FAILED: %s", exc)
            raise

    if dry_run:
        log.info("  [dry-run] TX not sent: %s", label)
        return None

    if tx_account is None:
        raise EnvironmentError("No wallet loaded — set DYSNOMIA_PRIVATE_KEY")

    if fixed_gas > 0:
        gas_limit = fixed_gas
        log.info("  ⛽ Using fixed gas limit: %d (skipping estimate)", gas_limit)
    else:
        gas_est = estimate_gas(fn_call, from_address=tx_from, value=value)
        gas_limit = int(gas_est * gas_mult)
    eip1559 = build_gas_params(gas_tier)

    if eip1559["maxFeePerGas"] > GAS_PRICE_CEIL:
        raise GasTooHigh(
            f"maxFeePerGas {eip1559['maxFeePerGas'] / 1e9:.1f} Beats > ceiling"
        )

    if wallet_ctx is not None and hasattr(wallet_ctx, 'nonce_tracker') and wallet_ctx.nonce_tracker:
        nonce = wallet_ctx.nonce_tracker.next()
    else:
        nonce = wallet.next_nonce()

    tx_params: dict[str, Any] = {
        "from": tx_from, "nonce": nonce, "gas": gas_limit,
        "chainId": CHAIN_ID, **eip1559,
    }
    if value > 0:
        tx_params["value"] = value

    tx = fn_call.build_transaction(tx_params)
    signed = tx_account.sign_transaction(tx)
    pool = get_submit_pool()
    tx_hash_hex = pool.send_raw(signed.raw_transaction)
    if tx_hash_hex is None:
        tx_hash_hex = signed.hash.hex()
    log.info("  TX: 0x%s (submitted, not waiting)", tx_hash_hex)
    return tx_hash_hex


def send_tx(
    fn_call,
    label: str,
    *,
    dry_run: bool = False,
    gas_mult: float = GAS_MULT,
    value: int = 0,
    skip_simulate: bool = False,
    fixed_gas: int = 0,
    gas_tier: str = "fast",
    wallet_ctx=None,
    depends_on_receipt: TxReceipt | None = None,
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
        fixed_gas:     Use this gas limit instead of estimate_gas (for when
                       estimate would fail due to read RPC lag after approve)
        wallet_ctx:    Optional WalletConfig for multi-wallet support.
                       If None, uses Joey's wallet (backward compat).
        depends_on_receipt: If set, wait for this dependency TX to confirm
                       before simulating. Ensures sequential operations
                       (e.g., prime → sell) don't simulate against pre-TX state.

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

    log.info("📤 %s [%s]", label, tx_from[:10])

    # Step 0: Wait for dependency TX if specified
    if depends_on_receipt is not None:
        dep_block = depends_on_receipt.get("blockNumber", 0)
        if dep_block:
            log.debug("  Dependency TX confirmed at block %d, proceeding", dep_block)

    # Step 1: eth_call simulation (free — always run unless skip_simulate)
    sim_block = 0
    if not skip_simulate:
        try:
            from .chain import w3_read
            sim_block = w3_read.eth.block_number
            result = simulate(fn_call, from_address=tx_from)
            log.debug("  Simulation OK at block %d: %s", sim_block, result)
        except SimulationFailed as exc:
            log.error("  Simulation FAILED: %s", exc)
            raise

    if dry_run:
        log.info("  [dry-run] TX not sent: %s", label)
        return None

    if tx_account is None:
        raise EnvironmentError("No wallet loaded — set DYSNOMIA_PRIVATE_KEY")

    # Step 1b: Block freshness check — re-simulate if state advanced >2 blocks
    if sim_block > 0 and not skip_simulate:
        try:
            from .chain import w3_read
            current_block = w3_read.eth.block_number
            if current_block > sim_block + 2:
                log.warning("  Stale sim: simulated at block %d, now at %d, re-simulating",
                            sim_block, current_block)
                simulate(fn_call, from_address=tx_from)
                sim_block = current_block
                log.debug("  Re-simulation OK at block %d", sim_block)
        except SimulationFailed as exc:
            log.error("  Re-simulation FAILED (state changed): %s", exc)
            raise
        except Exception:
            pass  # Non-critical — proceed with original sim result

    # Step 2: estimate_gas (abort if fails) — or use fixed_gas
    if fixed_gas > 0:
        gas_est = fixed_gas
        gas_limit = fixed_gas
        log.info("  ⛽ Using fixed gas limit: %d (skipping estimate)", fixed_gas)
    else:
        gas_est = estimate_gas(fn_call, from_address=tx_from, value=value)
        gas_limit = int(gas_est * gas_mult)

    # Step 2b: Build EIP-1559 gas params
    eip1559 = build_gas_params(gas_tier)

    # Step 2c: Gas price ceiling check (against actual maxFeePerGas)
    if eip1559["maxFeePerGas"] > GAS_PRICE_CEIL:
        raise GasTooHigh(
            f"maxFeePerGas {eip1559['maxFeePerGas'] / 1e9:.1f} Beats > ceiling "
            f"{GAS_PRICE_CEIL / 1e9:.0f} Beats — skipping cycle"
        )
    cost_pls = gas_est * eip1559["maxFeePerGas"] / 1e18
    log.info("  ⛽ Gas: est=%d  limit=%d (%.1fx)  maxFee=%.0f Beats  Cost≤%.4f PLS",
             gas_est, gas_limit, gas_mult, eip1559["maxFeePerGas"] / 1e9, cost_pls)

    # Step 4: Build TX with local nonce + EIP-1559 Type 2
    if wallet_ctx is not None and hasattr(wallet_ctx, 'nonce_tracker') and wallet_ctx.nonce_tracker:
        nonce = wallet_ctx.nonce_tracker.next()
    else:
        nonce = wallet.next_nonce()

    tx_params: dict[str, Any] = {
        "from":     tx_from,
        "nonce":    nonce,
        "gas":      gas_limit,
        "chainId":  CHAIN_ID,
        **eip1559,  # maxFeePerGas + maxPriorityFeePerGas + type=2
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

    # Wait for receipt with resubmit on drop.
    # PulseChain intermittently drops TXs from mempool. If the TX isn't mined
    # after 30s and the nonce hasn't advanced, resubmit with bumped priority.
    import time as _time
    from .chain import w3_read
    _w3_submit_direct = pool.get_w3()
    tx_hash_bytes = bytes.fromhex(tx_hash_hex.replace("0x", ""))
    receipt = None
    _resubmitted = False

    for _poll in range(24):  # 24 × 5s = 120s max
        _time.sleep(5)
        for _w3_check in [_w3_submit_direct, w3_read]:
            try:
                receipt = _w3_check.eth.get_transaction_receipt(tx_hash_bytes)
                if receipt:
                    break
            except Exception:
                pass
        if receipt:
            break

        # After 30s with no receipt, check if TX was dropped and resubmit once
        # with 50% higher priority fee to bump it through the mempool
        if _poll == 5 and not _resubmitted:
            try:
                cur_nonce = _w3_submit_direct.eth.get_transaction_count(tx_from)
            except Exception:
                cur_nonce = nonce
            if cur_nonce == nonce:
                log.warning("  TX not mined after 30s — rebuilding with 50%% higher priority")
                try:
                    bumped_eip = build_gas_params("urgent")
                    bumped_eip["maxPriorityFeePerGas"] = int(
                        bumped_eip["maxPriorityFeePerGas"] * 1.5
                    )
                    bumped_eip["maxFeePerGas"] = max(
                        bumped_eip["maxFeePerGas"],
                        bumped_eip["maxPriorityFeePerGas"] + 1,
                    )
                    bumped_tx = dict(tx)
                    bumped_tx.update(bumped_eip)
                    bumped_signed = tx_account.sign_transaction(bumped_tx)
                    new_hash = pool.send_raw(bumped_signed.raw_transaction)
                    if new_hash:
                        tx_hash_hex = new_hash
                        tx_hash_bytes = bytes.fromhex(
                            tx_hash_hex.replace("0x", "")
                        )
                        log.info("  Resubmitted (bumped): 0x%s", new_hash)
                    _resubmitted = True
                except Exception as resub_err:
                    err_s = str(resub_err).lower()
                    if "already known" in err_s:
                        log.info("  TX still in mempool (already known)")
                        _resubmitted = True
                    elif "nonce too low" in err_s:
                        log.info("  Nonce consumed — TX likely mined")
                    else:
                        log.warning("  Resubmit failed: %s", str(resub_err)[:80])

    if receipt is None:
        # Receipt not found after 120s — check if nonce advanced (TX mined but hash lost)
        on_chain_nonce = nonce
        for _w3_check in [_w3_submit_direct, w3_read]:
            try:
                n = _w3_check.eth.get_transaction_count(tx_from)
                on_chain_nonce = max(on_chain_nonce, n)
            except Exception:
                pass  # Can't check this RPC, try next
        if on_chain_nonce > nonce:
            log.warning("  Receipt not found but nonce advanced (%d->%d) -- TX mined (hash dropped by RPC)", nonce, on_chain_nonce)
            _reset_nonce_for(wallet_ctx)
            estimated_gas_cost = gas_limit * eip1559["maxFeePerGas"]
            log.warning("  Returning synthetic receipt (estimated gas: %d wei)", estimated_gas_cost)
            return {
                "status": 1,
                "transactionHash": type('', (), {"hex": lambda self: tx_hash_hex})(),
                "blockNumber": 0,
                "gasUsed": gas_limit,
                "effectiveGasPrice": eip1559["maxFeePerGas"],
                "_synthetic": True,
            }
        else:
            log.error("  Receipt timeout and nonce unchanged -- TX 0x%s dropped from mempool", tx_hash_hex)
            _reset_nonce_for(wallet_ctx)
            raise TimeExhausted(f"TX 0x{tx_hash_hex} dropped -- nonce {nonce} still pending")

    if receipt is None:
        return None

    status = receipt["status"]
    log.info(
        "  %s  Block: %d  Gas used: %d",
        "📦 OK" if status == 1 else "✗ REVERTED",
        receipt["blockNumber"],
        receipt["gasUsed"],
    )

    if status != 1:
        # On-chain revert: nonce was consumed, but reset to re-sync
        _reset_nonce_for(wallet_ctx)
        # Decode revert reason by replaying the TX via eth_call at the revert block
        revert_reason = _decode_onchain_revert(fn_call, tx_from, value, receipt)
        if revert_reason:
            log.warning("  Revert reason: %s", revert_reason)
        raise AssertionError(f"{label} REVERTED — tx: 0x{tx_hash_hex} — {revert_reason or 'unknown reason'}")

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


def _decode_onchain_revert(fn_call, tx_from: str, value: int, receipt: TxReceipt) -> str:
    """
    Replay a reverted TX via eth_call at the revert block to extract the reason.

    Decodes:
      - 0x08c379a0 = Error(string) — standard Solidity require/revert
      - 0x4e487b71 = Panic(uint256) — div by zero, overflow, etc.
      - Custom errors — logged as raw selector + params
    """
    from .simulator import decode_revert
    block_num = receipt.get("blockNumber", 0)
    if not block_num:
        return ""

    try:
        from .chain import w3_read
        call_params = {"from": tx_from, "gas": 5_000_000}
        if value > 0:
            call_params["value"] = value
        fn_call.call(call_params, block_identifier=block_num)
        return ""  # Didn't revert on replay — state-dependent failure
    except Exception as exc:
        try:
            return decode_revert(exc)
        except Exception:
            return f"undecoded: {str(exc)[:120]}"


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
