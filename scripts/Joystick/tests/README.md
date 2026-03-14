# Joystick Anvil Fork Tests

## Overview

Comprehensive test suite that forks PulseChain mainnet via Anvil and tests all 8 Joystick engines under favorable conditions.

## Prerequisites

```bash
# Install Foundry (includes Anvil)
curl -L https://foundry.paradigm.xyz | bash
foundryup

# Python deps
pip install web3 pytest python-dotenv requests eth-abi
```

## Running Tests

### Terminal 1: Start Anvil
```bash
anvil --fork-url https://rpc-pulsechain.g4mm4.io \
      --chain-id 369 \
      --auto-impersonate
```

### Terminal 2: Run Tests
```bash
cd C-Dysnomia

# All tests
python -m pytest scripts/Joystick/tests/test_anvil_full.py -v

# Stop on first failure
python -m pytest scripts/Joystick/tests/test_anvil_full.py -v -x

# Specific test class
python -m pytest scripts/Joystick/tests/test_anvil_full.py::TestE4TokenFactory -v

# With logging
python -m pytest scripts/Joystick/tests/test_anvil_full.py -v --log-cli-level=INFO
```

## Test Structure

| Class | Engine | What It Tests |
|---|---|---|
| `TestAnvilSetup` | — | Fork health, chain ID, Joey funding |
| `TestE2Cereal` | E2 DSS | GIBS price above break-even |
| `TestE4TokenFactory` | E4 | multiGenerate simulation, mintWM via RHO() |
| `TestE7Backbone` | E7 | OZZY Debenture=true, parent chain, DEX pair |
| `TestE8Phreak` | E8 | Config, burn address, JV8A parent, supply |
| `TestSplitSwap` | — | Impact calculation, split logic, Uniswap math |
| `TestCrossEngine` | All | Circuit breaker, instantiation, strategist |
| `TestMainnetState` | — | Fork state validation (pairs, ownership, data files) |
| `TestProfitability` | — | ROI calculations, strategy economics |

## How Anvil State Manipulation Works

Anvil provides special RPC methods (see `anvil_helpers.py`):
- `anvil_setBalance` — Fund any address with PLS
- `anvil_impersonateAccount` — Send TXs as any address without private key
- `anvil_setStorageAt` — Write arbitrary storage slots (skew reserves)
- `evm_snapshot` / `evm_revert` — Test isolation (used automatically per-test)

## Files

```
tests/
  conftest.py          — Fixtures: Anvil check, env setup, wallet patching, isolation
  anvil_helpers.py     — Anvil RPC utilities: balance, impersonate, storage, reserves
  test_anvil_full.py   — Main test suite: 8 engines + cross-engine + profitability
  README.md            — This file
```
