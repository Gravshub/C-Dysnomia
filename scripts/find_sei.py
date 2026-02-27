#!/usr/bin/env python3
"""
Focused probe to find SEI address + decode VOID messages + read MAP state.
"""
from web3 import Web3
from eth_utils import keccak

RPC = "https://rpc.pulsechainstats.com"
w3 = Web3(Web3.HTTPProvider(RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

MAP_ADDR  = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
CHO_ADDR  = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
CHAN_ADDR = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
ZUO_ADDR  = Web3.to_checksum_address("0xb0Ba7D36B7F0505879179ecE7401F24eB653c6E1")
VOID_ADDR = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")
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

def bool_call(addr, fn):
    abi = [{"inputs":[],"name":fn,"outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        return getattr(c.functions, fn)().call()
    except:
        return None

def addr_call_addr_input(addr, fn, input_val):
    abi = [{"inputs":[{"type":"address"}],"name":fn,"outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
    try:
        c = w3.eth.contract(address=addr, abi=abi)
        r = getattr(c.functions, fn)(input_val).call()
        return r if r != "0x0000000000000000000000000000000000000000" else None
    except:
        return None

# ─── PROBE MAP ────────────────────────────────────────────────────────────────
print(f"\n=== PROBE MAP ({MAP_ADDR}) ===")
all_names = [
    "Sei", "SEI", "Sea", "Tang", "Cho", "Chan", "Xie", "Xia", "Mai",
    "Qi", "Zuo", "Meta", "Choa", "Cheon", "Ring", "War", "World",
    "Gwat", "Pang", "Zi", "Yang", "Yau", "Zhou", "Phi", "Mu", "Nu",
    "Eta", "Rho", "Hecke", "Tau", "Sigma", "Lambda", "Theta",
    "Eris", "Fornax", "Fomalhaute", "Atropa", "Fed", "Siu",
    "V1", "V2", "V3", "V4", "Fdic",
]
for fn in all_names:
    r = addr_call(MAP_ADDR, fn)
    if r:
        print(f"  MAP.{fn:12s}() → {r}")

# Also check uint256 getters on MAP
for fn in ["Count", "Total", "Multiplier", "Threshold", "Luo"]:
    r = uint256_call(MAP_ADDR, fn)
    if r is not None:
        print(f"  MAP.{fn:12s}() → {r}")

# Check bool
for fn in ["Gwat", "NoCROWS"]:
    r = bool_call(MAP_ADDR, fn)
    if r is not None:
        print(f"  MAP.{fn:12s}() → {r}")

# MAP with address input (e.g., Qings(GIBS))
GIBS = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
for fn in ["Qings", "Venues", "New", "Mu", "Chi", "Sea", "Cho"]:
    r = addr_call_addr_input(MAP_ADDR, fn, GIBS)
    if r:
        print(f"  MAP.{fn}(GIBS) → {r}")
for fn in ["Qings", "Venues", "Mu", "Chi", "Sea"]:
    r = addr_call_addr_input(MAP_ADDR, fn, JOEY_WALLET)
    if r:
        print(f"  MAP.{fn}(Joey) → {r}")

# ─── PROBE CHO MORE ──────────────────────────────────────────────────────────
print(f"\n=== PROBE CHO EXTENDED ({CHO_ADDR}) ===")
cho_names = [
    "Sei", "Sea", "Tang", "Meta", "Choa", "Cheon", "Ring", "War", "World",
    "Map", "Gwat", "Pang", "Zi", "Yang", "Yau", "Zhou", "Phi", "Mu", "Nu",
    "Eta", "Rho", "Hecke", "Tau", "Sigma", "Lau", "Chan", "Xie", "Xia",
    "Yan", "Yue", "Fed", "Fdic", "Siu", "Atropa"
]
for fn in cho_names:
    r = addr_call(CHO_ADDR, fn)
    if r:
        print(f"  CHO.{fn:12s}() → {r}")

# CHO with address input
for fn in ["Yan", "Luo", "Qu", "Sea", "Saat", "User", "Soul"]:
    r = addr_call_addr_input(CHO_ADDR, fn, JOEY_WALLET)
    if r:
        print(f"  CHO.{fn}(Joey) → {r}")

# ─── DECODE VOID MESSAGES ────────────────────────────────────────────────────
print("\n=== DECODE VOID MESSAGES ===")
# The 3 txs from 0xb1c9b8d6... with selector 0x00000002
tx_blocks = [25888916, 25888922, 25891721]
for blk in tx_blocks:
    try:
        block = w3.eth.get_block(blk, full_transactions=True)
        void_txs = [tx for tx in block['transactions']
                    if tx.get('to') and tx['to'].lower() == VOID_ADDR.lower()]
        for tx in void_txs:
            inp = bytes(tx['input'])
            sel = inp[:4].hex()
            caller = tx['from']
            print(f"  Block {blk}: from={caller}  selector=0x{sel}  data_len={len(inp)}")
            if len(inp) > 4:
                print(f"    raw_data: {inp[:64].hex()}")
    except Exception as e:
        print(f"  Block {blk}: ERROR {e}")

# Also look for all txs in those blocks that involve VOID
for blk in tx_blocks:
    try:
        block = w3.eth.get_block(blk, full_transactions=True)
        print(f"\n  Block {blk} — all txs involving VOID:")
        for tx in block['transactions']:
            if tx.get('to') and tx['to'].lower() == VOID_ADDR.lower():
                print(f"    DIRECT: from={tx['from']} sel=0x{bytes(tx['input'])[:4].hex()}")
            # Check for internal txs via transaction receipt
    except Exception as e:
        print(f"  {e}")

# Look at the receipts for those txs - what events did they emit?
print("\n  Checking receipts for known tx hashes in those blocks:")
# Get tx hashes from those blocks
for blk in tx_blocks:
    try:
        block = w3.eth.get_block(blk, full_transactions=True)
        for tx in block['transactions']:
            receipt = w3.eth.get_transaction_receipt(tx['hash'])
            void_logs = [l for l in receipt.logs if l['address'].lower() == VOID_ADDR.lower()]
            if void_logs:
                print(f"  Block {blk}, tx={tx['hash'].hex()[:16]}..., from={tx['from'][:12]}...")
                print(f"    VOID logs: {len(void_logs)}, sel=0x{bytes(tx['input'])[:4].hex()}")
                if tx.get('to'):
                    print(f"    tx.to = {tx['to']}")
                # Decode if it's a known selector
                inp = bytes(tx['input'])
                if len(inp) >= 4:
                    sel = inp[:4]
                    sel_hex = sel.hex()
                    # Try to decode common selectors
                    for sig in ["Chat(string)", "Log(string)", "SetAttribute(string,string)",
                                "Alias(address,string)", "AddLibrary(string,address)",
                                "Enter(string,string)", "Enter()"]:
                        if sel == keccak(text=sig)[:4]:
                            print(f"    → Decoded as: {sig}")
                            break
                    else:
                        print(f"    → Unknown selector: 0x{sel_hex}")
    except Exception as e:
        pass

# ─── CHECK SEI VIA DEPLOY.TS SEQUENCE ────────────────────────────────────────
print("\n=== TRY TO FIND SEI VIA CHO ENTER EVENTS ===")
# CHO.Enter(LAU) is called during SEI.Start()
# Let's find calls to CHO.Enter which would reveal SEI or callers of SEI
# Enter(address) selector
enter_addr_sig = keccak(text="Enter(address)")[:4]
print(f"  Enter(address) selector: 0x{enter_addr_sig.hex()}")

# Also look at recent txs to VOID from any address (broader scan)
print("\n=== BROADER VOID ACTIVITY (last 10k blocks) ===")
from_block_broad = w3.eth.block_number - 10000
TRANSFER_TOPIC = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
try:
    logs = w3.eth.get_logs({
        "fromBlock": hex(from_block_broad),
        "toBlock": "latest",
        "address": VOID_ADDR,
        "topics": [TRANSFER_TOPIC]
    })
    print(f"  VOID Transfer events in last 10k blocks: {len(logs)}")
    if logs:
        # Group by caller
        callers = {}
        for log in logs:
            tx = w3.eth.get_transaction(log['transactionHash'])
            caller = tx['from']
            sel = bytes(tx['input'])[:4].hex() if tx['input'] else "none"
            key = f"{caller}|0x{sel}"
            callers[key] = callers.get(key, 0) + 1
        for k, cnt in sorted(callers.items(), key=lambda x: -x[1]):
            print(f"    {cnt}x {k}")
except Exception as e:
    print(f"  Error: {e}")
