---
name: recon
description: "On-chain reconnaissance: wallet balances, engine prerequisites, TGSv8 state, profitable opportunities. Read-only — no transactions sent."
argument-hint: "[target: wallet|engines|arb|treasury|tgsv8|all]"
user-invocable: true
disable-model-invocation: false
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
---

# /recon — On-Chain Reconnaissance

Perform read-only on-chain reconnaissance for the JOYSTICK bot on PulseChain (chain 369).

## Context Files — Read First

- `/opt/joystick/repo/CLAUDE.md` — ecosystem addresses, token mechanics, key constants
- `/opt/joystick/repo/scripts/Joystick/CLAUDE.md` — bot architecture, engine descriptions
- `/opt/joystick/repo/scripts/Joystick/core/config.py` — all contract addresses and thresholds

## Dynamic Context

Current block and gas:
!`python3 -c "import requests,json; rpc='https://rpc-pulsechain.g4mm4.io'; r=requests.post(rpc,json={'jsonrpc':'2.0','method':'eth_blockNumber','id':1}); b=int(json.loads(r.text)['result'],16); r2=requests.post(rpc,json={'jsonrpc':'2.0','method':'eth_gasPrice','id':2}); g=int(json.loads(r2.text)['result'],16)/1e9; print(f'Block: {b} | Gas: {g:.1f} Beats')"`

## Arguments

`$ARGUMENTS` can be:
- `wallet` — Joey wallet balances (PLS, GIBS, AFF, WM, ATROPA, VOID, FED, WPLS)
- `engines` — Check all 8 engine prerequisites and readiness
- `arb` — Scan for Purchase→DEX arbitrage opportunities across QINGs
- `treasury` — Check treasury token backing for claimable value
- `tgsv8` — TGSv8/TGSv8+ contract state, authorization, balances
- `all` or empty — Run wallet + engines + tgsv8 combined

## Rules

1. **NEVER send transactions.** All calls must be `eth_call` (read-only) or `eth_getBalance`.
2. Use RPC endpoint `https://rpc-pulsechain.g4mm4.io` for all reads.
3. Gas units are **Beats** (not Gwei). `eth_gasPrice` returns Impulses (wei-equiv) — divide by 10^9 for Beats.
4. 1 PLS = 10^18 Impulses = 10^9 Beats.
5. Use Multicall3 (`0xcA11bde05977b3631167028862bE2a173976CA11`) to batch reads where possible.
6. Use `pycryptodome` for keccak (`from Crypto.Hash import keccak`), NOT `pysha3`.

## Key Addresses

```
JOEY_WALLET  = 0x17367877aF5A8D0Eb33ba5689A880f696386E24D
GIBS_LAU     = 0x66a08aa12da955eb63d7ac121a88b2b210a07b03
GIBS_QING    = 0x1B8774C0d0ba2A814A592bE7978DFe78b0e86E35
JOEY_YUE     = 0x8e666227B0C5A42075a4f9bdf5d2176f287a9cf0
TGSv8        = 0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32
AFFECTION    = 0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D
WM           = 0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29
WPLS         = 0xA1077a294dDE1B09bB078844df40758a5D0f9a27
FED          = 0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff
ATROPA       = 0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6
VOID_TOKEN   = 0x965B0d74591bF30327075A247C47dBf487dCff08
```

## Implementation

### Wallet Recon
Write a Python script that uses Multicall3 to batch-read:
- `eth_getBalance(JOEY_WALLET)` for PLS
- `balanceOf(JOEY_WALLET)` for: GIBS_LAU, AFFECTION, WM, ATROPA, VOID, FED, WPLS
- `eth_getBalance(TGSv8)` for contract PLS balance
- Token balances held by TGSv8

Reference: `/opt/joystick/repo/scripts/Joystick/dashboard/chain_reader.py` for Multicall3 patterns.

### Engine Prerequisites
For each engine, check its on-chain prerequisites:
- **E2 CEREAL**: GIBS_LAU self-balance > 0, GIBS/WPLS or GIBS/FED pair reserves
- **E3 MERIDIAN**: SHIO balances (Fornax, Fomalhaute, CHO) at GIBS_LAU and GIBS_QING
- **E4 FACTORY**: WM balance at TGSv8, AFF route profitability
- **E5 ABUPRU**: PLS > 150K floor
- **E6 DaVINCI**: recon_results.json exists with targets
- **E7 BACKBONE**: V2 Federal tokens with Debenture=true
- **E8 PHR3AK**: TGSv8 createV4 readiness, WM balance

### TGSv8 Recon
Check: `owner()`, `paused()`, authorized addresses, nativeBal, token holdings.

## Output Format

```
========================================
  JOYSTICK RECON — Block NNNNNN
  Gas: NN.N Beats
========================================

── Wallet ──
PLS:      1,979,625
GIBS:     0 (all in LP)
AFF:      127.18
WM:       263.15
...

── TGSv8 ──
PLS:      NNN
Owner:    0x...
Paused:   false
...

── Engine Prerequisites ──
E1 RAZOR      [OK|WARN|FAIL]  one-line reason
E2 CEREAL     [OK|WARN|FAIL]  one-line reason
...
```

Show PLS values with commas. Token balances to 2 decimal places.
