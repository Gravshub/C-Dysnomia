#!/usr/bin/env python3
"""
Acquire ZUO and GIBS_QING tokens so CHOA.Yuan() returns non-zero values.

ROOT CAUSE:
  PANG.Push() computes: modExp(Omicron, Charge, Choa.Yuan(address(Qing)))
  CHOA.Yuan(Currency) = Currency.balanceOf(Joey_EOA)
                      + 10 * Currency.balanceOf(GIBS_LAU)
                      + 40 * Currency.balanceOf(Joey_YUE)

  Currently Yuan(ZUO) = 0 and Yuan(GIBS_QING) = 0.
  modExp(x, y, 0) = 0 for any x,y → Iota=0 → Ring.Eta().Iota=0 → Beat panics.

FIX:
  Purchase 1 ZUO and 1 GIBS_QING token via their AFFECTION market rate.
  QING contracts hold their own tokens (minted to address(this) in constructor).
  After purchase, Yuan(ZUO) = 1e18 > 0 and Yuan(GIBS_QING) = 1e18 > 0.

Usage:
  export DYSNOMIA_PRIVATE_KEY=0x...
  python scripts/tx_acquire_qing_tokens.py           # execute transactions
  python scripts/tx_acquire_qing_tokens.py --dry-run # estimate only
"""
import argparse, os, sys, time
from web3 import Web3
from eth_account import Account

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true", help="Gas estimate only, no TXs")
args = parser.parse_args()
DRY_RUN = args.dry_run

if DRY_RUN:
    print("[--dry-run] Gas estimates only — no transactions will be sent.")

# ── RPC ──────────────────────────────────────────────────────────────────────
RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# ── Addresses ─────────────────────────────────────────────────────────────────
JOEY_WALLET = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_LAU    = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
GIBS_QING   = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
ZUO         = Web3.to_checksum_address("0xb0Ba7D36B7F0505879179ecE7401F24eB653c6E1")
AFFECTION   = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
JOEY_YUE    = Web3.to_checksum_address("0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0")
CHOA_ADDR   = Web3.to_checksum_address("0x0f5a352fd4cA4850c2099C15B3600ff085B66197")
PANG_ADDR   = Web3.to_checksum_address("0xEe25Ccd41671F3B67d660cf6532085586aec8457")
RING_ADDR   = Web3.to_checksum_address("0x1574c84Ec7fA78fC6C749e1d242dbde163675e72")
META_ADDR   = Web3.to_checksum_address("0xE77Bdae31b2219e032178d88504Cc0170a5b9B97")

GIBS_QING_WAAT = 251913148994206487765525643443518492465195287520927385378321984475167864513

# ── Private Key ───────────────────────────────────────────────────────────────
JOEY_PKEY = os.environ.get("DYSNOMIA_PRIVATE_KEY", "")
if not JOEY_PKEY:
    print("ERROR: DYSNOMIA_PRIVATE_KEY not set.")
    sys.exit(1)
account = Account.from_key(JOEY_PKEY)
assert account.address.lower() == JOEY_WALLET.lower(), "Key mismatch!"
print(f"Wallet: {account.address}")

# ── ABIs ──────────────────────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
     "name":"approve","outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
     "name":"allowance","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"to","type":"address"},{"name":"amount","type":"uint256"}],
     "name":"transfer","outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"},
]

DYSNOMIA_ABI = ERC20_ABI + [
    {"inputs":[{"name":"PaymentToken","type":"address"},{"name":"Amount","type":"uint256"}],
     "name":"Purchase","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"PaymentToken","type":"address"}],"name":"GetMarketRate",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]

CHOA_ABI = [
    {"inputs":[{"name":"Currency","type":"address"}],"name":"Yuan",
     "outputs":[{"name":"Bae","type":"uint256"}],"stateMutability":"view","type":"function"},
]

PANG_ABI = [
    {"inputs":[{"name":"QingWaat","type":"uint256"}],"name":"Push",
     "outputs":[{"name":"Iota","type":"uint256"},{"name":"Omicron","type":"uint256"},
                {"name":"Eta","type":"uint256"},{"name":"Omega","type":"uint256"},
                {"name":"Charge","type":"uint256"}],
     "stateMutability":"nonpayable","type":"function"},
]

RING_ABI = [
    {"inputs":[],"name":"Eta",
     "outputs":[{"name":"Phoebe","type":"uint256"},{"name":"Iota","type":"uint256"},
                {"name":"Chao","type":"uint256"},{"name":"Charge","type":"uint256"}],
     "stateMutability":"nonpayable","type":"function"},
]

META_ABI = [
    {"inputs":[{"name":"QingWaat","type":"uint256"}],"name":"Beat",
     "outputs":[{"name":"Dione","type":"uint256"},{"name":"Charge","type":"uint256"},
                {"name":"Deimos","type":"uint256"},{"name":"Yeo","type":"uint256"}],
     "stateMutability":"nonpayable","type":"function"},
]

QING_ABI = DYSNOMIA_ABI + [
    {"inputs":[{"name":"UserToken","type":"address"}],"name":"Join",
     "outputs":[],"stateMutability":"nonpayable","type":"function"},
]

# ── Contract instances ─────────────────────────────────────────────────────────
affection = w3.eth.contract(address=AFFECTION, abi=ERC20_ABI)
zuo_c     = w3.eth.contract(address=ZUO, abi=QING_ABI)
gq_c      = w3.eth.contract(address=GIBS_QING, abi=QING_ABI)
choa_c    = w3.eth.contract(address=CHOA_ADDR, abi=CHOA_ABI)
pang_c    = w3.eth.contract(address=PANG_ADDR, abi=PANG_ABI)
ring_c    = w3.eth.contract(address=RING_ADDR, abi=RING_ABI)
meta_c    = w3.eth.contract(address=META_ADDR, abi=META_ABI)

# ── Helpers ───────────────────────────────────────────────────────────────────
def send_tx(fn, desc, gas_pad=1.3):
    gas_price = w3.eth.gas_price
    nonce = w3.eth.get_transaction_count(JOEY_WALLET)
    try:
        gas_est = fn.estimate_gas({"from": JOEY_WALLET})
    except Exception as e:
        print(f"  [GAS ESTIMATE FAILED] {desc}: {e}")
        return None
    gas = int(gas_est * gas_pad)
    cost_pls = gas * gas_price / 1e18
    print(f"  [{desc}]  gas={gas:,}  cost≈{cost_pls:.4f} PLS")
    if DRY_RUN:
        return "dry-run"
    tx = fn.build_transaction({
        "from": JOEY_WALLET, "nonce": nonce,
        "gas": gas, "gasPrice": gas_price,
        "chainId": 369,
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  TX sent: {tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    status = "OK" if receipt.status == 1 else "FAILED"
    print(f"  Status: {status}  Block: {receipt.blockNumber}  Gas used: {receipt.gasUsed:,}")
    if receipt.status != 1:
        raise RuntimeError(f"TX failed: {tx_hash.hex()}")
    return receipt

# ═════════════════════════════════════════════════════════════════════════════
# STEP 1: Pre-flight balance check
# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("  STEP 1: Pre-flight Balances")
print("="*70)

joey_pls = w3.eth.get_balance(JOEY_WALLET) / 1e18
joey_aff = affection.functions.balanceOf(JOEY_WALLET).call() / 1e18
zuo_bal_joey = zuo_c.functions.balanceOf(JOEY_WALLET).call() / 1e18
zuo_bal_self = zuo_c.functions.balanceOf(ZUO).call() / 1e18
zuo_rate     = zuo_c.functions.GetMarketRate(AFFECTION).call() / 1e18
gq_bal_joey  = gq_c.functions.balanceOf(JOEY_WALLET).call() / 1e18
gq_bal_self  = gq_c.functions.balanceOf(GIBS_QING).call() / 1e18
gq_rate      = gq_c.functions.GetMarketRate(AFFECTION).call() / 1e18

print(f"  Joey PLS:              {joey_pls:,.2f} PLS")
print(f"  Joey AFFECTION:        {joey_aff:.4f}")
print(f"  ZUO.balanceOf(Joey):   {zuo_bal_joey:.4f}")
print(f"  ZUO.balanceOf(ZUO):    {zuo_bal_self:.4f}  ← must be > 0 to Purchase")
print(f"  ZUO market rate:       {zuo_rate:.4f} AFFECTION per ZUO")
print(f"  GIBS_QING.bal(Joey):   {gq_bal_joey:.4f}")
print(f"  GIBS_QING.bal(QING):   {gq_bal_self:.4f}  ← must be > 0 to Purchase")
print(f"  GIBS_QING market rate: {gq_rate:.4f} AFFECTION per GIBS_QING")

# Check CHOA.Yuan before
try:
    yuan_zuo = choa_c.functions.Yuan(ZUO).call({"from": JOEY_WALLET})
    yuan_gq  = choa_c.functions.Yuan(GIBS_QING).call({"from": JOEY_WALLET})
    print(f"\n  CHOA.Yuan(ZUO):        {yuan_zuo}  {'← ZERO (bad)' if yuan_zuo == 0 else '← non-zero (good)'}")
    print(f"  CHOA.Yuan(GIBS_QING):  {yuan_gq}  {'← ZERO (bad)' if yuan_gq == 0 else '← non-zero (good)'}")
except Exception as e:
    print(f"  CHOA.Yuan() failed: {e}")
    yuan_zuo = 0
    yuan_gq = 0

# Early exit if already fixed
if yuan_zuo > 0 and yuan_gq > 0:
    print("\n  Both Yuan values are already non-zero — skipping to Beat dry-run.")
    need_zuo = False
    need_gq = False
else:
    need_zuo = (yuan_zuo == 0)
    need_gq  = (yuan_gq == 0)

# ═════════════════════════════════════════════════════════════════════════════
# STEP 2: Acquire ZUO tokens (if needed)
# ═════════════════════════════════════════════════════════════════════════════
if need_zuo:
    print("\n" + "="*70)
    print("  STEP 2: Acquire ZUO via Purchase(AFFECTION, 1e18)")
    print("="*70)

    if zuo_bal_self <= 0:
        print("  ERROR: ZUO contract holds 0 ZUO tokens — cannot Purchase.")
        print("  Alternative: Try ZUO.Join(GIBS_LAU) to mint tokens to ZUO contract,")
        print("  then Purchase. Or check if another token path exists.")
        # Try Join first then Purchase
        print("\n  Attempting ZUO.Join(GIBS_LAU) first to trigger mintToCap...")
        try:
            send_tx(zuo_c.functions.Join(GIBS_LAU), "ZUO.Join(GIBS_LAU)")
        except Exception as e:
            print(f"  Join failed: {e}")

        # Re-check self-balance
        zuo_bal_self = zuo_c.functions.balanceOf(ZUO).call() / 1e18
        print(f"  ZUO.balanceOf(ZUO) after Join: {zuo_bal_self:.4f}")

    if zuo_bal_self > 0:
        # Approve AFFECTION spend
        BUY_AMOUNT = 1 * 10**18  # 1 ZUO
        current_allowance = affection.functions.allowance(JOEY_WALLET, ZUO).call()
        if current_allowance < BUY_AMOUNT:
            print(f"  Approving AFFECTION → ZUO spend (1e18)...")
            send_tx(affection.functions.approve(ZUO, BUY_AMOUNT), "AFFECTION.approve(ZUO,1e18)")
        else:
            print(f"  AFFECTION already approved for ZUO: {current_allowance/1e18:.4f}")

        # Purchase ZUO
        send_tx(zuo_c.functions.Purchase(AFFECTION, BUY_AMOUNT), "ZUO.Purchase(AFFECTION,1e18)")
    else:
        print("  FATAL: No ZUO tokens available to purchase. Manual investigation needed.")
else:
    print("\n  STEP 2: ZUO — Yuan already non-zero, skipping.")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 3: Acquire GIBS_QING tokens (if needed)
# ═════════════════════════════════════════════════════════════════════════════
if need_gq:
    print("\n" + "="*70)
    print("  STEP 3: Acquire GIBS_QING via Purchase(AFFECTION, 1e18)")
    print("="*70)

    if gq_bal_self <= 0:
        print("  GIBS_QING contract holds 0 of itself — trying Join first...")
        try:
            send_tx(gq_c.functions.Join(GIBS_LAU), "GIBS_QING.Join(GIBS_LAU)")
        except Exception as e:
            print(f"  Join failed: {e}")

        gq_bal_self = gq_c.functions.balanceOf(GIBS_QING).call() / 1e18
        print(f"  GIBS_QING.balanceOf(QING) after Join: {gq_bal_self:.4f}")

    if gq_bal_self > 0:
        BUY_AMOUNT = 1 * 10**18  # 1 GIBS_QING
        current_allowance = affection.functions.allowance(JOEY_WALLET, GIBS_QING).call()
        if current_allowance < BUY_AMOUNT:
            print(f"  Approving AFFECTION → GIBS_QING spend (1e18)...")
            send_tx(affection.functions.approve(GIBS_QING, BUY_AMOUNT), "AFFECTION.approve(GIBS_QING,1e18)")
        else:
            print(f"  AFFECTION already approved for GIBS_QING: {current_allowance/1e18:.4f}")

        send_tx(gq_c.functions.Purchase(AFFECTION, BUY_AMOUNT), "GIBS_QING.Purchase(AFFECTION,1e18)")
    else:
        print("  FATAL: No GIBS_QING tokens available to purchase.")
else:
    print("\n  STEP 3: GIBS_QING — Yuan already non-zero, skipping.")

# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: Verify Yuan values are now non-zero
# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("  STEP 4: Post-Acquisition Yuan Verification")
print("="*70)

zuo_bal_joey_after = zuo_c.functions.balanceOf(JOEY_WALLET).call() / 1e18
gq_bal_joey_after  = gq_c.functions.balanceOf(JOEY_WALLET).call() / 1e18
print(f"  ZUO.balanceOf(Joey):   {zuo_bal_joey_after:.4f}")
print(f"  GIBS_QING.bal(Joey):   {gq_bal_joey_after:.4f}")

try:
    yuan_zuo_after = choa_c.functions.Yuan(ZUO).call({"from": JOEY_WALLET})
    yuan_gq_after  = choa_c.functions.Yuan(GIBS_QING).call({"from": JOEY_WALLET})
    print(f"  CHOA.Yuan(ZUO):        {yuan_zuo_after}  {'OK' if yuan_zuo_after > 0 else 'STILL ZERO!'}")
    print(f"  CHOA.Yuan(GIBS_QING):  {yuan_gq_after}  {'OK' if yuan_gq_after > 0 else 'STILL ZERO!'}")
    yuan_ok = yuan_zuo_after > 0 and yuan_gq_after > 0
except Exception as e:
    print(f"  Yuan check failed: {e}")
    yuan_ok = False

# ═════════════════════════════════════════════════════════════════════════════
# STEP 5: Beat dry-run
# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("  STEP 5: META.Beat() Dry-Run")
print("="*70)

# Also check RING.Eta and PANG.Push first
print("  Checking RING.Eta()...")
try:
    eta = ring_c.functions.Eta().call({"from": JOEY_WALLET})
    print(f"    Phoebe={eta[0]}, Iota={eta[1]}, Chao={eta[2]}, Charge={eta[3]}")
    if eta[1] == 0:
        print("    *** Iota still 0 — PANG.Push still returning 0 modExp ***")
except Exception as e:
    print(f"    Eta() failed: {e}")

print("  Checking PANG.Push(GIBS_QING_WAAT)...")
try:
    push = pang_c.functions.Push(GIBS_QING_WAAT).call({"from": JOEY_WALLET})
    print(f"    Iota={push[0]}, Omicron={push[1]}, Eta={push[2]}, Omega={push[3]}, Charge={push[4]}")
except Exception as e:
    print(f"    Push() failed: {e}")

print("\n  Calling META.Beat() via .call()...")
try:
    result = meta_c.functions.Beat(GIBS_QING_WAAT).call({"from": JOEY_WALLET})
    dione, charge, deimos, yeo = result
    print(f"\n  ┌─────────────────────────────────────────────────┐")
    print(f"  │  META.Beat() DRY-RUN SUCCEEDED                  │")
    print(f"  ├─────────────────────────────────────────────────┤")
    print(f"  │  Dione:   {dione:>38,} │")
    print(f"  │  Charge:  {charge:>38,} │")
    print(f"  │  Deimos:  {deimos:>38,} │")
    print(f"  │  Yeo:     {yeo:>38,} │")
    print(f"  └─────────────────────────────────────────────────┘")

    try:
        gas_est = meta_c.functions.Beat(GIBS_QING_WAAT).estimate_gas({"from": JOEY_WALLET})
        gas_price = w3.eth.gas_price
        cost = gas_est * gas_price / 1e18
        print(f"\n  Gas estimate for actual Beat TX: {gas_est:,} (~{cost:.4f} PLS)")
    except Exception as e:
        print(f"  Gas estimate failed: {e}")

    beat_ok = True
except Exception as e:
    print(f"\n  BEAT DRY-RUN FAILED: {e}")
    beat_ok = False

# ═════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═════════════════════════════════════════════════════════════════════════════
print("\n" + "="*70)
print("  SUMMARY")
print("="*70)
print(f"  ZUO tokens acquired:       {zuo_bal_joey_after:.4f} (Joey EOA)")
print(f"  GIBS_QING tokens acquired: {gq_bal_joey_after:.4f} (Joey EOA)")
print(f"  CHOA.Yuan values non-zero: {'YES' if yuan_ok else 'NO'}")
print(f"  Beat dry-run:              {'SUCCESS' if beat_ok else 'FAILED'}")
if beat_ok:
    print(f"\n  READY: Run tx_full_beat_flow.py --skip-shio --with-cheon --broadcast")
else:
    print(f"\n  NOT READY: Investigate CHOA.Yuan values and PANG.Push diagnostics above.")
print("="*70)
