#!/usr/bin/env python3
"""
Continue SHIO acquisition — Phases 2-5.
Phase 1 (Fornax) already completed. Picks up from PulseX swaps.

Fix: Use V1 router (0x165C3410...) for direct AFFECTION→SHIO swaps.
The "V2 router" (0x98bf93eb...) actually uses V1 factory, can't find V2 pairs.
"""
from web3 import Web3
from eth_account import Account
import os, sys, time

SUBMIT_RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# ── Addresses ────────────────────────────────────────────────
JOEY_WALLET      = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_LAU         = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
GIBS_QING        = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
FORNAX           = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
FOMALHAUTE       = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")
CHO_TOKEN        = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
AFFECTION        = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
# V1 router works for direct AFFECTION→SHIO swaps (V2 router has wrong factory)
PULSEX_V1_ROUTER = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")

# ── Private Key ──────────────────────────────────────────────
JOEY_PKEY = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
if not JOEY_PKEY:
    print("ERROR: DYSNOMIA_PRIVATE_KEY not set.")
    sys.exit(1)
account = Account.from_key(JOEY_PKEY)
assert account.address.lower() == JOEY_WALLET.lower(), "Key mismatch!"

# ── ABIs ─────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],"name":"transfer","outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"},
]

ROUTER_ABI = [
    {"inputs":[
        {"name":"amountIn","type":"uint256"},
        {"name":"amountOutMin","type":"uint256"},
        {"name":"path","type":"address[]"},
        {"name":"to","type":"address"},
        {"name":"deadline","type":"uint256"}
    ],"name":"swapExactTokensForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[
        {"name":"amountIn","type":"uint256"},
        {"name":"path","type":"address[]"}
    ],"name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"},
]

affection  = w3.eth.contract(address=AFFECTION,  abi=ERC20_ABI)
fornax     = w3.eth.contract(address=FORNAX,     abi=ERC20_ABI)
fomalhaute = w3.eth.contract(address=FOMALHAUTE, abi=ERC20_ABI)
cho_token  = w3.eth.contract(address=CHO_TOKEN,  abi=ERC20_ABI)
router     = w3.eth.contract(address=PULSEX_V1_ROUTER, abi=ROUTER_ABI)

def send_tx(fn_call, label, gas_mult=1.3):
    nonce     = w3.eth.get_transaction_count(JOEY_WALLET)
    gas_price = w3.eth.gas_price
    gas_est   = fn_call.estimate_gas({'from': JOEY_WALLET})
    print(f"  Nonce: {nonce}  Gas: {gas_est:,}  Cost: {gas_est * gas_price / 1e18:.4f} PLS")
    tx = fn_call.build_transaction({
        'from': JOEY_WALLET, 'nonce': nonce,
        'gas': int(gas_est * gas_mult), 'gasPrice': gas_price, 'chainId': 369,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  TX sent: 0x{tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    print(f"  Status: {receipt['status']}  Block: {receipt['blockNumber']:,}  Gas used: {receipt['gasUsed']:,}")
    assert receipt['status'] == 1, f"{label} FAILED!"
    print(f"  {label} ✓")
    return receipt

def fmt(val):
    return f"{val / 1e18:.6f}"

# ── Pre-check: Fornax already acquired ──────────────────────
print(f"\n{'='*60}")
print(f"  STATUS CHECK")
print(f"{'='*60}")
fornax_joey = fornax.functions.balanceOf(JOEY_WALLET).call()
aff_bal = affection.functions.balanceOf(JOEY_WALLET).call()
print(f"Fornax in wallet: {fmt(fornax_joey)} (Phase 1 done)")
print(f"AFFECTION: {fmt(aff_bal)}")
assert fornax_joey > 0, "Fornax not found! Run tx_acquire_shio.py first."

# DEX preview
fom_amounts = router.functions.getAmountsOut(5 * 10**18, [AFFECTION, FOMALHAUTE]).call()
cho_amounts = router.functions.getAmountsOut(2 * 10**18, [AFFECTION, CHO_TOKEN]).call()
print(f"\nV1 DEX preview: 5 AFFECTION → {fmt(fom_amounts[1])} Fomalhaute")
print(f"V1 DEX preview: 2 AFFECTION → {fmt(cho_amounts[1])} CHO")

# ── Phase 2: Fomalhaute via PulseX V1 ───────────────────────
print(f"\n{'='*60}")
print(f"  PHASE 2: FOMALHAUTE via PULSEX V1")
print(f"{'='*60}")

FOM_SPEND = 5 * 10**18
total_spend = FOM_SPEND + 2 * 10**18  # 7 AFFECTION total

print(f"\n--- AFFECTION.approve(V1 router, {fmt(total_spend)}) ---")
send_tx(affection.functions.approve(PULSEX_V1_ROUTER, total_spend), "Approve AFFECTION for V1 Router")
time.sleep(2)

deadline = w3.eth.get_block('latest')['timestamp'] + 600
print(f"\n--- router.swap({fmt(FOM_SPEND)} AFFECTION → Fomalhaute) ---")
send_tx(
    router.functions.swapExactTokensForTokens(
        FOM_SPEND, 1, [AFFECTION, FOMALHAUTE], JOEY_WALLET, deadline
    ),
    "Swap AFFECTION → Fomalhaute"
)

fom_joey = fomalhaute.functions.balanceOf(JOEY_WALLET).call()
print(f"\nFomalhaute in wallet: {fmt(fom_joey)}")
print("Phase 2 complete!")

# ── Phase 3: CHO via PulseX V1 ──────────────────────────────
print(f"\n{'='*60}")
print(f"  PHASE 3: CHO via PULSEX V1")
print(f"{'='*60}")

CHO_SPEND = 2 * 10**18
deadline = w3.eth.get_block('latest')['timestamp'] + 600
print(f"\n--- router.swap({fmt(CHO_SPEND)} AFFECTION → CHO) ---")
send_tx(
    router.functions.swapExactTokensForTokens(
        CHO_SPEND, 1, [AFFECTION, CHO_TOKEN], JOEY_WALLET, deadline
    ),
    "Swap AFFECTION → CHO"
)

cho_joey = cho_token.functions.balanceOf(JOEY_WALLET).call()
print(f"\nCHO in wallet: {fmt(cho_joey)}")
print("Phase 3 complete!")

# ── Phase 4: Transfer to GIBS_LAU and GIBS_QING ─────────────
print(f"\n{'='*60}")
print(f"  PHASE 4: TRANSFER TO GIBS_LAU + GIBS_QING")
print(f"{'='*60}")

fornax_joey = fornax.functions.balanceOf(JOEY_WALLET).call()
fom_joey = fomalhaute.functions.balanceOf(JOEY_WALLET).call()
cho_joey = cho_token.functions.balanceOf(JOEY_WALLET).call()

print(f"Joey's wallet:")
print(f"  Fornax:     {fmt(fornax_joey)}")
print(f"  Fomalhaute: {fmt(fom_joey)}")
print(f"  CHO:        {fmt(cho_joey)}")

fornax_half = fornax_joey // 2
cho_half = cho_joey // 2

# TX: Fornax → GIBS_LAU
print(f"\n--- Fornax.transfer(GIBS_LAU, {fmt(fornax_half)}) ---")
send_tx(fornax.functions.transfer(GIBS_LAU, fornax_half), "Fornax → GIBS_LAU")
time.sleep(2)

# TX: Fornax → GIBS_QING
fornax_remaining = fornax.functions.balanceOf(JOEY_WALLET).call()
print(f"\n--- Fornax.transfer(GIBS_QING, {fmt(fornax_remaining)}) ---")
send_tx(fornax.functions.transfer(GIBS_QING, fornax_remaining), "Fornax → GIBS_QING")
time.sleep(2)

# TX: Fomalhaute → GIBS_LAU (all — only needed there)
print(f"\n--- Fomalhaute.transfer(GIBS_LAU, {fmt(fom_joey)}) ---")
send_tx(fomalhaute.functions.transfer(GIBS_LAU, fom_joey), "Fomalhaute → GIBS_LAU")
time.sleep(2)

# TX: CHO → GIBS_LAU
print(f"\n--- CHO.transfer(GIBS_LAU, {fmt(cho_half)}) ---")
send_tx(cho_token.functions.transfer(GIBS_LAU, cho_half), "CHO → GIBS_LAU")
time.sleep(2)

# TX: CHO → GIBS_QING
cho_remaining = cho_token.functions.balanceOf(JOEY_WALLET).call()
print(f"\n--- CHO.transfer(GIBS_QING, {fmt(cho_remaining)}) ---")
send_tx(cho_token.functions.transfer(GIBS_QING, cho_remaining), "CHO → GIBS_QING")

# ── Phase 5: Post-flight Verification ───────────────────────
print(f"\n{'='*60}")
print(f"  PHASE 5: POST-FLIGHT VERIFICATION")
print(f"{'='*60}")

all_ok = True
for label, token, addr_name, addr in [
    ("Fornax",     fornax,     "GIBS_LAU",  GIBS_LAU),
    ("Fornax",     fornax,     "GIBS_QING", GIBS_QING),
    ("Fomalhaute", fomalhaute, "GIBS_LAU",  GIBS_LAU),
    ("CHO",        cho_token,  "GIBS_LAU",  GIBS_LAU),
    ("CHO",        cho_token,  "GIBS_QING", GIBS_QING),
]:
    bal = token.functions.balanceOf(addr).call()
    ok = bal > 0
    status = "OK" if ok else "ZERO!"
    print(f"  {label:12s} @ {addr_name:10s}: {fmt(bal)} [{status}]")
    if not ok:
        all_ok = False

aff_remaining = affection.functions.balanceOf(JOEY_WALLET).call()
pls_remaining = w3.eth.get_balance(JOEY_WALLET)
print(f"\nRemaining balances:")
print(f"  AFFECTION: {fmt(aff_remaining)}")
print(f"  PLS: {pls_remaining / 1e18:.2f}")

if all_ok:
    print(f"\nALL SHIO TOKENS ACQUIRED AND DISTRIBUTED!")
    print(f"META.Beat() should now work. Run tx_beat.py next.")
else:
    print(f"\nWARNING: Some SHIO balances still zero.")
