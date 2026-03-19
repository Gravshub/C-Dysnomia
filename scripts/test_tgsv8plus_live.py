"""
test_tgsv8plus_live.py — First live test sequence for TGSv8+ on PulseChain mainnet.

Executes real TXs. Estimated cost: ~500 PLS (5-6 TXs at ~80-100 PLS each).

Steps:
  0. Verify TGSv8+ state (owner, auth, payToken, lauRemaining)
  1. Approve AFF for TGSv8+
  2. Deposit 17 AFF into TGSv8+
  3. Test silentMint(1)
  3b. Fallback: test safeMint(1) if silentMint reverts
  4. Test silentMint(2) — confirms _mintToCap fires inside Purchase
  5. Withdraw test GIBS back to Joey
  6. Deposit 17 more AFF (for harvestCycle test)
  7. Test harvestCycle(17, 4500, 0, 9000, 1, 1)
  8. Auth Minter wallet

Usage:
  export DYSNOMIA_PRIVATE_KEY=0x...
  python scripts/test_tgsv8plus_live.py
  python scripts/test_tgsv8plus_live.py --dry-run
"""
import os
import sys
import argparse
import logging

# Ensure repo root is on path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(name)-16s %(levelname)-8s %(message)s",
)
log = logging.getLogger("tgsv8plus_live_test")

JOEY_WALLET = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
TGSV8PLUS_ADDRESS = "0xA5D7771f16204d26770657eac186A6167e69e736"
AFFECTION_ADDRESS = "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D"
GIBS_LAU_ADDRESS = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"
MINTER_WALLET = "0x924C0E0900eCA99D3bfA96D2E02B65f2c5F3e11a"


def main():
    parser = argparse.ArgumentParser(description="TGSv8+ live test sequence")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only")
    args = parser.parse_args()

    print("=" * 60)
    print("  TGSv8+ LIVE TEST SEQUENCE")
    print()
    print("  This will execute real TXs on PulseChain mainnet.")
    print("  Estimated cost: ~500 PLS (5-6 TXs at ~80-100 PLS each)")
    print()
    if not os.environ.get("DYSNOMIA_PRIVATE_KEY"):
        print("  To proceed: export DYSNOMIA_PRIVATE_KEY=0x...")
        print("  Or: --dry-run for simulation only")
        print("=" * 60)
        if not args.dry_run:
            sys.exit(1)
    print("=" * 60)
    print()

    os.environ.setdefault("TGSV8PLUS_ADDRESS", TGSV8PLUS_ADDRESS)

    from web3 import Web3
    from scripts.Joystick.core.chain import (
        tgsv8plus_contract, erc20, safe, w3_read, w3_submit,
    )
    from scripts.Joystick.core.executor import send_tx, approve_if_needed
    from scripts.Joystick.core.simulator import SimulationFailed

    plus_read = tgsv8plus_contract()
    plus_submit = tgsv8plus_contract(w3=w3_submit)
    if not plus_read or not plus_submit:
        print("ERROR: TGSv8+ contract not configured")
        sys.exit(1)

    results = {
        "silent_mint": "UNTESTED",
        "safe_mint": "UNTESTED",
        "harvest_cycle": "UNTESTED",
        "minter_auth": "UNTESTED",
    }
    total_gas = 0
    use_safe = False

    # ── Step 0: Verify TGSv8+ state ──────────────────────────────────────
    print("Step 0: Verify TGSv8+ state")
    owner = safe(plus_read, "owner")
    print(f"  owner()     = {owner}")
    assert owner and owner.lower() == JOEY_WALLET.lower(), f"Owner mismatch: {owner}"

    authed = safe(plus_read, "authorized", Web3.to_checksum_address(JOEY_WALLET))
    print(f"  authorized(Joey) = {authed}")

    lau = safe(plus_read, "lau")
    print(f"  lau()       = {lau}")
    assert lau and lau.lower() == GIBS_LAU_ADDRESS.lower(), f"LAU mismatch: {lau}"

    pay_token = safe(plus_read, "payToken")
    print(f"  payToken()  = {pay_token}")
    assert pay_token and pay_token.lower() == AFFECTION_ADDRESS.lower(), f"payToken mismatch"

    lau_remaining = safe(plus_read, "lauRemaining")
    print(f"  lauRemaining() = {lau_remaining}")
    if lau_remaining is not None:
        print(f"    = {lau_remaining / 1e18:.1f} LAU mintable")
    print("  Step 0: OK\n")

    # ── Step 1: Approve AFF for TGSv8+ ───────────────────────────────────
    print("Step 1: Approve AFF for TGSv8+")
    max_uint = 2**256 - 1
    aff_submit = w3_submit.eth.contract(
        address=Web3.to_checksum_address(AFFECTION_ADDRESS),
        abi=erc20(AFFECTION_ADDRESS).abi,
    )
    r = approve_if_needed(aff_submit, TGSV8PLUS_ADDRESS, max_uint,
                          "AFF→TGSv8+ (max)", dry_run=args.dry_run)
    if r:
        total_gas += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
        print(f"  TX: 0x{r['transactionHash'].hex()}")
    else:
        print("  Already approved or dry-run")
    print("  Step 1: OK\n")

    # ── Step 2: Deposit 17 AFF into TGSv8+ ───────────────────────────────
    print("Step 2: Deposit 17 AFF into TGSv8+")
    deposit_amount = 17 * 10**18
    r = send_tx(
        plus_submit.functions.deposit(
            Web3.to_checksum_address(AFFECTION_ADDRESS), deposit_amount
        ),
        "Deposit 17 AFF → TGSv8+",
        dry_run=args.dry_run,
    )
    if r:
        total_gas += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
        print(f"  TX: 0x{r['transactionHash'].hex()}")

    # Verify
    if not args.dry_run:
        aff_bal = safe(erc20(AFFECTION_ADDRESS), "balanceOf", TGSV8PLUS_ADDRESS) or 0
        print(f"  AFF in TGSv8+: {aff_bal / 1e18:.1f}")
        assert aff_bal >= deposit_amount, f"AFF deposit verification failed: {aff_bal}"
    print("  Step 2: OK\n")

    # ── Step 3: Test silentMint(1) ────────────────────────────────────────
    print("Step 3: Test silentMint(1)")
    try:
        r = send_tx(
            plus_submit.functions.silentMint(1),
            "silentMint(1)",
            dry_run=args.dry_run,
        )
        if r:
            total_gas += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
            print(f"  TX: 0x{r['transactionHash'].hex()}")
        results["silent_mint"] = "WORKS"
        print("  silentMint(1): OK\n")
    except (SimulationFailed, Exception) as exc:
        print(f"  silentMint(1) FAILED: {exc}")
        results["silent_mint"] = "FAILED"

        # Step 3b: Fallback to safeMint
        print("\nStep 3b: Fallback — test safeMint(1)")
        try:
            r = send_tx(
                plus_submit.functions.safeMint(1),
                "safeMint(1)",
                dry_run=args.dry_run,
            )
            if r:
                total_gas += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
            results["safe_mint"] = "WORKS"
            use_safe = True
            print("  safeMint(1): OK — recommend HARVEST_USE_SAFE=true\n")
        except Exception as exc2:
            results["safe_mint"] = "FAILED"
            print(f"  safeMint(1) ALSO FAILED: {exc2}")
            print("  BOTH mint paths failed — aborting remaining tests")
            _print_summary(results, total_gas, use_safe)
            return

    # Verify GIBS received
    if not args.dry_run:
        gibs_bal = safe(erc20(GIBS_LAU_ADDRESS), "balanceOf", TGSV8PLUS_ADDRESS) or 0
        print(f"  GIBS in TGSv8+: {gibs_bal / 1e18:.4f}")

    # ── Step 4: Test silentMint(2) ────────────────────────────────────────
    print("Step 4: Test silentMint(2) — confirms _mintToCap fires inside Purchase")
    mint_fn = plus_submit.functions.safeMint if use_safe else plus_submit.functions.silentMint
    mint_label = "safeMint(2)" if use_safe else "silentMint(2)"
    try:
        r = send_tx(mint_fn(2), mint_label, dry_run=args.dry_run)
        if r:
            total_gas += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
        print(f"  {mint_label}: OK — Purchase calls _mintToCap internally\n")
    except Exception as exc:
        print(f"  {mint_label} FAILED on iteration 2: {exc}")
        if not use_safe:
            use_safe = True
            print("  Recommendation: set HARVEST_USE_SAFE=true\n")

    # ── Step 5: Withdraw test GIBS back to Joey ──────────────────────────
    print("Step 5: Withdraw test GIBS back to Joey")
    try:
        r = send_tx(
            plus_submit.functions.withdraw(Web3.to_checksum_address(GIBS_LAU_ADDRESS)),
            "Withdraw GIBS → Joey",
            dry_run=args.dry_run,
        )
        if r:
            total_gas += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
        print("  Step 5: OK\n")
    except Exception as exc:
        print(f"  Withdraw FAILED: {exc} — continuing\n")

    # ── Step 6: Deposit 17 more AFF ──────────────────────────────────────
    print("Step 6: Deposit 17 more AFF (for harvestCycle test)")
    try:
        r = send_tx(
            plus_submit.functions.deposit(
                Web3.to_checksum_address(AFFECTION_ADDRESS), deposit_amount
            ),
            "Deposit 17 AFF → TGSv8+ (for harvestCycle)",
            dry_run=args.dry_run,
        )
        if r:
            total_gas += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
        print("  Step 6: OK\n")
    except Exception as exc:
        print(f"  Deposit FAILED: {exc}")
        print("  Cannot proceed to harvestCycle test without AFF")
        _print_summary(results, total_gas, use_safe)
        return

    # ── Step 7: Test harvestCycle ─────────────────────────────────────────
    print("Step 7: Test harvestCycle(17, 4500, 0, 9000, 1, 1)")
    print("  minPlsOut=0 for first test (no slippage guard)")
    try:
        r = send_tx(
            plus_submit.functions.harvestCycle(17, 4500, 0, 9000, 1, 1),
            "harvestCycle(17, 4500, 0, 9000, 1, 1)",
            dry_run=args.dry_run,
        )
        if r:
            total_gas += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)
            print(f"  TX: 0x{r['transactionHash'].hex()}")
            print(f"  Block: {r['blockNumber']}, Gas: {r['gasUsed']}")
            # Parse logs for HarvestCycle event
            for entry in r.get("logs", []):
                topics = entry.get("topics", [])
                if len(topics) >= 1:
                    log.debug("  Log topic[0]: %s", topics[0].hex() if hasattr(topics[0], "hex") else topics[0])
        results["harvest_cycle"] = "WORKS"
        print("  harvestCycle: OK\n")
    except Exception as exc:
        results["harvest_cycle"] = f"FAILED: {exc}"
        print(f"  harvestCycle FAILED: {exc}\n")

    # ── Step 8: Auth Minter wallet ────────────────────────────────────────
    print("Step 8: Auth Minter wallet")
    minter_cs = Web3.to_checksum_address(MINTER_WALLET)
    already = safe(plus_read, "authorized", minter_cs)
    if already:
        print(f"  Minter already authorized")
        results["minter_auth"] = "ALREADY SET"
    else:
        try:
            r = send_tx(
                plus_submit.functions.setAuth(minter_cs, True),
                "TGSv8+.setAuth(Minter, true)",
                dry_run=args.dry_run,
            )
            if r:
                total_gas += r["gasUsed"] * r.get("effectiveGasPrice", w3_submit.eth.gas_price)

            if not args.dry_run:
                verified = safe(plus_read, "authorized", minter_cs)
                assert verified, "Minter auth verification FAILED"
            results["minter_auth"] = "SET"
            print("  Minter auth: OK\n")
        except Exception as exc:
            results["minter_auth"] = f"FAILED: {exc}"
            print(f"  setAuth FAILED: {exc}\n")

    _print_summary(results, total_gas, use_safe)


def _print_summary(results, total_gas, use_safe):
    print()
    print("=" * 60)
    print("  TGSv8+ LIVE TEST SUMMARY")
    print("=" * 60)
    print(f"  silentMint:    {results['silent_mint']}")
    print(f"  safeMint:      {results['safe_mint']}")
    print(f"  harvestCycle:  {results['harvest_cycle']}")
    print(f"  Minter auth:   {results['minter_auth']}")
    print(f"  Total gas:     {total_gas / 1e18:.2f} PLS")
    print(f"  HARVEST_USE_SAFE recommended: {use_safe}")
    print()
    if results["harvest_cycle"] == "WORKS":
        print("  NEXT STEP: Wire into bot.py and run first automated cycle")
        print("    python -m scripts.Joystick.bot --once --dry-run")
    else:
        print("  harvestCycle failed — investigate before wiring into bot")
    print("=" * 60)


if __name__ == "__main__":
    main()
