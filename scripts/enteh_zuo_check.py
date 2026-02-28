#!/usr/bin/env python3
"""Check enteh's ZUO/Zürich balances to understand how they bypass Yuan(ZUO)=0"""
from web3 import Web3

READ_RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(READ_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}\n")

ENTEH_EOA   = Web3.to_checksum_address("0xccE83CfF8B531EaDdcf11AB414C59DC046D1aAc7")
JOEY_EOA    = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
CHO_ADDR    = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
CHAN_ADDR   = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
ZUO_QING    = Web3.to_checksum_address("0xb0Ba7D36B7F0505879179ecE7401F24eB653c6E1")
ZUO_TOKEN   = Web3.to_checksum_address("0x583d1C1427308f7f96BFd3E0d7A3F9674D8BF8ec")  # Zürich
CHOA_ADDR   = Web3.to_checksum_address("0x0f5a352fd4cA4850c2099C15B3600ff085B66197")
FORNAX      = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
FOMALHAUTE  = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")
GIBS_LAU    = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
JOEY_YUE    = Web3.to_checksum_address("0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0")
GIBS_QING   = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")

BASIC_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
]
CHO_ABI = [
    {"inputs":[{"name":"","type":"address"}],"name":"GetUserTokenAddress",
     "outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]
CHAN_ABI = [
    {"inputs":[{"name":"","type":"address"}],"name":"Yan",
     "outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]
CHOA_ABI = [
    {"inputs":[{"name":"Currency","type":"address"}],"name":"Yuan",
     "outputs":[{"name":"Bae","type":"uint256"}],"stateMutability":"view","type":"function"},
]

cho = w3.eth.contract(address=CHO_ADDR, abi=CHO_ABI)
chan = w3.eth.contract(address=CHAN_ADDR, abi=CHAN_ABI)
choa = w3.eth.contract(address=CHOA_ADDR, abi=CHOA_ABI)
zuo = w3.eth.contract(address=ZUO_QING, abi=BASIC_ABI)
zurich = w3.eth.contract(address=ZUO_TOKEN, abi=BASIC_ABI)

def W(v): return f"{v/1e18:.6f}" if isinstance(v,int) else str(v)

# Get enteh's LAU and YUE
try:
    enteh_lau = cho.functions.GetUserTokenAddress(ENTEH_EOA).call()
    print(f"enteh LAU: {enteh_lau}")
except Exception as e:
    enteh_lau = None
    print(f"enteh LAU: {e}")

try:
    enteh_yue = chan.functions.Yan(ENTEH_EOA).call()
    print(f"enteh YUE: {enteh_yue}")
except Exception as e:
    enteh_yue = None
    print(f"enteh YUE: {e}")

print()
print("=" * 65)
print("ZUO Balances:")
print("=" * 65)

# Check ZUO balances for enteh's sphere
for name, addr in [
    ("enteh EOA",  ENTEH_EOA),
    ("enteh LAU",  enteh_lau),
    ("enteh YUE",  enteh_yue),
    ("Joey EOA",   JOEY_EOA),
    ("GIBS_LAU",   GIBS_LAU),
    ("Joey YUE",   JOEY_YUE),
    ("GIBS_QING",  GIBS_QING),
    ("ZUO_QING",   ZUO_QING),
]:
    if addr and addr != "0x0000000000000000000000000000000000000000":
        try:
            b = zuo.functions.balanceOf(Web3.to_checksum_address(addr)).call()
            print(f"  ZUO.balOf({name:12s}) = {W(b)}")
        except Exception as e:
            print(f"  ZUO.balOf({name:12s}) = ERROR: {e}")

print()
print("=" * 65)
print("Zürich Balances:")
print("=" * 65)
for name, addr in [
    ("enteh EOA",  ENTEH_EOA),
    ("enteh LAU",  enteh_lau),
    ("enteh YUE",  enteh_yue),
    ("Joey EOA",   JOEY_EOA),
    ("GIBS_LAU",   GIBS_LAU),
    ("ZUO_QING",   ZUO_QING),
]:
    if addr and addr != "0x0000000000000000000000000000000000000000":
        try:
            b = zurich.functions.balanceOf(Web3.to_checksum_address(addr)).call()
            print(f"  Zürich.balOf({name:12s}) = {W(b)}")
        except Exception as e:
            print(f"  Zürich.balOf({name:12s}) = ERROR: {e}")

print()
print("=" * 65)
print("CHOA.Yuan(ZUO) for enteh vs Joey:")
print("=" * 65)
for name, addr in [("Joey", JOEY_EOA), ("enteh", ENTEH_EOA)]:
    try:
        yuan = choa.functions.Yuan(ZUO_QING).call({"from": addr})
        print(f"  CHOA.Yuan(ZUO, from={name}) = {yuan}")
    except Exception as e:
        print(f"  CHOA.Yuan(ZUO, from={name}) = ERROR: {e}")

print()
print("=" * 65)
print("SHIO Balances at GIBS_LAU and GIBS_QING (current state):")
print("=" * 65)
for tok_name, tok_addr in [("Fornax", FORNAX), ("Fomalhaute", FOMALHAUTE), ("CHO", CHO_ADDR)]:
    tok = w3.eth.contract(address=tok_addr, abi=BASIC_ABI)
    for place_name, place_addr in [("GIBS_LAU", GIBS_LAU), ("GIBS_QING", GIBS_QING), ("Joey_EOA", JOEY_EOA), ("Joey_YUE", JOEY_YUE)]:
        try:
            b = tok.functions.balanceOf(place_addr).call()
            print(f"  {tok_name}.balOf({place_name:12s}) = {W(b)}")
        except Exception as e:
            print(f"  {tok_name}.balOf({place_name:12s}) = ERR: {e}")
    print()

print()
print("=" * 65)
print("Beat dry-run:")
print("=" * 65)
GIBS_QING_WAAT = 251913148994206487765525643443518492465195287520927385378321984475167864513
META_ADDR = Web3.to_checksum_address("0xE77Bdae31b2219e032178d88504Cc0170a5b9B97")
meta_abi = [
    {"inputs":[{"name":"QingWaat","type":"uint256"}],"name":"Beat",
     "outputs":[{"name":"Dione","type":"uint256"},{"name":"Charge","type":"uint256"},
                {"name":"Deimos","type":"uint256"},{"name":"Yeo","type":"uint256"}],
     "stateMutability":"nonpayable","type":"function"},
]
meta = w3.eth.contract(address=META_ADDR, abi=meta_abi)
try:
    result = meta.functions.Beat(GIBS_QING_WAAT).call({"from": JOEY_EOA})
    print(f"  Beat() SUCCESS: {result}")
except Exception as e:
    print(f"  Beat() STILL FAILS: {str(e)[:120]}")
