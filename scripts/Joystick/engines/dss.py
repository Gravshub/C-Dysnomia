"""
dss.py — Engine 2: CEREAL (Silent GIBS Harvest via JoystickHub)

=== HISTORY ===
V1: DysnomiaSelfSnipev4 (DSS) — chatAndClaim, spammed VOID chat. DEPRECATED.
V2: TGSv8+ — harvestCycle(sellBps=10000), 100% sell, no LP. Sell-first order.
V3: JoystickHub — mintLPAndSell. LP-first, sell-second, modular proxy.
V4: HarvestModuleV3 — primeAndSell. Atomic prime+extract+sell, anti-sniper.
V5: FloorHarvestModule — atomic prime→LP(direct pair.mint)→sell(direct pair.swap).

=== CURRENT (JoystickHub + FloorHarvestModule) ===
Hub at 0x7bd76A0f7e03A3BA76A621ba0988C7db0AdbAB14 (block 26,092,219).
FloorHarvestModule at 0xF3Be3a9Ae911EEA2Ad5C07a74069f30AADAc8669.

Primary pipeline (FloorHarvestModule):
  TX1: hub.floorAndHarvest(primeCount, lpBps, wplsMax, burnLp, minWplsOut)
       - mintToCap() × N → Purchase(AFF, N*1e18) → LP via pair.mint → sell via pair.swap
       - ALL in one TX — no router, no sniper gap
       - PulseX V2 pair.mint(to, feeTo) — two-arg mint

Fallback (HarvestModuleV3 primeAndSell):
  TX1: hub.primeAndSell(N, minPLSOut, dex, sellPath)
       - sell-only, no LP component

=== ECONOMICS (FloorHarvestModule) ===
Per cycle (17 GIBS, 50% LP / 50% sell):
  - Mints: 17 GIBS via mintToCap (costs 17 AFFECTION)
  - LP: 8.5 GIBS + proportional WPLS → burned LP (permanent floor)
  - Sell: 8.5 GIBS → WPLS via direct pair.swap
  - Net: wplsFromSell (variable) — LP value is permanent floor contribution
  - Gas: single atomic TX (~1.2M gas)
  - Sniper risk: ZERO (atomic TX)

Prerequisites:
  - JoystickHub deployed, FloorHarvestModule registered + configured
  - Hub holds AFFECTION (17 per cycle) + WPLS (for LP side)
  - GIBS/WPLS V2 pair exists on PulseX V2
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
    AFF_MATH, GIBS_WPLS_V2_PAIR,
)
from ..core.chain import (
    erc20, factory_contract, safe, w3_read, w3_submit,
    joystick_hub, router_contract,
)
from ..core.executor import send_tx, submit_tx_nowait, approve_if_needed
from ..core.simulator import SimulationFailed
from ..oracle.price import get_amounts_out, get_amounts_out_v2
from enum import Enum
from ..oracle.ladder_oracle import get_ladder_signal, LadderSignal

log = get_logger(__name__)

# Gas estimates
PRIME_GAS_ESTIMATE = 200_000      # primeGibs(17) via mintToCap() × 17
HARVEST_GAS_ESTIMATE = 550_000    # mintLPAndSell with LP + sell (~550K est)
TOTAL_GAS_ESTIMATE = PRIME_GAS_ESTIMATE + HARVEST_GAS_ESTIMATE

# FloorHarvestModule gas — single atomic TX (prime + purchase + LP + sell)
FLOOR_GAS_ESTIMATE = 1_500_000    # ~1.2M observed, 1.5M conservative

# Extra gas per hop in multi-hop sell route
GAS_PER_EXTRA_HOP = 80_000

# Gas for AFF acquisition (wrap + swap + approve + deposit)
AFF_ACQUIRE_GAS_ESTIMATE = 250_000

# BuyWithMATH selector — keccak256("BuyWithMATH(uint256)")[:4]
BUYWITH_MATH_SELECTOR = Web3.keccak(text="BuyWithMATH(uint256)")[:4]


class DSSMode(str, Enum):
    HARVEST = "harvest"
    LADDER = "ladder"
    LADDER_LITE = "ladder_lite"


class DSSEngine(EngineBase):
    """
    Engine 2: CEREAL — Silent GIBS harvest via JoystickHub.

    Two-TX pipeline: primeGibs(N) → mintLPAndSell{value}(N, ...).
    LP first (undisturbed price), sell second (best route).
    Wallet role: joey (owner of JoystickHub).
    """
    name = "DSS"  # Keep registry name for Strategist/bot.py compatibility
    _last_ladder_signal: LadderSignal | None = None
    _last_sim_mode: DSSMode = DSSMode.HARVEST

    # ── Internal helpers ──────────────────────────────────────────────────

    def _has_prime_and_sell(self, hub) -> bool:
        """Check if HarvestModuleV3 primeAndSell selector is registered in Hub."""
        try:
            selector = Web3.keccak(text="primeAndSell(uint256,uint256,uint8,address[])")[:4]
            from ..core.chain import safe as _safe
            impl = _safe(hub, "module", selector)
            if impl and impl != "0x" + "0" * 40:
                return True
        except Exception:
            pass
        return False

    def _has_floor_harvest(self, hub) -> bool:
        """Check if FloorHarvestModule floorAndHarvest selector is registered in Hub."""
        try:
            selector = Web3.keccak(text="floorAndHarvest(uint256,uint256,uint256,bool,uint256)")[:4]
            from ..core.chain import safe as _safe
            impl = _safe(hub, "module", selector)
            if impl and impl != "0x" + "0" * 40:
                return True
        except Exception:
            pass
        return False

    def _quote_floor_cycle(self, hub, prime_count: int, lp_bps: int) -> tuple | None:
        """Call quoteFloorCycle on Hub. Returns (feasible, wplsNeeded, wplsFromSell, netWpls, lpGibs, sellGibs) or None."""
        try:
            wpls_available = safe(erc20(WPLS), "balanceOf", JOYSTICK_HUB) or 0
            result = safe(hub, "quoteFloorCycle", prime_count, lp_bps, wpls_available)
            if result:
                return result
        except Exception as exc:
            log.debug("E2: quoteFloorCycle failed: %s", exc)
        return None

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

            MAX_UINT256 = 2**256 - 1
            r = approve_if_needed(aff_c_submit, hub_addr, MAX_UINT256,
                                  "AFF→Hub", dry_run=dry_run)
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            r = send_tx(
                hub.functions.deposit(aff_cs, deposit_amount),
                f"Deposit {int(deposit_amount / 10**18)} AFF → Hub",
                dry_run=dry_run,
                skip_simulate=True,
                fixed_gas=200_000,
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
        3. AFF available (Hub or Joey)
        4. quoteFloorCycle says feasible (or sell-only break-even for fallback)
        """
        if not JOYSTICK_HUB:
            log.debug("E2 not ready: JOYSTICK_HUB_ADDRESS not set")
            return False

        pair = self._get_gibs_wpls_pair()
        if not pair:
            log.debug("E2 not ready: no GIBS/WPLS V2 pair")
            return False

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
            shortfall = aff_needed - aff_total
            _, acquire_cost = self._cheapest_aff_route(shortfall)
            joey_pls = w3_read.eth.get_balance(JOEY_WALLET)
            if joey_pls < acquire_cost + 200_000 * 10**18:
                log.debug("E2 not ready: AFF %d < %d, PLS too low to acquire (%d PLS)",
                          aff_total // 10**18, HARVEST_MINT_COUNT, joey_pls // 10**18)
                return False

        gas_price = w3_read.eth.gas_price

        # FloorHarvestModule path: always run when feasible — LP burn is permanent
        # floor value, GIBS supply is expendable. Sell side recovers gas when possible.
        hub = self._get_hub()
        if self._has_floor_harvest(hub):
            lp_bps = 10000 - HARVEST_SELL_BPS
            quote = self._quote_floor_cycle(hub, HARVEST_MINT_COUNT, lp_bps)
            if quote:
                feasible, wpls_needed, wpls_from_sell, net_wpls, lp_gibs, sell_gibs = quote
                gas_cost_wei = FLOOR_GAS_ESTIMATE * gas_price
                log.info(
                    "E2 [floor]: feasible=%s, wplsFromSell=%.1f, wplsNeeded=%.1f, "
                    "net=%.1f PLS, gas=%.1f PLS, GIBS=%.1f PLS",
                    feasible, wpls_from_sell / 1e18, wpls_needed / 1e18,
                    net_wpls / 1e18, gas_cost_wei / 1e18, gibs_price / 1e18,
                )
                if not feasible:
                    log.debug("E2 not ready: quoteFloorCycle infeasible (pair empty or no WPLS)")
                    return False
                # Always ready — LP burn builds permanent price floor
                return True

        # Fallback: sell-only break-even check
        lp_bps = 10000 - HARVEST_SELL_BPS
        sell_count = HARVEST_MINT_COUNT * HARVEST_SELL_BPS // 10000
        gas_cost_wei = TOTAL_GAS_ESTIMATE * gas_price
        revenue_wei = gibs_price * max(sell_count, 1)
        log.debug(
            "E2 [fallback]: GIBS=%.2f PLS, sell=%d, revenue=%.1f PLS, gas=%.1f PLS",
            gibs_price / 1e18, sell_count, revenue_wei / 1e18, gas_cost_wei / 1e18,
        )
        return revenue_wei > gas_cost_wei

    def _simulate_ladder(self, signal: LadderSignal) -> tuple[int, int]:
        """
        Simulate LADDER mode: estimate PLS from sell leg of mintLPAndSell
        using the oracle signal's parameters.
        """
        gas_price = w3_read.eth.gas_price

        # Check AFF availability (Hub + Joey wallet)
        aff_needed = signal.mint_count * 10**18
        aff_in_hub = self._aff_in_hub()
        aff_in_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
        if aff_in_hub + aff_in_joey < aff_needed:
            raise SimulationFailed(
                f"LADDER: AFF {(aff_in_hub + aff_in_joey) // 10**18} < needed {signal.mint_count}"
            )

        # Estimate sell output: sell_gibs = total * (1 - lp_bps/10000)
        total_gibs_wei = signal.mint_count * 10**18
        sell_gibs_wei = total_gibs_wei * (10000 - signal.lp_bps) // 10000
        if sell_gibs_wei == 0:
            sell_gibs_wei = 10**18  # minimum 1 GIBS

        _, _, pls_out = self._best_sell_route(sell_gibs_wei)
        if not pls_out:
            gibs_price = self._gibs_price_v2()
            if not gibs_price:
                raise SimulationFailed("LADDER: GIBS price oracle failed")
            pls_out = gibs_price * signal.mint_count

        # Gas estimate: mintLPAndSell ~550K, maybe + primeGibs ~200K
        gas_cost_wei = HARVEST_GAS_ESTIMATE * gas_price
        gibs_self_balance = safe(erc20(GIBS_LAU), "balanceOf", JOYSTICK_HUB) or 0
        if gibs_self_balance < total_gibs_wei:
            gas_cost_wei += PRIME_GAS_ESTIMATE * gas_price

        return pls_out, gas_cost_wei

    def simulate(self) -> tuple[int, int]:
        """
        Estimate (profit_wei, gas_cost_wei) for one cycle.
        Checks ladder oracle first; falls back to HARVEST.
        """
        if not JOYSTICK_HUB:
            raise SimulationFailed("JOYSTICK_HUB_ADDRESS not configured")

        pair = self._get_gibs_wpls_pair()
        if not pair:
            raise SimulationFailed("No GIBS/WPLS V2 pair")

        # 1. Always get ladder oracle signal (just reads, cheap)
        try:
            signal = get_ladder_signal()
            self._last_ladder_signal = signal
        except Exception as exc:
            log.debug("E2: ladder oracle failed: %s", exc)
            signal = None
            self._last_ladder_signal = None

        # 2. If ladder signal fires, simulate ladder mode
        if signal and signal.should_ladder:
            try:
                self._last_sim_mode = DSSMode(signal.mode.lower())
                return self._simulate_ladder(signal)
            except SimulationFailed:
                raise
            except Exception as exc:
                log.warning("E2: ladder sim failed (%s), falling through to harvest", exc)

        # 3. Fall through to existing HARVEST simulation
        self._last_sim_mode = DSSMode.HARVEST
        gas_price = w3_read.eth.gas_price
        hub = self._get_hub()

        # FloorHarvestModule path — always run, LP burn is strategic
        if self._has_floor_harvest(hub):
            lp_bps = 10000 - HARVEST_SELL_BPS
            quote = self._quote_floor_cycle(hub, HARVEST_MINT_COUNT, lp_bps)
            if not quote:
                raise SimulationFailed("quoteFloorCycle call failed")
            feasible, wpls_needed, wpls_from_sell, net_wpls, lp_gibs, sell_gibs = quote
            if not feasible:
                raise SimulationFailed(
                    f"E2 infeasible: quoteFloorCycle({HARVEST_MINT_COUNT}, {lp_bps}) "
                    f"wplsNeeded={wpls_needed/1e18:.1f}"
                )
            gas_cost_wei = FLOOR_GAS_ESTIMATE * gas_price
            return wpls_from_sell, gas_cost_wei

        # Fallback: sell-only estimate
        sell_count = HARVEST_MINT_COUNT * HARVEST_SELL_BPS // 10000
        if sell_count == 0:
            sell_count = 1
        sell_gibs_wei = sell_count * 10**18

        _, _, pls_out = self._best_sell_route(sell_gibs_wei)
        if not pls_out:
            gibs_price = self._gibs_price_v2()
            if not gibs_price:
                raise SimulationFailed("GIBS price oracle failed")
            pls_out = gibs_price * sell_count

        gas_cost_wei = TOTAL_GAS_ESTIMATE * gas_price
        if pls_out <= gas_cost_wei:
            raise SimulationFailed(
                f"E2 unprofitable: sell {sell_count} GIBS → {pls_out/1e18:.1f} PLS "
                f"<= gas {gas_cost_wei/1e18:.1f} PLS"
            )
        return pls_out, gas_cost_wei

    def execute(self, dry_run: bool = False) -> EngineResult:
        """
        Execute harvest cycle. Routes to LADDER or HARVEST based on last simulation mode.
        """
        if self._last_sim_mode in (DSSMode.LADDER, DSSMode.LADDER_LITE):
            return self._execute_ladder(dry_run=dry_run)
        return self._execute_harvest(dry_run=dry_run)

    def _execute_ladder(self, dry_run: bool = False) -> EngineResult:
        """
        Execute LADDER mode: re-read oracle, prime if needed,
        then mintLPAndSell with calibrated displacement.
        """
        from ..core.event_logger import events as _events

        tx_hashes = []
        gas_spent = 0

        # 1. Re-read oracle (state may have changed since simulate)
        try:
            signal = get_ladder_signal()
        except Exception as exc:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                tx_hashes=[], notes=f"LADDER oracle re-read failed: {exc}")

        if not signal.should_ladder:
            log.info("E2: LADDER signal gone — falling back to HARVEST")
            return self._execute_harvest(dry_run=dry_run)

        try:
            hub = self._get_hub_submit()
        except Exception as exc:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                tx_hashes=[], notes=f"Hub not configured: {exc}")

        hub_addr = Web3.to_checksum_address(JOYSTICK_HUB)
        aff_cs = Web3.to_checksum_address(AFFECTION)

        try:
            # 2. Ensure Hub has AFF
            aff_needed = signal.mint_count * 10**18
            aff_in_hub = self._aff_in_hub()
            if aff_in_hub < aff_needed:
                AFF_BATCH_CYCLES = 30
                aff_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
                deposit_amount = min(signal.mint_count * AFF_BATCH_CYCLES * 10**18, aff_joey)
                if deposit_amount < aff_needed:
                    return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                        tx_hashes=tx_hashes,
                                        notes=f"LADDER: insufficient AFF (Joey={aff_joey//10**18})")

                MAX_UINT256 = 2**256 - 1
                aff_c = w3_submit.eth.contract(address=aff_cs, abi=erc20(AFFECTION).abi)
                r = approve_if_needed(aff_c, hub_addr, MAX_UINT256, "AFF→Hub", dry_run=dry_run)
                if r:
                    tx_hashes.append(r["transactionHash"].hex())
                    gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

                r = send_tx(
                    hub.functions.deposit(aff_cs, deposit_amount),
                    f"Deposit {deposit_amount//10**18} AFF → Hub",
                    dry_run=dry_run, skip_simulate=True, fixed_gas=200_000,
                )
                if r:
                    tx_hashes.append(r["transactionHash"].hex())
                    gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # 3. Prime GIBS if Hub self-balance is low
            gibs_needed = signal.mint_count * 10**18
            gibs_in_hub = safe(erc20(GIBS_LAU), "balanceOf", JOYSTICK_HUB) or 0
            if gibs_in_hub < gibs_needed:
                r = send_tx(
                    hub.functions.primeGibs(signal.mint_count),
                    f"primeGibs({signal.mint_count}) [LADDER]",
                    dry_run=dry_run, gas_tier="fast",
                )
                if r:
                    tx_hashes.append(r["transactionHash"].hex())
                    gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # 4. Build mintLPAndSell params
            sell_gibs_wei = gibs_needed * (10000 - signal.lp_bps) // 10000
            sell_path, sell_dex, expected_sell = self._best_sell_route(sell_gibs_wei)
            min_sell_out = int(expected_sell * 95 / 100) if expected_sell else 0

            # WPLS needed for LP side
            wpls_needed = self._wpls_needed_for_lp(gibs_needed * signal.lp_bps // 10000)

            log.info(
                "E2: LADDER %s — mintLPAndSell(%d, lp=%d%%, burn=%d%%, min=%.1f PLS) "
                "gap=%.2f%% disp=%.1f GIBS",
                signal.mode, signal.mint_count, signal.lp_bps / 100,
                signal.burn_bps / 100, min_sell_out / 1e18,
                signal.gap_pct, signal.displacement_gibs,
            )

            # 5. Send mintLPAndSell TX
            r = send_tx(
                hub.functions.mintLPAndSell(
                    signal.mint_count, signal.lp_bps, signal.burn_bps,
                    1,  # lpDex = V2
                    min_sell_out, sell_path, sell_dex,
                ),
                f"mintLPAndSell({signal.mint_count}) [LADDER {signal.mode}]",
                dry_run=dry_run, value=wpls_needed,
                skip_simulate=True, fixed_gas=750_000, gas_tier="fast",
            )
            actual_pls = 0
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
                actual_pls = expected_sell or 0

                # 6. Log ladder event
                _events.log("engine.cereal.ladder", engine="CEREAL", success=True, data={
                    "mode": signal.mode,
                    "gap_pct_before": round(signal.gap_pct, 4),
                    "arb_threshold_pct": round(signal.arb_threshold_pct, 4),
                    "displacement_gibs": round(signal.displacement_gibs, 2),
                    "mint_count": signal.mint_count,
                    "lp_bps": signal.lp_bps,
                    "burn_bps": signal.burn_bps,
                    "pls_received": round(actual_pls / 1e18, 4),
                    "block": r.get("blockNumber", 0),
                    "tx_hash": r["transactionHash"].hex(),
                })

                # 7. Post-TX feedback: re-read gap for calibration
                try:
                    feedback_signal = get_ladder_signal()
                    _events.log("engine.cereal.ladder_feedback", engine="CEREAL", data={
                        "ladder_block": r.get("blockNumber", 0),
                        "feedback_block": r.get("blockNumber", 0),
                        "gap_pct_before": round(signal.gap_pct, 4),
                        "gap_pct_after": round(feedback_signal.gap_pct, 4),
                        "gap_closed": feedback_signal.gap_pct < signal.gap_pct * 0.5,
                        "price_before": round(signal.gibs_price_pls, 4),
                        "price_after": round(feedback_signal.gibs_price_pls, 4),
                    })
                except Exception as exc:
                    log.debug("E2: ladder feedback read failed: %s", exc)

            return EngineResult(
                success=True, profit_wei=actual_pls, gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"LADDER {signal.mode}: {signal.mint_count} GIBS — "
                      f"gap={signal.gap_pct:.2f}% disp={signal.displacement_gibs:.1f}",
            )

        except Exception as exc:
            log.error("E2 LADDER execute failed: %s", exc)
            return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                tx_hashes=tx_hashes, notes=str(exc))

    def _execute_harvest(self, dry_run: bool = False) -> EngineResult:
        """
        Harvest cycle via JoystickHub. Priority:
        1. FloorHarvestModule: floorAndHarvest() — atomic prime+LP+sell, no router
        2. HarvestModuleV3: primeAndSell() — atomic prime+sell (no LP)
        3. V2 fallback: primeGibs() + mintLPAndSell() — two TXs (sniper-vulnerable)
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
            aff_cs = Web3.to_checksum_address(AFFECTION)
            aff_needed = mint_count * 10**18

            # ── Step 1: Ensure Hub has enough AFF ──
            AFF_BATCH_CYCLES = 30
            aff_in_hub = self._aff_in_hub()
            if aff_in_hub < aff_needed:
                desired_deposit = mint_count * AFF_BATCH_CYCLES * 10**18
                aff_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
                deposit_amount = min(desired_deposit, aff_joey)

                if deposit_amount < aff_needed:
                    return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                        tx_hashes=tx_hashes,
                                        notes=f"Insufficient AFF: Joey has {aff_joey//10**18}, need {aff_needed//10**18}")

                log.info("E2: Hub needs AFF (has %d, needs %d) — batch depositing %d (~%d cycles)",
                         aff_in_hub // 10**18, mint_count,
                         deposit_amount // 10**18, deposit_amount // aff_needed)

                MAX_UINT256 = 2**256 - 1
                aff_c_submit = w3_submit.eth.contract(
                    address=aff_cs, abi=erc20(AFFECTION).abi,
                )
                r = approve_if_needed(aff_c_submit, hub_addr, MAX_UINT256,
                                      "AFF→Hub", dry_run=dry_run)
                if r:
                    tx_hashes.append(r["transactionHash"].hex())
                    gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

                r = send_tx(
                    hub.functions.deposit(aff_cs, deposit_amount),
                    f"Deposit {deposit_amount//10**18} AFF → Hub",
                    dry_run=dry_run,
                    skip_simulate=True,
                    fixed_gas=200_000,
                )
                if r:
                    tx_hashes.append(r["transactionHash"].hex())
                    gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # ── Step 2: Execute harvest ──

            # Priority 1: FloorHarvestModule (atomic LP+sell, no router)
            if self._has_floor_harvest(hub):
                hub_read = self._get_hub()
                quote = self._quote_floor_cycle(hub_read, mint_count, lp_bps)
                if quote:
                    feasible, wpls_needed, wpls_from_sell, net_wpls, lp_gibs, sell_gibs = quote
                    if feasible:
                        # wplsMax = 2x quote for slippage tolerance
                        wpls_max = wpls_needed * 2
                        # minWplsOut = 90% of quoted sell output
                        min_wpls_out = int(wpls_from_sell * 90 / 100)

                        log.info(
                            "E2: floorAndHarvest(%d, lp=%d%%, wplsMax=%.1f, LP→Joey, "
                            "minOut=%.1f) [FLOOR]",
                            mint_count, lp_bps / 100, wpls_max / 1e18,
                            min_wpls_out / 1e18,
                        )
                        r = send_tx(
                            hub.functions.floorAndHarvest(
                                mint_count, lp_bps, wpls_max, True, min_wpls_out,
                            ),
                            f"floorAndHarvest({mint_count}, LP={lp_bps/100:.0f}%)",
                            dry_run=dry_run,
                            gas_tier="fast",
                        )
                        if r:
                            tx_hashes.append(r["transactionHash"].hex())
                            gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
                            log.info("E2: floorAndHarvest mined. Block: %d, Gas: %d",
                                     r["blockNumber"], r["gasUsed"])

                        # WPLS stays in Hub as working capital for LP side.
                        # Sell proceeds replenish the WPLS pool each cycle.
                        # Manual hub.withdraw() if Joey needs PLS back.

                        return EngineResult(
                            success=True,
                            profit_wei=revenue_wei,
                            gas_wei=gas_spent,
                            tx_hashes=tx_hashes,
                            notes=f"Floor: {mint_count} GIBS — {lp_bps/100:.0f}% LP (→ Joey), "
                                  f"sell={sell_gibs/1e18:.1f} GIBS → {wpls_from_sell/1e18:.1f} WPLS",
                        )

            # Priority 2: primeAndSell (atomic sell-only, anti-sniper)
            gibs_amount = mint_count * 10**18
            sell_path, sell_dex, expected_sell = self._best_sell_route(gibs_amount)
            min_sell_out = int(expected_sell * 90 / 100) if expected_sell else 0

            if self._has_prime_and_sell(hub):
                log.info(
                    "E2: primeAndSell(%d, min=%.1f PLS, dex=%d, path=%s) [ATOMIC]",
                    mint_count, min_sell_out / 1e18, sell_dex,
                    [a[-6:] for a in sell_path],
                )
                r = send_tx(
                    hub.functions.primeAndSell(
                        mint_count, min_sell_out, sell_dex, sell_path,
                    ),
                    f"primeAndSell({mint_count}, min={min_sell_out/1e18:.0f} PLS)",
                    dry_run=dry_run,
                    gas_tier="fast",
                )
                if r:
                    tx_hashes.append(r["transactionHash"].hex())
                    gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

                return EngineResult(
                    success=True, profit_wei=revenue_wei, gas_wei=gas_spent,
                    tx_hashes=tx_hashes,
                    notes=f"Atomic: {mint_count} GIBS → PLS via {'→'.join(a[-6:] for a in sell_path)}",
                )

            # Priority 3: V2 two-TX fallback (sniper-vulnerable)
            log.warning("E2: no FloorHarvest or primeAndSell — V2 fallback (sniper-vulnerable)")
            r = send_tx(
                hub.functions.primeGibs(mint_count),
                f"primeGibs({mint_count})",
                dry_run=dry_run, gas_tier="fast",
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            gibs_for_lp_wei = (gibs_amount * lp_bps) // 10000
            wpls_needed = self._wpls_needed_for_lp(gibs_for_lp_wei)
            sell_gibs_wei = gibs_amount - gibs_for_lp_wei
            sell_path, sell_dex, expected_sell = self._best_sell_route(sell_gibs_wei)
            min_sell_out = int(expected_sell * 95 / 100) if expected_sell else 0

            r = send_tx(
                hub.functions.mintLPAndSell(
                    mint_count, lp_bps, HARVEST_BURN_BPS, HARVEST_LP_DEX,
                    min_sell_out, sell_path, sell_dex,
                ),
                f"mintLPAndSell({mint_count})",
                dry_run=dry_run, value=wpls_needed,
                skip_simulate=True, fixed_gas=500_000, gas_tier="fast",
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            return EngineResult(
                success=True, profit_wei=revenue_wei, gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"V2 fallback: {mint_count} GIBS — {lp_bps/100:.0f}% LP, {HARVEST_SELL_BPS/100:.0f}% sell",
            )

        except Exception as exc:
            log.error("E2 execute failed: %s", exc)
            return EngineResult(
                success=False, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes, notes=str(exc),
            )
