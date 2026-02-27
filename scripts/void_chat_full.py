#!/usr/bin/env python3
"""
Scan VOID chat for Noumenon's messages (wider range + decode by caller).
"""
from web3 import Web3
from eth_utils import keccak

RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}")

VOID_ADDR = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")
GIBS_ADDR = Web3.to_checksum_address("0x66a08aa12da955eb63d7ac121a88b2b210a07b03")
NOUMENON  = Web3.to_checksum_address("0xEbE9B8673d7096DCEE26DA7d9eaf6fc4eBe30980")
JOEY      = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")

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

# ─── WIDER VOID SCAN ─────────────────────────────────────────────────────────
# Scan last 50,000 blocks for VOID activity
current = w3.eth.block_number
SCAN_RANGE = 50000
from_block = max(0, current - SCAN_RANGE)
print(f"\nScanning VOID Transfer events from block {from_block:,} to {current:,} ({SCAN_RANGE:,} blocks)...")

try:
    # Split into chunks to avoid RPC limits
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
                "Joey" if caller.lower() == JOEY.lower() else \
                caller[:12] + "..."
        print(f"\n  [{label}] ({len(msgs)} events):")
        for blk, mtype, msg, to_addr in msgs[:20]:  # show up to 20 per caller
            to_label = to_addr[:12]+"..." if to_addr else "?"
            if msg:
                print(f"    [{blk:,}] {mtype}: '{msg[:100]}'")
            else:
                print(f"    [{blk:,}] {mtype} → {to_label}")
        if len(msgs) > 20:
            print(f"    ... and {len(msgs)-20} more")

except Exception as e:
    print(f"Error: {e}")

# ─── ALSO SCAN GIBS TRANSFERS (token distributions) ──────────────────────────
print(f"\n\n=== GIBS TRANSFERS (all time, last 100k blocks) ===")
from_block2 = max(0, current - 100000)
try:
    all_gibs = []
    for start in range(from_block2, current, chunk):
        end = min(start + chunk - 1, current)
        try:
            logs = w3.eth.get_logs({
                "fromBlock": hex(start),
                "toBlock": hex(end),
                "address": GIBS_ADDR,
                "topics": [TRANSFER_TOPIC]
            })
            all_gibs.extend(logs)
        except Exception as e:
            pass

    print(f"  Total GIBS Transfer events: {len(all_gibs)}")
    for log in all_gibs:
        blk = log['blockNumber']
        frm = "0x" + log['topics'][1].hex()[-40:]
        to  = "0x" + log['topics'][2].hex()[-40:]
        amt = int(log['data'].hex(), 16) / 1e18

        frm_label = "MINT" if frm == "0x"+"0"*40 else \
                    "Joey" if frm.lower() == JOEY.lower() else \
                    "GIBS" if frm.lower() == GIBS_ADDR.lower() else \
                    "DSS" if frm.lower() == "0x91df693177ee5c81016d0b7c4c2052a7d229c031" else \
                    frm[:10]+"..."
        to_label  = "Joey" if to.lower() == JOEY.lower() else \
                    "GIBS" if to.lower() == GIBS_ADDR.lower() else \
                    "DSS" if to.lower() == "0x91df693177ee5c81016d0b7c4c2052a7d229c031" else \
                    to[:10]+"..."
        print(f"  [{blk:,}] {frm_label:12s} → {to_label:12s}: {amt:,.2f} GIBS")
except Exception as e:
    print(f"  Error: {e}")
