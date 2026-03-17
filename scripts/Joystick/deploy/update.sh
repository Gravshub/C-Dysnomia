#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  |>JOYSTICK<| Update Script
#
#  Run this after pushing new code to GitHub:
#    sudo bash /opt/joystick/repo/scripts/Joystick/deploy/update.sh
#
#  What it does:
#    1. Pulls latest code from GitHub
#    2. Installs any new Python dependencies
#    3. Restarts the bot and API services
#    4. Shows you the status
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail

GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

INSTALL_DIR="/opt/joystick"
REPO_DIR="${INSTALL_DIR}/repo"
VENV_DIR="${INSTALL_DIR}/venv"
BOT_USER="joystick"

echo ""
echo -e "${CYAN}|>JOYSTICK<| Updating...${NC}"
echo ""

# Pull latest code
echo "Pulling latest code..."
cd "${REPO_DIR}"
sudo -u "${BOT_USER}" git pull origin claude/joystick-V2-FanxJ
echo ""

# Update Python deps if requirements changed
DASHBOARD_REQS="${REPO_DIR}/scripts/Joystick/dashboard/requirements.txt"
if [[ -f "$DASHBOARD_REQS" ]]; then
    echo "Checking Python dependencies..."
    "${VENV_DIR}/bin/pip" install -q -r "$DASHBOARD_REQS" 2>/dev/null
fi

# Reinstall core deps (in case new ones were added)
"${VENV_DIR}/bin/pip" install -q web3 eth-abi pycryptodome requests 2>/dev/null

# Restart services
echo "Restarting services..."
systemctl restart joystick-bot 2>/dev/null && echo -e "  ${GREEN}✓${NC} joystick-bot restarted" || echo "  ! joystick-bot not running"
systemctl restart joystick-api 2>/dev/null && echo -e "  ${GREEN}✓${NC} joystick-api restarted" || echo "  ! joystick-api not running"

echo ""

# Show status
echo "Current status:"
systemctl status joystick-bot --no-pager -l 2>/dev/null | head -5 || true
echo ""

echo -e "${GREEN}Update complete.${NC} Watch logs with: journalctl -u joystick-bot -f"
echo ""
