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
| `TestAnvilSetup` | — | Fork health, chain ID, Joey funding, impersonation, mining |
| `TestE1Razor` | E1 Arb | Instantiation, is_ready, simulate, reserve skewing, cross-DEX spread |
| `TestE2Cereal` | E2 DSS | Pair exists, price above break-even, is_ready, simulate, dry_run |
| `TestE3Meridian` | E3 Beat | SHIO balances, is_ready, simulate, META.Beat simulation, dry_run |
| `TestE4TokenFactory` | E4 | AFF disabled, multiGenerate, mints-to-contract proof, mintWM, dry_run |
| `TestE5LAU` | E5 | PLS gating, Alpha simulation, EmitSniper import, dry_run |
| `TestE6DaVinci` | E6 | Recon file, is_ready, simulate, dry_run |
| `TestE7Backbone` | E7 | OZZY Debenture=true, parent chain, DEX pair, is_ready, dry_run |
| `TestE8Phreak` | E8 | Config, burn address, ARM mode, JV8A parent, missing edges |
| `TestSplitSwap` | — | Impact calculation, multi-pair, split logic, Uniswap math |
| `TestStrategist` | — | ROI ranking, disabled engines, auto-recovery, auto-approve |
| `TestCrossEngine` | All | Instantiation, interface, circuit breaker, gas guard, EngineResult |
| `TestMainnetState` | — | GIBS pairs, TGSv8 owner, nonce, DSS multiplier, recon data |
| `TestProfitability` | — | DSS ROI, OZZY cost, spine lifetime, combinatorial growth |
| `TestInfrastructure` | — | RPC health, multicall, simulator, nonce tracker, gas oracle |

## How Anvil State Manipulation Works

Anvil provides special RPC methods (see `anvil_helpers.py`):
- `anvil_setBalance` — Fund any address with PLS
- `anvil_impersonateAccount` — Send TXs as any address without private key
- `anvil_setStorageAt` — Write arbitrary storage slots (skew reserves)
- `evm_snapshot` / `evm_revert` — Test isolation (used automatically per-test)

## Notes

- Tests skip automatically if Anvil is not running
- Each test gets full state isolation via EVM snapshot/revert
- Engine fixtures use deferred imports to avoid import-time RPC calls
- The wallet is patched with a MagicMock so Joey's address works without his private key
- No existing Joystick source files are modified — tests are purely additive

## Files

```
tests/
  conftest.py              — Fixtures: Anvil check, env setup, wallet patching, isolation
  anvil_helpers.py         — Anvil RPC utilities: balance, impersonate, storage, reserves
  test_anvil_full.py       — Main test suite: 14 classes, ~100+ tests
  test_engines_5_6.py      — Earlier E5/E6 focused tests
  test_razor_pulsechain.py — Earlier E1 Razor tests
  README.md                — This file
```
