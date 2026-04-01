# scripts/ — Python Tooling for Dysnomia On-Chain Operations

> **Parent context**: [`../CLAUDE.md`](../CLAUDE.md) (ecosystem, addresses, game mechanics)
> **Bot internals**: [`Joystick/CLAUDE.md`](Joystick/CLAUDE.md) (engine details, architecture, strategies)

---

## Overview

This directory contains all Python scripts for interacting with the Dysnomia/Atropa ecosystem on PulseChain. Scripts fall into three categories:

1. **Standalone TX scripts** (`tx_*.py`) — Execute specific on-chain transactions
2. **Recon/analysis scripts** (`recon_*.py`, `scan_*.py`) — Read-only chain inspection
3. **Deployment scripts** (`deploy_*.py`, `lp_*.py`) — Contract and LP deployment
4. **Chat scripts** (`chat_*.py`) — VOID chat interaction
5. **The Joystick bot** (`Joystick/`) — Modular arbitrage/treasury exploitation framework

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
tx['gas'] = int(gas_estimate * 2.5)  # GAS_MULT = 2.5x on PulseChain
```
**Never send blind.** If `estimate_gas()` reverts, abort the TX. Use EIP-1559 Type 2 transactions with `maxFeePerGas` + `maxPriorityFeePerGas`.

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
| `tx_beat_flow.py` | Full Beat orchestration (SHIO → Su() → Beat) | `CHEON.Su()`, `META.Beat()` |
| `tx_cheon_su.py` | CHEON.Su() YUE bar primer | `CHEON.Su(GIBS_QING)` |
| `tx_beat.py` | Direct Beat call | `META.Beat(QingWaat)` |
| `tx_lau_arb.py` | Execute Purchase→DEX arb loop | `Purchase()`, PulseX swap |
| `tx_acquire_shio.py` | Acquire SHIO tokens for Beat prereqs | DEX swaps for Fornax/Fomalhaute/CHO |
| `tx_acquire_shio_p2.py` | Phase 2 SHIO acquisition | Additional SHIO purchases |
| `tx_acquire_qing.py` | Acquire QING venue tokens | DEX swaps |
| `tx_acquire_zuo.py` | Acquire ZUO tokens | DEX swaps |
| `tx_map_new.py` | Create new QING venue via MAP.New() | `MAP.New(GIBS_LAU)` |
| `tx_sei_start.py` | Initialize player via SEI.Start() | `SEI.Start()` |
| `tx_set_multiplier.py` | Set DSS chat multiplier | `DSS.setChatMultiplier(17)` |
| `tx_terraform.py` | Terraform operations | Territory expansion |

### Recon / Analysis Scripts

| Script | Purpose |
|--------|---------|
| `scan_lau_arb.py` | Scan 272+ QINGs for Purchase→DEX arbitrage |
| `recon_beat.py` | Deep Beat prerequisites check (SHIO balances, contract state) |
| `beat_full_diagnostic.py` | Full Beat call chain diagnosis (step-by-step revert detection) |
| `recon_crows.py` | CROWS holder analysis for bouncer access |
| `recon_player.py` | Scan single player state |
| `recon_players.py` | Scan multiple active players |
| `recon_fornax.py` | Fornax whale mapping |
| `recon_shio.py` | SHIO availability and pricing |
| `recon_void.py` | VOID contract state inspection |
| `recon_zuo.py` | ZUO ownership analysis |
| `recon_zurich.py` | Zurich contract recon |
| `intel_aff_bots.py` | Grav's AFFECTION bot pipeline analysis |

### Deployment Scripts

| Script | Purpose |
|--------|---------|
| `deploy_tgsv8.py` | Deploy TGSv8 execution contract |
| `deploy_tgsv8plus.py` | Deploy TGSv8Plus extended contract |
| `deploy_joystick_hub.py` | Deploy JoystickHub modular proxy |
| `deploy_garbage.py` | Deploy GARBAGE pDAI Printer token (13 LP pairs) |
| `lp_create_pair.py` | Create LP pair on PulseX |
| `lp_deploy.py` | LP deployment orchestration |

### Chat / Social Scripts

| Script | Purpose |
|--------|---------|
| `chat_send.py` | Send VOID chat message |
| `chat_read.py` | Read VOID chat history |
| `chat_scan.py` | Scan VOID for active users |
| `chat_sync.py` | Sync VOID chat to local store |

---

## Relationship to Joystick Bot

Standalone scripts were the **prototyping ground** for Joystick engines:

| Script Origin | → Joystick Engine |
|--------------|-------------------|
| `tx_beat_flow.py` | → E3 `beat.py` |
| `scan_lau_arb.py` + `tx_lau_arb.py` | → E1 `arb.py` |
| `intel_aff_bots.py` | → E4 `token_factory.py` (AFF mode) |
| `deploy_joystick_hub.py` | → E2 `dss.py` (Hub-based harvest) |

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
web3>=6.0.0
python-dotenv>=1.0.0
requests>=2.28.0
```

See `Joystick/requirements.txt` for bot-specific dependencies.

---

## Data Files

| File | Description |
|------|-------------|
| `Joystick/data/recon_results.json` | Full treasury recon (39K lines) |
| `Joystick/data/spine_map.json` | Spine opportunity mapping (860K) |
| `Joystick/data/spinetracker_raw.json` | Raw spine data (944K) |
| `Joystick/data/spine_opportunities.json` | Ranked spine targets (338K) |
| `Joystick/data/token_master.json` | Master token registry (574K) |
| `Joystick/data/pair_registry.json` | Known DEX pair registry (543K) |
| `Joystick/data/branching_parents.json` | Token parent relationships (57K) |
| `Joystick/data/contracts.json` | Runtime address reference |
| `Joystick/data/v2_federal_tokens.json` | V2 Federal token scan |
| `Joystick/data/deploy_candidates.json` | V4 token candidates for E8 DEPLOY |
| `Joystick/data/supply_snapshots.json` | Supply inflation tracking |
| `Joystick/data/phreak_config.json` | E8 PHR3AK configuration |
| `Joystick/data/strategist_state.json` | Persisted strategist state |
| `Joystick/data/arb_routes.json` | Arbitrage route definitions |
| `Joystick/data/pulsex_dual_dex_tokens.json` | Dual-DEX token metadata |
| `Joystick/data/abis/` | Contract ABI files |
| `Joystick/data/events/` | Event log output (JSON-L) |
| `Joystick/data/intel/` | Competitive intelligence (watchlist, AFF minting reports) |

---

## Implementation Notes

- **Never use `pysha3`** — unreliable on many platforms. Use `pycryptodome` (`from Crypto.Hash import keccak`)
- **eth_call simulation before any TX** — always test with eth_call first
- **Atomic file writes** — use `os.rename()` / `os.replace()` for data files
- **No OpenZeppelin imports** in any Solidity — inline guards only
- **Chain ID 369** — always set explicitly in TX signing
- **BlockScout API** — `https://api.scan.pulsechain.com/api` returns decoded function names, accessible with standard User-Agent

**Last Updated**: 2026-04-01
