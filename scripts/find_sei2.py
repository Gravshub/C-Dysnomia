#!/usr/bin/env python3
"""
Find SEI by probing mystery contract and scanning CHAN deployer history.
"""
from web3 import Web3
from eth_utils import keccak
import rlp

RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

CHAN_ADDR    = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
MAP_ADDR    = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
MYSTERY     = Web3.to_checksum_address("0xc078C8DaE2aC8b08416e9a579B4C61D888C1f05D")
GIBS_ADDR   = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

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

def compute_create_addr(deployer, nonce):
    """Compute CREATE address from deployer and nonce."""
    if nonce == 0:
        encoded = rlp.encode([bytes.fromhex(deployer[2:]), b''])
    else:
        encoded = rlp.encode([bytes.fromhex(deployer[2:]), nonce])
    return Web3.to_checksum_address("0x" + keccak(encoded)[12:].hex())

# ─── PROBE MYSTERY CONTRACT ──────────────────────────────────────────────────
print(f"\n=== MYSTERY CONTRACT: {MYSTERY} ===")
# Probe all useful functions
probes_addr = ["Eta", "Mu", "Nu", "Chan", "Sei", "Void", "Lau", "Cho", "Map",
               "Chi", "On", "Phi", "Yang", "Yau", "Zhou", "Zheng", "Yi",
               "Siu", "Xie", "Xia", "Mai", "Qi", "Zuo", "Cho", "Shio",
               "Choa", "Cheon", "Meta", "Ring", "War", "World", "Sea"]
for fn in probes_addr:
    r = addr_call(MYSTERY, fn)
    if r:
        print(f"  .{fn:8s}() → {r}")
n_name = string_call(MYSTERY, "name")
n_sym  = string_call(MYSTERY, "symbol")
n_ts   = uint256_call(MYSTERY, "totalSupply")
print(f"  name={n_name}  symbol={n_sym}  totalSupply={n_ts}")

# ─── FIND CHAN DEPLOYER ───────────────────────────────────────────────────────
print(f"\n=== FIND CHAN DEPLOYER ===")
# We need to find when CHAN was deployed and by whom
# Strategy: look at CREATE2 or raw CREATE from known factory accounts
# Or use the Hecke/CHO deployer by scanning storage

# Look at CHAN storage to find deployer-related data
print(f"  CHAN storage slots:")
for i in range(15):
    slot_val = w3.eth.get_storage_at(CHAN_ADDR, i)
    val_hex = slot_val.hex()
    if val_hex != "0" * 64:
        if val_hex[:24] == "0" * 24 and len(val_hex) == 64:
            addr = "0x" + val_hex[24:]
            print(f"    slot[{i}] = {addr} (address)")
        else:
            # Try to decode as string or number
            try:
                # Check if it's ASCII in the upper bytes
                raw = bytes.fromhex(val_hex)
                printable = all(32 <= b <= 126 or b == 0 for b in raw)
                if printable:
                    text = raw.rstrip(b'\x00').decode('ascii', errors='replace')
                    if any(32 <= ord(c) <= 126 for c in text):
                        print(f"    slot[{i}] = '{text}' (string?)")
                    else:
                        print(f"    slot[{i}] = 0x{val_hex[:20]}...")
                else:
                    print(f"    slot[{i}] = 0x{val_hex[:20]}...")
            except:
                print(f"    slot[{i}] = 0x{val_hex[:20]}...")

# ─── COMPUTE SEI FROM CHAN DEPLOYER NONCE ────────────────────────────────────
print(f"\n=== COMPUTE SEI FROM CHAN DEPLOYER NONCE ===")
# Known game deployer address from CLAUDE.md:
# Creator wallet (internal): 0x7a20189B297343CF26d8548764b04891f37F3414
CREATOR = Web3.to_checksum_address("0x7a20189B297343CF26d8548764b04891f37F3414")
creator_nonce = w3.eth.get_transaction_count(CREATOR)
print(f"  Creator wallet nonce: {creator_nonce}")
print(f"  Checking recent CREATE addresses:")
for n in range(max(0, creator_nonce-30), creator_nonce+5):
    addr = compute_create_addr(CREATOR, n)
    code = w3.eth.get_code(addr)
    if len(code) > 2:
        name = string_call(addr, "name") or "?"
        chan_result = addr_call(addr, "Chan")
        if chan_result and chan_result.lower() == CHAN_ADDR.lower():
            print(f"  ★ NONCE {n}: {addr} → .Chan()={chan_result} ← THIS IS SEI!")
        elif name and "Dysnomia" in str(name):
            print(f"  nonce {n}: {addr} → name={name}  Chan()={chan_result}")
        else:
            # Quick probe
            for fn in ["Sei", "Chan", "Cho", "Map", "Xie", "Eta"]:
                r = addr_call(addr, fn)
                if r:
                    print(f"  nonce {n}: {addr} → .{fn}()={r}")
                    break

# ─── FIND SEI BY SCANNING CANDIDATE ADDRESSES ────────────────────────────────
print(f"\n=== FIND SEI BY CHAN() PROBE ===")
# We know SEI.Chan() returns CHAN_ADDR
# Let's check storage-derived addresses and known addresses
candidates = []

# Storage of CHO might have SEI reference
for i in range(15):
    slot_val = w3.eth.get_storage_at(CHO_ADDR := Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB"), i)
    val_hex = slot_val.hex()
    if val_hex[:24] == "0" * 24 and val_hex[24:] != "0" * 40:
        addr = Web3.to_checksum_address("0x" + val_hex[24:])
        candidates.append((f"CHO_slot{i}", addr))

# Also try MAP storage
for i in range(12):
    slot_val = w3.eth.get_storage_at(MAP_ADDR, i)
    val_hex = slot_val.hex()
    if val_hex[:24] == "0" * 24 and val_hex[24:] != "0" * 40:
        addr = Web3.to_checksum_address("0x" + val_hex[24:])
        candidates.append((f"MAP_slot{i}", addr))

print(f"  Checking {len(candidates)} candidate addresses for SEI.Chan() == CHAN...")
for label, cand in candidates:
    code = w3.eth.get_code(cand)
    if len(code) > 2:
        chan_r = addr_call(cand, "Chan")
        if chan_r and chan_r.lower() == CHAN_ADDR.lower():
            print(f"  ★ {label}: {cand} → .Chan()={chan_r} ← SEI FOUND!")
        else:
            # Still probe for name
            name = string_call(cand, "name")
            if name:
                print(f"    {label}: {cand} → name={name}")

# ─── BROADER CREATOR NONCE SCAN ──────────────────────────────────────────────
print(f"\n=== BROADER CREATOR NONCE SCAN ===")
# Look for contracts deployed by creator that have .Chan() getter returning CHAN
print(f"  Scanning creator nonces 0-100 for SEI:")
found_addresses = []
for n in range(101):
    addr = compute_create_addr(CREATOR, n)
    code = w3.eth.get_code(addr)
    if len(code) > 2:
        chan_r = addr_call(addr, "Chan")
        if chan_r and chan_r.lower() == CHAN_ADDR.lower():
            print(f"  ★ NONCE {n}: {addr} → .Chan()={chan_r} ← SEI!")
            found_addresses.append(addr)
        # Also check if it has Start() function selector
        # Start(address,string,string) selector
        start_sel = keccak(text="Start(address,string,string)")[:4]
        try:
            # Check if this contract has Start function
            code_hex = w3.eth.get_code(addr).hex()
            if start_sel.hex() in code_hex:
                name = string_call(addr, "name")
                print(f"  ★ NONCE {n}: {addr} → HAS Start() selector! name={name}")
                found_addresses.append(addr)
        except:
            pass

if not found_addresses:
    print(f"  SEI not found in creator nonces 0-100")
    # Check current nonce info
    print(f"  Creator current nonce: {creator_nonce}")
