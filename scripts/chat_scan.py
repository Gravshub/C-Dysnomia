#!/usr/bin/env python3
"""Scan VOID chat for messages and LAU token transfers — works with any LAU token on PulseChain.

Usage:
  python scripts/chat_scan.py                         # defaults (GIBS LAU, Joey wallet)
  python scripts/chat_scan.py --lau 0x1234...         # custom LAU token to track transfers
  python scripts/chat_scan.py --wallet 0xABCD...      # filter by caller wallet
  python scripts/chat_scan.py --blocks 100000         # scan last 100k blocks
"""
import argparse
from web3 import Web3
from eth_utils import keccak

# ── Ecosystem constants (never change) ────────────────────────────────────────
VOID_ADDR = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")
NOUMENON  = Web3.to_checksum_address("0xEbE9B8673d7096DCEE26DA7d9eaf6fc4eBe30980")

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_LAU    = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"
DEFAULT_WALLET = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
DEFAULT_BLOCKS = 50000

TRANSFER_TOPIC = "0x" + keccak(text="Transfer(address,address,uint256)").hex()

# Known selectors
chat_sel  = keccak(text="Chat(string)")[:4]
log_sel   = keccak(text="Log(string)")[:4]
attr_sel  = keccak(text="SetAttribute(string,string)")[:4]
alias_sel = keccak(text="Alias(address,string)")[:4]
addlib_sel = keccak(text="AddLibrary(string,address)")[:4]
enter_sel = keccak(text="Enter()")[:4]
enter2_sel = keccak(text="Enter(string,string)")[:4]

def decode_string_arg(inp_bytes):
    """Decode first string arg from ABI-encoded calldata."""
    try:
        if len(inp_bytes) < 4 + 32 + 32:
            return None
        offset = int(inp_bytes[4:36].hex(), 16)
        if 4 + offset + 32 > len(inp_bytes):
            return None
        length = int(inp_bytes[4+offset:4+offset+32].hex(), 16)
        if 4 + offset + 32 + length > len(inp_bytes):
            return None
        msg_bytes = inp_bytes[4+offset+32:4+offset+32+length]
        return msg_bytes.decode('utf-8', errors='replace')
    except:
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Scan VOID chat for messages and LAU token transfers"
    )
    parser.add_argument("--lau", type=str, default=DEFAULT_LAU,
                        help=f"LAU token address to track transfers (default: GIBS {DEFAULT_LAU})")
    parser.add_argument("--wallet", type=str, default=DEFAULT_WALLET,
                        help=f"Wallet address to label in output (default: Joey {DEFAULT_WALLET})")
    parser.add_argument("--blocks", type=int, default=DEFAULT_BLOCKS,
                        help=f"Number of blocks to scan back (default: {DEFAULT_BLOCKS})")
    args = parser.parse_args()

    lau_addr = Web3.to_checksum_address(args.lau)
    wallet   = Web3.to_checksum_address(args.wallet)
    scan_range = args.blocks

    RPC = "https://rpc.pulsechainstats.com"
    w3 = Web3(Web3.HTTPProvider(RPC))
    print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

    # ─── WIDER VOID SCAN ─────────────────────────────────────────────────────
    current = w3.eth.block_number
    from_block = max(0, current - scan_range)
    print(f"\nScanning VOID Transfer events from block {from_block:,} to {current:,} ({scan_range:,} blocks)...")

    try:
        chunk = 5000
        all_logs = []
        for start in range(from_block, current, chunk):
            end = min(start + chunk - 1, current)
            try:
                logs = w3.eth.get_logs({
                    "fromBlock": hex(start),
                    "toBlock": hex(end),
                    "address": VOID_ADDR,
                    "topics": [TRANSFER_TOPIC]
                })
                all_logs.extend(logs)
            except Exception as e:
                print(f"  Chunk {start}-{end} error: {e}")

        print(f"  Total VOID Transfer events: {len(all_logs)}")

        # Process each log
        messages_by_caller = {}
        seen_txs = set()

        for log in all_logs:
            tx_hash = log['transactionHash'].hex()
            if tx_hash in seen_txs:
                continue
            seen_txs.add(tx_hash)

            try:
                tx = w3.eth.get_transaction(tx_hash)
                inp = bytes(tx['input']) if tx['input'] else b''
                caller = tx['from']
                to     = tx.get('to', '')
                blk    = log['blockNumber']

                if caller not in messages_by_caller:
                    messages_by_caller[caller] = []

                # Decode message content
                if len(inp) >= 4:
                    sel = inp[:4]
                    if sel == chat_sel:
                        msg = decode_string_arg(inp)
                        messages_by_caller[caller].append((blk, "Chat", msg, to))
                    elif sel == log_sel:
                        msg = decode_string_arg(inp)
                        messages_by_caller[caller].append((blk, "Log", msg, to))
                    elif sel == attr_sel:
                        messages_by_caller[caller].append((blk, "SetAttr", None, to))
                    elif sel == alias_sel:
                        messages_by_caller[caller].append((blk, "Alias", None, to))
                    elif sel == addlib_sel:
                        messages_by_caller[caller].append((blk, "AddLib", None, to))
                    elif sel == enter_sel:
                        messages_by_caller[caller].append((blk, "Enter()", None, to))
                    elif sel == enter2_sel:
                        messages_by_caller[caller].append((blk, "Enter(str,str)", None, to))
                    else:
                        sel_hex = sel.hex()
                        messages_by_caller[caller].append((blk, f"0x{sel_hex}", None, to))
            except Exception as e:
                pass

        # Print results by caller
        print(f"\n  Unique callers: {len(messages_by_caller)}")
        for caller, msgs in sorted(messages_by_caller.items(), key=lambda x: -len(x[1])):
            label = "Noumenon" if caller.lower() == NOUMENON.lower() else \
                    "Wallet" if caller.lower() == wallet.lower() else \
                    caller[:12] + "..."
            print(f"\n  [{label}] ({len(msgs)} events):")
            for blk, mtype, msg, to_addr in msgs[:20]:
                to_label = to_addr[:12]+"..." if to_addr else "?"
                if msg:
                    print(f"    [{blk:,}] {mtype}: '{msg[:100]}'")
                else:
                    print(f"    [{blk:,}] {mtype} -> {to_label}")
            if len(msgs) > 20:
                print(f"    ... and {len(msgs)-20} more")

    except Exception as e:
        print(f"Error: {e}")

    # ─── ALSO SCAN LAU TRANSFERS (token distributions) ───────────────────────
    print(f"\n\n=== LAU TRANSFERS (last 100k blocks) ===")
    from_block2 = max(0, current - 100000)
    dss_addr = "0x91df693177ee5c81016d0b7c4c2052a7d229c031"
    try:
        chunk = 5000
        all_lau = []
        for start in range(from_block2, current, chunk):
            end = min(start + chunk - 1, current)
            try:
                logs = w3.eth.get_logs({
                    "fromBlock": hex(start),
                    "toBlock": hex(end),
                    "address": lau_addr,
                    "topics": [TRANSFER_TOPIC]
                })
                all_lau.extend(logs)
            except Exception as e:
                pass

        print(f"  Total LAU Transfer events: {len(all_lau)}")
        for log in all_lau:
            blk = log['blockNumber']
            frm = "0x" + log['topics'][1].hex()[-40:]
            to  = "0x" + log['topics'][2].hex()[-40:]
            amt = int(log['data'].hex(), 16) / 1e18

            frm_label = "MINT" if frm == "0x"+"0"*40 else \
                        "Wallet" if frm.lower() == wallet.lower() else \
                        "LAU" if frm.lower() == lau_addr.lower() else \
                        "DSS" if frm.lower() == dss_addr else \
                        frm[:10]+"..."
            to_label  = "Wallet" if to.lower() == wallet.lower() else \
                        "LAU" if to.lower() == lau_addr.lower() else \
                        "DSS" if to.lower() == dss_addr else \
                        to[:10]+"..."
            print(f"  [{blk:,}] {frm_label:12s} -> {to_label:12s}: {amt:,.2f}")
    except Exception as e:
        print(f"  Error: {e}")


if __name__ == "__main__":
    main()
