#!/usr/bin/env python3
"""
tx_lau_arb.py — DYSNOMIA Token Arbitrage Executor

Executes the arbitrage loop identified by scan_lau_arb.py:
  1. Approve payment token (AFFECTION / pDAI / pUSDC) to target contract
  2. target.Purchase(payment_token, amount) → receive target tokens at fixed rate
  3. Approve target tokens to PulseX V1 router
  4. router.swapExactTokensForTokens([target, WPLS], ...) → receive PLS

Routes (from affection.gitbook.io/docs/arbitrage-and-routes):
  AFFECTION → LAU token (any DYSNOMIA LAU with self-balance) → DEX → PLS
  pDAI      → pINDEPENDENCE / GIMME FIVE / MATH v1.1 / RNG   → DEX → PLS
  pUSDC     → MATH v1.1 (alternative payment)                  → DEX → PLS

Usage:
  # Dry-run (read-only, prints expected outcome)
  python scripts/tx_lau_arb.py --token 0x66a08aa... --payment 0x24F015... --amount 5 --dry-run

  # Execute
  python scripts/tx_lau_arb.py --token 0x66a08aa... --payment 0x24F015... --amount 5

  # Auto: compute safe amount from contract balance and AFFECTION holdings
  python scripts/tx_lau_arb.py --token 0x66a08aa... --payment 0x24F015...

  # pDAI route example
  python scripts/tx_lau_arb.py --token 0xA2262D77... --payment 0xefD766cC... --amount 10

Required env:
  DYSNOMIA_PRIVATE_KEY   Joey's wallet private key

Optional:
  PULSECHAIN_RPC         RPC endpoint (default: https://rpc.pulsechain.com)
  SLIPPAGE               Slippage tolerance 0.0–1.0 (default: 0.02 = 2%)
"""

import os, sys, time, argparse
from web3 import Web3
from eth_account import Account

# ── RPC ──────────────────────────────────────────────────────────────────────
SUBMIT_RPC = "https://rpc.pulsechain.com"
READ_RPC   = "https://rpc.pulsechainstats.com"

w3_read = Web3(Web3.HTTPProvider(READ_RPC,   request_kwargs={"timeout": 30}))
w3      = Web3(Web3.HTTPProvider(SUBMIT_RPC, request_kwargs={"timeout": 60}))
if not w3_read.is_connected():
    w3_read = w3

print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# ── Known addresses ───────────────────────────────────────────────────────────
JOEY_WALLET      = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
AFFECTION        = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
WPLS             = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
PDAI             = Web3.to_checksum_address("0xefD766cCb38EaF1dfd701853BFCe31359239F305")
PULSEX_V1_ROUTER = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")

PAYMENT_LABELS = {
    AFFECTION.lower(): "AFFECTION",
    PDAI.lower():      "pDAI",
    WPLS.lower():      "WPLS",
}

# ── ABIs ─────────────────────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "name": "allowance", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "name",   "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals","outputs": [{"type": "uint8"}], "stateMutability": "view", "type": "function"},
]

PURCHASE_ABI = [
    # Purchase(paymentToken, amountOfTargetTokenToReceive)
    # cost = amount * marketRate / 10**decimals  →  caller pays cost payment tokens
    {"inputs": [{"name": "_t", "type": "address"}, {"name": "_a", "type": "uint256"}],
     "name": "Purchase", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "_a", "type": "address"}], "name": "GetMarketRate",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "name",   "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals","outputs": [{"type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
]

ROUTER_ABI = [
    {"inputs": [
        {"name": "amountIn",    "type": "uint256"},
        {"name": "amountOutMin","type": "uint256"},
        {"name": "path",        "type": "address[]"},
        {"name": "to",          "type": "address"},
        {"name": "deadline",    "type": "uint256"},
    ], "name": "swapExactTokensForTokens",
     "outputs": [{"name": "amounts", "type": "uint256[]"}],
     "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [
        {"name": "amountIn", "type": "uint256"},
        {"name": "path",     "type": "address[]"},
    ], "name": "getAmountsOut",
     "outputs": [{"name": "amounts", "type": "uint256[]"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [
        {"name": "amountOut",   "type": "uint256"},
        {"name": "amountOutMin","type": "uint256"},
        {"name": "path",        "type": "address[]"},
        {"name": "to",          "type": "address"},
        {"name": "deadline",    "type": "uint256"},
    ], "name": "swapExactETHForTokens",
     "outputs": [{"name": "amounts", "type": "uint256[]"}],
     "stateMutability": "payable", "type": "function"},
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def fmt(val, dec=18):
    return f"{val / 10**dec:.6f}"

def safe(contract, fn, *args):
    try:
        return getattr(contract.functions, fn)(*args).call()
    except Exception:
        return None

def send_tx(fn_call, label, account, gas_mult=1.3):
    nonce     = w3.eth.get_transaction_count(JOEY_WALLET)
    gas_price = w3.eth.gas_price
    try:
        gas_est = fn_call.estimate_gas({"from": JOEY_WALLET})
    except Exception as exc:
        print(f"  ⚠ Gas estimation failed: {exc}")
        print("  This transaction will likely revert. Aborting for safety.")
        return None
    cost_pls = gas_est * gas_price / 1e18
    print(f"  Gas: {gas_est:,}  Gwei: {gas_price/1e9:.2f}  Cost: {cost_pls:.4f} PLS")
    tx = fn_call.build_transaction({
        "from": JOEY_WALLET, "nonce": nonce,
        "gas": int(gas_est * gas_mult), "gasPrice": gas_price, "chainId": 369,
    })
    signed   = account.sign_transaction(tx)
    tx_hash  = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  TX: 0x{tx_hash.hex()}")
    receipt  = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    status   = receipt["status"]
    print(f"  Status: {'✓' if status == 1 else '✗ REVERTED'}  Block: {receipt['blockNumber']:,}  "
          f"Gas used: {receipt['gasUsed']:,}")
    assert status == 1, f"{label} FAILED (reverted)"
    return receipt


# ── Main arb flow ─────────────────────────────────────────────────────────────
def run(token_addr: str, payment_addr: str, amount_tokens: float,
        slippage: float, dry_run: bool, account) -> None:

    target  = w3_read.eth.contract(address=token_addr,  abi=PURCHASE_ABI)
    payment = w3_read.eth.contract(address=payment_addr, abi=ERC20_ABI)
    router  = w3_read.eth.contract(address=PULSEX_V1_ROUTER, abi=ROUTER_ABI)

    tok_name  = safe(target, "name")   or token_addr[:8]
    tok_sym   = safe(target, "symbol") or "?"
    pay_label = PAYMENT_LABELS.get(payment_addr.lower(), payment_addr[:8])

    print(f"\n{'='*60}")
    print(f"LAU ARB: {tok_name} ({tok_sym})")
    print(f"  Token:   {token_addr}")
    print(f"  Payment: {payment_addr} [{pay_label}]")
    print(f"{'='*60}")

    # ── Step 1: Gather info ───────────────────────────────────────────────────
    market_rate  = safe(target, "GetMarketRate", payment_addr)
    self_bal     = safe(target, "balanceOf", token_addr)   # contract's own token balance
    joey_pay_bal = safe(payment, "balanceOf", JOEY_WALLET)  # Joey's payment token balance

    if not market_rate or market_rate == 0:
        print(f"❌ No market rate for {pay_label} on this token. Cannot Purchase.")
        return
    if not self_bal or self_bal == 0:
        print(f"❌ Contract self-balance is zero — no tokens available to purchase.")
        return

    rate_human   = market_rate / 1e18  # payment tokens per target token
    avail_tokens = self_bal / 1e18
    joey_pay     = joey_pay_bal / 1e18 if joey_pay_bal else 0.0

    print(f"  Market rate:    {rate_human:.4f} {pay_label} per {tok_sym}")
    print(f"  Contract holds: {avail_tokens:.4f} {tok_sym} (purchaseable)")
    print(f"  Joey holds:     {joey_pay:.4f} {pay_label}")

    # ── Step 2: Compute amount ────────────────────────────────────────────────
    if amount_tokens <= 0:
        # Auto: max we can afford and that's available
        affordable = joey_pay / rate_human if rate_human > 0 else 0.0
        amount_tokens = min(avail_tokens, affordable) * 0.95  # 5% safety margin
        if amount_tokens <= 0:
            print(f"❌ Cannot afford any tokens. Joey has {joey_pay:.4f} {pay_label}, "
                  f"rate = {rate_human:.4f}.")
            return
        print(f"  Auto amount:    {amount_tokens:.4f} {tok_sym} (95% of max affordable)")

    amount_wei     = int(amount_tokens * 1e18)
    payment_cost   = int(amount_wei * market_rate / (10**18))  # cost in payment token units

    print(f"\n  Purchasing:     {amount_tokens:.4f} {tok_sym}")
    print(f"  Paying:         {payment_cost / 1e18:.6f} {pay_label}")

    # ── Step 3: DEX price preview ─────────────────────────────────────────────
    try:
        amounts_out = router.functions.getAmountsOut(amount_wei, [token_addr, WPLS]).call()
        expected_pls = amounts_out[-1] / 1e18
    except Exception as exc:
        print(f"  ⚠ DEX quote failed ({exc}) — cannot estimate output")
        expected_pls = 0.0

    # Cost of payment in PLS
    try:
        pay_in_pls_amounts = router.functions.getAmountsOut(payment_cost, [payment_addr, WPLS]).call()
        cost_in_pls = pay_in_pls_amounts[-1] / 1e18
    except Exception:
        cost_in_pls = 0.0

    profit_pls = expected_pls - cost_in_pls

    print(f"\n  DEX expects:    {expected_pls:.6f} PLS")
    print(f"  Payment costs:  {cost_in_pls:.6f} PLS")
    print(f"  Est. profit:    {profit_pls:+.6f} PLS")

    if profit_pls <= 0:
        print("\n⚠ Warning: Expected profit is zero or negative at current prices.")
        if not dry_run:
            answer = input("Proceed anyway? [y/N]: ").strip().lower()
            if answer != "y":
                print("Aborted.")
                return

    if dry_run:
        print(f"\n[DRY-RUN] No transactions sent. Run without --dry-run to execute.")
        return

    # ── Step 4: Execute transactions ──────────────────────────────────────────
    print(f"\n{'─'*40}")
    print("Step 1/3: Approve payment token")
    print(f"{'─'*40}")
    pay_contract = w3.eth.contract(address=payment_addr, abi=ERC20_ABI)
    # Check current allowance to avoid unnecessary approval tx
    current_allowance = safe(pay_contract, "allowance", JOEY_WALLET, token_addr) or 0
    if current_allowance >= payment_cost:
        print(f"  Allowance sufficient ({current_allowance / 1e18:.4f}) — skipping approve")
    else:
        r1 = send_tx(
            pay_contract.functions.approve(token_addr, payment_cost),
            f"Approve {pay_label}", account
        )
        if r1 is None:
            return
        time.sleep(2)

    print(f"\n{'─'*40}")
    print(f"Step 2/3: Purchase {tok_sym} from contract")
    print(f"{'─'*40}")
    tok_contract = w3.eth.contract(address=token_addr, abi=PURCHASE_ABI)
    r2 = send_tx(
        tok_contract.functions.Purchase(payment_addr, amount_wei),
        f"Purchase {tok_sym}", account
    )
    if r2 is None:
        return
    time.sleep(2)

    # Check balance after purchase
    tok_erc = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
    received = safe(tok_erc, "balanceOf", JOEY_WALLET) or 0
    print(f"  Joey now holds: {received / 1e18:.6f} {tok_sym}")

    print(f"\n{'─'*40}")
    print(f"Step 3/3: Swap {tok_sym} → WPLS on {pay_label} route")
    print(f"{'─'*40}")
    # Approve router to spend received tokens
    r3 = send_tx(
        tok_erc.functions.approve(PULSEX_V1_ROUTER, received),
        f"Approve {tok_sym} for router", account
    )
    if r3 is None:
        return
    time.sleep(2)

    # Execute swap
    min_out = int(expected_pls * (1 - slippage) * 1e18) if expected_pls > 0 else 1
    deadline = w3.eth.get_block("latest")["timestamp"] + 300

    router_w3 = w3.eth.contract(address=PULSEX_V1_ROUTER, abi=ROUTER_ABI)
    r4 = send_tx(
        router_w3.functions.swapExactTokensForTokens(
            received, min_out, [token_addr, WPLS], JOEY_WALLET, deadline
        ),
        f"Swap {tok_sym} → WPLS", account
    )
    if r4 is None:
        return

    print(f"\n{'='*60}")
    print(f"✅ ARB COMPLETE: {tok_name} ({tok_sym})")
    print(f"  Paid:     {payment_cost / 1e18:.6f} {pay_label}")
    print(f"  Received: {received / 1e18:.6f} {tok_sym}")
    print(f"  Swapped for PLS (check wallet balance)")
    print(f"{'='*60}")


# ── CLI ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="DYSNOMIA token Purchase → DEX swap arbitrage")
    parser.add_argument("--token",    required=True,
                        help="Target token address (LAU, pINDEPENDENCE, GIMME FIVE, etc.)")
    parser.add_argument("--payment",  default=AFFECTION,
                        help=f"Payment token address (default: AFFECTION {AFFECTION})")
    parser.add_argument("--amount",   type=float, default=0.0,
                        help="Tokens to purchase (0 = auto-calculate safe max)")
    parser.add_argument("--slippage", type=float,
                        default=float(os.getenv("SLIPPAGE", "0.02")),
                        help="DEX slippage tolerance 0.0–1.0 (default: 0.02 = 2%%)")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Simulate only — no transactions sent")
    parser.add_argument("--rpc",      default=os.getenv("PULSECHAIN_RPC", SUBMIT_RPC),
                        help="PulseChain RPC URL for submission")
    parser.add_argument("--key",      default=os.getenv("DYSNOMIA_PRIVATE_KEY", ""),
                        help="Private key (or set DYSNOMIA_PRIVATE_KEY)")
    args = parser.parse_args()

    if not args.dry_run:
        if not args.key:
            print("ERROR: DYSNOMIA_PRIVATE_KEY not set. Use --dry-run or provide --key")
            sys.exit(1)
        account = Account.from_key(args.key)
        assert account.address.lower() == JOEY_WALLET.lower(), \
            f"Key resolves to {account.address}, expected {JOEY_WALLET}"
        print(f"Wallet: {account.address}")
    else:
        account = None
        print("[DRY-RUN MODE] No transactions will be sent.")

    token_addr   = Web3.to_checksum_address(args.token)
    payment_addr = Web3.to_checksum_address(args.payment)

    run(
        token_addr   = token_addr,
        payment_addr = payment_addr,
        amount_tokens= args.amount,
        slippage     = args.slippage,
        dry_run      = args.dry_run,
        account      = account,
    )


if __name__ == "__main__":
    main()
