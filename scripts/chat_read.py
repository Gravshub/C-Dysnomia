#!/usr/bin/env python3
"""
Read recent VOID chat messages.

Chat in Dysnomia is stored as LogEvent(uint64 Soul, uint64 Aura, string LogLine)
on Fomalhaute — the ZHOU SHIO at 0x7aE73C498A308247BE73688c09c96B3fd06dDB84.

Usage:
  python scripts/void_chat_reader.py           # last 50 messages
  python scripts/void_chat_reader.py --blocks 5000   # custom lookback range
"""
import sys
import argparse
from web3 import Web3
from eth_utils import keccak

RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(RPC))

# Fomalhaute is the ZHOU SHIO — where all VOID chat is stored
FOMALHAUTE = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")

# LogEvent(uint64 Soul, uint64 Aura, string LogLine)
LOG_TOPIC = "0x" + keccak(text="LogEvent(uint64,uint64,string)").hex()

def decode_log_event(log):
    """Decode LogEvent from raw log data (non-indexed params)."""
    data = bytes(log['data'])
    if len(data) < 128:
        return None, None, None
    try:
        soul      = int(data[0:32].hex(), 16)
        aura      = int(data[32:64].hex(), 16)
        str_offset = int(data[64:96].hex(), 16)
        str_len   = int(data[96:128].hex(), 16)
        msg_bytes = data[128:128 + str_len]
        msg       = msg_bytes.decode('utf-8', errors='replace')
        return soul, aura, msg
    except Exception as e:
        return None, None, None

def main():
    parser = argparse.ArgumentParser(description="Read recent VOID chat messages")
    parser.add_argument("--blocks", type=int, default=100000, help="How many blocks to scan (default: 100000)")
    parser.add_argument("--tail", type=int, default=50, help="Show last N messages (default: 50)")
    args = parser.parse_args()

    current = w3.eth.block_number
    scan_from = current - args.blocks
    print(f"Block: {current:,}")
    print(f"Scanning {args.blocks:,} blocks for VOID chat (Fomalhaute LogEvents)...")

    all_logs = []
    chunk_size = 5000
    for start in range(scan_from, current + 1, chunk_size):
        end = min(start + chunk_size - 1, current)
        try:
            chunk = w3.eth.get_logs({
                "fromBlock": hex(start),
                "toBlock":   hex(end),
                "address":   FOMALHAUTE,
                "topics":    [LOG_TOPIC]
            })
            all_logs.extend(chunk)
        except Exception as e:
            pass

    # Sort by block ascending, take last N
    all_logs.sort(key=lambda l: l['blockNumber'])
    recent = all_logs[-args.tail:]

    print(f"Total messages found: {len(all_logs)}  |  Showing last {len(recent)}\n")
    print("=" * 70)

    for log in recent:
        blk = log['blockNumber']
        soul, aura, msg = decode_log_event(log)
        if msg is None:
            continue
        print(f"[{blk:,}] {msg}")

    print("=" * 70)
    print(f"\n{len(all_logs)} total messages in scanned range.")
    print(f"To see more: python scripts/void_chat_reader.py --blocks 200000 --tail 100")

if __name__ == "__main__":
    main()
