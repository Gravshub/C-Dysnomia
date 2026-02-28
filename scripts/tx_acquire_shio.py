#!/usr/bin/env python3
"""
Acquire SHIO Tokens for META.Beat()

Beat requires Fornax, Fomalhaute, and CHO at GIBS_LAU and GIBS_QING.
All three have zero balance — this script acquires them:

Phase 1: Fornax via enteh's QING (Join → Purchase → Redeem)
Phase 2: Fomalhaute via PulseX V2 (AFFECTION → Fomalhaute swap)
Phase 3: CHO via PulseX V2 (AFFECTION → CHO swap)
Phase 4: Transfer all three to GIBS_LAU and GIBS_QING
Phase 5: Post-flight verification
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
ENTEH_QING       = Web3.to_checksum_address("0xA43F71ac277022A547c56706fbBc5d93f88C3467")
FORNAX           = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
FOMALHAUTE       = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")
CHO_TOKEN        = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
AFFECTION        = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
PULSEX_V2_ROUTER = Web3.to_checksum_address("0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02")

# ── Private Key ──────────────────────────────────────────────
JOEY_PKEY = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
if not JOEY_PKEY:
    print("ERROR: DYSNOMIA_PRIVATE_KEY not set. source .env first.")
    sys.exit(1)

account = Account.from_key(JOEY_PKEY)
assert account.address.lower() == JOEY_WALLET.lower(), "Key mismatch!"

# ── ABIs ─────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],"name":"transfer","outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]

QING_ABI = [
    {"inputs":[{"name":"UserToken","type":"address"}],"name":"Join","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"_t","type":"address"},{"name":"_a","type":"uint256"}],"name":"Purchase","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"_t","type":"address"},{"name":"_a","type":"uint256"}],"name":"Redeem","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve","outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"_a","type":"address"}],"name":"GetMarketRate","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
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

# ── Contract Instances ───────────────────────────────────────
enteh_qing = w3.eth.contract(address=ENTEH_QING, abi=QING_ABI)
affection  = w3.eth.contract(address=AFFECTION,  abi=ERC20_ABI)
fornax     = w3.eth.contract(address=FORNAX,     abi=ERC20_ABI)
fomalhaute = w3.eth.contract(address=FOMALHAUTE, abi=ERC20_ABI)
cho_token  = w3.eth.contract(address=CHO_TOKEN,  abi=ERC20_ABI)
router     = w3.eth.contract(address=PULSEX_V2_ROUTER, abi=ROUTER_ABI)

# ── TX Helper (from tx_grav_terraform.py) ────────────────────
def send_tx(fn_call, label, gas_mult=1.2):
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

# ── Phase 0: Pre-flight ─────────────────────────────────────
print(f"\n{'='*60}")
print(f"  PHASE 0: PRE-FLIGHT")
print(f"{'='*60}")

aff_bal = affection.functions.balanceOf(JOEY_WALLET).call()
print(f"AFFECTION balance: {fmt(aff_bal)} (need ~10)")
assert aff_bal >= 10 * 10**18, f"Need >= 10 AFFECTION, have {fmt(aff_bal)}"

# SHIO current balances at targets (should all be 0)
for name, token, addr_name, addr in [
    ("Fornax",     fornax,     "GIBS_LAU",  GIBS_LAU),
    ("Fornax",     fornax,     "GIBS_QING", GIBS_QING),
    ("Fomalhaute", fomalhaute, "GIBS_LAU",  GIBS_LAU),
    ("CHO",        cho_token,  "GIBS_LAU",  GIBS_LAU),
    ("CHO",        cho_token,  "GIBS_QING", GIBS_QING),
]:
    bal = token.functions.balanceOf(addr).call()
    print(f"{name} @ {addr_name}: {fmt(bal)}")

# Enteh QING state
qing_self_bal = enteh_qing.functions.balanceOf(ENTEH_QING).call()
qing_fornax_rate = enteh_qing.functions.GetMarketRate(FORNAX).call()
qing_aff_rate = enteh_qing.functions.GetMarketRate(AFFECTION).call()
fornax_at_qing = fornax.functions.balanceOf(ENTEH_QING).call()
print(f"\nEnteh QING self-balance: {fmt(qing_self_bal)}")
print(f"Enteh QING Fornax held: {fmt(fornax_at_qing)}")
print(f"Enteh QING GetMarketRate(AFFECTION): {fmt(qing_aff_rate)}")
print(f"Enteh QING GetMarketRate(FORNAX): {fmt(qing_fornax_rate)}")

# DEX preview
try:
    fom_amounts = router.functions.getAmountsOut(5 * 10**18, [AFFECTION, FOMALHAUTE]).call()
    print(f"\nDEX preview: 5 AFFECTION → {fmt(fom_amounts[1])} Fomalhaute")
except Exception as e:
    print(f"\nDEX preview Fomalhaute: {e}")

try:
    cho_amounts = router.functions.getAmountsOut(2 * 10**18, [AFFECTION, CHO_TOKEN]).call()
    print(f"DEX preview: 2 AFFECTION → {fmt(cho_amounts[1])} CHO")
except Exception as e:
    print(f"DEX preview CHO: {e}")

print(f"\nPre-flight OK. Proceeding with acquisition...")

# ── Phase 1: Fornax via Enteh's QING ────────────────────────
print(f"\n{'='*60}")
print(f"  PHASE 1: FORNAX via ENTEH'S QING")
print(f"{'='*60}")

NUM_JOINS = 3  # Join 3 times → 3 QING self-balance → 3 AFFECTION → 0.3 Fornax

# TX1-3: Join enteh's QING (each triggers _mintToCap → self-balance +1)
for i in range(NUM_JOINS):
    print(f"\n--- TX {i+1}: enteh_QING.Join(GIBS_LAU) [{i+1}/{NUM_JOINS}] ---")
    send_tx(enteh_qing.functions.Join(GIBS_LAU), f"Join enteh QING #{i+1}")
    time.sleep(2)

# Verify self-balance
qing_self_bal = enteh_qing.functions.balanceOf(ENTEH_QING).call()
print(f"\nEnteh QING self-balance after Joins: {fmt(qing_self_bal)}")
assert qing_self_bal >= NUM_JOINS * 10**18, f"Expected >= {NUM_JOINS} QING, got {fmt(qing_self_bal)}"

# TX4: Approve AFFECTION for enteh's QING
amt = NUM_JOINS * 10**18
print(f"\n--- TX {NUM_JOINS+1}: AFFECTION.approve(enteh_QING, {fmt(amt)}) ---")
send_tx(affection.functions.approve(ENTEH_QING, amt), "Approve AFFECTION for enteh QING")
time.sleep(2)

# TX5: Purchase QING with AFFECTION
print(f"\n--- TX {NUM_JOINS+2}: enteh_QING.Purchase(AFFECTION, {fmt(amt)}) ---")
send_tx(enteh_qing.functions.Purchase(AFFECTION, amt), f"Purchase {NUM_JOINS} QING")
time.sleep(2)

# Verify Joey has QING tokens
joey_qing_bal = enteh_qing.functions.balanceOf(JOEY_WALLET).call()
print(f"Joey QING balance: {fmt(joey_qing_bal)}")
assert joey_qing_bal >= amt, f"Expected >= {fmt(amt)} QING, got {fmt(joey_qing_bal)}"

# TX6: Approve QING for Redeem (QING contract needs to transferFrom Joey's QING)
print(f"\n--- TX {NUM_JOINS+3}: enteh_QING.approve(enteh_QING, {fmt(amt)}) ---")
send_tx(enteh_qing.functions.approve(ENTEH_QING, amt), "Approve QING for Redeem")
time.sleep(2)

# TX7: Redeem QING for Fornax
print(f"\n--- TX {NUM_JOINS+4}: enteh_QING.Redeem(FORNAX, {fmt(amt)}) ---")
expected_fornax = amt * qing_fornax_rate // 10**18
print(f"  Expected Fornax: {fmt(expected_fornax)} (rate: {fmt(qing_fornax_rate)})")
send_tx(enteh_qing.functions.Redeem(FORNAX, amt), f"Redeem {NUM_JOINS} QING → {fmt(expected_fornax)} Fornax")

fornax_joey = fornax.functions.balanceOf(JOEY_WALLET).call()
print(f"\nFornax in Joey's wallet: {fmt(fornax_joey)}")
print("Phase 1 complete!")

# ── Phase 2: Fomalhaute via PulseX V2 ───────────────────────
print(f"\n{'='*60}")
print(f"  PHASE 2: FOMALHAUTE via PULSEX V2")
print(f"{'='*60}")

FOM_SPEND = 5 * 10**18  # 5 AFFECTION

# TX8: Approve AFFECTION for PulseX V2 Router (combine with CHO spend)
total_dex_spend = FOM_SPEND + 2 * 10**18  # 5 + 2 = 7 AFFECTION total for both swaps
print(f"\n--- TX 8: AFFECTION.approve(router, {fmt(total_dex_spend)}) ---")
send_tx(affection.functions.approve(PULSEX_V2_ROUTER, total_dex_spend), "Approve AFFECTION for PulseX V2")
time.sleep(2)

# TX9: Swap AFFECTION → Fomalhaute
deadline = w3.eth.get_block('latest')['timestamp'] + 600  # 10 min deadline
print(f"\n--- TX 9: router.swapExactTokensForTokens({fmt(FOM_SPEND)} → Fomalhaute) ---")
send_tx(
    router.functions.swapExactTokensForTokens(
        FOM_SPEND, 1, [AFFECTION, FOMALHAUTE], JOEY_WALLET, deadline
    ),
    "Swap AFFECTION → Fomalhaute",
    gas_mult=1.3
)

fom_joey = fomalhaute.functions.balanceOf(JOEY_WALLET).call()
print(f"\nFomalhaute in Joey's wallet: {fmt(fom_joey)}")
print("Phase 2 complete!")

# ── Phase 3: CHO via PulseX V2 ──────────────────────────────
print(f"\n{'='*60}")
print(f"  PHASE 3: CHO via PULSEX V2")
print(f"{'='*60}")

CHO_SPEND = 2 * 10**18  # 2 AFFECTION

# TX10: Swap AFFECTION → CHO
deadline = w3.eth.get_block('latest')['timestamp'] + 600
print(f"\n--- TX 10: router.swapExactTokensForTokens({fmt(CHO_SPEND)} → CHO) ---")
send_tx(
    router.functions.swapExactTokensForTokens(
        CHO_SPEND, 1, [AFFECTION, CHO_TOKEN], JOEY_WALLET, deadline
    ),
    "Swap AFFECTION → CHO",
    gas_mult=1.3
)

cho_joey = cho_token.functions.balanceOf(JOEY_WALLET).call()
print(f"\nCHO in Joey's wallet: {fmt(cho_joey)}")
print("Phase 3 complete!")

# ── Phase 4: Transfer to GIBS_LAU and GIBS_QING ─────────────
print(f"\n{'='*60}")
print(f"  PHASE 4: TRANSFER TO GIBS_LAU + GIBS_QING")
print(f"{'='*60}")

# Re-read balances
fornax_joey = fornax.functions.balanceOf(JOEY_WALLET).call()
fom_joey = fomalhaute.functions.balanceOf(JOEY_WALLET).call()
cho_joey = cho_token.functions.balanceOf(JOEY_WALLET).call()

print(f"Joey's wallet:")
print(f"  Fornax:     {fmt(fornax_joey)}")
print(f"  Fomalhaute: {fmt(fom_joey)}")
print(f"  CHO:        {fmt(cho_joey)}")

# Split Fornax: half to LAU, half to QING
fornax_half = fornax_joey // 2
# Split CHO: half to LAU, half to QING
cho_half = cho_joey // 2

print(f"\nTransfer plan:")
print(f"  Fornax → GIBS_LAU:  {fmt(fornax_half)}")
print(f"  Fornax → GIBS_QING: {fmt(fornax_joey - fornax_half)}")
print(f"  Fomalhaute → GIBS_LAU: {fmt(fom_joey)} (all)")
print(f"  CHO → GIBS_LAU:  {fmt(cho_half)}")
print(f"  CHO → GIBS_QING: {fmt(cho_joey - cho_half)}")

# TX11: Fornax → GIBS_LAU
print(f"\n--- TX 11: Fornax.transfer(GIBS_LAU, {fmt(fornax_half)}) ---")
send_tx(fornax.functions.transfer(GIBS_LAU, fornax_half), "Fornax → GIBS_LAU")
time.sleep(2)

# TX12: Fornax → GIBS_QING
fornax_remaining = fornax.functions.balanceOf(JOEY_WALLET).call()
print(f"\n--- TX 12: Fornax.transfer(GIBS_QING, {fmt(fornax_remaining)}) ---")
send_tx(fornax.functions.transfer(GIBS_QING, fornax_remaining), "Fornax → GIBS_QING")
time.sleep(2)

# TX13: Fomalhaute → GIBS_LAU (all)
print(f"\n--- TX 13: Fomalhaute.transfer(GIBS_LAU, {fmt(fom_joey)}) ---")
send_tx(fomalhaute.functions.transfer(GIBS_LAU, fom_joey), "Fomalhaute → GIBS_LAU")
time.sleep(2)

# TX14: CHO → GIBS_LAU
print(f"\n--- TX 14: CHO.transfer(GIBS_LAU, {fmt(cho_half)}) ---")
send_tx(cho_token.functions.transfer(GIBS_LAU, cho_half), "CHO → GIBS_LAU")
time.sleep(2)

# TX15: CHO → GIBS_QING
cho_remaining = cho_token.functions.balanceOf(JOEY_WALLET).call()
print(f"\n--- TX 15: CHO.transfer(GIBS_QING, {fmt(cho_remaining)}) ---")
send_tx(cho_token.functions.transfer(GIBS_QING, cho_remaining), "CHO → GIBS_QING")

# ── Phase 5: Post-flight Verification ───────────────────────
print(f"\n{'='*60}")
print(f"  PHASE 5: POST-FLIGHT VERIFICATION")
print(f"{'='*60}")

print("\nSHIO balances at target addresses:")
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
    print(f"\nWARNING: Some SHIO balances are still zero. Check above.")
