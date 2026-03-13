import os, json, time, sys
from web3 import Web3

w3 = Web3(Web3.HTTPProvider('https://rpc-pulsechain.g4mm4.io', request_kwargs={'timeout': 60}))
print(f'Connected: {w3.is_connected()}, Block: {w3.eth.block_number}')

BOTS = {
    'Minter': '0x217a76D9BEf7CeC27eFB5039099221241ca26F93',
    'Buyer': '0x1B79F904087DaaF6C67d7AD2cfA1D7c727De885B',
    'Sell': '0xa767a0D5E04eD4c90Ad68F316A9E55090aa28c51',
}

AFF = '0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D'.lower()
MULTI_AFF = '0xCF138a83D739eE98D7A54159E94e5BFaa4B61988'.lower()
TRANSFER_SIG = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'

# Known function selectors (expanded)
SELECTORS = {
    '0x7c88e3d9': 'Generate()',
    '0xa9059cbb': 'transfer(address,uint256)',
    '0x23b872dd': 'transferFrom(address,address,uint256)',
    '0x095ea7b3': 'approve(address,uint256)',
    '0x38ed1739': 'swapExactTokensForTokens',
    '0x8803dbee': 'swapTokensForExactTokens',
    '0x7ff36ab5': 'swapExactETHForTokens',
    '0x18cbafe5': 'swapExactTokensForETH',
    '0xfb3bdb41': 'swapETHForExactTokens',
    '0x4a25d94a': 'swapTokensForExactETH',
    '0x5f575529': 'swap()',
    '0xd06ca61f': 'getAmountsOut',
    '0xe8e33700': 'addLiquidity',
    '0xf305d719': 'addLiquidityETH',
    '0xbaa2abde': 'removeLiquidity',
    '0x02751cec': 'removeLiquidityETH',
    '0x791ac947': 'swapExactTokensForETHSupportingFeeOnTransferTokens',
    '0x5c11d795': 'swapExactTokensForTokensSupportingFeeOnTransferTokens',
    '0xb6f9de95': 'swapExactETHForTokensSupportingFeeOnTransferTokens',
}

# Known addresses for labeling
KNOWN_ADDRS = {
    AFF: 'AFFECTION',
    MULTI_AFF: 'Multi_AFFECTION',
    '0x165c3410fc91ef562c50559f7d2289febed552d9': 'PulseX_V2_Router',
    '0x98bf93ebf5c380c0e6ae8e192a7e2ae08edacc02': 'PulseX_V1_Router',
    '0xa1077a294dde1b09bb078844df40758a5d0f9a27': 'WPLS',
    BOTS['Minter'].lower(): 'Minter_Bot',
    BOTS['Buyer'].lower(): 'Buyer_Bot',
    BOTS['Sell'].lower(): 'Sell_Bot',
    '0x' + '0'*40: 'ZERO/MINT',
}

def label(addr):
    a = addr.lower()
    return KNOWN_ADDRS.get(a, addr[:14] + '...')

current_block = w3.eth.block_number

erc20_abi = [
    {'inputs':[{'name':'a','type':'address'}],'name':'balanceOf','outputs':[{'name':'','type':'uint256'}],'stateMutability':'view','type':'function'},
]
aff_c = w3.eth.contract(address=Web3.to_checksum_address(AFF), abi=erc20_abi)

for bot_name, bot_addr in BOTS.items():
    print(f'\n{"="*70}')
    print(f'  {bot_name} Bot: {bot_addr}')
    print(f'{"="*70}')
    sys.stdout.flush()

    # Get nonce (total TX count)
    nonce = w3.eth.get_transaction_count(bot_addr)
    print(f'  Total TXs (nonce): {nonce}')

    # Check AFF balance
    aff_bal = aff_c.functions.balanceOf(Web3.to_checksum_address(bot_addr)).call()
    print(f'  AFF balance: {aff_bal / 1e18:.4f}')

    # PLS balance
    pls_bal = w3.eth.get_balance(Web3.to_checksum_address(bot_addr))
    print(f'  PLS balance: {pls_bal / 1e18:.4f}')

    # Pad address for topic filter
    to_topic = '0x' + bot_addr[2:].lower().zfill(64)
    from_topic = '0x' + bot_addr[2:].lower().zfill(64)
    aff_topic = '0x' + AFF[2:].lower().zfill(64)
    multi_topic = '0x' + MULTI_AFF[2:].lower().zfill(64)

    scan_wide = 50000
    start_wide = max(0, current_block - scan_wide)
    scan_range = 10000
    start_block = max(0, current_block - scan_range)

    # ---- Incoming AFF transfers ----
    logs_in = []
    try:
        logs_in = w3.eth.get_logs({
            'fromBlock': start_wide,
            'toBlock': current_block,
            'address': Web3.to_checksum_address(AFF),
            'topics': [TRANSFER_SIG, None, to_topic],
        })
        print(f'\n  AFF transfers TO {bot_name} (last {scan_wide} blocks): {len(logs_in)}')
        senders = {}
        total_in = 0
        for log in logs_in:
            from_addr = '0x' + log['topics'][1].hex()[-40:]
            amount = int(log['data'].hex(), 16) / 1e18
            total_in += amount
            senders[from_addr] = senders.get(from_addr, 0) + amount
        print(f'  Total AFF received: {total_in:.4f}')
        print(f'  Sender breakdown:')
        for addr, amt in sorted(senders.items(), key=lambda x: -x[1])[:10]:
            print(f'    {label(addr)}: {amt:.4f} AFF')
        print(f'  Last 5 incoming:')
        for log in logs_in[-5:]:
            from_addr = '0x' + log['topics'][1].hex()[-40:]
            amount = int(log['data'].hex(), 16) / 1e18
            print(f'    Block {log["blockNumber"]}: {amount:.4f} AFF from {label(from_addr)}')
    except Exception as e:
        print(f'  Error scanning incoming: {e}')
    sys.stdout.flush()

    # ---- Outgoing AFF transfers ----
    logs_out = []
    try:
        logs_out = w3.eth.get_logs({
            'fromBlock': start_wide,
            'toBlock': current_block,
            'address': Web3.to_checksum_address(AFF),
            'topics': [TRANSFER_SIG, from_topic, None],
        })
        print(f'\n  AFF transfers FROM {bot_name} (last {scan_wide} blocks): {len(logs_out)}')
        recipients = {}
        total_out = 0
        for log in logs_out:
            to_addr = '0x' + log['topics'][2].hex()[-40:]
            amount = int(log['data'].hex(), 16) / 1e18
            total_out += amount
            recipients[to_addr] = recipients.get(to_addr, 0) + amount
        print(f'  Total AFF sent: {total_out:.4f}')
        print(f'  Recipient breakdown:')
        for addr, amt in sorted(recipients.items(), key=lambda x: -x[1])[:10]:
            print(f'    {label(addr)}: {amt:.4f} AFF')
        print(f'  Last 5 outgoing:')
        for log in logs_out[-5:]:
            to_addr = '0x' + log['topics'][2].hex()[-40:]
            amount = int(log['data'].hex(), 16) / 1e18
            print(f'    Block {log["blockNumber"]}: {amount:.4f} AFF to {label(to_addr)}')
    except Exception as e:
        print(f'  Error scanning outgoing: {e}')
    sys.stdout.flush()

    # ---- AFF MINT events (from 0x0) ----
    try:
        logs_mint = w3.eth.get_logs({
            'fromBlock': start_wide,
            'toBlock': current_block,
            'address': Web3.to_checksum_address(AFF),
            'topics': [TRANSFER_SIG, '0x' + '0'*64, to_topic],
        })
        print(f'\n  AFF MINT events TO {bot_name} (last {scan_wide} blocks): {len(logs_mint)}')
        if logs_mint:
            total_minted = sum(int(l['data'].hex(), 16) / 1e18 for l in logs_mint)
            print(f'  Total AFF minted directly: {total_minted:.4f}')
            for log in logs_mint[-5:]:
                amount = int(log['data'].hex(), 16) / 1e18
                print(f'    Block {log["blockNumber"]}: MINTED {amount:.4f} AFF')
    except Exception as e:
        print(f'  Error scanning mints: {e}')

    # ---- AFF from Multi AFFECTION contract ----
    try:
        logs_multi = w3.eth.get_logs({
            'fromBlock': start_wide,
            'toBlock': current_block,
            'address': Web3.to_checksum_address(AFF),
            'topics': [TRANSFER_SIG, multi_topic, to_topic],
        })
        print(f'\n  AFF from Multi AFFECTION -> {bot_name}: {len(logs_multi)}')
        if logs_multi:
            total_multi = sum(int(l['data'].hex(), 16) / 1e18 for l in logs_multi)
            print(f'  Total: {total_multi:.4f}')
            for log in logs_multi[-5:]:
                amount = int(log['data'].hex(), 16) / 1e18
                print(f'    Block {log["blockNumber"]}: {amount:.4f} AFF from MultiAFF')
    except Exception as e:
        print(f'  Error: {e}')

    # ---- AFF from AFFECTION contract (Purchase/BuyWith path) ----
    try:
        logs_purchase = w3.eth.get_logs({
            'fromBlock': start_wide,
            'toBlock': current_block,
            'address': Web3.to_checksum_address(AFF),
            'topics': [TRANSFER_SIG, aff_topic, to_topic],
        })
        print(f'\n  AFF from AFFECTION contract -> {bot_name} (Purchase/BuyWith): {len(logs_purchase)}')
        if logs_purchase:
            total_p = sum(int(l['data'].hex(), 16) / 1e18 for l in logs_purchase)
            print(f'  Total: {total_p:.4f}')
            for log in logs_purchase[-5:]:
                amount = int(log['data'].hex(), 16) / 1e18
                print(f'    Block {log["blockNumber"]}: {amount:.4f} AFF (Purchase/BuyWith)')
    except Exception as e:
        print(f'  Error: {e}')

    # ---- Decode actual TXs from log-discovered TX hashes ----
    print(f'\n  --- Decoding TX function calls ---')
    all_tx_hashes = set()
    for logs_set in [logs_in, logs_out]:
        for log in logs_set[-30:]:
            all_tx_hashes.add(log['transactionHash'].hex())

    func_counts = {}
    target_counts = {}
    sample_txs = []

    for tx_hash in list(all_tx_hashes)[:40]:
        try:
            tx = w3.eth.get_transaction(tx_hash)
            sender = tx['from'].lower()
            to_addr = tx['to'].lower() if tx['to'] else 'contract_creation'
            inp = tx['input'].hex() if isinstance(tx['input'], bytes) else tx['input']
            selector = inp[:10] if len(inp) >= 10 else inp
            func_name = SELECTORS.get(selector, f'unknown({selector})')

            if sender == bot_addr.lower():
                func_counts[func_name] = func_counts.get(func_name, 0) + 1
                target_counts[to_addr] = target_counts.get(to_addr, 0) + 1
                sample_txs.append({
                    'hash': tx_hash[:16] + '...',
                    'to': to_addr,
                    'func': func_name,
                    'value_pls': tx['value'] / 1e18,
                    'block': tx['blockNumber'],
                    'input_len': len(inp),
                })
        except:
            pass

    if func_counts:
        print(f'  Function calls by {bot_name}:')
        for func, cnt in sorted(func_counts.items(), key=lambda x: -x[1]):
            print(f'    {func}: {cnt}x')
    if target_counts:
        print(f'  Target contracts:')
        for addr, cnt in sorted(target_counts.items(), key=lambda x: -x[1]):
            print(f'    {label(addr)}: {cnt}x')
    if sample_txs:
        sample_txs.sort(key=lambda x: x['block'])
        print(f'  Sample TXs (last 15):')
        for s in sample_txs[-15:]:
            print(f'    Block {s["block"]}: {s["func"]:50s} -> {label(s["to"])} (value={s["value_pls"]:.1f} PLS)')
    sys.stdout.flush()

    # ---- Check WPLS (swap output) transfers ----
    WPLS = '0xa1077a294dde1b09bb078844df40758a5d0f9a27'
    wpls_topic_to = '0x' + bot_addr[2:].lower().zfill(64)
    try:
        logs_wpls = w3.eth.get_logs({
            'fromBlock': start_wide,
            'toBlock': current_block,
            'address': Web3.to_checksum_address(WPLS),
            'topics': [TRANSFER_SIG, None, wpls_topic_to],
        })
        print(f'\n  WPLS transfers TO {bot_name}: {len(logs_wpls)}')
        if logs_wpls:
            total_wpls = sum(int(l['data'].hex(), 16) / 1e18 for l in logs_wpls)
            print(f'  Total WPLS received: {total_wpls:.4f}')
            for log in logs_wpls[-5:]:
                from_addr = '0x' + log['topics'][1].hex()[-40:]
                amount = int(log['data'].hex(), 16) / 1e18
                print(f'    Block {log["blockNumber"]}: {amount:.4f} WPLS from {label(from_addr)}')
    except Exception as e:
        print(f'  Error WPLS: {e}')
    sys.stdout.flush()

    # ---- Token balances ----
    print(f'\n  --- Token balances for {bot_name} ---')
    tokens_to_check = {
        'WPLS': ('0xA1077a294dDE1B09bB078844df40758a5D0f9a27', 18),
        'pDAI': ('0x6B175474E89094C44Da98b954EedeAC495271d0F', 18),
        'pUSDC': ('0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', 6),
        'pINDEPENDENCE': ('0xA2262D7728C689526693aE893D0fD8a352C7073C', 18),
        'GIMME_FIVE': ('0x2fc636E7fDF9f3E8d61033103052079781a6e7D2', 18),
        'MATH_v1.1': ('0xB680F0cc810317933F234f67EB6A9E923407f05D', 18),
        'WM': ('0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29', 18),
        'FED': ('0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff', 18),
        'Atropa': ('0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6', 18),
    }
    for tname, (taddr, dec) in tokens_to_check.items():
        try:
            tc = w3.eth.contract(address=Web3.to_checksum_address(taddr), abi=erc20_abi)
            bal = tc.functions.balanceOf(Web3.to_checksum_address(bot_addr)).call()
            if bal > 0:
                print(f'    {tname}: {bal / 10**dec:.4f}')
        except:
            pass
    sys.stdout.flush()

    # ---- Deep dive: decode receipt for 2 sample TXs from this bot ----
    if sample_txs:
        print(f'\n  --- Receipt deep-dive (2 sample TXs from {bot_name}) ---')
        for s in sample_txs[-2:]:
            tx_hash = None
            # Re-find full hash from logs
            for logs_set in [logs_in, logs_out]:
                for log in logs_set:
                    h = log['transactionHash'].hex()
                    if h[:16] == s['hash'][:16]:
                        tx_hash = h
                        break
                if tx_hash:
                    break
            if not tx_hash:
                continue
            try:
                receipt = w3.eth.get_transaction_receipt(tx_hash)
                print(f'\n    TX: {tx_hash}')
                print(f'    Status: {"SUCCESS" if receipt["status"] == 1 else "FAILED"}')
                print(f'    Gas used: {receipt["gasUsed"]}')
                print(f'    Block: {receipt["blockNumber"]}')
                print(f'    Logs ({len(receipt["logs"])}):')
                for rlog in receipt['logs'][:15]:
                    log_addr = rlog['address'].lower()
                    if rlog['topics'] and rlog['topics'][0].hex() == TRANSFER_SIG[2:]:
                        from_a = '0x' + rlog['topics'][1].hex()[-40:] if len(rlog['topics']) > 1 else '?'
                        to_a = '0x' + rlog['topics'][2].hex()[-40:] if len(rlog['topics']) > 2 else '?'
                        amt = int(rlog['data'].hex(), 16) / 1e18
                        print(f'      Transfer on {label(log_addr)}: {label(from_a)} -> {label(to_a)}: {amt:.4f}')
                    else:
                        topic0 = rlog['topics'][0].hex()[:10] if rlog['topics'] else 'none'
                        print(f'      Event {topic0}... on {label(log_addr)}')
            except Exception as e:
                print(f'    Error fetching receipt: {e}')
        sys.stdout.flush()

    time.sleep(0.5)

print('\n\n' + '='*70)
print('  CROSS-BOT FLOW ANALYSIS')
print('='*70)

# Check if bots send AFF to each other
for src_name, src_addr in BOTS.items():
    for dst_name, dst_addr in BOTS.items():
        if src_name == dst_name:
            continue
        src_topic = '0x' + src_addr[2:].lower().zfill(64)
        dst_topic = '0x' + dst_addr[2:].lower().zfill(64)
        try:
            logs = w3.eth.get_logs({
                'fromBlock': max(0, current_block - 50000),
                'toBlock': current_block,
                'address': Web3.to_checksum_address(AFF),
                'topics': [TRANSFER_SIG, src_topic, dst_topic],
            })
            if logs:
                total = sum(int(l['data'].hex(), 16) / 1e18 for l in logs)
                print(f'  {src_name} -> {dst_name}: {len(logs)} transfers, {total:.4f} AFF total')
                for log in logs[-3:]:
                    amount = int(log['data'].hex(), 16) / 1e18
                    print(f'    Block {log["blockNumber"]}: {amount:.4f} AFF')
        except Exception as e:
            print(f'  Error {src_name}->{dst_name}: {e}')

# Check PLS transfers between bots
print(f'\n  PLS (native) flow between bots:')
for src_name, src_addr in BOTS.items():
    for dst_name, dst_addr in BOTS.items():
        if src_name == dst_name:
            continue
        # Can't easily scan native PLS transfers without tracing, skip
        pass
print(f'  (Native PLS transfers require trace API - skipped)')

print('\n\nDone.')
