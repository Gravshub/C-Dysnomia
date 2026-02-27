#!/usr/bin/env python3
"""
Probe CHO for SEI/MAP addresses + scan VOID for recent chat messages.
"""
from web3 import Web3
from eth_utils import keccak

RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# Discovered addresses
CHO_ADDR  = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
CHAN_ADDR  = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
GIBS_ADDR = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
VOID_ADDR = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
DSS_ADDR  = Web3.to_checksum_address("0x91Df693177eE5C81016d0B7c4c2052A7d229c031")

# Also try these addresses as candidate SEI/MAP
ZUO_ADDR  = Web3.to_checksum_address("0xb0Ba7D36B7F0505879179ecE7401F24eB653c6E1")
QI_ADDR   = Web3.to_checksum_address("0x4d9Ce396BE95dbc5F71808c38107eB7422FD9a03")

def addr_call(contract_addr, fn_name):
    abi = [{"inputs":[],"name":fn_name,"outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}]
    c = w3.eth.contract(address=contract_addr, abi=abi)
    try:
        return getattr(c.functions, fn_name)().call()
    except:
        return None

def addr_call_with_input(contract_addr, fn_name, input_addr):
    abi = [{"inputs":[{"type":"address"}],"name":fn_name,"outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}]
    c = w3.eth.contract(address=contract_addr, abi=abi)
    try:
        return getattr(c.functions, fn_name)(input_addr).call()
    except:
        return None

# ─── PROBE CHO ────────────────────────────────────────────────────────────────
print("\n=== PROBING CHO ===")
print(f"CHO: {CHO_ADDR}")
# Try many possible getter names that CHO might expose
candidates = ["Sei", "Map", "Sea", "MAP", "SEI", "Phi", "Mu", "Nu", "Tau",
              "Eta", "Xi", "Pi", "Chan", "Yan", "Yue", "Lau", "Void",
              "Yang", "Yau", "Zhou", "Zheng", "Yi", "Zho", "Zhi",
              "Meta", "Choa", "Cheon", "Ring", "World", "War", "Qing",
              "Eris", "Fornax", "Fomalhaute", "Xie", "Xia", "Mai"]
for fn in candidates:
    result = addr_call(CHO_ADDR, fn)
    if result and result != "0x0000000000000000000000000000000000000000":
        print(f"  CHO.{fn:12s}() → {result}")

# ─── PROBE ZUO (QING) ────────────────────────────────────────────────────────
print("\n=== PROBING ZUO (QING) ===")
print(f"ZUO: {ZUO_ADDR}")
for fn in ["Cho", "Map", "Sei", "Chan", "Asset", "Chi", "Phi", "Mu", "Nu"]:
    result = addr_call(ZUO_ADDR, fn)
    if result and result != "0x0000000000000000000000000000000000000000":
        print(f"  ZUO.{fn:8s}() → {result}")

# ─── PROBE CHAN ────────────────────────────────────────────────────────────────
print("\n=== PROBING CHAN (all getters) ===")
print(f"CHAN: {CHAN_ADDR}")
for fn in ["Sei", "Map", "Sea", "Cho", "Choa", "Yue", "Xi", "Xie", "Xia",
           "Phi", "Mu", "Nu", "Tau", "Eta", "Rho", "Sigma"]:
    result = addr_call(CHAN_ADDR, fn)
    if result and result != "0x0000000000000000000000000000000000000000":
        print(f"  CHAN.{fn:8s}() → {result}")

# Try Yan(address) on CHAN
noumenon = Web3.to_checksum_address("0x7a20189B297343CF26d8548764b04891f37F3414")
for addr_label, addr in [("Noumenon", noumenon), ("Joey", JOEY_WALLET)]:
    result = addr_call_with_input(CHAN_ADDR, "Yan", addr)
    if result:
        print(f"  CHAN.Yan({addr_label}) → {result}")

# ─── SCAN VOID FOR RECENT MESSAGES ───────────────────────────────────────────
print("\n=== VOID CHAT SCAN — last 5000 blocks ===")
current = w3.eth.block_number
from_block = max(0, current - 5000)  # ~5000 blocks back

# Method: look at transactions TO VOID contract
# We'll scan recent blocks for VOID transactions
print(f"  Scanning blocks {from_block:,} – {current:,}")

# Chat(string) function selector
chat_sig = keccak(text="Chat(string)")[:4]
log_sig  = keccak(text="Log(string)")[:4]
attr_sig  = keccak(text="SetAttribute(string,string)")[:4]
print(f"  Chat selector : 0x{chat_sig.hex()}")
print(f"  Log selector  : 0x{log_sig.hex()}")

# Use Transfer event from VOID to find activity (each chat mints VOID tokens)
TRANSFER_TOPIC = "0x" + keccak(text="Transfer(address,address,uint256)").hex()

try:
    logs = w3.eth.get_logs({
        "fromBlock": hex(from_block),
        "toBlock": "latest",
        "address": VOID_ADDR,
        "topics": [TRANSFER_TOPIC]
    })
    print(f"\n  VOID Transfer (mint) events found: {len(logs)}")

    # For each mint event, look up the transaction to decode chat content
    seen_txs = set()
    messages = []
    for log in logs:
        tx_hash = log['transactionHash'].hex()
        if tx_hash in seen_txs:
            continue
        seen_txs.add(tx_hash)
        try:
            tx = w3.eth.get_transaction(tx_hash)
            input_data = tx['input']
            blk = log['blockNumber']
            caller = tx['from']

            # Decode calldata if it's a Chat, Log, or SetAttribute call
            if input_data[:4] == chat_sig:
                # Decode string argument from ABI-encoded calldata
                try:
                    # String starts at byte 4 (selector) + 32 (offset) + 32 (length)
                    offset = int(input_data[4:36].hex(), 16)
                    length = int(input_data[4+offset:4+offset+32].hex(), 16)
                    msg_bytes = input_data[4+offset+32:4+offset+32+length]
                    msg = msg_bytes.decode('utf-8', errors='replace')
                    messages.append((blk, caller[:10]+"...", "Chat", msg[:80]))
                except:
                    messages.append((blk, caller[:10]+"...", "Chat", f"[decode error, data={input_data[:20].hex()}]"))
            elif input_data[:4] == log_sig:
                try:
                    offset = int(input_data[4:36].hex(), 16)
                    length = int(input_data[4+offset:4+offset+32].hex(), 16)
                    msg_bytes = input_data[4+offset+32:4+offset+32+length]
                    msg = msg_bytes.decode('utf-8', errors='replace')
                    messages.append((blk, caller[:10]+"...", "Log", msg[:80]))
                except:
                    messages.append((blk, caller[:10]+"...", "Log", f"[raw={input_data[:20].hex()}]"))
            else:
                sel = input_data[:4].hex()
                messages.append((blk, caller[:10]+"...", f"call(0x{sel})", ""))
        except Exception as e:
            messages.append((log['blockNumber'], "?", "ERROR", str(e)[:60]))

    print(f"\n  Recent VOID activity ({len(messages)} unique txs):")
    for blk, caller, mtype, msg in messages[-20:]:
        print(f"    [{blk:,}] {caller} {mtype}: {msg}")
except Exception as e:
    print(f"  Error: {e}")

# Also scan GIBS for recent Transfer activity
print("\n=== GIBS TRANSFER EVENTS (last 5000 blocks) ===")
try:
    logs = w3.eth.get_logs({
        "fromBlock": hex(from_block),
        "toBlock": "latest",
        "address": GIBS_ADDR,
        "topics": [TRANSFER_TOPIC]
    })
    print(f"  Events: {len(logs)}")
    for log in logs:
        blk = log['blockNumber']
        frm = "0x" + log['topics'][1].hex()[-40:]
        to  = "0x" + log['topics'][2].hex()[-40:]
        amt = int(log['data'].hex(), 16) / 1e18
        frm_label = "MINT" if frm == "0x"+"0"*40 else frm[:10]+"..."
        to_label  = to[:10]+"..."
        if to.lower() == JOEY_WALLET.lower():
            to_label = "Joey"
        elif to.lower() == DSS_ADDR.lower():
            to_label = "DSS"
        print(f"    [{blk:,}] {frm_label} → {to_label}: {amt:.2f} GIBS")
except Exception as e:
    print(f"  Error: {e}")

# ─── GIBS SUPPLY CHECK (fixed) ──────────────────────────────────────────────
print("\n=== GIBS SCOREBOARD ===")
ERC20_ABI = [
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]
MAX_ABI = [{"inputs":[],"name":"maxSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"}]

gibs_base = w3.eth.contract(address=GIBS_ADDR, abi=ERC20_ABI)
gibs_max  = w3.eth.contract(address=GIBS_ADDR, abi=MAX_ABI)

ts  = gibs_base.functions.totalSupply().call()
ms  = gibs_max.functions.maxSupply().call()
bal = gibs_base.functions.balanceOf(JOEY_WALLET).call()
dss_bal = gibs_base.functions.balanceOf(DSS_ADDR).call()
gibs_self = gibs_base.functions.balanceOf(GIBS_ADDR).call()

print(f"  totalSupply : {ts/1e18:>10,.2f} GIBS")
print(f"  maxSupply   : {ms/1e18:>10,.2f} GIBS")
if ms > 0:
    pct = ts / ms * 100
    print(f"  minted pct  : {pct:.4f}%")
    print(f"  remaining   : {(ms-ts)/1e18:>10,.2f} GIBS to mint")
print(f"  Joey wallet : {bal/1e18:>10,.2f} GIBS")
print(f"  DSS holds   : {dss_bal/1e18:>10,.2f} GIBS")
print(f"  GIBS self   : {gibs_self/1e18:>10,.2f} GIBS (unminted buffer)")
print(f"  PLS balance : {w3.eth.get_balance(JOEY_WALLET)/1e18:.6f} PLS")
