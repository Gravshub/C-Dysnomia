"""
test_aff_direct.py — Direct AFFECTION multiGenerate + swap, single RPC.

Bypasses RPCPool to avoid the "replacement transaction underpriced" race
between multiple submit providers sharing a mempool.
"""
import logging
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("aff_direct")

from web3 import Web3
from eth_account import Account

# ── Constants ──────────────────────────────────────────────────────────────
SUBMIT_RPC = "https://rpc.pulsechain.com"
READ_RPC   = "https://rpc-pulsechain.g4mm4.io"
CHAIN_ID   = 369

JOEY_WALLET    = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
AFFECTION      = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
WPLS           = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
MULTI_AFF      = Web3.to_checksum_address("0xCF138a83D739eE98D7A54159E94e5BFaa4B61988")
V1_ROUTER      = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")

MULTI_AFF_ABI = [
    {"inputs":[{"internalType":"uint256","name":"_loops","type":"uint256"}],
     "name":"multiGenerate","outputs":[],"stateMutability":"nonpayable","type":"function"},
]

ERC20_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
     "name":"approve","outputs":[{"name":"","type":"bool"}],
     "stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
     "name":"allowance","outputs":[{"name":"","type":"uint256"}],
     "stateMutability":"view","type":"function"},
]

ROUTER_ABI = [
    {"inputs":[
        {"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},
        {"name":"path","type":"address[]"},{"name":"to","type":"address"},
        {"name":"deadline","type":"uint256"}],
     "name":"swapExactTokensForTokens",
     "outputs":[{"name":"amounts","type":"uint256[]"}],
     "stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],
     "name":"getAmountsOut",
     "outputs":[{"name":"amounts","type":"uint256[]"}],
     "stateMutability":"view","type":"function"},
]

GAS_MULT = 1.3
MAX_SLIPPAGE = 0.02
BATCH = 100

def fmt(wei): return f"{wei / 1e18:,.4f}"


def send_and_wait(w3, acct, fn_call, label, gas_price):
    """Build, sign, send, wait for receipt. Single RPC — no failover race."""
    log.info("→ %s", label)

    # Simulate first
    fn_call.call({"from": acct.address, "gas": 8_000_000})
    log.info("  Simulation OK")

    # Estimate gas
    gas_est = fn_call.estimate_gas({"from": acct.address})
    gas_limit = int(gas_est * GAS_MULT)
    log.info("  Gas estimate: %d (limit: %d, cost: %s PLS)",
             gas_est, gas_limit, fmt(gas_est * gas_price))

    # Build TX
    nonce = w3.eth.get_transaction_count(acct.address, "pending")
    tx = fn_call.build_transaction({
        "from": acct.address,
        "nonce": nonce,
        "gas": gas_limit,
        "gasPrice": gas_price,
        "chainId": CHAIN_ID,
    })

    # Sign + send
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    log.info("  TX: 0x%s", tx_hash.hex())

    # Wait for receipt
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    status = "OK" if receipt["status"] == 1 else "REVERTED"
    log.info("  %s  Block: %d  Gas used: %d",
             status, receipt["blockNumber"], receipt["gasUsed"])
    assert receipt["status"] == 1, f"{label} REVERTED"
    return receipt


def main():
    key = os.getenv("DYSNOMIA_PRIVATE_KEY", "")
    if not key:
        log.error("Set DYSNOMIA_PRIVATE_KEY in .env")
        return
    acct = Account.from_key(key)
    assert acct.address.lower() == JOEY_WALLET.lower(), f"Key mismatch: {acct.address}"

    # Single RPC for submit (avoid mempool race between providers)
    w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC, request_kwargs={"timeout": 60}))
    # Separate read RPC
    w3r = Web3(Web3.HTTPProvider(READ_RPC, request_kwargs={"timeout": 30}))

    multi = w3.eth.contract(address=MULTI_AFF, abi=MULTI_AFF_ABI)
    aff_token = w3r.eth.contract(address=AFFECTION, abi=ERC20_ABI)
    aff_token_w = w3.eth.contract(address=AFFECTION, abi=ERC20_ABI)
    router_r = w3r.eth.contract(address=V1_ROUTER, abi=ROUTER_ABI)
    router_w = w3.eth.contract(address=V1_ROUTER, abi=ROUTER_ABI)

    log.info("=" * 60)
    log.info("  AFFECTION Direct Mint Test")
    log.info("=" * 60)

    # Balances
    pls_bal = w3r.eth.get_balance(JOEY_WALLET)
    aff_bal = aff_token.functions.balanceOf(JOEY_WALLET).call()
    gas_price = w3.eth.gas_price
    log.info("  PLS:       %s", fmt(pls_bal))
    log.info("  AFF:       %s", fmt(aff_bal))
    log.info("  Gas price: %.2f Gwei", gas_price / 1e9)
    log.info("  Nonce:     %d", w3.eth.get_transaction_count(JOEY_WALLET, "pending"))

    aff_minted = BATCH * 3
    aff_minted_wei = aff_minted * 10**18

    # DEX price check
    amounts = router_r.functions.getAmountsOut(aff_minted_wei, [AFFECTION, WPLS]).call()
    wpls_out = amounts[-1]
    log.info("  %d AFF → %s WPLS on V1", aff_minted, fmt(wpls_out))

    # Gas estimate
    gas_est = multi.functions.multiGenerate(BATCH).estimate_gas({"from": JOEY_WALLET})
    gas_cost = gas_est * gas_price
    net = wpls_out - int(gas_cost * GAS_MULT)
    roi = net / gas_cost * 100 if gas_cost > 0 else 0
    log.info("  Gas cost:  %s PLS (est %d gas)", fmt(gas_cost), gas_est)
    log.info("  Net profit: %s PLS (%.0f%% ROI)", fmt(net), roi)

    if roi < 20:
        log.warning("  ROI below 20%% — skipping")
        return

    log.info("")
    log.info("  ── EXECUTING LIVE ──")
    pls_before = w3r.eth.get_balance(JOEY_WALLET)
    aff_before = aff_token.functions.balanceOf(JOEY_WALLET).call()

    t0 = time.time()
    tx_hashes = []
    total_gas = 0

    # ── TX 1: multiGenerate ──────────────────────────────────────────────
    # Re-fetch gas price right before sending
    gas_price = w3.eth.gas_price
    receipt1 = send_and_wait(w3, acct, multi.functions.multiGenerate(BATCH),
                              f"multiGenerate({BATCH}) → {aff_minted} AFF", gas_price)
    tx_hashes.append(receipt1["transactionHash"].hex())
    gas1 = receipt1["gasUsed"] * (receipt1.get("effectiveGasPrice", gas_price))
    total_gas += gas1

    # Verify AFF arrived
    aff_after_mint = aff_token.functions.balanceOf(JOEY_WALLET).call()
    aff_received = aff_after_mint - aff_before
    log.info("  AFF received: %s (expected %d)", fmt(aff_received), aff_minted)
    if aff_received <= 0:
        log.error("  AFF NOT RECEIVED — Generate() sends to contract, not tx.origin")
        log.error("  Need Path B (custom contract). Aborting swap.")
        return

    # ── TX 2: Approve AFF to V1 Router (if needed) ──────────────────────
    allowance = aff_token.functions.allowance(JOEY_WALLET, V1_ROUTER).call()
    if allowance < aff_received:
        gas_price = w3.eth.gas_price
        receipt_approve = send_and_wait(
            w3, acct,
            aff_token_w.functions.approve(V1_ROUTER, 2**256 - 1),
            "Approve AFF → V1 Router (max)", gas_price,
        )
        tx_hashes.append(receipt_approve["transactionHash"].hex())
        total_gas += receipt_approve["gasUsed"] * gas_price

    # ── TX 3: Swap AFF → WPLS ───────────────────────────────────────────
    # Re-check amounts out (price may have shifted)
    amounts_now = router_r.functions.getAmountsOut(aff_received, [AFFECTION, WPLS]).call()
    wpls_expected = amounts_now[-1]
    min_out = int(wpls_expected * (1 - MAX_SLIPPAGE))
    deadline = w3r.eth.get_block("latest")["timestamp"] + 300

    gas_price = w3.eth.gas_price
    receipt_swap = send_and_wait(
        w3, acct,
        router_w.functions.swapExactTokensForTokens(
            aff_received, min_out, [AFFECTION, WPLS], JOEY_WALLET, deadline,
        ),
        f"Swap {fmt(aff_received)} AFF → WPLS (V1)", gas_price,
    )
    tx_hashes.append(receipt_swap["transactionHash"].hex())
    total_gas += receipt_swap["gasUsed"] * gas_price

    elapsed = time.time() - t0

    # ── Results ──────────────────────────────────────────────────────────
    pls_after = w3r.eth.get_balance(JOEY_WALLET)
    aff_after = aff_token.functions.balanceOf(JOEY_WALLET).call()

    log.info("")
    log.info("  ── RESULTS ──")
    log.info("  TX hashes: %s", [f"0x{h}" for h in tx_hashes])
    log.info("  Time:      %.1fs", elapsed)
    log.info("  Total gas: %s PLS", fmt(total_gas))
    log.info("")
    log.info("  PLS: %s → %s (delta: %s)",
             fmt(pls_before), fmt(pls_after), fmt(pls_after - pls_before))
    log.info("  AFF: %s → %s (delta: %s)",
             fmt(aff_before), fmt(aff_after), fmt(aff_after - aff_before))
    log.info("")
    realized = pls_after - pls_before
    log.info("  REALIZED PLS PROFIT: %s PLS", fmt(realized))
    log.info("=" * 60)


if __name__ == "__main__":
    main()
