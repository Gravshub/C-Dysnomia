"""
Integration tests for ProbeController against an Anvil mainnet fork.

These tests require an Anvil process forking PulseChain mainnet:
    anvil --fork-url https://rpc-pulsechain.g4mm4.io --chain-id 369 --auto-impersonate

Tests auto-skip via the parent conftest's `anvil_url` fixture when Anvil
is not running.
"""
import pytest

from scripts.Joystick.core.probe_controller import (
    ProbeController,
    ProbeMode,
)


@pytest.fixture
def pc(tmp_path):
    return ProbeController(state_path=str(tmp_path / "probe.json"))


# ─── Task 17: basic record_sell + get_swap_logs + no-pending ──────────────

def test_record_sell_with_real_block(pc, w3, joystick_ready):
    """record_sell with a real Anvil block number sets up PendingSell correctly."""
    current_block = w3.eth.block_number
    pc.record_sell(
        sell_gibs_wei=8 * 10**18,
        block_number=current_block,
        tx_hash="0xdead",
    )
    assert pc.state.pending_sell is not None
    assert pc.state.pending_sell.sell_block == current_block
    assert pc.state.pending_sell.deadline_block == current_block + 5


def test_get_swap_logs_returns_list(pc, joystick_ready):
    """_get_swap_logs returns a list (empty or with events) without crashing."""
    logs = pc._get_swap_logs(from_block=1, to_block=2)
    assert isinstance(logs, list)


def test_check_arb_response_no_pending_returns_no_response(pc, joystick_ready):
    """No pending sell → check_arb_response returns NO_RESPONSE."""
    r = pc.check_arb_response()
    assert r.kind.value == "NO_RESPONSE"


# ─── Task 18: arb detection via real Swap event ───────────────────────────

def test_arb_detected_via_real_pair_swap(pc, w3, fund_joey, joystick_ready):
    """
    Force a real Swap event on GIBS/WPLS by submitting a tiny WPLS→GIBS trade
    from a non-Joey, non-Hub address, then verify the controller detects it.
    """
    from web3 import Web3
    from scripts.Joystick.core.config import GIBS_WPLS_V2_PAIR, WPLS, GIBS_LAU, PULSEX_V2_ROUTER

    # Create a fresh non-self address by impersonating a random hot wallet
    test_buyer = Web3.to_checksum_address("0x000000000000000000000000000000000000aBCd")
    from scripts.Joystick.tests.anvil_helpers import set_balance, impersonate
    set_balance(test_buyer, 100_000 * 10**18, "http://127.0.0.1:8545")
    impersonate(test_buyer, "http://127.0.0.1:8545")

    sell_block = w3.eth.block_number
    pc.record_sell(8 * 10**18, sell_block, "0xdead")

    # Submit a WPLS→GIBS swap on the V2 router from test_buyer
    router_abi = [
        {"name": "swapExactTokensForTokens",
         "outputs": [{"type": "uint256[]"}],
         "inputs": [
             {"type": "uint256"}, {"type": "uint256"},
             {"type": "address[]"}, {"type": "address"}, {"type": "uint256"}
         ],
         "type": "function", "stateMutability": "nonpayable"},
    ]
    router = w3.eth.contract(address=PULSEX_V2_ROUTER, abi=router_abi)

    # First wrap PLS → WPLS for the test buyer
    wpls_abi = [{"name": "deposit", "outputs": [], "inputs": [], "type": "function",
                 "stateMutability": "payable"}]
    wpls = w3.eth.contract(address=WPLS, abi=wpls_abi)
    wpls.functions.deposit().transact({"from": test_buyer, "value": 50_000 * 10**18})

    # Approve router
    erc20_abi = [{"name": "approve", "outputs": [{"type": "bool"}],
                  "inputs": [{"type": "address"}, {"type": "uint256"}],
                  "type": "function", "stateMutability": "nonpayable"}]
    wpls_token = w3.eth.contract(address=WPLS, abi=erc20_abi)
    wpls_token.functions.approve(PULSEX_V2_ROUTER, 2**256 - 1).transact({"from": test_buyer})

    # Swap WPLS for GIBS
    deadline = 2**63 - 1
    router.functions.swapExactTokensForTokens(
        50_000 * 10**18, 0, [WPLS, GIBS_LAU], test_buyer, deadline,
    ).transact({"from": test_buyer})

    # Now the controller should detect an arb response
    r = pc.check_arb_response()
    assert r.kind.value == "ARB_DETECTED"
    assert r.gibs_size_wei > 0
    assert pc.state.mode == ProbeMode.LOCKED


# ─── Task 19: full LP-add cycle through real Hub ──────────────────────────

def test_lp_add_cycle_through_real_hub(pc, w3, fund_joey, patch_wallet, joystick_ready, E2):
    """
    Full sequence: simulate an arb response, then call E2's _execute_lp_only_add,
    verify Joey's GIBS/WPLS LP balance increases.
    """
    from scripts.Joystick.core.config import GIBS_WPLS_V2_PAIR, JOEY_WALLET
    from scripts.Joystick.core.chain import erc20

    # Inject the controller into the engine
    E2.probe = pc

    # Pre-arb LP balance
    lp_token = erc20(GIBS_WPLS_V2_PAIR)
    lp_before = lp_token.functions.balanceOf(JOEY_WALLET).call()

    # Simulate an arb that bought 5 GIBS
    pc.state.last_arb_gibs = 5 * 10**18

    # Execute LP-only add
    result = E2._execute_lp_only_add(5 * 10**18)
    assert result.success, f"lp_only_add failed: {result.notes}"

    # Verify LP balance grew
    lp_after = lp_token.functions.balanceOf(JOEY_WALLET).call()
    assert lp_after > lp_before, f"LP balance did not increase: {lp_before} → {lp_after}"

    # Verify clear_lp_add_target (bypasses _execute_harvest which would normally call this)
    pc.clear_lp_add_target()
    assert pc.lp_add_target() is None
