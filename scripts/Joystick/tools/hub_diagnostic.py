#!/usr/bin/env python3
"""
hub_diagnostic.py — Read-only JoystickHub health check.

Zero gas, zero risk. Checks:
  1. Hub ownership + authorization (Joey)
  2. Config keys (harvest.gibsLau, harvest.affection, etc.)
  3. Module selector registration (all 3 modules)
  4. Token balances in Hub (AFF, GIBS, WPLS, PLS)
  5. Hub paused / reentrancy state
  6. DSS.mintToSelf readiness (DSS owner, GIBS balance)
  7. GIBS/WPLS pair reserves + price
  8. E2 end-to-end readiness summary

Usage:
    python scripts/Joystick/tools/hub_diagnostic.py
"""
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_JOYSTICK_DIR = os.path.dirname(_SCRIPT_DIR)
_SCRIPTS_DIR = os.path.dirname(_JOYSTICK_DIR)
_PROJECT_ROOT = os.path.dirname(_SCRIPTS_DIR)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from web3 import Web3
from Crypto.Hash import keccak as keccak_mod

# ── Addresses ───────────────────────────────────────────────────────────────
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
JOYSTICK_HUB = Web3.to_checksum_address("0x7bd76A0f7e03A3BA76A621ba0988C7db0AdbAB14")
HARVEST_MODULE = Web3.to_checksum_address("0xFAFB227DdC0804A55677A23eE2Ca0E966452D3B2")
AFFECTION_MODULE = Web3.to_checksum_address("0xfb7C1A1Ef0Ce8AB527998a1c2Ca12C6CA400da4B")
PURCHASE_MODULE = Web3.to_checksum_address("0xc59cb7229872E72B7349Ef7DFa170A2444a8264E")
GIBS_LAU = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
AFFECTION = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
WPLS = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
DSS = Web3.to_checksum_address("0x91Df693177eE5C81016d0B7c4c2052A7d229c031")
PULSEX_V2_FACTORY = Web3.to_checksum_address("0x29eA7545DEf87022BAdc76323F373EA1e707C523")
PULSEX_V2_ROUTER = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")

READ_RPC = os.getenv("PULSECHAIN_READ_RPC", "https://rpc-pulsechain.g4mm4.io")
w3 = Web3(Web3.HTTPProvider(READ_RPC, request_kwargs={"timeout": 30}))

ZERO = "0x" + "0" * 40


# ── Helpers ─────────────────────────────────────────────────────────────────

def tag(ok: bool) -> str:
    return "[PASS]" if ok else "[FAIL]"


def sol_keccak256(text: str) -> bytes:
    """Solidity-style keccak256 of a UTF-8 string."""
    h = keccak_mod.new(data=text.encode(), digest_bits=256)
    return h.digest()


def fn_selector(sig: str) -> bytes:
    """4-byte function selector: keccak256(sig)[:4]."""
    return sol_keccak256(sig)[:4]


def eth_call(to: str, data: str) -> str:
    """Raw eth_call, returns hex result or empty on revert."""
    try:
        result = w3.eth.call({"to": to, "data": data})
        return result.hex()
    except Exception:
        return ""


def read_address(raw_hex: str) -> str:
    """Decode a 32-byte word as an address."""
    if not raw_hex or len(raw_hex) < 40:
        return ZERO
    return Web3.to_checksum_address("0x" + raw_hex[-40:])


def read_uint256(raw_hex: str) -> int:
    """Decode a 32-byte word as uint256."""
    if not raw_hex:
        return 0
    return int(raw_hex[-64:], 16)


def read_bool(raw_hex: str) -> bool:
    """Decode a 32-byte word as bool."""
    return read_uint256(raw_hex) != 0


def erc20_balance(token: str, holder: str) -> int:
    """ERC20 balanceOf via eth_call."""
    selector = fn_selector("balanceOf(address)")
    data = "0x" + selector.hex() + holder.lower().replace("0x", "").zfill(64)
    result = eth_call(token, data)
    return read_uint256(result)


# ── Hub view helpers ────────────────────────────────────────────────────────

def hub_owner() -> str:
    sel = fn_selector("owner()")
    return read_address(eth_call(JOYSTICK_HUB, "0x" + sel.hex()))


def hub_is_paused() -> bool:
    sel = fn_selector("isPaused()")
    return read_bool(eth_call(JOYSTICK_HUB, "0x" + sel.hex()))


def hub_is_authorized(addr: str) -> bool:
    sel = fn_selector("isAuthorized(address)")
    data = "0x" + sel.hex() + addr.lower().replace("0x", "").zfill(64)
    return read_bool(eth_call(JOYSTICK_HUB, data))


def hub_module(selector_4bytes: bytes) -> str:
    """Read _modules[selector] → implementation address."""
    sel = fn_selector("module(bytes4)")
    # bytes4 is left-aligned in a 32-byte word
    padded = selector_4bytes.hex().ljust(64, "0")
    data = "0x" + sel.hex() + padded
    return read_address(eth_call(JOYSTICK_HUB, data))


def hub_config(key_str: str) -> int:
    """Read _config[keccak256(key_str)] → uint256."""
    config_key = sol_keccak256(key_str)
    sel = fn_selector("config(bytes32)")
    data = "0x" + sel.hex() + config_key.hex()
    return read_uint256(eth_call(JOYSTICK_HUB, data))


# ── Selectors for all module functions ──────────────────────────────────────

HARVEST_SELECTORS = {
    "primeGibs(uint256)": HARVEST_MODULE,
    "mintLPAndSell(uint256,uint256,uint256,uint8,uint256,address[],uint8)": HARVEST_MODULE,
    "harvestPreloaded(uint256,uint256,uint8,uint256,address[],uint8)": HARVEST_MODULE,
    "batchReseed(address[],uint256[])": HARVEST_MODULE,
    "harvestConfig()": HARVEST_MODULE,
}

AFFECTION_SELECTORS = {
    "buyAffection(address,bytes4,uint256,uint256,uint8)": AFFECTION_MODULE,
    "quoteBuyAffection(address,uint256,uint256,uint8)": AFFECTION_MODULE,
}

PURCHASE_SELECTORS = {
    "purchaseAndSell(address,uint256,address[],uint8,uint256)": PURCHASE_MODULE,
    "batchPurchaseAndSell(address[],uint256[],address[][],uint8[],uint256[])": PURCHASE_MODULE,
    "quotePurchase(address,uint256,address[],uint8)": PURCHASE_MODULE,
}

ALL_SELECTORS = {}
ALL_SELECTORS.update(HARVEST_SELECTORS)
ALL_SELECTORS.update(AFFECTION_SELECTORS)
ALL_SELECTORS.update(PURCHASE_SELECTORS)

# ── Config keys ─────────────────────────────────────────────────────────────

CONFIG_KEYS = {
    "harvest.gibsLau":       ("address", GIBS_LAU),
    "harvest.affection":     ("address", AFFECTION),
    "harvest.primeCount":    ("uint", None),
    "affection.token":       ("address", AFFECTION),
    "affection.maxLoops":    ("uint", None),
    "purchase.affection":    ("address", AFFECTION),
    "purchase.minSpreadBps": ("uint", None),
}


# ── Main diagnostic ────────────────────────────────────────────────────────

def main():
    block = w3.eth.block_number
    print(f"\n{'='*70}")
    print(f"  JOYSTICK HUB DIAGNOSTIC — Block {block:,}")
    print(f"  Hub: {JOYSTICK_HUB}")
    print(f"{'='*70}\n")

    all_pass = True

    # ── 1. Ownership & Auth ─────────────────────────────────────────────
    print("── 1. OWNERSHIP & AUTH ──────────────────────────────────────")
    owner = hub_owner()
    joey_is_owner = owner.lower() == JOEY_WALLET.lower()
    print(f"  Hub owner:        {owner}")
    print(f"  Joey is owner:    {tag(joey_is_owner)} {'✓' if joey_is_owner else '✗ WRONG OWNER'}")

    joey_authed = hub_is_authorized(JOEY_WALLET)
    print(f"  Joey authorized:  {tag(joey_authed)} {'✓' if joey_authed else '✗ NOT AUTHORIZED'}")

    paused = hub_is_paused()
    print(f"  Hub paused:       {tag(not paused)} {'✗ PAUSED!' if paused else '✓ Not paused'}")
    all_pass = all_pass and joey_is_owner and joey_authed and not paused

    # Check Minter/Seller wallet auth (env vars, optional)
    minter_wallet = os.getenv("MINTER_WALLET", "")
    seller_wallet = os.getenv("SELLER_WALLET", "")
    if minter_wallet:
        minter_cs = Web3.to_checksum_address(minter_wallet)
        minter_authed = hub_is_authorized(minter_cs)
        print(f"  Minter authorized: {tag(minter_authed)} {minter_cs[:10]}...")
    if seller_wallet:
        seller_cs = Web3.to_checksum_address(seller_wallet)
        seller_authed = hub_is_authorized(seller_cs)
        print(f"  Seller authorized: {tag(seller_authed)} {seller_cs[:10]}...")

    # ── 2. Config Keys ──────────────────────────────────────────────────
    print("\n── 2. CONFIG KEYS ───────────────────────────────────────────")
    config_ok = True
    for key_str, (typ, expected) in CONFIG_KEYS.items():
        val = hub_config(key_str)
        if typ == "address":
            val_display = Web3.to_checksum_address("0x" + hex(val)[2:].zfill(40)) if val else ZERO
            is_ok = (val != 0)
            matches = expected and val_display.lower() == expected.lower()
            status = "✓" if matches else ("≠ expected" if val and expected and not matches else "NOT SET")
            # Critical keys
            if key_str in ("harvest.gibsLau", "harvest.affection", "purchase.affection"):
                config_ok = config_ok and is_ok
            print(f"  {key_str:30s} = {val_display}  {tag(is_ok)} {status}")
        else:
            is_ok = True  # uint keys are optional
            print(f"  {key_str:30s} = {val}  [INFO]")
    all_pass = all_pass and config_ok

    # ── 3. Module Selector Registration ─────────────────────────────────
    print("\n── 3. MODULE SELECTORS ──────────────────────────────────────")
    selectors_ok = True
    for sig, expected_module in ALL_SELECTORS.items():
        sel_bytes = fn_selector(sig)
        impl = hub_module(sel_bytes)
        is_registered = impl.lower() != ZERO.lower()
        correct_module = impl.lower() == expected_module.lower()
        status_str = ""
        if not is_registered:
            status_str = "NOT REGISTERED"
            selectors_ok = False
        elif not correct_module:
            status_str = f"WRONG MODULE: {impl}"
            selectors_ok = False
        else:
            status_str = f"→ {impl[:10]}..."
        # Truncate long signatures for display
        sig_short = sig[:50] + ("..." if len(sig) > 50 else "")
        print(f"  0x{sel_bytes.hex()} {sig_short:55s} {tag(is_registered and correct_module)} {status_str}")
    all_pass = all_pass and selectors_ok

    # ── 4. Hub Token Balances ───────────────────────────────────────────
    print("\n── 4. HUB TOKEN BALANCES ────────────────────────────────────")
    tokens = {
        "AFFECTION": AFFECTION,
        "GIBS_LAU":  GIBS_LAU,
        "WPLS":      WPLS,
    }
    for name, addr in tokens.items():
        bal = erc20_balance(addr, JOYSTICK_HUB)
        print(f"  {name:15s} {bal / 1e18:>15.4f}")

    hub_pls = w3.eth.get_balance(JOYSTICK_HUB)
    print(f"  {'PLS (native)':15s} {hub_pls / 1e18:>15.4f}")

    # ── 5. DSS Readiness (mintToSelf) ───────────────────────────────────
    print("\n── 5. DSS READINESS (mintToSelf) ─────────────────────────────")

    # DSS owner check
    dss_owner_sel = fn_selector("owner()")
    dss_owner = read_address(eth_call(DSS, "0x" + dss_owner_sel.hex()))
    joey_is_dss_owner = dss_owner.lower() == JOEY_WALLET.lower()
    print(f"  DSS owner:        {dss_owner}")
    print(f"  Joey is DSS owner: {tag(joey_is_dss_owner)} {'✓' if joey_is_dss_owner else '✗ CANNOT CALL mintToSelf'}")

    # DSS GIBS balance (what mintToSelf would pull from)
    dss_gibs = erc20_balance(GIBS_LAU, DSS)
    print(f"  DSS GIBS balance: {dss_gibs / 1e18:.4f}")

    # GIBS LAU self-balance (what Generate() primes)
    gibs_self = erc20_balance(GIBS_LAU, GIBS_LAU)
    print(f"  GIBS self-balance: {gibs_self / 1e18:.4f} (for Purchase/mintToSelf)")

    # Joey GIBS balance
    joey_gibs = erc20_balance(GIBS_LAU, JOEY_WALLET)
    print(f"  Joey GIBS balance: {joey_gibs / 1e18:.4f}")

    # ── 6. GIBS/WPLS Pair & Price ───────────────────────────────────────
    print("\n── 6. GIBS/WPLS PAIR & PRICE ─────────────────────────────────")
    factory_sel = fn_selector("getPair(address,address)")
    pair_data = (
        "0x" + factory_sel.hex()
        + GIBS_LAU.lower().replace("0x", "").zfill(64)
        + WPLS.lower().replace("0x", "").zfill(64)
    )
    pair_addr = read_address(eth_call(PULSEX_V2_FACTORY, pair_data))
    pair_exists = pair_addr.lower() != ZERO.lower()
    print(f"  V2 pair:          {pair_addr}  {tag(pair_exists)}")

    if pair_exists:
        # Get reserves
        reserves_sel = fn_selector("getReserves()")
        token0_sel = fn_selector("token0()")
        reserves_raw = eth_call(pair_addr, "0x" + reserves_sel.hex())
        token0 = read_address(eth_call(pair_addr, "0x" + token0_sel.hex()))

        if reserves_raw and len(reserves_raw) >= 128:
            r0 = int(reserves_raw[:64], 16)
            r1 = int(reserves_raw[64:128], 16)

            if token0.lower() == GIBS_LAU.lower():
                gibs_r, wpls_r = r0, r1
            else:
                gibs_r, wpls_r = r1, r0

            gibs_price_pls = wpls_r / gibs_r if gibs_r > 0 else 0
            print(f"  GIBS reserve:     {gibs_r / 1e18:.4f}")
            print(f"  WPLS reserve:     {wpls_r / 1e18:.4f}")
            print(f"  GIBS price:       {gibs_price_pls:.2f} PLS")
            print(f"  Break-even (>21.5): {tag(gibs_price_pls > 21.5)} {'✓' if gibs_price_pls > 21.5 else '✗ BELOW BREAK-EVEN'}")

            # Estimate LP cost for 17 GIBS at 55% LP
            gibs_for_lp = 17 * 0.55
            wpls_needed = gibs_for_lp * (wpls_r / gibs_r) * 1.02  # +2% buffer
            print(f"\n  LP estimate (17 GIBS cycle, 55% LP):")
            print(f"    GIBS for LP:    {gibs_for_lp:.2f}")
            print(f"    WPLS needed:    {wpls_needed:.2f} PLS (as msg.value)")
            sell_gibs = 17 * 0.45
            sell_output = (sell_gibs * 1e18 * 997 * wpls_r) / (gibs_r * 1000 + sell_gibs * 1e18 * 997)
            print(f"    Sell output:    ~{sell_output / 1e18:.2f} PLS ({sell_gibs:.1f} GIBS)")

    # ── 7. Joey Wallet ──────────────────────────────────────────────────
    print("\n── 7. JOEY WALLET ───────────────────────────────────────────")
    joey_pls = w3.eth.get_balance(JOEY_WALLET)
    print(f"  PLS:              {joey_pls / 1e18:,.2f}")
    joey_aff = erc20_balance(AFFECTION, JOEY_WALLET)
    print(f"  AFFECTION:        {joey_aff / 1e18:.4f}")
    print(f"  GIBS:             {joey_gibs / 1e18:.4f}")

    # ── 8. E2 Readiness Summary ─────────────────────────────────────────
    print(f"\n{'='*70}")
    print("  E2 CEREAL READINESS SUMMARY")
    print(f"{'='*70}")

    checks = {
        "Hub owner = Joey":         joey_is_owner,
        "Joey authorized":          joey_authed,
        "Hub not paused":           not paused,
        "harvest.gibsLau set":      hub_config("harvest.gibsLau") != 0,
        "harvest.affection set":    hub_config("harvest.affection") != 0,
        "Selectors registered":     selectors_ok,
        "GIBS/WPLS V2 pair exists": pair_exists,
        "DSS owner = Joey":         joey_is_dss_owner,
    }

    blockers = []
    for desc, ok in checks.items():
        print(f"  {tag(ok)} {desc}")
        if not ok:
            blockers.append(desc)

    print()
    if not blockers:
        print("  ✓ ALL CHECKS PASSED — E2 is ready to execute")
    else:
        print(f"  ✗ {len(blockers)} BLOCKER(S):")
        for b in blockers:
            print(f"    → {b}")

        # Print fix hints
        print("\n── FIX ACTIONS ──────────────────────────────────────────────")
        if "harvest.gibsLau set" in blockers or "harvest.affection set" in blockers:
            gibs_int = int(GIBS_LAU, 16)
            aff_int = int(AFFECTION, 16)
            print(f"""
  Hub config keys need initialization. Send 1 TX:

    hub.batchSetConfig(
      keys = [
        keccak256("harvest.gibsLau"),     # {sol_keccak256("harvest.gibsLau").hex()}
        keccak256("harvest.affection"),   # {sol_keccak256("harvest.affection").hex()}
        keccak256("purchase.affection"),  # {sol_keccak256("purchase.affection").hex()}
        keccak256("affection.token"),     # {sol_keccak256("affection.token").hex()}
      ],
      vals = [
        {gibs_int},  # GIBS_LAU as uint256
        {aff_int},  # AFFECTION as uint256
        {aff_int},  # AFFECTION as uint256
        {aff_int},  # AFFECTION as uint256
      ]
    )""")

        if "Selectors registered" in blockers:
            print("\n  Module selectors need registration. Check individual selector")
            print("  failures above and call hub.batchRegisterModule() for each module.")

    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    main()
