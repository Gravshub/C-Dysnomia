#!/usr/bin/env python3
"""
CROWS Acquisition Recon — Investigate all paths to acquire 25+ CROWS tokens.

CROWS (0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1) is the social credential
token in Dysnomia. Holding 25+ CROWS grants bouncer access to any non-NoCROWS
QING venue.

Checks:
  A. CROWS basic state: name, symbol, totalSupply, maxSupply, decimals
  B. Joey's CROWS balance + CROWS self-balance (balanceOf(address(CROWS)))
  C. CROWS GetMarketRate(AFFECTION) — is Purchase viable?
  D. Other market rates on CROWS (scan common tokens)
  E. Joey's current AFFECTION balance
  F. PulseX V2 factory: CROWS/WPLS and CROWS/AFFECTION pairs
  G. PulseX V1 factory: same pairs
  H. 9mm V2 factory: same pairs
  I. Top holders via PulseChain Scan API
  J. Summary & recommended acquisition path
"""
from web3 import Web3
import json, time, traceback

try:
    import requests
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

# -- RPC --
w3 = Web3(Web3.HTTPProvider("https://rpc.pulsechain.com", request_kwargs={"timeout": 30}))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# -- Addresses --
JOEY_WALLET    = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
CROWS          = Web3.to_checksum_address("0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1")
AFFECTION      = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")
WPLS           = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
WM             = Web3.to_checksum_address("0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29")
VOID_ADDR      = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")
GIBS_LAU       = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
GIBS_QING      = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
JOEY_YUE       = Web3.to_checksum_address("0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0")
ATROPA_ERC20   = Web3.to_checksum_address("0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6")
DAI_FROM_ETH   = Web3.to_checksum_address("0xefD766cCb38EaF1dfd701853BFCe31359239F305")
CHO            = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")

# DEX Factories
PULSEX_V1_FACTORY = Web3.to_checksum_address("0x1715a3E4A142d8b698131108995174F37aEBA10D")
PULSEX_V2_FACTORY = Web3.to_checksum_address("0x29eA7545DEf87022BAdc76323F373EA1e707C523")
NINEMM_V2_FACTORY = Web3.to_checksum_address("0xE26E7F6b5A43A667dBA42Cd9C829d5C75A8093b1")

FACTORIES = [
    ("PulseX V1", PULSEX_V1_FACTORY),
    ("PulseX V2", PULSEX_V2_FACTORY),
    ("9mm V2",    NINEMM_V2_FACTORY),
]

# Tokens to check market rates against
RATE_CHECK_TOKENS = [
    ("AFFECTION",  AFFECTION),
    ("WPLS",       WPLS),
    ("WM",         WM),
    ("VOID",       VOID_ADDR),
    ("Atropa",     ATROPA_ERC20),
    ("DAI",        DAI_FROM_ETH),
    ("GIBS_LAU",   GIBS_LAU),
    ("CHO",        CHO),
]

# Tokens to check DEX pairs against
DEX_PARTNER_TOKENS = [
    ("WPLS",       WPLS),
    ("AFFECTION",  AFFECTION),
    ("WM",         WM),
    ("Atropa",     ATROPA_ERC20),
    ("DAI",        DAI_FROM_ETH),
    ("VOID",       VOID_ADDR),
]

# -- ABIs --
ERC20_ABI = [
    {"inputs": [], "name": "name", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSupply", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxSupply", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "_a", "type": "address"}], "name": "GetMarketRate", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "Entropy", "outputs": [{"type": "uint64"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "allowance", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "owner", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

# Purchase function ABI (on DYSNOMIA tokens)
PURCHASE_ABI = [
    {"inputs": [{"name": "Token", "type": "address"}, {"name": "Amount", "type": "uint256"}],
     "name": "Purchase", "outputs": [], "stateMutability": "nonpayable", "type": "function"},
]

FACTORY_ABI = [
    {"inputs": [{"type": "address"}, {"type": "address"}], "name": "getPair",
     "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

PAIR_ABI = [
    {"inputs": [], "name": "token0", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "getReserves", "outputs": [{"type": "uint112"}, {"type": "uint112"}, {"type": "uint32"}], "stateMutability": "view", "type": "function"},
]

ZERO = "0x" + "0" * 40

# -- Helpers --
def safe_call(contract, func_name, *args):
    try:
        return getattr(contract.functions, func_name)(*args).call()
    except Exception as e:
        return None

def fmt_token(val, decimals=18):
    if val is None:
        return "N/A"
    return f"{val / 10**decimals:,.4f}"

def fmt_raw(val):
    if val is None:
        return "N/A"
    return f"{val:,}"

def is_contract(addr):
    try:
        code = w3.eth.get_code(Web3.to_checksum_address(addr))
        return len(code) > 2
    except:
        return False


# ============================================================================
# SECTION A: CROWS Basic Token State
# ============================================================================
print("\n" + "=" * 80)
print("SECTION A: CROWS BASIC TOKEN STATE")
print("=" * 80)

crows = w3.eth.contract(address=CROWS, abi=ERC20_ABI)

name       = safe_call(crows, "name")
symbol     = safe_call(crows, "symbol")
total      = safe_call(crows, "totalSupply")
maxs       = safe_call(crows, "maxSupply")
decs       = safe_call(crows, "decimals") or 18
entropy    = safe_call(crows, "Entropy")
owner_addr = safe_call(crows, "owner")

print(f"  Name:            {name}")
print(f"  Symbol:          {symbol}")
print(f"  Decimals:        {decs}")
print(f"  Total Supply:    {fmt_token(total, decs)} (raw: {fmt_raw(total)})")
if maxs is not None:
    max_scaled = maxs * 10**decs
    print(f"  Max Supply:      {fmt_token(max_scaled, decs)} (raw maxSupply: {fmt_raw(maxs)})")
    maxed = total is not None and total >= max_scaled
    print(f"  Maxed Out?       {'YES -- no more _mintToCap()' if maxed else 'NO -- _mintToCap() can still fire'}")
else:
    print(f"  Max Supply:      N/A (no maxSupply function)")
    maxed = False
print(f"  Entropy:         {entropy}")
print(f"  owner():         {owner_addr}")


# ============================================================================
# SECTION B: Key Balances
# ============================================================================
print("\n" + "=" * 80)
print("SECTION B: KEY CROWS BALANCES")
print("=" * 80)

self_bal   = safe_call(crows, "balanceOf", CROWS)
joey_bal   = safe_call(crows, "balanceOf", JOEY_WALLET)
gibs_bal   = safe_call(crows, "balanceOf", GIBS_LAU)
qing_bal   = safe_call(crows, "balanceOf", GIBS_QING)
yue_bal    = safe_call(crows, "balanceOf", JOEY_YUE)

print(f"  CROWS self-balance (balanceOf(CROWS)):  {fmt_token(self_bal, decs)} (raw: {fmt_raw(self_bal)})")
print(f"  Joey's wallet (EOA):                     {fmt_token(joey_bal, decs)} (raw: {fmt_raw(joey_bal)})")
print(f"  GIBS_LAU:                                {fmt_token(gibs_bal, decs)}")
print(f"  GIBS_QING:                               {fmt_token(qing_bal, decs)}")
print(f"  Joey's YUE wallet:                       {fmt_token(yue_bal, decs)}")

# Bouncer check: need 25 CROWS
print(f"\n  >>> Joey needs 25.0000 CROWS for bouncer access")
if joey_bal is not None:
    joey_crows_fmt = joey_bal / 10**decs
    if joey_crows_fmt >= 25.0:
        print(f"  >>> Joey ALREADY HAS ENOUGH ({joey_crows_fmt:.4f} >= 25)!")
    else:
        deficit = 25.0 - joey_crows_fmt
        print(f"  >>> Joey has {joey_crows_fmt:.4f} -- needs {deficit:.4f} more CROWS")


# ============================================================================
# SECTION C: CROWS Market Rates & Purchase Viability
# ============================================================================
print("\n" + "=" * 80)
print("SECTION C: CROWS MARKET RATES & PURCHASE VIABILITY")
print("=" * 80)

print("\n  Market rates set on CROWS contract:")
aff_rate = None
rates_found = []
for label, addr in RATE_CHECK_TOKENS:
    rate = safe_call(crows, "GetMarketRate", addr)
    if rate is not None and rate > 0:
        print(f"    {label:15s}: {fmt_token(rate, decs)} (raw: {fmt_raw(rate)})")
        rates_found.append((label, addr, rate))
        if addr == AFFECTION:
            aff_rate = rate
    else:
        print(f"    {label:15s}: 0 (not set)")

# Purchase viability analysis
print(f"\n  AFFECTION rate on CROWS: {fmt_token(aff_rate, decs) if aff_rate else '0 (NOT SET)'}")
print(f"  CROWS self-balance:      {fmt_token(self_bal, decs)}")

if aff_rate and aff_rate > 0 and self_bal and self_bal > 0:
    max_purchasable = self_bal  # 1:1 rate means self-balance is the limit
    print(f"\n  PURCHASE VIABLE!")
    print(f"  Max purchasable via AFFECTION: {fmt_token(max_purchasable, decs)}")
    print(f"  Joey needs 25 -- self-balance covers? {'YES' if max_purchasable >= 25 * 10**decs else 'NO'}")
elif aff_rate and aff_rate > 0:
    print(f"\n  PURCHASE BLOCKED -- AFFECTION rate is set but self-balance = 0")
    print(f"  The contract holds no CROWS to sell. Purchase() would fail.")
elif self_bal and self_bal > 0:
    print(f"\n  PURCHASE BLOCKED -- self-balance > 0 but no AFFECTION rate set")
    print(f"  Need AddMarketRate(AFFECTION, rate) to be called by an owner")
else:
    print(f"\n  PURCHASE BLOCKED -- both AFFECTION rate = 0 AND self-balance = 0")


# ============================================================================
# SECTION D: Joey's AFFECTION Balance
# ============================================================================
print("\n" + "=" * 80)
print("SECTION D: JOEY'S AFFECTION BALANCE")
print("=" * 80)

aff_contract = w3.eth.contract(address=AFFECTION, abi=ERC20_ABI)
joey_aff = safe_call(aff_contract, "balanceOf", JOEY_WALLET)
aff_total = safe_call(aff_contract, "totalSupply")
print(f"  Joey's AFFECTION balance: {fmt_token(joey_aff, decs)} (raw: {fmt_raw(joey_aff)})")
print(f"  AFFECTION total supply:   {fmt_token(aff_total, decs)}")

# Check if Joey has approved CROWS to spend his AFFECTION
# (For Purchase, CROWS.Purchase(AFFECTION, amount) calls AFFECTION.transferFrom(msg.sender, ...))
aff_allowance = None
try:
    aff_full_abi = ERC20_ABI + [
        {"inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
         "name": "allowance", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    ]
    aff_c2 = w3.eth.contract(address=AFFECTION, abi=aff_full_abi)
    aff_allowance = aff_c2.functions.allowance(JOEY_WALLET, CROWS).call()
    print(f"  AFFECTION allowance (Joey -> CROWS): {fmt_token(aff_allowance, decs)}")
except Exception as e:
    print(f"  AFFECTION allowance check failed: {e}")

if joey_aff and joey_aff > 0 and aff_rate and aff_rate > 0 and self_bal and self_bal > 0:
    can_buy = min(joey_aff, self_bal)
    print(f"\n  If Purchase is viable, Joey can buy up to: {fmt_token(can_buy, decs)} CROWS")
    print(f"  (limited by {'AFFECTION balance' if joey_aff < self_bal else 'CROWS self-balance'})")


# ============================================================================
# SECTION E: DEX Pair Discovery (PulseX V1, V2, 9mm)
# ============================================================================
print("\n" + "=" * 80)
print("SECTION E: DEX PAIR DISCOVERY")
print("=" * 80)

dex_pairs_found = []

for f_label, f_addr in FACTORIES:
    print(f"\n  {f_label} ({f_addr}):")
    factory = w3.eth.contract(address=f_addr, abi=FACTORY_ABI)

    for p_label, p_addr in DEX_PARTNER_TOKENS:
        try:
            pair = factory.functions.getPair(CROWS, p_addr).call()
            if pair != ZERO:
                pair_contract = w3.eth.contract(address=pair, abi=PAIR_ABI)
                try:
                    r0, r1, ts = pair_contract.functions.getReserves().call()
                    t0 = pair_contract.functions.token0().call()
                    t1 = pair_contract.functions.token1().call()

                    if t0.lower() == CROWS.lower():
                        crows_reserve, other_reserve = r0, r1
                    else:
                        crows_reserve, other_reserve = r1, r0

                    has_liquidity = crows_reserve > 0 and other_reserve > 0
                    liq_tag = "HAS LIQUIDITY" if has_liquidity else "EMPTY"

                    print(f"    CROWS/{p_label}: {pair} [{liq_tag}]")
                    print(f"      CROWS reserve: {fmt_token(crows_reserve, decs)}")
                    print(f"      {p_label} reserve: {fmt_token(other_reserve, decs)}")

                    if has_liquidity:
                        # Calculate price
                        price = other_reserve / crows_reserve if crows_reserve > 0 else 0
                        print(f"      Price: 1 CROWS = {price:.8f} {p_label}")
                        cost_25 = 25 * price * 10**decs  # approximate
                        print(f"      ~Cost for 25 CROWS: {fmt_token(int(cost_25), decs)} {p_label}")

                    dex_pairs_found.append({
                        "factory": f_label,
                        "pair": pair,
                        "partner": p_label,
                        "partner_addr": p_addr,
                        "crows_reserve": crows_reserve,
                        "other_reserve": other_reserve,
                        "has_liquidity": has_liquidity,
                    })

                except Exception as e:
                    print(f"    CROWS/{p_label}: {pair} -- reserves call failed: {e}")
                    dex_pairs_found.append({
                        "factory": f_label,
                        "pair": pair,
                        "partner": p_label,
                        "partner_addr": p_addr,
                        "crows_reserve": 0,
                        "other_reserve": 0,
                        "has_liquidity": False,
                    })
            else:
                print(f"    CROWS/{p_label}: no pair exists")
        except Exception as e:
            print(f"    CROWS/{p_label}: getPair() failed: {e}")


# ============================================================================
# SECTION F: PairCreated Event Scan (catch ALL CROWS pairs)
# ============================================================================
print("\n" + "=" * 80)
print("SECTION F: PAIRCREATED EVENT SCAN (ALL CROWS PAIRS)")
print("=" * 80)

PAIR_CREATED_TOPIC = "0x" + w3.keccak(text="PairCreated(address,address,address,uint256)").hex()
crows_padded = "0x" + CROWS[2:].lower().zfill(64)
all_found_pairs = set()

for f_label, f_addr in FACTORIES:
    print(f"\n  {f_label}:")
    for topic_pos in ["topic1", "topic2"]:
        try:
            topics = [PAIR_CREATED_TOPIC]
            if topic_pos == "topic1":
                topics.append(crows_padded)
            else:
                topics.extend([None, crows_padded])

            logs = w3.eth.get_logs({
                "address": f_addr,
                "topics": topics,
                "fromBlock": 0,
                "toBlock": "latest",
            })

            for log in logs:
                pair_addr = "0x" + log["data"].hex()[24:64]
                pair_addr = Web3.to_checksum_address(pair_addr)
                if pair_addr in all_found_pairs:
                    continue
                all_found_pairs.add(pair_addr)

                if topic_pos == "topic1":
                    other = "0x" + log["topics"][2].hex()[24:]
                else:
                    other = "0x" + log["topics"][1].hex()[24:]
                other = Web3.to_checksum_address(other)

                # Get other token name
                other_name = None
                try:
                    oc = w3.eth.contract(address=other, abi=ERC20_ABI)
                    other_name = safe_call(oc, "symbol")
                except:
                    pass

                # Get reserves
                try:
                    pc = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
                    r0, r1, _ = pc.functions.getReserves().call()
                    t0 = pc.functions.token0().call()
                    if t0.lower() == CROWS.lower():
                        cr, orr = r0, r1
                    else:
                        cr, orr = r1, r0
                    has_liq = cr > 0 and orr > 0
                    print(f"    Pair: {pair_addr} | CROWS/{other_name or other[:10]}")
                    print(f"      Other: {other} ({other_name})")
                    print(f"      CROWS reserve: {fmt_token(cr, decs)} | Other: {fmt_token(orr, decs)} | {'LIQUID' if has_liq else 'EMPTY'}")
                    if has_liq:
                        price = orr / cr if cr > 0 else 0
                        print(f"      Price: 1 CROWS = {price:.8f} {other_name or '???'}")
                except Exception as e:
                    print(f"    Pair: {pair_addr} | CROWS/{other_name or other[:10]} -- reserves failed: {e}")

        except Exception as e:
            # Try with a reduced block range if full scan fails
            try:
                latest = w3.eth.block_number
                logs = w3.eth.get_logs({
                    "address": f_addr,
                    "topics": topics,
                    "fromBlock": max(0, latest - 10_000_000),
                    "toBlock": "latest",
                })
                for log in logs:
                    pair_addr = "0x" + log["data"].hex()[24:64]
                    pair_addr = Web3.to_checksum_address(pair_addr)
                    if pair_addr not in all_found_pairs:
                        all_found_pairs.add(pair_addr)
                        print(f"    Found pair (recent): {pair_addr} (block {log['blockNumber']})")
            except:
                pass

if not all_found_pairs:
    print("  No PairCreated events found for CROWS on any factory")


# ============================================================================
# SECTION G: Top CROWS Holders (PulseChain Scan API)
# ============================================================================
print("\n" + "=" * 80)
print("SECTION G: TOP CROWS HOLDERS (PulseChain Scan API)")
print("=" * 80)

url = f"https://api.scan.pulsechain.com/api/v2/tokens/{CROWS}/holders"
try:
    resp = requests.get(url, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        items = data.get("items", [])
        print(f"  Total holders returned: {len(items)}")
        print()
        for i, holder in enumerate(items[:20]):
            h_addr = holder.get("address", {}).get("hash", "???")
            h_name = holder.get("address", {}).get("name", "")
            h_val = holder.get("value", "0")
            h_pct = float(h_val) / (total or 1) * 100
            h_val_fmt = fmt_token(int(h_val), decs)

            # Identify known addresses
            known = ""
            h_lower = h_addr.lower()
            if h_lower == CROWS.lower():
                known = " [SELF -- contract balance]"
            elif h_lower == JOEY_WALLET.lower():
                known = " [JOEY'S WALLET]"
            elif h_lower == GIBS_LAU.lower():
                known = " [GIBS_LAU]"
            elif h_lower == JOEY_YUE.lower():
                known = " [JOEY'S YUE]"
            elif h_lower == "0xebe9b8673d7096dcee26da7d9eaf6fc4ebe30980":
                known = " [NOUMENON]"
            elif h_lower == "0x7a20189b297343cf26d8548764b04891f37f3414":
                known = " [CREATOR WALLET]"
            elif h_lower == VOID_ADDR.lower():
                known = " [VOID]"

            # Check if it's a DEX pair or contract
            is_pair = False
            contract_tag = ""
            if is_contract(h_addr):
                try:
                    pc = w3.eth.contract(address=Web3.to_checksum_address(h_addr), abi=PAIR_ABI)
                    pc.functions.getReserves().call()
                    is_pair = True
                    contract_tag = " [DEX PAIR]"
                except:
                    contract_tag = " [CONTRACT]"

            name_tag = f" ({h_name})" if h_name else ""

            print(f"  #{i+1:2d}  {h_addr}{name_tag}{known}{contract_tag}")
            print(f"       Balance: {h_val_fmt} ({h_pct:.2f}%)")
    else:
        print(f"  API returned {resp.status_code}")
except Exception as e:
    print(f"  API error: {e}")


# ============================================================================
# SECTION H: Check CROWS _mintToCap status
# ============================================================================
print("\n" + "=" * 80)
print("SECTION H: CROWS MINT STATUS & GAME ACTION MINING")
print("=" * 80)

if maxs is not None:
    max_scaled = maxs * 10**decs
    remaining = max_scaled - total if total else 0
    print(f"  Total minted so far:   {fmt_token(total, decs)}")
    print(f"  Max supply cap:        {fmt_token(max_scaled, decs)}")
    print(f"  Remaining mintable:    {fmt_token(remaining, decs)}")
    if remaining > 0:
        print(f"  _mintToCap() still active -- each game action mints 1 CROWS")
        print(f"  (This applies if CROWS is the token on the action contract)")
    else:
        print(f"  FULLY MINTED -- no more _mintToCap()")
else:
    print(f"  maxSupply not available -- cannot determine mint status")


# ============================================================================
# SECTION I: Check if CROWS is mintable via game actions
# ============================================================================
print("\n" + "=" * 80)
print("SECTION I: IS CROWS MINTED BY GAME ACTIONS?")
print("=" * 80)

# CROWS is a social credential. Check what contract controls it.
# In DYSNOMIA pattern: VOID.Chat -> _mintToCap on VOID token
# CROWS might be minted by a different contract action.
# Check the CROWS contract for common Dysnomia patterns

# Check if CROWS has owners pattern
print("  Checking CROWS ownership and minting patterns:")

# Try to see if CROWS has common DYSNOMIA functions
DYSNOMIA_FUNCS = [
    ([], "Rod", [{"type": "address"}]),
    ([], "Cone", [{"type": "address"}]),
    ([], "Shio", [{"type": "address"}]),
    ([], "Type", [{"type": "string"}]),
]

extra_abi = ERC20_ABI + [
    {"inputs": [], "name": "Rod", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "Cone", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "Shio", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "Type", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "Xiao", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

crows_ext = w3.eth.contract(address=CROWS, abi=extra_abi)
for fname in ["Rod", "Cone", "Shio", "Type", "Xiao"]:
    val = safe_call(crows_ext, fname)
    if val is not None:
        print(f"    {fname}(): {val}")


# ============================================================================
# SECTION J: Summary & Recommended Acquisition Paths
# ============================================================================
print("\n" + "=" * 80)
print("SECTION J: SUMMARY & RECOMMENDED ACQUISITION PATHS")
print("=" * 80)

print(f"\n  TARGET: 25 CROWS at Joey's wallet ({JOEY_WALLET[:10]}...)")
joey_has = joey_bal / 10**decs if joey_bal else 0
print(f"  Joey currently holds: {joey_has:.4f} CROWS")
deficit = max(0, 25.0 - joey_has)
print(f"  Deficit: {deficit:.4f} CROWS")

print(f"\n  ACQUISITION PATHS:")
print(f"  {'─' * 60}")

# Path 1: Purchase via AFFECTION
print(f"\n  1. Purchase(AFFECTION) on CROWS contract:")
if aff_rate and aff_rate > 0 and self_bal and self_bal > 0:
    joey_aff_fmt = joey_aff / 10**decs if joey_aff else 0
    print(f"     STATUS: VIABLE")
    print(f"     AFFECTION rate: {fmt_token(aff_rate, decs)}")
    print(f"     CROWS self-balance: {fmt_token(self_bal, decs)}")
    print(f"     Joey has {joey_aff_fmt:.4f} AFFECTION -- {'ENOUGH' if joey_aff_fmt >= deficit else 'NOT ENOUGH'}")
    if joey_aff_fmt >= deficit:
        print(f"     >>> Steps: AFFECTION.approve(CROWS, {int(deficit*10**decs)})")
        print(f"     >>>        CROWS.Purchase(AFFECTION, {int(deficit*10**decs)})")
elif aff_rate and aff_rate > 0:
    print(f"     STATUS: BLOCKED -- rate set ({fmt_token(aff_rate, decs)}) but self-balance = 0")
    print(f"     The CROWS contract holds no tokens to sell.")
else:
    print(f"     STATUS: BLOCKED -- AFFECTION rate = {fmt_token(aff_rate, decs) if aff_rate else '0'}")
    print(f"     No AFFECTION market rate set on CROWS. Cannot use Purchase().")

# Path 2: DEX swap
print(f"\n  2. DEX swap (PulseX/9mm):")
liquid_pairs = [p for p in dex_pairs_found if p.get("has_liquidity")]
if liquid_pairs:
    print(f"     STATUS: VIABLE -- {len(liquid_pairs)} pair(s) with liquidity")
    for p in liquid_pairs:
        print(f"     {p['factory']} CROWS/{p['partner']}: pair {p['pair']}")
        print(f"       CROWS reserve: {fmt_token(p['crows_reserve'], decs)}")
        print(f"       {p['partner']} reserve: {fmt_token(p['other_reserve'], decs)}")
else:
    print(f"     STATUS: NO LIQUID PAIRS FOUND")
    if dex_pairs_found:
        print(f"     {len(dex_pairs_found)} pair(s) exist but all have zero reserves")
    else:
        print(f"     No DEX pairs exist for CROWS")

# Path 3: Ask Noumenon
print(f"\n  3. Ask Noumenon for gift:")
print(f"     Noumenon (0xEbE9B8...30980) is an active gifter.")
print(f"     Previously gifted Joey 100 AFFECTION.")
print(f"     May have CROWS to share.")

# Path 4: Game actions that mint CROWS
print(f"\n  4. Game actions that mint CROWS:")
if not maxed:
    print(f"     CROWS is not maxed ({fmt_token(total, decs)} / {fmt_token(max_scaled, decs) if maxs else 'unknown'})")
    print(f"     If there is a game action that triggers _mintToCap() on CROWS,")
    print(f"     it would mint 1 CROWS per call. Need to identify which action.")
else:
    print(f"     CROWS is FULLY MINTED -- no more _mintToCap() possible")

print(f"\n{'=' * 80}")
print("CROWS RECON COMPLETE")
print(f"{'=' * 80}")
