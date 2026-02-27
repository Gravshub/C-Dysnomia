#!/usr/bin/env python3
"""
Verify if GIBS QING exists, find SEI, decode VOID messages.
"""
from web3 import Web3
from eth_utils import keccak

RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

MAP_ADDR    = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
CHO_ADDR    = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
CHAN_ADDR   = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
GIBS_ADDR  = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
CANDIDATE_QING = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
MYSTERY_CONTRACT = Web3.to_checksum_address("0xc078C8DaE2aC8b08416e9a579B4C61D888C1f05D")

def addr_call(addr, fn):
    abi = [{"inputs":[],"name":fn,"outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        r = getattr(c.functions, fn)().call()
        return r if r != "0x0000000000000000000000000000000000000000" else None
    except:
        return None

def uint256_call(addr, fn):
    abi = [{"inputs":[],"name":fn,"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        return getattr(c.functions, fn)().call()
    except:
        return None

def bool_call(addr, fn):
    abi = [{"inputs":[],"name":fn,"outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        return getattr(c.functions, fn)().call()
    except:
        return None

def string_call(addr, fn):
    abi = [{"inputs":[],"name":fn,"outputs":[{"type":"string"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        return getattr(c.functions, fn)().call()
    except:
        return None

def addr_call_addr(addr, fn, input_addr):
    abi = [{"inputs":[{"type":"address"}],"name":fn,"outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        r = getattr(c.functions, fn)(input_addr).call()
        return r if r != "0x0000000000000000000000000000000000000000" else None
    except:
        return None

# ─── CHECK IF CANDIDATE QING EXISTS ─────────────────────────────────────────
print(f"\n=== CHECK CANDIDATE QING: {CANDIDATE_QING} ===")
code = w3.eth.get_code(CANDIDATE_QING)
print(f"  Contract code size: {len(code)} bytes")
if len(code) > 2:
    print(f"  ✓ CONTRACT EXISTS!")
    # Probe it as a QING
    for fn in ["Asset", "Cho", "Map", "Chi", "Luo", "CoverCharge", "BouncerDivisor"]:
        r = addr_call(CANDIDATE_QING, fn)
        if r:
            print(f"  .{fn}() → {r}")
    # Check if Asset == GIBS
    asset = addr_call(CANDIDATE_QING, "Asset")
    if asset:
        asset_match = asset.lower() == GIBS_ADDR.lower()
        print(f"  Asset == GIBS? {asset_match}")
    # ERC20 info
    name = string_call(CANDIDATE_QING, "name")
    sym  = string_call(CANDIDATE_QING, "symbol")
    ts   = uint256_call(CANDIDATE_QING, "totalSupply")
    gwat = bool_call(CANDIDATE_QING, "Gwat")
    print(f"  name={name}  symbol={sym}  totalSupply={ts}  Gwat={gwat}")
else:
    print(f"  ✗ No contract at this address (QING not yet deployed)")
    print(f"  → This was a simulation result from MAP.New(GIBS) eth_call")

# ─── LOOK FOR MAP STORED QINGS MAPPING ──────────────────────────────────────
print(f"\n=== PROBE MAP FOR QINGS MAPPING ===")
# MAP might store a mapping from asset → QING address
# Try different getter names
for fn_name, input_val in [
    ("Qings", GIBS_ADDR),
    ("Sea", GIBS_ADDR),
    ("Mu", GIBS_ADDR),
    ("Chi", GIBS_ADDR),
    ("Venues", GIBS_ADDR),
    ("Yan", GIBS_ADDR),
    ("Yan", JOEY_WALLET),
]:
    r = addr_call_addr(MAP_ADDR, fn_name, input_val)
    if r:
        print(f"  MAP.{fn_name}({'GIBS' if input_val==GIBS_ADDR else 'Joey'}) → {r}")

# ─── PROBE MYSTERY CONTRACT ──────────────────────────────────────────────────
print(f"\n=== MYSTERY CONTRACT: {MYSTERY_CONTRACT} ===")
mystery_code = w3.eth.get_code(MYSTERY_CONTRACT)
print(f"  Code size: {len(mystery_code)} bytes")
if len(mystery_code) > 2:
    # Probe it like a LAU/DSS
    for fn in ["name", "symbol", "totalSupply"]:
        try:
            abi_fn = [{"inputs":[],"name":fn,"outputs":[{"type":"string" if fn in ["name","symbol"] else "uint256"}],"stateMutability":"view","type":"function"}]
            c = w3.eth.contract(address=MYSTERY_CONTRACT, abi=abi_fn)
            r = getattr(c.functions, fn)().call()
            print(f"  .{fn}() → {r}")
        except:
            pass
    for fn in ["Eta", "Mu", "Nu", "Chan", "Sei", "Void", "Lau", "Cho", "Map", "Chi", "On", "Phi"]:
        r = addr_call(MYSTERY_CONTRACT, fn)
        if r:
            print(f"  .{fn}() → {r}")

# ─── DECODE THE selector 0x00000002 ─────────────────────────────────────────
print(f"\n=== SELECTOR 0x00000002 ===")
# What function has selector 0x00000002?
# Brute-force check common Dysnomia function signatures
funcs = [
    "Chat(string)", "Log(string)", "Enter()", "Enter(string,string)",
    "Enter(address)", "Start(address,string,string)", "New(address)",
    "Void(bool,bool)", "Username(string)", "SetAttribute(string,string)",
    "Alias(address,string)", "mintToCap()", "Withdraw(address,uint256)",
    "chatAndClaim(string)", "chatAndSnipe(string)", "snipe()",
    "Faa(address,uint256)", "Miu(string,string)", "Luo()",
    "Xie()", "Xia()", "Mai()", "Qi()", "Zuo()", "Cho()", "Chan()",
    "Map()", "Sei()", "React()", "Phi()", "Mu()", "Nu()", "Eta()",
    "Rho()", "Tau()", "Sigma()", "Theta()", "Lambda()",
    "totalSupply()", "balanceOf(address)", "transfer(address,uint256)",
    "approve(address,uint256)", "transferFrom(address,address,uint256)",
    "AddMarketRate(address,uint256)", "Purchase(address,uint256)",
    "Redeem(address,uint256)", "Join(address)", "Bounce(address)",
    "addOwner(address)", "removeOwner(address)",
]
target = bytes.fromhex("00000002")
for sig in funcs:
    sel = keccak(text=sig)[:4]
    if sel == target:
        print(f"  MATCH: {sig} → 0x{sel.hex()}")
print(f"  (None of the above match 0x00000002 — likely a unique contract function)")
# Let's try the known VOID function entry points
print(f"\n  Known VOID function selectors:")
void_fns = ["Chat(string)", "Log(string)", "SetAttribute(string,string)",
            "Alias(address,string)", "AddLibrary(string,address)",
            "Enter()", "Enter(string,string)", "mintToCap()"]
for sig in void_fns:
    sel = keccak(text=sig)[:4]
    print(f"    0x{sel.hex()} = {sig}")

# ─── FIND SEI THROUGH MAP CONTRACT CREATION TX ──────────────────────────────
print(f"\n=== FIND SEI VIA MAP DEPLOYMENT ===")
# MAP was created on-chain. Its creator likely also created SEI.
# Get MAP contract creation transaction
try:
    # MAP code hash approach - get creation tx from traces
    # Alternative: scan deployment transactions around when MAP was deployed
    # First, let's check MAP's nonce (if MAP created anything via CREATE)
    map_nonce = w3.eth.get_transaction_count(MAP_ADDR)
    print(f"  MAP nonce: {map_nonce} (contracts it has deployed)")

    # Get creation block of MAP by checking its deployment
    # We can estimate when MAP was deployed relative to GIBS (block 26215664)
    # Scan backwards for MAP contract creation
    print(f"  MAP code size: {len(w3.eth.get_code(MAP_ADDR))} bytes")

    # Try reading MAP's full storage slots for SEI
    # Slot 0 onwards
    print(f"\n  MAP storage slots (first 5):")
    for i in range(5):
        slot_val = w3.eth.get_storage_at(MAP_ADDR, i)
        val_hex = slot_val.hex()
        if val_hex != "0" * 64:
            # Check if it's an address (last 20 bytes non-zero, first 12 zero)
            if val_hex[:24] == "0" * 24 and val_hex[24:] != "0" * 40:
                addr = "0x" + val_hex[24:]
                print(f"    slot[{i}] = {addr} (address)")
            else:
                print(f"    slot[{i}] = 0x{val_hex}")
        else:
            print(f"    slot[{i}] = 0x0")
except Exception as e:
    print(f"  Error: {e}")

# ─── CHECK CHO STORAGE SLOTS ────────────────────────────────────────────────
print(f"\n=== CHO STORAGE SLOTS ===")
try:
    for i in range(8):
        slot_val = w3.eth.get_storage_at(CHO_ADDR, i)
        val_hex = slot_val.hex()
        if val_hex != "0" * 64:
            if val_hex[:24] == "0" * 24 and val_hex[24:] != "0" * 40:
                addr = "0x" + val_hex[24:]
                print(f"    slot[{i}] = {addr} (address)")
            else:
                print(f"    slot[{i}] = 0x{val_hex}")
        else:
            print(f"    slot[{i}] = 0x0")
except Exception as e:
    print(f"  Error: {e}")

# ─── VERIFY CHAN.YAN FUNCTION SIGNATURE ──────────────────────────────────────
print(f"\n=== VERIFY CHAN.YAN() ===")
# Yan might take different argument types
yan_sig1 = keccak(text="Yan(address)")[:4]
yan_sig2 = keccak(text="Yan(uint64)")[:4]
yan_sig3 = keccak(text="Yan(uint256)")[:4]
print(f"  Yan(address) selector: 0x{yan_sig1.hex()}")
print(f"  Yan(uint64)  selector: 0x{yan_sig2.hex()}")
print(f"  Yan(uint256) selector: 0x{yan_sig3.hex()}")
# Call CHAN with each
for sig, input_type, val in [
    ("Yan(address)", "address", JOEY_WALLET),
    ("Yan(uint64)", "uint64", 0),
]:
    abi_fn = [{"inputs":[{"type":input_type}],"name":"Yan","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=CHAN_ADDR, abi=abi_fn)
        r = c.functions.Yan(val).call()
        print(f"  CHAN.Yan({input_type}={val!r}) → {r}")
    except Exception as e:
        print(f"  CHAN.Yan({input_type}) error: {e}")
