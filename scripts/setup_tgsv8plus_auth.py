"""
setup_tgsv8plus_auth.py — One-time: authorize Minter wallet on TGSv8+.

Allows Minter to call onlyAuth functions on TGSv8+ in the future
(e.g., if we later split minting to Minter and harvesting to Joey).

For now, Joey remains the sole caller of harvestCycle to preserve atomicity.
Minter auth is pre-emptive — enables future multi-wallet pipeline.

Usage:
  export DYSNOMIA_PRIVATE_KEY=0x...
  python scripts/setup_tgsv8plus_auth.py
  python scripts/setup_tgsv8plus_auth.py --dry-run
"""
import os
import sys
import argparse

# Ensure repo root is on path
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from web3 import Web3

MINTER_WALLET = "0x924C0E0900eCA99D3bfA96D2E02B65f2c5F3e11a"
TGSV8PLUS_ADDRESS = "0xA5D7771f16204d26770657eac186A6167e69e736"


def main():
    parser = argparse.ArgumentParser(description="Authorize Minter wallet on TGSv8+")
    parser.add_argument("--dry-run", action="store_true", help="Simulate only")
    args = parser.parse_args()

    # Set env var for TGSv8+
    os.environ.setdefault("TGSV8PLUS_ADDRESS", TGSV8PLUS_ADDRESS)

    from scripts.Joystick.core.chain import tgsv8plus_contract, safe, w3_submit
    from scripts.Joystick.core.executor import send_tx

    plus = tgsv8plus_contract(w3=w3_submit)
    if not plus:
        print("ERROR: TGSv8+ contract not configured")
        sys.exit(1)

    # Check current auth
    minter_cs = Web3.to_checksum_address(MINTER_WALLET)
    already_authed = safe(plus, "authorized", minter_cs)
    if already_authed:
        print(f"Minter {MINTER_WALLET} is ALREADY authorized on TGSv8+")
        return

    print(f"Authorizing Minter {MINTER_WALLET} on TGSv8+ ({TGSV8PLUS_ADDRESS})...")

    r = send_tx(
        plus.functions.setAuth(minter_cs, True),
        "TGSv8+.setAuth(Minter, true)",
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print("[dry-run] setAuth TX simulated OK")
        return

    if r:
        print(f"TX confirmed: 0x{r['transactionHash'].hex()}")
        print(f"Block: {r['blockNumber']}, Gas: {r['gasUsed']}")

    # Verify
    plus_read = tgsv8plus_contract()
    is_authed = safe(plus_read, "authorized", minter_cs)
    assert is_authed, "VERIFICATION FAILED: Minter is NOT authorized after TX"
    print(f"VERIFIED: Minter {MINTER_WALLET} is now authorized on TGSv8+")


if __name__ == "__main__":
    main()
