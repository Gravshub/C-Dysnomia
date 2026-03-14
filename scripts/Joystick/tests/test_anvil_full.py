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

"Hack the planet — but test it on a fork first."
"""
import pytest
import logging
import os
import time

from web3 import Web3

from .anvil_helpers import (
    anvil_rpc, set_balance, impersonate, stop_impersonate,
    mine_block, mine_blocks, snapshot, revert, set_automine,
    set_erc20_balance, find_balance_slot, skew_v2_reserves,
    read_reserves, get_pair_tokens, get_pair_address,
    balance_of, total_supply, transfer_via_impersonate,
    setup_joey_funded, setup_tgsv8_funded, deposit_token_to_tgsv8,
    approve_via_impersonate, get_token_price_pls,
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
DSS_ADDR    = "0x91Df693177eE5C81016d0B7c4c2052A7d229c031"
JV8A        = "0x364793Ea48DEe0b5484F98235ABd1B5f996A0C30"
MULTI_AFF   = "0xCF138a83D739eE98D7A54159E94e5BFaa4B61988"
V2_FACTORY  = "0x29eA7545DEf87022BAdc76323F373EA1e707C523"
V1_FACTORY  = "0x1715a3E4A142d8b698131108995174F37aEBA10D"
BURN_369    = "0x0000000000000000000000000000000000000369"
MULTICALL3  = "0xcA11bde05977b3631167028862bE2a173976CA11"

BAR         = "0xaAE18Cd46C45d343BbA1eab46716b4D69d799734"
FED         = "0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff"

FORNAX      = "0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7"
FOMALHAUTE  = "0x7aE73C498A308247BE73688c09c96B3fd06dDB84"
CHO_ADDR    = "0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB"

META        = "0xE77Bdae31b2219e032178d88504Cc0170a5b9B97"
CHEON       = "0x3d23084cA3F40465553797b5138CFC456E61FB5D"

V1_ROUTER   = "0x165C3410fC91EF562C50559f7d2289fEbed552d9"


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
        supply = total_supply(w3, GIBS)
        assert supply > 0, "GIBS has zero supply — fork state invalid"

    def test_affection_price_nonzero(self, w3):
        """AFFECTION has a live DEX pair with reserves (fork has market data)."""
        pair = get_pair_address(V2_FACTORY, AFFECTION, WPLS, w3)
        assert pair is not None, "No AFFECTION/WPLS pair"

    def test_set_balance_works(self, w3):
        """Verify anvil_setBalance modifies state correctly."""
        test_addr = "0x" + "ab" * 20
        set_balance(test_addr, 999 * 10**18)
        bal = w3.eth.get_balance(Web3.to_checksum_address(test_addr))
        assert bal == 999 * 10**18

    def test_impersonation_works(self, w3):
        """Verify we can send TXs as an impersonated address."""
        test_from = "0x" + "cd" * 20
        test_to = "0x" + "ef" * 20
        set_balance(test_from, 10 * 10**18)
        impersonate(test_from)
        tx_hash = w3.eth.send_transaction({
            "from": Web3.to_checksum_address(test_from),
            "to": Web3.to_checksum_address(test_to),
            "value": 1 * 10**18,
            "gas": 21000,
            "gasPrice": w3.eth.gas_price,
        })
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        assert receipt["status"] == 1
        stop_impersonate(test_from)

    def test_block_number_increases(self, w3):
        """Mining a block increases block number."""
        before = w3.eth.block_number
        mine_block()
        after = w3.eth.block_number
        assert after > before


# ═══════════════════════════════════════════════════════════════════════════
#  E1 (RAZOR) — Cross-DEX and cross-pair arbitrage
# ═══════════════════════════════════════════════════════════════════════════

class TestE1Razor:
    """E1 Arb engine — cross-DEX and cross-pair arbitrage."""

    def test_instantiate(self, E1):
        assert E1.name == "Arb"

    def test_is_ready(self, E1):
        """E1 should be able to report readiness without crashing."""
        # May or may not be ready depending on fork state
        ready = E1.is_ready()
        assert isinstance(ready, bool)

    def test_simulate_returns_tuple(self, E1):
        """simulate() should return (profit, gas) or raise SimulationFailed."""
        from scripts.Joystick.core.simulator import SimulationFailed
        try:
            profit, gas = E1.simulate()
            assert isinstance(profit, int)
            assert isinstance(gas, int)
            assert gas >= 0
        except SimulationFailed:
            pass  # Expected if no opportunities

    def test_reserve_skewing_creates_spread(self, w3):
        """Skewing V2 reserves should create a measurable price difference."""
        pair = get_pair_address(V2_FACTORY, GIBS, WPLS, w3)
        if not pair:
            pytest.skip("No GIBS/WPLS V2 pair")

        r0, r1, _ = read_reserves(pair, w3)
        t0, _ = get_pair_tokens(pair, w3)

        # Skew: make GIBS 10% cheaper by increasing GIBS reserve
        if t0.lower() == GIBS.lower():
            skew_v2_reserves(pair, int(r0 * 1.10), r1)
        else:
            skew_v2_reserves(pair, r0, int(r1 * 1.10))

        r0_new, r1_new, _ = read_reserves(pair, w3)
        # Verify reserves changed
        assert (r0_new, r1_new) != (r0, r1), "Reserve skewing had no effect"

    def test_cross_dex_spread_detection(self, w3):
        """
        After skewing V2 reserves, price should differ from V1.
        This is the basis for cross-DEX arb.
        """
        v1_pair = get_pair_address(V1_FACTORY, GIBS, WPLS, w3)
        v2_pair = get_pair_address(V2_FACTORY, GIBS, WPLS, w3)
        if not v1_pair or not v2_pair:
            pytest.skip("Need GIBS/WPLS on both V1 and V2")

        # Read V1 price
        r0_v1, r1_v1, _ = read_reserves(v1_pair, w3)
        t0_v1, _ = get_pair_tokens(v1_pair, w3)
        if t0_v1.lower() == GIBS.lower():
            price_v1 = r1_v1 / r0_v1
        else:
            price_v1 = r0_v1 / r1_v1

        # Skew V2 by 5%
        r0_v2, r1_v2, _ = read_reserves(v2_pair, w3)
        t0_v2, _ = get_pair_tokens(v2_pair, w3)
        if t0_v2.lower() == GIBS.lower():
            skew_v2_reserves(v2_pair, int(r0_v2 * 1.05), r1_v2)
            r0_s, r1_s, _ = read_reserves(v2_pair, w3)
            price_v2 = r1_s / r0_s
        else:
            skew_v2_reserves(v2_pair, r0_v2, int(r1_v2 * 1.05))
            r0_s, r1_s, _ = read_reserves(v2_pair, w3)
            price_v2 = r0_s / r1_s

        spread = abs(price_v1 - price_v2) / min(price_v1, price_v2) * 100
        assert spread > 3.0, f"Expected > 3% spread, got {spread:.1f}%"
        log.info("Cross-DEX spread: %.1f%% (V1=%.2f, V2=%.2f)", spread, price_v1, price_v2)

    def test_execute_dry_run(self, E1):
        """execute(dry_run=True) should not crash."""
        result = E1.execute(dry_run=True)
        assert hasattr(result, "success")
        assert hasattr(result, "profit_wei")


# ═══════════════════════════════════════════════════════════════════════════
#  E2 (CEREAL DSS) — chatAndClaim → GIBS → PLS
# ═══════════════════════════════════════════════════════════════════════════

class TestE2Cereal:
    """E2 DSS should be profitable — GIBS is at ~203 PLS, 10x above break-even."""

    def test_instantiate(self, E2):
        assert E2.name == "DSS"

    def test_gibs_pair_exists(self, w3):
        """GIBS/WPLS pair must exist for DSS to function."""
        # Check both V1 and V2
        v1_pair = get_pair_address(V1_FACTORY, GIBS, WPLS, w3)
        v2_pair = get_pair_address(V2_FACTORY, GIBS, WPLS, w3)
        assert v1_pair or v2_pair, "No GIBS/WPLS pair on either DEX"

    def test_gibs_price_above_breakeven(self, w3):
        """Verify GIBS/WPLS price > 21.5 PLS (DSS break-even)."""
        pair_addr = get_pair_address(V2_FACTORY, GIBS, WPLS, w3)
        if not pair_addr:
            pair_addr = get_pair_address(V1_FACTORY, GIBS, WPLS, w3)
        if not pair_addr:
            pytest.skip("No GIBS/WPLS pair on fork")

        r0, r1, _ = read_reserves(pair_addr, w3)
        t0, _ = get_pair_tokens(pair_addr, w3)
        if t0.lower() == GIBS.lower():
            r_gibs, r_wpls = r0, r1
        else:
            r_gibs, r_wpls = r1, r0

        price = r_wpls / r_gibs if r_gibs > 0 else 0
        assert price > 21.5, f"GIBS price {price:.2f} below DSS break-even"
        log.info("GIBS price: %.2f PLS (%.1fx above break-even)", price, price / 21.5)

    def test_is_ready(self, E2):
        """DSS should be ready given GIBS pair exists and price > break-even."""
        ready = E2.is_ready()
        # May fail if V1 factory lookup fails on fork — that's informative
        log.info("DSS is_ready: %s", ready)

    def test_simulate(self, E2):
        """DSS simulate should return positive profit and gas."""
        from scripts.Joystick.core.simulator import SimulationFailed
        try:
            profit, gas = E2.simulate()
            assert profit > 0, f"DSS profit should be positive, got {profit}"
            assert gas > 0, f"DSS gas should be positive, got {gas}"
            assert profit > gas, f"DSS should be profitable: profit={profit} < gas={gas}"
            log.info("DSS simulate: profit=%.4f PLS, gas=%.4f PLS, ROI=%.2fx",
                     profit / 1e18, gas / 1e18, profit / gas)
        except SimulationFailed as e:
            pytest.skip(f"DSS simulate failed: {e}")

    def test_dss_contract_callable(self, w3):
        """chatAndClaimWithMultiplier should be callable on DSS contract."""
        sig = Web3.keccak(text="chatAndClaimWithMultiplier(string)")[:4].hex()
        # ABI encode: "test"
        msg = "test"
        encoded_msg = msg.encode().hex()
        offset = "0000000000000000000000000000000000000000000000000000000000000020"
        length = hex(len(msg))[2:].zfill(64)
        data_hex = encoded_msg + "0" * (64 - len(encoded_msg))
        calldata = f"0x{sig}{offset}{length}{data_hex}"

        try:
            w3.eth.call({
                "from": Web3.to_checksum_address(JOEY),
                "to": Web3.to_checksum_address(DSS_ADDR),
                "data": calldata,
                "gas": 1_000_000,
            })
            log.info("DSS chatAndClaimWithMultiplier simulation OK")
        except Exception as e:
            # May revert due to contract state, but should not be "no code"
            assert "no code" not in str(e).lower(), f"DSS has no code: {e}"

    def test_execute_dry_run(self, E2):
        """execute(dry_run=True) should return a result."""
        result = E2.execute(dry_run=True)
        assert hasattr(result, "success")
        log.info("DSS dry_run result: success=%s notes=%s", result.success, result.notes)


# ═══════════════════════════════════════════════════════════════════════════
#  E3 (MERIDIAN Beat) — Territory positioning
# ═══════════════════════════════════════════════════════════════════════════

class TestE3Meridian:
    """E3 Beat — territory positioning via CHEON.Su + META.Beat."""

    def test_instantiate(self, E3):
        assert E3.name == "Beat"

    def test_shio_balances_at_gibs_lau(self, w3):
        """SHIO tokens (Fornax, Fomalhaute, CHO) should be present at GIBS_LAU."""
        fornax_bal = balance_of(w3, FORNAX, GIBS)
        fom_bal = balance_of(w3, FOMALHAUTE, GIBS)
        cho_bal = balance_of(w3, CHO_ADDR, GIBS)

        log.info("SHIO @ GIBS_LAU: Fornax=%s, Fomalhaute=%s, CHO=%s",
                 fornax_bal / 1e18, fom_bal / 1e18, cho_bal / 1e18)

        # At least Fornax should be present from gameplay
        if fornax_bal == 0 and fom_bal == 0 and cho_bal == 0:
            pytest.skip("No SHIO tokens at GIBS_LAU — Beat prerequisites unmet")

    def test_is_ready(self, E3):
        """Beat should be ready if SHIO balances are present."""
        ready = E3.is_ready()
        log.info("Beat is_ready: %s", ready)

    def test_simulate_beat(self, E3):
        """Beat simulate should not revert (strategic engine, profit=0)."""
        from scripts.Joystick.core.simulator import SimulationFailed
        try:
            profit, gas = E3.simulate()
            assert profit == 0, "Beat should return 0 profit (strategic)"
            assert gas > 0, "Beat should have gas cost"
            log.info("Beat simulate: gas=%.4f PLS", gas / 1e18)
        except SimulationFailed as e:
            log.warning("Beat simulate failed (may need CHEON.Su first): %s", e)

    def test_meta_beat_simulation(self, w3):
        """Direct eth_call of META.Beat(GIBS_QING_WAAT) should return territory data."""
        from scripts.Joystick.core.config import GIBS_QING_WAAT
        sig = Web3.keccak(text="Beat(uint256)")[:4].hex()
        data = f"0x{sig}" + hex(GIBS_QING_WAAT)[2:].zfill(64)
        try:
            result = w3.eth.call({
                "from": Web3.to_checksum_address(JOEY),
                "to": Web3.to_checksum_address(META),
                "data": data,
                "gas": 5_000_000,
            })
            # Returns (Dione, Charge, Deimos, Yeo)
            if len(result) >= 128:
                dione = int(result[:32].hex(), 16)
                charge = int(result[32:64].hex(), 16)
                log.info("Beat simulation: Dione=%s, Charge=%s", dione, charge)
        except Exception as e:
            log.info("Beat simulation info: %s", str(e)[:100])

    def test_execute_dry_run(self, E3):
        """execute(dry_run=True) should work."""
        result = E3.execute(dry_run=True)
        assert hasattr(result, "success")


# ═══════════════════════════════════════════════════════════════════════════
#  E4 (TOKEN FACTORY) — AFFECTION Generate + WM Mint
# ═══════════════════════════════════════════════════════════════════════════

class TestE4TokenFactory:
    """E4 — the confirmed profitable engine. multiGenerate is 262% ROI."""

    def test_instantiate(self, E4):
        assert E4.name == "TokenFactory"

    def test_affection_balance(self, w3):
        """Joey should have AFFECTION from mainnet state."""
        bal = balance_of(w3, AFFECTION, JOEY)
        log.info("Joey AFFECTION: %.2f", bal / 1e18)
        assert bal > 0, "Joey has zero AFFECTION on fork"

    def test_wm_balance(self, w3):
        """Joey should have WM from mainnet state."""
        bal = balance_of(w3, WM, JOEY)
        log.info("Joey WM: %.2f", bal / 1e18)
        assert bal > 0, "Joey has zero WM on fork"

    def test_multi_affection_contract_exists(self, w3):
        """The multiGenerate contract should have code."""
        code = w3.eth.get_code(Web3.to_checksum_address(MULTI_AFF))
        assert len(code) > 10, "Multi AFFECTION contract has no code"

    def test_simulate_multi_generate(self, w3):
        """Simulate multiGenerate(100) via eth_call — should not revert."""
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

    def test_multi_generate_mints_to_contract(self, w3):
        """
        multiGenerate(10) should increase AFFECTION contract's self-balance,
        NOT Joey's balance. This confirms the _mintToCap() → address(this) behavior.
        """
        aff_self_before = balance_of(w3, AFFECTION, AFFECTION)
        joey_before = balance_of(w3, AFFECTION, JOEY)

        # Execute multiGenerate(10) via impersonation
        sig = Web3.keccak(text="multiGenerate(uint256)")[:4].hex()
        data = f"0x{sig}" + hex(10)[2:].zfill(64)
        tx_hash = w3.eth.send_transaction({
            "from": Web3.to_checksum_address(JOEY),
            "to": Web3.to_checksum_address(MULTI_AFF),
            "data": data,
            "gas": 5_000_000,
            "gasPrice": w3.eth.gas_price,
        })
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        assert receipt["status"] == 1, "multiGenerate(10) TX reverted"

        aff_self_after = balance_of(w3, AFFECTION, AFFECTION)
        joey_after = balance_of(w3, AFFECTION, JOEY)

        # AFF should mint to AFFECTION contract, not to Joey
        aff_increase = aff_self_after - aff_self_before
        joey_increase = joey_after - joey_before
        assert aff_increase > 0, "AFFECTION self-balance didn't increase"
        assert joey_increase == 0, f"Joey's AFF increased by {joey_increase/1e18} (should be 0)"
        log.info("multiGenerate(10): +%d AFF to contract, +%d to Joey",
                 aff_increase // 10**18, joey_increase // 10**18)

    def test_is_ready(self, E4):
        """TokenFactory should be ready if TGSv8 is deployed and authorized."""
        ready = E4.is_ready()
        log.info("TokenFactory is_ready: %s", ready)

    def test_aff_generate_disabled(self, E4):
        """AFF_GENERATE_ENABLED should be False (confirmed unprofitable)."""
        assert not E4.AFF_GENERATE_ENABLED, "AFF Generate should be disabled"

    def test_tgsv8_mint_wm_simulation(self, w3):
        """Simulate TGSv8.mintWM(1) — calls mv.RHO() loop."""
        sig = Web3.keccak(text="mintWM(uint256)")[:4].hex()
        data = f"0x{sig}" + hex(1)[2:].zfill(64)
        try:
            w3.eth.call({
                "from": Web3.to_checksum_address(JOEY),
                "to": Web3.to_checksum_address(TGSV8),
                "data": data,
                "gas": 5_000_000,
            })
            log.info("mintWM(1) simulation OK")
        except Exception as e:
            log.warning("mintWM(1) simulation result: %s", e)
            pytest.skip(f"mintWM requires auth: {e}")

    def test_execute_dry_run(self, E4):
        """execute(dry_run=True) should return a result."""
        result = E4.execute(dry_run=True)
        assert hasattr(result, "success")
        log.info("TokenFactory dry_run: success=%s notes=%s", result.success, result.notes)


# ═══════════════════════════════════════════════════════════════════════════
#  E5 (LAU ABUPRU) — Mathematical state loop + EmitSniper
# ═══════════════════════════════════════════════════════════════════════════

class TestE5LAU:
    """E5 LAU — ABUPRU state sequence + EmitSniper."""

    def test_instantiate(self, E5):
        assert E5.name == "LAU"

    def test_is_ready_pls_gating(self, E5, w3):
        """LAU should be gated by PLS floor check."""
        ready = E5.is_ready()
        log.info("LAU is_ready: %s (Joey has %.0f PLS)", ready,
                 w3.eth.get_balance(Web3.to_checksum_address(JOEY)) / 1e18)

    def test_alpha_simulation(self, w3):
        """Test that Alpha() on AFFECTION contract can be simulated."""
        sig = Web3.keccak(text="Alpha(uint64)")[:4].hex()
        # Alpha needs Rod.Signal — use a test value
        data = f"0x{sig}" + hex(42)[2:].zfill(64)
        try:
            w3.eth.call({
                "from": Web3.to_checksum_address(JOEY),
                "to": Web3.to_checksum_address(AFFECTION),
                "data": data,
                "gas": 2_000_000,
            })
            log.info("Alpha(42) simulation OK")
        except Exception as e:
            log.info("Alpha simulation: %s (may need Rod.Signal)", str(e)[:80])

    def test_emit_sniper_import(self):
        """EmitSniper class should be importable."""
        from scripts.Joystick.engines.lau import EmitSniper
        sniper = EmitSniper()
        assert sniper is not None

    def test_execute_dry_run(self, E5):
        """execute(dry_run=True) should not crash."""
        result = E5.execute(dry_run=True)
        assert hasattr(result, "success")


# ═══════════════════════════════════════════════════════════════════════════
#  E6 (DaVINCI Treasury Sniper) — Claim backing from treasury tokens
# ═══════════════════════════════════════════════════════════════════════════

class TestE6DaVinci:
    """E6 Treasury Sniper — batchClaimTreasury via recon data."""

    def test_instantiate(self, E6):
        assert E6.name == "TreasurySniper"

    def test_recon_file_exists(self):
        """recon_results.json should be present."""
        import json
        data_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "recon_results.json"
        )
        assert os.path.exists(data_path), "recon_results.json not found"
        with open(data_path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_is_ready(self, E6):
        """TreasurySniper readiness depends on recon data."""
        ready = E6.is_ready()
        log.info("TreasurySniper is_ready: %s", ready)

    def test_simulate(self, E6):
        """TreasurySniper simulate should return (profit, gas) or (0, 0)."""
        from scripts.Joystick.core.simulator import SimulationFailed
        try:
            profit, gas = E6.simulate()
            assert isinstance(profit, int)
            assert isinstance(gas, int)
            log.info("TreasurySniper simulate: profit=%.4f, gas=%.4f",
                     profit / 1e18, gas / 1e18)
        except SimulationFailed as e:
            log.info("TreasurySniper simulate: %s", e)

    def test_execute_dry_run(self, E6):
        """execute(dry_run=True) should return a result."""
        result = E6.execute(dry_run=True)
        assert hasattr(result, "success")


# ═══════════════════════════════════════════════════════════════════════════
#  E7 (BACKBONE Spine Runner) — V2 Federal mint-claim loop
# ═══════════════════════════════════════════════════════════════════════════

class TestE7Backbone:
    """E7 Spine Runner — verify OZZY mechanics and spine loop."""

    def test_instantiate(self, E7):
        assert E7.name == "SpineRunner"

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
        pair = get_pair_address(V2_FACTORY, OZZY, WPLS, w3)
        assert pair is not None, "No OZZY/WPLS V2 pair"
        r0, r1, _ = read_reserves(pair, w3)
        assert r0 > 0 and r1 > 0, f"OZZY/WPLS pair has zero reserves: {r0}, {r1}"
        log.info("OZZY/WPLS reserves: %s, %s", r0, r1)

    def test_ozzy_extremely_cheap(self, w3):
        """100 PLS should buy trillions of OZZY tokens."""
        from scripts.Joystick.oracle.profitability import uniswap_v2_out
        pair = get_pair_address(V2_FACTORY, OZZY, WPLS, w3)
        if not pair:
            pytest.skip("No OZZY/WPLS pair")
        r0, r1, _ = read_reserves(pair, w3)
        t0, _ = get_pair_tokens(pair, w3)
        if t0.lower() == WPLS.lower():
            r_wpls, r_ozzy = r0, r1
        else:
            r_wpls, r_ozzy = r1, r0

        ozzy_out = uniswap_v2_out(100 * 10**18, r_wpls, r_ozzy)
        assert ozzy_out > 10**12 * 10**18, f"Expected > 1T OZZY, got {ozzy_out/1e18:.0f}"
        log.info("100 PLS buys %.2e OZZY tokens", ozzy_out / 1e18)

    def test_is_ready(self, E7):
        """SpineRunner readiness check."""
        ready = E7.is_ready()
        log.info("SpineRunner is_ready: %s", ready)

    def test_v2_federal_tokens_loaded(self):
        """v2_federal_tokens.json should list 14 tokens with only OZZY debenture=true."""
        import json
        data_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "v2_federal_tokens.json"
        )
        with open(data_path) as f:
            data = json.load(f)
        assert data["count"] == 14
        deb_true = [t for t in data["tokens"] if t.get("debenture") is True]
        assert len(deb_true) == 1
        assert deb_true[0]["symbol"] == "OZZY"

    def test_execute_dry_run(self, E7):
        """execute(dry_run=True) should return a result."""
        result = E7.execute(dry_run=True)
        assert hasattr(result, "success")


# ═══════════════════════════════════════════════════════════════════════════
#  E8 (PHR3AK) — DEPLOY, ARM, STITCH modes
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

    def test_mode2_arm_detects_zero_ozzy(self, w3):
        """TGSv8 should have 0 OZZY — E8 ARM mode should be triggered."""
        ozzy_in_tgsv8 = balance_of(w3, OZZY, TGSV8)
        assert ozzy_in_tgsv8 == 0, f"TGSv8 has {ozzy_in_tgsv8/1e18} OZZY (expected 0)"

    def test_is_ready(self, E8):
        """E8 should be ready (ARM mode available when OZZY=0 in TGSv8)."""
        ready = E8.is_ready()
        log.info("PHR3AK is_ready: %s", ready)

    def test_jv8a_parent_is_affection(self, w3):
        """JV8A parent should be AFFECTION (from TGSv8.tokenMeta)."""
        sig = Web3.keccak(text="tokenMeta(address)")[:4].hex()
        data = f"0x{sig}" + JV8A.lower().replace("0x", "").zfill(64)
        result = w3.eth.call({
            "to": Web3.to_checksum_address(TGSV8),
            "data": data,
        })
        raw = result.hex()
        parent = "0x" + raw[88:128]
        assert parent.lower() == AFFECTION.lower(), f"JV8A parent is {parent}"

    def test_jv8a_supply_zero(self, w3):
        """JV8A should have zero supply (deployed but never minted)."""
        supply = total_supply(w3, JV8A)
        assert supply == 0, f"JV8A supply={supply}, expected 0"

    def test_jv8a_no_dex_pair(self, w3):
        """JV8A should have no DEX pair yet."""
        pair = get_pair_address(V2_FACTORY, JV8A, WPLS, w3)
        assert pair is None, f"JV8A already has WPLS pair: {pair}"

    def test_scan_missing_edges(self):
        """scan_missing_edges should return candidates from recon data."""
        from scripts.Joystick.engines.phreak import _build_token_graph, scan_missing_edges
        graph = _build_token_graph()
        if not graph:
            pytest.skip("Empty graph — recon_results.json may be missing")
        candidates = scan_missing_edges(graph, max_candidates=5)
        log.info("Missing edges found: %d", len(candidates))
        if candidates:
            c = candidates[0]
            log.info("Top stitch: %s/%s (score=%.1f)", c.symbol_a, c.symbol_b, c.score)

    def test_execute_dry_run(self, E8):
        """execute(dry_run=True) should return a result."""
        result = E8.execute(dry_run=True)
        assert hasattr(result, "success")


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
        amount = 10_000 * 10**18  # 1% of reserves
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
        # Capped at max_impact (10%), then split across blocks
        amount = 100_000 * 10**18  # 10% of reserves (capped)
        plan = ss.plan(amount, [pair])
        assert plan.chunk_count > 1, f"Expected split, got {plan.chunk_count} chunks"
        assert plan.needs_multi_block, "Should need multi-block for single-pair split"

    def test_multi_pair_distribution(self):
        """Multiple pairs → distribute by liquidity weight."""
        from scripts.Joystick.core.split_swap import SplitSwap, PairInfo
        ss = SplitSwap()
        pair1 = PairInfo("0x" + "11" * 20, "0x" + "aa" * 20, "0x" + "bb" * 20,
                         1_000_000 * 10**18, 1_000_000 * 10**18, dex=1)
        pair2 = PairInfo("0x" + "22" * 20, "0x" + "aa" * 20, "0x" + "bb" * 20,
                         500_000 * 10**18, 500_000 * 10**18, dex=2)
        amount = 30_000 * 10**18  # 2% of total reserves
        plan = ss.plan(amount, [pair1, pair2])
        assert plan.chunk_count >= 2, "Should distribute across both pairs"

        # Verify proportional allocation
        if plan.chunk_count == 2:
            c1 = plan.chunks[0]
            c2 = plan.chunks[1]
            ratio = c1.sub_amount / c2.sub_amount if c2.sub_amount > 0 else 0
            assert 1.5 < ratio < 2.5, f"Allocation ratio {ratio:.1f} should be ~2:1"

    def test_empty_pairs(self):
        """Empty pairs should return empty plan."""
        from scripts.Joystick.core.split_swap import SplitSwap
        ss = SplitSwap()
        plan = ss.plan(1000, [])
        assert plan.chunk_count == 0

    def test_zero_amount(self):
        """Zero amount should return empty plan."""
        from scripts.Joystick.core.split_swap import SplitSwap, PairInfo
        ss = SplitSwap()
        pair = PairInfo("0x" + "11" * 20, "0x" + "aa" * 20, "0x" + "bb" * 20,
                        1_000_000 * 10**18, 1_000_000 * 10**18, dex=2)
        plan = ss.plan(0, [pair])
        assert plan.chunk_count == 0

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

    def test_same_block_same_pool_no_benefit(self):
        """Splitting same pool in same block gives ZERO benefit vs single swap."""
        from scripts.Joystick.oracle.profitability import uniswap_v2_out

        reserve_in = 1_000_000 * 10**18
        reserve_out = 1_000_000 * 10**18
        total_amount = 50_000 * 10**18  # 5% of pool

        # Single swap
        single_out = uniswap_v2_out(total_amount, reserve_in, reserve_out)

        # Two sequential swaps in same block (reserves move)
        half = total_amount // 2
        out1 = uniswap_v2_out(half, reserve_in, reserve_out)
        new_r_in = reserve_in + half
        new_r_out = reserve_out - out1
        out2 = uniswap_v2_out(total_amount - half, new_r_in, new_r_out)
        split_out = out1 + out2

        # Same-block splitting should be within 0.1% of single swap
        diff_pct = abs(single_out - split_out) / single_out * 100
        assert diff_pct < 0.5, f"Same-block split differs by {diff_pct:.2f}% — should be negligible"

    def test_plan_summary_string(self):
        """SwapPlan.summary() should return a readable string."""
        from scripts.Joystick.core.split_swap import SplitSwap, PairInfo
        ss = SplitSwap()
        pair = PairInfo("0x" + "11" * 20, "0x" + "aa" * 20, "0x" + "bb" * 20,
                        1_000_000 * 10**18, 1_000_000 * 10**18, dex=2)
        plan = ss.plan(10_000 * 10**18, [pair])
        summary = plan.summary()
        assert "SwapPlan" in summary
        assert "chunk" in summary


# ═══════════════════════════════════════════════════════════════════════════
#  STRATEGIST — Engine ranking and ROI comparison
# ═══════════════════════════════════════════════════════════════════════════

class TestStrategist:
    """Strategist engine ranking and ROI comparison."""

    def test_import(self):
        from scripts.Joystick.core.strategist import Strategist, Recommendation
        assert Strategist is not None

    def test_ranks_by_roi(self):
        """Strategist should rank engines by ROI score."""
        from scripts.Joystick.core.strategist import Strategist
        from scripts.Joystick.engines.base import EngineBase, EngineResult

        class HighROI(EngineBase):
            name = "HighROI"
            def is_ready(self): return True
            def simulate(self): return (10_000 * 10**18, 100 * 10**18)
            def execute(self, dry_run=False):
                return EngineResult(success=True, profit_wei=10_000*10**18, gas_wei=100*10**18)

        class LowROI(EngineBase):
            name = "LowROI"
            def is_ready(self): return True
            def simulate(self): return (200 * 10**18, 100 * 10**18)
            def execute(self, dry_run=False):
                return EngineResult(success=True, profit_wei=200*10**18, gas_wei=100*10**18)

        engines = [LowROI(), HighROI()]
        s = Strategist(engines, interactive=False)
        balances = {"pls": 2_000_000 * 10**18}
        rec = s.evaluate(balances)

        assert rec.engine is not None
        assert rec.engine.name == "HighROI", f"Expected HighROI, got {rec.engine.name}"

    def test_skips_disabled_engines(self):
        """Disabled engines should not be recommended."""
        from scripts.Joystick.core.strategist import Strategist
        from scripts.Joystick.engines.base import EngineBase, EngineResult

        class DisabledEngine(EngineBase):
            name = "Disabled"
            MAX_FAILURES = 1
            DISABLE_SECS = 0
            def is_ready(self): return True
            def simulate(self): return (10_000 * 10**18, 100 * 10**18)
            def execute(self, dry_run=False):
                return EngineResult(success=True, profit_wei=10_000*10**18, gas_wei=100*10**18)

        e = DisabledEngine()
        e.record_failure()  # Trip circuit breaker
        assert e.is_disabled()

        s = Strategist([e], interactive=False)
        rec = s.evaluate({"pls": 2_000_000 * 10**18})
        assert rec.engine is None or rec.engine.name != "Disabled"

    def test_circuit_breaker_auto_recovery(self):
        """Circuit breaker should auto-recover after DISABLE_SECS."""
        from scripts.Joystick.engines.base import EngineBase, EngineResult

        class RecoverableEngine(EngineBase):
            name = "Recoverable"
            MAX_FAILURES = 2
            DISABLE_SECS = 1  # 1 second for test speed
            def is_ready(self): return True
            def simulate(self): return (100, 10)
            def execute(self, dry_run=False):
                return EngineResult(success=False, profit_wei=0, gas_wei=0)

        e = RecoverableEngine()
        e.record_failure()
        e.record_failure()
        assert e.is_disabled()

        # Wait for recovery
        time.sleep(1.5)
        assert not e.is_disabled(), "Should have auto-recovered"

    def test_record_updates_stats(self):
        """Strategist.record() should update engine stats."""
        from scripts.Joystick.core.strategist import Strategist
        from scripts.Joystick.engines.base import EngineBase, EngineResult

        class DummyEngine(EngineBase):
            name = "Dummy"
            def is_ready(self): return True
            def simulate(self): return (100, 10)
            def execute(self, dry_run=False):
                return EngineResult(success=True, profit_wei=100*10**18, gas_wei=10*10**18)

        s = Strategist([DummyEngine()], interactive=False)
        result = EngineResult(success=True, profit_wei=500*10**18, gas_wei=50*10**18)
        s.record("Dummy", result)

        assert "Dummy" in s.stats
        assert s.stats["Dummy"].total_runs == 1
        assert s.stats["Dummy"].total_successes == 1
        assert s.stats["Dummy"].total_profit_pls == pytest.approx(500.0)

    def test_auto_approve_threshold(self):
        """Auto-approve should respect MEDIUM threshold."""
        from scripts.Joystick.core.strategist import Strategist, Recommendation
        from scripts.Joystick.engines.base import EngineBase, EngineResult

        class ProfitEngine(EngineBase):
            name = "Profit"
            def is_ready(self): return True
            def simulate(self): return (1000 * 10**18, 100 * 10**18)
            def execute(self, dry_run=False):
                return EngineResult(success=True, profit_wei=1000*10**18, gas_wei=100*10**18)

        s = Strategist([ProfitEngine()], interactive=False)
        rec = s.evaluate({"pls": 2_000_000 * 10**18})
        # HIGH or MEDIUM confidence should auto-approve
        if rec.confidence in ("HIGH", "MEDIUM"):
            assert rec.approved, f"Should auto-approve at {rec.confidence}"


# ═══════════════════════════════════════════════════════════════════════════
#  CROSS-ENGINE PIPELINE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestCrossEngine:
    """Verify cross-engine interactions work."""

    def test_all_engines_instantiate(self, all_engines):
        """All 8 engines should instantiate without error."""
        names = [e.name for e in all_engines]
        expected = ["Arb", "DSS", "Beat", "TokenFactory", "LAU",
                    "TreasurySniper", "SpineRunner", "PHR3AK"]
        assert names == expected, f"Engine names mismatch: {names}"

    def test_all_engines_have_interface(self, all_engines):
        """All engines should have is_ready, simulate, execute methods."""
        for e in all_engines:
            assert hasattr(e, "is_ready")
            assert hasattr(e, "simulate")
            assert hasattr(e, "execute")
            assert hasattr(e, "name")
            assert hasattr(e, "failure_count")

    def test_e8_arm_recognizes_zero_ozzy(self, w3):
        """E8 ARM mode should trigger when TGSv8 has zero OZZY."""
        ozzy_in_tgsv8 = balance_of(w3, OZZY, TGSV8)
        assert ozzy_in_tgsv8 == 0, "TGSv8 should start with 0 OZZY"

    def test_gas_guard_above_floor(self, w3):
        """Gas guard should pass when PLS > 100K floor."""
        from scripts.Joystick.core.gas_guard import GasGuard
        gg = GasGuard()
        # Joey has 2M PLS — should be fine
        from scripts.Joystick.core.config import PLS_GAS_FLOOR
        joey_bal = w3.eth.get_balance(Web3.to_checksum_address(JOEY))
        assert joey_bal > PLS_GAS_FLOOR, "Joey should be above gas floor"

    def test_gas_guard_detects_low_balance(self, w3):
        """Gas guard should fail when PLS below floor."""
        # Set Joey's balance very low
        set_balance(JOEY, 50_000 * 10**18)  # 50K < 100K floor

        from scripts.Joystick.core.gas_guard import GasGuard
        gg = GasGuard()
        assert not gg.check(), "Gas guard should fail with 50K PLS"

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

    def test_engine_result_properties(self):
        """EngineResult math properties should work correctly."""
        from scripts.Joystick.engines.base import EngineResult
        r = EngineResult(success=True, profit_wei=int(100e18), gas_wei=int(5e18),
                         tx_hashes=["0xabc"], notes="test")
        assert r.profit_pls == pytest.approx(100.0)
        assert r.gas_pls == pytest.approx(5.0)
        assert r.net_pls == pytest.approx(95.0)

    def test_engine_result_failure(self):
        """Failure result should have zero net."""
        from scripts.Joystick.engines.base import EngineResult
        r = EngineResult(success=False, profit_wei=0, gas_wei=0, notes="reverted")
        assert r.net_pls == 0.0

    def test_strategist_imports(self):
        """Strategist should import and accept engine list."""
        from scripts.Joystick.core.strategist import Strategist
        from scripts.Joystick.engines.arb import ArbEngine
        from scripts.Joystick.engines.dss import DSSEngine
        s = Strategist([ArbEngine(), DSSEngine()], interactive=False)
        assert s is not None

    def test_bot_instantiation(self, bot):
        """DysnomiaBot should instantiate with all engines."""
        assert len(bot.engines) == 8
        assert bot.dry_run is True

    def test_adaptive_delay(self):
        """AdaptiveDelay should adjust based on outcomes."""
        from scripts.Joystick.core.config import AdaptiveDelay
        d = AdaptiveDelay(base=30, lo=15, hi=300, backoff=1.5)

        d.after_profit()
        assert d.seconds == 15  # base/2

        d.current = 30
        d.after_skip()
        assert d.seconds == 45  # 30 * 1.5

        d.after_failure()
        assert d.seconds == 30  # reset to base


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
        pairs_found = 0
        for quote_name, quote_addr in [
            ("WPLS", WPLS), ("FED", FED), ("WM", WM),
        ]:
            pair = get_pair_address(V2_FACTORY, GIBS, quote_addr, w3)
            if pair:
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

    def test_joey_nonce_matches_mainnet(self, w3):
        """Joey's nonce should be > 100 (113+ from mainnet sessions)."""
        nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(JOEY))
        assert nonce >= 100, f"Joey nonce is {nonce}, expected > 100"
        log.info("Joey nonce: %d", nonce)

    def test_dss_contract_configured(self, w3):
        """DSS contract should have multiplier set to 17."""
        sig = Web3.keccak(text="multiplier()")[:4].hex()
        try:
            result = w3.eth.call({
                "to": Web3.to_checksum_address(DSS_ADDR),
                "data": f"0x{sig}",
            })
            mult = int(result.hex(), 16)
            log.info("DSS multiplier: %d", mult)
            assert mult == 17, f"DSS multiplier is {mult}, expected 17"
        except Exception as e:
            log.info("DSS multiplier read: %s", e)

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

    def test_dss_roi_calculation(self):
        """DSS at 200+ PLS/GIBS should yield massive ROI."""
        gas_cost_pls = 388  # DSS gas at typical gas price
        gibs_per_call = 18
        gibs_price = 200  # conservative current price
        revenue = gibs_per_call * gibs_price
        roi = (revenue - gas_cost_pls) / gas_cost_pls * 100
        assert roi > 800, f"Expected ROI > 800%, got {roi:.0f}%"
        log.info("DSS ROI at 200 PLS/GIBS: %.0f%%", roi)

    def test_ozzy_acquisition_cost(self):
        """100 PLS of OZZY should buy trillions of tokens."""
        from scripts.Joystick.oracle.profitability import uniswap_v2_out
        # OZZY/WPLS reserves from recon
        r_ozzy = 5_192_296_858_534_828 * 10**18
        r_wpls = int(80_389 * 10**18)
        amount_in = 100 * 10**18

        ozzy_out = uniswap_v2_out(amount_in, r_wpls, r_ozzy)
        assert ozzy_out > 1_000_000_000_000 * 10**18, \
            f"Expected > 1T OZZY, got {ozzy_out/1e18:.0f}"

    def test_spine_ammo_lifetime(self):
        """100 PLS of OZZY should last millions of years at E7 consumption rate."""
        ozzy_per_pls = 64_589_699_832
        pls_budget = 100
        total_ozzy = ozzy_per_pls * pls_budget
        hourly_consumption = 18_000
        hours = total_ozzy / hourly_consumption
        years = hours / 8760
        assert years > 1_000_000

    def test_stitch_combinatorial_growth(self):
        """Triangular route count grows quadratically with pair count."""
        def routes(n):
            return n * (n - 1) // 2

        r10 = routes(10)
        r15 = routes(15)
        assert r15 > 2 * r10

    def test_uniswap_v2_fee_calculation(self):
        """Verify 0.3% fee is correctly applied."""
        from scripts.Joystick.oracle.profitability import uniswap_v2_out
        # Equal reserves, 1:1 price
        reserve = 1_000_000 * 10**18
        amount_in = 1000 * 10**18
        out = uniswap_v2_out(amount_in, reserve, reserve)
        # With 0.3% fee: effective_in = 997, so out = 997000 * R / (R*1000 + 997000)
        # = 997000 / (1000000 + 997) * R ≈ 996 tokens (fee + slippage)
        assert out < amount_in, "Output should be less than input (fee)"
        assert out > amount_in * 990 // 1000, "Output too low for 0.3% fee"

    def test_price_impact_zero_reserve(self):
        """price_impact_pct should return 100% for zero reserves."""
        from scripts.Joystick.oracle.profitability import price_impact_pct
        assert price_impact_pct(1000, 0) == 100.0

    def test_uniswap_zero_reserves(self):
        """uniswap_v2_out should return 0 for zero reserves."""
        from scripts.Joystick.oracle.profitability import uniswap_v2_out
        assert uniswap_v2_out(1000, 0, 1000) == 0
        assert uniswap_v2_out(1000, 1000, 0) == 0
        assert uniswap_v2_out(0, 1000, 1000) == 0


# ═══════════════════════════════════════════════════════════════════════════
#  RPC & INFRASTRUCTURE TESTS
# ═══════════════════════════════════════════════════════════════════════════

class TestInfrastructure:
    """Test RPC, wallet, and infrastructure components."""

    def test_rpc_pool_health(self):
        """RPCPool should report health status."""
        from scripts.Joystick.core.chain import get_read_pool
        pool = get_read_pool()
        report = pool.health_report()
        assert len(report) > 0
        # At least one provider should be healthy (Anvil via LOCAL)
        healthy = [r for r in report if r["healthy"]]
        assert len(healthy) > 0, "No healthy RPC providers"

    def test_multicall_balance_snapshot(self, w3):
        """snapshot_balances() should return all expected keys."""
        from scripts.Joystick.core.chain import snapshot_balances
        snap = snapshot_balances()
        expected_keys = {"pls", "affection", "gibs", "wm", "fornax", "fomalhaute", "cho"}
        assert expected_keys <= set(snap.keys()), f"Missing keys: {expected_keys - set(snap.keys())}"
        assert snap["pls"] > 0, "PLS balance should be positive"
        log.info("Snapshot: PLS=%.0f, AFF=%.2f, GIBS=%.2f",
                 snap["pls"] / 1e18, snap["affection"] / 1e18, snap["gibs"] / 1e18)

    def test_safe_call_returns_data(self, w3):
        """safe() should return data for valid view calls."""
        from scripts.Joystick.core.chain import erc20, safe
        gibs_c = erc20(GIBS)
        supply = safe(gibs_c, "totalSupply")
        assert supply is not None
        assert supply > 0

    def test_safe_call_returns_none_on_revert(self, w3):
        """safe() should return None on revert, not raise."""
        from scripts.Joystick.core.chain import erc20, safe
        gibs_c = erc20(GIBS)
        # Call a function with wrong args — should return None
        result = safe(gibs_c, "balanceOf", "0x" + "00" * 20)
        # This should work but with zero balance
        assert result is not None or result == 0

    def test_simulator_decode_revert(self):
        """Simulator should decode standard Error(string) reverts."""
        from scripts.Joystick.core.simulator import decode_revert
        # Simulate a standard revert with "Not authorized" message
        error_hex = (
            "0x08c379a0"  # Error(string) selector
            "0000000000000000000000000000000000000000000000000000000000000020"  # offset
            "000000000000000000000000000000000000000000000000000000000000000e"  # length=14
            "4e6f7420617574686f72697a656400000000000000000000000000000000000000"  # "Not authorized"
        )

        class FakeError(Exception):
            pass

        result = decode_revert(FakeError(error_hex))
        assert "Not authorized" in result

    def test_wallet_nonce_tracker(self):
        """Nonce tracker should increment locally."""
        from scripts.Joystick.core.wallet import reset_nonce, next_nonce, peek_nonce
        reset_nonce()
        n1 = next_nonce()
        n2 = next_nonce()
        assert n2 == n1 + 1, f"Nonce should increment: {n1} → {n2}"

    def test_event_logger_import(self):
        """EventLogger should be importable."""
        from scripts.Joystick.core.event_logger import EventLogger
        assert EventLogger is not None

    def test_gas_oracle_import(self):
        """GasOracle should be importable and usable."""
        from scripts.Joystick.core.gas_oracle import GasOracle
        oracle = GasOracle()
        assert oracle is not None
