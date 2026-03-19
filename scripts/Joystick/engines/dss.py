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

Two-TX pipeline (workaround for TWO harvestCycle limitations):

  LIMITATION 1: harvestCycle uses silentMint pattern (no mintToCap before Purchase).
    GIBS self-balance must be pre-primed or Purchase reverts (ERC20InsufficientBalance).
    FIX: TX1 calls batchExecute(mintToCap × N) to prime GIBS self-balance.

  LIMITATION 2: harvestCycle's addLiquidity step uses 95% minimums that don't account
    for price impact from the sell step. The sell changes the GIBS/WPLS ratio, then
    addLiquidity reverts with INSUFFICIENT_A_AMOUNT because the new ratio doesn't
    match the minimum amounts.
    FIX: Use sellBps=10000 (100% sell, 0% LP). LP+burn done separately if desired.

  TX1: batchExecute — calls GIBS_LAU.mintToCap() × N to prime LAU self-balance (~196K gas)
  TX2: harvestCycle(N, 10000, minPls, 0, dex, dex) — mint + sell 100% → WPLS (~391K gas)
       Sweeps all WPLS to owner (Joey).

Default: 17 LAU per cycle, 100% sell, V2 DEX.
All values configurable via env vars (HARVEST_MINT_COUNT, HARVEST_SELL_DEX, etc.).

=== PROVEN ON MAINNET ===
Block 26066631: harvestCycle(17, 10000, 0, 0, 1, 1) — 17 GIBS → 2991.64 PLS
Gas: 196K (prime) + 391K (harvest) = 587K total ≈ 307 PLS
Net profit: 2,684 PLS per cycle

=== DSS DEPRECATION NOTE ===
The old DSS contract (0x91Df...) is NOT used for minting anymore. It remains
available ONLY for broadcasting messages to the VOID chat via DSS.chat(text).
All minting revenue now flows through TGSv8+.

=== ECONOMICS ===
Per cycle (batchExecute prime + harvestCycle):
  - Mints: 17 GIBS (costs 17 AFFECTION)
  - Sells: 17 GIBS (100%) → WPLS (~2992 PLS at current price)
  - Gas: ~196K (prime) + ~391K (harvest) = ~587K total ≈ 307 PLS
  - Net: ~2685 PLS per cycle
  - VOID spam: ZERO

Break-even: GIBS price > gas_cost / mint_count
At 587K gas, 656K Beats: ~385 PLS gas → break-even at ~23 PLS/GIBS
Current GIBS: ~176 PLS → 7.7x above break-even

Prerequisites:
  - TGSv8+ deployed and owner=Joey
  - AFFECTION deposited into TGSv8+ (17 per cycle)
  - GIBS/WPLS pair exists on PulseX V2
  - GIBS price above break-even
"""

from ..core.log_names import get_logger

from web3 import Web3

from .base import EngineBase, EngineResult
from ..core.config import (
    JOEY_WALLET, GIBS_LAU, WPLS, AFFECTION, TGSV8PLUS,
    PULSEX_V2_FACTORY,
    HARVEST_MINT_COUNT, HARVEST_SELL_DEX,
)
from ..core.chain import (
    erc20, factory_contract, safe, w3_read, w3_submit,
    tgsv8plus_contract,
)
from ..core.executor import send_tx, approve_if_needed
from ..core.simulator import SimulationFailed
from ..oracle.price import token_price_pls

log = get_logger(__name__)

# Gas estimates — measured on mainnet block 26066612/26066631
PRIME_GAS_ESTIMATE = 200_000     # batchExecute with 17 mintToCap calls (measured: 196K)
HARVEST_GAS_ESTIMATE = 400_000   # harvestCycle 100% sell, no LP (measured: 391K)
TOTAL_GAS_ESTIMATE = PRIME_GAS_ESTIMATE + HARVEST_GAS_ESTIMATE  # ~600K total

# mintToCap() function selector — keccak256("mintToCap()")[:4]
MINT_TO_CAP_SELECTOR = Web3.keccak(text="mintToCap()")[:4]


class DSSEngine(EngineBase):
    """
    Engine 2: CEREAL — Silent GIBS harvest via TGSv8+ harvestCycle.

    Two-TX pipeline: batchExecute(mintToCap×N) → harvestCycle(N, ...).
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

        # Break-even check (accounts for both TXs, 100% sell)
        gas_price = w3_read.eth.gas_price
        gas_cost_wei = TOTAL_GAS_ESTIMATE * gas_price
        revenue_wei = gibs_price * HARVEST_MINT_COUNT  # 100% sell

        log.debug(
            "E2: GIBS=%.2f PLS, mint=%d, 100%% sell, gas=%.1f PLS (2-TX)",
            gibs_price / 1e18, HARVEST_MINT_COUNT, gas_cost_wei / 1e18,
        )

        return revenue_wei > gas_cost_wei

    def simulate(self) -> tuple[int, int]:
        """
        Estimate (profit_wei, gas_cost_wei) for one harvest cycle.
        Gas includes both batchExecute (prime) and harvestCycle TXs.
        Uses quoteSell() for accurate DEX output estimation.
        100% sell — no LP step.
        """
        if not TGSV8PLUS:
            raise SimulationFailed("TGSV8PLUS_ADDRESS not configured")

        pair = self._get_gibs_wpls_pair()
        if not pair:
            raise SimulationFailed("No GIBS/WPLS V2 pair")

        # 100% sell — all minted GIBS go to DEX
        sell_gibs_wei = HARVEST_MINT_COUNT * 10**18

        # Use quoteSell for accurate WPLS estimate
        pls_out = self._quote_sell(sell_gibs_wei)
        if not pls_out:
            # Fallback to price oracle
            gibs_price = token_price_pls(GIBS_LAU, 10**18)
            if not gibs_price:
                raise SimulationFailed("GIBS price oracle failed")
            pls_out = gibs_price * HARVEST_MINT_COUNT

        gas_price = w3_read.eth.gas_price
        gas_cost_wei = TOTAL_GAS_ESTIMATE * gas_price

        if pls_out <= gas_cost_wei:
            raise SimulationFailed(
                f"E2 unprofitable: sell {HARVEST_MINT_COUNT} GIBS → {pls_out/1e18:.1f} PLS "
                f"<= gas {gas_cost_wei/1e18:.1f} PLS (2-TX)"
            )

        return pls_out, gas_cost_wei

    def execute(self, dry_run: bool = False) -> EngineResult:
        """
        Two-TX harvest pipeline via TGSv8+:

        1. Ensure AFF is deposited in TGSv8+
        2. TX1: batchExecute — call mintToCap() on GIBS_LAU × mintCount
           This primes the LAU contract's self-balance so Purchase works.
        3. TX2: harvestCycle — atomic sell+LP+burn pipeline
           Purchase × N succeeds because self-balance was primed in TX1.
        """
        plus = self._get_plus_submit()
        if not plus:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                tx_hashes=[], notes="TGSv8+ not configured")

        tx_hashes = []
        gas_spent = 0

        try:
            revenue_wei, gas_cost_wei = self.simulate()
        except SimulationFailed as exc:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                tx_hashes=[], notes=str(exc))

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

            # Step 2: Prime GIBS self-balance via batchExecute(mintToCap × N)
            # harvestCycle uses silent Purchase (no mintToCap), so we must
            # prime N tokens into GIBS_LAU's self-balance first.
            mint_count = HARVEST_MINT_COUNT
            gibs_addr = Web3.to_checksum_address(GIBS_LAU)
            targets = [gibs_addr] * mint_count
            datas = [MINT_TO_CAP_SELECTOR] * mint_count

            log.info("E2: Priming GIBS self-balance — batchExecute(mintToCap × %d)", mint_count)

            r = send_tx(
                plus.functions.batchExecute(targets, datas),
                f"Prime GIBS mintToCap × {mint_count}",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
                log.info("E2: Prime TX confirmed — gas %d", r["gasUsed"])

            # Step 3: Compute minPlsOut with slippage protection (100% sell)
            sell_gibs_wei = HARVEST_MINT_COUNT * 10**18
            expected_pls = self._quote_sell(sell_gibs_wei)
            min_pls_out = int(expected_pls * 95 / 100) if expected_pls else 0

            # Step 4: Execute harvestCycle — 100% sell, no LP (LP step has
            # INSUFFICIENT_A_AMOUNT bug due to tight minimums after price impact)
            log.info(
                "E2: harvestCycle(mint=%d, sell=100%%, minPLS=%.1f, dex=%d)",
                HARVEST_MINT_COUNT, min_pls_out / 1e18, HARVEST_SELL_DEX,
            )

            r = send_tx(
                plus.functions.harvestCycle(
                    HARVEST_MINT_COUNT,
                    10000,         # 100% sell — all GIBS → WPLS
                    min_pls_out,
                    0,             # 0% burn (no LP created)
                    HARVEST_SELL_DEX,
                    HARVEST_SELL_DEX,  # lpDex irrelevant (no LP step)
                ),
                f"HarvestCycle({HARVEST_MINT_COUNT}, 100% sell, dex={HARVEST_SELL_DEX})",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            log.info("E2 complete: %d GIBS minted + sold → PLS",
                     HARVEST_MINT_COUNT)

            return EngineResult(
                success=True,
                profit_wei=revenue_wei,
                gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"HarvestCycle: {HARVEST_MINT_COUNT} GIBS → PLS "
                      f"(2-TX: prime+sell, dex={HARVEST_SELL_DEX})",
            )

        except Exception as exc:
            log.error("E2 execute failed: %s", exc)
            return EngineResult(
                success=False, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes, notes=str(exc),
            )
