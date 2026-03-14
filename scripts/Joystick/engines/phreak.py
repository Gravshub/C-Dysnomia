"""
Engine 8 — PHR3AK: Token Web Manipulation Engine
|>JOYSTICK<| / Dysnomia · Atropa · PulseChain

Three modes:
  Mode 1: DEPLOY  — Create V4 token, pair with LP, burn % of LP tokens
  Mode 2: ARM     — Acquire Debenture=True tokens for E7 BACKBONE ammo
  Mode 3: STITCH  — Create LP pairs between existing tokens (new edges)

PHR3AK is infrastructure — it doesn't generate PLS directly.
It builds the token web topology that makes E1, E7, and all other engines
more profitable.

Mode 2 (ARM) is the critical path — one 100 PLS buy of OZZY unlocks
E7 BACKBONE, the projected primary revenue engine.

"Phantom Phreak didn't need to own the phone company.
 He just needed to know how the switches worked."

File: scripts/Joystick/engines/phreak.py
Implements: EngineBase ABC (is_ready, simulate, execute)
"""
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from web3 import Web3

from .base import EngineBase, EngineResult
from ..core.config import (
    JOEY_WALLET, TGSV8, WPLS,
    PULSEX_V1_FACTORY, PULSEX_V2_FACTORY,
    GAS_PRICE_CEIL, GAS_MULT, MAX_SLIPPAGE,
)
from ..core.chain import (
    w3_read, w3_submit, erc20, safe, multicall,
    tgsv8_contract, factory_contract, pair_contract,
)
from ..core.executor import send_tx, approve_if_needed
from ..core.simulator import SimulationFailed
from ..core.event_logger import events as _events
from ..core.split_swap import SplitSwap, PairInfo
from ..oracle.profitability import uniswap_v2_out, price_impact_pct

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
ZERO_ADDR = "0x" + "0" * 40
SLIP_BPS = 150  # 1.5% slippage tolerance

# Gas estimates
ARM_GAS_EST = 300_000
DEPLOY_GAS_EST = 2_000_000
STITCH_GAS_EST = 500_000
DEBENTURE_CHECK_GAS = 50_000

# Paths
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_CONFIG_PATH = os.path.join(_DATA_DIR, "phreak_config.json")
_RECON_PATH = os.path.join(_DATA_DIR, "recon_results.json")
_V2FED_PATH = os.path.join(_DATA_DIR, "v2_federal_tokens.json")
_EVENTS_DIR = os.path.join(_DATA_DIR, "events")


def _log_phreak_event(event: dict) -> None:
    """Append a timestamped event to phreak.json."""
    event["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    event["epoch"] = time.time()
    try:
        os.makedirs(_EVENTS_DIR, exist_ok=True)
        with open(os.path.join(_EVENTS_DIR, "phreak.json"), "a") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception:
        pass


# ── Config loader ─────────────────────────────────────────────────────────────

@dataclass
class DebToken:
    """A Debenture=True V2 Federal token."""
    address: str
    symbol: str
    parent: str
    note: str = ""


@dataclass
class PhreakConfig:
    """E8 runtime configuration."""
    deb_true_v2: list[DebToken] = field(default_factory=list)
    burn_address: str = "0x0000000000000000000000000000000000000369"
    default_keep_pct: int = 20
    max_impact_pct: float = 10.0
    split_threshold_pct: float = 3.33
    deploy_queue: list[dict] = field(default_factory=list)
    stitch_candidates: list[dict] = field(default_factory=list)
    factories: dict[str, str] = field(default_factory=dict)
    v2_federal_minter: str = ""
    debenture_monitor_interval_s: int = 600
    arm_default_pls: int = 100


def load_phreak_config() -> PhreakConfig:
    """Load phreak_config.json → PhreakConfig."""
    cfg = PhreakConfig()
    if not os.path.exists(_CONFIG_PATH):
        log.warning("E8: phreak_config.json not found — using defaults")
        return cfg
    try:
        with open(_CONFIG_PATH) as f:
            raw = json.load(f)
        cfg.burn_address = raw.get("burn_address", cfg.burn_address)
        cfg.default_keep_pct = raw.get("default_keep_pct", cfg.default_keep_pct)
        cfg.max_impact_pct = raw.get("max_impact_pct", cfg.max_impact_pct)
        cfg.split_threshold_pct = raw.get("split_threshold_pct", cfg.split_threshold_pct)
        cfg.deploy_queue = raw.get("deploy_queue", [])
        cfg.stitch_candidates = raw.get("stitch_candidates", [])
        cfg.factories = raw.get("factories", {})
        cfg.v2_federal_minter = raw.get("v2_federal_minter", "")
        cfg.debenture_monitor_interval_s = raw.get("debenture_monitor_interval_s", 600)
        cfg.arm_default_pls = raw.get("arm_default_pls", 100)
        for entry in raw.get("deb_true_v2", []):
            cfg.deb_true_v2.append(DebToken(
                address=Web3.to_checksum_address(entry["address"]),
                symbol=entry.get("symbol", entry["address"][:8]),
                parent=Web3.to_checksum_address(entry.get("parent", ZERO_ADDR)),
                note=entry.get("note", ""),
            ))
    except Exception as e:
        log.error("E8: failed to load phreak_config.json: %s", e)
    return cfg


def save_phreak_config(cfg: PhreakConfig) -> None:
    """Atomically write phreak_config.json."""
    data = {
        "deb_true_v2": [
            {"address": d.address, "symbol": d.symbol, "parent": d.parent, "note": d.note}
            for d in cfg.deb_true_v2
        ],
        "burn_address": cfg.burn_address,
        "default_keep_pct": cfg.default_keep_pct,
        "max_impact_pct": cfg.max_impact_pct,
        "split_threshold_pct": cfg.split_threshold_pct,
        "deploy_queue": cfg.deploy_queue,
        "stitch_candidates": cfg.stitch_candidates,
        "factories": cfg.factories,
        "v2_federal_minter": cfg.v2_federal_minter,
        "debenture_monitor_interval_s": cfg.debenture_monitor_interval_s,
        "arm_default_pls": cfg.arm_default_pls,
    }
    tmp = _CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, _CONFIG_PATH)


# ── Stitch scoring ────────────────────────────────────────────────────────────

@dataclass
class StitchCandidate:
    """A candidate edge to create between two tokens."""
    token_a: str
    token_b: str
    symbol_a: str
    symbol_b: str
    connections_a: int
    connections_b: int
    min_liquidity_pls: int
    score: float


def _build_token_graph() -> dict:
    """
    Build adjacency graph from recon_results.json.
    Returns dict: token_addr_lower → {
        "symbol": str,
        "pairs": [(pair_addr, partner_token, pls_liquidity), ...],
        "pls_per_token": int,
    }
    """
    graph = {}

    if not os.path.exists(_RECON_PATH):
        log.debug("E8: recon_results.json not found — empty graph")
        return graph

    try:
        with open(_RECON_PATH) as f:
            recon = json.load(f)
    except Exception as e:
        log.warning("E8: failed to load recon_results.json: %s", e)
        return graph

    for addr, entry in recon.get("results", {}).items():
        addr_l = addr.lower()
        cd = entry.get("chain_data", {})
        pairs = []
        pls_tok = cd.get("pls_per_token", 0)

        for pair_key in ("v1_pair", "v2_pair"):
            pair_data = cd.get(pair_key)
            if pair_data and pair_data.get("pair") and pair_data["pair"] != ZERO_ADDR:
                r_wpls = pair_data.get("r_wpls", 0)
                pairs.append((pair_data["pair"], WPLS.lower(), r_wpls))

        graph[addr_l] = {
            "symbol": entry.get("label", addr_l[:8]),
            "pairs": pairs,
            "pls_per_token": pls_tok,
        }

    return graph


def scan_missing_edges(
    graph: dict,
    max_candidates: int = 20,
) -> list[StitchCandidate]:
    """
    Scan for the highest-value missing edges.

    Scoring: (connections_A × connections_B) × sqrt(min_liquidity_pls)

    Only considers tokens with existing DEX pairs (connected tokens).
    """
    # Build set of existing pair connections
    existing_pairs = set()
    for addr, data in graph.items():
        for pair_addr, partner, _ in data["pairs"]:
            # Normalized pair key
            a, b = sorted([addr, partner])
            existing_pairs.add((a, b))

    # Get connected tokens (at least 1 existing pair)
    connected = {
        addr: data for addr, data in graph.items()
        if len(data["pairs"]) > 0
    }

    candidates = []

    tokens = list(connected.items())
    for i in range(len(tokens)):
        addr_a, data_a = tokens[i]
        conn_a = len(data_a["pairs"])
        min_liq_a = min((p[2] for p in data_a["pairs"]), default=0)

        for j in range(i + 1, len(tokens)):
            addr_b, data_b = tokens[j]

            # Skip if pair already exists
            pair_key = tuple(sorted([addr_a, addr_b]))
            if pair_key in existing_pairs:
                continue

            # Skip WPLS pairs (those are the standard pairs, not "edges" between tokens)
            if addr_a == WPLS.lower() or addr_b == WPLS.lower():
                continue

            conn_b = len(data_b["pairs"])
            min_liq_b = min((p[2] for p in data_b["pairs"]), default=0)

            min_liq = min(min_liq_a, min_liq_b)
            if min_liq <= 0:
                continue

            score = (conn_a * conn_b) * math.sqrt(min_liq / 1e18)

            candidates.append(StitchCandidate(
                token_a=Web3.to_checksum_address(addr_a),
                token_b=Web3.to_checksum_address(addr_b),
                symbol_a=data_a["symbol"],
                symbol_b=data_b["symbol"],
                connections_a=conn_a,
                connections_b=conn_b,
                min_liquidity_pls=min_liq,
                score=score,
            ))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[:max_candidates]


# ── PHR3AK Engine ─────────────────────────────────────────────────────────────

class PhreakEngine(EngineBase):
    """
    Engine 8 — PHR3AK: Token Web Manipulation.

    Three modes, evaluated in priority order:
      1. ARM:     if any DEB_TRUE_V2 token has 0 balance in TGSv8 → arm first
      2. DEPLOY:  if deploy_queue non-empty → create next V4 token + LP
      3. STITCH:  scan_missing_edges() → create highest-value LP pair

    ARM mode is the critical path — unlocks E7 BACKBONE.
    """
    name = "PHR3AK"

    def __init__(self):
        super().__init__()
        self._cfg: Optional[PhreakConfig] = None
        self._cfg_loaded_at: float = 0.0
        self._last_deb_monitor: float = 0.0
        self._splitter = SplitSwap()
        self._pending_mode: Optional[str] = None
        self._pending_data: Optional[dict] = None
        self._total_pls_spent: int = 0

    def _load_config(self) -> PhreakConfig:
        """Load config with 5-minute cache."""
        now = time.time()
        if self._cfg is None or (now - self._cfg_loaded_at) > 300:
            self._cfg = load_phreak_config()
            self._cfg_loaded_at = now
        return self._cfg

    # ── EngineBase interface ──────────────────────────────────────────────────

    def is_ready(self) -> bool:
        if not TGSV8:
            log.debug("E8: TGSV8_ADDRESS not set")
            return False

        cfg = self._load_config()

        # ARM mode is ready if any deb token has 0 balance in TGSv8
        if cfg.deb_true_v2:
            try:
                tgs = tgsv8_contract()
                for deb in cfg.deb_true_v2:
                    bal = safe(tgs, "bal", deb.address) or 0
                    if bal == 0:
                        return True
            except Exception:
                pass

        # DEPLOY mode is ready if queue has items
        if cfg.deploy_queue:
            return True

        # STITCH mode — check if we have tokens to pair
        try:
            tgs = tgsv8_contract()
            pls_bal = w3_read.eth.get_balance(JOEY_WALLET)
            if pls_bal > 200_000 * 10**18:  # Only stitch when well above gas floor
                return True
        except Exception:
            pass

        return False

    def simulate(self) -> tuple[int, int]:
        """
        Evaluate modes in priority order. Returns (expected_value_wei, gas_cost_wei).

        PHR3AK doesn't generate direct PLS profit — it's infrastructure.
        Returns strategic value estimates.
        """
        cfg = self._load_config()
        gas_price = w3_read.eth.gas_price

        # Priority 1: ARM — check for unfunded DEB_TRUE_V2 tokens
        arm_data = self._evaluate_arm(cfg, gas_price)
        if arm_data:
            self._pending_mode = "arm"
            self._pending_data = arm_data
            return arm_data["value_wei"], arm_data["gas_wei"]

        # Priority 2: DEPLOY
        deploy_data = self._evaluate_deploy(cfg, gas_price)
        if deploy_data:
            self._pending_mode = "deploy"
            self._pending_data = deploy_data
            return deploy_data["value_wei"], deploy_data["gas_wei"]

        # Priority 3: STITCH
        stitch_data = self._evaluate_stitch(cfg, gas_price)
        if stitch_data:
            self._pending_mode = "stitch"
            self._pending_data = stitch_data
            return stitch_data["value_wei"], stitch_data["gas_wei"]

        raise SimulationFailed("E8: no actionable mode available")

    def execute(self, dry_run: bool = False) -> EngineResult:
        """Execute the pending mode from simulate()."""
        if self._pending_mode is None:
            try:
                self.simulate()
            except SimulationFailed as exc:
                return EngineResult(success=False, profit_wei=0, gas_wei=0, notes=str(exc))

        mode = self._pending_mode
        data = self._pending_data
        self._pending_mode = None
        self._pending_data = None

        gas_price = w3_read.eth.gas_price
        if gas_price > GAS_PRICE_CEIL:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes=f"gas too high: {gas_price/1e9:.0f} Gwei")

        try:
            if mode == "arm":
                result = self._execute_arm(data, dry_run)
            elif mode == "deploy":
                result = self._execute_deploy(data, dry_run)
            elif mode == "stitch":
                result = self._execute_stitch(data, dry_run)
            else:
                result = EngineResult(success=False, profit_wei=0, gas_wei=0,
                                      notes=f"Unknown mode: {mode}")
        except Exception as e:
            log.error("E8 execute error (%s): %s", mode, e)
            result = EngineResult(success=False, profit_wei=0, gas_wei=0, notes=str(e))

        _log_phreak_event({
            "mode": mode,
            "success": result.success,
            "gas_pls": result.gas_pls,
            "notes": result.notes,
            "tx_hashes": result.tx_hashes,
            "dry_run": dry_run,
        })

        return result

    # ── ARM mode ──────────────────────────────────────────────────────────────

    def _evaluate_arm(self, cfg: PhreakConfig, gas_price: int) -> Optional[dict]:
        """Check if any DEB_TRUE_V2 token needs arming."""
        if not cfg.deb_true_v2:
            return None

        tgs = tgsv8_contract()

        for deb in cfg.deb_true_v2:
            bal = safe(tgs, "bal", deb.address) or 0
            if bal > 0:
                continue

            # Found unfunded deb token — plan acquisition
            amount_pls = cfg.arm_default_pls * 10**18
            gas_wei = int(ARM_GAS_EST * gas_price * GAS_MULT)

            # Check DEX availability
            route = self._find_cheapest_route(deb.address)
            if not route:
                log.debug("E8 ARM: no route found for %s", deb.symbol)
                continue

            # Estimate how many tokens we get
            expected_tokens = route.get("expected_tokens", 0)

            log.info("E8 ARM: %s needs ammo (TGSv8 bal=0). Route: %s, cost: %d PLS",
                     deb.symbol, route["method"], cfg.arm_default_pls)

            return {
                "deb_token": deb,
                "amount_pls": amount_pls,
                "route": route,
                "expected_tokens": expected_tokens,
                "gas_wei": gas_wei,
                "value_wei": amount_pls,  # Strategic value = cost of ammo
            }

        return None

    def _find_cheapest_route(self, token_addr: str) -> Optional[dict]:
        """
        Find the cheapest way to acquire a token:
          1. Check if mintable (Purchase, Generate, mint)
          2. If not → scan DEX pairs across V1, V2 factories
          3. Pick best effective price
        """
        token_cs = Web3.to_checksum_address(token_addr)

        # Try mintability: check if Purchase() works
        try:
            token_c = erc20(token_cs)
            # Check if token has self-balance (purchaseable tokens hold inventory)
            self_bal = safe(token_c, "balanceOf", token_cs) or 0
            if self_bal > 0:
                # Has inventory — might be purchaseable, but we'd need AFFECTION
                # For ARM, DEX buy is simpler and more reliable
                pass
        except Exception:
            pass

        # DEX scan: check all factory pairs
        best_route = None

        for factory_name, factory_addr in [
            ("pulsex_v1", PULSEX_V1_FACTORY),
            ("pulsex_v2", PULSEX_V2_FACTORY),
        ]:
            try:
                factory = factory_contract(factory_addr)
                pair_addr = safe(factory, "getPair", token_cs, WPLS)
                if not pair_addr or pair_addr == ZERO_ADDR:
                    continue

                pair = pair_contract(pair_addr)
                reserves = safe(pair, "getReserves")
                if not reserves:
                    continue

                r0, r1, _ = reserves
                token0 = safe(pair, "token0")

                if token0 and token0.lower() == token_cs.lower():
                    r_token, r_wpls = r0, r1
                else:
                    r_token, r_wpls = r1, r0

                if r_token == 0 or r_wpls == 0:
                    continue

                # Price: how many PLS per token
                pls_per_tok = r_wpls / r_token

                # Estimate tokens for default ARM amount
                test_amount = 100 * 10**18  # 100 PLS
                tokens_out = uniswap_v2_out(test_amount, r_wpls, r_token)
                impact = price_impact_pct(test_amount, r_wpls)

                route = {
                    "method": f"dex_{factory_name}",
                    "pair_addr": pair_addr,
                    "factory": factory_name,
                    "dex": 0 if "v1" in factory_name else 1,
                    "r_token": r_token,
                    "r_wpls": r_wpls,
                    "pls_per_tok": pls_per_tok,
                    "expected_tokens": tokens_out,
                    "impact_pct": impact,
                }

                if best_route is None or pls_per_tok < best_route["pls_per_tok"]:
                    best_route = route

            except Exception as e:
                log.debug("E8 ARM: factory %s scan error: %s", factory_name, e)

        return best_route

    def _execute_arm(self, data: dict, dry_run: bool) -> EngineResult:
        """
        Execute ARM mode: buy DEB_TRUE_V2 token on DEX, deposit into TGSv8.

        Flow:
          1. Swap PLS → WPLS → deb_token via TGSv8.swapNativeForTokens()
             or: wrap PLS, approve, deposit, swapExact
          2. Tokens land in TGSv8 working balance → E7 has ammo
        """
        deb = data["deb_token"]
        amount_pls = data["amount_pls"]
        route = data["route"]

        tgs = tgsv8_contract(w3=w3_submit)
        tgs_read = tgsv8_contract()
        tx_hashes = []
        gas_spent = 0

        log.info("E8 ARM: acquiring %s via %s for %d PLS",
                 deb.symbol, route["method"], amount_pls // 10**18)

        try:
            # Use TGSv8.swapNativeForTokens to buy token with PLS
            # This wraps PLS → WPLS → swaps on DEX → tokens land in TGSv8
            dex_enum = route.get("dex", 2)  # 0=V1, 1=V2, 2=best

            # Calculate min output with slippage
            expected_tokens = route["expected_tokens"]
            min_out = int(expected_tokens * (10000 - SLIP_BPS) / 10000)

            fn_call = tgs.functions.swapNativeForTokens(
                deb.address,
                min_out,
                dex_enum,
            )

            receipt = send_tx(
                fn_call,
                f"ARM: buy {deb.symbol} ({amount_pls//10**18} PLS)",
                dry_run=dry_run,
                value=amount_pls,
                skip_simulate=True,  # Payable function
            )

            if receipt is None and dry_run:
                return EngineResult(
                    success=True, profit_wei=0, gas_wei=0,
                    notes=f"[dry-run] ARM {deb.symbol}: {amount_pls//10**18} PLS → ~{expected_tokens//10**18} tokens",
                )

            if receipt and receipt.get("status") == 1:
                tx_hashes.append(receipt["transactionHash"].hex())
                gas_spent = receipt["gasUsed"] * receipt.get("effectiveGasPrice",
                                                             w3_submit.eth.gas_price)

                # Verify tokens landed in TGSv8
                new_bal = safe(tgs_read, "bal", deb.address) or 0
                log.info("E8 ARM: %s — TGSv8 now holds %s tokens",
                         deb.symbol, f"{new_bal/1e18:.0f}" if new_bal else "0")

                self._total_pls_spent += amount_pls

                return EngineResult(
                    success=True,
                    profit_wei=0,  # ARM is strategic, not profit-generating
                    gas_wei=gas_spent,
                    tx_hashes=tx_hashes,
                    notes=f"ARM {deb.symbol}: {amount_pls//10**18} PLS → {new_bal//10**18 if new_bal else 0} tokens in TGSv8",
                )
            else:
                return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                    tx_hashes=tx_hashes, notes=f"ARM TX reverted for {deb.symbol}")

        except Exception as e:
            log.error("E8 ARM failed: %s", e)
            return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                tx_hashes=tx_hashes, notes=str(e))

    # ── DEPLOY mode ───────────────────────────────────────────────────────────

    def _evaluate_deploy(self, cfg: PhreakConfig, gas_price: int) -> Optional[dict]:
        """Check if deploy queue has pending items."""
        if not cfg.deploy_queue:
            return None

        next_deploy = cfg.deploy_queue[0]
        gas_wei = int(DEPLOY_GAS_EST * gas_price * GAS_MULT)

        # Validate we have enough WM for the deploy
        tgs = tgsv8_contract()
        wm_bal = safe(tgs, "bal", Web3.to_checksum_address(
            "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29"  # WM
        )) or 0

        initial_mint = next_deploy.get("initial_mint", 100)
        # V4 2x bug: needs 2x the WM/AFFECTION for initial mint
        needed_parent = initial_mint * 2 * 10**18

        parent_addr = next_deploy.get("parent", "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
        parent_bal = safe(tgs, "bal", Web3.to_checksum_address(parent_addr)) or 0

        if parent_bal < needed_parent:
            log.debug("E8 DEPLOY: insufficient parent tokens (%d < %d needed)",
                      parent_bal // 10**18, needed_parent // 10**18)
            return None

        return {
            "deploy_spec": next_deploy,
            "gas_wei": gas_wei,
            "value_wei": gas_wei,  # Strategic value = gas cost
        }

    def _execute_deploy(self, data: dict, dry_run: bool) -> EngineResult:
        """
        Execute DEPLOY mode:
          1. TGSv8.createV4(name, symbol, initialMint, parent) → new token
          2. Add liquidity via TGSv8.addLiquidity()
          3. Burn (100 - keep_pct)% of LP tokens to burn address
        """
        spec = data["deploy_spec"]
        cfg = self._load_config()

        tgs = tgsv8_contract(w3=w3_submit)
        tgs_read = tgsv8_contract()
        tx_hashes = []
        gas_spent = 0

        name = spec.get("name", "JoystickToken")
        symbol = spec.get("symbol", "JT")
        initial_mint = spec.get("initial_mint", 100)
        parent = Web3.to_checksum_address(
            spec.get("parent", "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
        )
        token_b = Web3.to_checksum_address(spec.get("token_b", WPLS))
        token_b_amount = int(spec.get("token_b_amount", 0))
        token_a_amount = int(spec.get("token_a_amount", 0))
        keep_pct = spec.get("keep_pct", cfg.default_keep_pct)

        log.info("E8 DEPLOY: creating %s (%s), parent=%s, initial=%d",
                 name, symbol, parent[:10], initial_mint)

        try:
            # Step 1: Create V4 token
            fn_call = tgs.functions.createV4(name, symbol, initial_mint, parent)
            receipt = send_tx(fn_call, f"DEPLOY: createV4({symbol})", dry_run=dry_run)

            if receipt is None and dry_run:
                return EngineResult(
                    success=True, profit_wei=0, gas_wei=0,
                    notes=f"[dry-run] DEPLOY {symbol}: would create V4 + LP + burn",
                )

            if not receipt or receipt.get("status") != 1:
                return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                    notes=f"createV4 reverted for {symbol}")

            tx_hashes.append(receipt["transactionHash"].hex())
            gas_spent += receipt["gasUsed"] * receipt.get("effectiveGasPrice",
                                                          w3_submit.eth.gas_price)

            # Parse TokenCreated event to get new token address
            new_token = None
            token_created_topic = Web3.keccak(
                text="TokenCreated(uint256,address,address,uint256,uint8)"
            ).hex()
            for log_entry in receipt.get("logs", []):
                topics = log_entry.get("topics", [])
                if topics and topics[0].hex().lower() == token_created_topic[2:].lower():
                    # Token address is in the data or indexed topic
                    if len(topics) >= 3:
                        new_token = "0x" + topics[2].hex()[-40:]
                    break

            if not new_token:
                # Fallback: try tokenMeta on TGSv8 for last created
                log.warning("E8 DEPLOY: could not parse TokenCreated event — checking tokenMeta")
                return EngineResult(
                    success=True, profit_wei=0, gas_wei=gas_spent,
                    tx_hashes=tx_hashes,
                    notes=f"DEPLOY {symbol}: created but address parsing failed",
                )

            new_token = Web3.to_checksum_address(new_token)
            log.info("E8 DEPLOY: new token at %s", new_token)

            # Step 2: Add liquidity if amounts specified
            if token_a_amount > 0 and token_b_amount > 0:
                # Deposit token_b into TGSv8 if needed
                token_b_in_tgs = safe(tgs_read, "bal", token_b) or 0
                if token_b_in_tgs < token_b_amount:
                    needed = token_b_amount - token_b_in_tgs
                    token_b_c = w3_submit.eth.contract(
                        address=token_b, abi=erc20(token_b).abi
                    )
                    tgs_addr = Web3.to_checksum_address(TGSV8)
                    approve_if_needed(token_b_c, tgs_addr, needed, "token_b→TGSv8", dry_run=dry_run)
                    r = send_tx(
                        tgs.functions.deposit(token_b, needed),
                        f"Deposit {needed/1e18:.4f} token_b",
                        dry_run=dry_run,
                    )
                    if r:
                        tx_hashes.append(r["transactionHash"].hex())
                        gas_spent += r["gasUsed"] * r.get("effectiveGasPrice",
                                                           w3_submit.eth.gas_price)

                # Add liquidity: TGSv8.addLiquidity
                dex_enum = 1  # V2 default
                r = send_tx(
                    tgs.functions.addLiquidity(
                        new_token, token_b,
                        token_a_amount, token_b_amount,
                        SLIP_BPS,
                        JOEY_WALLET,  # LP tokens go to Joey
                        dex_enum,
                    ),
                    f"AddLiquidity {symbol}/{spec.get('token_b_symbol', 'TOKEN')}",
                    dry_run=dry_run,
                )
                if r:
                    tx_hashes.append(r["transactionHash"].hex())
                    gas_spent += r["gasUsed"] * r.get("effectiveGasPrice",
                                                       w3_submit.eth.gas_price)

                    # Step 3: Burn LP tokens
                    if keep_pct < 100:
                        self._burn_lp(
                            new_token, token_b, dex_enum,
                            keep_pct, cfg.burn_address,
                            dry_run, tx_hashes,
                        )

            # Remove from deploy queue
            if not dry_run:
                cfg.deploy_queue.pop(0)
                save_phreak_config(cfg)

            return EngineResult(
                success=True, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"DEPLOY {symbol} → {new_token}",
            )

        except Exception as e:
            log.error("E8 DEPLOY failed: %s", e)
            return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                tx_hashes=tx_hashes, notes=str(e))

    def _burn_lp(
        self,
        token_a: str,
        token_b: str,
        dex: int,
        keep_pct: int,
        burn_addr: str,
        dry_run: bool,
        tx_hashes: list,
    ) -> None:
        """Burn (100-keep_pct)% of LP tokens to the burn address."""
        factory_addr = PULSEX_V2_FACTORY if dex == 1 else PULSEX_V1_FACTORY
        factory = factory_contract(factory_addr)
        pair_addr = safe(factory, "getPair", token_a, token_b)

        if not pair_addr or pair_addr == ZERO_ADDR:
            log.warning("E8: LP pair not found for burn — skipping")
            return

        lp = erc20(pair_addr)
        lp_bal = safe(lp, "balanceOf", JOEY_WALLET) or 0
        if lp_bal == 0:
            return

        burn_amount = int(lp_bal * (100 - keep_pct) / 100)
        if burn_amount == 0:
            return

        burn_cs = Web3.to_checksum_address(burn_addr)
        lp_submit = w3_submit.eth.contract(address=pair_addr, abi=lp.abi)

        log.info("E8 DEPLOY: burning %d%% of LP (%s tokens) to %s",
                 100 - keep_pct, f"{burn_amount/1e18:.6f}", burn_addr[:10])

        r = send_tx(
            lp_submit.functions.transfer(burn_cs, burn_amount),
            f"Burn LP → {burn_addr[:10]}",
            dry_run=dry_run,
        )
        if r:
            tx_hashes.append(r["transactionHash"].hex())

    # ── STITCH mode ───────────────────────────────────────────────────────────

    def _evaluate_stitch(self, cfg: PhreakConfig, gas_price: int) -> Optional[dict]:
        """Scan for highest-value missing edge to create."""
        # Only stitch when well above gas floor
        pls_bal = w3_read.eth.get_balance(JOEY_WALLET)
        if pls_bal < 200_000 * 10**18:
            return None

        graph = _build_token_graph()
        if not graph:
            return None

        candidates = scan_missing_edges(graph)
        if not candidates:
            log.debug("E8 STITCH: no missing edges found")
            return None

        top = candidates[0]
        gas_wei = int(STITCH_GAS_EST * gas_price * GAS_MULT)

        log.info("E8 STITCH: top candidate %s/%s (score=%.2f, conn=%d×%d)",
                 top.symbol_a, top.symbol_b, top.score,
                 top.connections_a, top.connections_b)

        return {
            "candidate": top,
            "gas_wei": gas_wei,
            "value_wei": gas_wei,  # Strategic value
        }

    def _execute_stitch(self, data: dict, dry_run: bool) -> EngineResult:
        """
        Execute STITCH mode: create LP pair between two existing tokens.

        Flow:
          1. Acquire small amounts of both tokens (or use existing balances)
          2. Deposit into TGSv8
          3. TGSv8.addLiquidity(tokenA, tokenB, amtA, amtB, slipBps, to, dex)
          4. Burn % of LP tokens
        """
        candidate = data["candidate"]
        cfg = self._load_config()

        tgs = tgsv8_contract(w3=w3_submit)
        tgs_read = tgsv8_contract()
        tx_hashes = []
        gas_spent = 0

        token_a = candidate.token_a
        token_b = candidate.token_b

        log.info("E8 STITCH: creating pair %s/%s", candidate.symbol_a, candidate.symbol_b)

        try:
            # Check existing balances in TGSv8 and wallet
            bal_a_tgs = safe(tgs_read, "bal", token_a) or 0
            bal_b_tgs = safe(tgs_read, "bal", token_b) or 0

            bal_a_wallet = safe(erc20(token_a), "balanceOf", JOEY_WALLET) or 0
            bal_b_wallet = safe(erc20(token_b), "balanceOf", JOEY_WALLET) or 0

            total_a = bal_a_tgs + bal_a_wallet
            total_b = bal_b_tgs + bal_b_wallet

            if total_a == 0 or total_b == 0:
                # Need to acquire tokens — buy small amounts on DEX
                # Use 50 PLS worth of each token
                buy_pls = 50 * 10**18

                for token, sym in [(token_a, candidate.symbol_a),
                                   (token_b, candidate.symbol_b)]:
                    bal_tgs = safe(tgs_read, "bal", token) or 0
                    bal_wal = safe(erc20(token), "balanceOf", JOEY_WALLET) or 0

                    if bal_tgs + bal_wal > 0:
                        continue

                    # Buy via TGSv8.swapNativeForTokens
                    r = send_tx(
                        tgs.functions.swapNativeForTokens(token, 1, 2),
                        f"STITCH: buy {sym} ({buy_pls//10**18} PLS)",
                        dry_run=dry_run,
                        value=buy_pls,
                        skip_simulate=True,
                    )
                    if r:
                        tx_hashes.append(r["transactionHash"].hex())
                        gas_spent += r["gasUsed"] * r.get("effectiveGasPrice",
                                                           w3_submit.eth.gas_price)

                # Re-check balances after purchase
                bal_a_tgs = safe(tgs_read, "bal", token_a) or 0
                bal_b_tgs = safe(tgs_read, "bal", token_b) or 0

            # Deposit wallet tokens into TGSv8 if needed
            for token, sym in [(token_a, candidate.symbol_a),
                                (token_b, candidate.symbol_b)]:
                wal_bal = safe(erc20(token), "balanceOf", JOEY_WALLET) or 0
                if wal_bal > 0:
                    tgs_addr = Web3.to_checksum_address(TGSV8)
                    tok_c = w3_submit.eth.contract(address=token, abi=erc20(token).abi)
                    approve_if_needed(tok_c, tgs_addr, wal_bal, f"{sym}→TGSv8", dry_run=dry_run)
                    r = send_tx(
                        tgs.functions.deposit(token, wal_bal),
                        f"Deposit {sym} into TGSv8",
                        dry_run=dry_run,
                    )
                    if r:
                        tx_hashes.append(r["transactionHash"].hex())
                        gas_spent += r["gasUsed"] * r.get("effectiveGasPrice",
                                                           w3_submit.eth.gas_price)

            # Re-read final balances in TGSv8
            amt_a = safe(tgs_read, "bal", token_a) or 0
            amt_b = safe(tgs_read, "bal", token_b) or 0

            if amt_a == 0 or amt_b == 0:
                return EngineResult(
                    success=False, profit_wei=0, gas_wei=gas_spent,
                    tx_hashes=tx_hashes,
                    notes=f"STITCH: insufficient tokens (A={amt_a}, B={amt_b})",
                )

            # Use half of available balance for the LP to keep some reserve
            lp_a = amt_a // 2
            lp_b = amt_b // 2

            if lp_a == 0 or lp_b == 0:
                return EngineResult(
                    success=False, profit_wei=0, gas_wei=gas_spent,
                    tx_hashes=tx_hashes,
                    notes="STITCH: token amounts too small for LP",
                )

            # Add liquidity on V2
            dex_enum = 1  # V2
            r = send_tx(
                tgs.functions.addLiquidity(
                    token_a, token_b,
                    lp_a, lp_b,
                    SLIP_BPS,
                    JOEY_WALLET,
                    dex_enum,
                ),
                f"STITCH: addLiquidity {candidate.symbol_a}/{candidate.symbol_b}",
                dry_run=dry_run,
            )

            if r is None and dry_run:
                return EngineResult(
                    success=True, profit_wei=0, gas_wei=0,
                    notes=f"[dry-run] STITCH {candidate.symbol_a}/{candidate.symbol_b}",
                )

            if not r or r.get("status") != 1:
                return EngineResult(
                    success=False, profit_wei=0, gas_wei=gas_spent,
                    tx_hashes=tx_hashes,
                    notes=f"STITCH addLiquidity reverted",
                )

            tx_hashes.append(r["transactionHash"].hex())
            gas_spent += r["gasUsed"] * r.get("effectiveGasPrice",
                                               w3_submit.eth.gas_price)

            # Burn LP tokens
            keep_pct = cfg.default_keep_pct
            if keep_pct < 100:
                self._burn_lp(
                    token_a, token_b, dex_enum,
                    keep_pct, cfg.burn_address,
                    dry_run, tx_hashes,
                )

            log.info("E8 STITCH: pair %s/%s created", candidate.symbol_a, candidate.symbol_b)

            return EngineResult(
                success=True, profit_wei=0, gas_wei=gas_spent,
                tx_hashes=tx_hashes,
                notes=f"STITCH {candidate.symbol_a}/{candidate.symbol_b} — new edge created",
            )

        except Exception as e:
            log.error("E8 STITCH failed: %s", e)
            return EngineResult(success=False, profit_wei=0, gas_wei=gas_spent,
                                tx_hashes=tx_hashes, notes=str(e))

    # ── Debenture monitoring ──────────────────────────────────────────────────

    def monitor_debenture_changes(self) -> list[str]:
        """
        Check all V2 Federal tokens for Debenture status changes.
        Returns list of newly-discovered Deb=true addresses.

        Called periodically by the engine or bot loop.
        """
        cfg = self._load_config()
        now = time.time()

        if now - self._last_deb_monitor < cfg.debenture_monitor_interval_s:
            return []

        self._last_deb_monitor = now
        new_deb_true = []

        if not os.path.exists(_V2FED_PATH):
            return []

        try:
            with open(_V2FED_PATH) as f:
                v2data = json.load(f)
        except Exception:
            return []

        tgs = tgsv8_contract()
        known_addrs = {d.address.lower() for d in cfg.deb_true_v2}

        for tok in v2data.get("tokens", []):
            addr = tok["address"]
            addr_cs = Web3.to_checksum_address(addr)

            if addr.lower() in known_addrs:
                continue

            # Check on-chain Debenture status
            try:
                deb_status = tgs.functions.checkDebenture(addr_cs).call()
            except Exception:
                continue

            if deb_status:
                symbol = tok.get("symbol", addr[:8])
                parent = tok.get("parent_expected", ZERO_ADDR)

                # Try to get parent from recon
                try:
                    if os.path.exists(_RECON_PATH):
                        with open(_RECON_PATH) as f:
                            recon = json.load(f)
                        entry = recon.get("results", {}).get(addr.lower(), {})
                        chain_parent = entry.get("chain_data", {}).get("parent")
                        if chain_parent and chain_parent != ZERO_ADDR:
                            parent = chain_parent
                except Exception:
                    pass

                log.warning("E8 MONITOR: %s flipped to Debenture=TRUE!", symbol)
                new_deb = DebToken(
                    address=addr_cs,
                    symbol=symbol,
                    parent=Web3.to_checksum_address(parent) if parent != ZERO_ADDR else ZERO_ADDR,
                    note=f"Discovered via monitor at {now}",
                )
                cfg.deb_true_v2.append(new_deb)
                new_deb_true.append(addr_cs)

                _log_phreak_event({
                    "mode": "monitor",
                    "event": "debenture_flip",
                    "token": addr_cs,
                    "symbol": symbol,
                })

        if new_deb_true:
            save_phreak_config(cfg)
            log.info("E8 MONITOR: %d new Deb=true tokens discovered", len(new_deb_true))

        return new_deb_true

    # ── Cross-engine interface ────────────────────────────────────────────────

    def get_spine_balance(self, deb_token: str) -> int:
        """Check TGSv8 balance of a DEB_TRUE_V2 token. Used by E7 BACKBONE."""
        try:
            tgs = tgsv8_contract()
            return safe(tgs, "bal", Web3.to_checksum_address(deb_token)) or 0
        except Exception:
            return 0

    def get_splitter(self) -> SplitSwap:
        """Access the SplitSwap instance for cross-engine use."""
        return self._splitter

    # ── Status / diagnostics ──────────────────────────────────────────────────

    def status_line(self) -> str:
        """One-line engine status."""
        cfg = self._load_config()
        state = "DISABLED" if self.is_disabled() else ("READY" if self.is_ready() else "NOT READY")

        deb_status = []
        if cfg.deb_true_v2:
            try:
                tgs = tgsv8_contract()
                for deb in cfg.deb_true_v2:
                    bal = safe(tgs, "bal", deb.address) or 0
                    armed = "armed" if bal > 0 else "UNARMED"
                    deb_status.append(f"{deb.symbol}={armed}")
            except Exception:
                deb_status = [d.symbol for d in cfg.deb_true_v2]

        deploy_q = len(cfg.deploy_queue)
        deb_str = ", ".join(deb_status) if deb_status else "none"

        return (
            f"{self.name}: {state} "
            f"(deb=[{deb_str}], deploy_q={deploy_q}, "
            f"spent={self._total_pls_spent/1e18:,.0f} PLS, "
            f"failures={self.failure_count})"
        )


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    import logging as _logging

    parser = argparse.ArgumentParser(
        description="PHR3AK — Engine 8: Token Web Manipulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="simulate only, no TX sent")
    parser.add_argument("--status", action="store_true", help="print engine readiness and exit")
    parser.add_argument("--scan-edges", action="store_true", help="scan and print missing edges")
    parser.add_argument("--monitor-deb", action="store_true", help="check for debenture changes")
    parser.add_argument("--arm", type=str, metavar="SYMBOL", help="ARM a specific deb token")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args()

    _logging.basicConfig(
        level=_logging.DEBUG if args.verbose else _logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
    )

    engine = PhreakEngine()

    if args.status:
        print(engine.status_line())
        cfg = load_phreak_config()
        print(f"\nConfig:")
        print(f"  DEB_TRUE_V2: {len(cfg.deb_true_v2)} tokens")
        for d in cfg.deb_true_v2:
            bal = engine.get_spine_balance(d.address)
            print(f"    {d.symbol} ({d.address[:10]}...): TGSv8 bal={bal/1e18:.0f}")
        print(f"  Deploy queue: {len(cfg.deploy_queue)} items")
        print(f"  Burn address: {cfg.burn_address}")
        print(f"  Keep %: {cfg.default_keep_pct}")
        raise SystemExit(0)

    if args.scan_edges:
        graph = _build_token_graph()
        candidates = scan_missing_edges(graph, max_candidates=10)
        print(f"\nTop {len(candidates)} missing edges:")
        for i, c in enumerate(candidates):
            print(f"  {i+1}. {c.symbol_a}/{c.symbol_b} "
                  f"score={c.score:.2f} conn={c.connections_a}×{c.connections_b} "
                  f"min_liq={c.min_liquidity_pls/1e18:.0f} PLS")
        raise SystemExit(0)

    if args.monitor_deb:
        new = engine.monitor_debenture_changes()
        if new:
            print(f"New Deb=true tokens: {new}")
        else:
            print("No debenture changes detected")
        raise SystemExit(0)

    print(f"Ready: {engine.is_ready()}")
    try:
        value, gas = engine.simulate()
        print(f"Mode: {engine._pending_mode}")
        print(f"Value: {value/1e18:.4f} PLS  Gas: {gas/1e18:.4f} PLS")

        if args.arm or args.dry_run:
            result = engine.execute(dry_run=args.dry_run)
            prefix = "[dry-run]" if args.dry_run else "LIVE"
            print(f"{prefix} result: success={result.success} notes={result.notes}")
    except SimulationFailed as e:
        print(f"No actionable mode: {e}")
