#!/usr/bin/env python3
"""
Find Zürich token sources - needed to buy ZUO tokens via ZUO.Purchase(Zürich, N).
ZUO market rate: 1M Zürich per ZUO.

enteh has 0.001907 ZUO → spent ~1907 Zürich
Zürich total supply: 1.3B
ZUO holds 14.58M Zürich

Goal: Find a way to get Zürich tokens.
"""
from web3 import Web3

READ_RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(READ_RPC))
print(f"Connected: {w3.is_connected()}  Block: {w3.eth.block_number:,}\n")

ZUO_TOKEN = Web3.to_checksum_address("0x583d1C1427308f7f96BFd3E0d7A3F9674D8BF8ec")  # Zürich
JOEY_EOA  = Web3.to_checksum_address("0x17367877aF5A8D0Eb33ba5689A880f696386E24D")
AFFECTION = Web3.to_checksum_address("0x24F0154C1dCe548AdF15da2098Fdd8B8A3b8151D")
WPLS      = Web3.to_checksum_address("0xA1077a294dDE1B09bB078844df40758a5D0f9a27")

# PulseX V1 router: 0x165C3410fC91EF562C50559f7d2289fEbed552d9
# PulseX V1 factory
V1_ROUTER  = Web3.to_checksum_address("0x165C3410fC91EF562C50559f7d2289fEbed552d9")
V2_ROUTER  = Web3.to_checksum_address("0x98bf93ebf5c380C0e6Ae8e192A7e2AE08edAcc02")

V1_ROUTER_ABI = [
    {"inputs":[],"name":"factory","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"tokenA","type":"address"},{"name":"tokenB","type":"address"}],
     "name":"quote","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"amountIn","type":"uint256"},{"name":"path","type":"address[]"}],
     "name":"getAmountsOut","outputs":[{"name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"},
]

FACTORY_ABI = [
    {"inputs":[{"name":"tokenA","type":"address"},{"name":"tokenB","type":"address"}],
     "name":"getPair","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]

PAIR_ABI = [
    {"inputs":[],"name":"getReserves",
     "outputs":[{"name":"reserve0","type":"uint112"},{"name":"reserve1","type":"uint112"},{"name":"blockTimestampLast","type":"uint32"}],
     "stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token0","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"token1","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
]

ERC20_ABI = [
    {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"symbol","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"decimals","outputs":[{"type":"uint8"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"owner","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]

def W(v, dec=18): return f"{v / 10**dec:.6f}" if isinstance(v, int) else str(v)

print("=" * 65)
print("1. Zürich Token Info")
print("=" * 65)
zurich = w3.eth.contract(address=ZUO_TOKEN, abi=ERC20_ABI)
for fn in ["name", "symbol", "decimals", "totalSupply"]:
    try:
        v = getattr(zurich.functions, fn)().call()
        print(f"  Zürich.{fn}() = {v}")
    except Exception as e:
        print(f"  Zürich.{fn}() = ERR: {e}")

# Try to find owner
try:
    owner = zurich.functions.owner().call()
    print(f"  Zürich.owner() = {owner}")
except Exception as e:
    print(f"  Zürich.owner() = ERR (not Ownable): {e}")

print()
print("=" * 65)
print("2. PulseX Factory Lookup for Zürich pairs")
print("=" * 65)

v1_router = w3.eth.contract(address=V1_ROUTER, abi=V1_ROUTER_ABI)
try:
    v1_factory_addr = v1_router.functions.factory().call()
    print(f"  V1 Factory: {v1_factory_addr}")
    v1_factory = w3.eth.contract(address=v1_factory_addr, abi=FACTORY_ABI)

    for token_name, token_addr in [
        ("WPLS",      WPLS),
        ("AFFECTION", AFFECTION),
    ]:
        try:
            pair = v1_factory.functions.getPair(ZUO_TOKEN, token_addr).call()
            if pair == "0x0000000000000000000000000000000000000000":
                print(f"  V1 Pair (Zürich/{token_name}): NO PAIR")
            else:
                print(f"  V1 Pair (Zürich/{token_name}): {pair}")
                p = w3.eth.contract(address=pair, abi=PAIR_ABI)
                r0, r1, _ = p.functions.getReserves().call()
                t0 = p.functions.token0().call()
                print(f"    reserve0 ({t0}): {r0}")
                print(f"    reserve1: {r1}")
        except Exception as e:
            print(f"  V1 Pair (Zürich/{token_name}): ERR: {e}")
except Exception as e:
    print(f"  V1 Factory lookup failed: {e}")

# Also try V2 factory
v2_router = w3.eth.contract(address=V2_ROUTER, abi=V1_ROUTER_ABI)
try:
    v2_factory_addr = v2_router.functions.factory().call()
    print(f"  V2 Factory: {v2_factory_addr}")
    if v2_factory_addr != v1_factory_addr:
        v2_factory = w3.eth.contract(address=v2_factory_addr, abi=FACTORY_ABI)
        for token_name, token_addr in [("WPLS", WPLS), ("AFFECTION", AFFECTION)]:
            try:
                pair = v2_factory.functions.getPair(ZUO_TOKEN, token_addr).call()
                if pair == "0x0000000000000000000000000000000000000000":
                    print(f"  V2 Pair (Zürich/{token_name}): NO PAIR")
                else:
                    print(f"  V2 Pair (Zürich/{token_name}): {pair}")
            except Exception as e:
                print(f"  V2 Pair (Zürich/{token_name}): ERR: {e}")
except Exception as e:
    print(f"  V2 Factory: ERR: {e}")

print()
print("=" * 65)
print("3. Try getAmountsOut for Zürich on V1")
print("=" * 65)
# Check if V1 can route AFFECTION -> Zürich
try:
    path = [AFFECTION, ZUO_TOKEN]
    amounts = v1_router.functions.getAmountsOut(10**18, path).call()  # 1 AFFECTION
    print(f"  V1: 1 AFFECTION -> {W(amounts[-1])} Zürich")
except Exception as e:
    print(f"  V1 AFFECTION->Zürich: ERR: {e}")

try:
    path = [WPLS, ZUO_TOKEN]
    amounts = v1_router.functions.getAmountsOut(10**18, path).call()  # 1 WPLS
    print(f"  V1: 1 WPLS -> {W(amounts[-1])} Zürich")
except Exception as e:
    print(f"  V1 WPLS->Zürich: ERR: {e}")

print()
print("=" * 65)
print("4. Check known ZUO buyers - who transferred Zürich into ZUO?")
print("=" * 65)
# Get recent transfer events from ZUO_QING (ZUO token contract)
ZUO_QING = Web3.to_checksum_address("0xb0Ba7D36B7F0505879179ecE7401F24eB653c6E1")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
# Scan last 5000 blocks for ZUO transfer events
current_block = w3.eth.block_number
from_block = max(0, current_block - 5000)
try:
    logs = w3.eth.get_logs({
        "fromBlock": from_block,
        "toBlock": current_block,
        "address": ZUO_QING,
        "topics": [TRANSFER_TOPIC]
    })
    print(f"  ZUO Transfer events in last 5000 blocks: {len(logs)}")
    for log in logs[-10:]:  # show last 10
        from_addr = "0x" + log["topics"][1].hex()[-40:]
        to_addr = "0x" + log["topics"][2].hex()[-40:]
        amount = int(log["data"].hex(), 16)
        print(f"    {from_addr} -> {to_addr}: {W(amount)} ZUO (block {log['blockNumber']})")
except Exception as e:
    print(f"  ZUO Transfer scan: ERR: {e}")

print()
print("=" * 65)
print("5. Check Zürich contract for any distribution function")
print("=" * 65)
# Try common function selectors
from eth_utils import keccak
for sig in ["faucet()", "claim()", "mint(address,uint256)", "distribute()",
            "airdrop(address,uint256)", "transfer(address,uint256)",
            "GetMarketRate(address)", "Purchase(address,uint256)"]:
    sel = keccak(text=sig)[:4]
    try:
        result = w3.eth.call({
            "to": ZUO_TOKEN,
            "data": sel.hex()
        })
        print(f"  {sig}: responded with {result.hex()[:40]}")
    except Exception as e:
        err_msg = str(e)[:50]
        if "no data" not in err_msg.lower() and "not found" not in err_msg.lower():
            print(f"  {sig}: {err_msg}")

print()
print("Done.")
