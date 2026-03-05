#!/usr/bin/env python3
"""
gibs_pair_creator.py — GIBS Liquidity Pair Creation (dry-run by default)

Evaluates three pairing options for GIBS LAU token:
  Option A: GIBS / WPLS (PulseX V1) — unlocks Engine 2 DSS immediately
  Option B: GIBS / AFFECTION — intra-ecosystem pair
  Option C: GIBS / top Atropa tokens (ATROPA, TBILL, HAR)

Usage:
  python scripts/gibs_pair_creator.py --query          # query on-chain state only
  python scripts/gibs_pair_creator.py --option A --dry-run  # simulate Option A
  python scripts/gibs_pair_creator.py --option B --dry-run  # simulate Option B
  python scripts/gibs_pair_creator.py --option C --dry-run  # simulate Option C

NEVER runs live TXs without explicit --live flag (not yet implemented).
"""
import argparse
import json
import os
import sys
from dataclasses import dataclass
from enum import IntEnum

from dotenv import load_dotenv
load_dotenv()

from web3 import Web3

# ── Constants ─────────────────────────────────────────────────────────────────

RPC_READ = os.getenv("PULSECHAIN_READ_RPC", "https://rpc-pulsechain.g4mm4.io")
RPC_SUBMIT = os.getenv("PULSECHAIN_RPC", "https://rpc.pulsechain.com")

JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_LAU    = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
AFFECTION   = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
WPLS        = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
TGSV8       = Web3.to_checksum_address(os.getenv("TGSV8_ADDRESS", "0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32"))
DEAD_ADDR   = Web3.to_checksum_address("0x000000000000000000000000000000000000dEaD")

# Atropa ecosystem tokens (Option C)
ATROPA = Web3.to_checksum_address("0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6")
TBILL  = Web3.to_checksum_address("0x463413c579D29c26D59a65312657DFCe30D545A1")
HAR    = Web3.to_checksum_address("0x557F7e30aA6D909Cfe8a229A4CB178ab186EC622")

# PulseX factories
PULSEX_V1_FACTORY = Web3.to_checksum_address("0x1715a3E4A142d8b698131108995174F37aEBA10D")
PULSEX_V2_FACTORY = Web3.to_checksum_address("0x29eA7545DEf87022BAdc76323F373EA1e707C523")
PULSEX_V1_ROUTER  = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")

ZERO_ADDR = "0x" + "0" * 40

ERC20_ABI = [
    {"inputs": [], "name": "totalSupply", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxSupply", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
]

FACTORY_ABI = [
    {"inputs": [{"name": "tokenA", "type": "address"}, {"name": "tokenB", "type": "address"}],
     "name": "getPair", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

ROUTER_ABI = [
    {"inputs": [{"name": "amountIn", "type": "uint256"}, {"name": "path", "type": "address[]"}],
     "name": "getAmountsOut", "outputs": [{"type": "uint256[]"}], "stateMutability": "view", "type": "function"},
]


class DEX(IntEnum):
    V1 = 0
    V2 = 1


class StepType(IntEnum):
    TRANSFER_IN = 0
    TRANSFER_OUT = 1
    ADD_LIQUIDITY = 2
    APPROVE = 3


@dataclass
class Step:
    type: StepType
    token: str = ""
    tokenA: str = ""
    tokenB: str = ""
    amount: int = 0
    amountA: int = 0
    amountB: int = 0
    to: str = ""
    dex: DEX = DEX.V1
    note: str = ""


# ── On-chain queries ──────────────────────────────────────────────────────────

def query_state():
    """Query all on-chain state needed for the strategy analysis."""
    w3 = Web3(Web3.HTTPProvider(RPC_READ, request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        print("ERROR: Cannot connect to RPC")
        sys.exit(1)

    gibs = w3.eth.contract(address=GIBS_LAU, abi=ERC20_ABI)
    aff = w3.eth.contract(address=AFFECTION, abi=ERC20_ABI)

    state = {}

    # GIBS state
    state["gibs_total_supply"] = gibs.functions.totalSupply().call()
    try:
        state["gibs_max_supply"] = gibs.functions.maxSupply().call()
    except Exception:
        state["gibs_max_supply"] = 0
    state["gibs_joey_balance"] = gibs.functions.balanceOf(JOEY_WALLET).call()

    # AFFECTION state
    state["aff_joey_balance"] = aff.functions.balanceOf(JOEY_WALLET).call()

    # PLS balance
    state["pls_balance"] = w3.eth.get_balance(JOEY_WALLET)

    # Check existing pairs
    v1_factory = w3.eth.contract(address=PULSEX_V1_FACTORY, abi=FACTORY_ABI)
    v2_factory = w3.eth.contract(address=PULSEX_V2_FACTORY, abi=FACTORY_ABI)

    pairs = {}
    for label, tokenB in [("WPLS", WPLS), ("AFFECTION", AFFECTION)]:
        v1_pair = v1_factory.functions.getPair(GIBS_LAU, tokenB).call()
        v2_pair = v2_factory.functions.getPair(GIBS_LAU, tokenB).call()
        pairs[f"GIBS/{label}_V1"] = v1_pair if v1_pair != ZERO_ADDR else None
        pairs[f"GIBS/{label}_V2"] = v2_pair if v2_pair != ZERO_ADDR else None
    state["pairs"] = pairs

    # Check Atropa token pairs with GIBS
    for label, token in [("ATROPA", ATROPA), ("TBILL", TBILL), ("HAR", HAR)]:
        v1_pair = v1_factory.functions.getPair(GIBS_LAU, token).call()
        v2_pair = v2_factory.functions.getPair(GIBS_LAU, token).call()
        pairs[f"GIBS/{label}_V1"] = v1_pair if v1_pair != ZERO_ADDR else None
        pairs[f"GIBS/{label}_V2"] = v2_pair if v2_pair != ZERO_ADDR else None

    # Price queries via router
    router = w3.eth.contract(address=PULSEX_V1_ROUTER, abi=ROUTER_ABI)
    try:
        aff_price = router.functions.getAmountsOut(int(1e18), [AFFECTION, WPLS]).call()
        state["affection_price_pls"] = aff_price[1]
    except Exception:
        state["affection_price_pls"] = 0

    # Check Atropa/TBILL/HAR prices in PLS
    for label, token in [("ATROPA", ATROPA), ("TBILL", TBILL), ("HAR", HAR)]:
        try:
            price = router.functions.getAmountsOut(int(1e18), [token, WPLS]).call()
            state[f"{label.lower()}_price_pls"] = price[1]
        except Exception:
            state[f"{label.lower()}_price_pls"] = 0

    return state


def print_state(state: dict):
    """Pretty-print the on-chain state."""
    print("\n" + "=" * 60)
    print("  GIBS ON-CHAIN STATE")
    print("=" * 60)
    print(f"  GIBS totalSupply:  {state['gibs_total_supply'] / 1e18:,.4f}")
    print(f"  GIBS maxSupply:    {state['gibs_max_supply'] / 1e18:,.4f}" if state['gibs_max_supply'] else "  GIBS maxSupply:    (not available)")
    print(f"  GIBS Joey holds:   {state['gibs_joey_balance'] / 1e18:,.4f}")
    print(f"  AFFECTION Joey:    {state['aff_joey_balance'] / 1e18:,.4f}")
    print(f"  PLS balance:       {state['pls_balance'] / 1e18:,.1f}")
    print()
    print("  EXISTING PAIRS:")
    for name, addr in state["pairs"].items():
        status = addr[:10] + "..." if addr else "NONE"
        print(f"    {name:<25} {status}")
    print()
    print("  PRICES:")
    aff_pls = state.get("affection_price_pls", 0)
    print(f"    1 AFFECTION = {aff_pls / 1e18:.6f} PLS" if aff_pls else "    AFFECTION/PLS: no pair")
    for label in ["atropa", "tbill", "har"]:
        price = state.get(f"{label}_price_pls", 0)
        if price:
            print(f"    1 {label.upper()} = {price / 1e18:.6f} PLS")
        else:
            print(f"    {label.upper()}/PLS: no pair")

    # Compute GIBS implied price
    # DSS break-even: ~21.5 PLS/GIBS (from Session 1 analysis)
    gibs_implied_pls = 21.5
    print(f"\n  IMPLIED GIBS PRICE (DSS break-even): ~{gibs_implied_pls:.1f} PLS/GIBS")
    if aff_pls > 0:
        gibs_per_aff = gibs_implied_pls / (aff_pls / 1e18)
        print(f"  IMPLIED GIBS/AFFECTION ratio: {gibs_per_aff:.4f} GIBS per AFFECTION")
    print("=" * 60)


# ── Step arrays for each option ──────────────────────────────────────────────

def option_a_steps(gibs_amount: int, wpls_amount: int) -> list[Step]:
    """
    Option A — GIBS / WPLS on PulseX V1.

    Clean, simple. Unlocks Engine 2 (DSS) immediately.
    Pro: chatAndClaim profit loop enabled (18 GIBS/call at multiplier 17)
    Con: GIBS priced in PLS — vulnerable to PLS pump arb-out
    """
    return [
        Step(type=StepType.APPROVE, token=GIBS_LAU, to=PULSEX_V1_ROUTER,
             amount=gibs_amount, note="Approve GIBS for V1 router"),
        Step(type=StepType.APPROVE, token=WPLS, to=PULSEX_V1_ROUTER,
             amount=wpls_amount, note="Approve WPLS for V1 router"),
        Step(type=StepType.ADD_LIQUIDITY, tokenA=GIBS_LAU, tokenB=WPLS,
             amountA=gibs_amount, amountB=wpls_amount, dex=DEX.V1,
             to=JOEY_WALLET, note="Add GIBS/WPLS LP on V1"),
        # Optional: burn LP for permanent floor
        # Step(type=StepType.TRANSFER_OUT, token="LP_ADDRESS", to=DEAD_ADDR,
        #      note="Burn LP tokens for permanent floor"),
    ]


def option_b_steps(gibs_amount: int, aff_amount: int) -> list[Step]:
    """
    Option B — GIBS / AFFECTION on PulseX V1.

    Intra-ecosystem pair. Value cycles within Dysnomia.
    Pro: arb buys spend AFFECTION → feeds back into ecosystem
    Pro: potential two-leg arb via TGSv8.atomicArb()
    Con: lower liquidity depth initially (Joey has ~88 AFF)
    Con: does NOT unlock DSS directly (need GIBS→WPLS path for sell leg)
    """
    return [
        Step(type=StepType.APPROVE, token=GIBS_LAU, to=PULSEX_V1_ROUTER,
             amount=gibs_amount, note="Approve GIBS for V1 router"),
        Step(type=StepType.APPROVE, token=AFFECTION, to=PULSEX_V1_ROUTER,
             amount=aff_amount, note="Approve AFFECTION for V1 router"),
        Step(type=StepType.ADD_LIQUIDITY, tokenA=GIBS_LAU, tokenB=AFFECTION,
             amountA=gibs_amount, amountB=aff_amount, dex=DEX.V1,
             to=JOEY_WALLET, note="Add GIBS/AFFECTION LP on V1"),
    ]


def option_c_steps(gibs_amount: int, partner_token: str, partner_amount: int,
                    partner_label: str) -> list[Step]:
    """
    Option C — GIBS / Atropa token (ATROPA, TBILL, or HAR).

    Broadest play — connects GIBS into the maria token web.
    Pro: GIBS becomes a node in the Atropa tree
    Con: may have very different liquidity depth per partner
    """
    return [
        Step(type=StepType.APPROVE, token=GIBS_LAU, to=PULSEX_V1_ROUTER,
             amount=gibs_amount, note="Approve GIBS for V1 router"),
        Step(type=StepType.APPROVE, token=partner_token, to=PULSEX_V1_ROUTER,
             amount=partner_amount, note=f"Approve {partner_label} for V1 router"),
        Step(type=StepType.ADD_LIQUIDITY, tokenA=GIBS_LAU, tokenB=partner_token,
             amountA=gibs_amount, amountB=partner_amount, dex=DEX.V1,
             to=JOEY_WALLET, note=f"Add GIBS/{partner_label} LP on V1"),
    ]


# ── Dry-run simulation ──────────────────────────────────────────────────────

def simulate_option(option: str, state: dict):
    """Simulate the selected option by printing the step array."""
    gibs_bal = state["gibs_joey_balance"]
    aff_bal = state["aff_joey_balance"]
    pls_bal = state["pls_balance"]

    # Use 10% of GIBS balance for initial LP
    gibs_for_lp = gibs_bal // 10

    print(f"\n{'=' * 60}")
    print(f"  SIMULATING OPTION {option}")
    print(f"{'=' * 60}")

    if option == "A":
        # GIBS/WPLS — use strategic pricing: 50 PLS/GIBS
        # (above DSS break-even of 21.56, near AFFECTION parity of ~52.27 PLS)
        gibs_implied_pls = 50.0  # Strategic price — NOT break-even
        wpls_amount = int(gibs_for_lp * gibs_implied_pls)
        if wpls_amount > pls_bal // 5:  # Don't use more than 20% of PLS
            wpls_amount = pls_bal // 5
            gibs_for_lp = int(wpls_amount / gibs_implied_pls)

        steps = option_a_steps(gibs_for_lp, wpls_amount)
        print(f"  GIBS in LP:     {gibs_for_lp / 1e18:.4f}")
        print(f"  WPLS in LP:     {wpls_amount / 1e18:.4f}")
        print(f"  Implied price:  {gibs_implied_pls:.1f} PLS/GIBS")
        print(f"  DSS revenue/call: {18 * gibs_implied_pls:.0f} PLS (18 GIBS * {gibs_implied_pls} PLS)")
        print(f"  DSS gas/call:     ~388 PLS")
        print(f"  DSS net/call:     +{18 * gibs_implied_pls - 388:.0f} PLS")
        print(f"  Engine 2 DSS:   UNLOCKED after pair creation")

    elif option == "B":
        # GIBS/AFFECTION — compute ratio from prices
        aff_pls = state.get("affection_price_pls", 0)
        gibs_implied_pls = 21.5
        if aff_pls > 0:
            gibs_per_aff = gibs_implied_pls / (aff_pls / 1e18)
        else:
            gibs_per_aff = 1.0  # fallback

        # Use max 50% of AFFECTION (keep rest for arb)
        aff_for_lp = min(aff_bal // 2, int(gibs_for_lp / gibs_per_aff * 1e18))
        gibs_for_lp = int(aff_for_lp / 1e18 * gibs_per_aff * 1e18)

        steps = option_b_steps(gibs_for_lp, aff_for_lp)
        print(f"  GIBS in LP:        {gibs_for_lp / 1e18:.4f}")
        print(f"  AFFECTION in LP:   {aff_for_lp / 1e18:.4f}")
        print(f"  GIBS/AFF ratio:    {gibs_per_aff:.4f}")
        print(f"  AFF lock warning:  {aff_for_lp / 1e18:.1f} of {aff_bal / 1e18:.1f} AFF locked")
        print(f"  Engine 2 DSS:      NOT unlocked (need GIBS→WPLS path)")

    elif option == "C":
        # GIBS / best Atropa token
        best_token = None
        best_label = None
        best_price = 0
        for label, token in [("ATROPA", ATROPA), ("TBILL", TBILL), ("HAR", HAR)]:
            price = state.get(f"{label.lower()}_price_pls", 0)
            if price > best_price:
                best_price = price
                best_token = token
                best_label = label

        if not best_token:
            print("  ERROR: No Atropa token has a PLS price. Cannot simulate.")
            return

        gibs_implied_pls = 21.5
        partner_pls = best_price / 1e18
        gibs_per_partner = gibs_implied_pls / partner_pls if partner_pls > 0 else 1.0
        partner_amount = int(gibs_for_lp / gibs_per_partner)

        steps = option_c_steps(gibs_for_lp, best_token, partner_amount, best_label)
        print(f"  Partner:           {best_label} ({best_token[:10]}...)")
        print(f"  GIBS in LP:        {gibs_for_lp / 1e18:.4f}")
        print(f"  {best_label} in LP:      {partner_amount / 1e18:.4f}")
        print(f"  1 {best_label} = {partner_pls:.6f} PLS")

    else:
        print(f"  Unknown option: {option}")
        return

    print(f"\n  STEP ARRAY ({len(steps)} steps):")
    for i, step in enumerate(steps):
        print(f"    [{i}] {step.type.name}: {step.note}")
        if step.amount:
            print(f"        amount={step.amount / 1e18:.4f}")
        if step.amountA:
            print(f"        amountA={step.amountA / 1e18:.4f}  amountB={step.amountB / 1e18:.4f}")

    print(f"\n  NOTE: This is a DRY RUN. No transactions sent.")
    print(f"{'=' * 60}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GIBS Liquidity Pair Creator")
    parser.add_argument("--query", action="store_true", help="Query on-chain state only")
    parser.add_argument("--option", choices=["A", "B", "C"], help="Pair option to simulate")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Simulate only (default, always on)")
    args = parser.parse_args()

    print("Querying on-chain state...")
    state = query_state()
    print_state(state)

    if args.query:
        return

    if args.option:
        simulate_option(args.option, state)

    # Write strategy recommendation
    write_strategy(state)


def write_strategy(state: dict):
    """Write the strategy analysis to data/gibs_liquidity_strategy.md."""
    out_path = os.path.join(os.path.dirname(__file__), "Joystick", "data", "gibs_liquidity_strategy.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    gibs_bal = state["gibs_joey_balance"] / 1e18
    aff_bal = state["aff_joey_balance"] / 1e18
    pls_bal = state["pls_balance"] / 1e18
    aff_pls = state.get("affection_price_pls", 0) / 1e18

    # Determine which pairs exist
    any_gibs_pair = any(v is not None for v in state["pairs"].values())

    lines = [
        "# GIBS Liquidity Strategy",
        "",
        f"Generated: 2026-03-05 by gibs_pair_creator.py",
        "",
        "## On-Chain State at Query Time",
        "",
        f"- GIBS totalSupply: {state['gibs_total_supply'] / 1e18:,.4f}",
        f"- GIBS Joey holds: {gibs_bal:,.4f}",
        f"- AFFECTION Joey: {aff_bal:,.4f}",
        f"- PLS balance: {pls_bal:,.1f}",
        f"- 1 AFFECTION = {aff_pls:.6f} PLS" if aff_pls else "- AFFECTION/PLS price: unavailable",
        "",
        "## Existing GIBS Pairs",
        "",
    ]
    for name, addr in state["pairs"].items():
        lines.append(f"- {name}: {'`' + addr + '`' if addr else 'NONE'}")

    lines += [
        "",
        "## Option A — GIBS / WPLS (PulseX V1)",
        "",
        "The original plan. Clean, simple, enables Engine 2 (DSS) immediately.",
        "",
        "- Pro: Unlocks chatAndClaim profit loop (18 GIBS per call at multiplier 17)",
        "- Pro: DSS cycle becomes a single executeRoute call",
        "- Con: GIBS priced in PLS — if PLS pumps, GIBS gets arbed out",
        f"- Implied initial ratio: ~21.5 PLS/GIBS (DSS break-even)",
        "",
        "## Option B — GIBS / AFFECTION",
        "",
        "Intra-ecosystem pair. Prices GIBS in game tokens.",
        "",
        "- Pro: Value cycling within Dysnomia economy",
        "- Pro: TGSv8.atomicArb() can exploit two-leg spread",
        f"- Con: Joey only has {aff_bal:.1f} AFFECTION — locking in LP means less arb capital",
        "- Con: Does NOT unlock Engine 2 DSS directly",
    ]
    if aff_pls > 0:
        gibs_per_aff = 21.5 / aff_pls
        lines.append(f"- Computed ratio: {gibs_per_aff:.4f} GIBS per AFFECTION")

    lines += [
        "",
        "## Option C — GIBS / Atropa Tokens",
        "",
        "Broadest play — connects GIBS into the maria token web.",
        "",
    ]
    for label in ["atropa", "tbill", "har"]:
        price = state.get(f"{label}_price_pls", 0)
        if price:
            lines.append(f"- {label.upper()}: 1 token = {price / 1e18:.6f} PLS")
        else:
            lines.append(f"- {label.upper()}: no PLS pair found")
    lines += [
        "- Pro: GIBS becomes a node in the Atropa tree",
        "- Con: Varying liquidity depth — higher pool impact risk",
        "",
        "## RECOMMENDATION",
        "",
        f"Given:",
        f"- Joey PLS balance: ~{pls_bal:,.0f} ({'BELOW' if pls_bal < 100000 else 'ABOVE'} 100K buffer target)",
        f"- GIBS balance: ~{gibs_bal:,.0f}",
        f"- AFFECTION balance: ~{aff_bal:,.0f} (primary arb fuel for Engine 1)",
        f"- Engine 2 DSS blocked: {'YES' if not any_gibs_pair else 'NO'}",
        "",
    ]

    # Decision logic
    if pls_bal < 100000:
        lines += [
            "Recommended pair: **Option A (GIBS/WPLS)** — but **WAIT**",
            f"Reason: PLS balance ({pls_bal:,.0f}) is below the 100K gas buffer floor.",
            "  Creating LP now would further reduce PLS reserves below safe operating level.",
            "  Wait until PLS > 100K, then create GIBS/WPLS to unlock DSS immediately.",
            "Timing: WAIT until 100K PLS buffer restored",
            f"AFFECTION lock risk: LOW (Option A does not lock AFFECTION)",
        ]
    else:
        lines += [
            "Recommended pair: **Option A (GIBS/WPLS)**",
            "Reason: Unlocks Engine 2 DSS (highest immediate ROI engine when GIBS price > 21.5 PLS).",
            "  Option B locks AFFECTION (primary arb fuel). Option C adds complexity without DSS unlock.",
            "Timing: NOW (PLS buffer is adequate)",
            f"AFFECTION lock risk: LOW (Option A does not lock AFFECTION)",
        ]

    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\nStrategy written to: {out_path}")


if __name__ == "__main__":
    main()
