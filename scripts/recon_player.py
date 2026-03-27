#!/usr/bin/env python3
"""
Generalized player recon script for the Dysnomia ecosystem on PulseChain.

Merges functionality from enteh_recon.py and enteh_zuo_check.py into a single
tool that works for any player address.

Usage:
    # Full recon on a player
    python3 scripts/recon_player.py --address 0xccE83CfF8B531EaDdcf11AB414C59DC046D1aAc7

    # Adjust block scan range (default 100000)
    python3 scripts/recon_player.py --address 0x... --blocks 50000

    # Skip the slow TX scanning parts (Parts 2 and 3)
    python3 scripts/recon_player.py --address 0x... --skip-txscan

Parts:
    1. Basic player info: LAU, YUE, SHIO balances, QING venue, token balances,
       ZUO/Zurich balances, Beat dry-run
    2. META/CHEON Transfer event scanning (finds Beat/Su callers)
    3. Recent TX scanning (last 5000 blocks by default)
"""

import argparse
import time
import traceback

from web3 import Web3
from eth_utils import keccak

# ---------------------------------------------------------------------------
# RPC setup (per project convention: g4mm4.io for reads)
# ---------------------------------------------------------------------------
READ_RPC = "https://rpc-pulsechain.g4mm4.io"
w3 = Web3(Web3.HTTPProvider(READ_RPC, request_kwargs={"timeout": 30}))

# ---------------------------------------------------------------------------
# Ecosystem constants (NOT player-specific)
# ---------------------------------------------------------------------------
CHO        = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
CHAN       = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
META       = Web3.to_checksum_address("0xE77Bdae31b2219e032178d88504Cc0170a5b9B97")
CHEON      = Web3.to_checksum_address("0x3d23084cA3F40465553797b5138CFC456E61FB5D")
SEI        = Web3.to_checksum_address("0x3dC54d46e030C42979f33C9992348a990acb6067")
MAP        = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
VOID       = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")
CHOA       = Web3.to_checksum_address("0x0f5a352fd4cA4850c2099C15B3600ff085B66197")
FORNAX     = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
FOMALHAUTE = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")

# ZUO / Zurich
ZUO_QING   = Web3.to_checksum_address("0xb0Ba7D36B7F0505879179ecE7401F24eB653c6E1")
ZUO_TOKEN  = Web3.to_checksum_address("0x583d1C1427308f7f96BFd3E0d7A3F9674D8BF8ec")

ZERO = "0x0000000000000000000000000000000000000000"

# Selectors
BEAT_SEL = keccak(text="Beat(uint256)")[:4].hex()
SU_SEL   = keccak(text="Su(address)")[:4].hex()
TRANSFER_TOPIC = '0x' + keccak(text="Transfer(address,address,uint256)").hex()

# Known contract addresses for TX target labelling
KNOWN_CONTRACTS = {
    META.lower():        "META",
    CHEON.lower():       "CHEON",
    CHO.lower():         "CHO",
    CHAN.lower():         "CHAN",
    SEI.lower():         "SEI",
    MAP.lower():         "MAP",
    VOID.lower():        "VOID",
    CHOA.lower():        "CHOA",
    FORNAX.lower():      "Fornax",
    FOMALHAUTE.lower():  "Fomalhaute",
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

# ---------------------------------------------------------------------------
# Minimal ABIs
# ---------------------------------------------------------------------------
ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "totalSupply",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "name",
     "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "symbol",
     "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
    {"inputs": [], "name": "maxSupply",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

CHO_ABI = [
    {"inputs": [{"name": "", "type": "address"}], "name": "GetUserTokenAddress",
     "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

CHAN_ABI = [
    {"inputs": [{"name": "", "type": "address"}], "name": "Yan",
     "outputs": [{"type": "address"}], "stateMutability": "view", "type": "function"},
]

CHOA_ABI = [
    {"inputs": [{"name": "Currency", "type": "address"}], "name": "Yuan",
     "outputs": [{"name": "Bae", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

SAAT_ABI = [
    {"inputs": [{"name": "", "type": "uint256"}], "name": "Saat",
     "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"},
]

META_ABI = [
    {"inputs": [{"name": "QingWaat", "type": "uint256"}], "name": "Beat",
     "outputs": [{"name": "Dione", "type": "uint256"}, {"name": "Charge", "type": "uint256"},
                 {"name": "Deimos", "type": "uint256"}, {"name": "Yeo", "type": "uint256"}],
     "stateMutability": "nonpayable", "type": "function"},
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def W(v):
    """Format a wei value to ether with 6 decimals."""
    return f"{v / 1e18:.6f}" if isinstance(v, int) else str(v)


def resolve_player(player_addr):
    """Resolve a player's LAU and YUE addresses from on-chain contracts."""
    cho = w3.eth.contract(address=CHO, abi=CHO_ABI)
    chan = w3.eth.contract(address=CHAN, abi=CHAN_ABI)

    lau_addr = None
    yue_addr = None

    try:
        lau_addr = cho.functions.GetUserTokenAddress(player_addr).call()
        if lau_addr == ZERO:
            lau_addr = None
    except Exception as e:
        print(f"  LAU lookup error: {e}")

    try:
        yue_addr = chan.functions.Yan(player_addr).call()
        if yue_addr == ZERO:
            yue_addr = None
    except Exception as e:
        print(f"  YUE lookup error: {e}")

    return lau_addr, yue_addr


def build_check_addrs(player_addr, lau_addr, yue_addr):
    """Build dict of address labels to check balances for."""
    addrs = {"Player": player_addr}
    if lau_addr:
        addrs["LAU"] = lau_addr
    if yue_addr:
        addrs["YUE"] = yue_addr
    return addrs


# ===========================================================================
# PART 1: Basic player info
# ===========================================================================

def part1_player_info(player_addr):
    """Gather and display basic player information."""
    print("=" * 70)
    print("PLAYER RECON")
    print("=" * 70)

    print(f"\n--- PART 1: Player Info ---")

    # TX count and PLS balance
    tx_count = w3.eth.get_transaction_count(player_addr)
    pls_balance = w3.from_wei(w3.eth.get_balance(player_addr), 'ether')
    print(f"Player address: {player_addr}")
    print(f"TX count (nonce): {tx_count}")
    print(f"PLS balance: {pls_balance:.2f}")

    # Resolve LAU and YUE
    lau_addr, yue_addr = resolve_player(player_addr)
    print(f"LAU token: {lau_addr or 'NOT FOUND'}")
    print(f"YUE wallet: {yue_addr or 'NOT FOUND'}")

    # LAU details
    if lau_addr:
        lau_contract = w3.eth.contract(address=lau_addr, abi=ERC20_ABI)
        try:
            lau_name = lau_contract.functions.name().call()
            lau_sym = lau_contract.functions.symbol().call()
            lau_supply = lau_contract.functions.totalSupply().call()
            lau_max = lau_contract.functions.maxSupply().call()
            lau_player_bal = lau_contract.functions.balanceOf(player_addr).call()
            print(f"LAU name: {lau_name} ({lau_sym})")
            print(f"LAU supply: {w3.from_wei(lau_supply, 'ether'):.0f} / {w3.from_wei(lau_max, 'ether'):.0f}")
            print(f"LAU balance (player): {w3.from_wei(lau_player_bal, 'ether'):.4f}")
        except Exception as e:
            print(f"LAU details: ERROR - {e}")

    # QING / Saat
    if lau_addr:
        print(f"\n--- QING Venue Check ---")
        lau_c = w3.eth.contract(address=lau_addr, abi=SAAT_ABI)
        try:
            saat0 = lau_c.functions.Saat(0).call()
            saat1 = lau_c.functions.Saat(1).call()
            saat2 = lau_c.functions.Saat(2).call()
            print(f"LAU Saat[0]: {saat0}")
            print(f"LAU Saat[1]: {saat1}")
            print(f"LAU Saat[2]: {saat2}")
        except Exception as e:
            print(f"LAU Saat: ERROR - {e}")

    # SHIO token balances
    check_addrs = build_check_addrs(player_addr, lau_addr, yue_addr)
    print(f"\n--- SHIO Token Balances ---")

    shio_tokens = {
        "Fornax": FORNAX,
        "Fomalhaute": FOMALHAUTE,
        "CHO": CHO,
    }

    for token_name, token_addr in shio_tokens.items():
        tok = w3.eth.contract(address=token_addr, abi=ERC20_ABI)
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

    # Key token balances
    print(f"\n--- Key Token Balances ---")

    extra_tokens = {
        "AFFECTION": "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D",
        "CROWS":     "0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1",
        "WM (MV)":   "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29",
        "VOID":      VOID,
        "SEI":       SEI,
        "META":      META,
        "CHEON":     CHEON,
        "CHOA":      CHOA,
    }

    for tname, taddr in extra_tokens.items():
        taddr = Web3.to_checksum_address(taddr)
        tok = w3.eth.contract(address=taddr, abi=ERC20_ABI)
        for label, addr in check_addrs.items():
            try:
                bal = tok.functions.balanceOf(addr).call()
                if bal > 0:
                    print(f"  {tname} @ {label}: {w3.from_wei(bal, 'ether'):.6f}")
            except:
                pass

    # ZUO / Zurich balances
    print(f"\n--- ZUO Balances ---")
    zuo = w3.eth.contract(address=ZUO_QING, abi=ERC20_ABI)
    for label, addr in check_addrs.items():
        try:
            b = zuo.functions.balanceOf(Web3.to_checksum_address(addr)).call()
            print(f"  ZUO.balOf({label:12s}) = {W(b)}")
        except Exception as e:
            print(f"  ZUO.balOf({label:12s}) = ERROR: {e}")

    print(f"\n--- Zurich Balances ---")
    zurich = w3.eth.contract(address=ZUO_TOKEN, abi=ERC20_ABI)
    for label, addr in check_addrs.items():
        try:
            b = zurich.functions.balanceOf(Web3.to_checksum_address(addr)).call()
            print(f"  Zurich.balOf({label:12s}) = {W(b)}")
        except Exception as e:
            print(f"  Zurich.balOf({label:12s}) = ERROR: {e}")

    # CHOA.Yuan(ZUO) call
    print(f"\n--- CHOA.Yuan(ZUO) ---")
    choa = w3.eth.contract(address=CHOA, abi=CHOA_ABI)
    try:
        yuan = choa.functions.Yuan(ZUO_QING).call({"from": player_addr})
        print(f"  CHOA.Yuan(ZUO, from=Player) = {yuan}")
    except Exception as e:
        print(f"  CHOA.Yuan(ZUO, from=Player) = ERROR: {e}")

    return lau_addr, yue_addr, tx_count


# ===========================================================================
# PART 2: META/CHEON TX scanning
# ===========================================================================

def scan_transfer_events(contract_addr, contract_name, player_addr, start_block, current_block, chunk_size=10000):
    """Scan Transfer events for a contract, identify player's TXs and all callers."""
    print(f"\n--- Scanning {contract_name} Transfer events (blocks {start_block}-{current_block}) ---")

    found_txs = set()
    for chunk_start in range(start_block, current_block, chunk_size):
        chunk_end = min(chunk_start + chunk_size - 1, current_block)
        try:
            logs = w3.eth.get_logs({
                "address": contract_addr,
                "topics": [TRANSFER_TOPIC],
                "fromBlock": chunk_start,
                "toBlock": chunk_end,
            })
            if logs:
                print(f"  Blocks {chunk_start}-{chunk_end}: {len(logs)} Transfer events")
                for log in logs:
                    tx_hash = log['transactionHash'].hex()
                    found_txs.add(tx_hash)
            else:
                print(f"  Blocks {chunk_start}-{chunk_end}: 0 events")
        except Exception as e:
            print(f"  Blocks {chunk_start}-{chunk_end}: ERROR - {e}")
        time.sleep(0.2)

    print(f"\nTotal unique {contract_name} txs found: {len(found_txs)}")

    if not found_txs:
        return

    print(f"\n--- Analyzing {contract_name} transactions ---")
    player_txs = []
    all_callers = {}

    for i, tx_hash in enumerate(sorted(found_txs)):
        try:
            tx = w3.eth.get_transaction(tx_hash)
            caller = tx['from']
            to_addr = tx['to'] if tx['to'] else "CONTRACT_CREATE"
            input_data = tx['input'].hex() if isinstance(tx['input'], bytes) else tx['input']
            selector = input_data[:10] if len(input_data) >= 10 else input_data

            caller_lower = caller.lower()
            if caller_lower not in all_callers:
                all_callers[caller_lower] = {"count": 0, "addr": caller, "selectors": set()}
            all_callers[caller_lower]["count"] += 1
            all_callers[caller_lower]["selectors"].add(selector)

            if caller.lower() == player_addr.lower():
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                player_txs.append({
                    "hash": tx_hash,
                    "block": tx['blockNumber'],
                    "to": to_addr,
                    "selector": selector,
                    "status": receipt['status'],
                    "gas_used": receipt['gasUsed'],
                })
                print(f"  *** PLAYER TX: {tx_hash[:16]}... block={tx['blockNumber']} to={str(to_addr)[:10]}... sel={selector} status={'OK' if receipt['status'] else 'FAIL'}")

            if (i + 1) % 20 == 0:
                print(f"  ... checked {i+1}/{len(found_txs)} txs")
        except Exception as e:
            print(f"  TX {tx_hash[:16]}...: ERROR - {e}")
        time.sleep(0.1)

    print(f"\n--- All {contract_name} callers ---")
    for addr_lower, info in sorted(all_callers.items(), key=lambda x: x[1]['count'], reverse=True):
        sels = ", ".join(info['selectors'])
        is_player = " *** TARGET PLAYER ***" if addr_lower == player_addr.lower() else ""
        print(f"  {info['addr']}: {info['count']} calls [{sels}]{is_player}")

    if player_txs:
        print(f"\n--- Player's {contract_name} transactions ---")
        for tx in player_txs:
            print(f"  Block {tx['block']}: {tx['hash'][:20]}... | to={str(tx['to'])[:14]}... | sel={tx['selector']} | status={'SUCCESS' if tx['status'] else 'REVERTED'} | gas={tx['gas_used']}")
    else:
        print(f"\n  No {contract_name} transactions found from target player")


def part2_meta_cheon_scan(player_addr, scan_blocks):
    """Scan META and CHEON Transfer events for player activity."""
    print("\n" + "=" * 70)
    print("PART 2: Scanning for META/CHEON interactions")
    print("=" * 70)

    print(f"\nBeat selector: 0x{BEAT_SEL}")
    print(f"Su selector: 0x{SU_SEL}")
    print(f"Transfer topic: {TRANSFER_TOPIC}")

    current_block = w3.eth.block_number
    start_block = current_block - scan_blocks
    print(f"\nCurrent block: {current_block}")
    print(f"Scan range: {start_block} - {current_block} ({scan_blocks} blocks)")

    scan_transfer_events(META, "META", player_addr, start_block, current_block)
    scan_transfer_events(CHEON, "CHEON", player_addr, start_block, current_block)


# ===========================================================================
# PART 3: Recent TX scanning
# ===========================================================================

def part3_recent_txs(player_addr, lau_addr, yue_addr, tx_count):
    """Scan recent blocks for transactions from the player."""
    print("\n" + "=" * 70)
    print("PART 3: Scanning player's recent transactions (by block trace)")
    print("=" * 70)

    # Build KNOWN map with player-specific entries
    known = dict(KNOWN_CONTRACTS)
    if lau_addr:
        known[lau_addr.lower()] = "player_LAU"
    if yue_addr:
        known[yue_addr.lower()] = "player_YUE"

    current_block = w3.eth.block_number
    print(f"\nPlayer nonce: {tx_count}")
    print("Scanning last 5000 blocks for txs FROM player...")

    recent_txs = []
    scan_start = current_block - 5000

    for block_num in range(current_block, scan_start, -1):
        try:
            block = w3.eth.get_block(block_num, full_transactions=True)
            for tx in block.transactions:
                if tx['from'].lower() == player_addr.lower():
                    to_addr = tx['to'] if tx['to'] else "CONTRACT_CREATE"
                    input_data = tx['input'].hex() if isinstance(tx['input'], bytes) else tx['input']
                    selector = input_data[:10] if len(input_data) >= 10 else "0x"

                    recent_txs.append({
                        "hash": tx['hash'].hex(),
                        "block": tx['blockNumber'],
                        "to": to_addr,
                        "selector": selector,
                        "nonce": tx['nonce'],
                        "value": tx['value'],
                    })
                    print(f"  Found tx: block={block_num} nonce={tx['nonce']} to={str(to_addr)[:14]}... sel={selector}")
        except Exception:
            pass

        # Progress indicator
        if (current_block - block_num) % 1000 == 0 and block_num != current_block:
            print(f"  ... scanned {current_block - block_num} blocks, found {len(recent_txs)} txs")

        if len(recent_txs) >= 50:
            print(f"  Found 50 txs, stopping scan")
            break

    print(f"\nTotal recent player txs found: {len(recent_txs)}")

    if recent_txs:
        print("\n--- Player's recent transactions (decoded) ---")
        for tx in sorted(recent_txs, key=lambda x: x['block']):
            to_str = tx['to']
            if isinstance(to_str, str):
                label = known.get(to_str.lower(), "UNKNOWN")
                to_display = f"{label}({to_str[:10]}...)"
            else:
                to_display = str(to_str)

            val_str = f" val={w3.from_wei(tx['value'], 'ether'):.2f}" if tx['value'] > 0 else ""
            print(f"  Block {tx['block']} nonce={tx['nonce']}: {to_display} sel={tx['selector']}{val_str}")


# ===========================================================================
# Main
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generalized Dysnomia player recon script. "
                    "Scans on-chain state for any player address."
    )
    parser.add_argument(
        "--address", required=True,
        help="Player EOA address to scan (required)"
    )
    parser.add_argument(
        "--blocks", type=int, default=100000,
        help="Number of blocks to scan for META/CHEON events (default: 100000)"
    )
    parser.add_argument(
        "--skip-txscan", action="store_true",
        help="Skip the slow TX scanning parts (Parts 2 and 3)"
    )
    args = parser.parse_args()

    player_addr = Web3.to_checksum_address(args.address)

    print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")
    print(f"RPC: {READ_RPC}\n")

    # Part 1: Basic info (always runs)
    lau_addr, yue_addr, tx_count = part1_player_info(player_addr)

    if not args.skip_txscan:
        # Part 2: META/CHEON event scanning
        part2_meta_cheon_scan(player_addr, args.blocks)

        # Part 3: Recent TX scanning
        part3_recent_txs(player_addr, lau_addr, yue_addr, tx_count)
    else:
        print("\n--- Skipping TX scanning (--skip-txscan) ---")

    print("\n" + "=" * 70)
    print("RECON COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
