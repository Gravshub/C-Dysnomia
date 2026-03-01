#!/usr/bin/env python3
"""
scan_lau_arb.py — DYSNOMIA Token Arbitrage Scanner

Scans DYSNOMIA tokens for arbitrage opportunities:
  - Buy from contract at fixed market rate (Purchase function)
  - Sell on PulseX DEX at market price (if DEX price > purchase cost)

Covers two route families (from affection.gitbook.io/docs/arbitrage-and-routes):
  AFFECTION routes: AFFECTION → LAU tokens (all 272 QING assets) → DEX
  pDAI routes:      pDAI → pINDEPENDENCE / GIMME FIVE / MATH / RNG → DEX

This mirrors Noumenon's proven strategy: 100 AFFECTION → 33,594 AFFECTION
across 8 trades by purchasing underpriced tokens and selling on DEX.

LAU Discovery:
  1. Blockscout internal-tx scan of MAP (0xD3a7A95012...) to find all 272 QINGs
  2. qing.Asset() on each QING to resolve the underlying LAU token
  3. Seed list of known tokens from CLAUDE.md + affection.gitbook.io

Usage:
  python scripts/scan_lau_arb.py                      # Full scan (all routes)
  python scripts/scan_lau_arb.py --top 10             # Show top 10 only
  python scripts/scan_lau_arb.py --min-profit 100     # Min profit in PLS
  python scripts/scan_lau_arb.py --skip-discovery     # Use seed list only (faster)
"""

import sys, time, argparse
from decimal import Decimal

try:
    from web3 import Web3
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "web3", "requests", "-q"])
    from web3 import Web3
    import requests

# ── RPC ──────────────────────────────────────────────────────────────────────
RPC_READ = "https://rpc.pulsechainstats.com"
RPC_SUBMIT = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(RPC_READ, request_kwargs={"timeout": 30}))
if not w3.is_connected():
    w3 = Web3(Web3.HTTPProvider(RPC_SUBMIT, request_kwargs={"timeout": 30}))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# ── Addresses ────────────────────────────────────────────────────────────────
JOEY_WALLET   = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_LAU      = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
GIBS_QING     = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
JOEY_YUE      = Web3.to_checksum_address("0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0")
AFFECTION     = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
WPLS          = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
MAP_ADDR      = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
WM            = Web3.to_checksum_address("0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29")
ENTEH_LAU     = Web3.to_checksum_address("0xccE83CfF8B531EaDdcf11AB414C59DC046D1aAc7")

# Additional payment tokens (beyond AFFECTION)
PDAI          = Web3.to_checksum_address("0xefD766cCb38EaF1dfd701853BFCe31359239F305")  # pDAI from ETH
PUSDC         = Web3.to_checksum_address("0x15D38573d2feeb82e7ad5187aB8c1D52810B880")   # pUSDC

# Atropa ecosystem tokens (from affection.gitbook.io/docs)
# These accept pDAI (or pUSDC) as payment — same Purchase() mechanic as LAU/AFFECTION
PINDEPENDENCE = Web3.to_checksum_address("0xA2262D7728C689526693aE893D0fD8a352C7073C")
GIMME_FIVE    = Web3.to_checksum_address("0x2fc636E7fDF9f3E8d61033103052079781a6e7D2")
MATH_V11      = Web3.to_checksum_address("0xB680F0cc810317933F234f67EB6A9E923407f05D")  # libAtropaMath v1.1
RNG           = Web3.to_checksum_address("0xa96BcbeD7F01de6CEEd14fC86d90F21a36dE2143")

# All payment tokens to check market rates for
PAYMENT_TOKENS = [
    ("AFFECTION", AFFECTION),
    ("pDAI",      PDAI),
    ("pUSDC",     PUSDC),
    ("WPLS",      WPLS),
]

# Known seed list — (label, token_addr)
# Includes LAUs (accept AFFECTION) + Atropa tokens (accept pDAI/pUSDC)
KNOWN_LAUS = [
    ("GIBS (Joey)",     GIBS_LAU),
    ("GIBS-orphan",     Web3.to_checksum_address("0xabf97a71dfd71f3763c86080693c1ec94e5de846")),
    ("enteh",           ENTEH_LAU),
    # Grav LAU token (from CLAUDE.md: GravQING.Asset)
    ("Grav LAU",        Web3.to_checksum_address("0xF462A6fc9a07c4f4bd03a54e03a5db3024d64D47")),
    # Atropa ecosystem tokens (source: affection.gitbook.io/docs/arbitrage-and-routes)
    ("pINDEPENDENCE",   PINDEPENDENCE),
    ("GIMME FIVE",      GIMME_FIVE),
    ("MATH v1.1",       MATH_V11),
    ("RNG",             RNG),
]

# ── DEX Factories ────────────────────────────────────────────────────────────
PULSEX_V1_FACTORY = Web3.to_checksum_address("0x1715a3E4A142d8b698131108995174F37aEBA10D")
PULSEX_V2_FACTORY = Web3.to_checksum_address("0x29eA7545DEf87022BAdc76323F373EA1e707C523")
NINEMM_FACTORY    = Web3.to_checksum_address("0xE26E7F6b5A43A667dBA42Cd9C829d5C75A8093b1")
PULSEX_V1_ROUTER  = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")

FACTORIES = [
    ("PulseX V1", PULSEX_V1_FACTORY),
    ("PulseX V2", PULSEX_V2_FACTORY),
    ("9mm V2",    NINEMM_FACTORY),
]

ZERO = "0x" + "0" * 40

# ── ABIs ─────────────────────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs": [], "name": "name",        "outputs": [{"type": "string"}],  "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol",      "outputs": [{"type": "string"}],  "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSupply", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxSupply",   "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals",    "outputs": [{"type": "uint8"}],   "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "_a", "type": "address"}], "name": "GetMarketRate",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

FACTORY_ABI = [
    {"inputs": [{"type": "address"}, {"type": "address"}], "name": "getPair",
     "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

PAIR_ABI = [
    {"inputs": [], "name": "token0",      "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1",      "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "getReserves", "outputs": [{"type": "uint112"}, {"type": "uint112"}, {"type": "uint32"}],
     "stateMutability": "view", "type": "function"},
]

QING_ABI = [
    {"inputs": [], "name": "Asset", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

ROUTER_ABI = [
    {"inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}],
     "name": "getAmountsOut", "outputs": [{"name": "amounts", "type": "uint256[]"}],
     "stateMutability": "view", "type": "function"},
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def safe(contract, fn, *args):
    try:
        return getattr(contract.functions, fn)(*args).call()
    except Exception:
        return None

def fmt(val, dec=18):
    if val is None:
        return "N/A"
    return f"{val / 10**dec:,.4f}"

def is_contract(addr):
    try:
        return len(w3.eth.get_code(Web3.to_checksum_address(addr))) > 2
    except Exception:
        return False

# ── Section A: Discover LAU addresses via MAP internal transactions ────────────
def discover_qings_via_blockscout(map_address: str, skip=False) -> list[tuple[str, str]]:
    """
    Query Blockscout for internal transactions from MAP to find all QING contracts.
    Each QING has an Asset() getter that returns the associated LAU token address.
    Returns list of (qing_addr, lau_addr) tuples.
    """
    if skip:
        print("  [--skip-discovery] Skipping MAP enumeration, using seed list only.")
        return []

    print(f"\n{'='*70}")
    print("SECTION A: QING DISCOVERY via MAP Internal Transactions")
    print(f"{'='*70}")
    print(f"MAP: {map_address}")

    qings = []
    base_url = f"https://api.scan.pulsechain.com/api/v2/addresses/{map_address}/internal-transactions"
    params   = {"filter": "from", "page_size": 50}
    page_num = 0

    while True:
        try:
            resp = requests.get(base_url, params=params, timeout=20)
            if resp.status_code != 200:
                print(f"  Blockscout returned {resp.status_code} — stopping pagination")
                break
            data = resp.json()
        except Exception as exc:
            print(f"  Blockscout error: {exc}")
            break

        items = data.get("items", [])
        page_num += 1
        created_this_page = 0

        for tx in items:
            if tx.get("type") != "create":
                continue
            new_contract = tx.get("created_contract", {}).get("hash") or tx.get("to", {}).get("hash")
            if not new_contract:
                continue
            qings.append(new_contract)
            created_this_page += 1

        print(f"  Page {page_num}: {len(items)} internal txs, {created_this_page} CREATE ops")

        next_page = data.get("next_page_params")
        if not next_page:
            break
        params.update(next_page)
        time.sleep(0.3)

    print(f"  Total QINGs found: {len(qings)}")

    # Resolve LAU for each QING
    lau_pairs = []
    for q_raw in qings:
        q_addr = Web3.to_checksum_address(q_raw)
        c = w3.eth.contract(address=q_addr, abi=QING_ABI)
        asset = safe(c, "Asset")
        if asset and asset != ZERO and is_contract(asset):
            lau_pairs.append((q_addr, Web3.to_checksum_address(asset)))

    print(f"  QINGs with resolvable Asset (LAU): {len(lau_pairs)}")
    return lau_pairs


# ── Section B: DEX pair price discovery ──────────────────────────────────────
def get_dex_price_pls(token_addr: str) -> tuple[float, str, str]:
    """
    Find the best DEX pair for token → WPLS and return (price_pls, factory_name, pair_addr).
    Returns (0.0, '', '') if no liquid pair found.
    """
    best_price = 0.0
    best_factory = ""
    best_pair = ""

    # Check direct token → WPLS pairs across all factories
    for fname, faddr in FACTORIES:
        try:
            factory = w3.eth.contract(address=faddr, abi=FACTORY_ABI)
            pair_addr = factory.functions.getPair(
                Web3.to_checksum_address(token_addr), WPLS
            ).call()
        except Exception:
            continue

        if not pair_addr or pair_addr.lower() == ZERO.lower():
            continue

        try:
            pair = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
            t0   = pair.functions.token0().call()
            r0, r1, _ = pair.functions.getReserves().call()
        except Exception:
            continue

        if r0 == 0 or r1 == 0:
            continue

        # Determine which reserve is WPLS
        if t0.lower() == WPLS.lower():
            wpls_reserve, tok_reserve = r0, r1
        else:
            wpls_reserve, tok_reserve = r1, r0

        if tok_reserve == 0:
            continue

        price_pls = wpls_reserve / tok_reserve  # PLS per 1 raw unit → normalize below
        # Both sides are 18 decimals, so ratio is already in "PLS per LAU token"
        if price_pls > best_price:
            best_price   = price_pls
            best_factory = fname
            best_pair    = pair_addr

    return best_price, best_factory, best_pair


def get_token_price_pls(token_addr: str) -> float:
    """token → WPLS via PulseX V1 router getAmountsOut. Returns 0 on failure."""
    if token_addr.lower() == WPLS.lower():
        return 1.0
    try:
        router = w3.eth.contract(address=PULSEX_V1_ROUTER, abi=ROUTER_ABI)
        amounts = router.functions.getAmountsOut(10**18, [
            Web3.to_checksum_address(token_addr), WPLS
        ]).call()
        return amounts[-1] / 1e18
    except Exception:
        return 0.0

def get_affection_price_pls() -> float:
    return get_token_price_pls(AFFECTION)


# ── Section C: Full LAU scan ───────────────────────────────────────────────────
def scan_token(label: str, token_addr: str, payment_prices_pls: dict) -> dict | None:
    """
    Scan a DYSNOMIA token for arbitrage opportunity across all payment tokens.
    payment_prices_pls: {payment_addr: price_in_pls} mapping.
    Returns the best opportunity dict, or None if not eligible.
    """
    c = w3.eth.contract(address=token_addr, abi=ERC20_ABI)

    name     = safe(c, "name")       or "?"
    symbol   = safe(c, "symbol")     or "?"
    total    = safe(c, "totalSupply") or 0
    max_s    = safe(c, "maxSupply")   or 0
    self_bal = safe(c, "balanceOf", token_addr) or 0  # tokens in contract = purchaseable

    if not self_bal or self_bal == 0:
        return None

    # Find the cheapest payment token with a set market rate
    best_cost_pls = None
    best_payment_label = None
    best_payment_addr  = None
    best_rate = None

    for pay_label, pay_addr in PAYMENT_TOKENS:
        rate = safe(c, "GetMarketRate", pay_addr)
        if not rate or rate == 0:
            continue
        pay_price = payment_prices_pls.get(pay_addr, 0.0)
        if pay_price == 0.0:
            continue
        tokens_per_unit = 1e18 / rate      # how many tokens per 1 payment unit
        cost_pls = pay_price / tokens_per_unit  # PLS cost per 1 target token
        if best_cost_pls is None or cost_pls < best_cost_pls:
            best_cost_pls      = cost_pls
            best_payment_label = pay_label
            best_payment_addr  = pay_addr
            best_rate          = rate

    if best_cost_pls is None:
        return None

    # DEX price for this token
    dex_price_pls, dex_factory, dex_pair = get_dex_price_pls(token_addr)
    if dex_price_pls == 0:
        return None

    profit_pls_per_token = dex_price_pls - best_cost_pls
    purchaseable = self_bal / 1e18
    total_profit = profit_pls_per_token * purchaseable

    return {
        "label":            label,
        "address":          token_addr,
        "name":             name,
        "symbol":           symbol,
        "total_supply":     total / 1e18,
        "max_supply":       max_s,
        "self_bal_tokens":  purchaseable,
        "payment_label":    best_payment_label,
        "payment_addr":     best_payment_addr,
        "rate_per_unit":    best_rate / 1e18,
        "dex_price_pls":    dex_price_pls,
        "cost_pls_token":   best_cost_pls,
        "profit_pls_token": profit_pls_per_token,
        "max_tokens":       purchaseable,
        "total_profit_pls": total_profit,
        "dex_factory":      dex_factory,
        "dex_pair":         dex_pair,
    }

# Keep backward-compatible alias
def scan_lau(label, lau_addr, aff_price_pls):
    prices = {AFFECTION: aff_price_pls}
    return scan_token(label, lau_addr, prices)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="LAU arbitrage scanner")
    parser.add_argument("--top",            type=int, default=0,   help="Show only top N results (0 = all)")
    parser.add_argument("--min-profit",     type=float, default=0, help="Min total profit in PLS to include")
    parser.add_argument("--skip-discovery", action="store_true",   help="Skip Blockscout MAP scan (faster, seed list only)")
    args = parser.parse_args()

    # Discover all QINGs from MAP → resolve their LAU assets
    qing_lau_pairs = discover_qings_via_blockscout(MAP_ADDR, skip=args.skip_discovery)

    # Build combined LAU list (seed + discovered, dedup by address)
    seen = set()
    lau_candidates = list(KNOWN_LAUS)
    for qing_addr, lau_addr in qing_lau_pairs:
        if lau_addr.lower() not in seen:
            seen.add(lau_addr.lower())
            lau_candidates.append((f"via MAP QING {qing_addr[:8]}...", lau_addr))

    # Dedup seeds as well
    unique_laus = []
    seen2 = set()
    for label, addr in lau_candidates:
        if addr.lower() not in seen2:
            seen2.add(addr.lower())
            unique_laus.append((label, addr))

    print(f"\nTotal unique LAU candidates: {len(unique_laus)}")

    # Fetch all payment token prices once
    print("Fetching payment token prices...")
    payment_prices_pls = {}
    for pay_label, pay_addr in PAYMENT_TOKENS:
        price = get_token_price_pls(pay_addr)
        payment_prices_pls[pay_addr] = price
        print(f"  {pay_label}: {price:.6f} PLS")

    if payment_prices_pls.get(AFFECTION, 0) == 0:
        print("WARNING: could not fetch AFFECTION price — AFFECTION-route arbs will show zero profit")

    # Scan each token
    print(f"\n{'='*70}")
    print("SCANNING TOKENS FOR ARB OPPORTUNITIES ...")
    print(f"('AFFECTION routes' = LAU tokens  |  'pDAI routes' = Atropa tokens)")
    print(f"{'='*70}")

    results = []
    for label, lau_addr in unique_laus:
        print(f"\r  Scanning {lau_addr[:8]}... ({label[:20]})", end="", flush=True)
        try:
            r = scan_token(label, lau_addr, payment_prices_pls)
            if r:
                results.append(r)
        except Exception as exc:
            pass  # Skip broken tokens silently
        time.sleep(0.05)  # Rate limit

    print(f"\r  Done.{' ' * 60}")

    # Filter and sort
    if args.min_profit > 0:
        results = [r for r in results if r["total_profit_pls"] >= args.min_profit]

    results.sort(key=lambda r: r["profit_pls_token"], reverse=True)

    if args.top > 0:
        results = results[:args.top]

    # ── Output table ──────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"LAU ARB OPPORTUNITIES — {len(results)} found")
    print(f"AFFECTION price: {aff_price_pls:.6f} PLS/AFF")
    print(f"{'='*70}")

    if not results:
        print("\n  No profitable LAU arb opportunities found with current market conditions.")
        print("  Possible reasons:")
        print("  - No DEX pairs exist for these LAU tokens yet")
        print("  - DEX prices are below AFFECTION purchase cost")
        print("  - LAU contracts are fully depleted (self-balance = 0)")
        print("\n  → Consider:")
        print("    1. Running with --skip-discovery=False to get full MAP scan")
        print("    2. Checking AFFECTION price on DEX (may be inflated)")
        print("    3. Watching for new LAU token deployments (fresh tokens start cheap on DEX)")
        return

    # Header
    print(f"\n{'Token':<16} {'Sym':<7} {'Avail':>8} {'Pay via':<10} "
          f"{'DEX(PLS)':>10} {'Cost(PLS)':>10} {'Profit/tok':>12} {'Total PLS':>10} Exchange")
    print("-" * 100)

    for r in results:
        profitable = r["profit_pls_token"] > 0
        flag = "✅" if profitable else "❌"
        print(f"{flag} {r['name'][:14]:<14} {r['symbol'][:6]:<6} "
              f"{r['self_bal_tokens']:>8.2f} {r['payment_label']:<10} "
              f"{r['dex_price_pls']:>10.6f} {r['cost_pls_token']:>10.6f} "
              f"{r['profit_pls_token']:>+12.6f} {r['total_profit_pls']:>10.2f} "
              f"  {r['dex_factory']}")

    print(f"\n{'─'*70}")
    print("EXECUTION COMMANDS:")
    print(f"{'─'*70}")
    for r in results[:5]:
        if r["profit_pls_token"] <= 0:
            continue
        safe_amount = min(r["max_tokens"], 10.0)  # cap at 10 tokens for safety
        print(f"  # {r['name']} ({r['symbol']}) via {r['payment_label']} — {r['profit_pls_token']:+.4f} PLS/token profit")
        print(f"  python scripts/tx_lau_arb.py --token {r['address']} --payment {r['payment_addr']} --amount {safe_amount:.1f} --dry-run")
        print(f"  python scripts/tx_lau_arb.py --token {r['address']} --payment {r['payment_addr']} --amount {safe_amount:.1f}")
        print()

    print("Yuan optimization note:")
    print("  Transfer GIBS_QING tokens to GIBS_LAU (10x) and YUE (40x) to improve Beat modulus:")
    print("  → GIBS_QING: 0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
    print("  → GIBS_LAU:  0x66a08aa12da955eb63d7ac121a88b2b210a07b03  (10x weight)")
    print("  → Joey YUE:  0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0  (40x weight)")


if __name__ == "__main__":
    main()
