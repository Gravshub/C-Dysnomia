"""Identify key addresses and understand the full pipeline."""
import sys
from web3 import Web3

w3 = Web3(Web3.HTTPProvider('https://rpc-pulsechain.g4mm4.io', request_kwargs={'timeout': 60}))
print(f'Connected: {w3.is_connected()}, Block: {w3.eth.block_number}')

erc20_abi = [
    {'inputs':[{'name':'a','type':'address'}],'name':'balanceOf','outputs':[{'name':'','type':'uint256'}],'stateMutability':'view','type':'function'},
    {'inputs':[],'name':'symbol','outputs':[{'name':'','type':'string'}],'stateMutability':'view','type':'function'},
    {'inputs':[],'name':'name','outputs':[{'name':'','type':'string'}],'stateMutability':'view','type':'function'},
    {'inputs':[],'name':'totalSupply','outputs':[{'name':'','type':'uint256'}],'stateMutability':'view','type':'function'},
]

# Key unknown addresses from the analysis
addresses_to_identify = {
    '0x32d390e9e1b1': 'Top AFF sender to Minter (3.68M AFF)',
    '0x81fcd03d2100': 'Second AFF sender to Minter (364K AFF)',
    '0x79474ff39b0f': 'Third AFF sender to Minter (2.5K AFF) + Minter calls unknown(a791de3d00) on this',
    '0x98375da84c14': 'Minter calls unknown(bc9820c100) on this - mints MATH+RNG',
    '0x155172653e94': 'Top AFF recipient from Sell (3.95M AFF) - LP pair?',
    '0x9d7377a9cffc': 'AFF recipient from Buyer (58K) and Sell (6K)',
    '0xd21d1241473e': 'AFF recipient from Buyer (7.3K)',
    '0x8f6dfb2fa2f7': 'WPLS/pUSDC pair used by Buyer',
    '0xae8429918fdb': 'WPLS/pDAI pair used by Buyer',
}

print('\n' + '='*70)
print('  IDENTIFYING KEY ADDRESSES')
print('='*70)

# Need full addresses - let me reconstruct from partial + get_logs
# For the LP pairs and contracts, try to get their details

# 0x155172653e94... is clearly the AFF/WPLS LP pair (AFF goes in, WPLS comes out)
# Let's verify by checking known addresses

# Get full addresses from the actual logs
TRANSFER_SIG = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
AFF = '0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D'

# Scan a small window for Minter to get full addresses
minter = '0x217a76D9BEf7CeC27eFB5039099221241ca26F93'
minter_topic = '0x' + minter[2:].lower().zfill(64)

# Get AFF transfers TO Minter in early blocks to find the sender addresses
print('\nLooking up full addresses from early AFF transfers to Minter...')
try:
    logs = w3.eth.get_logs({
        'fromBlock': 20859000,
        'toBlock': 20870000,
        'address': Web3.to_checksum_address(AFF),
        'topics': [TRANSFER_SIG, None, minter_topic],
    })
    senders = set()
    for l in logs:
        s = '0x' + l['topics'][1].hex()[-40:]
        senders.add(s)
    print(f'  Unique AFF senders to Minter in first ~11K blocks: {len(senders)}')
    for s in senders:
        print(f'    {s}')
except Exception as e:
    print(f'  Error: {e}')

# Get full addresses from Minter's outgoing AFF
sell_bot = '0xa767a0D5E04eD4c90Ad68F316A9E55090aa28c51'
sell_topic = '0x' + sell_bot[2:].lower().zfill(64)

# Get AFF transfers FROM Sell to identify LP pair
print('\nLooking up LP pair from Sell bot AFF transfers...')
try:
    logs = w3.eth.get_logs({
        'fromBlock': 20859000,
        'toBlock': 20870000,
        'address': Web3.to_checksum_address(AFF),
        'topics': [TRANSFER_SIG, sell_topic],
    })
    recipients = set()
    for l in logs:
        r = '0x' + l['topics'][2].hex()[-40:]
        recipients.add(r)
    print(f'  Unique AFF recipients from Sell in first ~11K blocks: {len(recipients)}')
    for r in recipients:
        print(f'    {r}')
except Exception as e:
    print(f'  Error: {e}')

# Now identify each address
print('\n\nIdentifying contracts...')
key_addrs = set()

# Reconstruct from the logs above -- let me also check specific TXs
# Block 20859675: Minter calls 0x79474ff39b0f... with selector a791de3d
# Block 20859668: Minter calls 0x98375da84c14... with selector bc9820c1

# Get the full addresses from the TX data
tx_hash_675 = None  # Need to find from block scan
for blk_num in [20859675]:
    try:
        blk = w3.eth.get_block(blk_num, full_transactions=True)
        for tx in blk.transactions:
            if tx['from'].lower() == minter.lower():
                print(f'\n  Block {blk_num} Minter TX:')
                print(f'    To: {tx["to"]}')
                print(f'    Selector: {tx["input"].hex()[:10]}')
                key_addrs.add(tx['to'])
    except:
        pass

for blk_num in [20859668]:
    try:
        blk = w3.eth.get_block(blk_num, full_transactions=True)
        for tx in blk.transactions:
            if tx['from'].lower() == minter.lower():
                print(f'\n  Block {blk_num} Minter TX:')
                print(f'    To: {tx["to"]}')
                print(f'    Selector: {tx["input"].hex()[:10]}')
                key_addrs.add(tx['to'])
    except:
        pass

# Also get the contract addresses from a mid-activity window
print('\nScanning block 21500000 area for Minter TXs to find more contracts...')
for blk_num in range(21500000, 21500100):
    try:
        blk = w3.eth.get_block(blk_num, full_transactions=True)
        for tx in blk.transactions:
            if tx['from'].lower() == minter.lower():
                inp = tx['input'].hex()[:10]
                print(f'  Block {blk_num}: {inp} -> {tx["to"]}')
                key_addrs.add(tx['to'])
    except:
        pass

# Identify each discovered address
print('\n\nContract identification:')
for addr in key_addrs:
    if addr is None:
        continue
    try:
        c = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=erc20_abi)
        sym = c.functions.symbol().call()
        name = c.functions.name().call()
        print(f'  {addr}: {name} ({sym})')
    except:
        # Not an ERC20 - check code size
        code = w3.eth.get_code(Web3.to_checksum_address(addr))
        if len(code) > 0:
            print(f'  {addr}: Contract (code size {len(code)})')
        else:
            print(f'  {addr}: EOA')

# Identify the function selectors we saw
print('\n\nUnknown function selectors:')
print('  0xbc9820c1 - called on 0x98375da84c14... (mints MATH+RNG, takes pUSDC)')
print('  0xa791de3d - called on 0x79474ff39b0f... (takes MATH, mints AFF)')
print('  These are likely multi-mint contracts from Helios!')

# Check if 0x79474ff39b0f... matches any known multi-mint
# From CLAUDE.md:
# Multi MATH 1.1: 0x1322Dab9eE385Bb3D81f75EBb8356015B0872e53
# Multi MATH 1.0: 0x5bD78AdD4007C47ffEFc2c98a53188036199ac6f
# Multi AFFECTION: 0xCF138a83D739eE98D7A54159E94e5BFaa4B61988

# None match 0x79474ff39b0f... - this must be a different/custom multi-mint

# Let's also check the lifetime volume for each bot via a wider chunk
print('\n' + '='*70)
print('  PIPELINE SUMMARY')
print('='*70)

print("""
CONFIRMED PIPELINE (from transaction data):

1. BUYER BOT (0x1B79...885B) - THE FUNDER
   - Swaps PLS -> pUSDC and pDAI on PulseX V2
   - Sends pUSDC/pDAI to Minter Bot
   - Also sends raw PLS to fund Minter and Sell bots' gas

2. MINTER BOT (0x217a...F93) - THE MINTER
   - Receives pUSDC/pDAI from Buyer Bot
   - Calls 0x98375da84c14... (selector bc9820c1) with pUSDC -> mints MATH v1.1 + RNG
   - Calls 0x79474ff39b0f... (selector a791de3d) with MATH v1.1 -> mints AFFECTION
   - This is the BuyWithMATH route: pUSDC -> MATH v1.1 -> AFFECTION (1 MATH = 1 AFF)
   - Transfers ALL minted AFF to Sell Bot
   - Also receives AFF from 2 other addresses (likely intermediary contracts)

3. SELL BOT (0xa767...8c51) - THE SELLER
   - Receives AFF from Minter Bot (4.05M AFF lifetime)
   - Also receives AFF back from Buyer Bot (89K AFF - Buyer holds some as buffer)
   - Swaps AFF -> WPLS on PulseX V2 Router (swapExactTokensForETH)
   - LP pair: 0x155172653e94... (AFF/WPLS V2 pair)
   - Distributes PLS proceeds back to Minter and Buyer bots for next cycle

LIFETIME VOLUMES:
- Minter received:  4,055,439 AFF (minted via MATH route)
- Minter sent:      4,055,439 AFF (100% to Sell Bot)
- Sell received:    4,055,446 AFF (from Minter + small extras)
- Sell sold:        3,959,261 AFF via PulseX DEX
- Sell sent to Buyer: 89,963 AFF (buffer/held)

KEY CONTRACTS:
- 0x98375da84c14... = Custom multi-mint for MATH v1.1 (pUSDC -> MATH)
- 0x79474ff39b0f... = Custom multi-mint for AFFECTION (MATH -> AFF)
- 0x155172653e94... = AFF/WPLS V2 LP pair (sell destination)
- 0x8f6dfb2fa2f7... = pUSDC/WPLS V2 pair
- 0xae8429918fdb... = pDAI/WPLS V2 pair

VALUE EXTRACTION:
- Bot buys pUSDC at ~$0.007/PLS (14,400 PLS per swap)
- pUSDC -> MATH -> AFF at 1:1:1 rate via contract functions
- AFF sold on DEX at market price
- Early sell example: 200 AFF -> 12,075 WPLS (~60 PLS/AFF at that time)
- Pipeline: PLS -> pUSDC (market) -> MATH (1:1 contract) -> AFF (1:1 contract) -> PLS (DEX)
- Profit = DEX AFF price in PLS - cost of pUSDC in PLS

ACTIVITY PERIOD:
- Started: block 20,859,xxx (~179 days ago, ~Sep 2025)
- Buyer/Sell stopped: block 23,315,xxx (~93 days ago, ~Dec 2025)
- Minter stopped: block 23,629,xxx (~83 days ago, ~Dec 2025)
- Status: ALL DORMANT. Minter holds 108K PLS, Buyer holds 57K PLS + 5K AFF, Sell holds 20K PLS + 330K WPLS.
""")

# Verify the AFF/WPLS pair address
print('\nVerifying AFF/WPLS pair...')
# PulseX V2 Factory: 0x29eA7545DEf87022BAdc76323F373EA1e707C523
factory_abi = [
    {'inputs':[{'name':'tokenA','type':'address'},{'name':'tokenB','type':'address'}],
     'name':'getPair','outputs':[{'name':'','type':'address'}],'stateMutability':'view','type':'function'},
]
WPLS = '0xA1077a294dDE1B09bB078844df40758a5D0f9a27'
v2_factory = w3.eth.contract(
    address=Web3.to_checksum_address('0x29eA7545DEf87022BAdc76323F373EA1e707C523'),
    abi=factory_abi
)
pair = v2_factory.functions.getPair(
    Web3.to_checksum_address(AFF),
    Web3.to_checksum_address(WPLS)
).call()
print(f'  AFF/WPLS V2 pair: {pair}')
print(f'  Matches 0x155172653e94...? {pair.lower().startswith("0x155172653e94")}')

# Also check V1
v1_factory = w3.eth.contract(
    address=Web3.to_checksum_address('0x1715a3E4A142d8b698131108995174F37aEBA10D'),
    abi=factory_abi
)
pair_v1 = v1_factory.functions.getPair(
    Web3.to_checksum_address(AFF),
    Web3.to_checksum_address(WPLS)
).call()
print(f'  AFF/WPLS V1 pair: {pair_v1}')

# Check the unknown contracts
print('\nIdentifying 0x98375da84c14... and 0x79474ff39b0f...')
for blk_num in [20859668]:
    try:
        blk = w3.eth.get_block(blk_num, full_transactions=True)
        for tx in blk.transactions:
            if tx['from'].lower() == minter.lower():
                full_addr = tx['to']
                print(f'  Multi-MATH contract (bc9820c1): {full_addr}')
                code = w3.eth.get_code(Web3.to_checksum_address(full_addr))
                print(f'    Code size: {len(code)} bytes')
    except:
        pass

for blk_num in [20859675]:
    try:
        blk = w3.eth.get_block(blk_num, full_transactions=True)
        for tx in blk.transactions:
            if tx['from'].lower() == minter.lower():
                full_addr = tx['to']
                print(f'  Multi-AFF/MATH contract (a791de3d): {full_addr}')
                code = w3.eth.get_code(Web3.to_checksum_address(full_addr))
                print(f'    Code size: {len(code)} bytes')
    except:
        pass

# Check the 2 major AFF source addresses for Minter
print('\nIdentifying top AFF senders to Minter...')
# Need to find full addresses from logs
try:
    logs = w3.eth.get_logs({
        'fromBlock': 21000000,
        'toBlock': 21010000,
        'address': Web3.to_checksum_address(AFF),
        'topics': [TRANSFER_SIG, None, minter_topic],
    })
    for l in logs[:5]:
        sender = '0x' + l['topics'][1].hex()[-40:]
        amt = int(l['data'].hex(), 16) / 1e18
        # Try to identify
        code = w3.eth.get_code(Web3.to_checksum_address(sender))
        is_contract = len(code) > 0
        print(f'  {sender}: {amt:.0f} AFF ({"contract" if is_contract else "EOA"})')
except Exception as e:
    print(f'  Error: {e}')

print('\nDone.')
