"""
dss.py — Engine 2: CEREAL (Silent GIBS Harvest via TGSv8+)

=== HISTORY ===
Originally used DysnomiaSelfSnipev4 (DSS) contract at 0x91Df693177eE5C81016d0B7c4c2052A7d229c031.
DSS called GIBS_LAU.Chat(text) + GIBS_LAU.Purchase(AFF, 1e18) × multiplier.
This worked but:
  - Spammed the VOID chat with every mint (Chat is mandatory in DSS)
  - Required 3+ separate TXs per cycle (mint → approve → swap → optionally addLP)
  - Front-running exposure between the sell TX and the LP TX
  - DSS needed GIBS and AFF pre-loaded into the contract

=== CURRENT (TGSv8+) ===
Uses TGSv8+ contract at 0xA5D7771f16204d26770657eac186A6167e69e736.
TGSv8+.harvestCycle() does the ENTIRE pipeline in ONE atomic TX:
  1. silentMint(N) — calls LAU.Purchase(payToken, 1e18) × N. No Chat, no VOID spam.
  2. Sell sellBps% of minted LAU → WPLS on DEX
  3. addLiquidity with remaining LAU + received WPLS
  4. Burn burnBps% of received LP tokens → 0x...369 (permanent floor)
  5. Sweep leftover tokens to owner (Joey)

Default: 45% sell (4500 bps), 90% LP burn (9000 bps), 17 LAU per cycle.
All percentages configurable via env vars (HARVEST_SELL_BPS, HARVEST_BURN_BPS, etc.).

=== DSS DEPRECATION NOTE ===
The old DSS contract (0x91Df...) is NOT used for minting anymore. It remains
available ONLY for broadcasting messages to the VOID chat via DSS.chat(text).
All minting revenue now flows through TGSv8+.

=== ECONOMICS ===
Per harvestCycle(17, 4500, minPls, 9000, 1, 1):
  - Mints: 17 GIBS (costs 17 AFFECTION)
  - Sells: ~7.65 GIBS (45%) → WPLS
  - Re-LPs: ~9.35 GIBS (55%) + WPLS → LP tokens
  - Burns: 90% of LP → permanent floor
  - Net to wallet: ~45% of 17 GIBS in PLS value, minus gas
  - Gas: ~650K estimate (conservative — tune after first live harvestCycle)
  - VOID spam: ZERO

Break-even: GIBS price > gas_cost / (17 * sellBps/10000)
At 650K gas, 700K Beats: ~455 PLS gas → break-even at ~60 PLS/GIBS (at 45% sell)
Current GIBS: ~187 PLS → 3x above break-even

Prerequisites:
  - TGSv8+ deployed and owner=Joey
  - AFFECTION deposited into TGSv8+ (17 per cycle)
  - GIBS/WPLS pair exists on PulseX V2
  - GIBS price above break-even
"""
import logging

from ..core.log_names import get_logger

from web3 import Web3

from .base import EngineBase, EngineResult
from ..core.config import (
    JOEY_WALLET, GIBS_LAU, WPLS, AFFECTION, TGSV8PLUS,
    PULSEX_V2_FACTORY,
    HARVEST_SELL_BPS, HARVEST_BURN_BPS, HARVEST_MINT_COUNT,
    HARVEST_SELL_DEX, HARVEST_LP_DEX, HARVEST_USE_SAFE,
)
from ..core.chain import (
    erc20, factory_contract, safe, w3_read, w3_submit,
    tgsv8plus_contract,
)
from ..core.executor import send_tx, approve_if_needed
from ..core.simulator import SimulationFailed
from ..oracle.price import token_price_pls

log = get_logger(__name__)

# Gas estimate for harvestCycle (mint 17 + swap + addLiquidity + burn LP)
# Conservative — tune down after first live harvestCycle measurement.
HARVEST_GAS_ESTIMATE = 650_000


class DSSEngine(EngineBase):
    """
    Engine 2: CEREAL — Silent GIBS harvest via TGSv8+ harvestCycle.

    Replaces the old DSS chatAndClaimWithMultiplier path.
    Wallet role: joey (owner of TGSv8+).
    """
    name = "DSS"  # Keep registry name for Strategist/bot.py compatibility

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_plus(self):
        """Return TGSv8+ contract instance (read RPC)."""
        return tgsv8plus_contract()

    def _get_plus_submit(self):
        """Return TGSv8+ contract instance (submit RPC)."""
        return tgsv8plus_contract(w3=w3_submit)

    def _get_gibs_wpls_pair(self) -> str | None:
        """Return GIBS/WPLS V2 pair address, or None if it doesn't exist."""
        from ..oracle.data_store import DataStore
        store = DataStore.get()
        pair = store.lookup_pair(GIBS_LAU, WPLS)
        if pair:
            return pair
        # Fallback: live query
        factory = factory_contract(PULSEX_V2_FACTORY)
        pair_addr = safe(factory, "getPair", GIBS_LAU, WPLS)
        if not pair_addr or pair_addr == "0x" + "0" * 40:
            return None
        return pair_addr

    def _aff_in_plus(self) -> int:
        """Return AFFECTION balance inside TGSv8+."""
        return safe(erc20(AFFECTION), "balanceOf", TGSV8PLUS) or 0

    def _quote_sell(self, gibs_amount: int) -> int:
        """Use TGSv8+ quoteSell view to estimate WPLS output."""
        plus = self._get_plus()
        if not plus:
            return 0
        return safe(plus, "quoteSell", gibs_amount, HARVEST_SELL_DEX) or 0

    # ── EngineBase interface ──────────────────────────────────────────────

    def is_ready(self) -> bool:
        """
        Ready when:
        1. TGSv8+ is deployed and configured
        2. GIBS/WPLS V2 pair exists
        3. GIBS price exceeds break-even
        4. Enough AFFECTION available (in TGSv8+ or Joey's wallet)
        """
        if not TGSV8PLUS:
            log.debug("E2 not ready: TGSV8PLUS_ADDRESS not set")
            return False

        pair = self._get_gibs_wpls_pair()
        if not pair:
            log.debug("E2 not ready: no GIBS/WPLS V2 pair")
            return False

        gibs_price = token_price_pls(GIBS_LAU, 10**18)
        if not gibs_price:
            log.debug("E2 not ready: GIBS price oracle failed")
            return False

        # Check AFF availability (in TGSv8+ OR Joey wallet)
        aff_needed = HARVEST_MINT_COUNT * 10**18
        aff_in_plus = self._aff_in_plus()
        aff_in_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
        aff_total = aff_in_plus + aff_in_joey
        if aff_total < aff_needed:
            log.debug("E2 not ready: AFF %d < %d needed (plus=%d joey=%d)",
                      aff_total // 10**18, HARVEST_MINT_COUNT,
                      aff_in_plus // 10**18, aff_in_joey // 10**18)
            return False

        # Break-even check
        sell_gibs = HARVEST_MINT_COUNT * HARVEST_SELL_BPS // 10000
        if sell_gibs == 0:
            sell_gibs = 1
        gas_price = w3_read.eth.gas_price
        gas_cost_wei = HARVEST_GAS_ESTIMATE * gas_price
        revenue_wei = gibs_price * sell_gibs

        log.debug(
            "E2: GIBS=%.2f PLS, mint=%d, sell=%d(%.0f%%), gas=%.1f PLS",
            gibs_price / 1e18, HARVEST_MINT_COUNT, sell_gibs,
            HARVEST_SELL_BPS / 100, gas_cost_wei / 1e18,
        )

        return revenue_wei > gas_cost_wei

    def simulate(self) -> tuple[int, int]:
        """
        Estimate (profit_wei, gas_cost_wei) for one harvestCycle.
        Uses quoteSell() for accurate DEX output estimation.
        """
        if not TGSV8PLUS:
            raise SimulationFailed("TGSV8PLUS_ADDRESS not configured")

        pair = self._get_gibs_wpls_pair()
        if not pair:
            raise SimulationFailed("No GIBS/WPLS V2 pair")

        sell_gibs = HARVEST_MINT_COUNT * HARVEST_SELL_BPS // 10000
        sell_gibs_wei = sell_gibs * 10**18

        # Use quoteSell for accurate WPLS estimate
        pls_out = self._quote_sell(sell_gibs_wei)
        if not pls_out:
            # Fallback to price oracle
            gibs_price = token_price_pls(GIBS_LAU, 10**18)
            if not gibs_price:
                raise SimulationFailed("GIBS price oracle failed")
            pls_out = gibs_price * sell_gibs

        gas_price = w3_read.eth.gas_price
        gas_cost_wei = HARVEST_GAS_ESTIMATE * gas_price

        if pls_out <= gas_cost_wei:
            raise SimulationFailed(
                f"E2 unprofitable: sell {sell_gibs} GIBS → {pls_out/1e18:.1f} PLS "
                f"<= gas {gas_cost_wei/1e18:.1f} PLS"
            )

        return pls_out, gas_cost_wei

    def execute(self, dry_run: bool = False) -> EngineResult:
        """
        Atomic harvest cycle via TGSv8+:
        1. Ensure AFF is deposited in TGSv8+
        2. Call harvestCycle(mintCount, sellBps, minPlsOut, burnBps, sellDex, lpDex)
        3. All minting, selling, LP creation, and LP burning happens in one TX
        """
        plus = self._get_plus_submit()
        if not plus:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes="TGSv8+ not configured")

        tx_hashes = []
        gas_spent = 0

        try:
            revenue_wei, gas_cost_wei = self.simulate()
        except SimulationFailed as exc:
            return EngineResult(success=False, profit_wei=0, gas_wei=0, notes=str(exc))

        try:
            # Step 1: Ensure TGSv8+ has enough AFFECTION
            aff_needed = HARVEST_MINT_COUNT * 10**18
            aff_in_plus = self._aff_in_plus()

            if aff_in_plus < aff_needed:
                deposit_amount = aff_needed - aff_in_plus
                log.info("E2: Depositing %d AFF into TGSv8+", deposit_amount // 10**18)

                # Approve TGSv8+ to pull AFF from Joey
                aff_c = erc20(AFFECTION)
                aff_c_submit = w3_submit.eth.contract(
                    address=Web3.to_checksum_address(AFFECTION),
                    abi=aff_c.abi,
                )
                r = approve_if_needed(aff_c_submit, TGSV8PLUS, deposit_amount,
                                      "AFF→TGSv8+", dry_run=dry_run)
                if r:
                    tx_hashes.append(r["transactionHash"].hex())
                    gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

                # Deposit AFF into TGSv8+
                r = send_tx(
                    plus.functions.deposit(
                        Web3.to_checksum_address(AFFECTION), deposit_amount
                    ),
                    f"Deposit {deposit_amount // 10**18} AFF → TGSv8+",
                    dry_run=dry_run,
                )
                if r:
                    tx_hashes.append(r["transactionHash"].hex())
                    gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Step 2: Compute minPlsOut with slippage protection
            sell_gibs = HARVEST_MINT_COUNT * HARVEST_SELL_BPS // 10000
            sell_gibs_wei = sell_gibs * 10**18
            expected_pls = self._quote_sell(sell_gibs_wei)
            min_pls_out = int(expected_pls * 95 / 100) if expected_pls else 0

            # Step 3: Execute harvestCycle — THE ATOMIC PIPELINE
            log.info(
                "E2: harvestCycle(mint=%d, sell=%.0f%%, burn=%.0f%%, minPLS=%.1f)",
                HARVEST_MINT_COUNT, HARVEST_SELL_BPS / 100,
                HARVEST_BURN_BPS / 100, min_pls_out / 1e18,
            )

            r = send_tx(
                plus.functions.harvestCycle(
                    HARVEST_MINT_COUNT,
                    HARVEST_SELL_BPS,
                    min_pls_out,
                    HARVEST_BURN_BPS,
                    HARVEST_SELL_DEX,
                    HARVEST_LP_DEX,
                ),
                f"HarvestCycle({HARVEST_MINT_COUNT}, {HARVEST_SELL_BPS}bps, {HARVEST_BURN_BPS}bps)",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            log.info("E2 complete: %d GIBS minted, %.0f%% sold, %.0f%% LP burned",
                     HARVEST_MINT_COUNT, HARVEST_SELL_BPS / 100, HARVEST_BURN_BPS / 100)

            return EngineResult(
                success=True,
                profit_wei=revenue_wei,
                gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"HarvestCycle: {HARVEST_MINT_COUNT} GIBS, "
                      f"{HARVEST_SELL_BPS/100:.0f}% sell, {HARVEST_BURN_BPS/100:.0f}% burn",
            )

        except Exception as exc:
            log.error("E2 execute failed: %s", exc)
            return EngineResult(
                success=False, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes, notes=str(exc),
            )
