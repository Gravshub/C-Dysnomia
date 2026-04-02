"""
dss.py — Engine 2: CEREAL (Silent GIBS Harvest via JoystickHub)

=== HISTORY ===
V1: DysnomiaSelfSnipev4 (DSS) — chatAndClaim, spammed VOID chat. DEPRECATED.
V2: TGSv8+ — harvestCycle(sellBps=10000), 100% sell, no LP. Sell-first order.
V3: JoystickHub — mintLPAndSell. LP-first, sell-second, modular proxy.

=== CURRENT (JoystickHub) ===
Hub at 0x7bd76A0f7e03A3BA76A621ba0988C7db0AdbAB14 (block 26,092,219).
HarvestModule via delegatecall.

Two-TX pipeline:
  TX1: hub.primeGibs(N) — calls GIBS_LAU.mintToCap() × N to prime self-balance
  TX2: hub.mintLPAndSell{value: wplsNeeded}(N, lpBps, burnBps, lpDex, minSellOut, sellPath, sellDex)
       - Purchase(AFF, N) extracts GIBS from primed self-balance
       - LP first: 50% GIBS + proportional WPLS → addLiquidity (undisturbed price)
       - Sell second: remaining 50% GIBS via best route (oracle-calculated)
       - Optional LP burn → sweep to owner

=== ECONOMICS (LP Loop mode) ===
Per cycle (primeGibs + mintLPAndSell):
  - Mints: 17 GIBS (costs 17 AFFECTION)
  - LP: 8.5 GIBS + ~1,678 WPLS → LP tokens (deepens pool, earns fees)
  - Sell: 8.5 GIBS → ~1,580 PLS (recovers most WPLS)
  - Gas: ~200K (prime) + ~550K (harvest) ≈ 390 PLS
  - Net: ~1,190 PLS + LP position value (~1,678 PLS recoverable)
  - VOID spam: ZERO

Prerequisites:
  - JoystickHub deployed, owner=Joey, selectors wired, config set
  - AFFECTION deposited into Hub (17 per cycle)
  - GIBS/WPLS V2 pair exists on PulseX
  - GIBS price above break-even
"""

from ..core.log_names import get_logger

from web3 import Web3

from .base import EngineBase, EngineResult
from ..core.config import (
    JOEY_WALLET, GIBS_LAU, WPLS, AFFECTION, JOYSTICK_HUB,
    PULSEX_V2_FACTORY, PULSEX_V1_FACTORY, FED,
    PULSEX_V1_ROUTER,
    HARVEST_MINT_COUNT, HARVEST_SELL_DEX, HARVEST_LP_DEX,
    HARVEST_SELL_BPS, HARVEST_BURN_BPS,
    AFF_MATH,
)
from ..core.chain import (
    erc20, factory_contract, safe, w3_read, w3_submit,
    joystick_hub, router_contract,
)
from ..core.executor import send_tx, submit_tx_nowait, approve_if_needed
from ..core.simulator import SimulationFailed
from ..oracle.price import get_amounts_out, get_amounts_out_v2

log = get_logger(__name__)

# Gas estimates
PRIME_GAS_ESTIMATE = 200_000      # primeGibs(17) via mintToCap() × 17
HARVEST_GAS_ESTIMATE = 550_000    # mintLPAndSell with LP + sell (~550K est)
TOTAL_GAS_ESTIMATE = PRIME_GAS_ESTIMATE + HARVEST_GAS_ESTIMATE

# Extra gas per hop in multi-hop sell route
GAS_PER_EXTRA_HOP = 80_000

# Gas for AFF acquisition (wrap + swap + approve + deposit)
AFF_ACQUIRE_GAS_ESTIMATE = 250_000

# BuyWithMATH selector — keccak256("BuyWithMATH(uint256)")[:4]
BUYWITH_MATH_SELECTOR = Web3.keccak(text="BuyWithMATH(uint256)")[:4]


class DSSEngine(EngineBase):
    """
    Engine 2: CEREAL — Silent GIBS harvest via JoystickHub.

    Two-TX pipeline: primeGibs(N) → mintLPAndSell{value}(N, ...).
    LP first (undisturbed price), sell second (best route).
    Wallet role: joey (owner of JoystickHub).
    """
    name = "DSS"  # Keep registry name for Strategist/bot.py compatibility

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_hub(self):
        """Return JoystickHub contract instance (read RPC)."""
        return joystick_hub()

    def _get_hub_submit(self):
        """Return JoystickHub contract instance (submit RPC)."""
        return joystick_hub(w3=w3_submit)

    def _get_gibs_wpls_pair(self) -> str | None:
        """Return GIBS/WPLS V2 pair address, or None if it doesn't exist."""
        from ..oracle.data_store import DataStore
        store = DataStore.get()
        pair = store.lookup_pair(GIBS_LAU, WPLS)
        if pair:
            return pair
        factory = factory_contract(PULSEX_V2_FACTORY)
        pair_addr = safe(factory, "getPair", GIBS_LAU, WPLS)
        if not pair_addr or pair_addr == "0x" + "0" * 40:
            return None
        return pair_addr

    def _gibs_price_v2(self, amount: int = 10**18) -> int | None:
        """GIBS price in PLS via V2 router (GIBS/WPLS pair is V2 only)."""
        result = get_amounts_out_v2(amount, [
            Web3.to_checksum_address(GIBS_LAU),
            Web3.to_checksum_address(WPLS),
        ])
        return result[-1] if result else None

    def _aff_in_hub(self) -> int:
        """Return AFFECTION balance inside JoystickHub."""
        return safe(erc20(AFFECTION), "balanceOf", JOYSTICK_HUB) or 0

    def _gibs_wpls_reserves(self) -> tuple[int, int] | None:
        """Return (gibs_reserve, wpls_reserve) from the GIBS/WPLS V2 pair."""
        pair_addr = self._get_gibs_wpls_pair()
        if not pair_addr:
            return None
        from ..core.chain import pair_contract
        pair_c = pair_contract(pair_addr)
        reserves = safe(pair_c, "getReserves")
        if not reserves:
            return None
        token0 = safe(pair_c, "token0")
        if not token0:
            return None
        r0, r1 = reserves[0], reserves[1]
        if token0.lower() == GIBS_LAU.lower():
            return r0, r1
        return r1, r0

    def _wpls_needed_for_lp(self, gibs_for_lp_wei: int) -> int:
        """Calculate WPLS needed to LP given GIBS amount at current pool ratio."""
        reserves = self._gibs_wpls_reserves()
        if not reserves or reserves[0] == 0:
            return 0
        gibs_r, wpls_r = reserves
        # Proportional: wplsNeeded = gibsForLP * wplsReserve / gibsReserve
        # Add 2% buffer to ensure addLiquidity doesn't revert
        wpls_needed = (gibs_for_lp_wei * wpls_r) // gibs_r
        return int(wpls_needed * 102 / 100)

    def _best_sell_route(self, gibs_sell_wei: int) -> tuple[list[str], int, int]:
        """
        Find the best sell route for GIBS among candidate paths.

        Returns (path, dex, expected_output_wei).
        Candidates:
          - [GIBS, WPLS] on V2 — direct, lowest gas
          - [GIBS, FED, WPLS] on V2 — 2-hop via deeper FED pool
        """
        gibs_cs = Web3.to_checksum_address(GIBS_LAU)
        wpls_cs = Web3.to_checksum_address(WPLS)
        fed_cs = Web3.to_checksum_address(FED)

        candidates = []

        # Direct: GIBS → WPLS on V2
        direct = get_amounts_out_v2(gibs_sell_wei, [gibs_cs, wpls_cs])
        if direct and len(direct) >= 2:
            candidates.append(([gibs_cs, wpls_cs], 1, direct[-1], 0))

        # 2-hop: GIBS → FED → WPLS on V2
        two_hop = get_amounts_out_v2(gibs_sell_wei, [gibs_cs, fed_cs, wpls_cs])
        if two_hop and len(two_hop) >= 3:
            candidates.append(([gibs_cs, fed_cs, wpls_cs], 1, two_hop[-1], GAS_PER_EXTRA_HOP))

        if not candidates:
            # Absolute fallback: direct on V2
            return [gibs_cs, wpls_cs], 1, 0

        # Pick best net output (output minus extra gas cost)
        gas_price = w3_read.eth.gas_price
        best = max(candidates, key=lambda c: c[2] - (c[3] * gas_price))
        path, dex, output, _ = best

        log.debug("E2 best sell route: %s on dex=%d → %d wei",
                  [Web3.to_checksum_address(a)[-6:] for a in path], dex, output)
        return path, dex, output

    # ── AFF acquisition ─────────────────────────────────────────────────

    def _cheapest_aff_route(self, amount_aff_wei: int) -> tuple[str, int]:
        """
        Compare DEX buy vs Hub buyAffection for acquiring AFF.
        Returns ('dex' or 'buywith', estimated_pls_cost_wei).
        """
        wpls_cs = Web3.to_checksum_address(WPLS)
        aff_cs = Web3.to_checksum_address(AFFECTION)

        # DEX quote: how much WPLS to buy `amount_aff_wei` AFF?
        # Use V1 (typically slightly cheaper for AFF)
        dex_cost = None
        # Forward quote: try increasing PLS amounts until we get enough AFF
        # Start with rough estimate: ~43 PLS/AFF
        est_pls = int(amount_aff_wei * 45 / 1e18)  # 45 PLS/AFF estimate
        est_pls_wei = est_pls * 10**18
        v1_out = get_amounts_out(est_pls_wei, [wpls_cs, aff_cs])
        if v1_out and v1_out[-1] > 0:
            # Scale: cost = est_pls * (amount_needed / amount_got)
            got = v1_out[-1]
            dex_cost = int(est_pls_wei * amount_aff_wei / got)
            # Add 3% buffer for slippage
            dex_cost = int(dex_cost * 103 / 100)

        # BuyWith quote via Hub (MATH route)
        buywith_cost = None
        try:
            hub = self._get_hub()
            math_cs = Web3.to_checksum_address(AFF_MATH)
            loops = int(amount_aff_wei / 10**18)
            # Quote: how much PLS to buy `loops` AFF via MATH route?
            quote = safe(hub, "quoteBuyAffection", math_cs, est_pls_wei, loops, 1)
            if quote and quote[0] > 0:
                # quote[0] = est payment tokens needed (MATH)
                # We need to price MATH in PLS: WPLS → MATH
                math_in_pls = get_amounts_out_v2(
                    int(quote[0]), [math_cs, wpls_cs]
                )
                if math_in_pls:
                    # This gives us how much WPLS we'd get selling the MATH
                    # But we need the reverse: how much WPLS to BUY that much MATH
                    # Approximate: the PLS cost is the msg.value we'd send to buyAffection
                    wpls_for_math = get_amounts_out_v2(
                        est_pls_wei, [wpls_cs, math_cs]
                    )
                    if wpls_for_math and wpls_for_math[-1] > 0:
                        math_got = wpls_for_math[-1]
                        math_needed = int(quote[0])
                        buywith_cost = int(est_pls_wei * math_needed / math_got)
                        buywith_cost = int(buywith_cost * 103 / 100)
        except Exception as exc:
            log.debug("E2: BuyWith quote failed: %s", exc)

        # Compare
        if dex_cost and buywith_cost:
            if dex_cost <= buywith_cost:
                log.info("E2 AFF: DEX cheaper (%d vs %d PLS)", dex_cost // 10**18, buywith_cost // 10**18)
                return "dex", dex_cost
            else:
                log.info("E2 AFF: BuyWith cheaper (%d vs %d PLS)", buywith_cost // 10**18, dex_cost // 10**18)
                return "buywith", buywith_cost
        elif dex_cost:
            return "dex", dex_cost
        elif buywith_cost:
            return "buywith", buywith_cost
        else:
            # Fallback estimate
            return "dex", int(amount_aff_wei * 45)  # ~45 PLS/AFF rough

    def _acquire_aff(self, shortfall_wei: int, hub, dry_run: bool) -> tuple[list[str], int]:
        """
        Acquire AFFECTION via cheapest route and deposit into Hub.
        Returns (tx_hashes, gas_spent_wei).
        """
        tx_hashes = []
        gas_spent = 0
        route, pls_cost = self._cheapest_aff_route(shortfall_wei)

        if route == "buywith":
            # Hub buyAffection: send PLS, Hub wraps + swaps + BuyWith atomically
            math_cs = Web3.to_checksum_address(AFF_MATH)
            loops = int(shortfall_wei / 10**18)
            min_aff = int(shortfall_wei * 90 / 100)  # 10% slippage tolerance

            log.info("E2: Acquiring %d AFF via Hub buyAffection(MATH), cost ~%d PLS",
                      loops, pls_cost // 10**18)

            r = send_tx(
                hub.functions.buyAffection(
                    math_cs, BUYWITH_MATH_SELECTOR, loops, min_aff, 1
                ),
                f"buyAffection(MATH, {loops} loops)",
                dry_run=dry_run,
                value=pls_cost,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
        else:
            # DEX buy: swap PLS → WPLS → AFF on V1 router, then deposit
            wpls_cs = Web3.to_checksum_address(WPLS)
            aff_cs = Web3.to_checksum_address(AFFECTION)
            hub_addr = Web3.to_checksum_address(JOYSTICK_HUB)

            log.info("E2: Acquiring %d AFF via DEX (PLS→WPLS→AFF), cost ~%d PLS",
                      int(shortfall_wei / 10**18), pls_cost // 10**18)

            # Wrap PLS → WPLS
            WPLS_ABI = [{"constant": False, "inputs": [], "name": "deposit",
                         "outputs": [], "payable": True, "type": "function"}]
            wpls_c = w3_submit.eth.contract(address=wpls_cs, abi=WPLS_ABI)
            r = send_tx(
                wpls_c.functions.deposit(),
                f"Wrap {pls_cost // 10**18} PLS → WPLS",
                dry_run=dry_run,
                value=pls_cost,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Swap WPLS → AFF on V1
            router = router_contract(w3=w3_submit)
            r = approve_if_needed(
                w3_submit.eth.contract(address=wpls_cs, abi=erc20(WPLS).abi),
                Web3.to_checksum_address(PULSEX_V1_ROUTER), pls_cost,
                "WPLS→Router", dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            min_aff = int(shortfall_wei * 90 / 100)
            import time
            r = send_tx(
                router.functions.swapExactTokensForTokens(
                    pls_cost, min_aff,
                    [wpls_cs, aff_cs],
                    JOEY_WALLET,
                    int(time.time()) + 300,
                ),
                f"Swap WPLS → {int(shortfall_wei / 10**18)} AFF",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Now deposit AFF from Joey → Hub (use actual balance, not shortfall)
            aff_c_submit = w3_submit.eth.contract(address=aff_cs, abi=erc20(AFFECTION).abi)
            actual_aff = safe(aff_c_submit, "balanceOf", JOEY_WALLET) or 0
            deposit_amount = min(actual_aff, shortfall_wei)
            if deposit_amount == 0:
                log.warning("E2: No AFF to deposit after swap")
                return tx_hashes, gas_spent

            r = approve_if_needed(aff_c_submit, hub_addr, deposit_amount,
                                  "AFF→Hub", dry_run=dry_run)
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            r = send_tx(
                hub.functions.deposit(aff_cs, deposit_amount),
                f"Deposit {int(deposit_amount / 10**18)} AFF → Hub",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

        return tx_hashes, gas_spent

    # ── EngineBase interface ──────────────────────────────────────────────

    def is_ready(self) -> bool:
        """
        Ready when:
        1. JoystickHub is deployed and configured
        2. GIBS/WPLS V2 pair exists with reserves
        3. GIBS price exceeds break-even
        4. AFF acquirable (Hub has AFF, or Joey has AFF, or Joey has PLS to buy AFF)
        """
        if not JOYSTICK_HUB:
            log.debug("E2 not ready: JOYSTICK_HUB_ADDRESS not set")
            return False

        pair = self._get_gibs_wpls_pair()
        if not pair:
            log.debug("E2 not ready: no GIBS/WPLS V2 pair")
            return False

        # Use V2 router — GIBS/WPLS pair is on PulseX V2
        gibs_price = self._gibs_price_v2()
        if not gibs_price:
            log.debug("E2 not ready: GIBS price oracle failed")
            return False

        # Check AFF availability (in Hub, Joey wallet, or acquirable with PLS)
        aff_needed = HARVEST_MINT_COUNT * 10**18
        aff_in_hub = self._aff_in_hub()
        aff_in_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
        aff_total = aff_in_hub + aff_in_joey
        if aff_total < aff_needed:
            # Can Joey buy the shortfall with PLS?
            shortfall = aff_needed - aff_total
            _, acquire_cost = self._cheapest_aff_route(shortfall)
            joey_pls = w3_read.eth.get_balance(JOEY_WALLET)
            if joey_pls < acquire_cost + 200_000 * 10**18:  # need PLS for AFF + gas buffer
                log.debug("E2 not ready: AFF %d < %d, PLS too low to acquire (%d PLS)",
                          aff_total // 10**18, HARVEST_MINT_COUNT, joey_pls // 10**18)
                return False
            log.debug("E2: AFF shortfall %d — will auto-acquire (~%d PLS)",
                      shortfall // 10**18, acquire_cost // 10**18)

        # Break-even check: sell portion revenue must exceed total gas
        lp_bps = 10000 - HARVEST_SELL_BPS  # LP portion
        sell_count = HARVEST_MINT_COUNT * HARVEST_SELL_BPS // 10000
        gas_price = w3_read.eth.gas_price
        gas_cost_wei = TOTAL_GAS_ESTIMATE * gas_price
        revenue_wei = gibs_price * max(sell_count, 1)

        log.debug(
            "E2: GIBS=%.2f PLS, mint=%d, sell=%d%%, LP=%d%%, gas=%.1f PLS",
            gibs_price / 1e18, HARVEST_MINT_COUNT,
            HARVEST_SELL_BPS / 100, lp_bps / 100, gas_cost_wei / 1e18,
        )

        return revenue_wei > gas_cost_wei

    def simulate(self) -> tuple[int, int]:
        """
        Estimate (profit_wei, gas_cost_wei) for one LP loop cycle.
        Profit = sell revenue. LP value tracked separately.
        """
        if not JOYSTICK_HUB:
            raise SimulationFailed("JOYSTICK_HUB_ADDRESS not configured")

        pair = self._get_gibs_wpls_pair()
        if not pair:
            raise SimulationFailed("No GIBS/WPLS V2 pair")

        # Calculate sell portion
        sell_count = HARVEST_MINT_COUNT * HARVEST_SELL_BPS // 10000
        if sell_count == 0:
            sell_count = 1  # Always sell at least 1 for gas recovery
        sell_gibs_wei = sell_count * 10**18

        # Quote via best route
        _, _, pls_out = self._best_sell_route(sell_gibs_wei)
        if not pls_out:
            gibs_price = self._gibs_price_v2()
            if not gibs_price:
                raise SimulationFailed("GIBS price oracle failed")
            pls_out = gibs_price * sell_count

        # Gas estimate (2 TXs, extra hop may add gas)
        gas_price = w3_read.eth.gas_price
        gas_cost_wei = TOTAL_GAS_ESTIMATE * gas_price

        if pls_out <= gas_cost_wei:
            raise SimulationFailed(
                f"E2 unprofitable: sell {sell_count} GIBS → {pls_out/1e18:.1f} PLS "
                f"<= gas {gas_cost_wei/1e18:.1f} PLS"
            )

        return pls_out, gas_cost_wei

    def execute(self, dry_run: bool = False) -> EngineResult:
        """
        Two-TX LP loop via JoystickHub:

        1. Ensure AFF is deposited in Hub
        2. TX1: primeGibs(N) — Generate() × N to prime LAU self-balance
        3. TX2: mintLPAndSell{value}(N, lpBps, ...) — LP first, sell second
        """
        try:
            hub = self._get_hub_submit()
        except (ValueError, Exception) as exc:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                tx_hashes=[], notes=f"Hub not configured: {exc}")

        tx_hashes = []
        gas_spent = 0

        try:
            revenue_wei, gas_cost_wei = self.simulate()
        except SimulationFailed as exc:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                tx_hashes=[], notes=str(exc))

        try:
            mint_count = HARVEST_MINT_COUNT
            lp_bps = 10000 - HARVEST_SELL_BPS  # e.g., 10000-4500 = 5500
            hub_addr = Web3.to_checksum_address(JOYSTICK_HUB)
            gibs_cs = Web3.to_checksum_address(GIBS_LAU)
            aff_cs = Web3.to_checksum_address(AFFECTION)
            gibs_amount = mint_count * 10**18

            # ── Step 1: Ensure Hub has enough AFF for Purchase (1 AFF per GIBS) ──
            aff_needed = mint_count * 10**18
            aff_in_hub = self._aff_in_hub()
            if aff_in_hub < aff_needed:
                shortfall = aff_needed - aff_in_hub
                log.info("E2: Hub needs %d more AFF (has %d, needs %d)",
                         shortfall // 10**18, aff_in_hub // 10**18, mint_count)

                # Check Joey's AFF balance
                aff_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
                if aff_joey >= shortfall:
                    # Deposit Joey's AFF into Hub
                    aff_c_submit = w3_submit.eth.contract(
                        address=aff_cs, abi=erc20(AFFECTION).abi,
                    )
                    r = approve_if_needed(aff_c_submit, hub_addr, shortfall,
                                          "AFF→Hub", dry_run=dry_run)
                    if r:
                        tx_hashes.append(r["transactionHash"].hex())
                        gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

                    r = send_tx(
                        hub.functions.deposit(aff_cs, shortfall),
                        f"Deposit {shortfall//10**18} AFF → Hub",
                        dry_run=dry_run,
                        skip_simulate=True,  # approve just landed — read RPC may lag
                    )
                    if r:
                        tx_hashes.append(r["transactionHash"].hex())
                        gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
                else:
                    return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                        tx_hashes=tx_hashes,
                                        notes=f"Insufficient AFF: Joey has {aff_joey//10**18}, need {shortfall//10**18}")

            # ── Step 2+3: primeGibs → mintLPAndSell (back-to-back, no receipt wait) ──
            # CRITICAL: These two TXs MUST land in the same or consecutive blocks.
            # If we wait for primeGibs receipt, MEV bots snipe the GIBS self-balance
            # via Purchase() before mintLPAndSell can execute.
            # Fix: submit primeGibs without waiting, then immediately submit
            # mintLPAndSell with the next nonce. Miners must include them in order.

            # ── Step 2: primeGibs (fire-and-forget — no receipt wait) ──
            log.info("E2: primeGibs(%d) [no-wait, urgent]", mint_count)
            prime_hash = submit_tx_nowait(
                hub.functions.primeGibs(mint_count),
                f"primeGibs({mint_count})",
                dry_run=dry_run,
                gas_tier="urgent",  # must land quickly — sniper watches self-balance
            )
            if prime_hash:
                tx_hashes.append(prime_hash)

            # ── Step 3: mintLPAndSell (fire-and-forget, fixed gas — can't estimate against pre-prime state) ──
            gibs_for_lp_wei = (gibs_amount * lp_bps) // 10000
            wpls_needed = self._wpls_needed_for_lp(gibs_for_lp_wei)

            sell_gibs_wei = gibs_amount - gibs_for_lp_wei
            sell_path, sell_dex, expected_sell = self._best_sell_route(sell_gibs_wei)
            min_sell_out = int(expected_sell * 95 / 100) if expected_sell else 0

            log.info(
                "E2: mintLPAndSell(%d, lp=%d%%, burn=%d%%, lpDex=%d, "
                "minSell=%.1f, sellPath=%s, sellDex=%d, value=%.1f PLS) [no-wait]",
                mint_count, lp_bps / 100, HARVEST_BURN_BPS / 100,
                HARVEST_LP_DEX, min_sell_out / 1e18,
                [a[-6:] for a in sell_path], sell_dex,
                wpls_needed / 1e18,
            )

            # Submit mintLPAndSell WITHOUT waiting — both TXs now in mempool together.
            # Can't use estimate_gas here because primeGibs hasn't mined yet (state
            # still shows 0 GIBS self-balance). Use fixed 1M gas based on observed
            # usage (~377K with sell, ~515K with 2-hop sell, padded to 1M).
            harvest_hash = submit_tx_nowait(
                hub.functions.mintLPAndSell(
                    mint_count,
                    lp_bps,
                    HARVEST_BURN_BPS,
                    HARVEST_LP_DEX,
                    min_sell_out,
                    sell_path,
                    sell_dex,
                ),
                f"mintLPAndSell({mint_count}, LP={lp_bps/100:.0f}%, "
                f"burn={HARVEST_BURN_BPS/100:.0f}%, dex={sell_dex})",
                dry_run=dry_run,
                value=wpls_needed,
                skip_simulate=True,  # payable + depends on primeGibs state
                fixed_gas=1_000_000,  # can't estimate — primeGibs hasn't mined yet
                gas_tier="urgent",    # 100% base fee tip — must land same block as primeGibs
            )
            if harvest_hash:
                tx_hashes.append(harvest_hash)

            # ── Step 4: Wait for both TXs to mine ──
            if not dry_run and harvest_hash:
                import time as _time
                from ..core.chain import w3_read
                log.info("E2: Waiting for primeGibs + mintLPAndSell receipts...")
                harvest_bytes = bytes.fromhex(harvest_hash.replace("0x", ""))
                _w3_submit = w3_submit
                receipt = None
                for _poll in range(24):  # 120s max
                    _time.sleep(5)
                    for _w3 in [_w3_submit, w3_read]:
                        try:
                            receipt = _w3.eth.get_transaction_receipt(harvest_bytes)
                            if receipt:
                                break
                        except Exception:
                            pass
                    if receipt:
                        break

                if receipt and receipt.get("status") == 1:
                    gas_spent += receipt["gasUsed"] * receipt.get("effectiveGasPrice", w3_submit.eth.gas_price)
                    log.info("E2: mintLPAndSell mined. Block: %d, Gas: %d",
                             receipt["blockNumber"], receipt["gasUsed"])
                elif receipt:
                    log.error("E2: mintLPAndSell REVERTED on-chain")
                    return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                        tx_hashes=tx_hashes, notes="mintLPAndSell reverted on-chain")
                else:
                    log.error("E2: mintLPAndSell receipt timeout (120s)")
                    return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                        tx_hashes=tx_hashes, notes="mintLPAndSell receipt timeout")

            log.info("E2 complete: %d GIBS — %d%% LP, %d%% sold",
                     mint_count, lp_bps / 100, HARVEST_SELL_BPS / 100)

            return EngineResult(
                success=True,
                profit_wei=revenue_wei,
                gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"LP Loop: {mint_count} GIBS — {lp_bps/100:.0f}% LP, "
                      f"{HARVEST_SELL_BPS/100:.0f}% sell via "
                      f"{'→'.join(a[-6:] for a in sell_path)}",
            )

        except Exception as exc:
            log.error("E2 execute failed: %s", exc)
            return EngineResult(
                success=False, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes, notes=str(exc),
            )
