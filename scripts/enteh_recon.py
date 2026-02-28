#!/usr/bin/env python3
"""Recon script for player enteh (0xccE83CfF8B531EaDdcf11AB414C59DC046D1aAc7)"""

from web3 import Web3
from eth_utils import keccak
import time
import traceback

# --- Setup ---
w3 = Web3(Web3.HTTPProvider("https://rpc.pulsechain.com", request_kwargs={"timeout": 30}))
w3_read = Web3(Web3.HTTPProvider("https://rpc.pulsechain.com", request_kwargs={"timeout": 30}))

PLAYER = Web3.to_checksum_address("0xccE83CfF8B531EaDdcf11AB414C59DC046D1aAc7")

# Key addresses
CHO = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
CHAN = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
META = Web3.to_checksum_address("0xE77Bdae31b2219e032178d88504Cc0170a5b9B97")
CHEON = Web3.to_checksum_address("0x3d23084cA3F40465553797b5138CFC456E61FB5D")
SEI = Web3.to_checksum_address("0x3dC54d46e030C42979f33C9992348a990acb6067")
MAP = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
VOID = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")
CHOA = Web3.to_checksum_address("0x0f5a352fd4cA4850c2099C15B3600ff085B66197")

# SHIO tokens
FORNAX = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
FOMALHAUTE = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")

# Selectors
BEAT_SEL = keccak(text="Beat(uint256)")[:4].hex()
SU_SEL = keccak(text="Su(address)")[:4].hex()
TRANSFER_TOPIC = '0x' + keccak(text="Transfer(address,address,uint256)").hex()

print("=" * 70)
print("ENTEH PLAYER RECON")
print("=" * 70)

# ========== PART 1: Basic Player Info ==========
print("\n--- PART 1: Player Info ---")

# TX count
tx_count = w3.eth.get_transaction_count(PLAYER)
print(f"Player address: {PLAYER}")
print(f"TX count (nonce): {tx_count}")
print(f"PLS balance: {w3.from_wei(w3.eth.get_balance(PLAYER), 'ether'):.2f}")

# Get LAU token via CHO
cho_abi = [{"inputs":[{"name":"","type":"address"}],"name":"GetUserTokenAddress","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
cho = w3.eth.contract(address=CHO, abi=cho_abi)
try:
    lau_addr = cho.functions.GetUserTokenAddress(PLAYER).call()
    print(f"LAU token: {lau_addr}")
except Exception as e:
    lau_addr = None
    print(f"LAU token: ERROR - {e}")

# Get YUE via CHAN
chan_abi = [{"inputs":[{"name":"","type":"address"}],"name":"Yan","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"}]
chan = w3.eth.contract(address=CHAN, abi=chan_abi)
try:
    yue_addr = chan.functions.Yan(PLAYER).call()
    print(f"YUE wallet: {yue_addr}")
except Exception as e:
    yue_addr = None
    print(f"YUE wallet: ERROR - {e}")

# Get LAU details if found
ZERO = "0x0000000000000000000000000000000000000000"
lau_name_abi = [
    {"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"symbol","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"maxSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"","type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]

if lau_addr and lau_addr != ZERO:
    lau_contract = w3.eth.contract(address=lau_addr, abi=lau_name_abi)
    try:
        lau_name = lau_contract.functions.name().call()
        lau_sym = lau_contract.functions.symbol().call()
        lau_supply = lau_contract.functions.totalSupply().call()
        lau_max = lau_contract.functions.maxSupply().call()
        lau_player_bal = lau_contract.functions.balanceOf(PLAYER).call()
        print(f"LAU name: {lau_name} ({lau_sym})")
        print(f"LAU supply: {w3.from_wei(lau_supply, 'ether'):.0f} / {w3.from_wei(lau_max, 'ether'):.0f}")
        print(f"LAU balance (player): {w3.from_wei(lau_player_bal, 'ether'):.4f}")
    except Exception as e:
        print(f"LAU details: ERROR - {e}")

# ========== PART 1b: SHIO Balances ==========
print("\n--- SHIO Token Balances ---")

erc20_abi = [
    {"inputs":[{"name":"","type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]

shio_tokens = {
    "Fornax": FORNAX,
    "Fomalhaute": FOMALHAUTE,
    "CHO": CHO,
}

check_addrs = {"Player": PLAYER}
if lau_addr and lau_addr != ZERO:
    check_addrs["LAU"] = lau_addr
if yue_addr and yue_addr != ZERO:
    check_addrs["YUE"] = yue_addr

for token_name, token_addr in shio_tokens.items():
    tok = w3.eth.contract(address=token_addr, abi=erc20_abi)
    try:
        supply = tok.functions.totalSupply().call()
        print(f"\n  {token_name} ({token_addr[:10]}...) supply: {w3.from_wei(supply, 'ether'):.0f}")
    except:
        print(f"\n  {token_name} ({token_addr[:10]}...) supply: ERROR")

    for label, addr in check_addrs.items():
        try:
            bal = tok.functions.balanceOf(addr).call()
            if bal > 0:
                print(f"    {label} ({addr[:10]}...): {w3.from_wei(bal, 'ether'):.6f} ***HAS TOKENS***")
            else:
                print(f"    {label} ({addr[:10]}...): 0")
        except Exception as e:
            print(f"    {label}: ERROR - {e}")

# ========== PART 1c: Check QING venue ==========
print("\n--- QING Venue Check ---")

# Check if enteh has a QING via MAP
# We can try GetQing on the LAU
if lau_addr and lau_addr != ZERO:
    # Try to find their QING by checking MAP events or direct reads
    map_abi = [
        {"inputs":[{"name":"","type":"uint256"}],"name":"GetQing","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    ]

    # Check the LAU's Saat to get Waat
    lau_saat_abi = [
        {"inputs":[{"name":"","type":"uint256"}],"name":"Saat","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    ]
    lau_c = w3.eth.contract(address=lau_addr, abi=lau_saat_abi)
    try:
        saat0 = lau_c.functions.Saat(0).call()
        saat1 = lau_c.functions.Saat(1).call()
        saat2 = lau_c.functions.Saat(2).call()
        print(f"LAU Saat[0]: {saat0}")
        print(f"LAU Saat[1]: {saat1}")
        print(f"LAU Saat[2]: {saat2}")
    except Exception as e:
        print(f"LAU Saat: ERROR - {e}")

# ========== PART 1d: Additional token balances ==========
print("\n--- Key Token Balances ---")

extra_tokens = {
    "AFFECTION": "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D",
    "CROWS": "0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1",
    "WM (MV)": "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29",
    "VOID": VOID,
    "SEI": SEI,
    "META": META,
    "CHEON": CHEON,
    "CHOA": CHOA,
}

for tname, taddr in extra_tokens.items():
    taddr = Web3.to_checksum_address(taddr)
    tok = w3.eth.contract(address=taddr, abi=erc20_abi)
    for label, addr in check_addrs.items():
        try:
            bal = tok.functions.balanceOf(addr).call()
            if bal > 0:
                print(f"  {tname} @ {label}: {w3.from_wei(bal, 'ether'):.6f}")
        except:
            pass

# ========== PART 2: Scan for Beat/Su interactions ==========
print("\n" + "=" * 70)
print("PART 2: Scanning for META/CHEON interactions")
print("=" * 70)

print(f"\nBeat selector: 0x{BEAT_SEL}")
print(f"Su selector: 0x{SU_SEL}")
print(f"Transfer topic: {TRANSFER_TOPIC}")

# Strategy: Scan META Transfer events in recent blocks, then check if caller is enteh
current_block = w3.eth.block_number
print(f"\nCurrent block: {current_block}")

# Scan META Transfer events in chunks
# META mints via _mintToCap on each Beat call, so Transfer from 0x0 means a Beat was called
print("\n--- Scanning META Transfer events (last 100K blocks) ---")

found_txs = set()
CHUNK = 10000
start_block = current_block - 100000

for chunk_start in range(start_block, current_block, CHUNK):
    chunk_end = min(chunk_start + CHUNK - 1, current_block)
    try:
        logs = w3.eth.get_logs({
            "address": META,
            "topics": [TRANSFER_TOPIC],
            "fromBlock": chunk_start,
            "toBlock": chunk_end,
        })
        if logs:
            print(f"  Blocks {chunk_start}-{chunk_end}: {len(logs)} Transfer events")
            for log in logs:
                tx_hash = log['transactionHash'].hex()
                if tx_hash not in found_txs:
                    found_txs.add(tx_hash)
        else:
            print(f"  Blocks {chunk_start}-{chunk_end}: 0 events")
    except Exception as e:
        print(f"  Blocks {chunk_start}-{chunk_end}: ERROR - {e}")
    time.sleep(0.2)

print(f"\nTotal unique META txs found: {len(found_txs)}")

# Now check each META tx to see who called it and what function
if found_txs:
    print("\n--- Analyzing META transactions ---")
    enteh_txs = []
    all_meta_callers = {}

    for i, tx_hash in enumerate(sorted(found_txs)):
        try:
            tx = w3.eth.get_transaction(tx_hash)
            caller = tx['from']
            to_addr = tx['to'] if tx['to'] else "CONTRACT_CREATE"
            input_data = tx['input'].hex() if isinstance(tx['input'], bytes) else tx['input']
            selector = input_data[:10] if len(input_data) >= 10 else input_data

            # Track all callers
            caller_lower = caller.lower()
            if caller_lower not in all_meta_callers:
                all_meta_callers[caller_lower] = {"count": 0, "addr": caller, "selectors": set()}
            all_meta_callers[caller_lower]["count"] += 1
            all_meta_callers[caller_lower]["selectors"].add(selector)

            if caller.lower() == PLAYER.lower():
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                enteh_txs.append({
                    "hash": tx_hash,
                    "block": tx['blockNumber'],
                    "to": to_addr,
                    "selector": selector,
                    "status": receipt['status'],
                    "gas_used": receipt['gasUsed'],
                })
                print(f"  *** ENTEH TX: {tx_hash[:16]}... block={tx['blockNumber']} to={to_addr[:10]}... sel={selector} status={'OK' if receipt['status'] else 'FAIL'}")

            if (i + 1) % 20 == 0:
                print(f"  ... checked {i+1}/{len(found_txs)} txs")
        except Exception as e:
            print(f"  TX {tx_hash[:16]}...: ERROR - {e}")
        time.sleep(0.1)

    print(f"\n--- All META callers ---")
    for addr_lower, info in sorted(all_meta_callers.items(), key=lambda x: x[1]['count'], reverse=True):
        sels = ", ".join(info['selectors'])
        is_enteh = " *** ENTEH ***" if addr_lower == PLAYER.lower() else ""
        print(f"  {info['addr']}: {info['count']} calls [{sels}]{is_enteh}")

    if enteh_txs:
        print(f"\n--- ENTEH's META transactions ---")
        for tx in enteh_txs:
            print(f"  Block {tx['block']}: {tx['hash'][:20]}... | to={tx['to'][:14]}... | sel={tx['selector']} | status={'SUCCESS' if tx['status'] else 'REVERTED'} | gas={tx['gas_used']}")
    else:
        print("\n  No META transactions found from enteh")

# ========== PART 2b: Scan CHEON Transfer events ==========
print("\n--- Scanning CHEON Transfer events (last 100K blocks) ---")

cheon_txs = set()
for chunk_start in range(start_block, current_block, CHUNK):
    chunk_end = min(chunk_start + CHUNK - 1, current_block)
    try:
        logs = w3.eth.get_logs({
            "address": CHEON,
            "topics": [TRANSFER_TOPIC],
            "fromBlock": chunk_start,
            "toBlock": chunk_end,
        })
        if logs:
            print(f"  Blocks {chunk_start}-{chunk_end}: {len(logs)} Transfer events")
            for log in logs:
                tx_hash = log['transactionHash'].hex()
                cheon_txs.add(tx_hash)
        else:
            print(f"  Blocks {chunk_start}-{chunk_end}: 0 events")
    except Exception as e:
        print(f"  Blocks {chunk_start}-{chunk_end}: ERROR - {e}")
    time.sleep(0.2)

print(f"\nTotal unique CHEON txs found: {len(cheon_txs)}")

if cheon_txs:
    print("\n--- Checking CHEON txs for enteh ---")
    enteh_cheon = []
    all_cheon_callers = {}

    for i, tx_hash in enumerate(sorted(cheon_txs)):
        try:
            tx = w3.eth.get_transaction(tx_hash)
            caller = tx['from']
            to_addr = tx['to'] if tx['to'] else "CONTRACT_CREATE"
            input_data = tx['input'].hex() if isinstance(tx['input'], bytes) else tx['input']
            selector = input_data[:10] if len(input_data) >= 10 else input_data

            caller_lower = caller.lower()
            if caller_lower not in all_cheon_callers:
                all_cheon_callers[caller_lower] = {"count": 0, "addr": caller, "selectors": set()}
            all_cheon_callers[caller_lower]["count"] += 1
            all_cheon_callers[caller_lower]["selectors"].add(selector)

            if caller.lower() == PLAYER.lower():
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                enteh_cheon.append({
                    "hash": tx_hash,
                    "block": tx['blockNumber'],
                    "to": to_addr,
                    "selector": selector,
                    "status": receipt['status'],
                    "gas_used": receipt['gasUsed'],
                })
                print(f"  *** ENTEH TX: {tx_hash[:16]}... block={tx['blockNumber']} sel={selector} status={'OK' if receipt['status'] else 'FAIL'}")
        except Exception as e:
            pass
        time.sleep(0.1)

    print(f"\n--- All CHEON callers ---")
    for addr_lower, info in sorted(all_cheon_callers.items(), key=lambda x: x[1]['count'], reverse=True):
        sels = ", ".join(info['selectors'])
        is_enteh = " *** ENTEH ***" if addr_lower == PLAYER.lower() else ""
        print(f"  {info['addr']}: {info['count']} calls [{sels}]{is_enteh}")

    if enteh_cheon:
        print(f"\n--- ENTEH's CHEON transactions ---")
        for tx in enteh_cheon:
            print(f"  Block {tx['block']}: {tx['hash'][:20]}... | sel={tx['selector']} | status={'SUCCESS' if tx['status'] else 'REVERTED'} | gas={tx['gas_used']}")
    else:
        print("\n  No CHEON transactions found from enteh")

# ========== PART 3: Direct tx scan (last 50 txs from enteh) ==========
print("\n" + "=" * 70)
print("PART 3: Scanning enteh's recent transactions (by block trace)")
print("=" * 70)

# We'll scan recent blocks for txs FROM enteh
# First find which blocks enteh was active in by checking nonce progression
# Better: scan backwards from current block looking for txs from enteh

# Actually let's try a targeted approach: get enteh's transactions from
# recent blocks where they were active. We know tx_count so let's try
# scanning the last ~1000 blocks for any tx from this address.

print(f"\nEnteh nonce: {tx_count}")
print("Scanning last 5000 blocks for txs FROM enteh...")

enteh_recent_txs = []
scan_start = current_block - 5000

for block_num in range(current_block, scan_start, -1):
    try:
        block = w3.eth.get_block(block_num, full_transactions=True)
        for tx in block.transactions:
            if tx['from'].lower() == PLAYER.lower():
                to_addr = tx['to'] if tx['to'] else "CONTRACT_CREATE"
                input_data = tx['input'].hex() if isinstance(tx['input'], bytes) else tx['input']
                selector = input_data[:10] if len(input_data) >= 10 else "0x"

                enteh_recent_txs.append({
                    "hash": tx['hash'].hex(),
                    "block": tx['blockNumber'],
                    "to": to_addr,
                    "selector": selector,
                    "nonce": tx['nonce'],
                    "value": tx['value'],
                })
                print(f"  Found tx: block={block_num} nonce={tx['nonce']} to={str(to_addr)[:14]}... sel={selector}")
    except Exception as e:
        pass  # Skip blocks that error

    # Progress indicator
    if (current_block - block_num) % 1000 == 0 and block_num != current_block:
        print(f"  ... scanned {current_block - block_num} blocks, found {len(enteh_recent_txs)} txs")

    # If we found enough, or scanned enough
    if len(enteh_recent_txs) >= 50:
        print(f"  Found 50 txs, stopping scan")
        break

print(f"\nTotal recent enteh txs found: {len(enteh_recent_txs)}")

# Identify known contract targets
KNOWN = {
    META.lower(): "META",
    CHEON.lower(): "CHEON",
    CHO.lower(): "CHO",
    CHAN.lower(): "CHAN",
    SEI.lower(): "SEI",
    MAP.lower(): "MAP",
    VOID.lower(): "VOID",
    CHOA.lower(): "CHOA",
    FORNAX.lower(): "Fornax",
    FOMALHAUTE.lower(): "Fomalhaute",
    "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D".lower(): "AFFECTION",
    "0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1".lower(): "CROWS",
    "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29".lower(): "WM",
    "0x4757438723055f14A1Af5C9651C2E37730F41A9E".lower(): "YI",
    "0x43136735603d4060f226c279613a4dd97146937c".lower(): "SIU",
    "0xb702b3ec6d9de1011be963efe30a28b6ddfbe011".lower(): "YANG",
    "0x7e91d862a346659daeed93726e733c8c1347a225".lower(): "YAU",
    "0x5cc318d0c01fed5942b5ed2f53db07727d36e261".lower(): "ZHOU",
    "0x24e62c39e34d7fe2b7df1162e1344eb6eb3b3e15".lower(): "ZHENG",
    "0x4Df51741F2926525A21bF63E4769bA70633D2792".lower(): "XIE",
    "0x7f4a4DD4a6f233d2D82BE38b2F9fc0Fef46f25FA".lower(): "XIA",
    "0xc48B0a4E79eF302c8Eb5be71F562d08fB8E6A3d8".lower(): "MAI",
    "0x4d9Ce396BE95dbc5F71808c38107eB7422FD9a03".lower(): "QI",
    "0xEe25Ccd41671F3B67d660cf6532085586aec8457".lower(): "PANG",
    "0xCbAdd3C3957Bd9D6C036863CB053FEccf3D53338".lower(): "ZI",
    "0x29A924D9B0233026B9844f2aFeB202F1791D7593".lower(): "HECKE",
    "0x1574c84Ec7fA78fC6C749e1d242dbde163675e72".lower(): "RING",
}

if lau_addr and lau_addr != ZERO:
    KNOWN[lau_addr.lower()] = "enteh_LAU"
if yue_addr and yue_addr != ZERO:
    KNOWN[yue_addr.lower()] = "enteh_YUE"

if enteh_recent_txs:
    print("\n--- Enteh's recent transactions (decoded) ---")
    for tx in sorted(enteh_recent_txs, key=lambda x: x['block']):
        to_str = tx['to']
        if isinstance(to_str, str):
            label = KNOWN.get(to_str.lower(), "UNKNOWN")
            to_display = f"{label}({to_str[:10]}...)"
        else:
            to_display = str(to_str)

        val_str = f" val={w3.from_wei(tx['value'], 'ether'):.2f}" if tx['value'] > 0 else ""
        print(f"  Block {tx['block']} nonce={tx['nonce']}: {to_display} sel={tx['selector']}{val_str}")

print("\n" + "=" * 70)
print("RECON COMPLETE")
print("=" * 70)
