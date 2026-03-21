---
name: tx-debug
description: "Debug a failed or stuck PulseChain transaction. Traces the call, decodes calldata, identifies revert reason, suggests fix."
argument-hint: "<tx_hash>"
user-invocable: true
disable-model-invocation: false
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - WebFetch
---

# /tx-debug — Transaction Debugger

Debug a failed or stuck transaction on PulseChain (chain 369).

## Context Files — Read First

- `/opt/joystick/repo/CLAUDE.md` — contract addresses (Part 2), known bugs (Part 4), function selectors
- `/opt/joystick/repo/scripts/Joystick/core/config.py` — all addresses for matching
- `/opt/joystick/repo/scripts/Joystick/core/executor.py` — TX building patterns

## Arguments

`$ARGUMENTS` must contain a transaction hash (0x-prefixed, 66 chars). If not provided, ask the user.

## Investigation Steps

### Step 1: Fetch TX Data
Use Python with `requests` to call RPC at `https://rpc-pulsechain.g4mm4.io`:
```python
eth_getTransactionByHash(tx_hash) → from, to, input, value, gasPrice, nonce, blockNumber
eth_getTransactionReceipt(tx_hash) → status, gasUsed, logs, contractAddress
```

### Step 2: Identify Participants
Match `from` and `to` addresses against known addresses:
- Joey: `0x17367877aF5A8D0Eb33ba5689A880f696386E24D`
- TGSv8: `0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32`
- GIBS_LAU: `0x66a08aa12da955eb63d7ac121a88b2b210a07b03`
- Check `core/config.py` for full address list

### Step 3: Decode Calldata
Match the first 4 bytes of `input` against known selectors from CLAUDE.md:
- `0x2499a533` → `Purchase(address,uint256)`
- `0xd805b650` → `Generate()`
- `0xd1f05872` → `multiGenerate(uint256)`
- `0xcc93bb90` → `multiBuyWith(address,uint256)`
- Check TGSv8 selectors: `executeRoute`, `atomicArb`, `batchClaimTreasury`, `batchMintAndClaim`, `mintWM`, etc.

Decode parameters with `eth_abi.decode()`.

### Step 4: Check TX Status
- `status == 1` → Success (check if behavior was unexpected)
- `status == 0` → Reverted — proceed to revert analysis
- No receipt → Pending or dropped

### Step 5: Revert Analysis (for status=0)
Replay via `eth_call` at the block BEFORE the TX:
```python
eth_call({from, to, data, value, gas}, hex(blockNumber - 1))
```
Parse revert reason:
- `0x08c379a2` prefix → Error(string) — decode the string
- `0x4e487b71` prefix → Panic(uint256) — decode panic code
- Custom errors: decode against known contract ABIs

### Step 6: Check Known Bugs
Cross-reference against CLAUDE.md Part 4:
- **V4 mint 2x transferFrom**: approve `type(uint256).max` as fix
- **_mintToCap mints to self**: tokens go to contract, not caller
- **RPCPool race**: "replacement TX underpriced" — use single provider
- **Gas units**: Beats vs Impulses confusion
- **Division by zero**: SHIO balances at 0

### Step 7: Stuck TX Analysis (no receipt)
```python
eth_getTransactionCount(from, "latest")   # confirmed nonce
eth_getTransactionCount(from, "pending")  # pending nonce
```
- TX nonce > confirmed nonce with gap → nonce gap blocking
- TX nonce == pending nonce → gas too low, suggest speedup

### Step 8: BlockScout Supplementary
```
https://api.scan.pulsechain.com/api?module=transaction&action=gettxinfo&txhash={tx_hash}
```

## Output Format

```
========================================
  TX DEBUG — 0xABCD...1234
========================================
Block:     NNNNNN
Status:    REVERTED / SUCCESS / PENDING
From:      0x... (Joey / Minter / Unknown)
To:        0x... (TGSv8 / GIBS_LAU / ...)
Function:  functionName(args...)
Value:     N PLS
Gas Used:  NNN,NNN / NNN,NNN (NN%)
Gas Price: NN.N Beats
Cost:      NNN.NN PLS

─── Revert Reason ───
ErrorName(param types)
  Human-readable explanation of why it reverted.

─── Root Cause ───
Explanation of the underlying issue.

─── Fix ───
Specific steps to resolve the issue.
```
