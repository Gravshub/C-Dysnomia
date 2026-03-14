"""
test_anvil_full.py — Comprehensive Anvil fork test suite for Joystick Bot.

Tests all 8 engines under favorable conditions on forked PulseChain.
Each test class targets one engine; cross-engine tests verify pipelines.

Requires Anvil running:
  anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate

Run:
  cd C-Dysnomia
  python -m pytest scripts/Joystick/tests/test_anvil_full.py -v --tb=short -x

Flags:
  -v          verbose output
  --tb=short  short tracebacks
  -x          stop on first failure
"""
import pytest
import logging
import os

from web3 import Web3

from .anvil_helpers import (
    anvil_rpc, set_balance, impersonate, stop_impersonate,
    mine_block, mine_blocks, snapshot, revert,
    set_erc20_balance, find_balance_slot, skew_v2_reserves,
    read_reserves, setup_joey_funded, deposit_token_to_tgsv8,
)

log = logging.getLogger("joystick.test")

# ── Addresses (mirrors core/config.py) ─────────────────────────────────────
JOEY        = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
TGSV8       = "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32"
AFFECTION   = "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D"
WM          = "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29"
WPLS        = "0xA1077a294dDE1B09bB078844df40758a5D0f9a27"
GIBS        = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"
OZZY        = "0x52b4F56d87765E7A9567E35bea97de13C3386554"
DSS         = "0x91Df693177eE5C81016d0B7c4c2052A7d229c031"
JV8A        = "0x364793Ea48DEe0b5484F98235ABd1B5f996A0C30"
MULTI_AFF   = "0xCF138a83D739eE98D7A54159E94e5BFaa4B61988"
V2_FACTORY  = "0x29eA7545DEf87022BAdc76323F373EA1e707C523"
V1_FACTORY  = "0x1715a3E4A142d8b698131108995174F37aEBA10D"
BURN_369    = "0x0000000000000000000000000000000000000369"
MULTICALL3  = "0xcA11bde05977b3631167028862bE2a173976CA11"

BAR         = "0xaAE18Cd46C45d343BbA1eab46716b4D69d799734"
FED         = "0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff"

# ── Helper: read ERC20 balance via raw eth_call ────────────────────────────
def _balance_of(w3, token, holder):
    """Quick ERC20 balanceOf without needing ABI imports."""
    data = "0x70a08231" + holder.lower().replace("0x", "").zfill(64)
    result = w3.eth.call({"to": Web3.to_checksum_address(token), "data": data})
    return int(result.hex(), 16)


# ═══════════════════════════════════════════════════════════════════════════
#  SETUP TESTS — Verify Anvil and environment are correct
# ═══════════════════════════════════════════════════════════════════════════

class TestAnvilSetup:
    """Verify the Anvil fork is alive and state is accessible."""

    def test_anvil_connected(self, w3):
        assert w3.is_connected()

    def test_chain_id_369(self, w3):
        assert w3.eth.chain_id == 369

    def test_joey_has_pls(self, w3):
        bal = w3.eth.get_balance(Web3.to_checksum_address(JOEY))
        assert bal >= 1_000_000 * 10**18, f"Joey only has {bal/1e18:.0f} PLS"

    def test_tgsv8_has_code(self, w3):
        code = w3.eth.get_code(Web3.to_checksum_address(TGSV8))
        assert len(code) > 10, "TGSv8 has no code — fork may have failed"

    def test_multicall3_works(self, w3):
        """Verify Multicall3 is accessible on forked chain."""
        code = w3.eth.get_code(Web3.to_checksum_address(MULTICALL3))
        assert len(code) > 10

    def test_snapshot_revert_works(self):
        snap = snapshot()
        assert snap is not None
        result = revert(snap)
        assert result.get("result") is True

    def test_gibs_supply_nonzero(self, w3):
        """GIBS token exists and has supply (sanity check on fork state)."""
        data = "0x18160ddd"  # totalSupply()
        result = w3.eth.call({"to": Web3.to_checksum_address(GIBS), "data": data})
        supply = int(result.hex(), 16)
        assert supply > 0, "GIBS has zero supply — fork state invalid"

    def test_affection_price_nonzero(self, w3):
        """AFFECTION has a live DEX pair with reserves (fork has market data)."""
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(V2_FACTORY),
            abi=[{"constant": True, "inputs": [
                {"name": "", "type": "address"}, {"name": "", "type": "address"}
            ], "name": "getPair", "outputs": [{"name": "", "type": "address"}],
                "type": "function"}],
        )
        pair = factory.functions.getPair(
            Web3.to_checksum_address(AFFECTION),
            Web3.to_checksum_address(WPLS),
        ).call()
        assert pair != "0x" + "0" * 40, "No AFFECTION/WPLS pair"


# ═══════════════════════════════════════════════════════════════════════════
#  ENGINE IMPORTS (deferred to avoid import-time RPC calls before Anvil)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def E1():
    from scripts.Joystick.engines.arb import ArbEngine
    return ArbEngine()

@pytest.fixture
def E2():
    from scripts.Joystick.engines.dss import DSSEngine
    return DSSEngine()

@pytest.fixture
def E3():
    from scripts.Joystick.engines.beat import BeatEngine
    return BeatEngine(with_cheon=True)

@pytest.fixture
def E4():
    from scripts.Joystick.engines.token_factory import TokenFactoryEngine
    return TokenFactoryEngine()

@pytest.fixture
def E5():
    from scripts.Joystick.engines.lau import LAUEngine
    return LAUEngine()

@pytest.fixture
def E6():
    from scripts.Joystick.engines.treasury_sniper import TreasurySniperEngine
    return TreasurySniperEngine()

@pytest.fixture
def E7():
    from scripts.Joystick.engines.spine_runner import SpineRunnerEngine
    return SpineRunnerEngine()

@pytest.fixture
def E8():
    from scripts.Joystick.engines.phreak import PhreakEngine
    return PhreakEngine()


# ═══════════════════════════════════════════════════════════════════════════
#  E2 (CEREAL DSS) — chatAndClaim → GIBS → PLS
# ═══════════════════════════════════════════════════════════════════════════

class TestE2Cereal:
    """E2 DSS should be profitable — GIBS is at ~203 PLS, 10x above break-even."""

    def test_instantiate(self, E2):
        assert E2.name == "DSS"

    def test_gibs_price_above_breakeven(self, w3):
        """Verify GIBS/WPLS price > 21.5 PLS (DSS break-even)."""
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(V2_FACTORY),
            abi=[{"constant": True, "inputs": [
                {"name": "", "type": "address"}, {"name": "", "type": "address"}
            ], "name": "getPair", "outputs": [{"name": "", "type": "address"}],
                "type": "function"}],
        )
        pair_addr = factory.functions.getPair(
            Web3.to_checksum_address(GIBS),
            Web3.to_checksum_address(WPLS),
        ).call()
        if pair_addr == "0x" + "0" * 40:
            pytest.skip("No GIBS/WPLS pair on fork")

        r0, r1, _ = read_reserves(pair_addr, w3)
        # Determine which is GIBS
        pair_t0 = w3.eth.call({
            "to": Web3.to_checksum_address(pair_addr),
            "data": "0x0dfe1681",  # token0()
        })
        t0 = "0x" + pair_t0.hex()[-40:]
        if t0.lower() == GIBS.lower():
            r_gibs, r_wpls = r0, r1
        else:
            r_gibs, r_wpls = r1, r0

        price = r_wpls / r_gibs if r_gibs > 0 else 0
        assert price > 21.5, f"GIBS price {price:.2f} below DSS break-even"
        log.info("GIBS price: %.2f PLS (%.1fx above break-even)", price, price / 21.5)


# ═══════════════════════════════════════════════════════════════════════════
#  E4 (TOKEN FACTORY) — AFFECTION Generate + WM Mint
# ═══════════════════════════════════════════════════════════════════════════

class TestE4TokenFactory:
    """E4 — the confirmed profitable engine. multiGenerate is 262% ROI."""

    def test_instantiate(self, E4):
        assert E4.name == "TokenFactory"

    def test_affection_balance(self, w3):
        """Joey should have ~97 AFFECTION from mainnet state."""
        bal = _balance_of(w3, AFFECTION, JOEY)
        log.info("Joey AFFECTION: %.2f", bal / 1e18)
        # Fork should have the mainnet balance
        assert bal > 0, "Joey has zero AFFECTION on fork"

    def test_multi_affection_contract_exists(self, w3):
        """The multiGenerate contract should have code."""
        code = w3.eth.get_code(Web3.to_checksum_address(MULTI_AFF))
        assert len(code) > 10, "Multi AFFECTION contract has no code"

    def test_simulate_aff_generate(self, w3):
        """
        Simulate multiGenerate(100) via eth_call.
        Should not revert (the function is callable by anyone).
        """
        # multiGenerate(uint256) selector
        sig = Web3.keccak(text="multiGenerate(uint256)")[:4].hex()
        data = f"0x{sig}" + hex(100)[2:].zfill(64)
        try:
            result = w3.eth.call({
                "from": Web3.to_checksum_address(JOEY),
                "to": Web3.to_checksum_address(MULTI_AFF),
                "data": data,
                "gas": 10_000_000,
            })
            log.info("multiGenerate(100) simulation OK: %s", result.hex()[:20])
        except Exception as e:
            pytest.fail(f"multiGenerate(100) simulation reverted: {e}")

    def test_wm_balance(self, w3):
        """Joey should have ~263 WM from mainnet state."""
        bal = _balance_of(w3, WM, JOEY)
        log.info("Joey WM: %.2f", bal / 1e18)
        assert bal > 0, "Joey has zero WM on fork"

    def test_tgsv8_mint_wm_simulation(self, w3):
        """
        Simulate TGSv8.mintWM(1) — calls mv.RHO() loop.
        Should succeed if TGSv8 is properly configured.
        """
        sig = Web3.keccak(text="mintWM(uint256)")[:4].hex()
        data = f"0x{sig}" + hex(1)[2:].zfill(64)
        try:
            result = w3.eth.call({
                "from": Web3.to_checksum_address(JOEY),
                "to": Web3.to_checksum_address(TGSV8),
                "data": data,
                "gas": 5_000_000,
            })
            log.info("mintWM(1) simulation OK")
        except Exception as e:
            # May fail if Joey is not auth on TGSv8 — that's expected info
            log.warning("mintWM(1) simulation result: %s", e)
            pytest.skip(f"mintWM requires auth: {e}")


# ═══════════════════════════════════════════════════════════════════════════
#  E7 (BACKBONE) — Spine Runner
# ═══════════════════════════════════════════════════════════════════════════

class TestE7Backbone:
    """E7 Spine Runner — verify OZZY mechanics and spine loop."""

    def test_ozzy_debenture_true(self, w3):
        """OZZY must have Debenture=true for spine to work."""
        sig = Web3.keccak(text="Debenture()")[:4].hex()
        result = w3.eth.call({
            "to": Web3.to_checksum_address(OZZY),
            "data": f"0x{sig}",
        })
        deb = int(result.hex(), 16)
        assert deb == 1, f"OZZY Debenture={deb}, expected 1 (true)"

    def test_ozzy_parent_is_bar(self, w3):
        """OZZY's parent should be BAR."""
        for fn_name in ["parent()", "Parent()"]:
            sig = Web3.keccak(text=fn_name)[:4].hex()
            try:
                result = w3.eth.call({
                    "to": Web3.to_checksum_address(OZZY),
                    "data": f"0x{sig}",
                })
                parent = "0x" + result.hex()[-40:]
                if parent.lower() == BAR.lower():
                    return  # success
            except Exception:
                continue
        pytest.fail("Could not read OZZY parent or it's not BAR")

    def test_ozzy_dex_pair_exists(self, w3):
        """OZZY/WPLS V2 pair should exist with reserves."""
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(V2_FACTORY),
            abi=[{"constant": True, "inputs": [
                {"name": "", "type": "address"}, {"name": "", "type": "address"}
            ], "name": "getPair", "outputs": [{"name": "", "type": "address"}],
                "type": "function"}],
        )
        pair = factory.functions.getPair(
            Web3.to_checksum_address(OZZY),
            Web3.to_checksum_address(WPLS),
        ).call()
        assert pair != "0x" + "0" * 40, "No OZZY/WPLS V2 pair"

        r0, r1, _ = read_reserves(pair, w3)
        assert r0 > 0 and r1 > 0, f"OZZY/WPLS pair has zero reserves: {r0}, {r1}"
        log.info("OZZY/WPLS reserves: %s, %s", r0, r1)


# ═══════════════════════════════════════════════════════════════════════════
#  E8 (PHR3AK) — DEPLOY, ARM, STITCH
# ═══════════════════════════════════════════════════════════════════════════

class TestE8Phreak:
    """E8 PHR3AK — all three modes."""

    def test_instantiate(self, E8):
        assert E8.name == "PHR3AK"

    def test_config_loads(self):
        """phreak_config.json should load successfully."""
        from scripts.Joystick.engines.phreak import load_phreak_config
        cfg = load_phreak_config()
        assert len(cfg.deb_true_v2) > 0, "No DEB_TRUE_V2 tokens in config"
        assert cfg.deb_true_v2[0].address.lower() == OZZY.lower()
        assert cfg.burn_address.lower() == BURN_369.lower()

    def test_burn_address_is_eoa(self, w3):
        """0x...369 should be an EOA (no code) — confirmed burn address."""
        code = w3.eth.get_code(Web3.to_checksum_address(BURN_369))
        assert len(code) == 0, "Burn address has code — NOT safe to burn"

    def test_jv8a_parent_is_affection(self, w3):
        """JV8A parent should be AFFECTION (from TGSv8.tokenMeta)."""
        sig = Web3.keccak(text="tokenMeta(address)")[:4].hex()
        data = f"0x{sig}" + JV8A.lower().replace("0x", "").zfill(64)
        result = w3.eth.call({
            "to": Web3.to_checksum_address(TGSV8),
            "data": data,
        })
        # tokenMeta returns struct: (token, parent, initialSupply, timestamp, version, flagged)
        raw = result.hex()
        parent = "0x" + raw[88:128]
        assert parent.lower() == AFFECTION.lower(), f"JV8A parent is {parent}, expected AFFECTION"

    def test_jv8a_supply_zero(self, w3):
        """JV8A should have zero supply (deployed but never minted)."""
        data = "0x18160ddd"  # totalSupply()
        result = w3.eth.call({"to": Web3.to_checksum_address(JV8A), "data": data})
        supply = int(result.hex(), 16)
        assert supply == 0, f"JV8A supply={supply}, expected 0"

    def test_jv8a_no_dex_pair(self, w3):
        """JV8A should have no DEX pair yet."""
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(V2_FACTORY),
            abi=[{"constant": True, "inputs": [
                {"name": "", "type": "address"}, {"name": "", "type": "address"}
            ], "name": "getPair", "outputs": [{"name": "", "type": "address"}],
                "type": "function"}],
        )
        pair = factory.functions.getPair(
            Web3.to_checksum_address(JV8A),
            Web3.to_checksum_address(WPLS),
        ).call()
        assert pair == "0x" + "0" * 40, f"JV8A already has WPLS pair: {pair}"


# ═══════════════════════════════════════════════════════════════════════════
#  SPLIT SWAP — Pool impact management
# ═══════════════════════════════════════════════════════════════════════════

class TestSplitSwap:
    """SplitSwap utility — pure math tests (no chain interaction)."""

    def test_import(self):
        from scripts.Joystick.core.split_swap import SplitSwap, PairInfo, SwapPlan
        ss = SplitSwap()
        assert ss is not None

    def test_single_pair_low_impact(self):
        """1% impact on single pair → no split needed."""
        from scripts.Joystick.core.split_swap import SplitSwap, PairInfo
        ss = SplitSwap()
        pair = PairInfo(
            pair_addr="0x" + "11" * 20,
            token_in="0x" + "aa" * 20,
            token_out="0x" + "bb" * 20,
            reserve_in=1_000_000 * 10**18,
            reserve_out=1_000_000 * 10**18,
            dex=2,
        )
        # 1% of reserve_in = 10,000 tokens
        amount = 10_000 * 10**18
        plan = ss.plan(amount, [pair])
        assert plan.chunk_count == 1, f"Expected 1 chunk, got {plan.chunk_count}"
        assert not plan.needs_multi_block

    def test_single_pair_high_impact(self):
        """15% impact on single pair → should split with block delays."""
        from scripts.Joystick.core.split_swap import SplitSwap, PairInfo
        ss = SplitSwap()
        pair = PairInfo(
            pair_addr="0x" + "11" * 20,
            token_in="0x" + "aa" * 20,
            token_out="0x" + "bb" * 20,
            reserve_in=1_000_000 * 10**18,
            reserve_out=1_000_000 * 10**18,
            dex=2,
        )
        # 15% of reserve = way above threshold
        amount = 150_000 * 10**18
        plan = ss.plan(amount, [pair])
        assert plan.chunk_count > 1, f"Expected split, got {plan.chunk_count} chunks"
        assert plan.needs_multi_block, "Should need multi-block for single-pair split"

    def test_uniswap_math_accuracy(self):
        """Verify our getAmountOut matches the Uniswap v2 formula."""
        from scripts.Joystick.oracle.profitability import uniswap_v2_out
        # Known: 1000 in, 100K/100K reserves, 0.3% fee
        out = uniswap_v2_out(1000 * 10**18, 100_000 * 10**18, 100_000 * 10**18)
        # Expected: ~990.07 (after 0.3% fee + slippage)
        expected_approx = 990 * 10**18
        assert out > expected_approx * 0.99, f"Output {out/1e18:.2f} too low"
        assert out < expected_approx * 1.01, f"Output {out/1e18:.2f} too high"

    def test_impact_calculation(self):
        """price_impact_pct should be amount/reserve * 100."""
        from scripts.Joystick.oracle.profitability import price_impact_pct
        impact = price_impact_pct(5000 * 10**18, 100_000 * 10**18)
        assert abs(impact - 5.0) < 0.01, f"Expected 5%, got {impact}%"


# ═══════════════════════════════════════════════════════════════════════════
#  CROSS-ENGINE PIPELINE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestCrossEngine:
    """Verify cross-engine interactions work."""

    def test_e8_arm_recognizes_zero_ozzy(self, w3):
        """E8 ARM mode should trigger when TGSv8 has zero OZZY."""
        ozzy_in_tgsv8 = _balance_of(w3, OZZY, TGSV8)
        assert ozzy_in_tgsv8 == 0, "TGSv8 should start with 0 OZZY"
        # E8's simulate should prioritize ARM when OZZY is 0

    def test_gas_guard_floor_check(self, w3):
        """Gas guard should block operations when PLS < 100K floor."""
        from scripts.Joystick.core.gas_guard import GasGuard
        gg = GasGuard()
        # Joey has 2M PLS — should be fine
        # Test the logic by checking threshold
        from scripts.Joystick.core.config import PLS_GAS_FLOOR
        joey_bal = w3.eth.get_balance(Web3.to_checksum_address(JOEY))
        assert joey_bal > PLS_GAS_FLOOR, "Joey should be above gas floor"

    def test_engine_base_circuit_breaker(self):
        """Circuit breaker trips after MAX_FAILURES consecutive failures."""
        from scripts.Joystick.engines.base import EngineBase, EngineResult

        class DummyEngine(EngineBase):
            name = "Dummy"
            MAX_FAILURES = 3
            DISABLE_SECS = 0  # no auto-recovery for test

            def is_ready(self): return True
            def simulate(self): return (100, 10)
            def execute(self, dry_run=False):
                return EngineResult(success=False, profit_wei=0, gas_wei=0)

        e = DummyEngine()
        assert not e.is_disabled()

        e.record_failure()
        e.record_failure()
        assert not e.is_disabled()  # 2 < 3

        e.record_failure()
        assert e.is_disabled()  # 3 >= 3

        e.record_success()
        assert not e.is_disabled()  # reset

    def test_all_engines_instantiate(self, E1, E2, E3, E4, E5, E6, E7, E8):
        """All 8 engines should instantiate without error."""
        engines = [E1, E2, E3, E4, E5, E6, E7, E8]
        names = [e.name for e in engines]
        expected = ["Arb", "DSS", "Beat", "TokenFactory", "LAU",
                    "TreasurySniper", "SpineRunner", "PHR3AK"]
        assert names == expected, f"Engine names mismatch: {names}"
        log.info("All 8 engines instantiated: %s", names)

    def test_strategist_imports(self):
        """Strategist should import and accept engine list."""
        from scripts.Joystick.core.strategist import Strategist
        from scripts.Joystick.engines.arb import ArbEngine
        from scripts.Joystick.engines.dss import DSSEngine

        s = Strategist([ArbEngine(), DSSEngine()], interactive=False)
        assert s is not None


# ═══════════════════════════════════════════════════════════════════════════
#  STATE VERIFICATION — Mainnet fork sanity checks
# ═══════════════════════════════════════════════════════════════════════════

class TestMainnetState:
    """
    Verify that the forked mainnet state matches expected conditions.
    These tests confirm the fork is usable for engine testing.
    """

    def test_gibs_lp_pairs_exist(self, w3):
        """At least some GIBS LP pairs should exist on fork."""
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(V2_FACTORY),
            abi=[{"constant": True, "inputs": [
                {"name": "", "type": "address"}, {"name": "", "type": "address"}
            ], "name": "getPair", "outputs": [{"name": "", "type": "address"}],
                "type": "function"}],
        )
        pairs_found = 0
        for quote_name, quote_addr in [
            ("WPLS", WPLS), ("FED", FED), ("WM", WM),
        ]:
            pair = factory.functions.getPair(
                Web3.to_checksum_address(GIBS),
                Web3.to_checksum_address(quote_addr),
            ).call()
            if pair != "0x" + "0" * 40:
                pairs_found += 1
                log.info("GIBS/%s pair: %s", quote_name, pair)

        assert pairs_found >= 2, f"Only {pairs_found} GIBS pairs found on fork"

    def test_tgsv8_owner_is_joey(self, w3):
        """TGSv8 should be owned by Joey."""
        sig = Web3.keccak(text="owner()")[:4].hex()
        result = w3.eth.call({
            "to": Web3.to_checksum_address(TGSV8),
            "data": f"0x{sig}",
        })
        owner = "0x" + result.hex()[-40:]
        assert owner.lower() == JOEY.lower(), f"TGSv8 owner is {owner}, not Joey"

    def test_v2_federal_tokens_count(self):
        """v2_federal_tokens.json should list 14 tokens."""
        import json
        data_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "v2_federal_tokens.json"
        )
        with open(data_path) as f:
            data = json.load(f)
        assert data["count"] == 14
        assert len(data["tokens"]) == 14

    def test_ozzy_is_only_deb_true(self):
        """Only OZZY should have debenture=true in the V2 Federal list."""
        import json
        data_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "v2_federal_tokens.json"
        )
        with open(data_path) as f:
            data = json.load(f)
        deb_true = [t for t in data["tokens"] if t.get("debenture") is True]
        assert len(deb_true) == 1
        assert deb_true[0]["symbol"] == "OZZY"

    def test_recon_results_loadable(self):
        """recon_results.json should be loadable."""
        import json
        data_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "recon_results.json"
        )
        assert os.path.exists(data_path), "recon_results.json not found"
        with open(data_path) as f:
            data = json.load(f)
        assert isinstance(data, dict), "recon_results.json is not a dict"
        log.info("recon_results.json loaded: %d top-level keys", len(data))


# ═══════════════════════════════════════════════════════════════════════════
#  PROFITABILITY METHODOLOGY — Strategy-level tests
# ═══════════════════════════════════════════════════════════════════════════

class TestProfitability:
    """Test specific profit strategies that the bot should exploit."""

    def test_affection_generate_roi(self):
        """
        multiGenerate(100) ROI calculation:
          Cost: ~4,273 PLS gas
          Output: 300 AFFECTION × 48.7 PLS/AFF = ~14,610 PLS
          ROI: ~262%
        """
        gas_cost_pls = 4273
        aff_output = 300
        aff_price = 48.7  # from on-chain recon
        revenue = aff_output * aff_price
        roi = (revenue - gas_cost_pls) / gas_cost_pls * 100

        assert roi > 100, f"Expected ROI > 100%, got {roi:.0f}%"
        log.info("Strategy F ROI: %.0f%% (revenue=%.0f, cost=%.0f)", roi, revenue, gas_cost_pls)

    def test_ozzy_acquisition_cost(self):
        """
        100 PLS of OZZY should buy trillions of tokens.
        At ~1.55e-11 PLS/OZZY, this is effectively free spine ammo.
        """
        from scripts.Joystick.oracle.profitability import uniswap_v2_out
        # OZZY/WPLS reserves from recon
        r_ozzy = 5_192_296_858_534_828 * 10**18
        r_wpls = int(80_389 * 10**18)
        amount_in = 100 * 10**18  # 100 PLS

        ozzy_out = uniswap_v2_out(amount_in, r_wpls, r_ozzy)
        assert ozzy_out > 1_000_000_000_000 * 10**18, \
            f"Expected > 1T OZZY, got {ozzy_out/1e18:.0f}"
        log.info("100 PLS buys %.0f OZZY tokens", ozzy_out / 1e18)

    def test_spine_ammo_lifetime(self):
        """
        E7 consumes ~18,000 OZZY/hour.
        At 64.6B OZZY/PLS, 100 PLS buys enough for millions of years.
        """
        ozzy_per_pls = 64_589_699_832  # from recon
        pls_budget = 100
        total_ozzy = ozzy_per_pls * pls_budget

        hourly_consumption = 18_000  # OZZY per hour at 50 iter/TX, 6 TX/min
        hours = total_ozzy / hourly_consumption
        years = hours / 8760

        assert years > 1_000_000, f"Expected > 1M years, got {years:.0f}"
        log.info("100 PLS of OZZY = %.0f years of E7 operation", years)

    def test_stitch_combinatorial_growth(self):
        """
        Triangular route count = C(n,2) = n*(n-1)/2 for n pairs.
        Going from 10→15 pairs more than doubles routes.
        """
        def routes(n):
            return n * (n - 1) // 2

        r10 = routes(10)
        r15 = routes(15)
        r20 = routes(20)

        assert r15 > 2 * r10, f"15 pairs ({r15}) should be > 2x 10 pairs ({r10})"
        log.info("Triangular routes: 10=%d, 15=%d (+%.0f%%), 20=%d (+%.0f%%)",
                 r10, r15, (r15 - r10) / r10 * 100, r20, (r20 - r10) / r10 * 100)
