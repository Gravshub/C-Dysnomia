#!/usr/bin/env python3
"""
Full Beat diagnostic - check ALL potential panic points.

Panic trace for Ring.Eta():
  1. Yue.React(ZUO) - onlyOwners check
  2. Pang.Push(ZUO_WAAT):
     - (Charge, Omicron, Omega) = XIE.Power(ZUO_WAAT)
       - Omicron = Fornax.balOf(GIBS_LAU) / GIBS_LAU.Entropy    <- needs non-zero
       - Omega   = Fornax.balOf(ZUO_QING) / ZUO_QING.Entropy    <- needs non-zero!
       - Charge  = XIA.Charge(ZUO_WAAT)                          <- check
     - Omicron = modExp(Omicron, Charge, Yuan(ZUO))  <- needs Yuan(ZUO)>0
     - Iota    = modExp(Iota, ZUO.Entropy, Yuan(ZUO)) <- needs Yuan(ZUO)>0
  3. Chao = Chao / Omicron  <- panics if Omicron=0
  4. Charge = Charge / Omega <- panics if Omega=0
  5. Iota1 = Iota^2          <- 0 if Iota=0

  Then Beat:
  6. Charge = Charge1 * Charge2 / Iota1  <- panics if Iota1=0
  7. Yeo = Yeo / Chao                    <- panics if Chao=0
"""
from web3 import Web3

READ_RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(READ_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}\n")

JOEY_EOA   = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_QING  = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
GIBS_LAU   = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
JOEY_YUE   = Web3.to_checksum_address("0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0")
ZUO_QING   = Web3.to_checksum_address("0xb0Ba7D36B7F0505879179ecE7401F24eB653c6E1")
ZUO_TOKEN  = Web3.to_checksum_address("0x583d1C1427308f7f96BFd3E0d7A3F9674D8BF8ec")
CHO_ADDR   = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
CHOA_ADDR  = Web3.to_checksum_address("0x0f5a352fd4cA4850c2099C15B3600ff085B66197")
META_ADDR  = Web3.to_checksum_address("0xE77Bdae31b2219e032178d88504Cc0170a5b9B97")
RING_ADDR  = Web3.to_checksum_address("0x1574c84Ec7fA78fC6C749e1d242dbde163675e72")
PANG_ADDR  = Web3.to_checksum_address("0xEe25Ccd41671F3B67d660cf6532085586aec8457")
XIE_ADDR   = Web3.to_checksum_address("0x4Df51741F2926525A21bF63E4769bA70633D2792")
SEI_ADDR   = Web3.to_checksum_address("0x3dC54d46e030C42979f33C9992348a990acb6067")
FORNAX     = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
FOMALHAUTE = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")
AFFECTION  = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")

BASIC_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"cOwner","type":"address"}],"name":"owner",
     "outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Entropy","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Waat","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"_a","type":"address"}],"name":"GetMarketRate",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]

XIE_ABI = [
    {"inputs":[{"name":"QingWaat","type":"uint256"}],"name":"Power",
     "outputs":[{"name":"Charge","type":"uint256"},{"name":"Omicron","type":"uint256"},
                {"name":"Omega","type":"uint256"}],"stateMutability":"nonpayable","type":"function"},
]

CHOA_ABI = [
    {"inputs":[{"name":"Currency","type":"address"}],"name":"Yuan",
     "outputs":[{"name":"Bae","type":"uint256"}],"stateMutability":"view","type":"function"},
]

META_ABI = [
    {"inputs":[{"name":"QingWaat","type":"uint256"}],"name":"Beat",
     "outputs":[{"name":"Dione","type":"uint256"},{"name":"Charge","type":"uint256"},
                {"name":"Deimos","type":"uint256"},{"name":"Yeo","type":"uint256"}],
     "stateMutability":"nonpayable","type":"function"},
]

def W(v): return f"{v/1e18:.8f}" if isinstance(v, int) else str(v)
def safe(fn, *args, **kwargs):
    try: return fn(*args, **kwargs)
    except Exception as e: return f"ERR: {str(e)[:60]}"

zuo_q  = w3.eth.contract(address=ZUO_QING, abi=BASIC_ABI)
fornax = w3.eth.contract(address=FORNAX,    abi=BASIC_ABI)
choa   = w3.eth.contract(address=CHOA_ADDR, abi=CHOA_ABI)
xie    = w3.eth.contract(address=XIE_ADDR,  abi=XIE_ABI)
yue    = w3.eth.contract(address=JOEY_YUE,  abi=BASIC_ABI)
meta   = w3.eth.contract(address=META_ADDR, abi=META_ABI)
cho    = w3.eth.contract(address=CHO_ADDR,  abi=BASIC_ABI)

GIBS_QING_WAAT = 251913148994206487765525643443518492465195287520927385378321984475167864513
ZUO_WAAT = zuo_q.functions.Waat().call()

print("=" * 65)
print("1. Joey_YUE Ownership (why Yue.React() doesn't fail)")
print("=" * 65)
for name, addr in [
    ("SEI",      SEI_ADDR),
    ("CHAN",      "0xe250bf9729076B14A8399794B61C72d0F4AeFcd8"),
    ("RING",     RING_ADDR),
    ("Joey_EOA", JOEY_EOA),
    ("META",     META_ADDR),
    ("PANG",     PANG_ADDR),
    ("CHO",      CHO_ADDR),
]:
    r = safe(yue.functions.owner(Web3.to_checksum_address(addr)).call)
    print(f"  Joey_YUE.owner({name:10s}) = {r}")

print()
print("=" * 65)
print("2. Fornax balances at ALL potential Qing addresses (for XIE.Power)")
print("=" * 65)
# XIE.Power(QingWaat) calls:
# Omega = Fornax.balOf(Qing) / Qing.Entropy()
# where Qing = GetQing(QingWaat)
for name, addr in [
    ("GIBS_LAU",       GIBS_LAU),   # Alpha.On.Phi (Omicron)
    ("ZUO_QING",       ZUO_QING),   # when Push(ZUO_WAAT), Qing=ZUO -> Omega
    ("GIBS_QING",      GIBS_QING),  # when Push(GIBS_QING_WAAT), Qing=GIBS_QING -> Omega
    ("Joey_EOA",       JOEY_EOA),
]:
    b = safe(fornax.functions.balanceOf(Web3.to_checksum_address(addr)).call)
    print(f"  Fornax.balOf({name:12s}) = {W(b)}")

print()
print("=" * 65)
print("3. ZUO_QING Entropy")
print("=" * 65)
zuo_entropy = safe(zuo_q.functions.Entropy().call)
gibs_entropy_abi = [{"inputs":[],"name":"Entropy","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"}]
gibs = w3.eth.contract(address=GIBS_QING, abi=gibs_entropy_abi)
gibs_entropy = safe(gibs.functions.Entropy().call)
gibs_lau_abi = [{"inputs":[],"name":"Entropy","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"}]
lau = w3.eth.contract(address=GIBS_LAU, abi=gibs_lau_abi)
# LAU has Saat(1) not Entropy
print(f"  ZUO_QING.Entropy = {zuo_entropy}")
print(f"  GIBS_QING.Entropy = {gibs_entropy}")

print()
print("=" * 65)
print("4. XIE.Power() for ZUO_WAAT and GIBS_QING_WAAT (static call)")
print("=" * 65)
for name, waat in [("ZUO_WAAT", ZUO_WAAT), ("GIBS_QING_WAAT", GIBS_QING_WAAT)]:
    try:
        result = xie.functions.Power(waat).call({"from": JOEY_EOA})
        print(f"  XIE.Power({name}): Charge={result[0]}, Omicron={result[1]}, Omega={result[2]}")
        if result[2] == 0:
            print(f"    WARNING: Omega=0! Ring.Eta() will panic at Charge/Omega!")
    except Exception as e:
        print(f"  XIE.Power({name}): ERR: {str(e)[:80]}")

print()
print("=" * 65)
print("5. CHOA.Yuan() for ZUO and GIBS_QING")
print("=" * 65)
for name, addr in [("ZUO_QING", ZUO_QING), ("GIBS_QING", GIBS_QING)]:
    try:
        y = choa.functions.Yuan(addr).call({"from": JOEY_EOA})
        print(f"  Yuan({name}) = {y}")
        if y == 0:
            print(f"    WARNING: Yuan=0! modExp returns 0 -> div/0 downstream!")
    except Exception as e:
        print(f"  Yuan({name}): ERR: {str(e)[:80]}")

print()
print("=" * 65)
print("6. Current Beat dry-run error")
print("=" * 65)
try:
    result = meta.functions.Beat(GIBS_QING_WAAT).call({"from": JOEY_EOA})
    print(f"  Beat SUCCESS: {result}")
except Exception as e:
    print(f"  Beat FAILS: {str(e)[:120]}")

print()
print("=" * 65)
print("7. Fix requirements summary")
print("=" * 65)

zuo_bal_joey = safe(zuo_q.functions.balanceOf(JOEY_EOA).call)
fornax_zuo = safe(fornax.functions.balanceOf(ZUO_QING).call)
fornax_gibs = safe(fornax.functions.balanceOf(GIBS_QING).call)

print(f"  ZUO at Joey_EOA      = {W(zuo_bal_joey)}")
print(f"  Fornax at ZUO_QING   = {W(fornax_zuo)}")
print(f"  Fornax at GIBS_QING  = {W(fornax_gibs)}")
print()
if isinstance(zuo_bal_joey, int) and zuo_bal_joey == 0:
    print("  NEED: ZUO tokens at Joey_EOA (buy via Zürich)")
if isinstance(fornax_zuo, int) and fornax_zuo == 0:
    print("  NEED: Fornax tokens at ZUO_QING (transfer from Joey_EOA or GIBS_LAU)")

print()
print("  Acquisition path:")
print("  1. Swap WPLS->Zürich on PulseX V1 (pair exists!)")
print("     Rate: 1 WPLS -> ~0.1648 Zürich")
print("     Need: ~1000 Zürich -> costs ~6070 WPLS")
print("  2. ZUO_QING.Purchase(Zürich, 0.001e18) -> ~1907 Zürich for 0.001907 ZUO")
print("  3. If Fornax at ZUO_QING = 0:")
print("     Transfer some Fornax from Joey_EOA/GIBS_LAU to ZUO_QING")
print("     (Joey has GIBS_LAU.Fornax=0.15 available)")
print("     But only an owner can withdraw Fornax from GIBS_LAU...")
print("     Alternative: Buy Fornax from enteh QING and send directly to ZUO_QING")
