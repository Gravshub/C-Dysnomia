"""Deep analysis of 3 bot addresses - scan ALL token activity, not just AFF."""
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

TRANSFER_SIG = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'

AFF = '0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D'.lower()
MULTI_AFF = '0xCF138a83D739eE98D7A54159E94e5BFaa4B61988'.lower()

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
    '0xa1bee1dae9af77dac73aa0459ed63b4d93fc6d29': 'WM',
    '0xcc78a0acdf847a2c1714d2a925bb4477df5d48a6': 'Atropa',
    '0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff': 'FED',
    '0xcf138a83d739ee98d7a54159e94e5bfaa4b61988': 'Multi_AFF',
    '0x5ef3011243b03f817223a19f277638397048a0dc': 'MATH_v1.0',
    '0x232a27ab6941281b3f474fe5ff7cc89816fb675a': 'Fa',
    '0x73a19fafb359faf519c9707b781dfdb88407d10d': 'Faung',
    '0xa96bcbed7f01de6ceed14fc86d90f21a36de2143': 'RNG',
    BOTS['Minter'].lower(): 'Minter_Bot',
    BOTS['Buyer'].lower(): 'Buyer_Bot',
    BOTS['Sell'].lower(): 'Sell_Bot',
    '0x' + '0'*40: 'ZERO/MINT',
}

SELECTORS = {
    '0x7c88e3d9': 'Generate()',
    '0xa9059cbb': 'transfer(addr,uint)',
    '0x23b872dd': 'transferFrom(addr,addr,uint)',
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
    '0xe8e33700': 'addLiquidity',
    '0xf305d719': 'addLiquidityETH',
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

# Strategy: since 50K blocks showed zero AFF activity, these bots operated BEFORE that window.
# Let's find WHEN they were active by checking some older block ranges.
# Also scan what they actually DO by looking at recent blocks for ANY activity.

for bot_name, bot_addr in BOTS.items():
    print(f'\n{"="*70}')
    print(f'  {bot_name} Bot: {bot_addr}')
    print(f'{"="*70}')

    nonce = w3.eth.get_transaction_count(bot_addr)
    pls = w3.eth.get_balance(Web3.to_checksum_address(bot_addr)) / 1e18
    aff_c = w3.eth.contract(address=Web3.to_checksum_address(AFF), abi=erc20_abi)
    aff_bal = aff_c.functions.balanceOf(Web3.to_checksum_address(bot_addr)).call() / 1e18
    print(f'  Nonce: {nonce}, PLS: {pls:.2f}, AFF: {aff_bal:.4f}')
    sys.stdout.flush()

    # ---- APPROACH 1: Scan recent blocks for ANY TX from this bot ----
    # Check last 500 blocks to find any recent activity
    print(f'\n  Scanning last 500 blocks for TXs from {bot_name}...')
    recent_txs = []
    for blk_num in range(current_block, current_block - 500, -1):
        try:
            blk = w3.eth.get_block(blk_num, full_transactions=True)
            for tx in blk.transactions:
                if tx['from'].lower() == bot_addr.lower():
                    inp = tx['input'].hex() if isinstance(tx['input'], bytes) else tx['input']
                    selector = inp[:10] if len(inp) >= 10 else inp
                    func_name = SELECTORS.get(selector, f'unknown({selector})')
                    to_addr = tx['to'].lower() if tx['to'] else 'create'
                    recent_txs.append({
                        'block': blk_num,
                        'hash': tx['hash'].hex(),
                        'to': to_addr,
                        'func': func_name,
                        'value': tx['value'] / 1e18,
                    })
        except:
            pass
        if len(recent_txs) >= 10:
            break

    if recent_txs:
        print(f'  Found {len(recent_txs)} recent TXs:')
        for t in recent_txs[:10]:
            v = f' ({t["value"]:.1f} PLS)' if t['value'] > 0 else ''
            print(f'    Block {t["block"]}: {t["func"]:50s} -> {lbl(t["to"])}{v}')
    else:
        print(f'  No TXs in last 500 blocks.')
    sys.stdout.flush()

    # ---- APPROACH 2: Scan ALL token Transfer events FROM this bot (last 5000 blocks) ----
    print(f'\n  Scanning Transfer events FROM {bot_name} (last 5000 blocks, any token)...')
    from_topic = '0x' + bot_addr[2:].lower().zfill(64)
    try:
        logs_from = w3.eth.get_logs({
            'fromBlock': current_block - 5000,
            'toBlock': current_block,
            'topics': [TRANSFER_SIG, from_topic],
        })
        if logs_from:
            print(f'  Found {len(logs_from)} outgoing Transfer events')
            # Group by token
            by_token = {}
            for log in logs_from:
                tok = log['address'].lower()
                to_a = '0x' + log['topics'][2].hex()[-40:]
                amt = int(log['data'].hex(), 16) / 1e18
                if tok not in by_token:
                    by_token[tok] = {'count': 0, 'total': 0, 'recipients': {}}
                by_token[tok]['count'] += 1
                by_token[tok]['total'] += amt
                by_token[tok]['recipients'][to_a] = by_token[tok]['recipients'].get(to_a, 0) + amt
            for tok, info in sorted(by_token.items(), key=lambda x: -x[1]['total']):
                sym = lbl(tok)
                if sym.endswith('...'):
                    sym = get_symbol(tok) + f' ({tok[:14]}...)'
                print(f'    {sym}: {info["count"]} transfers, {info["total"]:.4f} total')
                for r, a in sorted(info['recipients'].items(), key=lambda x: -x[1])[:3]:
                    print(f'      -> {lbl(r)}: {a:.4f}')
        else:
            print(f'  No outgoing transfers in last 5000 blocks')
    except Exception as e:
        print(f'  Error: {e}')
    sys.stdout.flush()

    # ---- APPROACH 3: Scan Transfer events TO this bot (last 5000 blocks, any token) ----
    print(f'\n  Scanning Transfer events TO {bot_name} (last 5000 blocks, any token)...')
    to_topic = '0x' + bot_addr[2:].lower().zfill(64)
    try:
        logs_to = w3.eth.get_logs({
            'fromBlock': current_block - 5000,
            'toBlock': current_block,
            'topics': [TRANSFER_SIG, None, to_topic],
        })
        if logs_to:
            print(f'  Found {len(logs_to)} incoming Transfer events')
            by_token = {}
            for log in logs_to:
                tok = log['address'].lower()
                from_a = '0x' + log['topics'][1].hex()[-40:]
                amt = int(log['data'].hex(), 16) / 1e18
                if tok not in by_token:
                    by_token[tok] = {'count': 0, 'total': 0, 'senders': {}}
                by_token[tok]['count'] += 1
                by_token[tok]['total'] += amt
                by_token[tok]['senders'][from_a] = by_token[tok]['senders'].get(from_a, 0) + amt
            for tok, info in sorted(by_token.items(), key=lambda x: -x[1]['total']):
                sym = lbl(tok)
                if sym.endswith('...'):
                    sym = get_symbol(tok) + f' ({tok[:14]}...)'
                print(f'    {sym}: {info["count"]} transfers, {info["total"]:.4f} total')
                for s, a in sorted(info['senders'].items(), key=lambda x: -x[1])[:3]:
                    print(f'      <- {lbl(s)}: {a:.4f}')
        else:
            print(f'  No incoming transfers in last 5000 blocks')
    except Exception as e:
        print(f'  Error: {e}')
    sys.stdout.flush()

    # ---- APPROACH 4: Deep-dive a recent TX receipt ----
    if recent_txs:
        print(f'\n  --- Receipt deep-dive (latest TX) ---')
        tx_hash = recent_txs[0]['hash']
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            print(f'  TX: {tx_hash}')
            print(f'  Status: {"OK" if receipt["status"] == 1 else "FAIL"}, Gas: {receipt["gasUsed"]}, Logs: {len(receipt["logs"])}')
            for rlog in receipt['logs'][:20]:
                log_addr = rlog['address'].lower()
                if rlog['topics'] and rlog['topics'][0].hex() == TRANSFER_SIG[2:]:
                    from_a = '0x' + rlog['topics'][1].hex()[-40:] if len(rlog['topics']) > 1 else '?'
                    to_a = '0x' + rlog['topics'][2].hex()[-40:] if len(rlog['topics']) > 2 else '?'
                    amt = int(rlog['data'].hex(), 16) / 1e18
                    tok_label = lbl(log_addr)
                    if tok_label.endswith('...'):
                        tok_label = get_symbol(log_addr)
                    print(f'    Transfer [{tok_label}]: {lbl(from_a)} -> {lbl(to_a)}: {amt:.4f}')
                else:
                    topic0 = rlog['topics'][0].hex()[:10] if rlog['topics'] else 'none'
                    print(f'    Event {topic0}... on {lbl(log_addr)}')
        except Exception as e:
            print(f'  Error: {e}')
        sys.stdout.flush()

    # ---- APPROACH 5: Check wider AFF history (100K, 200K blocks back) ----
    for lookback in [100000, 200000]:
        start = max(0, current_block - lookback)
        end = start + 10000  # just check a 10K window at the start of lookback
        print(f'\n  Checking AFF activity in blocks {start}-{end} ({lookback} blocks ago)...')
        try:
            logs_old = w3.eth.get_logs({
                'fromBlock': start,
                'toBlock': end,
                'address': Web3.to_checksum_address(AFF),
                'topics': [TRANSFER_SIG, None, to_topic],
            })
            if logs_old:
                total = sum(int(l['data'].hex(), 16) / 1e18 for l in logs_old)
                print(f'    AFF received: {len(logs_old)} transfers, {total:.4f} AFF')
            else:
                print(f'    No AFF activity')
        except Exception as e:
            print(f'    Error: {e}')
        try:
            logs_old_out = w3.eth.get_logs({
                'fromBlock': start,
                'toBlock': end,
                'address': Web3.to_checksum_address(AFF),
                'topics': [TRANSFER_SIG, from_topic],
            })
            if logs_old_out:
                total = sum(int(l['data'].hex(), 16) / 1e18 for l in logs_old_out)
                print(f'    AFF sent: {len(logs_old_out)} transfers, {total:.4f} AFF')
            else:
                print(f'    No outgoing AFF activity')
        except Exception as e:
            print(f'    Error: {e}')
        sys.stdout.flush()

    time.sleep(0.5)

# ---- CROSS-BOT: Check inter-bot AFF transfers across wider range ----
print(f'\n{"="*70}')
print(f'  CROSS-BOT ANALYSIS')
print(f'{"="*70}')

for src_name, src_addr in BOTS.items():
    for dst_name, dst_addr in BOTS.items():
        if src_name == dst_name:
            continue
        src_t = '0x' + src_addr[2:].lower().zfill(64)
        dst_t = '0x' + dst_addr[2:].lower().zfill(64)
        for lookback in [200000]:
            try:
                logs = w3.eth.get_logs({
                    'fromBlock': max(0, current_block - lookback),
                    'toBlock': current_block,
                    'address': Web3.to_checksum_address(AFF),
                    'topics': [TRANSFER_SIG, src_t, dst_t],
                })
                if logs:
                    total = sum(int(l['data'].hex(), 16) / 1e18 for l in logs)
                    print(f'  AFF: {src_name} -> {dst_name}: {len(logs)} transfers, {total:.4f} AFF (last {lookback} blocks)')
            except Exception as e:
                print(f'  Error {src_name}->{dst_name}: {e}')

# ---- Check Multi AFFECTION contract activity ----
print(f'\n  Multi AFFECTION contract activity (last 5000 blocks):')
multi_from = '0x' + MULTI_AFF[2:].zfill(64)
try:
    logs_multi_out = w3.eth.get_logs({
        'fromBlock': current_block - 5000,
        'toBlock': current_block,
        'address': Web3.to_checksum_address(AFF),
        'topics': [TRANSFER_SIG, multi_from],
    })
    print(f'  AFF sent from Multi_AFF: {len(logs_multi_out)} transfers')
    if logs_multi_out:
        recipients = {}
        for l in logs_multi_out:
            to_a = '0x' + l['topics'][2].hex()[-40:]
            amt = int(l['data'].hex(), 16) / 1e18
            recipients[to_a] = recipients.get(to_a, 0) + amt
        for r, a in sorted(recipients.items(), key=lambda x: -x[1])[:10]:
            print(f'    -> {lbl(r)}: {a:.4f} AFF')
except Exception as e:
    print(f'  Error: {e}')

# Check AFF mints to Multi AFF contract
multi_to = '0x' + MULTI_AFF[2:].zfill(64)
try:
    logs_mint_multi = w3.eth.get_logs({
        'fromBlock': current_block - 5000,
        'toBlock': current_block,
        'address': Web3.to_checksum_address(AFF),
        'topics': [TRANSFER_SIG, '0x' + '0'*64, multi_to],
    })
    print(f'\n  AFF minted TO Multi_AFF: {len(logs_mint_multi)} mints')
except Exception as e:
    print(f'  Error: {e}')

# Check AFF contract self-balance and total supply
try:
    aff_self = aff_c.functions.balanceOf(Web3.to_checksum_address(AFF)).call() / 1e18
    print(f'\n  AFF contract self-balance: {aff_self:.4f}')
except:
    pass
try:
    multi_bal = aff_c.functions.balanceOf(Web3.to_checksum_address(MULTI_AFF)).call() / 1e18
    print(f'  Multi_AFF AFF balance: {multi_bal:.4f}')
except:
    pass

print('\n\nDone.')
