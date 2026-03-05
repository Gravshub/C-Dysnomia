#!/usr/bin/env python3
"""
Fornax SHIO Token Holder Investigation
Goal: Find ANY way for Joey to acquire Fornax tokens on PulseChain.
Fornax is maxed out (totalSupply == maxSupply), self-balance=0, no DEX pairs.
"""

import json
import sys
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

# --- Config ---
RPC = "https://rpc.pulsechain.com"
FORNAX = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
AFFECTION = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
CHO = Web3.to_checksum_address("0xB6be11F0A788014C1f68C92F8D6CcC1AbF78F2aB")
JOEY_EOA = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_LAU = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
GIBS_QING = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
XIE = Web3.to_checksum_address("0x4Df51741F2926525A21bF63E4769bA70633D2792")
VOID = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")
ZERO = "0x0000000000000000000000000000000000000000"

HOLDERS = [
    ("0x530c8cE74897805A4612EAFf07972D049aCaf95F", 25280, "WHALE (49.6%)"),
    ("0x0474606332105A1dA6FC8EF7De2470551D389Cb9", 303, "Deployer? (0.6%)"),
    ("0x1F45433da3D6388602598438532d269dcc18C74F", 41, "Contract (41)"),
    ("0xA43F71ac277022A547c56706fbBc5d93f88C3467", 11, "Contract (11)"),
    ("0xE4169cF239e2FDc6E6e4a3a6fA0a703058ce400b", 9, "Contract (9)"),
    ("0x1058d2B915463B0796695a0CE91236Cc2D1E3C5c", 1, "Contract (1)"),
    ("0xD32c39fEE49391c7952d1b30b15921b0D3b42E69", 0.01, "Contract (0.01)"),
]

# --- ABIs ---
BASIC_ABI = [
    {"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"symbol","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Type","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"maxSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"type":"address"}],"name":"GetMarketRate","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Asset","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"CoverCharge","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Waat","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Origin","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"type":"address"}],"name":"GetUserTokenAddress","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"owner","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"decimals","outputs":[{"type":"uint8"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Rod","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Cone","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Phi","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"On","outputs":[{"type":"address","name":"Phi"},{"type":"address","name":"Mu"},{"type":"uint64","name":"Xi"},{"type":"uint64","name":"Pi"},{"type":"address","name":"Shio"},{"type":"uint64","name":"Ring"},{"type":"uint64","name":"Omicron"},{"type":"uint64","name":"Omega"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Entropy","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Luo","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"BouncerDivisor","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"NoCROWS","outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
    # Purchase function
    {"inputs":[{"type":"address","name":"Token"},{"type":"uint256","name":"Amount"}],"name":"Purchase","outputs":[],"stateMutability":"nonpayable","type":"function"},
    # AddMarketRate
    {"inputs":[{"type":"address"},{"type":"uint256"}],"name":"AddMarketRate","outputs":[],"stateMutability":"nonpayable","type":"function"},
    # Staff/owner checks
    {"inputs":[{"type":"address"}],"name":"isOwner","outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"type":"address"}],"name":"isStaff","outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
    # LAU specifics
    {"inputs":[],"name":"username","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    # SHIO specifics
    {"inputs":[],"name":"Mu","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Alpha","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    # YUE specifics
    {"inputs":[{"type":"address"},{"type":"uint256"}],"name":"Withdraw","outputs":[],"stateMutability":"nonpayable","type":"function"},
    # Check _owners array
    {"inputs":[{"type":"uint256"}],"name":"_owners","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    # React on YUE
    {"inputs":[{"type":"uint64"}],"name":"React","outputs":[],"stateMutability":"nonpayable","type":"function"},
    # QING Join
    {"inputs":[{"type":"address"}],"name":"Join","outputs":[],"stateMutability":"nonpayable","type":"function"},
    # CHO functions
    {"inputs":[{"type":"address"}],"name":"GetUser","outputs":[{"type":"uint64","name":"Soul"},{"type":"tuple","name":"On","components":[{"type":"address","name":"Phi"},{"type":"address","name":"Mu"},{"type":"uint64","name":"Xi"},{"type":"uint64","name":"Pi"},{"type":"address","name":"Shio"},{"type":"uint64","name":"Ring"},{"type":"uint64","name":"Omicron"},{"type":"uint64","name":"Omega"}]},{"type":"string","name":"Username"},{"type":"uint64","name":"Entropy"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"type":"uint64"}],"name":"GetSoulToken","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]

# Additional ABI for checking who deployed Fornax and SHIO parent contract
SHIO_EXTRA_ABI = [
    {"inputs":[],"name":"Fomalhaute","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Fornax","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Tethys","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]

w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

if not w3.is_connected():
    print("ERROR: Cannot connect to PulseChain RPC")
    sys.exit(1)

print(f"Connected to PulseChain. Block: {w3.eth.block_number}")
print("=" * 80)

def safe_call(contract, func_name, *args):
    """Call a contract function, return None on error."""
    try:
        fn = contract.functions[func_name](*args)
        return fn.call()
    except Exception as e:
        return None

def fmt_tokens(raw, decimals=18):
    """Format raw token amount."""
    if raw is None:
        return "ERROR"
    if raw == 0:
        return "0"
    return f"{raw / 10**decimals:,.4f}"

def investigate_address(addr_str, expected_tokens, label):
    """Deep investigation of a Fornax holder."""
    addr = Web3.to_checksum_address(addr_str)
    print(f"\n{'='*80}")
    print(f"INVESTIGATING: {addr}")
    print(f"Label: {label} (~{expected_tokens} Fornax)")
    print(f"{'='*80}")

    # Check if EOA or contract
    code = w3.eth.get_code(addr)
    is_contract = len(code) > 2  # b'0x' or b'' for EOA

    if not is_contract:
        print(f"  TYPE: EOA (Externally Owned Account)")
        tx_count = w3.eth.get_transaction_count(addr)
        balance = w3.eth.get_balance(addr)
        print(f"  TX count: {tx_count}")
        print(f"  PLS balance: {fmt_tokens(balance)}")

        # Check Fornax balance
        fornax = w3.eth.contract(address=FORNAX, abi=BASIC_ABI)
        bal = safe_call(fornax, "balanceOf", addr)
        print(f"  Fornax balance: {fmt_tokens(bal)}")

        # Check if they have a LAU via CHO
        cho = w3.eth.contract(address=CHO, abi=BASIC_ABI)
        user_token = safe_call(cho, "GetUserTokenAddress", addr)
        if user_token and user_token != ZERO:
            print(f"  CHO LAU token: {user_token}")
            lau = w3.eth.contract(address=Web3.to_checksum_address(user_token), abi=BASIC_ABI)
            uname = safe_call(lau, "username")
            name = safe_call(lau, "name")
            sym = safe_call(lau, "symbol")
            print(f"    LAU name: {name}, symbol: {sym}, username: {uname}")
        else:
            print(f"  CHO LAU token: None (not a player via CHO)")
            # Try VOID
            void = w3.eth.contract(address=VOID, abi=BASIC_ABI)
            # No direct lookup by address, skip

        return {"type": "EOA", "address": addr, "fornax": bal, "acquisition_path": None}

    # It's a contract
    print(f"  TYPE: CONTRACT (code size: {len(code)} bytes)")

    c = w3.eth.contract(address=addr, abi=BASIC_ABI + SHIO_EXTRA_ABI)

    # Basic identity
    name = safe_call(c, "name")
    symbol = safe_call(c, "symbol")
    ctype = safe_call(c, "Type")
    print(f"  name(): {name}")
    print(f"  symbol(): {symbol}")
    print(f"  Type(): {ctype}")

    # Supply info
    total_supply = safe_call(c, "totalSupply")
    max_supply = safe_call(c, "maxSupply")
    decimals = safe_call(c, "decimals")
    if decimals is None:
        decimals = 18
    print(f"  totalSupply: {fmt_tokens(total_supply, decimals)}")
    print(f"  maxSupply: {fmt_tokens(max_supply, decimals) if max_supply else 'N/A'}")

    # Fornax balance (actual)
    fornax = w3.eth.contract(address=FORNAX, abi=BASIC_ABI)
    fornax_bal = safe_call(fornax, "balanceOf", addr)
    print(f"  Fornax balance (actual): {fmt_tokens(fornax_bal)}")

    # Self balance
    self_bal = safe_call(c, "balanceOf", addr)
    print(f"  Self-balance (own token): {fmt_tokens(self_bal, decimals)}")

    # Owner
    owner = safe_call(c, "owner")
    print(f"  owner(): {owner}")

    # Check some key addresses
    origin = safe_call(c, "Origin")
    if origin:
        print(f"  Origin(): {origin}")

    # Market rates
    print(f"\n  --- Market Rates ---")
    affection_rate = safe_call(c, "GetMarketRate", AFFECTION)
    print(f"  GetMarketRate(AFFECTION): {fmt_tokens(affection_rate, decimals) if affection_rate is not None else 'N/A (no function or error)'}")

    fornax_rate = safe_call(c, "GetMarketRate", FORNAX)
    print(f"  GetMarketRate(FORNAX): {fmt_tokens(fornax_rate, decimals) if fornax_rate is not None else 'N/A'}")

    # Check SHIO-specific functions
    rod = safe_call(c, "Rod")
    cone = safe_call(c, "Cone")
    if rod or cone:
        print(f"\n  --- SHIO Info ---")
        print(f"  Rod(): {rod}")
        print(f"  Cone(): {cone}")

    mu = safe_call(c, "Mu")
    alpha = safe_call(c, "Alpha")
    if mu:
        print(f"  Mu(): {mu}")
    if alpha:
        print(f"  Alpha(): {alpha}")

    # QING-specific
    asset = safe_call(c, "Asset")
    if asset:
        print(f"\n  --- QING Info ---")
        print(f"  Asset(): {asset}")
        cover = safe_call(c, "CoverCharge")
        print(f"  CoverCharge(): {fmt_tokens(cover, decimals) if cover is not None else 'N/A'}")
        waat = safe_call(c, "Waat")
        print(f"  Waat(): {waat}")
        bouncer_div = safe_call(c, "BouncerDivisor")
        print(f"  BouncerDivisor(): {bouncer_div}")
        no_crows = safe_call(c, "NoCROWS")
        print(f"  NoCROWS(): {no_crows}")
        entropy = safe_call(c, "Entropy")
        print(f"  Entropy(): {entropy}")

        # Check if asset is Fornax
        if asset and Web3.to_checksum_address(asset) == FORNAX:
            print(f"\n  *** THIS QING's ASSET IS FORNAX! ***")
            print(f"  This venue trades Fornax directly!")

    # On (Bao struct)
    on = safe_call(c, "On")
    if on:
        print(f"\n  --- Bao (On) ---")
        print(f"  Phi: {on[0]}")
        print(f"  Mu:  {on[1]}")
        print(f"  Xi:  {on[2]}")
        print(f"  Pi:  {on[3]}")
        print(f"  Shio: {on[4]}")
        print(f"  Ring: {on[5]}")
        print(f"  Omicron: {on[6]}")
        print(f"  Omega: {on[7]}")

    # Check if Joey/GIBS is owner or staff
    print(f"\n  --- Joey Access ---")
    joey_is_owner = safe_call(c, "isOwner", JOEY_EOA)
    joey_is_staff = safe_call(c, "isStaff", JOEY_EOA)
    gibs_is_owner = safe_call(c, "isOwner", GIBS_LAU)
    gibs_is_staff = safe_call(c, "isStaff", GIBS_LAU)
    print(f"  isOwner(Joey EOA): {joey_is_owner}")
    print(f"  isStaff(Joey EOA): {joey_is_staff}")
    print(f"  isOwner(GIBS_LAU): {gibs_is_owner}")
    print(f"  isStaff(GIBS_LAU): {gibs_is_staff}")

    # Check Purchase feasibility
    print(f"\n  --- Purchase Feasibility ---")
    if affection_rate is not None and affection_rate > 0:
        print(f"  AFFECTION rate: {fmt_tokens(affection_rate, decimals)} -> Purchase with AFFECTION is POSSIBLE if contract has self-balance > 0")
        if self_bal is not None and self_bal > 0:
            print(f"  *** CONTRACT HAS SELF-BALANCE: {fmt_tokens(self_bal, decimals)} ***")
            print(f"  *** Purchase() MIGHT WORK HERE! ***")
        else:
            print(f"  Contract self-balance is 0 -> Purchase() will fail (no tokens to give)")
    else:
        print(f"  No AFFECTION market rate -> Purchase with AFFECTION not possible")

    # Check if this contract has Fornax it could transfer to Joey
    if fornax_bal and fornax_bal > 0:
        print(f"\n  *** THIS CONTRACT HOLDS {fmt_tokens(fornax_bal)} FORNAX ***")
        print(f"  Checking if there's a way to extract it...")

        # Check for Withdraw function
        # Check if it's a YUE
        if ctype and "YUE" in str(ctype).upper():
            print(f"  Type is YUE -> check Withdraw(FORNAX, amount)")
            print(f"  Need to be owner/staff to call Withdraw")

        # Check for Redeem/exchange
        # Try various function selectors
        luo = safe_call(c, "Luo")
        if luo:
            print(f"  Luo(): {luo}")

    # Fornax-specific checks: does this contract have a relationship to XIE?
    fornax_check = safe_call(c, "Fornax")
    fomalhaute_check = safe_call(c, "Fomalhaute")
    tethys_check = safe_call(c, "Tethys")
    if fornax_check:
        print(f"\n  Fornax(): {fornax_check}")
    if fomalhaute_check:
        print(f"  Fomalhaute(): {fomalhaute_check}")
    if tethys_check:
        print(f"  Tethys(): {tethys_check}")

    result = {
        "type": "contract",
        "address": addr,
        "name": name,
        "symbol": symbol,
        "ctype": ctype,
        "fornax_bal": fornax_bal,
        "self_bal": self_bal,
        "affection_rate": affection_rate,
        "asset": asset,
    }
    return result

# --- Investigate Fornax itself ---
print("\n" + "=" * 80)
print("FORNAX TOKEN STATUS")
print("=" * 80)
fornax = w3.eth.contract(address=FORNAX, abi=BASIC_ABI + SHIO_EXTRA_ABI)
print(f"  name: {safe_call(fornax, 'name')}")
print(f"  symbol: {safe_call(fornax, 'symbol')}")
print(f"  Type: {safe_call(fornax, 'Type')}")
print(f"  totalSupply: {fmt_tokens(safe_call(fornax, 'totalSupply'))}")
print(f"  maxSupply: {fmt_tokens(safe_call(fornax, 'maxSupply'))}")
fornax_self_bal = safe_call(fornax, 'balanceOf', FORNAX)
print(f"  self-balance: {fmt_tokens(fornax_self_bal)}")
print(f"  owner: {safe_call(fornax, 'owner')}")
fornax_affection_rate = safe_call(fornax, 'GetMarketRate', AFFECTION)
print(f"  GetMarketRate(AFFECTION): {fmt_tokens(fornax_affection_rate)}")
print(f"  Entropy: {safe_call(fornax, 'Entropy')}")
print(f"  Rod: {safe_call(fornax, 'Rod')}")
print(f"  Cone: {safe_call(fornax, 'Cone')}")
fornax_on = safe_call(fornax, 'On')
if fornax_on:
    print(f"  On.Phi: {fornax_on[0]}")
    print(f"  On.Mu: {fornax_on[1]}")
    print(f"  On.Shio: {fornax_on[4]}")

# Also check XIE contract
print(f"\n  --- XIE (Fornax parent) ---")
xie = w3.eth.contract(address=XIE, abi=BASIC_ABI + SHIO_EXTRA_ABI)
print(f"  XIE name: {safe_call(xie, 'name')}")
print(f"  XIE Fornax(): {safe_call(xie, 'Fornax')}")
xie_fornax_bal = safe_call(fornax, 'balanceOf', XIE)
print(f"  XIE's Fornax balance: {fmt_tokens(xie_fornax_bal)}")

# Check Fornax balance at key Joey addresses
print(f"\n  --- Joey's Fornax Balances ---")
joey_fornax = safe_call(fornax, 'balanceOf', JOEY_EOA)
gibs_fornax = safe_call(fornax, 'balanceOf', GIBS_LAU)
qing_fornax = safe_call(fornax, 'balanceOf', GIBS_QING)
print(f"  Joey EOA: {fmt_tokens(joey_fornax)}")
print(f"  GIBS_LAU: {fmt_tokens(gibs_fornax)}")
print(f"  GIBS_QING: {fmt_tokens(qing_fornax)}")

# --- Investigate each holder ---
results = []
for addr_str, expected, label in HOLDERS:
    try:
        result = investigate_address(addr_str, expected, label)
        results.append(result)
    except Exception as e:
        print(f"\n  ERROR investigating {addr_str}: {e}")
        results.append({"address": addr_str, "error": str(e)})

# --- Check Fornax owners list ---
print("\n" + "=" * 80)
print("FORNAX OWNERSHIP CHAIN")
print("=" * 80)
for i in range(5):
    owner_i = safe_call(fornax, "_owners", i)
    if owner_i:
        print(f"  _owners[{i}]: {owner_i}")
    else:
        break

# --- Check if Fornax has any addOwner mechanism exploitable ---
print(f"\n  isOwner(Joey): {safe_call(fornax, 'isOwner', JOEY_EOA)}")
print(f"  isOwner(GIBS_LAU): {safe_call(fornax, 'isOwner', GIBS_LAU)}")
print(f"  isOwner(XIE): {safe_call(fornax, 'isOwner', XIE)}")
print(f"  isStaff(Joey): {safe_call(fornax, 'isStaff', JOEY_EOA)}")

# --- Check XIE ownership (Fornax's parent) ---
print(f"\n  --- XIE Ownership ---")
print(f"  XIE owner: {safe_call(xie, 'owner')}")
for i in range(5):
    o = safe_call(xie, "_owners", i)
    if o:
        print(f"  XIE _owners[{i}]: {o}")
    else:
        break
print(f"  XIE isOwner(Joey): {safe_call(xie, 'isOwner', JOEY_EOA)}")

# --- Check if any holder contract has a mechanism to send Fornax ---
print("\n" + "=" * 80)
print("SUMMARY: ACQUISITION PATHS")
print("=" * 80)

can_purchase = []
has_fornax = []
for r in results:
    if r.get("error"):
        continue
    if r.get("type") == "EOA":
        if r.get("fornax") and r["fornax"] > 0:
            has_fornax.append(f"  EOA {r['address']}: {fmt_tokens(r['fornax'])} Fornax (need manual transfer)")
    elif r.get("type") == "contract":
        if r.get("fornax_bal") and r["fornax_bal"] > 0:
            has_fornax.append(f"  {r.get('name','?')} ({r.get('ctype','?')}) {r['address']}: {fmt_tokens(r['fornax_bal'])} Fornax")
        if r.get("affection_rate") and r["affection_rate"] > 0 and r.get("self_bal") and r["self_bal"] > 0:
            can_purchase.append(f"  {r.get('name','?')} ({r.get('ctype','?')}) {r['address']}: rate={fmt_tokens(r['affection_rate'])}, self_bal={fmt_tokens(r['self_bal'])}")

print(f"\nContracts with Fornax balance:")
for h in has_fornax:
    print(h)
if not has_fornax:
    print("  None found with Fornax > 0")

print(f"\nContracts where Purchase() might work (AFFECTION rate > 0 AND self-balance > 0):")
for p in can_purchase:
    print(p)
if not can_purchase:
    print("  None found -- Purchase is dead everywhere")

print(f"\n--- KEY FINDING ---")
print(f"Fornax self-balance: {fmt_tokens(fornax_self_bal)}")
print(f"Fornax total/max: {fmt_tokens(safe_call(fornax, 'totalSupply'))}/{fmt_tokens(safe_call(fornax, 'maxSupply'))}")
if fornax_self_bal and fornax_self_bal > 0:
    print("Purchase() on Fornax IS possible (self-balance > 0)!")
else:
    print("Purchase() on Fornax is DEAD (self-balance = 0, maxed out)")

# --- Additional: Check if any QING venue has Fornax as Asset ---
print(f"\n{'='*80}")
print("CHECKING: Any QING with Fornax as Asset?")
print("="*80)
for r in results:
    if r.get("asset"):
        asset_addr = Web3.to_checksum_address(r["asset"])
        if asset_addr == FORNAX:
            print(f"  *** FOUND: {r['address']} ({r.get('name')}) has Asset=FORNAX ***")
        else:
            # Check what the asset is
            asset_c = w3.eth.contract(address=asset_addr, abi=BASIC_ABI)
            asset_name = safe_call(asset_c, "name")
            asset_sym = safe_call(asset_c, "symbol")
            print(f"  {r['address']} ({r.get('name')}) -> Asset: {asset_addr} ({asset_name}/{asset_sym})")

# --- Check: Can Fornax be earned through game actions? ---
print(f"\n{'='*80}")
print("CHECKING: Fornax earning mechanisms")
print("="*80)
# Fornax is a SHIO token (Rod or Cone of XIE)
# SHIOs mint via _mintToCap triggered by game actions on the parent contract
# Check if XIE has any public functions that trigger Fornax mintToCap

# Check if Fornax is actually maxed
fornax_ts = safe_call(fornax, 'totalSupply')
fornax_ms = safe_call(fornax, 'maxSupply')
if fornax_ts and fornax_ms:
    if fornax_ts >= fornax_ms * 10**18:
        print(f"  Fornax IS maxed out (total >= max). No more minting possible.")
    elif fornax_ts < fornax_ms * 10**18:
        remaining = (fornax_ms * 10**18 - fornax_ts) / 10**18
        print(f"  Fornax has {remaining:.4f} tokens left to mint!")
        print(f"  Game actions on XIE could still mint Fornax!")
    else:
        print(f"  totalSupply: {fornax_ts}, maxSupply: {fornax_ms}")
        print(f"  Need to check if maxSupply is already in wei or not")

# Double check: maxSupply might already be in base units or might need *10**18
print(f"\n  Raw totalSupply: {fornax_ts}")
print(f"  Raw maxSupply: {fornax_ms}")
if fornax_ts and fornax_ms:
    if fornax_ms < 10**18:
        # maxSupply is in tokens, totalSupply is in wei
        print(f"  maxSupply appears to be in tokens: {fornax_ms}")
        print(f"  totalSupply in tokens: {fornax_ts / 10**18:.4f}")
        if fornax_ts / 10**18 >= fornax_ms:
            print(f"  CONFIRMED: Fornax is fully minted (maxed)")
        else:
            print(f"  *** Fornax still has room to mint! ***")
    else:
        # Both in wei
        print(f"  Both values appear to be in wei")
        if fornax_ts >= fornax_ms:
            print(f"  CONFIRMED: Fornax is fully minted (maxed)")
        else:
            remaining_wei = fornax_ms - fornax_ts
            print(f"  *** Fornax has {remaining_wei / 10**18:.4f} tokens remaining! ***")

# --- Final: check if whale (0x530c) could be a SHIO or YUE that distributes ---
print(f"\n{'='*80}")
print("FINAL ANALYSIS")
print("="*80)
print("""
Fornax Acquisition Options:
1. Purchase() on Fornax directly: DEAD (self-balance = 0, maxed out)
2. DEX swap: No known Fornax pairs
3. Manual transfer from a holder (e.g., whale 0x530c or deployer)
4. Game mechanic: If Fornax is NOT fully maxed, XIE actions could mint more
5. QING venue: If any QING has Fornax as Asset, joining/trading could yield Fornax
6. YUE wallet: If a YUE holds Fornax and Joey has access, Withdraw() could work
7. Contract with self-balance + AFFECTION rate: Purchase() on that contract's OWN token,
   then somehow exchange that token for Fornax
""")

print("\nScript complete.")
