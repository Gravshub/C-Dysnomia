#!/usr/bin/env python3
"""
ZUO Ownership Recon — Find who owns ZUO and how to get ZUO tokens.

The Beat call panics because CHOA.Yuan(ZUO) = 0:
  Yuan(ZUO) = ZUO.balanceOf(Joey) + 10*ZUO.balanceOf(GIBS_LAU) + 40*ZUO.balanceOf(Joey_YUE)

PANG.Push(ZUO_WAAT) does:
  Iota = modExp(Iota, ZUO.Entropy(), CHOA.Yuan(ZUO))  -> 0 if Yuan=0
  Omicron = modExp(Omicron, Charge, CHOA.Yuan(ZUO))   -> 0 if Yuan=0

Then Ring.Eta() does: Chao = Chao / Omicron -> div/0 panic.

Fix: Get any ZUO tokens to Joey EOA, GIBS_LAU, or Joey_YUE.

ZUO holds 346 of its own tokens. GWAT=false so Withdraw() is unlocked.
We need to find a ZUO owner or a path to become one.
"""
from web3 import Web3

READ_RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(READ_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}\n")

# ── Addresses ─────────────────────────────────────────────────────────────────
JOEY_EOA    = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_QING   = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
GIBS_LAU    = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
JOEY_YUE    = Web3.to_checksum_address("0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0")
ZUO_QING    = Web3.to_checksum_address("0xb0Ba7D36B7F0505879179ecE7401F24eB653c6E1")
ZUO_TOKEN   = Web3.to_checksum_address("0x583d1C1427308f7f96BFd3E0d7A3F9674D8BF8ec")  # Zürich
CHO_ADDR    = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
MAP_ADDR    = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
CHOA_ADDR   = Web3.to_checksum_address("0x0f5a352fd4cA4850c2099C15B3600ff085B66197")
AFFECTION   = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
META_ADDR   = Web3.to_checksum_address("0xE77Bdae31b2219e032178d88504Cc0170a5b9B97")
SEI_ADDR    = Web3.to_checksum_address("0x3dC54d46e030C42979f33C9992348a990acb6067")
CHAN_ADDR   = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
XIE_ADDR    = Web3.to_checksum_address("0x4Df51741F2926525A21bF63E4769bA70633D2792")
PANG_ADDR   = Web3.to_checksum_address("0xEe25Ccd41671F3B67d660cf6532085586aec8457")
ZI_ADDR     = Web3.to_checksum_address("0xCbAdd3C3957Bd9D6C036863CB053FEccf3D53338")
RING_ADDR   = Web3.to_checksum_address("0x1574c84Ec7fA78fC6C749e1d242dbde163675e72")
QI_ADDR     = Web3.to_checksum_address("0x4d9Ce396BE95dbc5F71808c38107eB7422FD9a03")
ENTEH_QING  = Web3.to_checksum_address("0xA43F71ac277022A547c56706fbBc5d93f88C3467")

# ── ABIs ──────────────────────────────────────────────────────────────────────
OWNER_ABI = [
    {"inputs":[{"name":"cOwner","type":"address"}],"name":"owner",
     "outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Type","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"GWAT","outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"_a","type":"address"}],"name":"GetMarketRate",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Entropy","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Waat","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Asset","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Cho","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"maxSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]

CHOA_ABI = [
    {"inputs":[{"name":"Currency","type":"address"}],"name":"Yuan",
     "outputs":[{"name":"Bae","type":"uint256"}],"stateMutability":"view","type":"function"},
]

def safe_call(contract, func_name, *args, label=""):
    try:
        fn = getattr(contract.functions, func_name)
        result = fn(*args).call()
        return result
    except Exception as e:
        return f"ERROR: {str(e)[:80]}"

def W(amt):
    """Format wei as decimal tokens"""
    if isinstance(amt, str):
        return amt
    return f"{amt / 1e18:.6f}"

# ── Setup contracts ───────────────────────────────────────────────────────────
zuo = w3.eth.contract(address=ZUO_QING, abi=OWNER_ABI)
cho = w3.eth.contract(address=CHO_ADDR, abi=OWNER_ABI)
choa = w3.eth.contract(address=CHOA_ADDR, abi=CHOA_ABI)

print("=" * 65)
print("1. ZUO QING Ownership Check")
print("=" * 65)
candidates = [
    ("Joey EOA",       JOEY_EOA),
    ("GIBS_QING",      GIBS_QING),
    ("GIBS_LAU",       GIBS_LAU),
    ("CHO",            CHO_ADDR),
    ("MAP",            MAP_ADDR),
    ("CHOA",           CHOA_ADDR),
    ("META",           META_ADDR),
    ("SEI",            SEI_ADDR),
    ("CHAN",           CHAN_ADDR),
    ("XIE",            XIE_ADDR),
    ("PANG",           PANG_ADDR),
    ("ZI",             ZI_ADDR),
    ("RING",           RING_ADDR),
    ("QI",             QI_ADDR),
    ("ZUO_TOKEN",      ZUO_TOKEN),   # Zürich itself
    ("ENTEH_QING",     ENTEH_QING),
]
for name, addr in candidates:
    result = safe_call(zuo, "owner", addr)
    print(f"  ZUO.owner({name:12s}) = {result}")

print()
print("=" * 65)
print("2. CHO Contract Ownership Check")
print("=" * 65)
cho_candidates = [
    ("Joey EOA",       JOEY_EOA),
    ("GIBS_QING",      GIBS_QING),
    ("GIBS_LAU",       GIBS_LAU),
    ("ZUO_QING",       ZUO_QING),
    ("MAP",            MAP_ADDR),
    ("CHOA",           CHOA_ADDR),
    ("META",           META_ADDR),
    ("SEI",            SEI_ADDR),
    ("ENTEH_QING",     ENTEH_QING),
]
for name, addr in cho_candidates:
    result = safe_call(cho, "owner", addr)
    print(f"  CHO.owner({name:12s}) = {result}")

print()
print("=" * 65)
print("3. ZUO Token Balances (need > 0 for CHOA.Yuan(ZUO) > 0)")
print("=" * 65)
for name, addr in [("Joey EOA", JOEY_EOA), ("GIBS_LAU", GIBS_LAU), ("Joey YUE", JOEY_YUE), ("ZUO_QING itself", ZUO_QING)]:
    bal = safe_call(zuo, "balanceOf", addr)
    print(f"  ZUO_QING.balanceOf({name}) = {W(bal)}")

print()
print("=" * 65)
print("4. ZUO Market Rates (how to buy ZUO tokens)")
print("=" * 65)
for name, addr in [("AFFECTION", AFFECTION), ("ZUO_TOKEN(Zürich)", ZUO_TOKEN), ("MAP", MAP_ADDR)]:
    rate = safe_call(zuo, "GetMarketRate", addr)
    print(f"  ZUO.GetMarketRate({name}) = {rate}")

print()
print("=" * 65)
print("5. ZUO QING State")
print("=" * 65)
print(f"  ZUO.GWAT       = {safe_call(zuo, 'GWAT')}")
print(f"  ZUO.totalSupply= {W(safe_call(zuo, 'totalSupply'))}")
print(f"  ZUO.maxSupply  = {safe_call(zuo, 'maxSupply')}")
print(f"  ZUO.Entropy    = {safe_call(zuo, 'Entropy')}")
print(f"  ZUO.Asset      = {safe_call(zuo, 'Asset')}")

print()
print("=" * 65)
print("6. Zürich Token State (ZUO_TOKEN)")
print("=" * 65)
# Try V1 DYSNOMIA functions on Zürich
zurich = w3.eth.contract(address=ZUO_TOKEN, abi=OWNER_ABI)
print(f"  Zürich.name()  = {safe_call(zurich, 'name')}")
print(f"  Zürich.totalSupply = {W(safe_call(zurich, 'totalSupply'))}")
print(f"  Zürich.GetMarketRate(AFFECTION) = {safe_call(zurich, 'GetMarketRate', AFFECTION)}")
print(f"  Zürich.balanceOf(ZUO_QING) = {W(safe_call(zurich, 'balanceOf', ZUO_QING))}")
print(f"  Zürich.balanceOf(Joey)     = {W(safe_call(zurich, 'balanceOf', JOEY_EOA))}")

print()
print("=" * 65)
print("7. CHOA.Yuan() Values")
print("=" * 65)
# Yuan uses tx.origin (static call uses msg.sender as tx.origin in eth_call)
print(f"  NOTE: These use w3.from_address=Joey for tx.origin context")
try:
    yuan_zuo = choa.functions.Yuan(ZUO_QING).call({"from": JOEY_EOA})
    print(f"  CHOA.Yuan(ZUO_QING)   = {yuan_zuo}")
except Exception as e:
    print(f"  CHOA.Yuan(ZUO_QING)   = ERROR: {e}")

try:
    yuan_cho = choa.functions.Yuan(CHO_ADDR).call({"from": JOEY_EOA})
    print(f"  CHOA.Yuan(CHO)        = {yuan_cho}")
except Exception as e:
    print(f"  CHOA.Yuan(CHO)        = ERROR: {e}")

print()
print("=" * 65)
print("8. MAP ownership / GetQing lookups")
print("=" * 65)
map_abi = [
    {"inputs":[{"name":"cOwner","type":"address"}],"name":"owner",
     "outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"Waat","type":"uint256"}],"name":"GetQing",
     "outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]
map_contract = w3.eth.contract(address=MAP_ADDR, abi=map_abi)
try:
    zuo_waat = zuo.functions.Waat().call()
    qing_at_waat = map_contract.functions.GetQing(zuo_waat).call()
    print(f"  ZUO.Waat()         = {zuo_waat}")
    print(f"  MAP.GetQing(ZUO.Waat()) = {qing_at_waat}")
    print(f"  == ZUO_QING?       = {qing_at_waat.lower() == ZUO_QING.lower()}")
except Exception as e:
    print(f"  ERROR: {e}")

print()
print("=" * 65)
print("9. CHO owners: check all known QING addresses as potential CHO owners")
print("=" * 65)
# CHO.addOwner(Mu) is called for each QING created by MAP
# So we need to find other QING addresses
other_qings = [
    ("ZUO_QING",   ZUO_QING),
    ("ENTEH_QING", ENTEH_QING),
    ("GIBS_QING",  GIBS_QING),
]
for name, addr in other_qings:
    result = safe_call(cho, "owner", addr)
    print(f"  CHO.owner({name}) = {result}")

print()
print("Done.")
