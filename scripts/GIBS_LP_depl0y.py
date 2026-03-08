#!/usr/bin/env python3
"""
|>JOYSTICK<| — GIBS LAU FULL LP DEPLOYMENT
Deploy 10 PulseX liquidity pools for GIBS LAU token.

Pool 0: GIBS/WPLS  (price anchor, addLiquidityETH on V2)
Pool 1: GIBS/FED   (V2 Router)
Pool 2: GIBS/ATROPA (V1 Router)
Pool 3: GIBS/WM    (V2 Router)
Pool 4: GIBS/PROOF_RES (V2)
Pool 5: GIBS/ZHENG (V2)
Pool 6: GIBS/VOID  (V2)
Pool 7: GIBS/DFM   (V2)
Pool 8: GIBS/PARADE (V2)
Pool 9: GIBS/TLRz  (V2)

Usage:
  source .env
  python3 scripts/GIBS_LP_depl0y.py --status             # check pair existence + balances
  python3 scripts/GIBS_LP_depl0y.py --dry-run --all       # simulate all pools
  python3 scripts/GIBS_LP_depl0y.py --pool 0              # deploy GIBS/WPLS only
  python3 scripts/GIBS_LP_depl0y.py --pool 0 --pool 1     # deploy specific pools
  python3 scripts/GIBS_LP_depl0y.py --all                 # deploy all 10 pools

Requires:
  - DYSNOMIA_PRIVATE_KEY or JOEY_PRIVATE_KEY env var
  - RPC_URL env var (default: http://127.0.0.1:8545 for Anvil)
  - Joey wallet holds sufficient GIBS + partner tokens + PLS for gas
"""
import os
import sys
import time
import argparse
from decimal import Decimal
from web3 import Web3
from eth_account import Account

# ---------------------------------------------------------------------------
# RPC + wallet
# ---------------------------------------------------------------------------
RPC_URL = os.getenv("RPC_URL", os.getenv("PULSECHAIN_RPC", "http://127.0.0.1:8545"))
KEY = os.getenv("JOEY_PRIVATE_KEY") or os.getenv("DYSNOMIA_PRIVATE_KEY")

CHAIN_ID = 369
GAS_MULT = float(os.getenv("GAS_MULT", "1.3"))
SLIPPAGE = float(os.getenv("LP_SLIPPAGE", "0.01"))  # 1%
DEADLINE_SECS = 600  # 10 minutes

# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------
JOEY       = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_LAU   = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
WPLS       = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
FED        = Web3.to_checksum_address("0x1D177CB9EfEEa49A8B97ab1C72785a3A37ABc9Ff")
ATROPA     = Web3.to_checksum_address("0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6")
WM         = Web3.to_checksum_address("0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29")
PROOF_RES  = Web3.to_checksum_address("0xaA1505C928fd85E10a550CfDe9e8F464c3574D8a")
ZHENG      = Web3.to_checksum_address("0x24e62c39e34d7fe2b7df1162e1344eb6eb3b3e15")
VOID       = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")
DFM        = Web3.to_checksum_address("0x51160F352ED148C89d48dfe6384Edd07aFA24E0E")
PARADE     = Web3.to_checksum_address("0xE37ACc54711562510FaFC45d8199Ee329ebBceDd")
TLRz       = Web3.to_checksum_address("0xC7145e1290B1d1221Aba5Ae48d4aCE17c6BE088F")

V1_ROUTER  = Web3.to_checksum_address("0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02")
V2_ROUTER  = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")
V1_FACTORY = Web3.to_checksum_address("0x1715a3E4A142d8b698131108995174F37aEBA10D")
V2_FACTORY = Web3.to_checksum_address("0x29eA7545DEf87022BAdc76323F373EA1e707C523")

ZERO_ADDR  = "0x" + "0" * 40

# ---------------------------------------------------------------------------
# ABIs (minimal, inline — matches codebase convention)
# ---------------------------------------------------------------------------
ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}],
     "name": "approve", "outputs": [{"type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
     "name": "allowance", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"type": "uint8"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSupply", "outputs": [{"type": "uint256"}],
     "stateMutability": "view", "type": "function"},
]

ROUTER_ABI = [
    # addLiquidity — standard Uniswap V2 Router02 (8 params)
    {"inputs": [
        {"name": "tokenA", "type": "address"},
        {"name": "tokenB", "type": "address"},
        {"name": "amountADesired", "type": "uint256"},
        {"name": "amountBDesired", "type": "uint256"},
        {"name": "amountAMin", "type": "uint256"},
        {"name": "amountBMin", "type": "uint256"},
        {"name": "to", "type": "address"},
        {"name": "deadline", "type": "uint256"},
    ], "name": "addLiquidity",
     "outputs": [
        {"name": "amountA", "type": "uint256"},
        {"name": "amountB", "type": "uint256"},
        {"name": "liquidity", "type": "uint256"},
     ], "stateMutability": "nonpayable", "type": "function"},
    # addLiquidityETH — wraps native PLS to WPLS
    {"inputs": [
        {"name": "token", "type": "address"},
        {"name": "amountTokenDesired", "type": "uint256"},
        {"name": "amountTokenMin", "type": "uint256"},
        {"name": "amountETHMin", "type": "uint256"},
        {"name": "to", "type": "address"},
        {"name": "deadline", "type": "uint256"},
    ], "name": "addLiquidityETH",
     "outputs": [
        {"name": "amountToken", "type": "uint256"},
        {"name": "amountETH", "type": "uint256"},
        {"name": "liquidity", "type": "uint256"},
     ], "stateMutability": "payable", "type": "function"},
]

FACTORY_ABI = [
    {"inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"}],
     "name": "getPair", "outputs": [{"type": "address"}],
     "stateMutability": "view", "type": "function"},
]

PAIR_ABI = [
    {"inputs": [], "name": "getReserves",
     "outputs": [
        {"name": "reserve0", "type": "uint112"},
        {"name": "reserve1", "type": "uint112"},
        {"name": "blockTimestampLast", "type": "uint32"},
     ], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token0", "outputs": [{"type": "address"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"type": "address"}],
     "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

# ---------------------------------------------------------------------------
# Pool definitions — exact amounts from the deployment plan
# ---------------------------------------------------------------------------
# partner_amount is in human-readable units (will be multiplied by 10**18)
POOLS = [
    {
        "name": "GIBS/WPLS",
        "partner": WPLS,
        "partner_symbol": "WPLS",
        "gibs_amount": 806,
        "partner_amount": 18_135,
        "router": V2_ROUTER,
        "factory": V2_FACTORY,
        "is_eth": True,
    },
    {
        "name": "GIBS/FED",
        "partner": FED,
        "partner_symbol": "FED",
        "gibs_amount": 854,
        "partner_amount": 324_390,
        "router": V2_ROUTER,
        "factory": V2_FACTORY,
        "is_eth": False,
    },
    {
        "name": "GIBS/ATROPA",
        "partner": ATROPA,
        "partner_symbol": "ATROPA",
        "gibs_amount": 781,
        "partner_amount": Decimal("181.38"),
        "router": V1_ROUTER,
        "factory": V1_FACTORY,
        "is_eth": False,
    },
    {
        "name": "GIBS/WM",
        "partner": WM,
        "partner_symbol": "WM",
        "gibs_amount": 476,
        "partner_amount": 23_501,
        "router": V2_ROUTER,
        "factory": V2_FACTORY,
        "is_eth": False,
    },
    {
        "name": "GIBS/PROOF_RES",
        "partner": PROOF_RES,
        "partner_symbol": "PROOF_RES",
        "gibs_amount": 59,
        "partner_amount": 25_156_996_094,
        "router": V2_ROUTER,
        "factory": V2_FACTORY,
        "is_eth": False,
    },
    {
        "name": "GIBS/ZHENG",
        "partner": ZHENG,
        "partner_symbol": "ZHENG",
        "gibs_amount": 50,
        "partner_amount": Decimal("506.14"),
        "router": V2_ROUTER,
        "factory": V2_FACTORY,
        "is_eth": False,
    },
    {
        "name": "GIBS/VOID",
        "partner": VOID,
        "partner_symbol": "VOID",
        "gibs_amount": 50,
        "partner_amount": Decimal("556.39"),
        "router": V2_ROUTER,
        "factory": V2_FACTORY,
        "is_eth": False,
    },
    {
        "name": "GIBS/DFM",
        "partner": DFM,
        "partner_symbol": "DFM",
        "gibs_amount": 50,
        "partner_amount": 1_285_014_632_271_340,
        "router": V2_ROUTER,
        "factory": V2_FACTORY,
        "is_eth": False,
    },
    {
        "name": "GIBS/PARADE",
        "partner": PARADE,
        "partner_symbol": "PARADE",
        "gibs_amount": 50,
        "partner_amount": 16_025_853_197_523_384,
        "router": V2_ROUTER,
        "factory": V2_FACTORY,
        "is_eth": False,
    },
    {
        "name": "GIBS/TLRz",
        "partner": TLRz,
        "partner_symbol": "TLRz",
        "gibs_amount": 50,
        "partner_amount": 51_994_051_485_760_528,
        "router": V2_ROUTER,
        "factory": V2_FACTORY,
        "is_eth": False,
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def to_wei(amount, decimals=18):
    """Convert human-readable amount to wei. Handles Decimal for fractional amounts."""
    return int(Decimal(str(amount)) * Decimal(10 ** decimals))


def safe(contract, fn, *args):
    """Call a view function; return None on error."""
    try:
        return getattr(contract.functions, fn)(*args).call()
    except Exception:
        return None


def get_pair(w3, factory_addr, tokenA, tokenB):
    """Return pair address or None if not created."""
    factory = w3.eth.contract(address=factory_addr, abi=FACTORY_ABI)
    pair = safe(factory, "getPair", tokenA, tokenB)
    if pair and pair != ZERO_ADDR:
        return Web3.to_checksum_address(pair)
    return None


def send_tx(w3, acct, fn_call, label, nonce, value=0, dry_run=False):
    """
    Simulate via eth_call, estimate gas, sign, submit, wait.
    Returns (receipt, new_nonce) or (None, nonce) on dry-run.
    """
    call_params = {"from": acct.address}
    if value > 0:
        call_params["value"] = value

    # Simulate
    try:
        fn_call.call(call_params)
    except Exception as exc:
        print(f"  SIMULATION FAILED for {label}: {exc}")
        return None, nonce

    if dry_run:
        try:
            gas_est = fn_call.estimate_gas(call_params)
        except Exception:
            gas_est = 0
        gas_price = w3.eth.gas_price
        cost = gas_est * gas_price / 1e18
        print(f"  [dry-run] {label}: gas={gas_est:,} cost={cost:.2f} PLS")
        return None, nonce

    # Estimate gas
    try:
        gas_est = fn_call.estimate_gas(call_params)
    except Exception as exc:
        print(f"  GAS ESTIMATION FAILED for {label}: {exc}")
        return None, nonce

    gas_price = w3.eth.gas_price
    cost = gas_est * gas_price / 1e18
    print(f"  {label}: gas={gas_est:,} cost={cost:.2f} PLS")

    tx_params = {
        "from": acct.address,
        "nonce": nonce,
        "gas": int(gas_est * GAS_MULT),
        "gasPrice": gas_price,
        "chainId": CHAIN_ID,
    }
    if value > 0:
        tx_params["value"] = value

    tx = fn_call.build_transaction(tx_params)
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  TX: 0x{tx_hash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    status = receipt["status"]
    print(f"  Status: {'OK' if status == 1 else 'REVERTED'}  Block: {receipt['blockNumber']:,}")

    if status != 1:
        print(f"  ERROR: {label} REVERTED")
        return None, nonce + 1

    return receipt, nonce + 1


def approve_if_needed(w3, acct, token_addr, spender, amount, label, nonce, dry_run=False):
    """Approve spender if current allowance < amount. Returns new nonce."""
    token = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
    current = safe(token, "allowance", acct.address, spender) or 0
    if current >= amount:
        print(f"  Allowance sufficient for {label} ({current / 1e18:.4f})")
        return nonce

    print(f"  Approving {label}...")
    fn = token.functions.approve(spender, amount)
    receipt, nonce = send_tx(w3, acct, fn, f"Approve {label}", nonce, dry_run=dry_run)
    if receipt is None and not dry_run:
        print(f"  WARNING: Approve for {label} may have failed")
    return nonce


# ---------------------------------------------------------------------------
# Pool deployment
# ---------------------------------------------------------------------------
def deploy_pool(w3, acct, pool_idx, dry_run=False):
    """Deploy a single liquidity pool. Returns True on success."""
    pool = POOLS[pool_idx]
    name = pool["name"]
    partner = pool["partner"]
    router_addr = pool["router"]
    factory_addr = pool["factory"]
    is_eth = pool["is_eth"]

    gibs_wei = to_wei(pool["gibs_amount"])
    partner_wei = to_wei(pool["partner_amount"])

    gibs_min = int(gibs_wei * (1 - SLIPPAGE))
    partner_min = int(partner_wei * (1 - SLIPPAGE))

    router_label = "V1" if router_addr == V1_ROUTER else "V2"
    print(f"\n{'='*60}")
    print(f"POOL {pool_idx}: {name}  [{router_label} Router]")
    print(f"{'='*60}")
    print(f"  GIBS:    {pool['gibs_amount']}")
    print(f"  {pool['partner_symbol']}: {pool['partner_amount']}")

    # Check if pair already exists
    existing = get_pair(w3, factory_addr, GIBS_LAU, partner)
    if existing:
        print(f"  Pair already exists: {existing} — SKIPPING")
        return True

    # Check balances
    gibs_token = w3.eth.contract(address=GIBS_LAU, abi=ERC20_ABI)
    gibs_bal = safe(gibs_token, "balanceOf", acct.address) or 0

    if gibs_bal < gibs_wei:
        print(f"  ERROR: Insufficient GIBS. Have {gibs_bal/1e18:.2f}, need {pool['gibs_amount']}")
        return False

    if is_eth:
        pls_bal = w3.eth.get_balance(acct.address)
        needed = partner_wei + int(5000 * 1e18)  # gas buffer
        if pls_bal < needed:
            print(f"  ERROR: Insufficient PLS. Have {pls_bal/1e18:.0f}, need ~{needed/1e18:.0f}")
            return False
    else:
        partner_token = w3.eth.contract(address=partner, abi=ERC20_ABI)
        partner_bal = safe(partner_token, "balanceOf", acct.address) or 0
        if partner_bal < partner_wei:
            print(f"  ERROR: Insufficient {pool['partner_symbol']}. "
                  f"Have {partner_bal/1e18:.4f}, need {float(pool['partner_amount']):.4f}")
            return False

    nonce = w3.eth.get_transaction_count(acct.address)
    router = w3.eth.contract(address=router_addr, abi=ROUTER_ABI)
    deadline = w3.eth.get_block("latest")["timestamp"] + DEADLINE_SECS

    # Approve GIBS to router
    nonce = approve_if_needed(
        w3, acct, GIBS_LAU, router_addr, gibs_wei,
        f"GIBS->{router_label}", nonce, dry_run=dry_run
    )

    if is_eth:
        # addLiquidityETH — native PLS wraps to WPLS
        fn = router.functions.addLiquidityETH(
            GIBS_LAU, gibs_wei, gibs_min, partner_min, acct.address, deadline
        )
        receipt, nonce = send_tx(
            w3, acct, fn, f"addLiquidityETH {name}", nonce,
            value=partner_wei, dry_run=dry_run
        )
    else:
        # Approve partner token to router
        nonce = approve_if_needed(
            w3, acct, partner, router_addr, partner_wei,
            f"{pool['partner_symbol']}->{router_label}", nonce, dry_run=dry_run
        )

        fn = router.functions.addLiquidity(
            GIBS_LAU, partner, gibs_wei, partner_wei,
            gibs_min, partner_min, acct.address, deadline
        )
        receipt, nonce = send_tx(
            w3, acct, fn, f"addLiquidity {name}", nonce, dry_run=dry_run
        )

    if dry_run:
        print(f"  [dry-run] Pool {pool_idx} simulation complete")
        return True

    if receipt is None:
        print(f"  FAILED: Pool {pool_idx} ({name})")
        return False

    # Verify pair created
    pair_addr = get_pair(w3, factory_addr, GIBS_LAU, partner)
    if pair_addr:
        pair = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
        lp_bal = safe(pair, "balanceOf", acct.address) or 0
        reserves = safe(pair, "getReserves") or (0, 0, 0)
        print(f"  Pair: {pair_addr}")
        print(f"  LP tokens: {lp_bal / 1e18:.6f}")
        print(f"  Reserves: ({reserves[0]/1e18:.4f}, {reserves[1]/1e18:.4f})")
    else:
        print(f"  WARNING: Pair not found after addLiquidity — check TX logs")
        return False

    return True


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------
def show_status(w3, wallet_addr):
    """Display status of all 10 pools."""
    print(f"\n{'='*70}")
    print(f"|>JOYSTICK<| GIBS LP STATUS — Wallet: {wallet_addr}")
    print(f"{'='*70}")

    gibs_token = w3.eth.contract(address=GIBS_LAU, abi=ERC20_ABI)
    gibs_bal = safe(gibs_token, "balanceOf", wallet_addr) or 0
    pls_bal = w3.eth.get_balance(wallet_addr)
    print(f"  GIBS balance: {gibs_bal / 1e18:.4f}")
    print(f"  PLS balance:  {pls_bal / 1e18:.0f}")

    total_lp_value = 0
    for i, pool in enumerate(POOLS):
        pair_addr = get_pair(w3, pool["factory"], GIBS_LAU, pool["partner"])
        if pair_addr:
            pair = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
            lp_bal = safe(pair, "balanceOf", wallet_addr) or 0
            reserves = safe(pair, "getReserves") or (0, 0, 0)
            status = "LIVE"
            total_lp_value += lp_bal
        else:
            lp_bal = 0
            reserves = (0, 0, 0)
            status = "NOT CREATED"

        print(f"\n  Pool {i}: {pool['name']:18s} [{status}]")
        if pair_addr:
            print(f"    Pair:     {pair_addr}")
            print(f"    LP:       {lp_bal / 1e18:.6f}")
            print(f"    Reserves: ({reserves[0]/1e18:.4f}, {reserves[1]/1e18:.4f})")
        else:
            print(f"    GIBS needed:    {pool['gibs_amount']}")
            print(f"    Partner needed: {pool['partner_amount']} {pool['partner_symbol']}")

    # Check partner token balances
    print(f"\n{'='*70}")
    print("PARTNER TOKEN BALANCES")
    print(f"{'='*70}")
    seen = set()
    for pool in POOLS:
        if pool["partner"] in seen or pool["is_eth"]:
            continue
        seen.add(pool["partner"])
        token = w3.eth.contract(address=pool["partner"], abi=ERC20_ABI)
        bal = safe(token, "balanceOf", wallet_addr) or 0
        print(f"  {pool['partner_symbol']:12s}: {bal / 1e18:.4f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="|>JOYSTICK<| GIBS LAU LP Deployment"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Simulate via eth_call, no TX broadcast")
    parser.add_argument("--pool", type=int, action="append",
                        help="Deploy specific pool(s) by index (0-9). Repeatable.")
    parser.add_argument("--all", action="store_true",
                        help="Deploy all 10 pools in order")
    parser.add_argument("--status", action="store_true",
                        help="Show status of all pools (read-only)")
    parser.add_argument("--rpc", type=str, default=None,
                        help="Override RPC URL")
    args = parser.parse_args()

    rpc = args.rpc or RPC_URL
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 60}))
    if not w3.is_connected():
        print(f"ERROR: Cannot connect to RPC at {rpc}")
        sys.exit(1)
    print(f"Connected to {rpc} (chain {w3.eth.chain_id})")

    # Status mode — no key needed
    if args.status:
        show_status(w3, JOEY)
        return

    # Need key for deployment
    key = KEY
    if not key:
        print("ERROR: Set DYSNOMIA_PRIVATE_KEY or JOEY_PRIVATE_KEY env var")
        sys.exit(1)

    acct = Account.from_key(key)
    print(f"Wallet: {acct.address}")
    if acct.address.lower() != JOEY.lower():
        print(f"WARNING: Key resolves to {acct.address}, expected {JOEY}")

    # Determine which pools to deploy
    if args.all:
        pool_indices = list(range(10))
    elif args.pool:
        pool_indices = args.pool
    else:
        print("ERROR: Specify --pool N, --all, or --status")
        sys.exit(1)

    for idx in pool_indices:
        if idx < 0 or idx >= len(POOLS):
            print(f"ERROR: Pool index {idx} out of range (0-9)")
            sys.exit(1)

    # Deploy in order
    results = {}
    for idx in pool_indices:
        ok = deploy_pool(w3, acct, idx, dry_run=args.dry_run)
        results[idx] = ok
        if not ok and not args.dry_run:
            print(f"\nPool {idx} failed. Stopping.")
            break

    # Summary
    print(f"\n{'='*60}")
    print("DEPLOYMENT SUMMARY")
    print(f"{'='*60}")
    for idx, ok in results.items():
        status = "OK" if ok else "FAILED"
        print(f"  Pool {idx}: {POOLS[idx]['name']:18s} [{status}]")

    if all(results.values()):
        print("\nAll requested pools deployed successfully.")
    else:
        failed = [i for i, ok in results.items() if not ok]
        print(f"\nFailed pools: {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
