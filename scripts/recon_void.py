#!/usr/bin/env python3
"""
Scan VOID for recent chat messages and discover SEI/MAP addresses.
"""
from web3 import Web3
import json

RPC = "https://rpc.pulsechainstats.com"
w3 = Web3(Web3.HTTPProvider(RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# Known addresses
VOID_ADDR    = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")
ZHOU_ADDR    = Web3.to_checksum_address("0x5cc318d0c01fed5942b5ed2f53db07727d36e261")
GIBS_ADDR    = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
YANG_ADDR    = Web3.to_checksum_address("0xb702b3ec6d9de1011be963efe30a28b6ddfbe011")
YAU_ADDR     = Web3.to_checksum_address("0x7e91d862a346659daeed93726e733c8c1347a225")
NOUMENON_YUE = Web3.to_checksum_address("0x935a694377cf48d8fc934f17db289774f0ce7075")
JOEY_WALLET  = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

# Generic address getter ABI
ADDR_ABI = [{"inputs":[],"name":"","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]

def addr_call(contract_addr, fn_name):
    abi = [{"inputs":[],"name":fn_name,"outputs":[{"internalType":"address","name":"","type":"address"}],"stateMutability":"view","type":"function"}]
    c = w3.eth.contract(address=contract_addr, abi=abi)
    try:
        return getattr(c.functions, fn_name)().call()
    except Exception as e:
        return f"ERROR: {e}"

def uint64_call(contract_addr, fn_name):
    abi = [{"inputs":[],"name":fn_name,"outputs":[{"internalType":"uint64","name":"","type":"uint64"}],"stateMutability":"view","type":"function"}]
    c = w3.eth.contract(address=contract_addr, abi=abi)
    try:
        return getattr(c.functions, fn_name)().call()
    except Exception as e:
        return f"ERROR: {e}"

def uint256_call(contract_addr, fn_name):
    abi = [{"inputs":[],"name":fn_name,"outputs":[{"internalType":"uint256","name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]
    c = w3.eth.contract(address=contract_addr, abi=abi)
    try:
        return getattr(c.functions, fn_name)().call()
    except Exception as e:
        return f"ERROR: {e}"

# ─── TOKEN SCOREBOARD ───────────────────────────────────────────────────────
print("\n=== TOKEN SCOREBOARD ===")
ERC20_ABI = [
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"symbol","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"maxSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]
tokens = {
    "GIBS":      GIBS_ADDR,
    "VOID":      VOID_ADDR,
    "ZHOU":      ZHOU_ADDR,
}
for tname, taddr in tokens.items():
    c = w3.eth.contract(address=taddr, abi=ERC20_ABI)
    try:
        ts = c.functions.totalSupply().call() / 1e18
        bal = c.functions.balanceOf(JOEY_WALLET).call() / 1e18
        try:
            ms = c.functions.maxSupply().call() / 1e18
            pct = (c.functions.totalSupply().call() / c.functions.maxSupply().call()) * 100
            print(f"  {tname:10s}  totalSupply={ts:>12,.2f}  maxSupply={ms:>12,.2f}  ({pct:.1f}%)  Joey={bal:,.2f}")
        except:
            print(f"  {tname:10s}  totalSupply={ts:>12,.2f}  Joey={bal:,.2f}")
    except Exception as e:
        print(f"  {tname}: ERROR {e}")

pls_balance = w3.eth.get_balance(JOEY_WALLET) / 1e18
print(f"  {'PLS(gas)':10s}  wallet={pls_balance:.6f} PLS")

# ─── VOID CHAT SCAN ─────────────────────────────────────────────────────────
print("\n=== RECENT VOID CHAT (last 500 blocks) ===")
current = w3.eth.block_number
from_block = current - 500

# Chat(string) selector: keccak256("Chat(string)")[:4]
from eth_utils import keccak
chat_sel = keccak(text="Chat(string)")[:4].hex()
log_sel  = keccak(text="Log(string)")[:4].hex()
print(f"  Scanning blocks {from_block:,} – {current:,}")
print(f"  Chat selector: 0x{chat_sel}  Log selector: 0x{log_sel}")

try:
    # Get all txs TO VOID in range — use getLogs on Transfer event as proxy
    # since direct tx scan isn't available; fall back to checking known GIBS transfer events
    TRANSFER_TOPIC = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
    logs = w3.eth.get_logs({
        "fromBlock": from_block,
        "toBlock": "latest",
        "address": GIBS_ADDR,  # GIBS Transfer events = mint activity
        "topics": [TRANSFER_TOPIC]
    })
    print(f"  GIBS Transfer events: {len(logs)}")
    for log in logs[-10:]:
        blk = log['blockNumber']
        frm = "0x" + log['topics'][1].hex()[-40:]
        to  = "0x" + log['topics'][2].hex()[-40:]
        amt = int(log['data'].hex(), 16) / 1e18 if log['data'] else 0
        print(f"    block={blk:,}  from={frm[:10]}...  to={to[:10]}...  amount={amt:.2f} GIBS")
except Exception as e:
    print(f"  Error scanning GIBS logs: {e}")

# Try to read recent transactions to VOID to find Chat calls
print("\n  Scanning recent VOID transactions for Chat() calls...")
try:
    latest = w3.eth.get_block('latest', full_transactions=True)
    void_txs = [tx for tx in latest['transactions'] if tx.get('to') and tx['to'].lower() == VOID_ADDR.lower()]
    print(f"  VOID txs in latest block: {len(void_txs)}")
except Exception as e:
    print(f"  {e}")

# ─── ADDRESS DISCOVERY ───────────────────────────────────────────────────────
print("\n=== ADDRESS DISCOVERY ===")

# Step 1: Get CHAN from Noumenon's YUE
print(f"\nNoumenon YUE: {NOUMENON_YUE}")
chan = addr_call(NOUMENON_YUE, "Chan")
print(f"  .Chan()   → {chan}")

if "ERROR" not in str(chan):
    chan_addr = Web3.to_checksum_address(chan)

    # Step 2: Get XIE from CHAN
    xie = addr_call(chan_addr, "Xie")
    print(f"\nCHAN: {chan_addr}")
    print(f"  .Xie()    → {xie}")

    if "ERROR" not in str(xie):
        xie_addr = Web3.to_checksum_address(xie)

        # Step 3: XIA from XIE
        xia = addr_call(xie_addr, "Xia")
        print(f"\nXIE: {xie_addr}")
        print(f"  .Xia()    → {xia}")

        if "ERROR" not in str(xia):
            xia_addr = Web3.to_checksum_address(xia)

            mai = addr_call(xia_addr, "Mai")
            print(f"\nXIA: {xia_addr}")
            print(f"  .Mai()    → {mai}")

            if "ERROR" not in str(mai):
                mai_addr = Web3.to_checksum_address(mai)

                qi = addr_call(mai_addr, "Qi")
                print(f"\nMAI: {mai_addr}")
                print(f"  .Qi()     → {qi}")

                if "ERROR" not in str(qi):
                    qi_addr = Web3.to_checksum_address(qi)

                    zuo = addr_call(qi_addr, "Zuo")
                    print(f"\nQI: {qi_addr}")
                    print(f"  .Zuo()    → {zuo}")

                    if "ERROR" not in str(zuo):
                        zuo_addr = Web3.to_checksum_address(zuo)

                        cho = addr_call(zuo_addr, "Cho")
                        print(f"\nZUO: {zuo_addr}")
                        print(f"  .Cho()    → {cho}")

# Try to find SEI from CHAN (check if CHAN.Sei() exists)
if "ERROR" not in str(chan):
    chan_addr = Web3.to_checksum_address(chan)
    print(f"\n--- Probing CHAN for SEI/related getters ---")
    for fn in ["Sei", "SEI", "Yan", "Sea", "Map", "Cho", "Xia", "Xi"]:
        result = addr_call(chan_addr, fn)
        print(f"  CHAN.{fn:5s}() → {result}")

# Probe YANG for MAP
print(f"\n--- Probing YANG for MAP/SEI ---")
for fn in ["Map", "Sea", "Sei", "Cho", "Chan", "Phi", "Mu"]:
    result = addr_call(YANG_ADDR, fn)
    print(f"  YANG.{fn:5s}() → {result}")

# Probe YAU
print(f"\n--- Probing YAU ---")
for fn in ["Tau", "Map", "Sei", "Chan", "Phi"]:
    result = addr_call(YAU_ADDR, fn)
    print(f"  YAU.{fn:5s}() → {result}")

# Check if Joey's GIBS has CHO registered (GIBS.Eta() = VOID; VOID might have CHO)
print(f"\n--- Probing VOID for CHO/SEI/MAP ---")
for fn in ["Cho", "Chan", "Sei", "Map", "Nu", "Phi", "Mu"]:
    result = addr_call(VOID_ADDR, fn)
    print(f"  VOID.{fn:5s}() → {result}")

# ─── GIBS STATE ──────────────────────────────────────────────────────────────
print("\n=== GIBS LAU STATE ===")
GIBS_ABI_EXT = ERC20_ABI + [
    {"inputs":[],"name":"maxSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Eta","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"On","outputs":[{"components":[{"type":"address","name":"Phi"},{"type":"address","name":"Mu"},{"type":"uint64","name":"Xi"},{"type":"uint64","name":"Pi"},{"type":"address","name":"Shio"},{"type":"uint64","name":"Ring"},{"type":"uint64","name":"Omicron"},{"type":"uint64","name":"Omega"}],"type":"tuple"}],"stateMutability":"view","type":"function"},
]
gibs = w3.eth.contract(address=GIBS_ADDR, abi=GIBS_ABI_EXT)
try:
    ts = gibs.functions.totalSupply().call()
    ms = gibs.functions.maxSupply().call()
    bal = gibs.functions.balanceOf(JOEY_WALLET).call()
    pct = (ts / ms * 100) if ms > 0 else 0
    print(f"  totalSupply : {ts/1e18:,.2f} GIBS")
    print(f"  maxSupply   : {ms/1e18:,.2f} GIBS")
    print(f"  minted pct  : {pct:.2f}%")
    print(f"  Joey wallet : {bal/1e18:,.2f} GIBS")
    remaining = (ms - ts) / 1e18
    print(f"  to mint     : {remaining:,.2f} GIBS remaining")
except Exception as e:
    print(f"  ERROR: {e}")
