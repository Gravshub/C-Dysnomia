#!/usr/bin/env python3
"""
Recon script: Find LAU, QING, YUE, and SHIO balances for player 0xccE83CfF8B531EaDdcf11AB414C59DC046D1aAc7
"""

from web3 import Web3
import json

RPC = "https://rpc.pulsechain.com"
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
assert w3.is_connected(), "Failed to connect to PulseChain RPC"

PLAYER = Web3.to_checksum_address("0xccE83CfF8B531EaDdcf11AB414C59DC046D1aAc7")

# Contract addresses
CHO_ADDR = Web3.to_checksum_address("0xB6be11F0A788014C1F68C92F8D6CcC1AbF78F2aB")
CHAN_ADDR = Web3.to_checksum_address("0xe250bf9729076B14A8399794B61C72d0F4AeFcd8")
MAP_ADDR = Web3.to_checksum_address("0xD3a7A95012Edd46Ea115c693B74c5e524b3DdA75")
FORNAX_ADDR = Web3.to_checksum_address("0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7")
FOMALHAUTE_ADDR = Web3.to_checksum_address("0x7aE73C498A308247BE73688c09c96B3fd06dDB84")
SEI_ADDR = Web3.to_checksum_address("0x3dC54d46e030C42979f33C9992348a990acb6067")
VOID_ADDR = Web3.to_checksum_address("0x965B0d74591bF30327075A247C47dBf487dCff08")

# Standard ERC20 ABI fragments
BALANCE_OF_ABI = [{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"}]
NAME_ABI = [{"inputs":[],"name":"name","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"}]
SYMBOL_ABI = [{"inputs":[],"name":"symbol","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"}]
TOTAL_SUPPLY_ABI = [{"inputs":[],"name":"totalSupply","outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"}]
DECIMALS_ABI = [{"inputs":[],"name":"decimals","outputs":[{"type":"uint8"}],"stateMutability":"view","type":"function"}]

# LAU-specific
LAU_ABI = [
    {"inputs":[],"name":"Username","outputs":[{"type":"string"}],"stateMutability":"view","type":"function"},
    {"inputs":[{"name":"","type":"uint256"}],"name":"Saat","outputs":[{"type":"uint64"}],"stateMutability":"view","type":"function"},
    {"inputs":[],"name":"owner","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]

# CHO
CHO_ABI = [
    {"inputs":[{"name":"","type":"address"}],"name":"GetUserTokenAddress","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]

# CHAN
CHAN_ABI = [
    {"inputs":[{"name":"","type":"address"}],"name":"Yan","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]

# MAP - check for QING creation
MAP_ABI = [
    {"inputs":[{"name":"","type":"address"}],"name":"GetQingAddress","outputs":[{"type":"address"}],"stateMutability":"view","type":"function"},
]

ZERO_ADDR = "0x0000000000000000000000000000000000000000"

def fmt(val, decimals=18):
    """Format a raw token balance to human-readable."""
    return val / (10 ** decimals)

def safe_call(contract, func_name, *args):
    """Call a contract function, return None on revert."""
    try:
        return getattr(contract.functions, func_name)(*args).call()
    except Exception as e:
        return None

print("=" * 70)
print(f"PLAYER RECON: {PLAYER}")
print("=" * 70)

# ── Step 1: Transaction count ──
tx_count = w3.eth.get_transaction_count(PLAYER)
balance_pls = w3.eth.get_balance(PLAYER)
print(f"\n[1] WALLET INFO")
print(f"    Address:    {PLAYER}")
print(f"    TX Count:   {tx_count}")
print(f"    PLS Balance: {fmt(balance_pls):.4f} PLS")

# ── Step 2: CHO.GetUserTokenAddress → LAU ──
cho = w3.eth.contract(address=CHO_ADDR, abi=CHO_ABI)
lau_addr = safe_call(cho, "GetUserTokenAddress", PLAYER)
print(f"\n[2] CHO.GetUserTokenAddress({PLAYER})")
if lau_addr and lau_addr != ZERO_ADDR:
    print(f"    LAU Token Address: {lau_addr}")
else:
    print(f"    LAU Token Address: NONE (returned {lau_addr})")
    lau_addr = None

# ── Step 3: CHAN.Yan → YUE ──
chan = w3.eth.contract(address=CHAN_ADDR, abi=CHAN_ABI)
yue_addr = safe_call(chan, "Yan", PLAYER)
print(f"\n[3] CHAN.Yan({PLAYER})")
if yue_addr and yue_addr != ZERO_ADDR:
    print(f"    YUE Wallet Address: {yue_addr}")
else:
    print(f"    YUE Wallet Address: NONE (returned {yue_addr})")
    yue_addr = None

# ── Step 4: LAU details ──
if lau_addr:
    lau = w3.eth.contract(address=Web3.to_checksum_address(lau_addr), abi=LAU_ABI + NAME_ABI + SYMBOL_ABI + TOTAL_SUPPLY_ABI + DECIMALS_ABI + BALANCE_OF_ABI)

    username = safe_call(lau, "Username")
    name = safe_call(lau, "name")
    symbol = safe_call(lau, "symbol")
    total_supply = safe_call(lau, "totalSupply")
    decimals = safe_call(lau, "decimals") or 18
    owner = safe_call(lau, "owner")

    # Saat triple
    saat0 = safe_call(lau, "Saat", 0)
    saat1 = safe_call(lau, "Saat", 1)
    saat2 = safe_call(lau, "Saat", 2)
    saat3 = safe_call(lau, "Saat", 3)

    # Player's LAU balance
    player_lau_bal = safe_call(lau, "balanceOf", PLAYER)

    print(f"\n[4] LAU TOKEN DETAILS")
    print(f"    Name:         {name}")
    print(f"    Symbol:       {symbol}")
    print(f"    Username:     {username}")
    print(f"    Total Supply: {fmt(total_supply, decimals):.4f} {symbol}")
    print(f"    Decimals:     {decimals}")
    print(f"    Owner:        {owner}")
    print(f"    Saat[0]:      {saat0}")
    print(f"    Saat[1]:      {saat1}  (Soul)")
    print(f"    Saat[2]:      {saat2}")
    print(f"    Saat[3]:      {saat3}")
    print(f"    Player holds: {fmt(player_lau_bal, decimals):.4f} {symbol}")

# ── Step 5: Check QING via MAP ──
print(f"\n[5] QING VENUE LOOKUP")
if lau_addr:
    map_contract = w3.eth.contract(address=MAP_ADDR, abi=MAP_ABI)
    qing_addr = safe_call(map_contract, "GetQingAddress", Web3.to_checksum_address(lau_addr))
    if qing_addr and qing_addr != ZERO_ADDR:
        print(f"    QING Address (via MAP.GetQingAddress(LAU)): {qing_addr}")

        # Get QING details
        qing = w3.eth.contract(address=Web3.to_checksum_address(qing_addr), abi=NAME_ABI + SYMBOL_ABI + TOTAL_SUPPLY_ABI + DECIMALS_ABI + BALANCE_OF_ABI)
        qing_name = safe_call(qing, "name")
        qing_symbol = safe_call(qing, "symbol")
        qing_supply = safe_call(qing, "totalSupply")
        qing_decimals = safe_call(qing, "decimals") or 18
        print(f"    QING Name:    {qing_name}")
        print(f"    QING Symbol:  {qing_symbol}")
        print(f"    QING Supply:  {fmt(qing_supply, qing_decimals):.4f}")
    else:
        print(f"    QING Address: NONE (player has no QING venue)")
        qing_addr = None
else:
    print(f"    Skipped — no LAU found")
    qing_addr = None

# ── Step 6: SHIO token balances at LAU and YUE ──
print(f"\n[6] SHIO TOKEN BALANCES (Fornax, Fomalhaute, CHO)")

shio_tokens = [
    ("Fornax", FORNAX_ADDR),
    ("Fomalhaute", FOMALHAUTE_ADDR),
    ("CHO", CHO_ADDR),
]

targets = []
if lau_addr:
    targets.append(("LAU", Web3.to_checksum_address(lau_addr)))
if yue_addr:
    targets.append(("YUE", Web3.to_checksum_address(yue_addr)))
if qing_addr:
    targets.append(("QING", Web3.to_checksum_address(qing_addr)))
targets.append(("EOA", PLAYER))

for token_name, token_addr in shio_tokens:
    token = w3.eth.contract(address=token_addr, abi=BALANCE_OF_ABI + TOTAL_SUPPLY_ABI + DECIMALS_ABI)
    token_decimals = safe_call(token, "decimals") or 18
    token_supply = safe_call(token, "totalSupply")
    print(f"\n  {token_name} ({token_addr})")
    print(f"    Total Supply: {fmt(token_supply, token_decimals):.4f}")

    for target_name, target_addr in targets:
        bal = safe_call(token, "balanceOf", target_addr)
        if bal is not None:
            formatted = fmt(bal, token_decimals)
            marker = " <<<" if formatted > 0 else ""
            print(f"    at {target_name} ({target_addr}): {formatted:.4f}{marker}")
        else:
            print(f"    at {target_name} ({target_addr}): ERROR")

# ── Step 7: Additional token balances ──
print(f"\n[7] OTHER TOKEN BALANCES AT PLAYER EOA")
other_tokens = [
    ("AFFECTION", "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D"),
    ("WM (MV)", "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29"),
    ("CROWS", "0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1"),
    ("VOID", VOID_ADDR.lower()),
    ("SEI", SEI_ADDR.lower()),
]

for token_name, addr in other_tokens:
    token = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=BALANCE_OF_ABI + DECIMALS_ABI)
    token_decimals = safe_call(token, "decimals") or 18
    bal = safe_call(token, "balanceOf", PLAYER)
    if bal is not None:
        formatted = fmt(bal, token_decimals)
        marker = " <<<" if formatted > 0 else ""
        print(f"    {token_name}: {formatted:.4f}{marker}")

# ── Step 8: Check if YUE has interesting balances ──
if yue_addr:
    print(f"\n[8] TOKEN BALANCES AT YUE WALLET ({yue_addr})")
    all_check = other_tokens + [("Fornax", FORNAX_ADDR), ("Fomalhaute", FOMALHAUTE_ADDR)]
    if lau_addr:
        all_check.append(("LAU (self)", lau_addr))

    for token_name, addr in all_check:
        token = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=BALANCE_OF_ABI + DECIMALS_ABI)
        token_decimals = safe_call(token, "decimals") or 18
        bal = safe_call(token, "balanceOf", Web3.to_checksum_address(yue_addr))
        if bal is not None:
            formatted = fmt(bal, token_decimals)
            if formatted > 0:
                print(f"    {token_name}: {formatted:.4f} <<<")

print(f"\n{'=' * 70}")
print("RECON COMPLETE")
print("=" * 70)
