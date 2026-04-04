#!/usr/bin/env bash
# run_ammo_chain_tests.sh — Start Anvil fork + run V2 Ammo Chain tests.
#
# Usage:
#   ./scripts/Joystick/tests/run_ammo_chain_tests.sh          # run all
#   ./scripts/Joystick/tests/run_ammo_chain_tests.sh Phase1    # run Phase 1 only
#   ./scripts/Joystick/tests/run_ammo_chain_tests.sh Phase4 -s # show output

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$REPO_ROOT"

ANVIL_PORT=8545
ANVIL_URL="http://127.0.0.1:${ANVIL_PORT}"
FORK_URL="${PULSECHAIN_READ_RPC:-https://rpc-pulsechain.g4mm4.io}"
export PATH="$HOME/.foundry/bin:$PATH"

# ── Check Anvil ───────────────────────────────────────────────────────────
if ! command -v anvil &>/dev/null; then
    echo "ERROR: Anvil not found. Install Foundry:"
    echo "  curl -L https://foundry.paradigm.xyz | bash && foundryup"
    exit 1
fi

# ── Check if Anvil is already running ────────────────────────────────────
STARTED_ANVIL=false
if curl -s "$ANVIL_URL" -X POST -H "Content-Type: application/json" \
   -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' 2>/dev/null \
   | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if int(d.get('result','0'),16)==369 else 1)" 2>/dev/null; then
    echo "Anvil already running on port $ANVIL_PORT"
else
    echo "Starting Anvil fork of PulseChain..."
    anvil --fork-url "$FORK_URL" --chain-id 369 --auto-impersonate \
          --port "$ANVIL_PORT" --silent &
    ANVIL_PID=$!
    STARTED_ANVIL=true
    trap "kill $ANVIL_PID 2>/dev/null || true" EXIT

    # Wait for Anvil to be ready
    for i in $(seq 1 30); do
        if curl -s "$ANVIL_URL" -X POST -H "Content-Type: application/json" \
           -d '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}' \
           | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if int(d.get('result','0'),16)==369 else 1)" 2>/dev/null; then
            echo "Anvil ready (PID $ANVIL_PID)"
            break
        fi
        sleep 1
    done
fi

# ── Run Tests ────────────────────────────────────────────────────────────
PHASE="${1:-}"
shift || true
EXTRA_ARGS="${*:-}"

if [ -n "$PHASE" ]; then
    echo "Running: TestPhase${PHASE}*"
    python -m pytest scripts/Joystick/tests/test_v2_ammo_chain.py \
        -k "Phase${PHASE}" -v --tb=short $EXTRA_ARGS
else
    echo "Running all V2 Ammo Chain tests..."
    python -m pytest scripts/Joystick/tests/test_v2_ammo_chain.py \
        -v --tb=short -x $EXTRA_ARGS
fi

echo "Done."
