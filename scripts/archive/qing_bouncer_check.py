#!/usr/bin/env python3
"""
QING Bouncer Check — Enteh's Venue
Checks all conditions needed for Joey to Join() enteh's QING.

Join() requires:
  1. VerifyUserTokenPermissions(UserToken) — WITHOUT balance == 0, SHIO ownership
  2. CoverCharge payment (if > 0) in Asset token
  3. That's it — bouncer() is NOT called by Join()
"""

from web3 import Web3
import json
import traceback

RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(RPC))

# Addresses
ENTEH_QING   = w3.to_checksum_address("0xA43F71ac277022A547c56706fbBc5d93f88C3467")
JOEY_WALLET  = w3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_LAU     = w3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
CROWS        = w3.to_checksum_address("0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1")
WITHOUT      = w3.to_checksum_address("0x173216Ed67eBF3E6767D86e8b3Ff32e0d64437bF")
CHO          = w3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
AFFECTION    = w3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
FORNAX       = w3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
VOID_ADDR    = w3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")
MAP_ADDR     = w3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")

# Minimal ABIs
ERC20_ABI = json.loads('[{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"stateMutability":"view","type":"function"},{"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"stateMutability":"view","type":"function"},{"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},{"inputs":[{"name":"_a","type":"address"}],"name":"GetMarketRate","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]')

QING_ABI = json.loads('''[
    {"inputs":[],"name":"Asset","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"CoverCharge","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"BouncerDivisor","outputs":[{"name":"","type":"uint16"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"NoCROWS","outputs":[{"name":"","type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"UserToken","type":"address"}],"name":"Admitted","outputs":[{"name":"","type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Waat","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Entropy","outputs":[{"name":"","type":"uint64"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"GWAT","outputs":[{"name":"","type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"_a","type":"address"}],"name":"GetMarketRate","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"UserToken","type":"address"}],"name":"Join","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"cBouncer","type":"address"}],"name":"bouncer","outputs":[{"name":"","type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Cho","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Map","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"cOwner","type":"address"}],"name":"owner","outputs":[{"name":"","type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"name":"allowance","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
]''')

LAU_ABI = json.loads('''[
    {"inputs":[{"name":"","type":"uint256"}],"name":"Saat","outputs":[{"name":"","type":"uint64"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"On","outputs":[{"name":"Phi","type":"address"},{"name":"Mu","type":"address"},{"name":"Xi","type":"uint64"},{"name":"Pi","type":"uint64"},{"name":"Shio","type":"address"},{"name":"Ring","type":"uint64"},{"name":"Omicron","type":"uint64"},{"name":"Omega","type":"uint64"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"name":"","type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Username","outputs":[{"name":"","type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"cOwner","type":"address"}],"name":"owner","outputs":[{"name":"","type":"bool"}],"stateMutability":"view","type":"function"}
]''')

CHO_ABI = json.loads('''[
    {"inputs":[{"name":"UserToken","type":"address"}],"name":"VerifyUserTokenPermissions","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"wallet","type":"address"}],"name":"GetUserTokenAddress","outputs":[{"name":"UserToken","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Void","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"}
]''')

SHIO_ABI = json.loads('''[
    {"inputs":[{"name":"cOwner","type":"address"}],"name":"owner","outputs":[{"name":"","type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Rod","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Cone","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Rho","outputs":[{"name":"","type":"address"}],"stateMutability":"view","type":"function"}
]''')

MAP_ABI = json.loads('''[
    {"inputs":[{"name":"_contract","type":"address"}],"name":"hasOwner","outputs":[{"name":"does","type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"Asset","type":"address"}],"name":"Forbidden","outputs":[{"name":"","type":"bool"}],"stateMutability":"view","type":"function"}
]''')

def fmt(val, decimals=18):
    """Format a wei value to human-readable."""
    return f"{val / 10**decimals:,.4f}"

def sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────
print("QING BOUNCER CHECK — Enteh's Venue")
print(f"RPC: {RPC}")
print(f"Connected: {w3.is_connected()}")
print(f"Block: {w3.eth.block_number}")

qing = w3.eth.contract(address=ENTEH_QING, abi=QING_ABI)
crows_token = w3.eth.contract(address=CROWS, abi=ERC20_ABI)
without_token = w3.eth.contract(address=WITHOUT, abi=ERC20_ABI)
affection_token = w3.eth.contract(address=AFFECTION, abi=ERC20_ABI)
cho_contract = w3.eth.contract(address=CHO, abi=CHO_ABI)
gibs_lau = w3.eth.contract(address=GIBS_LAU, abi=LAU_ABI)
map_contract = w3.eth.contract(address=MAP_ADDR, abi=MAP_ABI)

# ─────────────────────────────────────────────────────────────
sep("1. ENTEH QING STATE")
# ─────────────────────────────────────────────────────────────
try:
    qing_name = qing.functions.name().call()
    qing_symbol = qing.functions.symbol().call()
    print(f"Name: {qing_name}")
    print(f"Symbol: {qing_symbol}")
except Exception as e:
    print(f"Name/Symbol error: {e}")

asset_addr = qing.functions.Asset().call()
cover_charge = qing.functions.CoverCharge().call()
bouncer_divisor = qing.functions.BouncerDivisor().call()
no_crows = qing.functions.NoCROWS().call()
qing_total_supply = qing.functions.totalSupply().call()
qing_waat = qing.functions.Waat().call()
qing_entropy = qing.functions.Entropy().call()
qing_gwat = qing.functions.GWAT().call()
qing_cho = qing.functions.Cho().call()
qing_map = qing.functions.Map().call()

print(f"Asset: {asset_addr}")
print(f"CoverCharge: {cover_charge} wei = {fmt(cover_charge)} tokens")
print(f"BouncerDivisor: {bouncer_divisor}")
print(f"NoCROWS: {no_crows}")
print(f"totalSupply: {qing_total_supply} wei = {fmt(qing_total_supply)} tokens")
print(f"Waat: {qing_waat}")
print(f"Entropy: {qing_entropy}")
print(f"GWAT: {qing_gwat}")
print(f"Cho: {qing_cho}")
print(f"Map: {qing_map}")

# Self-balance
qing_self_bal = qing.functions.balanceOf(ENTEH_QING).call()
print(f"\nSelf-balance (QING holds of itself): {qing_self_bal} wei = {fmt(qing_self_bal)} tokens")

# Market rates
qing_rate_affection = qing.functions.GetMarketRate(AFFECTION).call()
qing_rate_fornax = qing.functions.GetMarketRate(FORNAX).call()
print(f"\nGetMarketRate(AFFECTION): {qing_rate_affection} = {fmt(qing_rate_affection)}")
print(f"GetMarketRate(FORNAX): {qing_rate_fornax} = {fmt(qing_rate_fornax)}")

# ─────────────────────────────────────────────────────────────
sep("2. ASSET TOKEN INFO")
# ─────────────────────────────────────────────────────────────
asset_token = w3.eth.contract(address=asset_addr, abi=ERC20_ABI)
try:
    asset_name = asset_token.functions.name().call()
    asset_symbol = asset_token.functions.symbol().call()
    print(f"Asset Name: {asset_name}")
    print(f"Asset Symbol: {asset_symbol}")
except Exception as e:
    print(f"Asset name/symbol error: {e}")

asset_total_supply = asset_token.functions.totalSupply().call()
asset_joey_bal = asset_token.functions.balanceOf(JOEY_WALLET).call()
asset_gibs_bal = asset_token.functions.balanceOf(GIBS_LAU).call()
print(f"Asset totalSupply: {asset_total_supply} wei = {fmt(asset_total_supply)} tokens")
print(f"Asset balanceOf(Joey EOA): {asset_joey_bal} wei = {fmt(asset_joey_bal)} tokens")
print(f"Asset balanceOf(GIBS_LAU): {asset_gibs_bal} wei = {fmt(asset_gibs_bal)} tokens")

# Check allowance of Joey -> QING for asset
asset_allowance = asset_token.functions.allowance(JOEY_WALLET, ENTEH_QING).call()
print(f"Asset allowance(Joey -> QING): {asset_allowance} wei = {fmt(asset_allowance)} tokens")

# Bouncer threshold
if bouncer_divisor > 0:
    bouncer_threshold = asset_total_supply // bouncer_divisor
    print(f"\nBouncer threshold (Asset.totalSupply / BouncerDivisor): {bouncer_threshold} wei = {fmt(bouncer_threshold)} tokens")
    print(f"  Joey EOA has enough for bouncer? {asset_joey_bal >= bouncer_threshold}")
else:
    print("BouncerDivisor is 0 — division by zero, bouncer by asset disabled")

# ─────────────────────────────────────────────────────────────
sep("3. WITHOUT TOKEN (Ban Check)")
# ─────────────────────────────────────────────────────────────
without_joey = without_token.functions.balanceOf(JOEY_WALLET).call()
print(f"WITHOUT.balanceOf(Joey): {without_joey} wei = {fmt(without_joey)}")
print(f"PASS (must be 0): {'YES' if without_joey == 0 else 'NO -- BANNED'}")

# ─────────────────────────────────────────────────────────────
sep("4. CROWS TOKEN")
# ─────────────────────────────────────────────────────────────
crows_joey = crows_token.functions.balanceOf(JOEY_WALLET).call()
crows_gibs = crows_token.functions.balanceOf(GIBS_LAU).call()
print(f"CROWS.balanceOf(Joey EOA): {crows_joey} wei = {fmt(crows_joey)} tokens")
print(f"CROWS.balanceOf(GIBS_LAU): {crows_gibs} wei = {fmt(crows_gibs)} tokens")
crows_threshold = 25 * 10**18
print(f"Need >= 25 CROWS for bouncer: Joey EOA {'YES' if crows_joey >= crows_threshold else 'NO'}, GIBS_LAU {'YES' if crows_gibs >= crows_threshold else 'NO'}")
print(f"(Note: CROWS check is for bouncer/admin, NOT required for Join())")

# ─────────────────────────────────────────────────────────────
sep("5. GIBS LAU STATE")
# ─────────────────────────────────────────────────────────────
saat0 = gibs_lau.functions.Saat(0).call()
saat1 = gibs_lau.functions.Saat(1).call()
saat2 = gibs_lau.functions.Saat(2).call()
print(f"Saat[0] (session): {saat0}")
print(f"Saat[1] (soul): {saat1}")
print(f"Saat[2] (aura): {saat2}")

try:
    username = gibs_lau.functions.Username().call()
    print(f"Username: {username}")
except:
    print("Username: (call failed)")

# Check GIBS LAU ownership
joey_owns_gibs = gibs_lau.functions.owner(JOEY_WALLET).call()
print(f"GIBS_LAU.owner(Joey): {joey_owns_gibs}")

# Get SHIO from On struct
try:
    on = gibs_lau.functions.On().call()
    shio_addr = on[4]  # Shio is the 5th field
    print(f"\nGIBS_LAU.On.Phi: {on[0]}")
    print(f"GIBS_LAU.On.Mu (SHA): {on[1]}")
    print(f"GIBS_LAU.On.Shio: {shio_addr}")

    # Check SHIO ownership of GIBS_LAU
    shio = w3.eth.contract(address=shio_addr, abi=SHIO_ABI)
    shio_owns_gibs = shio.functions.owner(GIBS_LAU).call()
    print(f"SHIO.owner(GIBS_LAU): {shio_owns_gibs}")

    rod_addr = shio.functions.Rod().call()
    print(f"SHIO.Rod(): {rod_addr}")
    rod = w3.eth.contract(address=rod_addr, abi=SHIO_ABI)
    rod_owns_gibs = rod.functions.owner(GIBS_LAU).call()
    print(f"Rod.owner(GIBS_LAU): {rod_owns_gibs}")

    print(f"\nVerifyUserTokenPermissions SHIO check: {'PASS' if shio_owns_gibs and rod_owns_gibs else 'FAIL'}")
except Exception as e:
    print(f"SHIO check error: {e}")
    traceback.print_exc()

# ─────────────────────────────────────────────────────────────
sep("6. ADMITTED CHECK")
# ─────────────────────────────────────────────────────────────
admitted = qing.functions.Admitted(GIBS_LAU).call()
print(f"QING.Admitted(GIBS_LAU): {admitted}")
if cover_charge == 0:
    print("CoverCharge is 0 — Admitted() always returns true (line 138: if CoverCharge != 0)")
else:
    print(f"CoverCharge is {fmt(cover_charge)} — Admitted checks guest list timestamp")

# ─────────────────────────────────────────────────────────────
sep("7. CHO DELEGATE CHECK")
# ─────────────────────────────────────────────────────────────
try:
    cho_user_token = cho_contract.functions.GetUserTokenAddress(JOEY_WALLET).call()
    print(f"CHO.GetUserTokenAddress(Joey): {cho_user_token}")
    if cho_user_token == "0x0000000000000000000000000000000000000000":
        print("Joey NOT registered in CHO — Join() will auto-call Cho.Enter(GIBS_LAU)")
    else:
        print(f"Joey registered in CHO with token: {cho_user_token}")
        if cho_user_token.lower() == GIBS_LAU.lower():
            print("  Matches GIBS_LAU -- correct")
        else:
            print(f"  WARNING: Does NOT match GIBS_LAU ({GIBS_LAU})")
except Exception as e:
    print(f"CHO check error: {e}")

# ─────────────────────────────────────────────────────────────
sep("8. BOUNCER STATUS (for reference — NOT needed for Join)")
# ─────────────────────────────────────────────────────────────
try:
    bouncer_joey = qing.functions.bouncer(JOEY_WALLET).call()
    print(f"bouncer(Joey EOA): {bouncer_joey}")
except Exception as e:
    print(f"bouncer(Joey EOA) error: {e}")

try:
    bouncer_gibs = qing.functions.bouncer(GIBS_LAU).call()
    print(f"bouncer(GIBS_LAU): {bouncer_gibs}")
except Exception as e:
    print(f"bouncer(GIBS_LAU) error: {e}")

# Check MAP.Forbidden
try:
    forbidden = map_contract.functions.Forbidden(asset_addr).call()
    print(f"MAP.Forbidden(Asset): {forbidden}")
except Exception as e:
    print(f"MAP.Forbidden error: {e}")

# ─────────────────────────────────────────────────────────────
sep("9. QING OWNERSHIP")
# ─────────────────────────────────────────────────────────────
try:
    qing_owner_joey = qing.functions.owner(JOEY_WALLET).call()
    qing_owner_gibs = qing.functions.owner(GIBS_LAU).call()
    qing_owner_cho = qing.functions.owner(CHO).call()
    print(f"QING.owner(Joey EOA): {qing_owner_joey}")
    print(f"QING.owner(GIBS_LAU): {qing_owner_gibs}")
    print(f"QING.owner(CHO): {qing_owner_cho}")
except Exception as e:
    print(f"QING ownership error: {e}")

# ─────────────────────────────────────────────────────────────
sep("10. DRY-RUN: QING.Join(GIBS_LAU)")
# ─────────────────────────────────────────────────────────────
print("Attempting eth_call simulation from Joey's wallet...")
print(f"  Function: Join({GIBS_LAU})")
print(f"  From: {JOEY_WALLET}")
print(f"  To: {ENTEH_QING}")

try:
    # Build the call
    tx = qing.functions.Join(GIBS_LAU).build_transaction({
        'from': JOEY_WALLET,
        'gas': 3000000,
        'gasPrice': w3.to_wei(1, 'gwei'),
        'nonce': 0,  # doesn't matter for call
        'chainId': 369,
    })

    # Dry-run via eth_call
    result = w3.eth.call({
        'from': JOEY_WALLET,
        'to': ENTEH_QING,
        'data': tx['data'],
        'gas': 3000000,
    })
    print(f"\n  DRY-RUN RESULT: SUCCESS")
    print(f"  Return data: {result.hex() if result else '(empty — void function)'}")

except Exception as e:
    error_str = str(e)
    print(f"\n  DRY-RUN RESULT: REVERTED")
    print(f"  Error: {error_str}")

    # Try to decode common error selectors
    if "0x" in error_str:
        # Extract revert data if present
        if "InvalidUserToken" in error_str:
            print("  => VerifyUserTokenPermissions failed: SHIO ownership check failed")
        elif "CoverChargeUnauthorized" in error_str:
            print("  => Need to approve Asset token for CoverCharge payment")
        elif "execution reverted" in error_str.lower():
            print("  => Generic revert — likely the assert() in VerifyUserTokenPermissions (WITHOUT balance != 0)")
            print("     OR the SHIO/Rod ownership check failed")

# ─────────────────────────────────────────────────────────────
sep("11. SUMMARY — JOIN REQUIREMENTS")
# ─────────────────────────────────────────────────────────────
print("""
Join() call chain:
  1. Cho.VerifyUserTokenPermissions(GIBS_LAU)
     a. assert(WITHOUT.balanceOf(tx.origin) == 0)  — ban check
     b. Get Rod by soul index: Void.Nu().Psi().Mu().Tau().Upsilon().GetRodByIdx(Saat[1])
     c. Check: _on.Shio.owner(GIBS_LAU) == true
     d. Check: _on.Shio.Rod().owner(GIBS_LAU) == true

  2. If CoverCharge > 0 AND not on guest list:
     a. Asset.allowance(Joey, QING) must EXCEED CoverCharge (> not >=)
     b. Asset.transferFrom(Joey, QING, CoverCharge)

  3. Auto-register in CHO if needed
  4. _mintToCap()
""")

# Final verdict
print("--- VERDICT ---")
issues = []

if without_joey != 0:
    issues.append(f"BLOCKED: WITHOUT balance is {fmt(without_joey)} (must be 0)")

if cover_charge > 0:
    if asset_allowance <= cover_charge:
        issues.append(f"NEED: Approve {fmt(cover_charge)} of Asset ({asset_addr}) to QING")
    if asset_joey_bal < cover_charge:
        issues.append(f"NEED: Acquire {fmt(cover_charge)} of Asset token (have {fmt(asset_joey_bal)})")

try:
    if not shio_owns_gibs:
        issues.append("BLOCKED: SHIO does not own GIBS_LAU")
    if not rod_owns_gibs:
        issues.append("BLOCKED: Rod does not own GIBS_LAU")
except:
    issues.append("UNKNOWN: Could not verify SHIO/Rod ownership")

if not joey_owns_gibs:
    issues.append("WARNING: Joey EOA does not own GIBS_LAU (Cho.Enter will fail)")

if len(issues) == 0:
    print("ALL CHECKS PASS — Join() should succeed!")
else:
    print("ISSUES FOUND:")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")
