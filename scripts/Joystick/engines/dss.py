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
from ..core.probe_controller import ArbResponseKind

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

    def __init__(self, probe_controller=None):
        super().__init__()
        # Probe controller — adaptive sell sizing for GIBS/WPLS.
        # If not injected, create the default singleton.
        from ..core.probe_controller import ProbeController
        self.probe = probe_controller or ProbeController()

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

    def _has_mint_lp_sell_pair(self, hub) -> bool:
        """Check if mintLPAndSellPair selector is registered in Hub."""
        try:
            sig = "mintLPAndSellPair(address,address,address,uint256,uint256,uint256,uint256,uint8,uint256,address[],uint8)"
            selector = Web3.keccak(text=sig)[:4]
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

    def _read_gibs_wpls_reserves(self) -> tuple[int, int]:
        """Returns (R_gibs_wei, R_wpls_wei) at current block.

        Thin wrapper around _gibs_wpls_reserves() that always returns a tuple.
        Used by ProbeController.next_sell_gibs().
        """
        reserves = self._gibs_wpls_reserves()
        if not reserves:
            return (0, 0)
        return (int(reserves[0]), int(reserves[1]))

    def _execute_lp_only_add(self, gibs_wei: int, dry_run: bool = False) -> EngineResult:
        """Submit a Hub mintLPAndSell with lp_bps=10000 (LP only, no sell)."""
        gibs_r, wpls_r = self._read_gibs_wpls_reserves()
        if gibs_r == 0 or wpls_r == 0:
            return EngineResult(
                success=False, profit_wei=0, gas_wei=0,
                tx_hashes=[], notes="lp_only_add: failed to read reserves",
            )
        wpls_needed = int((gibs_wei * wpls_r // gibs_r) * 105 // 100)
        mint_count = (gibs_wei + 10**18 - 1) // 10**18

        try:
            hub = self._get_hub_submit()
        except Exception as exc:
            return EngineResult(
                success=False, profit_wei=0, gas_wei=0,
                tx_hashes=[], notes=f"lp_only_add: hub init failed: {exc}",
            )

        log.info(
            "E2: lp_only_add — mintLPAndSell(%d, lp_bps=10000, burn_bps=0) value=%.2f PLS",
            mint_count, wpls_needed / 1e18,
        )
        try:
            r = send_tx(
                hub.functions.mintLPAndSell(
                    mint_count, 10000, 0,  # lp_bps=10000 (all LP), burn_bps=0
                    1,                     # lp_dex = V2
                    0, [], 0,              # no sell
                ),
                f"lpOnlyAdd({mint_count})",
                dry_run=dry_run, value=wpls_needed,
                skip_simulate=True, fixed_gas=750_000, gas_tier="fast",
            )
            if r:
                return EngineResult(
                    success=True, profit_wei=0,
                    gas_wei=r["gasUsed"] * r.get("effectiveGasPrice", 0),
                    tx_hashes=[r["transactionHash"].hex()],
                    notes=f"LP-only add: {mint_count} GIBS",
                )
        except Exception as exc:
            return EngineResult(
                success=False, profit_wei=0, gas_wei=0,
                tx_hashes=[], notes=f"lp_only_add: tx failed: {exc}",
            )
        return EngineResult(
            success=False, profit_wei=0, gas_wei=0,
            tx_hashes=[], notes="lp_only_add: send_tx returned None",
        )

    def _execute_lp_add_via_tgsv8(self, gibs_wei: int, pair_addr: str,
                                    dry_run: bool = False) -> EngineResult:
        """Add LP to an arbitrary GIBS pair via TGSv8.addLiquidity.

        Used after arb detection on non-WPLS pairs (e.g., GIBS/AFF).
        Flow: primeGibs → Purchase → deposit to TGSv8 → addLiquidity.
        """
        from ..core.chain import tgsv8_contract, pair_contract, w3_read
        tx_hashes = []
        gas_spent = 0

        # Determine the other token in the pair
        pc = pair_contract(Web3.to_checksum_address(pair_addr))
        t0 = safe(pc, "token0")
        reserves = safe(pc, "getReserves")
        if not t0 or not reserves:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                tx_hashes=[], notes="lp_add_tgsv8: failed to read pair")

        if t0.lower() == GIBS_LAU.lower():
            other_token = safe(pc, "token1")
            gibs_r, other_r = reserves[0], reserves[1]
        else:
            other_token = t0
            gibs_r, other_r = reserves[1], reserves[0]

        if not other_token or gibs_r == 0:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                tx_hashes=[], notes="lp_add_tgsv8: invalid pair state")

        # Calculate matching amount of other token
        ratio = other_r / gibs_r  # unitless
        other_needed = int(gibs_wei * ratio)

        mint_count = (gibs_wei + 10**18 - 1) // 10**18
        aff_for_mint = mint_count * 10**18  # 1 AFF per GIBS
        total_aff = aff_for_mint + other_needed  # assumes other_token is AFF

        log.info("E2: LP-add via TGSv8 on %s — %d GIBS + %d other, needs %d AFF total",
                 pair_addr[-8:], mint_count, other_needed // 10**18, total_aff // 10**18)

        # Ensure Joey has enough AFF (acquire if needed)
        aff_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
        if aff_joey < total_aff:
            hub = self._get_hub_submit()
            shortfall = total_aff - aff_joey
            acq_hashes, acq_gas = self._acquire_aff(shortfall, hub, dry_run)
            tx_hashes.extend(acq_hashes)
            gas_spent += acq_gas

        # Prime + Purchase GIBS
        hub = self._get_hub_submit()
        r = send_tx(hub.functions.primeGibs(mint_count),
                    f"primeGibs({mint_count}) [lp-add]",
                    dry_run=dry_run, gas_tier="fast")
        if r:
            tx_hashes.append(r["transactionHash"].hex())
            gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

        PURCHASE_ABI = [{"inputs": [{"name": "_t", "type": "address"},
                         {"name": "_a", "type": "uint256"}],
                         "name": "Purchase", "outputs": [], "type": "function"}]
        gibs_c = w3_submit.eth.contract(
            address=Web3.to_checksum_address(GIBS_LAU), abi=PURCHASE_ABI)
        aff_cs = Web3.to_checksum_address(AFFECTION)

        # Approve AFF → GIBS_LAU for Purchase
        MAX_UINT = 2**256 - 1
        approve_if_needed(
            w3_submit.eth.contract(address=aff_cs, abi=erc20(AFFECTION).abi),
            Web3.to_checksum_address(GIBS_LAU), MAX_UINT,
            "AFF→GIBS_LAU", dry_run=dry_run)

        r = send_tx(gibs_c.functions.Purchase(aff_cs, gibs_wei),
                    f"Purchase({gibs_wei//10**18} GIBS) [lp-add]",
                    dry_run=dry_run, skip_simulate=True, fixed_gas=200_000)
        if r:
            tx_hashes.append(r["transactionHash"].hex())
            gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

        # Deposit to TGSv8 + addLiquidity
        tgs = tgsv8_contract(w3=w3_submit)
        tgs_addr = tgs.address
        gibs_cs = Web3.to_checksum_address(GIBS_LAU)
        other_cs = Web3.to_checksum_address(other_token)

        approve_if_needed(
            w3_submit.eth.contract(address=gibs_cs, abi=erc20(GIBS_LAU).abi),
            tgs_addr, MAX_UINT, "GIBS→TGSv8", dry_run=dry_run)
        approve_if_needed(
            w3_submit.eth.contract(address=other_cs, abi=erc20(other_token).abi),
            tgs_addr, MAX_UINT, "other→TGSv8", dry_run=dry_run)

        gibs_bal = safe(erc20(GIBS_LAU), "balanceOf", JOEY_WALLET) or 0
        other_bal = safe(erc20(other_token), "balanceOf", JOEY_WALLET) or 0
        # Re-match ratio
        g_deposit = min(gibs_bal, gibs_wei)
        o_deposit = min(other_bal, int(g_deposit * ratio))

        send_tx(tgs.functions.deposit(gibs_cs, g_deposit),
                "deposit GIBS [lp-add]",
                dry_run=dry_run, skip_simulate=True, fixed_gas=200_000, gas_tier="fast")
        send_tx(tgs.functions.deposit(other_cs, o_deposit),
                "deposit other [lp-add]",
                dry_run=dry_run, skip_simulate=True, fixed_gas=200_000, gas_tier="fast")

        r = send_tx(tgs.functions.addLiquidity(
                        gibs_cs, other_cs, g_deposit, o_deposit,
                        1500, JOEY_WALLET, 1),
                    f"addLiquidity({g_deposit//10**18} GIBS + {o_deposit//10**18} other) [lp-add]",
                    dry_run=dry_run, skip_simulate=True, fixed_gas=500_000)
        if r:
            tx_hashes.append(r["transactionHash"].hex())
            gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
            log.info("E2: LP-add on %s mined! Block: %d", pair_addr[-8:], r["blockNumber"])
            return EngineResult(
                success=True, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"LP-add via TGSv8: {g_deposit//10**18} GIBS on {pair_addr[-8:]}",
            )

        return EngineResult(
            success=False, profit_wei=0, gas_wei=gas_spent,
            tx_hashes=tx_hashes, notes="lp_add_tgsv8: addLiquidity failed",
        )

    def _execute_harvest_pair(
        self,
        lau: str,
        payment_token: str,
        lp_partner: str,
        prime_count: int,
        purchase_amt: int,
        lp_bps: int,
        sell_path: list[str],
        sell_dex: int,
        min_sell_out: int = 0,
        dry_run: bool = False,
        sell_pair_address: str = "",
    ) -> EngineResult:
        """Atomic harvest on any LAU/pair via Hub mintLPAndSellPair.

        Single TX: prime → purchase → LP → sell.  Replaces the multi-TX
        primeGibs + Purchase + deposit + addLiquidity pipeline.
        """
        hub = self._get_hub_submit()
        tx_hashes = []
        gas_spent = 0

        lau_cs = Web3.to_checksum_address(lau)
        payment_cs = Web3.to_checksum_address(payment_token)
        lp_partner_cs = Web3.to_checksum_address(lp_partner)
        sell_path_cs = [Web3.to_checksum_address(a) for a in sell_path]

        log.info(
            "E2: mintLPAndSellPair(lau=%s, payment=%s, lp=%s, prime=%d, "
            "purchase=%d, lpBps=%d, sell=%s, minOut=%.1f PLS) [ATOMIC-PAIR]",
            lau_cs[-8:], payment_cs[-8:], lp_partner_cs[-8:],
            prime_count, purchase_amt, lp_bps,
            [a[-6:] for a in sell_path_cs],
            min_sell_out / 1e18,
        )

        r = send_tx(
            hub.functions.mintLPAndSellPair(
                lau_cs,
                payment_cs,
                lp_partner_cs,
                prime_count,
                purchase_amt,
                lp_bps,
                0,           # burnBps = 0
                1,           # lpDex = V2
                min_sell_out,
                sell_path_cs,
                sell_dex,
            ),
            f"mintLPAndSellPair({purchase_amt} {lau_cs[-6:]}/{lp_partner_cs[-6:]})",
            dry_run=dry_run,
            gas_tier="fast",
        )
        if r:
            tx_hashes.append(r["transactionHash"].hex())
            gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
            log.info(
                "E2: mintLPAndSellPair mined. Block: %d, Gas: %d",
                r["blockNumber"], r["gasUsed"],
            )

            # Record sell for probe controller (sell portion = (10000-lpBps)/10000)
            sell_gibs_wei = purchase_amt * 10**18 * (10000 - lp_bps) // 10000
            try:
                self.probe.record_sell(
                    sell_gibs_wei=sell_gibs_wei,
                    block_number=r["blockNumber"],
                    tx_hash=r["transactionHash"].hex(),
                    pair_address=sell_pair_address or "",
                )
            except Exception as _probe_exc:
                log.debug("E2: probe.record_sell failed: %s", _probe_exc)

            return EngineResult(
                success=True,
                profit_wei=0,  # calculated by caller
                gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"AtomicPair: {purchase_amt} {lau_cs[-6:]}, "
                      f"{lp_bps/100:.0f}% LP on {lp_partner_cs[-6:]}, "
                      f"sell via {'→'.join(a[-6:] for a in sell_path_cs)}",
            )

        return EngineResult(
            success=False, profit_wei=0, gas_wei=gas_spent,
            tx_hashes=tx_hashes,
            notes="mintLPAndSellPair: send_tx returned None",
        )

    def _arb_trigger_size(self, sell_pair: str, ref_pair: str,
                          arb_gas_pls: float = 227.0) -> int:
        """GIBS that must be sold into sell_pair so a cross-pool arb vs ref_pair
        is profitable after arb_gas_pls gas cost.

        Uses binary search over sell sizes, simulating the optimal arb bot
        trade across both constant-product pools.  Returns whole-token count.
        """
        from ..core.chain import pair_contract as _pair_c

        def _read_pair(addr):
            pc = _pair_c(Web3.to_checksum_address(addr))
            res = safe(pc, "getReserves")
            t0 = safe(pc, "token0")
            if not res or not t0:
                return None
            if t0.lower() == GIBS_LAU.lower():
                return res[0] / 1e18, res[1] / 1e18   # (gibs, other)
            return res[1] / 1e18, res[0] / 1e18

        sell_pool = _read_pair(sell_pair)
        ref_pool = _read_pair(ref_pair)
        if not sell_pool or not ref_pool:
            return 17  # fallback

        Rg_sell, Ro_sell = sell_pool   # GIBS/AFF
        Rg_ref, Ro_ref = ref_pool     # GIBS/WPLS
        gibs_pls = Ro_ref / Rg_ref    # PLS per GIBS

        def _arb_profit_after_sell(sell_gibs):
            """Simulate: we sell sell_gibs into sell_pair, arb bot finds optimal trade."""
            # Our sell into sell_pair
            out = (sell_gibs * 0.997 * Ro_sell) / (Rg_sell + sell_gibs * 0.997)
            nRg = Rg_sell + sell_gibs
            nRo = Ro_sell - out

            # Cross-rate: AFF/PLS ≈ (Rg_sell/Ro_sell) * (Ro_ref/Rg_ref)
            aff_pls = gibs_pls * (Rg_sell / Ro_sell)

            best = 0.0
            # Arb: buy GIBS from depressed sell_pair, sell on ref_pair
            for arb_x10 in range(1, 3000):
                arb = arb_x10 / 10.0
                if arb >= nRg * 0.3:
                    break
                aff_cost = (arb * 1000 * nRo) / ((nRg - arb) * 997)
                pls_out = (arb * 0.997 * Ro_ref) / (Rg_ref + arb * 0.997)
                profit = pls_out - aff_cost * aff_pls
                if profit > best:
                    best = profit
            return best

        # Binary search for minimum sell size that triggers arb
        lo, hi = 1, 2000
        while lo < hi:
            mid = (lo + hi) // 2
            if _arb_profit_after_sell(mid) >= arb_gas_pls:
                hi = mid
            else:
                lo = mid + 1

        return lo

    # Known GIBS LP pairs and their partner tokens (address, dex: 0=V1,1=V2)
    _GIBS_PAIRS = [
        ("0xa152659B651b89b1895Edfb6544bDB82ff3E9c25", "0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6", 0),  # GIBS/ATROPA V1
        ("0xB07760241467931aDCd8f9f4A5704099a9A7e416", "0x965B0d74591bF30327075A247C47dBf487dCff08", 1),  # GIBS/VOID V2
        ("0xA2a7a2153136B6eE075335b979Fb6ac033412e4d", "0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff", 1),  # GIBS/FED V2
        ("0xc23Cf1aF3C44FA61Dc79C7DF5ccA241f26d29207", "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29", 1),  # GIBS/WM V2
    ]

    def _find_thinnest_pair(self) -> tuple[str, str, float, int]:
        """Find the GIBS pair with the lowest GIBS reserve (max displacement).

        Returns (pair_addr, other_token, gibs_reserve, dex) or (None,None,0,1).
        Skips pairs where the other token has no WPLS route (can't sell to PLS).
        """
        from ..core.chain import pair_contract as _pair_c
        from ..oracle.price import get_amounts_out_v2, get_amounts_out

        best = (None, None, float("inf"), 1)
        wpls_cs = Web3.to_checksum_address(WPLS)
        gibs_cs = Web3.to_checksum_address(GIBS_LAU)

        for pair_addr, other_token, dex in self._GIBS_PAIRS:
            try:
                pc = _pair_c(Web3.to_checksum_address(pair_addr))
                res = safe(pc, "getReserves")
                t0 = safe(pc, "token0")
                if not res or not t0:
                    continue
                if t0.lower() == GIBS_LAU.lower():
                    rg = res[0] / 1e18
                else:
                    rg = res[1] / 1e18
                if rg < 1:  # skip empty pairs
                    continue

                # Verify the sell route works: other_token → WPLS
                other_cs = Web3.to_checksum_address(other_token)
                if other_cs.lower() != wpls_cs.lower():
                    try:
                        test_path = [other_cs, wpls_cs]
                        if dex == 1:
                            amt = get_amounts_out_v2(10**18, test_path)
                        else:
                            amt = get_amounts_out(10**18, test_path)
                        if not amt or amt[-1] == 0:
                            continue
                    except Exception:
                        continue

                if rg < best[2]:
                    best = (pair_addr, other_token, rg, dex)
            except Exception:
                continue

        if best[0] is None:
            return (None, None, 0, 1)
        return best

    def _self_arb_thin_pool(
        self, thin_pair: str, thin_other: str, thin_dex: int,
        dry_run: bool = False,
    ) -> EngineResult:
        """After displacing a thin GIBS pool, buy cheap GIBS and sell on deep pool.

        Buy leg:  WPLS → thin_other → GIBS  (via thin_dex router, cheap GIBS)
        Sell leg: GIBS → WPLS               (via V2 router, fair price)

        Returns EngineResult with profit = sell_pls - buy_pls.
        Skips if estimated profit < gas cost.
        """
        from ..core.chain import pair_contract as _pair_c, router_contract, w3_read
        from ..oracle.price import get_amounts_out_v2, get_amounts_out
        from ..core.config import (
            PULSEX_V1_ROUTER, PULSEX_V2_ROUTER, GIBS_WPLS_V2_PAIR,
        )
        import time

        cs = Web3.to_checksum_address
        gibs_cs = cs(GIBS_LAU)
        wpls_cs = cs(WPLS)
        other_cs = cs(thin_other)
        thin_pair_cs = cs(thin_pair)

        # Read displaced thin pool
        pc = _pair_c(thin_pair_cs)
        res = safe(pc, "getReserves")
        t0 = safe(pc, "token0")
        if not res or not t0:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                tx_hashes=[], notes="self_arb: can't read thin pair")
        if t0.lower() == GIBS_LAU.lower():
            rg_thin, ro_thin = res[0] / 1e18, res[1] / 1e18
        else:
            ro_thin, rg_thin = res[0] / 1e18, res[1] / 1e18

        # Read GIBS/WPLS (deep, undisturbed)
        pw = _pair_c(cs(GIBS_WPLS_V2_PAIR))
        rw = safe(pw, "getReserves")
        tw = safe(pw, "token0")
        if not rw or not tw:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                tx_hashes=[], notes="self_arb: can't read WPLS pair")
        if tw.lower() == GIBS_LAU.lower():
            rg_w, ro_w = rw[0] / 1e18, rw[1] / 1e18
        else:
            ro_w, rg_w = rw[0] / 1e18, rw[1] / 1e18

        gibs_pls = ro_w / rg_w  # fair GIBS price in PLS

        # Find optimal arb size (maximize profit)
        # Buy route: WPLS → other → GIBS (on thin_dex)
        # Sell route: GIBS → WPLS (on V2)
        buy_path = [wpls_cs, other_cs, gibs_cs] if other_cs.lower() != wpls_cs.lower() else [wpls_cs, gibs_cs]
        sell_path = [gibs_cs, wpls_cs]

        best_profit = 0
        best_buy_pls = 0
        best_gibs = 0

        for pls_in in range(100, 8001, 100):  # test 100-8000 PLS buy sizes
            pls_wei = pls_in * 10**18
            try:
                if thin_dex == 0:
                    buy_out = get_amounts_out(pls_wei, buy_path)
                else:
                    buy_out = get_amounts_out_v2(pls_wei, buy_path)
                gibs_bought_wei = buy_out[-1] if buy_out else 0
                if gibs_bought_wei == 0:
                    continue

                sell_out = get_amounts_out_v2(gibs_bought_wei, sell_path)
                pls_out = sell_out[-1] if sell_out else 0

                profit = (pls_out - pls_wei) / 1e18
                if profit > best_profit:
                    best_profit = profit
                    best_buy_pls = pls_in
                    best_gibs = gibs_bought_wei / 1e18
            except Exception:
                continue

        # Estimate gas for 2 router swaps + wrap
        ARB_GAS_EST = 350_000
        gas_price = w3_submit.eth.gas_price
        gas_cost_pls = ARB_GAS_EST * gas_price / 1e18

        log.info(
            "E2: self-arb check — buy %d PLS → %.1f GIBS (thin %s), "
            "sell → profit %.0f PLS, gas ~%.0f PLS",
            best_buy_pls, best_gibs, thin_pair_cs[-8:],
            best_profit, gas_cost_pls,
        )

        if best_profit <= gas_cost_pls or best_buy_pls == 0:
            log.info("E2: self-arb skipped — profit %.0f < gas %.0f", best_profit, gas_cost_pls)
            return EngineResult(success=True, profit_wei=0, gas_wei=0,
                                tx_hashes=[],
                                notes=f"self_arb: skipped (profit {best_profit:.0f} < gas {gas_cost_pls:.0f})")

        # Execute: wrap PLS → buy via thin_dex router → sell via V2 router
        tx_hashes = []
        gas_spent = 0
        buy_wei = best_buy_pls * 10**18
        MAX_UINT = 2**256 - 1

        # Wrap PLS
        WPLS_DEP_ABI = [{"constant": False, "inputs": [], "name": "deposit",
                         "outputs": [], "payable": True, "type": "function"}]
        wpls_c = w3_submit.eth.contract(address=wpls_cs, abi=WPLS_DEP_ABI)
        r = send_tx(wpls_c.functions.deposit(),
                    f"wrap {best_buy_pls} PLS [self-arb]",
                    value=buy_wei, skip_simulate=True, fixed_gas=50_000,
                    dry_run=dry_run)
        if r:
            tx_hashes.append(r["transactionHash"].hex())
            gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", gas_price)

        # Buy: WPLS → other → GIBS via thin_dex router
        buy_router_addr = cs(PULSEX_V1_ROUTER if thin_dex == 0 else PULSEX_V2_ROUTER)
        approve_if_needed(
            w3_submit.eth.contract(address=wpls_cs, abi=erc20(WPLS).abi),
            buy_router_addr, MAX_UINT,
            f"WPLS→{'V1' if thin_dex == 0 else 'V2'}Router [arb]",
            dry_run=dry_run)

        SWAP_ABI = [{"inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {"name": "path", "type": "address[]"},
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"}],
            "name": "swapExactTokensForTokens",
            "outputs": [{"name": "", "type": "uint256[]"}],
            "type": "function"}]
        buy_router = w3_submit.eth.contract(address=buy_router_addr, abi=SWAP_ABI)
        min_gibs = int(best_gibs * 0.85 * 1e18)

        gibs_before = safe(erc20(GIBS_LAU), "balanceOf", JOEY_WALLET) or 0
        r = send_tx(buy_router.functions.swapExactTokensForTokens(
                        buy_wei, min_gibs, buy_path,
                        JOEY_WALLET, int(time.time()) + 300),
                    f"buy {best_gibs:.0f} GIBS from thin pool [self-arb]",
                    skip_simulate=True, fixed_gas=300_000, gas_tier="fast",
                    dry_run=dry_run)
        gibs_received = 0
        if r:
            tx_hashes.append(r["transactionHash"].hex())
            gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", gas_price)
            gibs_after = safe(erc20(GIBS_LAU), "balanceOf", JOEY_WALLET) or 0
            gibs_received = gibs_after - gibs_before

        if gibs_received == 0 and not dry_run:
            return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                tx_hashes=tx_hashes, notes="self_arb: buy failed")

        # Sell: GIBS → WPLS via V2 router
        sell_router_addr = cs(PULSEX_V2_ROUTER)
        approve_if_needed(
            w3_submit.eth.contract(address=gibs_cs, abi=erc20(GIBS_LAU).abi),
            sell_router_addr, MAX_UINT,
            "GIBS→V2Router [arb]", dry_run=dry_run)

        sell_router = w3_submit.eth.contract(address=sell_router_addr, abi=SWAP_ABI)
        min_pls_out = int(buy_wei * 0.85)  # at minimum get 85% back

        r = send_tx(sell_router.functions.swapExactTokensForTokens(
                        gibs_received, min_pls_out, sell_path,
                        JOEY_WALLET, int(time.time()) + 300),
                    f"sell {gibs_received//10**18} GIBS on WPLS [self-arb]",
                    skip_simulate=True, fixed_gas=200_000, gas_tier="fast",
                    dry_run=dry_run)
        if r:
            tx_hashes.append(r["transactionHash"].hex())
            gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", gas_price)

        actual_profit = int(best_profit * 1e18)
        log.info("E2: self-arb complete — est profit %.0f PLS, gas %.0f PLS",
                 best_profit, gas_spent / 1e18)

        return EngineResult(
            success=True, profit_wei=actual_profit, gas_wei=gas_spent,
            tx_hashes=tx_hashes,
            notes=f"self_arb: buy {best_buy_pls} PLS → {best_gibs:.0f} GIBS (thin {thin_pair_cs[-8:]}), "
                  f"profit ~{best_profit:.0f} PLS",
        )

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
        floor_feasible = False
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
                floor_feasible = feasible
                if feasible:
                    return True

        # LADDER mode — uses mintLPAndSell with Joey's PLS as msg.value,
        # so works even when Hub WPLS=0 (floor infeasible).
        # Two cases we want to cover:
        #   (a) Organic ladder — oracle signals should_ladder=True
        #       (only when pair depth is sufficient for external arb to engage)
        #   (b) Forced rescue — floor is infeasible (Hub WPLS drained),
        #       keep E2 alive by mintLPAndSell via Joey's PLS
        try:
            signal = get_ladder_signal()
            if signal.should_ladder:
                log.info(
                    "E2 [ladder]: mode=%s, gap=%.2f%%, disp=%.1f GIBS, price=%.1f PLS",
                    signal.mode, signal.gap_pct, signal.displacement_gibs, signal.gibs_price_pls,
                )
                return True
            # Rescue path: floor infeasible but price known — simulate() will
            # construct a forced ladder signal and run mintLPAndSell via Joey.
            if (not floor_feasible) and signal.gibs_price_pls > 0:
                joey_pls = w3_read.eth.get_balance(JOEY_WALLET)
                # Minimum PLS needed: wpls_needed for LP side + 2 TX gas headroom
                # (~1500 PLS worst case). 200K PLS floor already maintained by gas_guard.
                if joey_pls >= 200_000 * 10**18:
                    log.info(
                        "E2 [rescue]: floor infeasible, Joey PLS=%d — will force LADDER",
                        joey_pls // 10**18,
                    )
                    return True
        except Exception as exc:
            log.debug("E2: ladder oracle check failed in is_ready: %s", exc)

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

        # Check AFF availability (Hub + Joey wallet, or acquirable via DEX)
        gas_cost_extra = 0  # extra gas if AFF acquisition needed
        aff_needed = signal.mint_count * 10**18
        aff_in_hub = self._aff_in_hub()
        aff_in_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
        if aff_in_hub + aff_in_joey < aff_needed:
            # AFF insufficient — check if we can acquire with Joey's PLS
            shortfall = aff_needed - (aff_in_hub + aff_in_joey)
            _, acquire_cost = self._cheapest_aff_route(shortfall)
            joey_pls = w3_read.eth.get_balance(JOEY_WALLET)
            if joey_pls < acquire_cost + 200_000 * 10**18:
                raise SimulationFailed(
                    f"LADDER: AFF {(aff_in_hub + aff_in_joey) // 10**18} < needed {signal.mint_count}, "
                    f"PLS too low to acquire"
                )
            # AFF acquirable — include acquisition gas in cost estimate
            gas_cost_extra = AFF_ACQUIRE_GAS_ESTIMATE * w3_read.eth.gas_price
            log.info("E2 sim: AFF acquirable (%d AFF for ~%d PLS)",
                     shortfall // 10**18, acquire_cost // 10**18)

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

        return pls_out, gas_cost_wei + gas_cost_extra

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

        # 2. Check floor harvest feasibility first
        floor_feasible = False
        gas_price = w3_read.eth.gas_price
        hub = self._get_hub()
        if self._has_floor_harvest(hub):
            lp_bps = 10000 - HARVEST_SELL_BPS
            quote = self._quote_floor_cycle(hub, HARVEST_MINT_COUNT, lp_bps)
            if quote:
                feasible, wpls_needed, wpls_from_sell, net_wpls, lp_gibs, sell_gibs = quote
                floor_feasible = feasible

        # 3. Organic ladder: oracle genuinely signals it (gap big enough for
        # external arb bots to close). With the oracle's depth gate in place,
        # this only fires when pair depth is sufficient — won't happen at
        # current depths, but when GIBS/FED deepens it will.
        if signal and signal.should_ladder:
            try:
                self._last_sim_mode = DSSMode(signal.mode.lower())
                return self._simulate_ladder(signal)
            except SimulationFailed:
                raise
            except Exception as exc:
                log.warning("E2: ladder sim failed (%s), falling through to forced-ladder", exc)

        # 4. Forced ladder RESCUE: floor is infeasible (Hub WPLS drained) and
        # oracle says HARVEST_ONLY (not enough depth for organic ladder).
        # _simulate_ladder uses Joey's PLS via msg.value so it works with
        # Hub WPLS=0. Without this, E2 would silently skip every cycle until
        # Hub was manually refilled.
        if not floor_feasible and signal and signal.gibs_price_pls > 0:
            try:
                from ..oracle.ladder_oracle import LadderSignal
                forced = LadderSignal(
                    should_ladder=True, mode="LADDER",
                    gibs_price_pls=signal.gibs_price_pls,
                    gap_pct=signal.gap_pct,
                    arb_threshold_pct=signal.arb_threshold_pct,
                    displacement_gibs=float(HARVEST_MINT_COUNT),
                    mint_count=HARVEST_MINT_COUNT,
                    # burn_bps=0 — user policy: accumulate LP, do not burn
                    lp_bps=3000, burn_bps=0,
                    tvl_pls=signal.tvl_pls,
                    notes=f"FORCED rescue: floor infeasible (original mode={signal.mode})",
                )
                self._last_ladder_signal = forced
                self._last_sim_mode = DSSMode.LADDER
                log.info("E2: forcing LADDER rescue — floor infeasible, using Joey PLS")
                return self._simulate_ladder(forced)
            except SimulationFailed:
                raise
            except Exception as exc:
                log.warning("E2: forced ladder rescue failed (%s), falling through", exc)

        # 4. Fall through to existing HARVEST simulation
        self._last_sim_mode = DSSMode.HARVEST

        # FloorHarvestModule path — already checked feasibility above
        if floor_feasible and quote:
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
        Execute LADDER mode: use the signal simulate() already built,
        prime if needed, then mintLPAndSell with calibrated displacement.

        We deliberately trust self._last_ladder_signal instead of re-reading
        the oracle. The simulate() → execute() pipeline already made this
        decision; re-reading here would bypass the upstream decision and
        create the "LADDER signal gone — falling back to HARVEST" flap that
        burned money in cycle 44 of the initial run.
        """
        from ..core.event_logger import events as _events

        tx_hashes = []
        gas_spent = 0

        signal = self._last_ladder_signal
        if signal is None or not signal.should_ladder:
            # Should not happen in normal flow — simulate() sets this before
            # execute() is called. Defensive fallback to harvest.
            log.warning("E2: _execute_ladder called without prior ladder signal")
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
            # Purchase cost: mint_count AFF (1 AFF per GIBS).
            # LP partner cost: ~mint_count * (R_aff/R_gibs) AFF when doing 100% LP.
            # We estimate 2.2x mint_count to cover both Purchase + LP matching.
            aff_per_cycle = int(signal.mint_count * 2.2)
            aff_needed = aff_per_cycle * 10**18
            aff_in_hub = self._aff_in_hub()
            if aff_in_hub < aff_needed:
                AFF_BATCH_CYCLES = 30
                aff_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
                desired_deposit = aff_per_cycle * AFF_BATCH_CYCLES * 10**18
                deposit_amount = min(desired_deposit, aff_joey)
                if deposit_amount < aff_needed:
                    # Joey wallet AFF insufficient — acquire from DEX
                    acquire_amount = desired_deposit - aff_joey
                    log.info("E2 LADDER: AFF shortfall — acquiring %d AFF from DEX",
                             acquire_amount // 10**18)
                    acq_hashes, acq_gas = self._acquire_aff(acquire_amount, hub, dry_run)
                    tx_hashes.extend(acq_hashes)
                    gas_spent += acq_gas

                    # _acquire_aff deposits directly into Hub (both routes).
                    # Re-check Hub balance — if sufficient, skip manual deposit.
                    aff_in_hub = self._aff_in_hub()
                    if aff_in_hub >= aff_needed:
                        log.info("E2 LADDER: AFF acquired — Hub now has %d, skipping deposit",
                                 aff_in_hub // 10**18)
                    else:
                        aff_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
                        if aff_joey + aff_in_hub < aff_needed:
                            return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                                tx_hashes=tx_hashes,
                                                notes=f"LADDER: insufficient AFF after acquire (hub={aff_in_hub//10**18} joey={aff_joey//10**18})")
                        deposit_amount = aff_joey

                if aff_in_hub < aff_needed and deposit_amount > 0:
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

            # 3. Thin-pool displacement strategy
            #
            # LP on GIBS/AFF (deep — position building, fee earning).
            # Sell on the thinnest GIBS pair (GIBS/ATROPA, GIBS/VOID, etc.)
            # to create 20-30% price impact with just 17 GIBS.
            # Arb bots buy cheap GIBS from the thin pool, sell into deep pools
            # → volume flows through our GIBS/AFF LP → we earn fees.
            #
            gibs_needed = signal.mint_count * 10**18

            # Initialize sell vars (used by legacy path and post-TX logging)
            aff_cs = Web3.to_checksum_address(AFFECTION)
            wpls_cs = Web3.to_checksum_address(WPLS)
            gibs_cs = Web3.to_checksum_address(GIBS_LAU)
            sell_path = [gibs_cs, aff_cs, wpls_cs]
            sell_dex = 1
            expected_sell = 0
            min_sell_out = 0

            # 4. Try atomic mintLPAndSellPair
            if self._has_mint_lp_sell_pair(hub):
                # Find thinnest GIBS pair for max displacement
                thin_pair, thin_other, thin_rg, thin_dex = self._find_thinnest_pair()

                if thin_pair and thin_rg > 0:
                    sell_gibs_wei = gibs_needed * (10000 - signal.lp_bps) // 10000

                    # Build sell path through thin pair: [GIBS, thin_other, WPLS]
                    thin_other_cs = Web3.to_checksum_address(thin_other)
                    if thin_other_cs.lower() == wpls_cs.lower():
                        sell_path = [gibs_cs, wpls_cs]
                    else:
                        sell_path = [gibs_cs, thin_other_cs, wpls_cs]
                    sell_dex = thin_dex

                    from ..oracle.price import get_amounts_out_v2, get_amounts_out
                    try:
                        if sell_dex == 1:
                            amounts = get_amounts_out_v2(sell_gibs_wei, sell_path)
                        else:
                            amounts = get_amounts_out(sell_gibs_wei, sell_path)
                        expected_sell = amounts[-1] if amounts else 0
                    except Exception:
                        expected_sell = 0
                    min_sell_out = int(expected_sell * 85 / 100) if expected_sell else 0

                    sell_impact = 17 / thin_rg * 200 if thin_rg > 0 else 0

                    log.info(
                        "E2: DISPLACE — mint %d, LP %d%% on GIBS/AFF, sell %d%% into "
                        "%s (R=%d GIBS, ~%.0f%% impact) sell=%s min=%.0f PLS [ATOMIC]",
                        signal.mint_count, signal.lp_bps / 100,
                        (10000 - signal.lp_bps) / 100,
                        thin_pair[-8:], int(thin_rg),
                        sell_impact,
                        "->".join(a[-6:] for a in sell_path),
                        min_sell_out / 1e18,
                    )

                    result = self._execute_harvest_pair(
                        lau=GIBS_LAU,
                        payment_token=AFFECTION,
                        lp_partner=AFFECTION,   # LP on GIBS/AFF
                        prime_count=signal.mint_count,
                        purchase_amt=signal.mint_count,
                        lp_bps=signal.lp_bps,
                        sell_path=sell_path,
                        sell_dex=sell_dex,
                        min_sell_out=min_sell_out,
                        dry_run=dry_run,
                    )
                else:
                    # No thin pair found — fall back to sell through AFF
                    sell_gibs_wei = gibs_needed * (10000 - signal.lp_bps) // 10000
                    sell_path = [gibs_cs, aff_cs, wpls_cs]
                    from ..oracle.price import get_amounts_out_v2
                    try:
                        amounts = get_amounts_out_v2(sell_gibs_wei, sell_path)
                        expected_sell = amounts[-1] if amounts else 0
                    except Exception:
                        expected_sell = 0
                    min_sell_out = int(expected_sell * 90 / 100) if expected_sell else 0

                    log.info(
                        "E2: HARVEST — mint %d, LP %d%% on GIBS/AFF, sell via AFF "
                        "(no thin pair) min=%.0f PLS [ATOMIC]",
                        signal.mint_count, signal.lp_bps / 100, min_sell_out / 1e18,
                    )
                    result = self._execute_harvest_pair(
                        lau=GIBS_LAU,
                        payment_token=AFFECTION,
                        lp_partner=AFFECTION,
                        prime_count=signal.mint_count,
                        purchase_amt=signal.mint_count,
                        lp_bps=signal.lp_bps,
                        sell_path=sell_path,
                        sell_dex=sell_dex,
                        min_sell_out=min_sell_out,
                        dry_run=dry_run,
                    )

                tx_hashes.extend(result.tx_hashes)
                gas_spent += result.gas_wei
                r = {"transactionHash": bytes.fromhex(result.tx_hashes[0]) if result.tx_hashes else b"",
                     "blockNumber": 0, "gasUsed": 0} if result.success else None

                # Self-arb: buy cheap GIBS from displaced thin pool, sell on deep pool
                if result.success and thin_pair:
                    arb_result = self._self_arb_thin_pool(
                        thin_pair, thin_other, thin_dex, dry_run=dry_run)
                    tx_hashes.extend(arb_result.tx_hashes)
                    gas_spent += arb_result.gas_wei

            else:
                # Legacy 2-TX path: primeGibs + mintLPAndSell (GIBS/WPLS)
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

                wpls_needed = self._wpls_needed_for_lp(gibs_needed * signal.lp_bps // 10000)

                log.info(
                    "E2: LADDER %s — mintLPAndSell(%d, lp=%d%%, burn=%d%%, min=%.1f PLS) "
                    "gap=%.2f%% disp=%.1f GIBS [LEGACY 2-TX]",
                    signal.mode, signal.mint_count, signal.lp_bps / 100,
                    signal.burn_bps / 100, min_sell_out / 1e18,
                    signal.gap_pct, signal.displacement_gibs,
                )

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
            # ── Probe controller integration ─────────────────────────────────
            # 1. Check if a previous sell is still within its monitoring window
            arb_response = self.probe.check_arb_response()
            if arb_response.kind is ArbResponseKind.PENDING:
                log.info("E2: probe pending — deferring this cycle")
                return EngineResult(
                    success=False, profit_wei=0, gas_wei=0,
                    tx_hashes=[], notes="probe pending",
                )

            # 2. Ask the probe controller for sell size this cycle (read-only)
            pool_reserves = self._read_gibs_wpls_reserves()
            hub_gibs = safe(erc20(GIBS_LAU), "balanceOf", JOYSTICK_HUB) or 0
            sell_gibs_wei_probe = self.probe.next_sell_gibs(hub_gibs, pool_reserves)
            if sell_gibs_wei_probe > 0:
                # Convert probe's desired sell size to a mint_count (round up)
                probe_mint_count = (sell_gibs_wei_probe + 10**18 - 1) // 10**18
            else:
                # Probe returned 0 — either hub empty or reserves zero.
                # Fall back to HARVEST_MINT_COUNT so the engine can proceed with
                # the default mint count (the pending-sell case is already caught
                # by the check_arb_response PENDING early return above).
                probe_mint_count = HARVEST_MINT_COUNT
            # ── End probe controller integration ─────────────────────────────

            mint_count = probe_mint_count
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
                    # Joey wallet AFF insufficient — acquire from DEX
                    acquire_amount = desired_deposit - aff_joey
                    log.info("E2: AFF shortfall — acquiring %d AFF from DEX",
                             acquire_amount // 10**18)
                    acq_hashes, acq_gas = self._acquire_aff(acquire_amount, hub, dry_run)
                    tx_hashes.extend(acq_hashes)
                    gas_spent += acq_gas

                    # _acquire_aff deposits directly into Hub (both routes).
                    # Re-check Hub balance — if sufficient, skip manual deposit.
                    aff_in_hub = self._aff_in_hub()
                    if aff_in_hub >= aff_needed:
                        log.info("E2: AFF acquired — Hub now has %d (need %d), skipping deposit",
                                 aff_in_hub // 10**18, aff_needed // 10**18)
                    else:
                        # Check if any AFF landed in Joey wallet (partial DEX path)
                        aff_joey = safe(erc20(AFFECTION), "balanceOf", JOEY_WALLET) or 0
                        if aff_joey + aff_in_hub < aff_needed:
                            return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                                tx_hashes=tx_hashes,
                                                notes=f"Insufficient AFF after acquire: hub={aff_in_hub//10**18} joey={aff_joey//10**18} need={aff_needed//10**18}")
                        deposit_amount = aff_joey  # deposit whatever Joey has

                if aff_in_hub < aff_needed and deposit_amount > 0:
                    log.info("E2: Hub needs AFF (has %d, needs %d) — depositing %d",
                             aff_in_hub // 10**18, aff_needed // 10**18,
                             deposit_amount // 10**18)

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

            # 3. If we owe an LP-add from a recent successful arb, do it now
            #    (placed AFTER AFF check so we don't spend PLS on LP if AFF is
            #    insufficient and the cycle would exit early anyway)
            lp_target = self.probe.lp_add_target()
            if lp_target is not None:
                lp_pair = self.probe.lp_add_pair()
                try:
                    if lp_pair and self._has_mint_lp_sell_pair(hub):
                        # Atomic LP+sell on non-WPLS pair via mintLPAndSellPair
                        lp_mint_count = (lp_target + 10**18 - 1) // 10**18
                        lp_sell_path, lp_sell_dex, lp_expected = self._best_sell_route(
                            lp_target * (10000 - HARVEST_LP_BPS) // 10000)
                        lp_min_out = int(lp_expected * 90 / 100) if lp_expected else 0
                        # Determine LP partner from pair
                        from ..core.chain import pair_contract as _pair_c
                        _pc = _pair_c(Web3.to_checksum_address(lp_pair))
                        _t0 = safe(_pc, "token0")
                        _lp_partner = safe(_pc, "token1") if _t0 and _t0.lower() == GIBS_LAU.lower() else _t0
                        if _lp_partner:
                            lp_result = self._execute_harvest_pair(
                                lau=GIBS_LAU, payment_token=AFFECTION,
                                lp_partner=_lp_partner,
                                prime_count=lp_mint_count, purchase_amt=lp_mint_count,
                                lp_bps=HARVEST_LP_BPS, sell_path=lp_sell_path,
                                sell_dex=lp_sell_dex, min_sell_out=lp_min_out,
                                dry_run=dry_run)
                        else:
                            lp_result = self._execute_lp_add_via_tgsv8(
                                lp_target, lp_pair, dry_run=dry_run)
                    elif lp_pair:
                        # Fallback: non-WPLS pair but no mintLPAndSellPair module
                        lp_result = self._execute_lp_add_via_tgsv8(
                            lp_target, lp_pair, dry_run=dry_run)
                    else:
                        # Default: LP via Hub on GIBS/WPLS
                        lp_result = self._execute_lp_only_add(lp_target, dry_run=dry_run)
                    if lp_result.success:
                        self.probe.clear_lp_add_target()
                    else:
                        self.probe.record_lp_add_failure()
                        log.warning("E2: lp_add_target failed: %s", lp_result.notes)
                except Exception as exc:
                    self.probe.record_lp_add_failure()
                    log.error("E2: lp_add_target exception: %s", exc)

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
                            # Record sell with probe controller (sell_gibs from quote)
                            try:
                                self.probe.record_sell(
                                    sell_gibs_wei=int(sell_gibs),
                                    block_number=r["blockNumber"],
                                    tx_hash=r["transactionHash"].hex(),
                                )
                            except Exception as _probe_exc:
                                log.debug("E2: probe.record_sell failed: %s", _probe_exc)

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

            # Priority 1.5: mintLPAndSellPair (atomic LP+sell on ANY pair)
            # Use this when we want to LP on a non-WPLS pair (e.g., GIBS/AFF)
            if self._has_mint_lp_sell_pair(hub):
                gibs_amount = mint_count * 10**18
                sell_gibs_wei = gibs_amount * (10000 - lp_bps) // 10000

                # Sell through the LP partner: [GIBS, AFF, WPLS]
                aff_cs = Web3.to_checksum_address(AFFECTION)
                wpls_cs = Web3.to_checksum_address(WPLS)
                gibs_cs = Web3.to_checksum_address(GIBS_LAU)
                sell_path = [gibs_cs, aff_cs, wpls_cs]
                sell_dex = 1  # V2
                from ..oracle.price import get_amounts_out_v2
                try:
                    amounts = get_amounts_out_v2(sell_gibs_wei, sell_path)
                    expected_sell = amounts[-1] if amounts else 0
                except Exception:
                    expected_sell = 0
                min_sell_out = int(expected_sell * 90 / 100) if expected_sell else 0

                result = self._execute_harvest_pair(
                    lau=GIBS_LAU,
                    payment_token=AFFECTION,
                    lp_partner=AFFECTION,  # LP on GIBS/AFF pair
                    prime_count=mint_count,
                    purchase_amt=mint_count,
                    lp_bps=lp_bps,
                    sell_path=sell_path,
                    sell_dex=sell_dex,
                    min_sell_out=min_sell_out,
                    dry_run=dry_run,
                )
                if result.success:
                    return EngineResult(
                        success=True,
                        profit_wei=revenue_wei,
                        gas_wei=gas_spent + result.gas_wei,
                        tx_hashes=tx_hashes + result.tx_hashes,
                        notes=result.notes,
                    )
                # If mintLPAndSellPair failed, fall through to primeAndSell

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
                    # Record sell with probe controller (all minted GIBS are sold here)
                    try:
                        self.probe.record_sell(
                            sell_gibs_wei=gibs_amount,
                            block_number=r["blockNumber"],
                            tx_hash=r["transactionHash"].hex(),
                        )
                    except Exception as _probe_exc:
                        log.debug("E2: probe.record_sell failed: %s", _probe_exc)

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
                # Record sell with probe controller (sell_gibs_wei computed above)
                try:
                    self.probe.record_sell(
                        sell_gibs_wei=sell_gibs_wei,
                        block_number=r["blockNumber"],
                        tx_hash=r["transactionHash"].hex(),
                    )
                except Exception as _probe_exc:
                    log.debug("E2: probe.record_sell failed: %s", _probe_exc)

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
