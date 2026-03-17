# scripts/ — Python Tooling for Dysnomia On-Chain Operations

> **Parent context**: [`../CLAUDE.md`](../CLAUDE.md) (ecosystem, addresses, game mechanics)
> **Bot internals**: [`Joystick/CLAUDE.md`](Joystick/CLAUDE.md) (engine details, architecture, strategies)

---

## Overview

This directory contains all Python scripts for interacting with the Dysnomia/Atropa ecosystem on PulseChain. Scripts fall into three categories:

1. **Standalone TX scripts** (`tx_*.py`) — Execute specific on-chain transactions
2. **Recon/analysis scripts** (`*_recon.py`, `analyze_*.py`, `scan_*.py`) — Read-only chain inspection
3. **The Joystick bot** (`Joystick/`) — Modular arbitrage/treasury exploitation framework

All scripts target PulseChain (chain 369) and use Joey's wallet (`0x17367877aF5A8D0Eb33ba5689A880f696386E24D`).

---

## Shared Patterns

### RPC Configuration
```python
READ_RPC   = "https://rpc-pulsechain.g4mm4.io"   # reads, eth_call, simulations
SUBMIT_RPC = "https://rpc.pulsechain.com"          # TX submission only
```
- **g4mm4.io** for all read operations (faster, supports eth_call simulation)
- **pulsechain.com** for sending signed transactions
- Gas denomination: **Beats** (not Gwei). `1 PLS = 1,000,000,000 Beats`
- `eth_gasPrice` returns Impulses (wei-equivalent). Divide by 10^9 for Beats.

### Wallet Access
Most scripts load the private key from environment:
```python
import os
from web3 import Web3
PRIVATE_KEY = os.environ["JOEY_PK"]
w3 = Web3(Web3.HTTPProvider(READ_RPC))
```
**Never hardcode keys.** Always via env var `JOEY_PK`.

### Common Helpers
Many scripts inline these patterns (no shared lib yet):
- `eth_call(to, data)` — raw JSON-RPC call for read operations
- `erc20_balance(token, holder)` — `balanceOf()` via eth_call
- `get_amounts_out(router, amountIn, path)` — DEX price quoting
- `keccak256(sig)[:4]` — function selector generation (use `pycryptodome` not `pysha3`)

### Gas Estimation
```python
gas_estimate = w3.eth.estimate_gas(tx) 
tx['gas'] = int(gas_estimate * 1.3)  # Always 1.3x multiplier
```
**Never send blind.** If `estimate_gas()` reverts, abort the TX.

### ABI Encoding
Most scripts use raw ABI encoding rather than contract objects for flexibility:
```python
from eth_abi import encode
calldata = selector + encode(['uint256', 'address[]'], [amount, [token_a, token_b]])
```

---

## Script Inventory

### Transaction Scripts (`tx_*.py`)

| Script | Purpose | Key Functions Called |
|--------|---------|-------------------|
| `tx_full_beat_flow.py` | Full Beat orchestration (SHIO → Su() → Beat) | `CHEON.Su()`, `META.Beat()` |
| `tx_cheon_su.py` | CHEON.Su() YUE bar primer | `CHEON.Su(GIBS_QING)` |
| `tx_beat.py` | Direct Beat call | `META.Beat(QingWaat)` |
| `tx_lau_arb.py` | Execute Purchase→DEX arb loop | `Purchase()`, PulseX swap |
| `tx_acquire_shio.py` | Acquire SHIO tokens for Beat prereqs | DEX swaps for Fornax/Fomalhaute/CHO |
| `tx_acquire_shio_p2.py` | Phase 2 SHIO acquisition | Additional SHIO purchases |
| `tx_acquire_qing_tokens.py` | Acquire QING venue tokens | DEX swaps |
| `tx_acquire_zuo.py` | Acquire ZUO tokens | DEX swaps |
| `tx_map_new.py` | Create new QING venue via MAP.New() | `MAP.New(GIBS_LAU)` |
| `tx_sei_start.py` | Initialize player via SEI.Start() | `SEI.Start()` |
| `tx_create_gibs_wpls_pair.py` | Create initial GIBS/WPLS LP pair | PulseX factory + addLiquidity |
| `tx_set_multiplier.py` | Set DSS chat multiplier | `DSS.setChatMultiplier(17)` |
| `tx_void_broadcast.py` | Broadcast message via VOID | `VOID.Chat()` |
| `tx_grav_terraform.py` | Terraform operations | Territory expansion |

### Recon / Analysis Scripts

| Script | Purpose | Output |
|--------|---------|--------|
| `scan_lau_arb.py` | Scan 272+ QINGs for Purchase→DEX arbitrage | Console report, opportunities list |
| `beat_recon.py` | Deep Beat prerequisites check | SHIO balances, contract state |
| `beat_full_diagnostic.py` | Full Beat call chain diagnosis | Step-by-step revert detection |
| `crows_recon.py` | CROWS holder analysis for bouncer access | Holder list, thresholds |
| `enteh_recon.py` | Analyze Enteh's Beat strategy | TX pattern analysis |
| `enteh_zuo_check.py` | Check Enteh's ZUO state | Balance/ownership check |
| `player_recon.py` | Scan active players | Player list, Soul IDs |
| `fornax_holders_recon.py` | Fornax whale mapping | Holder distribution |
| `shio_acquisition_recon.py` | SHIO availability and pricing | DEX liquidity for SHIO tokens |
| `discover_sei_map.py` | Discover SEI→MAP relationships | Contract state mapping |
| `find_sei.py` / `find_sei2.py` / `find_sei_final.py` | SEI contract discovery | Address resolution |
| `find_world.py` | WORLD contract discovery | Address resolution |
| `verify_qing_sei.py` | Verify QING/SEI relationships | Cross-reference check |
| `verify_key.py` | Verify wallet key setup | Key validation |
| `qing_bouncer_check.py` | Check QING bouncer requirements | Access verification |
| `zuo_ownership_recon.py` | ZUO ownership analysis | Ownership mapping |
| `zurich_recon.py` | Zurich contract recon | State inspection |

### AFFECTION Analysis Scripts

| Script | Purpose |
|--------|---------|
| `test_aff_mint.py` | AFFECTION multiGenerate mainnet test harness (full 7-step verification) |
| `test_aff_direct.py` | Direct single-RPC AFF mint test (bypasses RPCPool race condition) |
| `analyze_aff_bots.py` | Grav's bot pipeline Transfer event scanner |
| `analyze_aff_bots_v2.py` | Extended pipeline analysis with payment token tracing |
| `analyze_aff_bots_v3.py` | Pipeline analysis iteration 3 |
| `analyze_aff_bots_v4.py` | Pipeline analysis iteration 4 |
| `analyze_aff_bots_v5.py` | Final pipeline analysis with full route decomposition |

### Deployment Scripts

| Script | Purpose |
|--------|---------|
| `deploy_tgsv8.py` | Deploy TGSv8 execution contract |
| `GIBS_LP_depl0y.py` | Python LP pair deployment orchestration |
| `gibs_pair_creator.py` | GIBS LP pair creation helper |
| `JS-GIBS_LPTB.js` | JavaScript LP token balance checker |
| `JS-Gibs_LPADD.js` | JavaScript LP addition helper |

### Chat / Social Scripts

| Script | Purpose |
|--------|---------|
| `void_chat_full.py` | Full VOID chat interaction |
| `void_chat_reader.py` | Read VOID chat history |
| `void_chat_sync.py` | Sync VOID chat to local store |
| `void_scan.py` | Scan VOID for active users |

### Other Files

- `install.dys` — Dysnomia installation script
- `final_check.py` — Pre-deployment verification
- `archive/` — Superseded scripts kept for reference

---

## Relationship to Joystick Bot

Standalone scripts were the **prototyping ground** for Joystick engines:

| Script Origin | → Joystick Engine |
|--------------|-------------------|
| `tx_full_beat_flow.py` | → E3 `beat.py` |
| `scan_lau_arb.py` + `tx_lau_arb.py` | → E1 `arb.py` |
| `test_aff_mint.py` | → E4 `token_factory.py` (AFF mode) |
| `void_chat_full.py` | → E2 `dss.py` |

**Rule**: Never rewrite existing standalone scripts. Import them as modules if needed, or copy patterns into Joystick engines. Standalone scripts remain useful for one-off recon and debugging outside the bot loop.

---

## Running Scripts

```bash
# From repo root
export JOEY_PK="0x..."
export PULSECHAIN_READ_RPC="https://rpc-pulsechain.g4mm4.io"
export PULSECHAIN_RPC="https://rpc.pulsechain.com"

# Recon (read-only, safe)
python3 scripts/scan_lau_arb.py

# TX scripts (sends transactions — costs gas!)
python3 scripts/tx_cheon_su.py

# Joystick bot
cd scripts/Joystick && pip install -r requirements.txt
python3 -m bot  # or: python3 bot.py
```

### Dependencies
```
web3>=6.0
eth_abi
pycryptodome    # for Crypto.Hash.keccak (NOT pysha3 — unreliable)
requests
```

See `Joystick/requirements.txt` for bot-specific dependencies.

---

## Data Files

| File | Location | Description |
|------|----------|-------------|
| `Joystick/data/recon_results.json` | 39K lines, 1.26 MB | Full treasury recon |
| `Joystick/data/spine_map.json` | 860K | Spine opportunity mapping |
| `Joystick/data/token_master.json` | 574K | Master token registry |
| `Joystick/data/pair_registry.json` | 543K | Known DEX pair registry |
| `Joystick/data/contracts.json` | 1.5K | Runtime address reference |
| `Joystick/data/v2_federal_tokens.json` | 5.5K | V2 Federal token scan |
| `Joystick/data/abis/` | 61K | Contract ABI files |
| `../data/void_chat.jsonl` | 30K | VOID chat log archive |

---

## Implementation Notes

- **Never use `pysha3`** — unreliable on many platforms. Use `pycryptodome` (`from Crypto.Hash import keccak`)
- **eth_call simulation before any TX** — always test with eth_call first
- **Atomic file writes** — use `os.rename()` / `os.replace()` for data files
- **No OpenZeppelin imports** in any Solidity — inline guards only
- **Chain ID 369** — always set explicitly in TX signing
- **BlockScout API** — `https://api.scan.pulsechain.com/api` returns decoded function names, accessible with standard User-Agent

**Last Updated**: 2026-03-16
