import json
import os
import time
import logging

from web3 import Web3

from .base import EngineBase, EngineResult
from ..core.config import (
    JOEY_WALLET, AFFECTION, WPLS,
    PULSEX_V1_ROUTER, PULSEX_V2_ROUTER,
    PULSEX_V1_FACTORY, PULSEX_V2_FACTORY,
    MAX_SLIPPAGE, RESERVE_CACHE_TTL,
    GRAPH_ARB_MIN_PROFIT_PLS, TGSV8,
    HUB_TOKENS, SEED_LAUS,
)
from ..core.chain import erc20, purchasable, router_contract, safe, w3_submit, w3_read
from ..core.executor import send_tx, approve_if_needed
from ..core.simulator import SimulationFailed, estimate_gas
from ..core.event_logger import events as _events
from ..oracle.scanner import scan_tokens
from ..oracle.profitability import rank_opportunities

log = logging.getLogger(__name__)

# Gas estimates per mode
PURCHASE_GAS_ESTIMATE = 400_000   # approve×2 + purchase + swap
CROSS_DEX_GAS_ESTIMATE = 350_000  # deposit + atomicArb + withdraw via TGSv8
CROSS_PAIR_GAS_ESTIMATE = 500_000 # 3-hop swap via router

# Mode 2 thresholds
CROSS_DEX_MIN_SPREAD_BPS = 50     # 0.5% minimum spread to consider (50 basis points)
CROSS_DEX_TEST_AMOUNT = 10 * 10**18  # 10 tokens for spread detection

# Event log file for RAZOR
_JOYSTICK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_RAZOR_LOG = os.path.join(_JOYSTICK_DIR, "data", "events", "razor.json")


def _log_razor_event(event: dict) -> None:
    """Append a timestamped event to razor.json."""
    event["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    event["epoch"] = time.time()
    try:
        os.makedirs(os.path.dirname(_RAZOR_LOG), exist_ok=True)
        with open(_RAZOR_LOG, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception:
        pass


class ArbEngine(EngineBase):
    """
    Engine 1 — RAZOR: Multi-mode arbitrage engine.

    Mode 1 (Purchase): scan_tokens() → rank → approve → Purchase → swap → PLS
    Mode 2 (CrossDex): V1↔V2 spread on same token/WPLS pair
    Mode 3 (CrossPair): Graph-based triangle arb across connected DEX pools
    """
    name = "Arb"

    def __init__(self):
        super().__init__()
        self._top_opportunity: dict | None = None
        self._pair_graph = None
        self._graph_last_refresh: float = 0

    def is_ready(self) -> bool:
        """
        Ready if ANY mode is viable:
          - Purchase mode: AFFECTION balance >= 1
          - CrossDex mode: TGSv8 deployed + PLS/WPLS > 10 (for deposit+arb)
          - CrossPair mode: PLS balance > 0 (WPLS wrapping handled by router)
        """
        # Check AFFECTION for Purchase mode
        aff = erc20(AFFECTION)
        aff_bal = safe(aff, "balanceOf", JOEY_WALLET) or 0
        if aff_bal >= 10**18:
            return True

        # Check PLS for CrossDex / CrossPair modes
        pls_bal = w3_read.eth.get_balance(JOEY_WALLET)
        if pls_bal >= 10 * 10**18:  # At least 10 PLS
            return True

        log.debug("ArbEngine not ready: AFF=%.4f, PLS=%.4f", aff_bal / 1e18, pls_bal / 1e18)
        return False

    # ── simulate() — run all modes, pick best ──────────────────────────────

    def simulate(self) -> tuple[int, int]:
        """
        Scan all modes, rank by profit, cache top opportunity.
        Returns (expected_profit_wei, expected_gas_wei).
        Raises SimulationFailed if no profitable opportunity in any mode.
        """
        gas_price = w3_read.eth.gas_price
        best_opp = None

        # Mode 1: Purchase arb
        try:
            opp = self._simulate_purchase(gas_price)
            if opp and (best_opp is None or opp["profit_wei"] > best_opp["profit_wei"]):
                best_opp = opp
        except Exception as exc:
            log.debug("Purchase mode scan failed: %s", exc)

        # Mode 2: Cross-DEX spread via TGSv8 atomicArb
        try:
            opp = self._simulate_cross_dex(gas_price)
            if opp and (best_opp is None or opp["profit_wei"] > best_opp["profit_wei"]):
                best_opp = opp
        except Exception as exc:
            log.debug("CrossDex mode scan failed: %s", exc)

        # Mode 3: Cross-pair graph arb
        try:
            opp = self._simulate_cross_pair(gas_price)
            if opp and (best_opp is None or opp["profit_wei"] > best_opp["profit_wei"]):
                best_opp = opp
        except Exception as exc:
            log.debug("CrossPair mode scan failed: %s", exc)

        if not best_opp:
            raise SimulationFailed("No profitable arb opportunities across all modes")

        self._top_opportunity = best_opp
        mode = best_opp.get("mode", "?")

        log.info(
            "ArbEngine top [%s]: profit %.4f PLS",
            mode, best_opp["profit_wei"] / 1e18,
        )

        return best_opp["profit_wei"], best_opp["gas_wei"]

    def _simulate_purchase(self, gas_price: int) -> dict | None:
        """Mode 1: Purchase → DEX arb scan."""
        gas_cost_wei = PURCHASE_GAS_ESTIMATE * gas_price

        tokens = scan_tokens()
        ranked = rank_opportunities(tokens, gas_cost_wei)

        if not ranked:
            return None

        top = ranked[0]
        log.debug(
            "Purchase mode top: %s (%s) — profit %.4f PLS (impact %.1f%%)",
            top["label"], top["symbol"], top["profit_wei"] / 1e18, top["impact_pct"],
        )

        return {
            "mode": "purchase",
            "profit_wei": top["profit_wei"],
            "gas_wei": gas_cost_wei,
            **top,
        }

    def _simulate_cross_dex(self, gas_price: int) -> dict | None:
        """
        Mode 2: V1↔V2 cross-DEX spread via TGSv8.

        Uses TGSv8.getBestAmountsOut() to find tokens where V1 and V2 prices
        diverge, then simulates atomicArb() via eth_call to verify profitability.

        Requires TGSv8 deployed and TGSV8_ADDRESS set in .env.
        """
        if not TGSV8:
            log.debug("CrossDex: TGSv8 not configured — skipping")
            return None

        from ..core.chain import tgsv8_contract, factory_contract

        tgs = tgsv8_contract()  # read-only instance
        gas_cost_wei = CROSS_DEX_GAS_ESTIMATE * gas_price

        # Collect candidate tokens: all tokens that might have pairs on BOTH DEXes
        candidates = self._cross_dex_candidates()
        if not candidates:
            log.debug("CrossDex: no dual-DEX candidates found")
            return None

        best = None

        for token_addr, label in candidates:
            try:
                # Query reserves on both DEXes via TGSv8.getReservesBoth()
                v1rA, v1rB, v2rA, v2rB = safe(
                    tgs, "getReservesBoth", token_addr, WPLS
                ) or (0, 0, 0, 0)

                # Need liquidity on BOTH DEXes
                if v1rA == 0 or v1rB == 0 or v2rA == 0 or v2rB == 0:
                    continue

                # Compute spot prices (WPLS per token) on each DEX
                # price = reserveWPLS / reserveToken
                v1_price = v1rB / v1rA  # WPLS per token on V1
                v2_price = v2rB / v2rA  # WPLS per token on V2

                if v1_price == 0 or v2_price == 0:
                    continue

                # Calculate spread in basis points
                spread_bps = abs(v1_price - v2_price) / min(v1_price, v2_price) * 10000

                if spread_bps < CROSS_DEX_MIN_SPREAD_BPS:
                    continue

                # Determine direction: buy on cheaper DEX, sell on expensive DEX
                # DEX enum: 0=V1, 1=V2
                if v1_price < v2_price:
                    buy_dex, sell_dex = 0, 1  # Buy V1 (cheaper), sell V2
                    buy_reserves = (v1rA, v1rB)
                    sell_reserves = (v2rA, v2rB)
                else:
                    buy_dex, sell_dex = 1, 0  # Buy V2 (cheaper), sell V1
                    buy_reserves = (v2rA, v2rB)
                    sell_reserves = (v1rA, v1rB)

                # Optimal input: cap at 5% of the smaller pool's WPLS reserve
                # to limit price impact
                smaller_wpls_reserve = min(v1rB, v2rB)
                max_input = smaller_wpls_reserve * 5 // 100

                # Also cap at Joey's available WPLS/PLS
                wpls_bal = safe(erc20(WPLS), "balanceOf", JOEY_WALLET) or 0
                pls_bal = w3_read.eth.get_balance(JOEY_WALLET)
                available = wpls_bal + pls_bal - gas_cost_wei
                if available <= 0:
                    continue
                trade_amount = min(max_input, available)
                if trade_amount < 10**16:  # At least 0.01 WPLS
                    continue

                # Simulate profit: buy tokenOut with WPLS, sell tokenOut back to WPLS
                # Step 1: WPLS → token on buy_dex (Uniswap v2 formula)
                buy_r_in = buy_reserves[1]   # WPLS reserve on buy side
                buy_r_out = buy_reserves[0]  # Token reserve on buy side
                tokens_bought = (buy_r_out * trade_amount * 997) // (buy_r_in * 1000 + trade_amount * 997)

                if tokens_bought == 0:
                    continue

                # Step 2: token → WPLS on sell_dex
                sell_r_in = sell_reserves[0]   # Token reserve on sell side
                sell_r_out = sell_reserves[1]  # WPLS reserve on sell side
                wpls_received = (sell_r_out * tokens_bought * 997) // (sell_r_in * 1000 + tokens_bought * 997)

                profit_wei = wpls_received - trade_amount - gas_cost_wei
                if profit_wei <= 0:
                    continue

                log.debug(
                    "CrossDex: %s spread=%.0fbps input=%.4f profit=%.4f PLS (buy=%s sell=%s)",
                    label, spread_bps, trade_amount / 1e18, profit_wei / 1e18,
                    "V1" if buy_dex == 0 else "V2",
                    "V1" if sell_dex == 0 else "V2",
                )

                if best is None or profit_wei > best["profit_wei"]:
                    best = {
                        "mode": "cross_dex",
                        "profit_wei": profit_wei,
                        "gas_wei": gas_cost_wei,
                        "token": token_addr,
                        "label": label,
                        "trade_amount": trade_amount,
                        "buy_dex": buy_dex,
                        "sell_dex": sell_dex,
                        "spread_bps": spread_bps,
                        "tokens_bought": tokens_bought,
                        "wpls_received": wpls_received,
                    }

            except Exception as exc:
                log.debug("CrossDex scan error for %s: %s", label, exc)
                continue

        return best

    def _cross_dex_candidates(self) -> list[tuple[str, str]]:
        """
        Build list of (token_address, label) for tokens with pairs on BOTH
        V1 and V2 DEXes against WPLS.

        Uses pair_registry.json via DataStore — zero RPC calls.
        Falls back to live scan only if registry is empty/missing.
        """
        from ..oracle.data_store import DataStore

        store = DataStore.get()
        dual = store.dual_dex_tokens(base_token=WPLS)

        if dual:
            candidates = [(addr, sym) for addr, sym, _v1, _v2 in dual]
            log.debug("CrossDex: %d dual-DEX candidates from pair_registry", len(candidates))
            return candidates

        # Fallback: live scan (original logic, only if cache is empty)
        log.info("CrossDex: pair_registry empty — falling back to live factory scan")
        return self._cross_dex_candidates_live()

    def _cross_dex_candidates_live(self) -> list[tuple[str, str]]:
        """Original live factory scan — only used as fallback when pair_registry is empty."""
        from ..core.chain import factory_contract

        seen = set()
        candidates = []

        # Start with hub tokens and seed LAUs
        token_list = [(label, addr) for label, addr in SEED_LAUS]
        token_list += [("HUB", addr) for addr in HUB_TOKENS if addr.lower() != WPLS.lower()]

        # Add tokens from scanner cache if available
        try:
            cached = scan_tokens()
            for rec in cached:
                addr = rec.get("address", "")
                if addr:
                    token_list.append((rec.get("label", rec.get("symbol", "?")), addr))
        except Exception:
            pass

        # Filter to tokens with pairs on BOTH V1 and V2
        v1_factory = factory_contract(PULSEX_V1_FACTORY)
        v2_factory = factory_contract(PULSEX_V2_FACTORY)

        for label, addr in token_list:
            addr_lower = addr.lower()
            if addr_lower in seen or addr_lower == WPLS.lower():
                continue
            seen.add(addr_lower)

            addr_cs = Web3.to_checksum_address(addr)

            # Quick check: does this token have pairs on BOTH factories?
            v1_pair = safe(v1_factory, "getPair", addr_cs, WPLS)
            if not v1_pair or v1_pair == "0x" + "0" * 40:
                continue

            v2_pair = safe(v2_factory, "getPair", addr_cs, WPLS)
            if not v2_pair or v2_pair == "0x" + "0" * 40:
                continue

            candidates.append((addr_cs, label))

        log.debug("CrossDex: %d dual-DEX candidates found (live scan)", len(candidates))
        return candidates

    def _simulate_cross_pair(self, gas_price: int) -> dict | None:
        """Mode 3: Graph-based triangle arb scan."""
        from ..oracle.pair_discovery import (
            load_pair_graph, discover_pairs, refresh_reserves, reserves_stale,
        )
        from ..oracle.graph import scan_all_triangles

        # Load or build pair graph (with caching)
        now = time.time()
        if self._pair_graph is None or (now - self._graph_last_refresh) > RESERVE_CACHE_TTL:
            cached = load_pair_graph()
            if cached:
                if reserves_stale(cached):
                    refresh_reserves(cached)
                self._pair_graph = cached
            else:
                log.info("Building pair graph (first scan)...")
                self._pair_graph = discover_pairs()
            self._graph_last_refresh = now

        graph = self._pair_graph
        if graph is None or graph.edge_count == 0:
            return None

        # Scan triangles from primary hubs
        cycles = scan_all_triangles(
            graph,
            gas_price_wei=gas_price,
            min_profit_pls=GRAPH_ARB_MIN_PROFIT_PLS,
        )

        if not cycles:
            return None

        top = cycles[0]
        log.debug(
            "CrossPair mode top: %s — profit %.4f PLS (score=%.2f)",
            top.path_symbols, top.net_profit_pls / 1e18, top.score,
        )

        return {
            "mode": "cross_pair",
            "profit_wei": top.net_profit_pls,
            "gas_wei": CROSS_PAIR_GAS_ESTIMATE * gas_price,
            "cycle": top,
        }

    # ── execute() — dispatch by mode ────────────────────────────────────────

    def execute(self, dry_run: bool = False) -> EngineResult:
        """Execute the top arb opportunity found in simulate()."""
        if self._top_opportunity is None:
            try:
                self.simulate()
            except SimulationFailed as exc:
                return EngineResult(success=False, profit_wei=0, gas_wei=0, notes=str(exc))

        opp = self._top_opportunity
        self._top_opportunity = None  # Consume — force re-scan next cycle

        mode = opp.get("mode", "purchase")

        if mode == "purchase":
            result = self._execute_purchase(opp, dry_run)
        elif mode == "cross_dex":
            result = self._execute_cross_dex(opp, dry_run)
        elif mode == "cross_pair":
            result = self._execute_cross_pair(opp, dry_run)
        else:
            result = EngineResult(success=False, profit_wei=0, gas_wei=0, notes=f"Unknown mode: {mode}")

        # Log to razor.json
        _log_razor_event({
            "mode": mode,
            "success": result.success,
            "profit_pls": result.profit_pls,
            "gas_pls": result.gas_pls,
            "net_pls": result.net_pls,
            "tx_hashes": result.tx_hashes,
            "notes": result.notes,
            "dry_run": dry_run,
        })

        return result

    def _execute_purchase(self, opp: dict, dry_run: bool) -> EngineResult:
        """Mode 1: approve → Purchase → approve → swapExactTokensForETH."""
        token_addr   = opp["address"]
        payment_addr = opp["payment"]
        token_amount = opp["token_amount"]
        expected_pls = opp["dex_out_wei"]
        token_sym    = opp.get("symbol", "?")

        router = router_contract(w3=w3_submit)
        token_c   = w3_submit.eth.contract(address=token_addr,   abi=purchasable(token_addr).abi)
        payment_c = w3_submit.eth.contract(address=payment_addr, abi=erc20(payment_addr).abi)
        token_erc = w3_submit.eth.contract(address=token_addr,   abi=erc20(token_addr).abi)

        deadline = int(time.time()) + 300
        min_pls  = int(expected_pls * (1 - MAX_SLIPPAGE))

        payment_cost = token_amount * opp["rate"] // 10**18
        tx_hashes = []
        gas_spent = 0

        try:
            log.info("Purchase Arb: %s — buying %s %s for %.4f payment tokens",
                     opp["label"], token_amount / 1e18, token_sym, payment_cost / 1e18)

            # Step 1: Approve payment token to target contract
            r = approve_if_needed(payment_c, token_addr, payment_cost, payment_addr, dry_run=dry_run)
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Step 2: Purchase tokens at fixed market rate
            r = send_tx(
                token_c.functions.Purchase(payment_addr, token_amount),
                f"Purchase {token_sym}",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Verify we received tokens
            received = safe(token_erc, "balanceOf", JOEY_WALLET) or 0
            if not dry_run and received == 0:
                raise AssertionError(f"Purchase returned 0 {token_sym}")

            # Step 3: Approve router to spend received tokens
            sell_amount = received if not dry_run else token_amount
            r = approve_if_needed(token_erc, PULSEX_V1_ROUTER, sell_amount, token_sym, dry_run=dry_run)
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Step 4: Swap tokens -> native PLS
            r = send_tx(
                router.functions.swapExactTokensForETH(
                    sell_amount, min_pls, [token_addr, WPLS], JOEY_WALLET, deadline
                ),
                f"Swap {token_sym} -> PLS",
                dry_run=dry_run,
                skip_simulate=True,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            log.info("Purchase arb complete: %s. TXs: %d", token_sym, len(tx_hashes))
            return EngineResult(
                success=True,
                profit_wei=expected_pls,
                gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"PurchaseArb: {opp['label']} ({token_sym})",
            )

        except (SimulationFailed, AssertionError, Exception) as exc:
            log.error("Purchase arb execute failed: %s", exc)
            return EngineResult(
                success=False, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes, notes=str(exc),
            )

    def _execute_cross_dex(self, opp: dict, dry_run: bool) -> EngineResult:
        """
        Mode 2: Cross-DEX arbitrage via TGSv8.atomicArb().

        Flow:
          1. Wrap PLS → WPLS if needed
          2. Approve TGSv8 to pull WPLS
          3. Deposit WPLS into TGSv8 working balance
          4. Call TGSv8.atomicArb(WPLS, token, amount, buyDex, sellDex, minProfit)
          5. Withdraw profit (WPLS) from TGSv8
          6. Optionally unwrap WPLS → PLS
        """
        from ..core.chain import tgsv8_contract
        from ..core import wallet

        token_addr = opp["token"]
        trade_amount = opp["trade_amount"]
        buy_dex = opp["buy_dex"]
        sell_dex = opp["sell_dex"]
        label = opp.get("label", "?")
        expected_profit = opp["profit_wei"]

        tgs_addr = Web3.to_checksum_address(TGSV8)
        tgs_read = tgsv8_contract()
        tgs_write = tgsv8_contract(w3=w3_submit)

        tx_hashes = []
        gas_spent = 0

        try:
            log.info(
                "CrossDex Arb: %s — %.4f WPLS, buy=%s sell=%s, spread=%.0fbps",
                label, trade_amount / 1e18,
                "V1" if buy_dex == 0 else "V2",
                "V1" if sell_dex == 0 else "V2",
                opp.get("spread_bps", 0),
            )

            # Step 1: Ensure WPLS balance (wrap PLS if needed)
            wpls_c = erc20(WPLS)
            wpls_submit = w3_submit.eth.contract(address=WPLS, abi=wpls_c.abi)
            wpls_bal = safe(wpls_c, "balanceOf", JOEY_WALLET) or 0

            if wpls_bal < trade_amount and not dry_run:
                wrap_amount = trade_amount - wpls_bal + 10**15
                log.info("  Wrapping %.4f PLS → WPLS", wrap_amount / 1e18)
                nonce = wallet.next_nonce()
                tx = {
                    "to": WPLS,
                    "from": JOEY_WALLET,
                    "value": wrap_amount,
                    "gas": 50_000,
                    "gasPrice": w3_submit.eth.gas_price,
                    "nonce": nonce,
                    "chainId": 369,
                }
                signed = wallet.account.sign_transaction(tx)
                tx_hash = w3_submit.eth.send_raw_transaction(signed.raw_transaction)
                receipt = w3_submit.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                assert receipt["status"] == 1, "WPLS wrap failed"
                tx_hashes.append(tx_hash.hex())
                gas_spent += receipt["gasUsed"] * receipt.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Step 2: Approve TGSv8 to pull WPLS
            r = approve_if_needed(wpls_submit, tgs_addr, trade_amount, "WPLS→TGSv8", dry_run=dry_run)
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Step 3: Deposit WPLS into TGSv8 working balance
            r = send_tx(
                tgs_write.functions.deposit(WPLS, trade_amount),
                f"Deposit {trade_amount / 1e18:.4f} WPLS into TGSv8",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Step 4: TGSv8 needs to approve routers for the tokens it will swap
            # atomicArb handles internal approvals — the contract manages this

            # Step 5: Call atomicArb() — atomic: reverts if profit < minProfit
            min_profit = max(0, int(expected_profit * 0.8))  # 80% of expected as safety
            r = send_tx(
                tgs_write.functions.atomicArb(
                    WPLS,           # tokenIn
                    token_addr,     # tokenOut
                    trade_amount,   # amountIn
                    buy_dex,        # buyOn (DEX enum: 0=V1, 1=V2)
                    sell_dex,       # sellOn
                    min_profit,     # minProfit
                ),
                f"atomicArb {label} ({trade_amount / 1e18:.4f} WPLS)",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Step 6: Withdraw all WPLS from TGSv8 (principal + profit)
            if not dry_run:
                tgs_wpls_bal = safe(tgs_read, "bal", WPLS) or 0
                if tgs_wpls_bal > 0:
                    r = send_tx(
                        tgs_write.functions.withdraw(WPLS, tgs_wpls_bal),
                        f"Withdraw {tgs_wpls_bal / 1e18:.4f} WPLS from TGSv8",
                        dry_run=dry_run,
                    )
                    if r:
                        tx_hashes.append(r["transactionHash"].hex())
                        gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            log.info("CrossDex arb complete: %s. TXs: %d", label, len(tx_hashes))
            return EngineResult(
                success=True,
                profit_wei=expected_profit,
                gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"CrossDexArb: {label} buy={'V1' if buy_dex == 0 else 'V2'} sell={'V1' if sell_dex == 0 else 'V2'}",
            )

        except (SimulationFailed, AssertionError, Exception) as exc:
            log.error("CrossDex arb execute failed: %s", exc)
            # Attempt to recover any WPLS left in TGSv8
            try:
                if not dry_run:
                    tgs_wpls_bal = safe(tgs_read, "bal", WPLS) or 0
                    if tgs_wpls_bal > 0:
                        log.info("  Recovering %.4f WPLS from TGSv8", tgs_wpls_bal / 1e18)
                        send_tx(
                            tgs_write.functions.withdraw(WPLS, tgs_wpls_bal),
                            "Recovery withdraw",
                            dry_run=False,
                        )
            except Exception as recovery_exc:
                log.error("  Recovery withdraw also failed: %s", recovery_exc)

            return EngineResult(
                success=False, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes, notes=str(exc),
            )

    def _execute_cross_pair(self, opp: dict, dry_run: bool) -> EngineResult:
        """
        Mode 3: Triangle arb via multi-hop router swaps.

        Execution strategy (Option B — simulate-then-execute):
          1. Build swap path from cycle
          2. For WPLS-rooted triangles: swapExactTokensForTokens per hop
          3. Each hop uses 99% of simulated output as minAmountOut
        """
        cycle = opp.get("cycle")
        if not cycle:
            return EngineResult(success=False, profit_wei=0, gas_wei=0, notes="No cycle data")

        path = cycle.path
        pools = cycle.pools
        opt_input = cycle.optimal_input

        if opt_input == 0:
            return EngineResult(success=False, profit_wei=0, gas_wei=0, notes="Zero optimal input")

        tx_hashes = []
        gas_spent = 0

        try:
            log.info("CrossPair Arb: %s — input %.4f of %s",
                     cycle.path_symbols, opt_input / 1e18,
                     self._pair_graph.symbol(path[0]) if self._pair_graph else path[0][:10])

            # Determine if this is a WPLS-rooted triangle
            is_wpls_rooted = path[0].lower() == WPLS.lower()

            if is_wpls_rooted:
                result = self._execute_wpls_triangle(cycle, dry_run)
            else:
                # For non-WPLS triangles, execute hop-by-hop through router
                result = self._execute_generic_triangle(cycle, dry_run)

            return result

        except Exception as exc:
            log.error("CrossPair arb execute failed: %s", exc)
            return EngineResult(
                success=False, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes, notes=str(exc),
            )

    def _execute_wpls_triangle(self, cycle, dry_run: bool) -> EngineResult:
        """
        Execute a WPLS-rooted triangle via PulseX router.
        WPLS → B → C → WPLS using swapExactTokensForTokens per hop,
        with final hop using swapExactTokensForETH to get native PLS back.
        """
        from ..oracle.price import simulate_swap_exact

        path = cycle.path
        pools = cycle.pools
        opt_input = cycle.optimal_input

        # Build the full swap path for the router
        # For a triangle WPLS→B→C→WPLS, we can do it in one router call
        # if all hops are on the same DEX factory
        same_factory = len(set(p.factory for p in pools)) == 1
        factory = pools[0].factory if same_factory else None

        # Choose router based on factory
        if factory == "V2":
            router_addr = PULSEX_V2_ROUTER
        else:
            router_addr = PULSEX_V1_ROUTER

        from ..core.chain import ROUTER_ABI
        router = w3_submit.eth.contract(
            address=Web3.to_checksum_address(router_addr), abi=ROUTER_ABI
        )

        deadline = int(time.time()) + 300
        tx_hashes = []
        gas_spent = 0

        if same_factory:
            # Single router call with full path
            swap_path = [Web3.to_checksum_address(p) for p in path]
            min_out = int(cycle.expected_output * (1 - MAX_SLIPPAGE))

            # Need WPLS balance — wrap PLS if needed
            wpls_c = erc20(WPLS)
            wpls_c_submit = w3_submit.eth.contract(address=WPLS, abi=wpls_c.abi)
            wpls_bal = safe(wpls_c, "balanceOf", JOEY_WALLET) or 0

            if wpls_bal < opt_input:
                # Wrap PLS → WPLS
                wrap_amount = opt_input - wpls_bal + 10**15  # tiny buffer
                log.info("  Wrapping %.4f PLS → WPLS", wrap_amount / 1e18)
                if not dry_run:
                    # WPLS deposit() is just sending ETH to WPLS contract
                    from ..core.chain import ROUTER_ABI
                    # Use low-level send for WPLS deposit
                    from ..core import wallet
                    nonce = wallet.next_nonce()
                    tx = {
                        "to": WPLS,
                        "from": JOEY_WALLET,
                        "value": wrap_amount,
                        "gas": 50_000,
                        "gasPrice": w3_submit.eth.gas_price,
                        "nonce": nonce,
                        "chainId": 369,
                    }
                    signed = wallet.account.sign_transaction(tx)
                    tx_hash = w3_submit.eth.send_raw_transaction(signed.raw_transaction)
                    receipt = w3_submit.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                    assert receipt["status"] == 1, "WPLS wrap failed"
                    tx_hashes.append(tx_hash.hex())
                    gas_spent += receipt["gasUsed"] * receipt.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Approve router to spend WPLS
            r = approve_if_needed(wpls_c_submit, router_addr, opt_input, "WPLS", dry_run=dry_run)
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Execute the multi-hop swap
            log.info("  Executing %d-hop swap: %s (min_out=%.4f)",
                     len(pools), " → ".join(swap_path[:3]) + "...", min_out / 1e18)

            r = send_tx(
                router.functions.swapExactTokensForTokens(
                    opt_input, min_out, swap_path, JOEY_WALLET, deadline
                ),
                f"Triangle swap: {cycle.path_symbols}",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            log.info("CrossPair arb complete. TXs: %d", len(tx_hashes))
            return EngineResult(
                success=True,
                profit_wei=cycle.net_profit_pls,
                gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"CrossPairArb: {cycle.path_symbols} [{factory}]",
            )

        else:
            # Mixed factory — execute hop by hop
            return self._execute_generic_triangle(cycle, dry_run)

    def _execute_generic_triangle(self, cycle, dry_run: bool) -> EngineResult:
        """
        Execute a triangle hop-by-hop when pools span different factories.
        Each hop is a separate swapExactTokensForTokens call on the appropriate router.
        """
        from ..core.chain import ROUTER_ABI

        path = cycle.path
        pools = cycle.pools
        opt_input = cycle.optimal_input

        deadline = int(time.time()) + 300
        tx_hashes = []
        gas_spent = 0
        current_amount = opt_input

        # Simulate each hop to get expected intermediate amounts
        intermediate_amounts = [opt_input]
        from ..oracle.price import simulate_swap_exact
        for i, pool in enumerate(pools):
            token_in = path[i].lower()
            if pool.token_a.lower() == token_in:
                r_in, r_out = pool.reserve_a, pool.reserve_b
            else:
                r_in, r_out = pool.reserve_b, pool.reserve_a
            out = simulate_swap_exact(intermediate_amounts[-1], r_in, r_out)
            intermediate_amounts.append(out)

        # First hop: may need WPLS wrap + approve
        start_token = Web3.to_checksum_address(path[0])
        if start_token.lower() == WPLS.lower():
            wpls_c = erc20(WPLS)
            wpls_c_submit = w3_submit.eth.contract(address=WPLS, abi=wpls_c.abi)
            wpls_bal = safe(wpls_c, "balanceOf", JOEY_WALLET) or 0
            if wpls_bal < opt_input and not dry_run:
                wrap_amount = opt_input - wpls_bal + 10**15
                from ..core import wallet
                nonce = wallet.next_nonce()
                tx = {
                    "to": WPLS, "from": JOEY_WALLET, "value": wrap_amount,
                    "gas": 50_000, "gasPrice": w3_submit.eth.gas_price,
                    "nonce": nonce, "chainId": 369,
                }
                signed = wallet.account.sign_transaction(tx)
                tx_hash = w3_submit.eth.send_raw_transaction(signed.raw_transaction)
                receipt = w3_submit.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                assert receipt["status"] == 1, "WPLS wrap failed"
                tx_hashes.append(tx_hash.hex())
                gas_spent += receipt["gasUsed"] * receipt.get("effectiveGasPrice", w3_submit.eth.gas_price)

        # Execute each hop
        for i, pool in enumerate(pools):
            token_in = Web3.to_checksum_address(path[i])
            token_out = Web3.to_checksum_address(path[i + 1])

            router_addr = PULSEX_V2_ROUTER if pool.factory == "V2" else PULSEX_V1_ROUTER
            router = w3_submit.eth.contract(
                address=Web3.to_checksum_address(router_addr), abi=ROUTER_ABI
            )

            # Get current balance of input token for this hop
            if i == 0:
                swap_amount = opt_input
            else:
                # Use actual balance received from previous hop
                tok_c = erc20(token_in)
                swap_amount = safe(tok_c, "balanceOf", JOEY_WALLET) or 0
                if dry_run:
                    swap_amount = intermediate_amounts[i]

            min_out = int(intermediate_amounts[i + 1] * (1 - MAX_SLIPPAGE))

            # Approve router for this token
            tok_submit = w3_submit.eth.contract(address=token_in, abi=erc20(token_in).abi)
            r = approve_if_needed(tok_submit, router_addr, swap_amount, f"hop{i}", dry_run=dry_run)
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            # Swap
            hop_path = [token_in, token_out]
            r = send_tx(
                router.functions.swapExactTokensForTokens(
                    swap_amount, min_out, hop_path, JOEY_WALLET, deadline
                ),
                f"Hop {i+1}/{len(pools)}: {pool.symbol_a}/{pool.symbol_b} [{pool.factory}]",
                dry_run=dry_run,
            )
            if r:
                tx_hashes.append(r["transactionHash"].hex())
                gas_spent += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

        log.info("Generic triangle arb complete. TXs: %d", len(tx_hashes))
        return EngineResult(
            success=True,
            profit_wei=cycle.net_profit_pls,
            gas_wei=gas_spent,
            tx_hashes=tx_hashes,
            notes=f"CrossPairArb: {cycle.path_symbols} [mixed]",
        )


if __name__ == "__main__":
    import argparse, logging as _logging

    parser = argparse.ArgumentParser(
        description="RAZOR — Engine 1 multi-mode arbitrage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run",     action="store_true", help="simulate only, no TX sent")
    parser.add_argument("--execute",     action="store_true", help="live execution (sends TX!)")
    parser.add_argument("--force-scan",  action="store_true", help="bypass token discovery cache")
    parser.add_argument("--mode",        choices=["all", "purchase", "cross_dex", "cross_pair"],
                        default="all",   help="restrict to one arb mode (default: all)")
    parser.add_argument("--status",      action="store_true", help="print engine readiness and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args()

    _logging.basicConfig(
        level=_logging.DEBUG if args.verbose else _logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    if args.force_scan:
        from ..oracle.scanner import invalidate_cache
        invalidate_cache()

    engine = ArbEngine()

    if args.status:
        print(engine.status_line())
        raise SystemExit(0)

    print(f"Ready: {engine.is_ready()}")
    try:
        profit, gas = engine.simulate()
        opp = engine._top_opportunity
        mode = opp.get("mode", "?") if opp else "?"
        print(f"Top opportunity [{mode}]: profit={profit/1e18:.4f} PLS  gas={gas/1e18:.4f} PLS")
        print(f"ROI: {engine.roi():.2f}x")

        if opp:
            for k, v in opp.items():
                if k not in ("mode", "profit_wei", "gas_wei", "cycle"):
                    print(f"  {k}: {v}")

        if args.execute:
            result = engine.execute(dry_run=False)
            print(f"LIVE result: success={result.success} net={result.net_pls:.4f} PLS")
        elif args.dry_run:
            result = engine.execute(dry_run=True)
            print(f"Dry-run result: success={result.success} notes={result.notes}")

    except SimulationFailed as e:
        print(f"No opportunity: {e}")


# ── Module Documentation ─────────────────────────────────────────────────────
#
# arb.py — Engine 1: Multi-Mode Arbitrage (RAZOR)
#
# Three arb modes, ranked by ROI each cycle:
#   Mode 1: PurchaseArb  — Buy tokens at Dysnomia market rate, sell on PulseX
#   Mode 2: CrossDexArb  — Same token on V1 vs V2, exploit spread via TGSv8.atomicArb()
#   Mode 3: CrossPairArb — Graph-based triangle arb across connected pools
#
# is_ready():  Any mode viable (AFFECTION >= 1 OR PLS >= 10 for cross-DEX/pair)
# simulate():  Run all modes, pick best opportunity across all three
# execute():   Dispatch to the right execution path based on mode
#
# Mode 2 flow (TGSv8 substrate):
#   1. _cross_dex_candidates()     — find tokens with BOTH V1+V2 WPLS pairs
#   2. TGSv8.getReservesBoth()     — read reserves from both DEXes in one call
#   3. Compute spread (bps)        — filter >= 50bps (CROSS_DEX_MIN_SPREAD_BPS)
#   4. Uniswap v2 formula          — simulate buy on cheaper, sell on expensive
#   5. TGSv8.atomicArb()           — atomic execution, reverts if unprofitable
#   6. deposit(WPLS) beforehand    — withdraw(WPLS) after for principal + profit
#
# CLI:
#   python -m scripts.Joystick.engines.arb --status
#   python -m scripts.Joystick.engines.arb --dry-run
#   python -m scripts.Joystick.engines.arb --execute
#   python -m scripts.Joystick.engines.arb --mode cross_dex --dry-run -v
#   python -m scripts.Joystick.engines.arb --force-scan --dry-run
# ─────────────────────────────────────────────────────────────────────────────
