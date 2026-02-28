#!/usr/bin/env python3
"""
Full Beat Integration Flow — SHIO Acquisition → (CHEON.Su) → META.Beat()

Single orchestration script for the complete territory computation sequence:

  Phase 0 — SHIO status check at GIBS_LAU + GIBS_QING
  Phase 1 — Fornax acquisition via enteh's QING (if SHIO missing)
  Phase 2 — Fomalhaute + CHO via PulseX V1 router (if SHIO missing)
  Phase 3 — Transfer SHIO to GIBS_LAU + GIBS_QING (if SHIO missing)
  Phase 4 — CHEON.Su(GIBS_QING) optional YUE bar primer (--with-cheon)
  Phase 5 — META.Beat(GIBS_QING_WAAT) dry-run
  Phase 6 — META.Beat execute
  Phase 7 — Summary

Game loop: CHEON.Su(QingAddr) → META.Beat(QingWaat) → WORLD.Code(lat, lon, QingAddr)

Note on --with-cheon: Enteh skips Su() entirely and calls Beat directly.
Su() primes the YUE bars (Hypobar/Epibar) for better territory metrics but
is not required for Beat to succeed.

Usage:
  python scripts/tx_full_beat_flow.py                  # full flow, auto-skip SHIO if present
  python scripts/tx_full_beat_flow.py --dry-run        # simulate only, no TXs sent
  python scripts/tx_full_beat_flow.py --with-cheon     # include CHEON.Su() before Beat
  python scripts/tx_full_beat_flow.py --skip-shio      # skip SHIO acquisition phases
"""
import argparse, os, sys, time
from web3 import Web3
from eth_account import Account

# ── CLI ──────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Full Beat integration flow")
parser.add_argument("--dry-run",    action="store_true", help="Simulate all phases, no TXs sent")
parser.add_argument("--with-cheon", action="store_true", help="Run CHEON.Su() before Beat")
parser.add_argument("--skip-shio",  action="store_true", help="Skip SHIO acquisition (assume already present)")
args = parser.parse_args()

DRY_RUN    = args.dry_run
WITH_CHEON = args.with_cheon
SKIP_SHIO  = args.skip_shio

if DRY_RUN:
    print("[--dry-run] Simulation mode — no transactions will be sent.")

# ── RPC ──────────────────────────────────────────────────────
SUBMIT_RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(SUBMIT_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# ── Addresses ────────────────────────────────────────────────
JOEY_WALLET      = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_LAU         = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
GIBS_QING        = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
META             = Web3.to_checksum_address("0xE77Bdae31b2219e032178d88504Cc0170a5b9B97")
CHEON_ADDR       = Web3.to_checksum_address("0x3d23084cA3F40465553797b5138CFC456E61FB5D")
ENTEH_QING       = Web3.to_checksum_address("0xA43F71ac277022A547c56706fbBc5d93f88C3467")
FORNAX           = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
FOMALHAUTE       = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")
CHO_TOKEN        = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
AFFECTION        = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
# V1 router for AFFECTION→SHIO swaps (V2 router has wrong factory reference)
PULSEX_V1_ROUTER = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")

GIBS_QING_WAAT = 251913148994206487765525643443518492465195287520927385378321984475167864513

# ── Private Key ──────────────────────────────────────────────
JOEY_PKEY = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
if not JOEY_PKEY:
    print("ERROR: DYSNOMIA_PRIVATE_KEY not set. source .env first.")
    sys.exit(1)
account = Account.from_key(JOEY_PKEY)
assert account.address.lower() == JOEY_WALLET.lower(), "Key mismatch!"

# ── ABIs ─────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve",
     "outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],"name":"transfer",
     "outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"},
]

QING_ABI = [
    {"inputs":[{"name":"UserToken","type":"address"}],"name":"Join",
     "outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"_t","type":"address"},{"name":"_a","type":"uint256"}],"name":"Purchase",
     "outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"_t","type":"address"},{"name":"_a","type":"uint256"}],"name":"Redeem",
     "outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"name":"approve",
     "outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"_a","type":"address"}],"name":"GetMarketRate",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Waat","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Entropy","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"},
]

ROUTER_ABI = [
    {"inputs":[
        {"name":"amountIn","type":"uint256"},{"name":"amountOutMin","type":"uint256"},
        {"name":"path","type":"address[]"},{"name":"to","type":"address"},
        {"name":"deadline","type":"uint256"}
     ],"name":"swapExactTokensForTokens","outputs":[{"name":"amounts","type":"uint256[]"}],
     "stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],
     "name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],
     "stateMutability":"view","type":"function"},
]

META_ABI = [
    {"inputs":[{"name":"QingWaat","type":"uint256"}],"name":"Beat",
     "outputs":[
         {"name":"Dione","type":"uint256"},{"name":"Charge","type":"uint256"},
         {"name":"Deimos","type":"uint256"},{"name":"Yeo","type":"uint256"}
     ],"stateMutability":"nonpayable","type":"function"},
]

CHEON_ABI = [
    {"inputs":[{"name":"Qing","type":"address"}],"name":"Su",
     "outputs":[
         {"name":"Charge","type":"uint256"},
         {"name":"Hypobar","type":"uint256"},
         {"name":"Epibar","type":"uint256"}
     ],"stateMutability":"nonpayable","type":"function"},
]

# ── Contract Instances ───────────────────────────────────────
enteh_qing = w3.eth.contract(address=ENTEH_QING, abi=QING_ABI)
gibs_q     = w3.eth.contract(address=GIBS_QING,  abi=QING_ABI)
affection  = w3.eth.contract(address=AFFECTION,  abi=ERC20_ABI)
fornax     = w3.eth.contract(address=FORNAX,     abi=ERC20_ABI)
fomalhaute = w3.eth.contract(address=FOMALHAUTE, abi=ERC20_ABI)
cho_token  = w3.eth.contract(address=CHO_TOKEN,  abi=ERC20_ABI)
router     = w3.eth.contract(address=PULSEX_V1_ROUTER, abi=ROUTER_ABI)
meta       = w3.eth.contract(address=META,       abi=META_ABI)
cheon      = w3.eth.contract(address=CHEON_ADDR, abi=CHEON_ABI)

# ── Helpers ───────────────────────────────────────────────────
def fmt(val):
    return f"{val / 1e18:.6f}"

def send_tx(fn_call, label, gas_mult=1.3):
    if DRY_RUN:
        print(f"  [DRY-RUN] Would send: {label}")
        return None
    nonce     = w3.eth.get_transaction_count(JOEY_WALLET)
    gas_price = w3.eth.gas_price
    gas_est   = fn_call.estimate_gas({'from': JOEY_WALLET})
    print(f"  Nonce: {nonce}  Gas: {gas_est:,}  Cost: {gas_est * gas_price / 1e18:.4f} PLS")
    tx = fn_call.build_transaction({
        'from': JOEY_WALLET, 'nonce': nonce,
        'gas': int(gas_est * gas_mult), 'gasPrice': gas_price, 'chainId': 369,
    })
    signed   = account.sign_transaction(tx)
    tx_hash  = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  TX sent: 0x{tx_hash.hex()}")
    receipt  = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
    print(f"  Status: {receipt['status']}  Block: {receipt['blockNumber']:,}  Gas used: {receipt['gasUsed']:,}")
    assert receipt['status'] == 1, f"{label} FAILED!"
    print(f"  {label} ✓")
    return receipt

SHIO_CHECKS = [
    ("Fornax",     fornax,     "GIBS_LAU",  GIBS_LAU),
    ("Fornax",     fornax,     "GIBS_QING", GIBS_QING),
    ("Fomalhaute", fomalhaute, "GIBS_LAU",  GIBS_LAU),
    ("CHO",        cho_token,  "GIBS_LAU",  GIBS_LAU),
    ("CHO",        cho_token,  "GIBS_QING", GIBS_QING),
]

def check_shio():
    all_ok = True
    for label, token, addr_name, addr in SHIO_CHECKS:
        bal = token.functions.balanceOf(addr).call()
        ok  = bal > 0
        status = "OK" if ok else "ZERO!"
        print(f"  {label:12s} @ {addr_name:10s}: {fmt(bal)} [{status}]")
        if not ok:
            all_ok = False
    return all_ok

# ─────────────────────────────────────────────────────────────
# PHASE 0 — SHIO STATUS CHECK
# ─────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  PHASE 0: SHIO STATUS CHECK")
print(f"{'='*60}")

shio_ok = check_shio()

aff_bal = affection.functions.balanceOf(JOEY_WALLET).call()
pls_bal = w3.eth.get_balance(JOEY_WALLET)
print(f"\n  Joey AFFECTION: {fmt(aff_bal)}")
print(f"  Joey PLS:       {pls_bal / 1e18:.2f}")

if shio_ok or SKIP_SHIO:
    if shio_ok:
        print(f"\n  All SHIO tokens present — skipping acquisition.")
    else:
        print(f"\n  [--skip-shio] Skipping acquisition despite missing tokens.")
    needs_shio = False
else:
    print(f"\n  Missing SHIO tokens — will acquire (need ~10 AFFECTION + ~16K PLS gas).")
    assert aff_bal >= 10 * 10**18, f"Need >= 10 AFFECTION, have {fmt(aff_bal)}"
    needs_shio = True

# ─────────────────────────────────────────────────────────────
# PHASE 1 — FORNAX via ENTEH'S QING  (if needed)
# ─────────────────────────────────────────────────────────────
if needs_shio:
    print(f"\n{'='*60}")
    print(f"  PHASE 1: FORNAX via ENTEH'S QING")
    print(f"{'='*60}")

    NUM_JOINS = 3
    fornax_rate = enteh_qing.functions.GetMarketRate(FORNAX).call()
    print(f"  Enteh QING Fornax rate: {fmt(fornax_rate)} (per QING token)")
    print(f"  Plan: Join×{NUM_JOINS} → Purchase {NUM_JOINS} QING → Redeem → ~{fmt(NUM_JOINS * 10**18 * fornax_rate // 10**18)} Fornax")

    for i in range(NUM_JOINS):
        print(f"\n--- Join enteh QING [{i+1}/{NUM_JOINS}] ---")
        send_tx(enteh_qing.functions.Join(GIBS_LAU), f"Join enteh QING #{i+1}")
        if not DRY_RUN:
            time.sleep(2)

    amt = NUM_JOINS * 10**18
    print(f"\n--- AFFECTION.approve(enteh_QING, {fmt(amt)}) ---")
    send_tx(affection.functions.approve(ENTEH_QING, amt), "Approve AFFECTION for enteh QING")
    if not DRY_RUN:
        time.sleep(2)

    print(f"\n--- enteh_QING.Purchase(AFFECTION, {fmt(amt)}) ---")
    send_tx(enteh_qing.functions.Purchase(AFFECTION, amt), f"Purchase {NUM_JOINS} QING with AFFECTION")
    if not DRY_RUN:
        time.sleep(2)

    print(f"\n--- enteh_QING.approve(enteh_QING, {fmt(amt)}) ---")
    send_tx(enteh_qing.functions.approve(ENTEH_QING, amt), "Approve QING for Redeem")
    if not DRY_RUN:
        time.sleep(2)

    print(f"\n--- enteh_QING.Redeem(FORNAX, {fmt(amt)}) ---")
    send_tx(enteh_qing.functions.Redeem(FORNAX, amt), "Redeem QING → Fornax")
    if not DRY_RUN:
        fornax_joey = fornax.functions.balanceOf(JOEY_WALLET).call()
        print(f"  Fornax in wallet: {fmt(fornax_joey)}")

    print("  Phase 1 complete!")

# ─────────────────────────────────────────────────────────────
# PHASE 2 — FOMALHAUTE + CHO via PULSEX V1  (if needed)
# ─────────────────────────────────────────────────────────────
if needs_shio:
    print(f"\n{'='*60}")
    print(f"  PHASE 2: FOMALHAUTE + CHO via PULSEX V1")
    print(f"{'='*60}")

    FOM_SPEND = 5 * 10**18
    CHO_SPEND = 2 * 10**18
    total_dex = FOM_SPEND + CHO_SPEND

    try:
        fom_preview = router.functions.getAmountsOut(FOM_SPEND, [AFFECTION, FOMALHAUTE]).call()
        cho_preview = router.functions.getAmountsOut(CHO_SPEND, [AFFECTION, CHO_TOKEN]).call()
        print(f"  V1 DEX: {fmt(FOM_SPEND)} AFFECTION → {fmt(fom_preview[1])} Fomalhaute")
        print(f"  V1 DEX: {fmt(CHO_SPEND)} AFFECTION → {fmt(cho_preview[1])} CHO")
    except Exception as e:
        print(f"  DEX preview failed: {e} (continuing anyway)")

    print(f"\n--- AFFECTION.approve(V1 Router, {fmt(total_dex)}) ---")
    send_tx(affection.functions.approve(PULSEX_V1_ROUTER, total_dex), "Approve AFFECTION for V1 Router")
    if not DRY_RUN:
        time.sleep(2)

    deadline = w3.eth.get_block('latest')['timestamp'] + 600
    print(f"\n--- swap {fmt(FOM_SPEND)} AFFECTION → Fomalhaute ---")
    send_tx(
        router.functions.swapExactTokensForTokens(
            FOM_SPEND, 1, [AFFECTION, FOMALHAUTE], JOEY_WALLET, deadline
        ),
        "Swap AFFECTION → Fomalhaute"
    )
    if not DRY_RUN:
        time.sleep(2)

    deadline = w3.eth.get_block('latest')['timestamp'] + 600
    print(f"\n--- swap {fmt(CHO_SPEND)} AFFECTION → CHO ---")
    send_tx(
        router.functions.swapExactTokensForTokens(
            CHO_SPEND, 1, [AFFECTION, CHO_TOKEN], JOEY_WALLET, deadline
        ),
        "Swap AFFECTION → CHO"
    )
    if not DRY_RUN:
        fom_joey = fomalhaute.functions.balanceOf(JOEY_WALLET).call()
        cho_joey = cho_token.functions.balanceOf(JOEY_WALLET).call()
        print(f"  Fomalhaute in wallet: {fmt(fom_joey)}")
        print(f"  CHO in wallet:        {fmt(cho_joey)}")

    print("  Phase 2 complete!")

# ─────────────────────────────────────────────────────────────
# PHASE 3 — TRANSFER SHIO TO GIBS_LAU + GIBS_QING  (if needed)
# ─────────────────────────────────────────────────────────────
if needs_shio:
    print(f"\n{'='*60}")
    print(f"  PHASE 3: TRANSFER SHIO TO GIBS_LAU + GIBS_QING")
    print(f"{'='*60}")

    if not DRY_RUN:
        fornax_joey = fornax.functions.balanceOf(JOEY_WALLET).call()
        fom_joey    = fomalhaute.functions.balanceOf(JOEY_WALLET).call()
        cho_joey    = cho_token.functions.balanceOf(JOEY_WALLET).call()
        print(f"  Joey's wallet: Fornax={fmt(fornax_joey)}  Fomalhaute={fmt(fom_joey)}  CHO={fmt(cho_joey)}")
        fornax_half = fornax_joey // 2
        cho_half    = cho_joey // 2
    else:
        fornax_joey = 300000000000000000  # ~0.3 estimated
        fom_joey    = 1400000000000000    # ~0.0014 estimated
        cho_joey    = 12700000000000000   # ~0.0127 estimated
        fornax_half = fornax_joey // 2
        cho_half    = cho_joey // 2
        print(f"  [DRY-RUN] Estimated amounts:")
        print(f"    Fornax:     {fmt(fornax_joey)}")
        print(f"    Fomalhaute: {fmt(fom_joey)}")
        print(f"    CHO:        {fmt(cho_joey)}")

    print(f"\n--- Fornax.transfer(GIBS_LAU, {fmt(fornax_half)}) ---")
    send_tx(fornax.functions.transfer(GIBS_LAU, fornax_half), "Fornax → GIBS_LAU")
    if not DRY_RUN:
        time.sleep(2)

    if not DRY_RUN:
        fornax_remaining = fornax.functions.balanceOf(JOEY_WALLET).call()
    else:
        fornax_remaining = fornax_joey - fornax_half
    print(f"\n--- Fornax.transfer(GIBS_QING, {fmt(fornax_remaining)}) ---")
    send_tx(fornax.functions.transfer(GIBS_QING, fornax_remaining), "Fornax → GIBS_QING")
    if not DRY_RUN:
        time.sleep(2)

    print(f"\n--- Fomalhaute.transfer(GIBS_LAU, {fmt(fom_joey)}) ---")
    send_tx(fomalhaute.functions.transfer(GIBS_LAU, fom_joey), "Fomalhaute → GIBS_LAU")
    if not DRY_RUN:
        time.sleep(2)

    print(f"\n--- CHO.transfer(GIBS_LAU, {fmt(cho_half)}) ---")
    send_tx(cho_token.functions.transfer(GIBS_LAU, cho_half), "CHO → GIBS_LAU")
    if not DRY_RUN:
        time.sleep(2)

    if not DRY_RUN:
        cho_remaining = cho_token.functions.balanceOf(JOEY_WALLET).call()
    else:
        cho_remaining = cho_joey - cho_half
    print(f"\n--- CHO.transfer(GIBS_QING, {fmt(cho_remaining)}) ---")
    send_tx(cho_token.functions.transfer(GIBS_QING, cho_remaining), "CHO → GIBS_QING")

    print(f"\n  Verifying distributions:")
    if not DRY_RUN:
        check_shio()
    else:
        print("  [DRY-RUN] Skipping post-transfer verification.")
    print("  Phase 3 complete!")

# ─────────────────────────────────────────────────────────────
# PHASE 4 — CHEON.Su()  (optional, --with-cheon)
# ─────────────────────────────────────────────────────────────
su_charge = su_hypobar = su_epibar = None

if WITH_CHEON:
    print(f"\n{'='*60}")
    print(f"  PHASE 4: CHEON.Su({GIBS_QING}) [--with-cheon]")
    print(f"{'='*60}")

    try:
        result = cheon.functions.Su(GIBS_QING).call({'from': JOEY_WALLET, 'gas': 5_000_000})
        su_charge, su_hypobar, su_epibar = result
        print(f"\n  Dry-run Su() result:")
        print(f"    Charge:  {su_charge}  ({fmt(su_charge)})")
        print(f"    Hypobar: {su_hypobar}  ({fmt(su_hypobar)})")
        print(f"    Epibar:  {su_epibar}  ({fmt(su_epibar)})")

        print(f"\n--- CHEON.Su({GIBS_QING}) ---")
        receipt = send_tx(cheon.functions.Su(GIBS_QING), "CHEON.Su()")
        print("  Phase 4 complete — YUE bars primed.")
    except Exception as e:
        print(f"\n  Su() failed: {e}")
        print("  Continuing to Beat without CHEON primer (same as enteh's approach).")
else:
    print(f"\n  Phase 4 skipped (add --with-cheon to prime YUE bars first).")

# ─────────────────────────────────────────────────────────────
# PHASE 5 — META.Beat() DRY-RUN
# ─────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  PHASE 5: META.Beat() DRY-RUN")
print(f"{'='*60}")

print(f"  Verifying SHIO balances before Beat:")
if not DRY_RUN:
    shio_ready = check_shio()
    if not shio_ready:
        print("\n  FATAL: SHIO tokens still missing after acquisition. Aborting.")
        sys.exit(1)
else:
    print("  [DRY-RUN] Assuming SHIO balances OK.")
    shio_ready = True

try:
    result = meta.functions.Beat(GIBS_QING_WAAT).call({'from': JOEY_WALLET, 'gas': 5_000_000})
    dione, charge, deimos, yeo = result
    print(f"\n  DRY-RUN SUCCESS!")
    print(f"    Dione:  {dione}")
    print(f"    Charge: {charge}")
    print(f"    Deimos: {deimos}")
    print(f"    Yeo:    {yeo}")
except Exception as e:
    print(f"\n  DRY-RUN FAILED: {e}")
    print("\n  Beat is reverting. Possible causes:")
    print("    - SHIO balances too low (need enough to avoid div/0)")
    print("    - Chan state not initialized for Joey's YUE")
    print("    - Try acquiring more SHIO tokens (run with --skip-shio=False)")
    sys.exit(1)

if DRY_RUN:
    print(f"\n[--dry-run] Stopping here. Remove --dry-run to execute transactions.")
    sys.exit(0)

# ─────────────────────────────────────────────────────────────
# PHASE 6 — META.Beat() EXECUTE
# ─────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  PHASE 6: META.Beat() EXECUTE")
print(f"{'='*60}")

nonce     = w3.eth.get_transaction_count(JOEY_WALLET)
gas_price = w3.eth.gas_price
gas_est   = meta.functions.Beat(GIBS_QING_WAAT).estimate_gas({'from': JOEY_WALLET})
print(f"  Nonce: {nonce}  Gas est: {gas_est:,}  Cost: {gas_est * gas_price / 1e18:.4f} PLS")

tx = meta.functions.Beat(GIBS_QING_WAAT).build_transaction({
    'from': JOEY_WALLET, 'nonce': nonce,
    'gas': int(gas_est * 1.3), 'gasPrice': gas_price, 'chainId': 369,
})
signed  = account.sign_transaction(tx)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"  TX sent: 0x{tx_hash.hex()}")

receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
print(f"  Status: {receipt['status']}  Block: {receipt['blockNumber']:,}  Gas used: {receipt['gasUsed']:,}")
assert receipt['status'] == 1, "Beat TX FAILED!"
print(f"  META.Beat() ✓")

# ─────────────────────────────────────────────────────────────
# PHASE 7 — SUMMARY
# ─────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"  PHASE 7: SUMMARY")
print(f"{'='*60}")

print(f"\n  Beat Results (from dry-run — same values):")
print(f"    Dione:  {dione}")
print(f"    Charge: {charge}")
print(f"    Deimos: {deimos}")
print(f"    Yeo:    {yeo}")

if su_charge is not None:
    print(f"\n  CHEON.Su() Results:")
    print(f"    Charge:  {su_charge}")
    print(f"    Hypobar: {su_hypobar}")
    print(f"    Epibar:  {su_epibar}")

print(f"\n  Beat TX: 0x{tx_hash.hex()}")
print(f"  Block:   {receipt['blockNumber']:,}")
print(f"  Gas:     {receipt['gasUsed']:,}")

print(f"\n  Final SHIO balances:")
check_shio()

aff_remaining = affection.functions.balanceOf(JOEY_WALLET).call()
pls_remaining = w3.eth.get_balance(JOEY_WALLET)
print(f"\n  AFFECTION remaining: {fmt(aff_remaining)}")
print(f"  PLS remaining:       {pls_remaining / 1e18:.2f}")

print(f"\n{'='*60}")
print(f"  Beat integration complete!")
print(f"  Next: WORLD.Code(lat, lon, GIBS_QING) for territory claiming")
print(f"  (WORLD contract not yet deployed — monitor for deployment)")
print(f"{'='*60}")
