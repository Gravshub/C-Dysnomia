"""Deep-dive into bot pipeline during peak activity period."""
import sys, time
from web3 import Web3

w3 = Web3(Web3.HTTPProvider('https://rpc-pulsechain.g4mm4.io', request_kwargs={'timeout': 60}))
current_block = w3.eth.block_number
print(f'Connected: {w3.is_connected()}, Block: {current_block}')

BOTS = {
    'Minter': '0x217a76D9BEf7CeC27eFB5039099221241ca26F93',
    'Buyer': '0x1B79F904087DaaF6C67d7AD2cfA1D7c727De885B',
    'Sell': '0xa767a0D5E04eD4c90Ad68F316A9E55090aa28c51',
}

AFF = '0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D'.lower()
MULTI_AFF = '0xCF138a83D739eE98D7A54159E94e5BFaa4B61988'.lower()
TRANSFER_SIG = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'

KNOWN = {
    AFF: 'AFFECTION',
    MULTI_AFF: 'Multi_AFF',
    '0x165c3410fc91ef562c50559f7d2289febed552d9': 'PulseX_V2_Router',
    '0x98bf93ebf5c380c0e6ae8e192a7e2ae08edacc02': 'PulseX_V1_Router',
    '0xa1077a294dde1b09bb078844df40758a5d0f9a27': 'WPLS',
    '0x6b175474e89094c44da98b954eedeac495271d0f': 'pDAI',
    '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48': 'pUSDC',
    '0xa2262d7728c689526693ae893d0fd8a352c7073c': 'pINDEPENDENCE',
    '0x2fc636e7fdf9f3e8d61033103052079781a6e7d2': 'GIMME_FIVE',
    '0xb680f0cc810317933f234f67eb6a9e923407f05d': 'MATH_v1.1',
    '0x5ef3011243b03f817223a19f277638397048a0dc': 'MATH_v1.0',
    '0xa1bee1dae9af77dac73aa0459ed63b4d93fc6d29': 'WM',
    '0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff': 'FED',
    '0x232a27ab6941281b3f474fe5ff7cc89816fb675a': 'Fa',
    '0x73a19fafb359faf519c9707b781dfdb88407d10d': 'Faung',
    '0xa96bcbed7f01de6ceed14fc86d90f21a36de2143': 'RNG',
    '0xccddacef154704c604365db9e3b1df356b9c4b6e2': 'Multi_PI',
    '0xccdacef154704c604365db9e3b1df356b9c4b6e2': 'Multi_PI',
    '0xa4c61d20945c11855e7a390153fd29cec9c7349b': 'Multi_G5',
    '0x1322dab9ee385bb3d81f75ebb8356015b0872e53': 'Multi_MATH_1.1',
    '0x5bd78add4007c47ffefc2c98a53188036199ac6f': 'Multi_MATH_1.0',
    BOTS['Minter'].lower(): 'Minter_Bot',
    BOTS['Buyer'].lower(): 'Buyer_Bot',
    BOTS['Sell'].lower(): 'Sell_Bot',
    '0x' + '0'*40: 'ZERO/MINT',
}

SELECTORS = {
    '0x7c88e3d9': 'Generate()',
    '0xa9059cbb': 'transfer(addr,uint)',
    '0x23b872dd': 'transferFrom()',
    '0x095ea7b3': 'approve(addr,uint)',
    '0x38ed1739': 'swapExactTokensForTokens',
    '0x8803dbee': 'swapTokensForExactTokens',
    '0x7ff36ab5': 'swapExactETHForTokens',
    '0x18cbafe5': 'swapExactTokensForETH',
    '0xfb3bdb41': 'swapETHForExactTokens',
    '0x4a25d94a': 'swapTokensForExactETH',
    '0x791ac947': 'swapExactTokensForETHSupportingFee',
    '0x5c11d795': 'swapExactTokensForTokensSupportingFee',
    '0xb6f9de95': 'swapExactETHForTokensSupportingFee',
}

erc20_abi = [
    {'inputs':[{'name':'a','type':'address'}],'name':'balanceOf','outputs':[{'name':'','type':'uint256'}],'stateMutability':'view','type':'function'},
    {'inputs':[],'name':'symbol','outputs':[{'name':'','type':'string'}],'stateMutability':'view','type':'function'},
]

def lbl(addr):
    return KNOWN.get(addr.lower(), addr[:14]+'...')

def get_symbol(addr):
    try:
        c = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=erc20_abi)
        return c.functions.symbol().call()
    except:
        return '???'

# From v3 analysis:
# Minter: active blocks 20859743 - 23629626 (last TX ~83 days ago)
# Buyer:  active blocks 20859491 - 23315273 (last TX ~93 days ago)
# Sell:   active blocks 20859743 - 23315189 (last TX ~93 days ago)
# All started at same time (~block 20859xxx)

# Key findings from v3:
# - Buyer's last TXs: swapExactETHForTokens on PulseX V2 Router, buying pUSDC and pDAI
# - Sell's last TXs: swapExactTokensForETH selling AFF for PLS via 0x155172... pair,
#                    then sending PLS to Minter and Buyer bots
# - Minter's last TX: approve pDAI to some address

# Let's deep dive into a representative activity window
# Pick a window in the middle of their active period for typical behavior
# Also look at the last few days of activity for Minter (it ran 10 days longer)

print('\n' + '='*70)
print('  PHASE 1: PIPELINE DEEP-DIVE (Minter bot - last activity)')
print('='*70)

# Minter was last active at block 23629626 - let's scan a wide window
minter_addr = BOTS['Minter']
minter_topic = '0x' + minter_addr[2:].lower().zfill(64)

# Scan 2000 blocks around last minter activity
scan_start = 23628000
scan_end = 23630000

print(f'\nScanning blocks {scan_start}-{scan_end} for Minter TXs...')
minter_txs = []
for blk_num in range(scan_end, scan_start, -1):
    try:
        blk = w3.eth.get_block(blk_num, full_transactions=True)
        for tx in blk.transactions:
            if tx['from'].lower() == minter_addr.lower():
                inp = tx['input'].hex() if isinstance(tx['input'], bytes) else tx['input']
                selector = inp[:10] if len(inp) >= 10 else inp
                func_name = SELECTORS.get(selector, f'unknown({selector})')
                to_addr = tx['to'].lower() if tx['to'] else 'create'
                minter_txs.append({
                    'block': blk_num,
                    'hash': tx['hash'].hex(),
                    'to': to_addr,
                    'func': func_name,
                    'value': tx['value'] / 1e18,
                    'input': inp,
                })
    except:
        pass
    if len(minter_txs) >= 20:
        break

print(f'Found {len(minter_txs)} Minter TXs')
for t in minter_txs:
    v = f' ({t["value"]:.1f} PLS)' if t['value'] > 0 else ''
    print(f'  Block {t["block"]}: {t["func"]:50s} -> {lbl(t["to"])}{v}')
    # Decode receipt for each
    try:
        receipt = w3.eth.get_transaction_receipt(t['hash'])
        for rlog in receipt['logs'][:15]:
            log_addr = rlog['address'].lower()
            if rlog['topics'] and rlog['topics'][0].hex() == TRANSFER_SIG[2:]:
                from_a = '0x' + rlog['topics'][1].hex()[-40:]
                to_a = '0x' + rlog['topics'][2].hex()[-40:]
                amt = int(rlog['data'].hex(), 16) / 1e18
                tok_l = lbl(log_addr)
                if tok_l.endswith('...'):
                    tok_l = get_symbol(log_addr)
                print(f'    [{tok_l}] {lbl(from_a)} -> {lbl(to_a)}: {amt:.4f}')
            else:
                topic0 = rlog['topics'][0].hex()[:10] if rlog['topics'] else 'none'
                print(f'    event {topic0}... on {lbl(log_addr)}')
    except:
        pass
sys.stdout.flush()

# ---- PHASE 2: Look at a typical activity window for all 3 bots together ----
print('\n' + '='*70)
print('  PHASE 2: CONCURRENT ACTIVITY (blocks 23314000-23316000 - all 3 active)')
print('='*70)

scan_start = 23314000
scan_end = 23316000

all_bot_txs = []
for blk_num in range(scan_end, scan_start, -1):
    try:
        blk = w3.eth.get_block(blk_num, full_transactions=True)
        for tx in blk.transactions:
            sender = tx['from'].lower()
            for bot_name, bot_addr in BOTS.items():
                if sender == bot_addr.lower():
                    inp = tx['input'].hex() if isinstance(tx['input'], bytes) else tx['input']
                    selector = inp[:10] if len(inp) >= 10 else inp
                    func_name = SELECTORS.get(selector, f'unknown({selector})')
                    to_addr = tx['to'].lower() if tx['to'] else 'create'
                    all_bot_txs.append({
                        'block': blk_num,
                        'hash': tx['hash'].hex(),
                        'bot': bot_name,
                        'to': to_addr,
                        'func': func_name,
                        'value': tx['value'] / 1e18,
                        'input': inp,
                    })
    except:
        pass
    if len(all_bot_txs) >= 30:
        break

all_bot_txs.sort(key=lambda x: x['block'], reverse=True)
print(f'Found {len(all_bot_txs)} TXs from all bots')

for t in all_bot_txs[:30]:
    v = f' ({t["value"]:.1f} PLS)' if t['value'] > 0 else ''
    print(f'\n  Block {t["block"]} [{t["bot"]:6s}]: {t["func"]:45s} -> {lbl(t["to"])}{v}')
    try:
        receipt = w3.eth.get_transaction_receipt(t['hash'])
        for rlog in receipt['logs'][:15]:
            log_addr = rlog['address'].lower()
            if rlog['topics'] and rlog['topics'][0].hex() == TRANSFER_SIG[2:]:
                from_a = '0x' + rlog['topics'][1].hex()[-40:]
                to_a = '0x' + rlog['topics'][2].hex()[-40:]
                amt = int(rlog['data'].hex(), 16) / 1e18
                tok_l = lbl(log_addr)
                if tok_l.endswith('...'):
                    tok_l = get_symbol(log_addr)
                print(f'    [{tok_l}] {lbl(from_a)} -> {lbl(to_a)}: {amt:.4f}')
            else:
                topic0 = rlog['topics'][0].hex()[:10] if rlog['topics'] else 'none'
                print(f'    event {topic0}... on {lbl(log_addr)}')
    except:
        pass
sys.stdout.flush()

# ---- PHASE 3: Scan AFF-specific activity in peak window ----
print('\n' + '='*70)
print('  PHASE 3: AFF TRANSFER FLOWS (blocks 23310000-23316000)')
print('='*70)

scan_start = 23310000
scan_end = 23316000

for bot_name, bot_addr in BOTS.items():
    to_topic = '0x' + bot_addr[2:].lower().zfill(64)
    from_topic = to_topic

    # AFF incoming
    try:
        logs_in = w3.eth.get_logs({
            'fromBlock': scan_start, 'toBlock': scan_end,
            'address': Web3.to_checksum_address(AFF),
            'topics': [TRANSFER_SIG, None, to_topic],
        })
        if logs_in:
            total = sum(int(l['data'].hex(), 16) / 1e18 for l in logs_in)
            senders = {}
            for l in logs_in:
                s = '0x' + l['topics'][1].hex()[-40:]
                senders[s] = senders.get(s, 0) + int(l['data'].hex(), 16) / 1e18
            print(f'\n  {bot_name}: {len(logs_in)} AFF received, {total:.4f} total')
            for s, a in sorted(senders.items(), key=lambda x: -x[1]):
                print(f'    from {lbl(s)}: {a:.4f} AFF')
    except Exception as e:
        print(f'  Error {bot_name} in: {e}')

    # AFF outgoing
    try:
        logs_out = w3.eth.get_logs({
            'fromBlock': scan_start, 'toBlock': scan_end,
            'address': Web3.to_checksum_address(AFF),
            'topics': [TRANSFER_SIG, from_topic],
        })
        if logs_out:
            total = sum(int(l['data'].hex(), 16) / 1e18 for l in logs_out)
            recipients = {}
            for l in logs_out:
                r = '0x' + l['topics'][2].hex()[-40:]
                recipients[r] = recipients.get(r, 0) + int(l['data'].hex(), 16) / 1e18
            print(f'  {bot_name}: {len(logs_out)} AFF sent, {total:.4f} total')
            for r, a in sorted(recipients.items(), key=lambda x: -x[1]):
                print(f'    to {lbl(r)}: {a:.4f} AFF')
    except Exception as e:
        print(f'  Error {bot_name} out: {e}')

sys.stdout.flush()

# ---- PHASE 4: Look at early activity to understand initial pipeline setup ----
print('\n' + '='*70)
print('  PHASE 4: EARLY ACTIVITY (blocks 20859000-20862000 - first TXs)')
print('='*70)

scan_start = 20859000
scan_end = 20862000

early_txs = []
for blk_num in range(scan_start, min(scan_end, scan_start + 3000)):
    try:
        blk = w3.eth.get_block(blk_num, full_transactions=True)
        for tx in blk.transactions:
            sender = tx['from'].lower()
            for bot_name, bot_addr in BOTS.items():
                if sender == bot_addr.lower():
                    inp = tx['input'].hex() if isinstance(tx['input'], bytes) else tx['input']
                    selector = inp[:10] if len(inp) >= 10 else inp
                    func_name = SELECTORS.get(selector, f'unknown({selector})')
                    to_addr = tx['to'].lower() if tx['to'] else 'create'
                    early_txs.append({
                        'block': blk_num,
                        'hash': tx['hash'].hex(),
                        'bot': bot_name,
                        'to': to_addr,
                        'func': func_name,
                        'value': tx['value'] / 1e18,
                    })
    except:
        pass
    if len(early_txs) >= 20:
        break

early_txs.sort(key=lambda x: x['block'])
print(f'Found {len(early_txs)} early TXs')
for t in early_txs[:20]:
    v = f' ({t["value"]:.1f} PLS)' if t['value'] > 0 else ''
    print(f'\n  Block {t["block"]} [{t["bot"]:6s}]: {t["func"]:45s} -> {lbl(t["to"])}{v}')
    try:
        receipt = w3.eth.get_transaction_receipt(t['hash'])
        for rlog in receipt['logs'][:10]:
            log_addr = rlog['address'].lower()
            if rlog['topics'] and rlog['topics'][0].hex() == TRANSFER_SIG[2:]:
                from_a = '0x' + rlog['topics'][1].hex()[-40:]
                to_a = '0x' + rlog['topics'][2].hex()[-40:]
                amt = int(rlog['data'].hex(), 16) / 1e18
                tok_l = lbl(log_addr)
                if tok_l.endswith('...'):
                    tok_l = get_symbol(log_addr)
                print(f'    [{tok_l}] {lbl(from_a)} -> {lbl(to_a)}: {amt:.4f}')
            else:
                topic0 = rlog['topics'][0].hex()[:10] if rlog['topics'] else 'none'
                print(f'    event {topic0}... on {lbl(log_addr)}')
    except:
        pass
sys.stdout.flush()

# ---- PHASE 5: Summary stats ----
print('\n' + '='*70)
print('  PHASE 5: LIFETIME AFF FLOWS (scanning 500K block chunks)')
print('='*70)

# Scan entire activity range in chunks for AFF flows
activity_start = 20859000
activity_end = 23630000
chunk_size = 500000

for bot_name, bot_addr in BOTS.items():
    to_topic = '0x' + bot_addr[2:].lower().zfill(64)
    from_topic = to_topic
    total_in = 0
    total_out = 0
    count_in = 0
    count_out = 0
    senders_all = {}
    recipients_all = {}

    for chunk_start in range(activity_start, activity_end, chunk_size):
        chunk_end = min(chunk_start + chunk_size, activity_end)
        try:
            logs_in = w3.eth.get_logs({
                'fromBlock': chunk_start, 'toBlock': chunk_end,
                'address': Web3.to_checksum_address(AFF),
                'topics': [TRANSFER_SIG, None, to_topic],
            })
            for l in logs_in:
                amt = int(l['data'].hex(), 16) / 1e18
                total_in += amt
                count_in += 1
                s = '0x' + l['topics'][1].hex()[-40:]
                senders_all[s] = senders_all.get(s, 0) + amt
        except Exception as e:
            print(f'  Chunk {chunk_start} in error: {e}')

        try:
            logs_out = w3.eth.get_logs({
                'fromBlock': chunk_start, 'toBlock': chunk_end,
                'address': Web3.to_checksum_address(AFF),
                'topics': [TRANSFER_SIG, from_topic],
            })
            for l in logs_out:
                amt = int(l['data'].hex(), 16) / 1e18
                total_out += amt
                count_out += 1
                r = '0x' + l['topics'][2].hex()[-40:]
                recipients_all[r] = recipients_all.get(r, 0) + amt
        except Exception as e:
            print(f'  Chunk {chunk_start} out error: {e}')

    print(f'\n  {bot_name}:')
    print(f'    Lifetime AFF received: {count_in} transfers, {total_in:.4f} AFF')
    print(f'    Top senders:')
    for s, a in sorted(senders_all.items(), key=lambda x: -x[1])[:5]:
        print(f'      {lbl(s)}: {a:.4f} AFF')
    print(f'    Lifetime AFF sent: {count_out} transfers, {total_out:.4f} AFF')
    print(f'    Top recipients:')
    for r, a in sorted(recipients_all.items(), key=lambda x: -x[1])[:5]:
        print(f'      {lbl(r)}: {a:.4f} AFF')
    sys.stdout.flush()

print('\n\nDone.')
