#!/usr/bin/env python3
"""
Find SEI: The YUE contract was deployed BY SEI via `new YUE(...)`.
So the creator of Noumenon's YUE IS the SEI contract address.
"""
from web3 import Web3
from eth_utils import keccak

RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

NOUMENON_YUE = Web3.to_checksum_address("0x935a694377cf48d8fc934f17db289774f0ce7075")
CHAN_ADDR    = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
MAP_ADDR    = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_ADDR   = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
HECKE_ADDR  = Web3.to_checksum_address("0x29A924D9B0233026B9844f2aFeB202F1791D7593")

def addr_call(addr, fn):
    abi = [{"inputs":[],"name":fn,"outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        r = getattr(c.functions, fn)().call()
        return r if r != "0x0000000000000000000000000000000000000000" else None
    except:
        return None

def string_call(addr, fn):
    abi = [{"inputs":[],"name":fn,"outputs":[{"type":"string"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        return getattr(c.functions, fn)().call()
    except:
        return None

def uint256_call(addr, fn):
    abi = [{"inputs":[],"name":fn,"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"}]
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

# ─── FIND SEI AS NOUMENON YUE CREATOR ───────────────────────────────────────
print(f"\n=== FIND SEI: Who deployed Noumenon's YUE? ===")
print(f"  Noumenon YUE: {NOUMENON_YUE}")

# Get transaction that created Noumenon's YUE
# Use eth_getTransactionByBlockNumberAndIndex via block search
# First, find creation block via binary search
code = w3.eth.get_code(NOUMENON_YUE)
print(f"  YUE code size: {len(code)} bytes")

# Binary search for creation block
lo, hi = 0, w3.eth.block_number
print(f"  Searching creation block (lo={lo}, hi={hi})...")
while lo < hi:
    mid = (lo + hi) // 2
    code_at_mid = w3.eth.get_code(NOUMENON_YUE, mid)
    if len(code_at_mid) > 2:
        hi = mid
    else:
        lo = mid + 1
creation_block = lo
print(f"  ✓ Noumenon YUE created at block: {creation_block:,}")

# Find the transaction in that block that created this contract
block = w3.eth.get_block(creation_block, full_transactions=True)
for tx in block['transactions']:
    # Contract creation: tx.to is None
    if tx.get('to') is None:
        # Check if this tx created NOUMENON_YUE
        receipt = w3.eth.get_transaction_receipt(tx['hash'])
        if receipt.get('contractAddress', '').lower() == NOUMENON_YUE.lower():
            print(f"\n  DIRECT DEPLOY (tx.to=None):")
            print(f"  tx.from = {tx['from']} ← THIS IS SEI? (external deploy)")
            print(f"  tx hash = {tx['hash'].hex()}")
    # Contract creation via CREATE from another contract
    # The tx.to would be the calling contract (SEI)
    else:
        receipt = w3.eth.get_transaction_receipt(tx['hash'])
        # Check if any created contract in this tx is NOUMENON_YUE
        for log in receipt.logs:
            pass  # logs don't directly tell us about CREATE
        # The contractAddress is only set for direct deploys, not internal creates
        # We need to look at trace, or check if the SEI address is tx.to

# Most likely YUE was created by SEI internally (CREATE from SEI contract)
# The tx to SEI that triggered the YUE creation
print(f"\n  Looking for SEI.Start() call that created Noumenon's YUE...")
print(f"  All txs in block {creation_block}:")

# The Start(address,string,string) selector
start_sel = keccak(text="Start(address,string,string)")[:4]
print(f"  Start(address,string,string) selector: 0x{start_sel.hex()}")

for tx in block['transactions']:
    if tx.get('to'):
        inp = bytes(tx['input']) if tx['input'] else b''
        if len(inp) >= 4 and inp[:4] == start_sel:
            print(f"\n  ★ FOUND Start() call!")
            print(f"    tx.to   = {tx['to']} ← THIS IS SEI!")
            print(f"    tx.from = {tx['from']}")
            print(f"    tx.hash = {tx['hash'].hex()}")
            SEI_ADDR = tx['to']

            # Verify it's SEI
            chan_r = addr_call(SEI_ADDR, "Chan")
            print(f"    SEI.Chan() = {chan_r}")
            name_r = string_call(SEI_ADDR, "name")
            print(f"    SEI.name() = {name_r}")
            ts_r   = uint256_call(SEI_ADDR, "totalSupply")
            print(f"    SEI.totalSupply() = {ts_r}")

# If not found via Start(), scan all txs in block
print(f"\n  All txs in creation block ({len(block['transactions'])}):")
for tx in block['transactions']:
    inp = bytes(tx['input']) if tx['input'] else b''
    sel = inp[:4].hex() if len(inp) >= 4 else "0000"
    to  = tx.get('to', 'CREATE')
    print(f"    {tx['from'][:12]}... → {str(to)[:12]}... sel=0x{sel}")

# ─── ALSO CHECK HECKE ────────────────────────────────────────────────────────
print(f"\n=== HECKE MERIDIANS: {HECKE_ADDR} ===")
name_h = string_call(HECKE_ADDR, "name")
sym_h  = string_call(HECKE_ADDR, "symbol")
print(f"  name={name_h}  symbol={sym_h}")

# ─── MAP GETTERS FOR GIBS QING ───────────────────────────────────────────────
print(f"\n=== MAP STORAGE SLOTS (all) ===")
for i in range(15):
    slot_val = w3.eth.get_storage_at(MAP_ADDR, i)
    val_hex = slot_val.hex()
    if val_hex != "0" * 64:
        raw = bytes.fromhex(val_hex)
        # Try decode as address
        if val_hex[:24] == "0" * 24 and val_hex[24:] != "0" * 40:
            addr = "0x" + val_hex[24:]
            name = string_call(addr, "name") or ""
            print(f"  slot[{i:2d}] = {addr}  ({name})")
        else:
            # Try string
            try:
                text = raw.rstrip(b'\x00').decode('ascii', errors='?')
                print(f"  slot[{i:2d}] = '{text[:40]}...'")
            except:
                print(f"  slot[{i:2d}] = 0x{val_hex[:40]}...")

# ─── PROBE CHAN FOR YAN USING NOUMENON YUE's CREATOR ADDRESS ─────────────────
print(f"\n=== CHAN.YAN() PROBE ===")
# The Noumenon YUE was created by someone calling SEI.Start()
# That caller registered in CHAN.Yan()
# Let's try different known addresses
known_wallets = {
    "Joey":     "0x17367877aF5A8D0Eb33ba5689A880f696386E24D",
    "Creator":  "0x7a20189B297343CF26d8548764b04891f37F3414",
    "GIBS":     GIBS_ADDR,
    "Noumenon_YUE": NOUMENON_YUE,
    "CHAN":     CHAN_ADDR,
    "MAP":     MAP_ADDR,
}
for label, wallet in known_wallets.items():
    r = addr_call_addr(CHAN_ADDR, "Yan", Web3.to_checksum_address(wallet))
    if r:
        print(f"  CHAN.Yan({label}) → {r}")
    else:
        print(f"  CHAN.Yan({label}) → 0x0 (no YUE)")
