#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  |>JOYSTICK<| Health Check
#
#  Run anytime to see if everything is working:
#    bash /opt/joystick/repo/scripts/Joystick/deploy/health_check.sh
#
#  Checks: services, RPC, wallet balance, gas, disk space, memory
# ═══════════════════════════════════════════════════════════════════════

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }

echo ""
echo "═══════════════════════════════════════════════"
echo "  |>JOYSTICK<| Health Check"
echo "═══════════════════════════════════════════════"
echo ""

# ─── Service status ──────────────────────────────────────────────────
echo -e "${CYAN}Services:${NC}"

for svc in joystick-bot joystick-api; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        UPTIME=$(systemctl show "$svc" --property=ActiveEnterTimestamp --value 2>/dev/null)
        pass "$svc is running (since $UPTIME)"
    elif systemctl is-enabled --quiet "$svc" 2>/dev/null; then
        warn "$svc is enabled but not running"
    else
        fail "$svc is not installed or not enabled"
    fi
done

echo ""

# ─── Environment file ────────────────────────────────────────────────
echo -e "${CYAN}Configuration:${NC}"

ENV_FILE="/opt/joystick/.env.pulse"
if [[ -f "$ENV_FILE" ]]; then
    # Check if private key has been set (not still the placeholder)
    if grep -q "YOUR_PRIVATE_KEY_HERE" "$ENV_FILE" 2>/dev/null; then
        fail ".env.pulse exists but private key is still the placeholder!"
    else
        pass ".env.pulse configured"
    fi

    # Check permissions
    PERMS=$(stat -c %a "$ENV_FILE" 2>/dev/null)
    if [[ "$PERMS" == "600" ]]; then
        pass ".env.pulse permissions correct (600 — owner only)"
    else
        warn ".env.pulse permissions are $PERMS (should be 600)"
        warn "Fix with: sudo chmod 600 $ENV_FILE"
    fi
else
    fail ".env.pulse not found! Run the setup script first."
fi

echo ""

# ─── RPC connectivity ────────────────────────────────────────────────
echo -e "${CYAN}PulseChain RPC:${NC}"

# Load env for Python check
if [[ -f "$ENV_FILE" ]]; then
    set -a && source "$ENV_FILE" && set +a 2>/dev/null
fi

VENV_PY="/opt/joystick/venv/bin/python"

if [[ -x "$VENV_PY" ]]; then
    CHAIN_CHECK=$("$VENV_PY" -c "
import sys
try:
    from web3 import Web3
    w = Web3(Web3.HTTPProvider('https://rpc-pulsechain.g4mm4.io', request_kwargs={'timeout': 10}))
    block = w.eth.block_number
    gas_i = w.eth.gas_price
    gas_b = gas_i / 1e9

    # Joey wallet balance
    bal = w.eth.get_balance(Web3.to_checksum_address('0x17367877aF5A8D0Eb33ba5689A880f696386E24D'))
    pls = bal / 1e18

    print(f'BLOCK:{block}')
    print(f'GAS:{gas_b:.1f}')
    print(f'PLS:{pls:.2f}')
    print(f'BUFFER:{'OK' if pls >= 100000 else 'LOW'}')
except Exception as e:
    print(f'ERROR:{e}', file=sys.stderr)
    sys.exit(1)
" 2>&1)

    if echo "$CHAIN_CHECK" | grep -q "^BLOCK:"; then
        BLOCK=$(echo "$CHAIN_CHECK" | grep "^BLOCK:" | cut -d: -f2)
        GAS=$(echo "$CHAIN_CHECK" | grep "^GAS:" | cut -d: -f2)
        PLS=$(echo "$CHAIN_CHECK" | grep "^PLS:" | cut -d: -f2)
        BUFFER=$(echo "$CHAIN_CHECK" | grep "^BUFFER:" | cut -d: -f2)

        pass "RPC connected — block $(printf "%'d" "$BLOCK")"
        pass "Gas price: ${GAS} Beats"

        # Matches GAS_PRICE_CEIL default in core/config.py (2_000_000 Beats).
        # Override with GAS_CEILING_BEATS in the environment if the bot is
        # running with a different ceiling.
        GAS_CEIL_BEATS="${GAS_CEILING_BEATS:-2000000}"
        if (( $(echo "$GAS > $GAS_CEIL_BEATS" | bc -l 2>/dev/null || echo 0) )); then
            warn "Gas above ceiling (${GAS_CEIL_BEATS} Beats) — bot would SKIP"
        fi

        pass "Joey PLS balance: $(printf "%'.2f" "$PLS")"

        if [[ "$BUFFER" == "LOW" ]]; then
            fail "PLS below 100K gas buffer floor!"
        else
            pass "Gas buffer OK (above 100K floor)"
        fi
    else
        fail "RPC connection failed: $CHAIN_CHECK"
    fi
else
    fail "Python venv not found at $VENV_PY"
fi

echo ""

# ─── System resources ────────────────────────────────────────────────
echo -e "${CYAN}System resources:${NC}"

# Disk space
DISK_USED=$(df /opt/joystick 2>/dev/null | awk 'NR==2 {print $5}' | tr -d '%')
if [[ -n "$DISK_USED" ]] && [[ "$DISK_USED" -lt 85 ]]; then
    pass "Disk usage: ${DISK_USED}%"
elif [[ -n "$DISK_USED" ]]; then
    warn "Disk usage: ${DISK_USED}% (getting full!)"
else
    warn "Could not check disk usage"
fi

# Memory
MEM_AVAIL=$(free -m 2>/dev/null | awk '/Mem:/ {print $7}')
if [[ -n "$MEM_AVAIL" ]] && [[ "$MEM_AVAIL" -gt 100 ]]; then
    pass "Available memory: ${MEM_AVAIL}MB"
else
    warn "Low memory: ${MEM_AVAIL}MB available"
fi

# Uptime
UPTIME=$(uptime -p 2>/dev/null || uptime)
pass "VPS uptime: $UPTIME"

echo ""

# ─── Recent bot activity ─────────────────────────────────────────────
echo -e "${CYAN}Recent bot logs (last 5 lines):${NC}"

if systemctl is-active --quiet joystick-bot 2>/dev/null; then
    journalctl -u joystick-bot --no-pager -n 5 --output=short 2>/dev/null || echo "  (no logs yet)"
else
    echo "  (bot is not running)"
fi

echo ""
echo "═══════════════════════════════════════════════"
echo ""
