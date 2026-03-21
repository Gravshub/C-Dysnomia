---
name: deploy-test
description: "Run the Joystick test suite on an Anvil PulseChain fork. Validates engines, contracts, and data integrity."
argument-hint: "[test: all|anvil|data|engines|tgsv8|<file.py>]"
user-invocable: true
disable-model-invocation: true
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
---

# /deploy-test — Run Tests on Anvil Fork

Run the Joystick test suite against an Anvil fork of PulseChain. Validates contracts, engines, and data integrity.

## Context Files — Read First

- `/opt/joystick/repo/scripts/Joystick/tests/` — test files
- `/opt/joystick/repo/scripts/Joystick/deploy/DEPLOY_GUIDE.md` — deployment context

## Arguments

`$ARGUMENTS` can be:
- `all` or empty — Run full test suite
- `anvil` — Anvil fork integration tests (`test_anvil_full.py`)
- `data` — Data store tests (`test_data_store.py`)
- `engines` — Engine simulation tests (`test_engines_5_6.py`)
- `tgsv8` — TGSv8+ tests (`test_tgsv8plus.py`)
- `razor` — RAZOR PulseChain tests (`test_razor_pulsechain.py`)
- A specific filename — Run that test file directly

## Prerequisites Check

Before running tests, verify:
1. `which anvil` — Anvil (Foundry) installed
2. `python3 -c "import web3, eth_abi, dotenv"` — Python dependencies
3. Check for `.env` or `.env.pulse` at `/opt/joystick/repo/`

## Anvil Fork Setup

For integration tests, start an Anvil fork:

```bash
anvil --fork-url https://rpc-pulsechain.g4mm4.io \
      --chain-id 369 \
      --auto-impersonate \
      --port 8545 \
      --silent &
ANVIL_PID=$!
```

Wait for readiness:
```bash
for i in $(seq 1 10); do
  curl -s -X POST http://127.0.0.1:8545 \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"eth_blockNumber","id":1}' && break
  sleep 1
done
```

## Running Tests

```bash
cd /opt/joystick/repo
python3 -m pytest scripts/Joystick/tests/$TEST_FILE -v --tb=short 2>&1
```

Key env vars (set by conftest.py — do not override):
- `PULSECHAIN_RPC=http://127.0.0.1:8545`
- `PULSECHAIN_READ_RPC=http://127.0.0.1:8545`
- `TGSV8_ADDRESS=0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32`

## Cleanup

Always kill Anvil when done:
```bash
kill $ANVIL_PID 2>/dev/null
```

## Output Format

```
========================================
  JOYSTICK TEST RESULTS
========================================
Anvil fork: Block NNNNNN (PulseChain 369)

PASSED:  NN
FAILED:  NN
SKIPPED: NN

─── Failures ───
test_xxx.py::test_name — Error: ...
  Root cause: ...
  Suggested fix: ...
```
