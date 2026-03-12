"""Find actual activity period of bots via binary search + decode TXs by receipt."""
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
    '0xcc78a0acdf847a2c1714d2a925bb4477df5d48a6': 'Atropa',
    '0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff': 'FED',
    '0x232a27ab6941281b3f474fe5ff7cc89816fb675a': 'Fa',
    '0x73a19fafb359faf519c9707b781dfdb88407d10d': 'Faung',
    '0xa96bcbed7f01de6ceed14fc86d90f21a36de2143': 'RNG',
    '0xccddacef154704c604365db9e3b1df356b9c4b6e2': 'Multi_PI',
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

# ---- FIND ACTIVITY WINDOW: Binary search for last block with activity ----
# Use eth_getTransactionCount at different blocks to find when nonce stopped growing

print('\n' + '='*70)
print('  FINDING ACTIVITY WINDOWS')
print('='*70)

for bot_name, bot_addr in BOTS.items():
    final_nonce = w3.eth.get_transaction_count(bot_addr)
    print(f'\n  {bot_name} ({bot_addr}): final nonce = {final_nonce}')

    # Binary search: find the block where nonce reached final value
    lo, hi = 15000000, current_block  # PulseChain genesis ~15M
    while lo < hi - 100:
        mid = (lo + hi) // 2
        try:
            n = w3.eth.get_transaction_count(bot_addr, block_identifier=mid)
            if n < final_nonce:
                lo = mid
            else:
                hi = mid
        except:
            lo = mid

    # Now scan around 'hi' to find exact last TX block
    print(f'    Last TX approximately at block: {hi}')
    print(f'    That is {current_block - hi} blocks ago')

    # Also find first TX
    lo2, hi2 = 15000000, current_block
    while lo2 < hi2 - 100:
        mid = (lo2 + hi2) // 2
        try:
            n = w3.eth.get_transaction_count(bot_addr, block_identifier=mid)
            if n == 0:
                lo2 = mid
            else:
                hi2 = mid
        except:
            lo2 = mid
    print(f'    First TX approximately at block: {hi2}')
    print(f'    Activity span: blocks {hi2} to {hi} ({hi - hi2} blocks)')

    # Convert blocks to rough dates (PulseChain ~3s blocks)
    secs_since_last = (current_block - hi) * 3
    days_since_last = secs_since_last / 86400
    secs_since_first = (current_block - hi2) * 3
    days_since_first = secs_since_first / 86400
    print(f'    First TX: ~{days_since_first:.0f} days ago')
    print(f'    Last TX: ~{days_since_last:.0f} days ago')
    sys.stdout.flush()

    # ---- Now scan a window around the LAST active block for AFF transfers ----
    scan_start = max(0, hi - 2000)
    scan_end = min(current_block, hi + 100)

    to_topic = '0x' + bot_addr[2:].lower().zfill(64)
    from_topic = '0x' + bot_addr[2:].lower().zfill(64)

    print(f'\n    Scanning AFF transfers around last activity (blocks {scan_start}-{scan_end})...')

    # AFF incoming
    try:
        logs_in = w3.eth.get_logs({
            'fromBlock': scan_start,
            'toBlock': scan_end,
            'address': Web3.to_checksum_address(AFF),
            'topics': [TRANSFER_SIG, None, to_topic],
        })
        if logs_in:
            total = sum(int(l['data'].hex(), 16) / 1e18 for l in logs_in)
            print(f'    AFF received: {len(logs_in)} transfers, {total:.4f} total')
            # Show last 5
            for l in logs_in[-5:]:
                from_a = '0x' + l['topics'][1].hex()[-40:]
                amt = int(l['data'].hex(), 16) / 1e18
                print(f'      Block {l["blockNumber"]}: {amt:.4f} AFF from {lbl(from_a)}')
        else:
            print(f'    No AFF received in window')
    except Exception as e:
        print(f'    Error: {e}')

    # AFF outgoing
    try:
        logs_out = w3.eth.get_logs({
            'fromBlock': scan_start,
            'toBlock': scan_end,
            'address': Web3.to_checksum_address(AFF),
            'topics': [TRANSFER_SIG, from_topic],
        })
        if logs_out:
            total = sum(int(l['data'].hex(), 16) / 1e18 for l in logs_out)
            print(f'    AFF sent: {len(logs_out)} transfers, {total:.4f} total')
            for l in logs_out[-5:]:
                to_a = '0x' + l['topics'][2].hex()[-40:]
                amt = int(l['data'].hex(), 16) / 1e18
                print(f'      Block {l["blockNumber"]}: {amt:.4f} AFF to {lbl(to_a)}')
        else:
            print(f'    No AFF sent in window')
    except Exception as e:
        print(f'    Error: {e}')
    sys.stdout.flush()

    # ---- Scan ALL token transfers around last activity ----
    print(f'\n    All token transfers around last activity:')
    try:
        all_out = w3.eth.get_logs({
            'fromBlock': scan_start,
            'toBlock': scan_end,
            'topics': [TRANSFER_SIG, from_topic],
        })
        if all_out:
            by_token = {}
            for l in all_out:
                tok = l['address'].lower()
                to_a = '0x' + l['topics'][2].hex()[-40:]
                amt = int(l['data'].hex(), 16) / 1e18
                if tok not in by_token:
                    by_token[tok] = {'count': 0, 'total': 0, 'dests': set()}
                by_token[tok]['count'] += 1
                by_token[tok]['total'] += amt
                by_token[tok]['dests'].add(to_a)
            print(f'    Outgoing token transfers: {len(all_out)} across {len(by_token)} tokens')
            for tok, info in sorted(by_token.items(), key=lambda x: -x[1]['count'])[:15]:
                sym = lbl(tok)
                if sym.endswith('...'):
                    sym = get_symbol(tok) + f' ({tok[:10]}...)'
                dests_str = ', '.join(lbl(d) for d in list(info['dests'])[:3])
                print(f'      {sym}: {info["count"]}x, {info["total"]:.2f} -> [{dests_str}]')
        else:
            print(f'    No outgoing transfers')
    except Exception as e:
        print(f'    Error: {e}')
    sys.stdout.flush()

    try:
        all_in = w3.eth.get_logs({
            'fromBlock': scan_start,
            'toBlock': scan_end,
            'topics': [TRANSFER_SIG, None, to_topic],
        })
        if all_in:
            by_token = {}
            for l in all_in:
                tok = l['address'].lower()
                from_a = '0x' + l['topics'][1].hex()[-40:]
                amt = int(l['data'].hex(), 16) / 1e18
                if tok not in by_token:
                    by_token[tok] = {'count': 0, 'total': 0, 'srcs': set()}
                by_token[tok]['count'] += 1
                by_token[tok]['total'] += amt
                by_token[tok]['srcs'].add(from_a)
            print(f'    Incoming token transfers: {len(all_in)} across {len(by_token)} tokens')
            for tok, info in sorted(by_token.items(), key=lambda x: -x[1]['count'])[:15]:
                sym = lbl(tok)
                if sym.endswith('...'):
                    sym = get_symbol(tok) + f' ({tok[:10]}...)'
                srcs_str = ', '.join(lbl(s) for s in list(info['srcs'])[:3])
                print(f'      {sym}: {info["count"]}x, {info["total"]:.2f} <- [{srcs_str}]')
        else:
            print(f'    No incoming transfers')
    except Exception as e:
        print(f'    Error: {e}')
    sys.stdout.flush()

    # ---- Decode 5 actual TXs from this bot near its last active block ----
    print(f'\n    Decoding TXs from blocks near last activity...')
    found_txs = []
    for blk_num in range(hi, max(scan_start, hi - 500), -1):
        try:
            blk = w3.eth.get_block(blk_num, full_transactions=True)
            for tx in blk.transactions:
                if tx['from'].lower() == bot_addr.lower():
                    inp = tx['input'].hex() if isinstance(tx['input'], bytes) else tx['input']
                    selector = inp[:10] if len(inp) >= 10 else inp
                    func_name = SELECTORS.get(selector, f'unknown({selector})')
                    to_addr = tx['to'].lower() if tx['to'] else 'create'
                    found_txs.append({
                        'block': blk_num,
                        'hash': tx['hash'].hex(),
                        'to': to_addr,
                        'func': func_name,
                        'value': tx['value'] / 1e18,
                        'input': inp,
                    })
        except:
            pass
        if len(found_txs) >= 5:
            break

    for t in found_txs[:5]:
        v = f' ({t["value"]:.1f} PLS)' if t['value'] > 0 else ''
        print(f'    Block {t["block"]}: {t["func"]:50s} -> {lbl(t["to"])}{v}')

        # Decode receipt
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
                    print(f'      [{tok_l}] {lbl(from_a)} -> {lbl(to_a)}: {amt:.4f}')
                else:
                    topic0 = rlog['topics'][0].hex()[:10] if rlog['topics'] else 'none'
                    print(f'      event {topic0}... on {lbl(log_addr)}')
        except:
            pass

    if not found_txs:
        print(f'    Could not find TXs by scanning blocks (may need wider range)')
    sys.stdout.flush()

    time.sleep(0.5)

print('\n\nDone.')
