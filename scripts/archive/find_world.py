#!/usr/bin/env python3
"""Scan CREATOR wallet's contract deployments to find ZI/PANG/RING/CHEON/META/WORLD."""
from web3 import Web3

w3 = Web3(Web3.HTTPProvider("https://rpc.pulsechain.com"))

CREATOR = "0x7a20189b297343cf26d8548764b04891f37f3414"
Transfer_sig = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_TOPIC   = "0x0000000000000000000000000000000000000000000000000000000000000000"
CREATOR_TOPIC = "0x000000000000000000000000" + CREATOR[2:]

ABI = [
    {"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"Type","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
]

target_types = {"ZI", "PANG", "RING", "CHEON", "META", "WORLD", "GWAT"}
seen = set()

# Narrow windows of 50 blocks around the key deployment range
# CHOA at 23,720,409, WM at 23,726,410 — scan 23,720,409 to 23,760,000
for start in range(23720409, 23760000, 50):
    end = start + 49
    try:
        logs = w3.eth.get_logs({
            "fromBlock": start,
            "toBlock": end,
            "topics": [Transfer_sig, ZERO_TOPIC, CREATOR_TOPIC]
        })
        for log in logs:
            addr = log['address']
            if addr in seen:
                continue
            seen.add(addr)
            try:
                ci = w3.eth.contract(address=addr, abi=ABI)
                n = ci.functions.name().call()
                t = ""
                try:
                    t = ci.functions.Type().call()
                except Exception:
                    pass
                marker = "***" if t in target_types else "   "
                print(f"{marker} block {log['blockNumber']:,}: {addr}  -> {n} ({t})")
            except Exception as e2:
                pass
    except Exception as e:
        print(f"  Error {start}-{end}: {str(e)[:60]}")
