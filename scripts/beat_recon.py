#!/usr/bin/env python3
"""
BEAT Reconnaissance — Read-only dry-run of META.Beat() for GIBS QING.

Reads on-chain state and simulates Beat via .call() without sending a tx.
Returns: Dione, Charge, Deimos, Yeo (territory range + power metrics).

Call chain (from META.Beat):
  META.Beat(QingWaat)
    -> Ring.Pang().Zi().Choa().Sei().Chan().Xie().Xia().Mai().Qi().Zuo().GetQing(QingWaat)
    -> Ring.Eta()  (returns Phoebe, Iota, Chao, Charge via RING)
    -> Ring.Pang().Push(QingWaat)  (returns Yeo, Omicron, Dione, Omega, Charge)
    -> Xiao.modExp(Dione, Phoebe, Yuan(Qing))  => Deimos
    -> Yeo = Yeo / Chao

Game loop context:
  CHEON.Su()  ->  META.Beat()  ->  WORLD.Code()  ->  GWAT()
"""
from web3 import Web3
import sys

# ── RPC ──────────────────────────────────────────────────────────────────────
READ_RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(READ_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# ── Addresses ────────────────────────────────────────────────────────────────
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_QING   = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
GIBS_LAU    = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
META_ADDR   = Web3.to_checksum_address("0xE77Bdae31b2219e032178d88504Cc0170a5b9B97")
RING_ADDR   = Web3.to_checksum_address("0x1574c84Ec7fA78fC6C749e1d242dbde163675e72")
PANG_ADDR   = Web3.to_checksum_address("0xEe25Ccd41671F3B67d660cf6532085586aec8457")
CHEON_ADDR  = Web3.to_checksum_address("0x3d23084cA3F40465553797b5138CFC456E61FB5D")
HECKE_ADDR  = Web3.to_checksum_address("0x29A924D9B0233026B9844f2aFeB202F1791D7593")
MAP_ADDR    = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
SEI_ADDR    = Web3.to_checksum_address("0x3dC54d46e030C42979f33C9992348a990acb6067")
JOEY_YUE    = Web3.to_checksum_address("0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0")

# ── ABIs ─────────────────────────────────────────────────────────────────────
QING_ABI = [
    {"inputs":[],"name":"Waat","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Entropy","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Asset","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"symbol","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"GWAT","outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"CoverCharge","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]

META_ABI = [
    {"inputs":[],"name":"Ring","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Type","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"QingWaat","type":"uint256"}],"name":"Beat",
     "outputs":[{"name":"Dione","type":"uint256"},{"name":"Charge","type":"uint256"},
                {"name":"Deimos","type":"uint256"},{"name":"Yeo","type":"uint256"}],
     "stateMutability":"nonpayable","type":"function"},
]

RING_ABI = [
    {"inputs":[],"name":"Pang","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"","type":"uint64"}],"name":"Moments","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Eta",
     "outputs":[{"name":"Phoebe","type":"uint256"},{"name":"Iota","type":"uint256"},
                {"name":"Chao","type":"uint256"},{"name":"Charge","type":"uint256"}],
     "stateMutability":"nonpayable","type":"function"},
]

HECKE_ABI = [
    {"inputs":[{"name":"Waat","type":"uint256"}],"name":"Compliment",
     "outputs":[{"name":"Longitude","type":"int256"},{"name":"Latitude","type":"int256"}],
     "stateMutability":"view","type":"function"},
    {"inputs":[{"name":"Waat","type":"uint256"}],"name":"GetMeridian",
     "outputs":[{"name":"Meridian","type":"uint256"}],
     "stateMutability":"view","type":"function"},
]

CHEON_ABI = [
    {"inputs":[],"name":"Sei","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"Qing","type":"address"}],"name":"Su",
     "outputs":[{"name":"Charge","type":"uint256"},{"name":"Hypobar","type":"uint256"},
                {"name":"Epibar","type":"uint256"}],
     "stateMutability":"nonpayable","type":"function"},
]

PANG_ABI = [
    {"inputs":[],"name":"Zi","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"QingWaat","type":"uint256"}],"name":"Push",
     "outputs":[{"name":"Iota","type":"uint256"},{"name":"Omicron","type":"uint256"},
                {"name":"Eta","type":"uint256"},{"name":"Omega","type":"uint256"},
                {"name":"Charge","type":"uint256"}],
     "stateMutability":"nonpayable","type":"function"},
]

LAU_ABI = [
    {"inputs":[{"name":"","type":"uint256"}],"name":"Saat","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Username","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
]

ERC20_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]

# ── Contract instances ───────────────────────────────────────────────────────
gibs_qing = w3.eth.contract(address=GIBS_QING, abi=QING_ABI)
meta      = w3.eth.contract(address=META_ADDR, abi=META_ABI)
ring      = w3.eth.contract(address=RING_ADDR, abi=RING_ABI)
hecke     = w3.eth.contract(address=HECKE_ADDR, abi=HECKE_ABI)
cheon     = w3.eth.contract(address=CHEON_ADDR, abi=CHEON_ABI)
pang      = w3.eth.contract(address=PANG_ADDR, abi=PANG_ABI)
gibs_lau  = w3.eth.contract(address=GIBS_LAU, abi=LAU_ABI)
meta_erc  = w3.eth.contract(address=META_ADDR, abi=ERC20_ABI)

# ═════════════════════════════════════════════════════════════════════════════
# STEP 1: Read GIBS QING state
# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "="*72)
print("  STEP 1: GIBS QING On-Chain State")
print("="*72)

waat = gibs_qing.functions.Waat().call()
entropy = gibs_qing.functions.Entropy().call()
asset = gibs_qing.functions.Asset().call()
qing_name = gibs_qing.functions.name().call()
qing_supply = gibs_qing.functions.totalSupply().call()
gwat_flag = gibs_qing.functions.GWAT().call()
cover = gibs_qing.functions.CoverCharge().call()

print(f"  Name:         {qing_name}")
print(f"  Waat:         {waat}")
print(f"  Entropy:      {entropy}")
print(f"  Asset:        {asset}")
print(f"  Total Supply: {qing_supply / 1e18:,.0f}")
print(f"  GWAT flag:    {gwat_flag}")
print(f"  Cover Charge: {cover / 1e18:.0f}")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 2: Verify META contract
# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "="*72)
print("  STEP 2: META Contract Verification")
print("="*72)

meta_name  = meta.functions.name().call()
meta_type  = meta.functions.Type().call()
meta_ring  = meta.functions.Ring().call()
meta_supply = meta.functions.totalSupply().call()

print(f"  Name:          {meta_name}")
print(f"  Type:          {meta_type}")
print(f"  Total Supply:  {meta_supply / 1e18:,.0f}")
print(f"  Ring address:  {meta_ring}")
ring_match = meta_ring.lower() == RING_ADDR.lower()
print(f"  Ring matches:  {'YES' if ring_match else 'NO *** MISMATCH ***'}")
if not ring_match:
    print(f"    Expected: {RING_ADDR}")
    print(f"    Got:      {meta_ring}")

# Verify RING -> PANG chain
ring_pang = ring.functions.Pang().call()
pang_match = ring_pang.lower() == PANG_ADDR.lower()
print(f"  RING.Pang():   {ring_pang}")
print(f"  Pang matches:  {'YES' if pang_match else 'NO *** MISMATCH ***'}")

# Verify CHEON -> SEI chain
cheon_sei = cheon.functions.Sei().call()
sei_match = cheon_sei.lower() == SEI_ADDR.lower()
print(f"  CHEON.Sei():   {cheon_sei}")
print(f"  SEI matches:   {'YES' if sei_match else 'NO *** MISMATCH ***'}")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 3: HECKE coordinates for GIBS QING
# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "="*72)
print("  STEP 3: GIBS QING Hecke Coordinates")
print("="*72)

try:
    (longitude, latitude) = hecke.functions.Compliment(waat).call()
    meridian = hecke.functions.GetMeridian(waat).call()
    print(f"  Latitude:   {latitude}")
    print(f"  Longitude:  {longitude}")
    print(f"  Meridian:   {meridian}")
except Exception as e:
    print(f"  Error reading coordinates: {e}")
    latitude, longitude, meridian = None, None, None

# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: Joey's player state
# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "="*72)
print("  STEP 4: Joey's Player State")
print("="*72)

try:
    joey_username = gibs_lau.functions.Username().call()
    joey_soul = gibs_lau.functions.Saat(1).call()
    joey_aura = gibs_lau.functions.Saat(2).call()
    joey_meta_bal = meta_erc.functions.balanceOf(JOEY_WALLET).call()
    joey_meta_yue = meta_erc.functions.balanceOf(JOEY_YUE).call()
    joey_pls = w3.eth.get_balance(JOEY_WALLET)
    print(f"  Username:     {joey_username}")
    print(f"  Soul (Saat1): {joey_soul}")
    print(f"  Aura (Saat2): {joey_aura}")
    print(f"  META balance: {joey_meta_bal / 1e18:.4f} (wallet)")
    print(f"  META in YUE:  {joey_meta_yue / 1e18:.4f}")
    print(f"  PLS balance:  {joey_pls / 1e18:,.2f} PLS")
except Exception as e:
    print(f"  Error reading player state: {e}")

# Check RING.Moments for Joey's soul
try:
    moments = ring.functions.Moments(joey_soul).call()
    print(f"  RING Moments: {moments}")
except Exception as e:
    print(f"  RING Moments: error - {e}")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 4b: Deep diagnostics — SHIO token balances driving Beat
# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "="*72)
print("  STEP 4b: SHIO Token Balances (Beat Prerequisites)")
print("="*72)

# Fornax = XIE.Fornax() — the REAL SHIO token used by XIE.Power for Omicron/Omega
# NOTE: 0x4Df51741... is XIE itself, NOT Fornax. XIE.Fornax() returns the actual SHIO.
FORNAX_ADDR = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
# Fomalhaute = XIA.Fomalhaute() — SHIO token used by XIA.Charge as modulus
FOMALHAUTE_ADDR = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")
# Eris (QI SHIO) — used in QI reactions
ERIS_ADDR = Web3.to_checksum_address("0xe843765114992e18061498aed708537ce9d924fa")
# CHO/Tethys = ZI.Tethys() — used for Omega/Eta in ZI.Spin
CHO_ADDR = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")

CHO_ABI = [
    {"inputs":[],"name":"GetUser","outputs":[{"components":[
        {"name":"Soul","type":"uint64"},
        {"components":[
            {"name":"Phi","type":"address"},
            {"components":[
                {"name":"Base","type":"uint64"},{"name":"Secret","type":"uint64"},
                {"name":"Signal","type":"uint64"},{"name":"Channel","type":"uint64"},
                {"name":"Contour","type":"uint64"},{"name":"Pole","type":"uint64"},
                {"name":"Identity","type":"uint64"},{"name":"Foundation","type":"uint64"},
                {"name":"Element","type":"uint64"},{"name":"Coordinate","type":"uint64"},
                {"name":"Charge","type":"uint64"},{"name":"Chin","type":"uint64"},
                {"name":"Monopole","type":"uint64"}
            ],"name":"Mu","type":"tuple"},
            {"name":"Xi","type":"uint64"},{"name":"Pi","type":"uint64"},
            {"name":"Shio","type":"address"},
            {"name":"Ring","type":"uint64"},
            {"name":"Omicron","type":"uint64"},{"name":"Omega","type":"uint64"}
        ],"name":"On","type":"tuple"},
        {"name":"Username","type":"string"},
        {"name":"Entropy","type":"uint64"}
    ],"name":"","type":"tuple"}],"stateMutability":"view","type":"function"},
]

fornax = w3.eth.contract(address=FORNAX_ADDR, abi=ERC20_ABI)
fomalhaute = w3.eth.contract(address=FOMALHAUTE_ADDR, abi=ERC20_ABI)
eris = w3.eth.contract(address=ERIS_ADDR, abi=ERC20_ABI)
cho = w3.eth.contract(address=CHO_ADDR, abi=CHO_ABI + ERC20_ABI)

# Get Joey's User struct from CHO to find Alpha.On.Phi
try:
    user = cho.functions.GetUser().call({'from': JOEY_WALLET})
    phi_addr = user[1][0]  # On.Phi
    user_entropy = user[3]  # Entropy
    print(f"  Joey's CHO User:")
    print(f"    Soul:     {user[0]}")
    print(f"    On.Phi:   {phi_addr}")
    print(f"    Entropy:  {user_entropy}")
    print(f"    Username: {user[2]}")
except Exception as e:
    print(f"  CHO.GetUser() failed: {e}")
    phi_addr = None
    user_entropy = 0

# SHIO token balances — these drive XIE.Power and XIA.Charge
print(f"\n  SHIO Token Balances:")
shio_checks = [
    ("Fornax (XIE SHIO)", fornax, FORNAX_ADDR),
    ("Fomalhaute (XIA SHIO)", fomalhaute, FOMALHAUTE_ADDR),
    ("Eris (QI SHIO)", eris, ERIS_ADDR),
    ("CHO (Tethys)", w3.eth.contract(address=CHO_ADDR, abi=ERC20_ABI), CHO_ADDR),
]

for name, contract, addr in shio_checks:
    joey_bal = contract.functions.balanceOf(JOEY_WALLET).call()
    qing_bal = contract.functions.balanceOf(GIBS_QING).call()
    yue_bal = contract.functions.balanceOf(JOEY_YUE).call()
    phi_bal = contract.functions.balanceOf(phi_addr).call() if phi_addr else 0
    print(f"    {name}:")
    print(f"      Joey wallet:  {joey_bal / 1e18:.4f}")
    print(f"      Joey YUE:     {yue_bal / 1e18:.4f}")
    if phi_addr:
        print(f"      Joey Phi:     {phi_bal / 1e18:.4f}  ({phi_addr})")
    print(f"      GIBS QING:    {qing_bal / 1e18:.4f}")

# Key formula checks
print(f"\n  XIE.Power formula inputs:")
print(f"    Omicron = Fornax.balanceOf(Phi) / Entropy")
if phi_addr:
    phi_fornax = fornax.functions.balanceOf(phi_addr).call()
    print(f"      = {phi_fornax / 1e18:.4f} / {user_entropy} = {phi_fornax // user_entropy if user_entropy > 0 else 0}")
print(f"    Omega = Fornax.balanceOf(GIBS_QING) / QING.Entropy")
qing_fornax = fornax.functions.balanceOf(GIBS_QING).call()
print(f"      = {qing_fornax / 1e18:.4f} / {entropy} = {qing_fornax // entropy if entropy > 0 else 0}")
print(f"\n  XIA.Charge formula:")
if phi_addr:
    phi_fomal = fomalhaute.functions.balanceOf(phi_addr).call()
    print(f"    modulus = Fomalhaute.balanceOf(Phi) = {phi_fomal / 1e18:.4f}")
    print(f"    modExp(base, exp, {phi_fomal}) {'= 0 if modulus is 0!' if phi_fomal == 0 else ''}")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 5: Dry-run META.Beat(QingWaat) via .call()
# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "="*72)
print("  STEP 5: DRY-RUN META.Beat(QingWaat)")
print("="*72)
print(f"  QingWaat parameter: {waat}")
print(f"  Calling from: {JOEY_WALLET}")

try:
    result = meta.functions.Beat(waat).call({'from': JOEY_WALLET})
    dione, charge, deimos, yeo = result

    print(f"\n  ┌─────────────────────────────────────────────────┐")
    print(f"  │  META.Beat() Return Values                      │")
    print(f"  ├─────────────────────────────────────────────────┤")
    print(f"  │  Dione:   {dione:>38,} │")
    print(f"  │  Charge:  {charge:>38,} │")
    print(f"  │  Deimos:  {deimos:>38,} │")
    print(f"  │  Yeo:     {yeo:>38,} │")
    print(f"  └─────────────────────────────────────────────────┘")

    print(f"\n  Interpretation:")
    print(f"    Dione  = Modular base value (used in territory claiming)")
    print(f"    Charge = Power multiplier (Charge1 * PushCharge / Iota^2)")
    print(f"    Deimos = modExp(Dione, Phoebe, Yuan(Qing)) — creator reward metric")
    print(f"    Yeo    = Territory range (Yeo/Chao) — used by WORLD.Code for ±lat/lon bounds")

    if yeo > 0 and latitude is not None:
        print(f"\n  Territory range from GIBS QING:")
        print(f"    Center:  ({latitude}, {longitude})")
        print(f"    Range:   ±{yeo}")
        print(f"    Lat bounds: [{latitude - yeo}, {latitude + yeo}]")
        print(f"    Lon bounds: [{longitude - yeo}, {longitude + yeo}]")

    # Estimate gas for the actual transaction
    print(f"\n  Gas estimate:")
    try:
        gas_est = meta.functions.Beat(waat).estimate_gas({'from': JOEY_WALLET})
        gas_price = w3.eth.gas_price
        cost_pls = gas_est * gas_price / 1e18
        print(f"    Gas:  {gas_est:,}")
        print(f"    Cost: {cost_pls:,.4f} PLS (at {gas_price / 1e9:.2f} gwei)")
    except Exception as e:
        print(f"    Gas estimation failed: {e}")

except Exception as e:
    print(f"\n  BEAT DRY-RUN FAILED: {e}")
    print(f"\n  Diagnosing...")

    # Try to isolate the failure point
    print(f"\n  Trying RING.Eta() separately...")
    try:
        eta_result = ring.functions.Eta().call({'from': JOEY_WALLET})
        print(f"    Eta() returned: Phoebe={eta_result[0]}, Iota={eta_result[1]}, Chao={eta_result[2]}, Charge={eta_result[3]}")
    except Exception as e2:
        print(f"    Eta() also failed: {e2}")

    print(f"\n  Trying PANG.Push({waat}) separately...")
    try:
        push_result = pang.functions.Push(waat).call({'from': JOEY_WALLET})
        print(f"    Push() returned: Iota={push_result[0]}, Omicron={push_result[1]}, Eta={push_result[2]}, Omega={push_result[3]}, Charge={push_result[4]}")
    except Exception as e3:
        print(f"    Push() also failed: {e3}")

    beat_ok = False
else:
    beat_ok = True

# ═════════════════════════════════════════════════════════════════════════════
# STEP 6: Dry-run CHEON.Su() (precursor to Beat in game loop)
# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "="*72)
print("  STEP 6: DRY-RUN CHEON.Su(GIBS_QING)")
print("="*72)

try:
    su_result = cheon.functions.Su(GIBS_QING).call({'from': JOEY_WALLET})
    su_charge, hypobar, epibar = su_result
    print(f"  Charge:   {su_charge:,}")
    print(f"  Hypobar:  {hypobar:,}")
    print(f"  Epibar:   {epibar:,}")
    print(f"\n  Interpretation:")
    print(f"    Charge  = ReactYue power from CHAN")
    print(f"    Hypobar = Lower bar weight (used in WORLD.Code)")
    print(f"    Epibar  = Upper bar weight")

    try:
        su_gas = cheon.functions.Su(GIBS_QING).estimate_gas({'from': JOEY_WALLET})
        su_gas_price = w3.eth.gas_price
        su_cost = su_gas * su_gas_price / 1e18
        print(f"\n  Gas estimate: {su_gas:,} (~{su_cost:,.4f} PLS)")
    except Exception as e:
        print(f"\n  Su() gas estimation failed: {e}")

except Exception as e:
    print(f"  CHEON.Su() DRY-RUN FAILED: {e}")

# ═════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "="*72)
print("  SUMMARY")
print("="*72)
print(f"  GIBS QING Waat:    {waat}")
print(f"  META contract:     {META_ADDR} (verified)")
print(f"  RING chain:        META -> RING -> PANG (verified)")
print(f"  CHEON chain:       CHEON -> SEI (verified)")
if latitude is not None:
    print(f"  QING coordinates:  ({latitude}, {longitude})")
print(f"  Beat dry-run:      {'SUCCESS' if beat_ok else 'FAILED (div by zero)'}")

if not beat_ok:
    print(f"\n  ROOT CAUSE ANALYSIS:")
    print(f"    RING.Eta() returned Chao=0 and Iota=0.")
    print(f"    Beat divides by both: Charge1*Charge/Iota1 and Yeo/Chao.")
    print(f"    The game loop is: CHEON.Su() -> META.Beat() -> WORLD.Code()")
    print(f"    Su() must be called first to build YUE bar weights (Hypobar/Epibar)")
    print(f"    which feed back into Yue.React() -> Chao in RING.Eta().")
    print(f"\n  NEXT STEPS:")
    print(f"    1. Send CHEON.Su(GIBS_QING) transaction to build YUE state")
    print(f"    2. Re-run this recon to verify Beat values are non-zero")
    print(f"    3. Then send META.Beat(QingWaat) transaction")
else:
    print(f"\n  Next step: Run tx_beat.py to send the actual Beat transaction.")
print("="*72)
