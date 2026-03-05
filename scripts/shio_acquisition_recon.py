#!/usr/bin/env python3
"""
SHIO Acquisition Recon — Find all paths to acquire Fornax, Fomalhaute, CHO tokens.

These three SHIO tokens are required at GIBS_LAU and GIBS_QING for META.Beat()
to succeed. Without them, Beat reverts with division-by-zero.

Checks:
  A. Token state & Purchase viability (self-balance, market rates)
  B. DEX factory pair discovery (PulseX V1/V2, 9mm)
  C. PairCreated event scan (catch ALL pairs)
  D. Top holders via PulseChain Scan API
  E. Enteh's SHIO source trace (Transfer events)
  F. Summary table
"""
from web3 import Web3
import json, time, traceback
try:
    import requests
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

# ── RPC ──────────────────────────────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider("https://rpc.pulsechain.com", request_kwargs={"timeout": 30}))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

# ── Addresses ────────────────────────────────────────────────────────────────
JOEY_WALLET    = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
GIBS_LAU       = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
GIBS_QING      = Web3.to_checksum_address("0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35")
JOEY_YUE       = Web3.to_checksum_address("0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0")
AFFECTION      = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D")

# SHIO tokens needed for Beat
FORNAX         = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
FOMALHAUTE     = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")
CHO            = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")

SHIO_TOKENS = [
    ("Fornax",     FORNAX),
    ("Fomalhaute", FOMALHAUTE),
    ("CHO",        CHO),
]

# Enteh (reference player who successfully calls Beat)
ENTEH_EOA = Web3.to_checksum_address("0x18F621662D6A1f23700EA32D146B32195DC33111")
ENTEH_LAU = Web3.to_checksum_address("0xccE83CfF8B531EaDdcf11AB414C59DC046D1aAc7")

# DEX Factories
PULSEX_V1_FACTORY = Web3.to_checksum_address("0x1715a3E4A142d8b698131108995174F37aEBA10D")
PULSEX_V2_FACTORY = Web3.to_checksum_address("0x29eA7545DEf87022BAdc76323F373EA1e707C523")
NINEMM_V2_FACTORY = Web3.to_checksum_address("0xE26E7F6b5A43A667dBA42Cd9C829d5C75A8093b1")

FACTORIES = [
    ("PulseX V1", PULSEX_V1_FACTORY),
    ("PulseX V2", PULSEX_V2_FACTORY),
    ("9mm V2",    NINEMM_V2_FACTORY),
]

# Common DEX partner tokens
WPLS           = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")
DAI_FROM_ETH   = Web3.to_checksum_address("0xefD766cCb38EaF1dfd701853BFCe31359239F305")
ATROPA_ERC20   = Web3.to_checksum_address("0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6")
WM             = Web3.to_checksum_address("0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29")
CROWS          = Web3.to_checksum_address("0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1")
VOID_ADDR      = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")

PARTNER_TOKENS = [
    ("WPLS",       WPLS),
    ("DAI",        DAI_FROM_ETH),
    ("AFFECTION",  AFFECTION),
    ("Atropa",     ATROPA_ERC20),
    ("WM",         WM),
    ("CROWS",      CROWS),
    ("VOID",       VOID_ADDR),
]

# ── ABIs ─────────────────────────────────────────────────────────────────────
ERC20_ABI = [
    {"inputs": [], "name": "name", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol", "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSupply", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxSupply", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "decimals", "outputs": [{"type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "_a", "type": "address"}], "name": "GetMarketRate", "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "Entropy", "outputs": [{"type": "uint64"}], "stateMutability": "view", "type": "function"},
]

FACTORY_ABI = [
    {"inputs": [{"type": "address"}, {"type": "address"}], "name": "getPair", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

PAIR_ABI = [
    {"inputs": [], "name": "token0", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "token1", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "getReserves", "outputs": [{"type": "uint112"}, {"type": "uint112"}, {"type": "uint32"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "factory", "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

ZERO = "0x" + "0" * 40

# ── Helpers ──────────────────────────────────────────────────────────────────
def safe_call(contract, func_name, *args):
    try:
        return getattr(contract.functions, func_name)(*args).call()
    except Exception:
        return None

def fmt_token(val, decimals=18):
    if val is None:
        return "N/A"
    return f"{val / 10**decimals:,.3f}"

def is_contract(addr):
    try:
        code = w3.eth.get_code(Web3.to_checksum_address(addr))
        return len(code) > 2
    except:
        return False

# ══════════════════════════════════════════════════════════════════════════════
# SECTION A: Token State & Purchase Viability
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("SECTION A: TOKEN STATE & PURCHASE VIABILITY")
print("=" * 80)

summary = {}

for label, addr in SHIO_TOKENS:
    print(f"\n{'─' * 60}")
    print(f"  {label} ({addr})")
    print(f"{'─' * 60}")

    c = w3.eth.contract(address=addr, abi=ERC20_ABI)

    name = safe_call(c, "name")
    symbol = safe_call(c, "symbol")
    total = safe_call(c, "totalSupply")
    maxs = safe_call(c, "maxSupply")
    decs = safe_call(c, "decimals") or 18
    self_bal = safe_call(c, "balanceOf", addr)
    entropy = safe_call(c, "Entropy")

    print(f"  Name:         {name}")
    print(f"  Symbol:       {symbol}")
    print(f"  Total Supply: {fmt_token(total, decs)}  (raw: {total})")
    print(f"  Max Supply:   {maxs}  (cap: {fmt_token(maxs * 10**decs if maxs else 0, decs)})")
    print(f"  Maxed Out?    {'YES' if total and maxs and total >= maxs * 10**decs else 'NO — _mintToCap() can still fire!'}")
    print(f"  Self-Balance: {fmt_token(self_bal, decs)}  (raw: {self_bal})")
    print(f"  Entropy:      {entropy}")

    # Purchase viability
    can_purchase = False
    aff_rate = safe_call(c, "GetMarketRate", AFFECTION)
    print(f"\n  AFFECTION Rate: {fmt_token(aff_rate, decs)} ({aff_rate})")

    if aff_rate and aff_rate > 0 and self_bal and self_bal > 0:
        can_purchase = True
        max_buy = self_bal  # Can buy up to self-balance
        print(f"  ✅ Purchase(AFFECTION) AVAILABLE — max buy: {fmt_token(max_buy, decs)}")
    elif aff_rate and aff_rate > 0:
        print(f"  ❌ Purchase blocked — rate set but self-balance = 0")
    else:
        print(f"  ❌ Purchase blocked — no AFFECTION rate")

    # Check other market rates
    print(f"\n  Other Market Rates:")
    rate_tokens = PARTNER_TOKENS + [("Fornax", FORNAX), ("Fomalhaute", FOMALHAUTE), ("CHO", CHO)]
    for rt_label, rt_addr in rate_tokens:
        if rt_addr == addr:
            continue
        rate = safe_call(c, "GetMarketRate", rt_addr)
        if rate and rate > 0:
            print(f"    {rt_label}: {fmt_token(rate, decs)}")

    # Balances at Joey's addresses
    print(f"\n  Joey's Balances:")
    for blabel, baddr in [("JOEY_WALLET", JOEY_WALLET), ("GIBS_LAU", GIBS_LAU), ("GIBS_QING", GIBS_QING), ("JOEY_YUE", JOEY_YUE)]:
        bal = safe_call(c, "balanceOf", baddr)
        print(f"    {blabel}: {fmt_token(bal, decs)}")

    # Enteh's balances for comparison
    print(f"\n  Enteh's Balances:")
    for blabel, baddr in [("ENTEH_EOA", ENTEH_EOA), ("ENTEH_LAU", ENTEH_LAU)]:
        bal = safe_call(c, "balanceOf", baddr)
        print(f"    {blabel}: {fmt_token(bal, decs)}")

    summary[label] = {
        "addr": addr,
        "total": total,
        "max": maxs,
        "maxed": total and maxs and total >= maxs * 10**decs,
        "self_bal": self_bal,
        "aff_rate": aff_rate,
        "can_purchase": can_purchase,
        "entropy": entropy,
        "dex_pairs": [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION B: DEX Factory Pair Discovery
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("SECTION B: DEX FACTORY PAIR DISCOVERY")
print("=" * 80)

for label, addr in SHIO_TOKENS:
    print(f"\n{'─' * 60}")
    print(f"  {label} Pairs")
    print(f"{'─' * 60}")

    for f_label, f_addr in FACTORIES:
        factory = w3.eth.contract(address=f_addr, abi=FACTORY_ABI)
        for p_label, p_addr in PARTNER_TOKENS + [("Fornax", FORNAX), ("Fomalhaute", FOMALHAUTE), ("CHO", CHO)]:
            if p_addr == addr:
                continue
            try:
                pair = factory.functions.getPair(addr, p_addr).call()
                if pair != ZERO:
                    pair_contract = w3.eth.contract(address=pair, abi=PAIR_ABI)
                    try:
                        r0, r1, ts = pair_contract.functions.getReserves().call()
                        t0 = pair_contract.functions.token0().call()
                        t1 = pair_contract.functions.token1().call()
                        # Identify which reserve is the SHIO token
                        if t0.lower() == addr.lower():
                            shio_reserve, other_reserve = r0, r1
                            other_token = t1
                        else:
                            shio_reserve, other_reserve = r1, r0
                            other_token = t0
                        print(f"  ✅ {f_label} | {label}/{p_label}")
                        print(f"     Pair: {pair}")
                        print(f"     {label} reserve: {fmt_token(shio_reserve)} | {p_label} reserve: {fmt_token(other_reserve)}")
                        summary[label]["dex_pairs"].append({
                            "factory": f_label,
                            "pair": pair,
                            "partner": p_label,
                            "partner_addr": p_addr,
                            "shio_reserve": shio_reserve,
                            "other_reserve": other_reserve,
                        })
                    except Exception as e:
                        print(f"  ⚠️  {f_label} | {label}/{p_label} — pair {pair} but reserves failed: {e}")
                        summary[label]["dex_pairs"].append({
                            "factory": f_label,
                            "pair": pair,
                            "partner": p_label,
                            "partner_addr": p_addr,
                            "shio_reserve": 0,
                            "other_reserve": 0,
                        })
            except Exception:
                pass  # No pair exists


# ══════════════════════════════════════════════════════════════════════════════
# SECTION C: PairCreated Event Scan
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("SECTION C: PAIRCREATED EVENT SCAN")
print("=" * 80)

PAIR_CREATED_TOPIC = "0x" + w3.keccak(text="PairCreated(address,address,address,uint256)").hex()

for label, addr in SHIO_TOKENS:
    print(f"\n{'─' * 60}")
    print(f"  {label} — Scanning PairCreated events")
    print(f"{'─' * 60}")

    token_padded = "0x" + addr[2:].lower().zfill(64)
    found_pairs = set()

    for f_label, f_addr in FACTORIES:
        # Try scanning for token as topic1 (token0)
        for topic_pos in ["topic1", "topic2"]:
            try:
                topics = [PAIR_CREATED_TOPIC]
                if topic_pos == "topic1":
                    topics.append(token_padded)
                else:
                    topics.extend([None, token_padded])

                logs = w3.eth.get_logs({
                    "address": f_addr,
                    "topics": topics,
                    "fromBlock": 0,
                    "toBlock": "latest",
                })

                for log in logs:
                    pair_addr = "0x" + log["data"].hex()[24:64]
                    pair_addr = Web3.to_checksum_address(pair_addr)
                    if pair_addr not in found_pairs:
                        found_pairs.add(pair_addr)
                        # Get other token
                        if topic_pos == "topic1":
                            other = "0x" + log["topics"][2].hex()[24:]
                        else:
                            other = "0x" + log["topics"][1].hex()[24:]
                        other = Web3.to_checksum_address(other)

                        # Try to get name of other token
                        other_name = None
                        try:
                            other_c = w3.eth.contract(address=other, abi=ERC20_ABI)
                            other_name = safe_call(other_c, "symbol")
                        except:
                            pass

                        # Check reserves
                        try:
                            pc = w3.eth.contract(address=pair_addr, abi=PAIR_ABI)
                            r0, r1, _ = pc.functions.getReserves().call()
                            t0 = pc.functions.token0().call()
                            if t0.lower() == addr.lower():
                                shio_r, other_r = r0, r1
                            else:
                                shio_r, other_r = r1, r0
                            print(f"  ✅ {f_label} | {label}/{other_name or other[:10]}")
                            print(f"     Pair: {pair_addr}")
                            print(f"     Other: {other} ({other_name})")
                            print(f"     Reserves: {label}={fmt_token(shio_r)} | Other={fmt_token(other_r)}")
                        except Exception as e:
                            print(f"  ⚠️  {f_label} | Pair {pair_addr} — reserves failed: {e}")

            except Exception as e:
                # RPC may not support fromBlock=0, try recent range
                if "range" in str(e).lower() or "10000" in str(e):
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
                            if pair_addr not in found_pairs:
                                found_pairs.add(pair_addr)
                                print(f"  Found pair: {pair_addr} (block {log['blockNumber']})")
                    except:
                        pass

    if not found_pairs:
        print(f"  No PairCreated events found for {label}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION D: Top Holders via PulseChain Scan API
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("SECTION D: TOP HOLDERS (PulseChain Scan API)")
print("=" * 80)

for label, addr in SHIO_TOKENS:
    print(f"\n{'─' * 60}")
    print(f"  {label} Top Holders")
    print(f"{'─' * 60}")

    # Try Blockscout V2 API first
    url = f"https://api.scan.pulsechain.com/api/v2/tokens/{addr}/holders"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            for i, holder in enumerate(items[:15]):
                h_addr = holder.get("address", {}).get("hash", "???")
                h_name = holder.get("address", {}).get("name", "")
                h_val = holder.get("value", "0")
                h_pct = float(h_val) / (summary[label]["total"] or 1) * 100
                h_val_fmt = fmt_token(int(h_val))

                # Check if it's a contract (potential DEX pair)
                is_pair = False
                if is_contract(h_addr):
                    try:
                        pc = w3.eth.contract(address=Web3.to_checksum_address(h_addr), abi=PAIR_ABI)
                        pc.functions.getReserves().call()
                        is_pair = True
                    except:
                        pass

                pair_tag = " [DEX PAIR!]" if is_pair else ""
                contract_tag = " [CONTRACT]" if is_contract(h_addr) and not is_pair else ""
                name_tag = f" ({h_name})" if h_name else ""

                print(f"  #{i+1:2d}  {h_addr}{name_tag}{contract_tag}{pair_tag}")
                print(f"       Balance: {h_val_fmt} ({h_pct:.1f}%)")
        else:
            print(f"  API returned {resp.status_code}")
    except Exception as e:
        print(f"  API error: {e}")

    time.sleep(0.5)  # Rate limit


# ══════════════════════════════════════════════════════════════════════════════
# SECTION E: Enteh's SHIO Source Trace
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("SECTION E: ENTEH'S SHIO SOURCE TRACE")
print("=" * 80)

TRANSFER_TOPIC = "0x" + w3.keccak(text="Transfer(address,address,uint256)").hex()

for label, addr in SHIO_TOKENS:
    print(f"\n{'─' * 60}")
    print(f"  {label} → Enteh EOA ({ENTEH_EOA[:10]}...)")
    print(f"{'─' * 60}")

    enteh_padded = "0x" + ENTEH_EOA[2:].lower().zfill(64)

    latest = w3.eth.block_number
    chunk = 5_000_000
    start = 17_000_000  # PulseChain started around here

    transfers = []

    while start < latest:
        end = min(start + chunk - 1, latest)
        try:
            logs = w3.eth.get_logs({
                "address": addr,
                "topics": [TRANSFER_TOPIC, None, enteh_padded],
                "fromBlock": start,
                "toBlock": end,
            })
            for log in logs:
                from_addr = "0x" + log["topics"][1].hex()[24:]
                amount = int(log["data"].hex(), 16)
                transfers.append({
                    "from": Web3.to_checksum_address(from_addr),
                    "amount": amount,
                    "block": log["blockNumber"],
                    "tx": log["transactionHash"].hex(),
                })
        except Exception as e:
            # Try smaller chunks
            sub_chunk = chunk // 5
            sub_start = start
            while sub_start < end:
                sub_end = min(sub_start + sub_chunk - 1, end)
                try:
                    logs = w3.eth.get_logs({
                        "address": addr,
                        "topics": [TRANSFER_TOPIC, None, enteh_padded],
                        "fromBlock": sub_start,
                        "toBlock": sub_end,
                    })
                    for log in logs:
                        from_addr = "0x" + log["topics"][1].hex()[24:]
                        amount = int(log["data"].hex(), 16)
                        transfers.append({
                            "from": Web3.to_checksum_address(from_addr),
                            "amount": amount,
                            "block": log["blockNumber"],
                            "tx": log["transactionHash"].hex(),
                        })
                except Exception as e2:
                    print(f"    Chunk {sub_start}-{sub_end} failed: {e2}")
                sub_start = sub_end + 1
                time.sleep(0.2)
        start = end + 1
        time.sleep(0.2)

    if transfers:
        print(f"  Found {len(transfers)} transfers:")
        for t in transfers:
            from_label = "SELF/Purchase" if t["from"].lower() == addr.lower() else \
                         "MINT" if t["from"] == ZERO else \
                         t["from"][:10] + "..."

            # Check if from address is a contract
            if t["from"].lower() != addr.lower() and t["from"] != ZERO:
                if is_contract(t["from"]):
                    try:
                        fc = w3.eth.contract(address=t["from"], abi=ERC20_ABI)
                        fname = safe_call(fc, "name")
                        if fname:
                            from_label = f"{t['from'][:10]}... ({fname})"
                    except:
                        pass

            print(f"    Block {t['block']:>10,} | From: {from_label:40s} | Amount: {fmt_token(t['amount'])}")
            print(f"      TX: {t['tx']}")
    else:
        print(f"  No Transfer events found to enteh's EOA")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION F: SUMMARY TABLE
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("SECTION F: SUMMARY & RECOMMENDED ACQUISITION PATHS")
print("=" * 80)

print(f"\n{'Token':<12} {'Self-Bal':>12} {'Maxed?':>8} {'Purchase?':>12} {'DEX Pairs':>10} {'Path'}")
print("─" * 80)

for label, info in summary.items():
    dex_count = len(info["dex_pairs"])
    dex_with_liq = sum(1 for p in info["dex_pairs"] if p.get("shio_reserve", 0) > 0)

    path = "???"
    if info["can_purchase"]:
        path = "Purchase(AFFECTION) ✅"
    elif dex_with_liq > 0:
        path = f"DEX swap ({dex_with_liq} pairs) ✅"
    elif not info["maxed"]:
        path = "Game actions → mintToCap → Purchase"
    else:
        path = "Need transfer from holder"

    print(f"{label:<12} {fmt_token(info['self_bal']):>12} {'YES' if info['maxed'] else 'NO':>8} "
          f"{'YES ✅' if info['can_purchase'] else 'NO ❌':>12} "
          f"{dex_count:>10} {path}")

# Minimum amounts needed
print(f"\n{'─' * 60}")
print("  MINIMUM SHIO AMOUNTS FOR BEAT:")
print(f"{'─' * 60}")

for label, addr in SHIO_TOKENS:
    # Read entropy values
    lau_c = w3.eth.contract(address=GIBS_LAU, abi=ERC20_ABI)
    qing_c = w3.eth.contract(address=GIBS_QING, abi=ERC20_ABI)

    lau_entropy = safe_call(lau_c, "Entropy")
    qing_entropy = safe_call(qing_c, "Entropy")

    if label in ("Fornax", "CHO"):
        # XIE.Power: Fornax.balanceOf(LAU) / Alpha.Entropy  (needs >= Entropy)
        # ZI.Spin:   CHO.balanceOf(LAU) / Alpha.Entropy     (needs >= Entropy)
        min_lau = lau_entropy if lau_entropy else "UNKNOWN"
        min_qing = qing_entropy if qing_entropy else "UNKNOWN"
        print(f"  {label}: min at LAU = {min_lau} wei ({fmt_token(min_lau) if isinstance(min_lau, int) else 'N/A'})")
        print(f"  {label}: min at QING = {min_qing} wei ({fmt_token(min_qing) if isinstance(min_qing, int) else 'N/A'})")
    else:
        # XIA.Charge: modExp(_b, _e, Fomalhaute.balanceOf(LAU))  — just needs > 0
        print(f"  {label}: min at LAU = 1 wei (just needs > 0 for modExp modulus)")

print(f"\n  Joey's AFFECTION balance: {fmt_token(safe_call(w3.eth.contract(address=AFFECTION, abi=ERC20_ABI), 'balanceOf', JOEY_WALLET))}")
print(f"\n{'═' * 80}")
print("RECON COMPLETE")
print(f"{'═' * 80}")
