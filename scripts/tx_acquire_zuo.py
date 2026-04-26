#!/usr/bin/env python3
"""
Acquire ZUO tokens via WPLS -> Zürich -> ZUO path.

Root cause of Beat panic: CHOA.Yuan(ZUO) = 0 because Joey holds 0 ZUO tokens.
Fix: Buy ZUO from ZUO_QING using Zürich (which we get by swapping WPLS on V1 DEX).

DEX Path:
  - PulseX V1 router: 0x165C3410fC91EF562C50559f7d2289fEbed552d9
  - V1 Pair (Zürich/WPLS): 0x42DdaFfFE52489927a84B429920Dc8C392c3F70b
  - Rate: ~0.165 Zürich per WPLS

Purchase path:
  - ZUO_QING.Purchase(Zürich, ZUO_amount)
  - Market rate: 1M Zürich per ZUO (rate = 1e24)
  - cost = ZUO_amount * 1e24 / 1e18 = ZUO_amount * 1e6
  - To buy 0.001 ZUO: costs 1000 Zürich tokens
  - But we just need Yuan(ZUO) > 0, so even 1 ZUO wei works!
    (1 wei ZUO costs 1e6 wei Zürich = negligible)

Plan:
  Phase 1: Swap PLS -> Zürich via V1 router (swapExactETHForTokens)
           Buy ~1200 Zürich using ~7300 WPLS
  Phase 2: Approve ZUO_QING to spend Zürich
  Phase 3: ZUO_QING.Purchase(Zürich_addr, 1e15) -> buy 0.001 ZUO, costs 1000 Zürich
  Phase 4: Verify Yuan(ZUO) > 0
  Phase 5: Beat dry-run via .call()
"""
import os
import sys
import time
from web3 import Web3
from eth_account import Account

DRY_RUN = "--dry-run" in sys.argv

# ── Config ────────────────────────────────────────────────────────────────────
READ_RPC  = "https://rpc.pulsechain.com"
WRITE_RPC = "https://rpc.pulsechain.com"
PRIV_KEY  = os.environ["JOEY_PK"]  # set via env: export JOEY_PK=0x... (NEVER hardcode)
CHAIN_ID  = 369

w3 = Web3(Web3.HTTPProvider(READ_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")
if DRY_RUN:
    print("*** DRY RUN MODE ***")
print()

acct = Account.from_key(PRIV_KEY)
JOEY = acct.address
print(f"Joey:  {JOEY}")
print(f"PLS:   {w3.from_wei(w3.eth.get_balance(JOEY), 'ether'):.4f}")

# ── Addresses ─────────────────────────────────────────────────────────────────
ZUO_QING   = Web3.to_checksum_address("0xb0Ba7D36B7F0505879179ecE7401F24eB653c6E1")
ZURICH_TKN = Web3.to_checksum_address("0x583d1C1427308f7f96BFd3E0d7A3F9674D8BF8ec")  # Zürich
WPLS       = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
V1_ROUTER  = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")
META_ADDR  = Web3.to_checksum_address("0xE77Bdae31b2219e032178d88504Cc0170a5b9B97")
CHOA_ADDR  = Web3.to_checksum_address("0x0f5a352fd4cA4850c2099C15B3600ff085B66197")
GIBS_QING_WAAT = 251913148994206487765525643443518492465195287520927385378321984475167864513

# ── ABIs ──────────────────────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],
     "name":"approve","outputs":[{"type":"bool"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],
     "name":"allowance","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
]

V1_ROUTER_ABI = [
    {"inputs":[
        {"name":"amountOutMin","type":"uint256"},
        {"name":"path","type":"address[]"},
        {"name":"to","type":"address"},
        {"name":"deadline","type":"uint256"}
     ],"name":"swapExactETHForTokens",
     "outputs":[{"name":"amounts","type":"uint256[]"}],
     "stateMutability":"payable","type":"function"},
    {"inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],
     "name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],
     "stateMutability":"view","type":"function"},
]

QING_ABI = [
    {"inputs":[{"name":"_t","type":"address"},{"name":"_a","type":"uint256"}],
     "name":"Purchase","outputs":[],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"name":"_a","type":"address"}],"name":"GetMarketRate",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf",
     "outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"maxSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"GWAT","outputs":[{"type":"bool"}],"stateMutability":"view","type":"function"},
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

zurich  = w3.eth.contract(address=ZURICH_TKN, abi=ERC20_ABI)
zuo_qing= w3.eth.contract(address=ZUO_QING, abi=QING_ABI)
v1_rtr  = w3.eth.contract(address=V1_ROUTER, abi=V1_ROUTER_ABI)
choa    = w3.eth.contract(address=CHOA_ADDR, abi=CHOA_ABI)
meta    = w3.eth.contract(address=META_ADDR, abi=META_ABI)

def send_tx(tx_dict, desc):
    """Sign and send a transaction (or simulate in dry run)"""
    if DRY_RUN:
        try:
            w3.eth.call({**tx_dict, "from": JOEY})
            print(f"  [DRY] {desc}: call() OK")
        except Exception as e:
            print(f"  [DRY] {desc}: call() WOULD FAIL: {e}")
        return None

    # Estimate gas
    try:
        gas = w3.eth.estimate_gas({**tx_dict, "from": JOEY})
        tx_dict["gas"] = int(gas * 1.3)
    except Exception as e:
        print(f"  Gas estimation failed: {e}, using 300000")
        tx_dict["gas"] = 300000

    tx_dict["nonce"] = w3.eth.get_transaction_count(JOEY)
    tx_dict["chainId"] = CHAIN_ID
    if "gasPrice" not in tx_dict:
        tx_dict["gasPrice"] = w3.eth.gas_price

    signed = acct.sign_transaction(tx_dict)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  TX sent: {tx_hash.hex()}")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    if receipt.status == 1:
        print(f"  {desc}: SUCCESS (gas used: {receipt.gasUsed:,})")
    else:
        print(f"  {desc}: FAILED (receipt.status=0)")
    return receipt

# ── Preflight ──────────────────────────────────────────────────────────────────
print("\n" + "="*65)
print("PREFLIGHT")
print("="*65)

zuo_rate = zuo_qing.functions.GetMarketRate(ZURICH_TKN).call()
print(f"ZUO.GetMarketRate(Zürich) = {zuo_rate}")
zuo_bal_joey = zuo_qing.functions.balanceOf(JOEY).call()
print(f"ZUO.balanceOf(Joey) = {W(zuo_bal_joey)}")
zurich_bal = zurich.functions.balanceOf(JOEY).call()
print(f"Zürich.balanceOf(Joey) = {W(zurich_bal)}")

yuan_zuo = choa.functions.Yuan(ZUO_QING).call({"from": JOEY})
print(f"CHOA.Yuan(ZUO) = {yuan_zuo}")

# ── Phase 1: Swap PLS -> Zürich ───────────────────────────────────────────────
print("\n" + "="*65)
print("PHASE 1: Swap PLS -> Zürich via V1 Router")
print("="*65)

# How much PLS to use? We need ~1000 Zürich to buy 0.001 ZUO.
# At rate ~0.165 Zürich/WPLS, ~6100 WPLS should get ~1000 Zürich.
# Add 20% buffer: use 8000 WPLS.
PLS_TO_SWAP = w3.to_wei(8000, 'ether')  # 8000 PLS
path = [WPLS, ZURICH_TKN]

# Get expected output
try:
    amounts = v1_rtr.functions.getAmountsOut(PLS_TO_SWAP, path).call()
    expected_zurich = amounts[-1]
    print(f"Swap {8000} PLS -> ~{W(expected_zurich)} Zürich")
    # Use 5% slippage tolerance
    min_zurich = int(expected_zurich * 0.95)
    print(f"Min out (5% slippage): {W(min_zurich)} Zürich")
except Exception as e:
    print(f"getAmountsOut failed: {e}")
    # Fallback min
    min_zurich = int(900 * 1e18)  # 900 Zürich minimum

deadline = int(time.time()) + 1200  # 20 minutes

print(f"\nExecuting swap...")
swap_tx = {
    "to": V1_ROUTER,
    "value": PLS_TO_SWAP,
    "data": v1_rtr.encode_abi("swapExactETHForTokens", args=[min_zurich, path, JOEY, deadline]),
}
swap_receipt = send_tx(swap_tx, "swapExactETHForTokens PLS->Zürich")

# Check Zürich balance after
if not DRY_RUN:
    time.sleep(2)
    zurich_bal_after = zurich.functions.balanceOf(JOEY).call()
    print(f"Zürich balance after swap: {W(zurich_bal_after)}")
else:
    zurich_bal_after = expected_zurich

# ── Phase 2: Approve ZUO_QING to spend Zürich ────────────────────────────────
print("\n" + "="*65)
print("PHASE 2: Approve ZUO_QING to spend Zürich")
print("="*65)

# ZUO to buy: 0.001 ZUO = 1e15 wei ZUO
# Cost: 0.001 * 1e6 = 1e9 Zürich tokens? Wait...
# cost = _a * 1e24 / 1e18 = _a * 1e6 (in Zürich wei)
# 1e15 * 1e6 = 1e21 = 1000 Zürich tokens
# BUT actual Zürich to spend for 0.001 ZUO:
# cost (in Zürich wei) = 1e15 * 1e24 / 1e18 = 1e21 = 1000 * 1e18 Zürich

ZUO_TO_BUY = 1_000_000_000_000_000  # 0.001 ZUO in wei
ZURICH_COST = ZUO_TO_BUY * (zuo_rate // 10**18)  # simplified
# Actually: cost = ZUO_TO_BUY * zuo_rate / 1e18
ZURICH_COST_WEI = ZUO_TO_BUY * zuo_rate // (10**18)
print(f"ZUO to buy: {W(ZUO_TO_BUY)} ZUO")
print(f"Zürich cost (wei): {ZURICH_COST_WEI} = {W(ZURICH_COST_WEI)} Zürich")

# Approve ZUO_QING for the exact amount plus buffer
APPROVE_AMOUNT = int(ZURICH_COST_WEI * 1.1)  # 10% buffer

approve_tx = {
    "to": ZURICH_TKN,
    "data": zurich.encode_abi("approve", args=[ZUO_QING, APPROVE_AMOUNT]),
}
send_tx(approve_tx, f"Zürich.approve(ZUO_QING, {W(APPROVE_AMOUNT)})")

# ── Phase 3: Purchase ZUO tokens ──────────────────────────────────────────────
print("\n" + "="*65)
print("PHASE 3: ZUO_QING.Purchase(Zürich, ZUO_amount)")
print("="*65)

print(f"Purchasing {W(ZUO_TO_BUY)} ZUO (costs ~{W(ZURICH_COST_WEI)} Zürich)...")
purchase_tx = {
    "to": ZUO_QING,
    "data": zuo_qing.encode_abi("Purchase", args=[ZURICH_TKN, ZUO_TO_BUY]),
}
send_tx(purchase_tx, f"ZUO_QING.Purchase(Zürich, {W(ZUO_TO_BUY)} ZUO)")

# ── Phase 4: Verify ───────────────────────────────────────────────────────────
print("\n" + "="*65)
print("PHASE 4: Verification")
print("="*65)

if not DRY_RUN:
    time.sleep(2)

zuo_bal_new = zuo_qing.functions.balanceOf(JOEY).call()
print(f"ZUO.balanceOf(Joey) = {W(zuo_bal_new)}")

yuan_new = choa.functions.Yuan(ZUO_QING).call({"from": JOEY})
print(f"CHOA.Yuan(ZUO) = {yuan_new}")

if yuan_new > 0:
    print("  CHOA.Yuan(ZUO) > 0 ✓")
else:
    print("  WARNING: CHOA.Yuan(ZUO) still 0!")

# ── Phase 5: Beat Dry-run ─────────────────────────────────────────────────────
print("\n" + "="*65)
print("PHASE 5: Beat dry-run via .call()")
print("="*65)

try:
    result = meta.functions.Beat(GIBS_QING_WAAT).call({"from": JOEY})
    print(f"Beat() DRY-RUN SUCCESS!")
    print(f"  Dione  = {result[0]}")
    print(f"  Charge = {result[1]}")
    print(f"  Deimos = {result[2]}")
    print(f"  Yeo    = {result[3]}")
    print()
    print("Ready to execute Beat()!")
except Exception as e:
    print(f"Beat() still fails: {str(e)[:120]}")
    print("Need to debug further.")

print()
print(f"PLS remaining: {w3.from_wei(w3.eth.get_balance(JOEY), 'ether'):.4f}")
