#!/usr/bin/env python3
"""
Sync VOID chat log to data/void_chat.jsonl (append-only).

Scans Fomalhaute LogEvents from the last synced block forward.
Appends new messages to data/void_chat.jsonl — one JSON object per line.
Run before each session to catch up, then push with the repo.

Usage:
  python scripts/void_chat_sync.py          # incremental sync
  python scripts/void_chat_sync.py --full   # rescan all history
  python scripts/void_chat_sync.py --print  # print recent messages too
"""
import os
import json
import argparse
from pathlib import Path
from web3 import Web3
from eth_utils import keccak

RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(RPC))

FOMALHAUTE  = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")
LOG_TOPIC   = "0x" + keccak(text="LogEvent(uint64,uint64,string)").hex()
CHAT_FILE   = Path(__file__).parent.parent / "data" / "void_chat.jsonl"
STATE_FILE  = Path(__file__).parent.parent / "data" / "void_chat_state.json"

# Block where VOID went live (approx)
GENESIS_BLOCK = 25_820_000

def decode_log_event(log):
    data = bytes(log['data'])
    if len(data) < 128:
        return None
    try:
        soul      = int(data[0:32].hex(), 16)
        aura      = int(data[32:64].hex(), 16)
        str_offset = int(data[64:96].hex(), 16)
        str_len   = int(data[96:128].hex(), 16)
        msg       = data[128:128 + str_len].decode('utf-8', errors='replace')
        return {"soul": soul, "aura": aura, "msg": msg}
    except:
        return None

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_block": GENESIS_BLOCK}

def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

def load_existing_hashes():
    """Load set of already-stored tx hashes to avoid duplicates."""
    seen = set()
    if CHAT_FILE.exists():
        for line in CHAT_FILE.read_text().splitlines():
            try:
                obj = json.loads(line)
                seen.add(obj.get("tx", ""))
            except:
                pass
    return seen

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full",  action="store_true", help="Rescan all history from genesis")
    parser.add_argument("--print", action="store_true", help="Print recent messages after sync")
    parser.add_argument("--tail",  type=int, default=20, help="Lines to print with --print")
    args = parser.parse_args()

    current = w3.eth.block_number
    print(f"Block: {current:,}")

    state = load_state()
    scan_from = GENESIS_BLOCK if args.full else state["last_block"]
    seen_hashes = set() if args.full else load_existing_hashes()

    print(f"Syncing from block {scan_from:,} → {current:,} ({current - scan_from:,} blocks)...")

    # Scan in 5000-block chunks
    new_entries = []
    chunk_size = 5000
    for start in range(scan_from, current + 1, chunk_size):
        end = min(start + chunk_size - 1, current)
        try:
            logs = w3.eth.get_logs({
                "fromBlock": hex(start),
                "toBlock":   hex(end),
                "address":   FOMALHAUTE,
                "topics":    [LOG_TOPIC]
            })
            for log in logs:
                txh = log['transactionHash'].hex()
                if txh in seen_hashes:
                    continue
                decoded = decode_log_event(log)
                if decoded is None:
                    continue
                entry = {
                    "block": log['blockNumber'],
                    "tx":    txh,
                    **decoded,
                }
                new_entries.append(entry)
                seen_hashes.add(txh)
        except Exception as e:
            print(f"  Chunk {start}-{end} error: {e}")

    # Append new entries
    if new_entries:
        CHAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CHAT_FILE, "a") as f:
            for entry in sorted(new_entries, key=lambda e: e["block"]):
                f.write(json.dumps(entry) + "\n")
        print(f"Appended {len(new_entries)} new messages.")
    else:
        print("No new messages.")

    # Update state
    save_state({"last_block": current})

    if args.print or args.full:
        print(f"\n{'='*70}")
        print(f"VOID CHAT — last {args.tail} messages")
        print(f"{'='*70}")
        if CHAT_FILE.exists():
            lines = CHAT_FILE.read_text().strip().splitlines()
            for line in lines[-args.tail:]:
                try:
                    e = json.loads(line)
                    print(f"[{e['block']:,}] {e['msg']}")
                except:
                    pass

    total = sum(1 for _ in CHAT_FILE.open()) if CHAT_FILE.exists() else 0
    print(f"\nTotal stored: {total} messages  |  data/void_chat.jsonl")

if __name__ == "__main__":
    main()
