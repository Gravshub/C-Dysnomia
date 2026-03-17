#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  |>JOYSTICK<| VPS Deployment Script
#
#  What this script does (in order):
#    1. Creates a dedicated "joystick" user (security — never run bots as root)
#    2. Creates the directory structure under /opt/joystick/
#    3. Clones the repo from GitHub
#    4. Sets up a Python virtual environment with all dependencies
#    5. Copies the env template for you to fill in
#    6. Installs the systemd service files
#    7. Sets correct file permissions
#
#  What this script does NOT do:
#    - Put your private key anywhere. YOU do that manually (step shown at end)
#    - Start the bot. You start it after verifying the config.
#
#  Run as root on your VPS:
#    curl -O https://raw.githubusercontent.com/Gravshub/C-Dysnomia/claude/joystick-V2-FanxJ/scripts/Joystick/deploy/setup_vps.sh
#    chmod +x setup_vps.sh
#    sudo bash setup_vps.sh
#
#  Or if you already have the repo cloned:
#    sudo bash scripts/Joystick/deploy/setup_vps.sh
# ═══════════════════════════════════════════════════════════════════════

set -euo pipefail
# set -e = exit immediately if any command fails
# set -u = treat unset variables as errors
# set -o pipefail = catch errors in piped commands

# ─── Colors for output (makes it easier to read) ────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ─── Pre-flight checks ──────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  |>JOYSTICK<| VPS Deployment"
echo "  \"Hack the planet.\""
echo "═══════════════════════════════════════════════════"
echo ""

# Must be root
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root. Try: sudo bash $0"
fi

# Check for required tools
for cmd in git python3 pip3; do
    if ! command -v $cmd &> /dev/null; then
        info "Installing $cmd..."
        apt-get update -qq && apt-get install -y -qq $cmd
    fi
done

# Ensure python3-venv is available (some VPS images strip it)
apt-get install -y -qq python3-venv python3-dev build-essential 2>/dev/null || true

# ─── Configuration ───────────────────────────────────────────────────
INSTALL_DIR="/opt/joystick"
REPO_URL="https://github.com/Gravshub/C-Dysnomia.git"
REPO_BRANCH="claude/joystick-V2-FanxJ"
BOT_USER="joystick"

info "Install directory: ${INSTALL_DIR}"
info "Repository: ${REPO_URL}"
info "Branch: ${REPO_BRANCH}"
echo ""

# ─── Step 1: Create the joystick user ───────────────────────────────
# Why: Running the bot as root is dangerous. If the bot has a bug,
# root access means it could damage the entire system. A dedicated
# user can only touch its own files.
info "Step 1/7: Creating '${BOT_USER}' user..."

if id "$BOT_USER" &>/dev/null; then
    ok "User '${BOT_USER}' already exists"
else
    # --system = system user (no home directory bloat)
    # --shell /usr/sbin/nologin = can't SSH in as this user (security)
    # --group = create a matching group
    useradd --system --shell /usr/sbin/nologin --create-home \
            --home-dir "${INSTALL_DIR}" --group "${BOT_USER}"
    ok "User '${BOT_USER}' created"
fi

# ─── Step 2: Create directory structure ──────────────────────────────
info "Step 2/7: Creating directories..."

mkdir -p "${INSTALL_DIR}"/{repo,data,logs}

# data/ = where the bot writes engine_state.json, tx_log.json
# logs/ = where log files go
# repo/ = the git clone lives here

ok "Directories created: ${INSTALL_DIR}/{repo,data,logs}"

# ─── Step 3: Clone or update the repository ─────────────────────────
info "Step 3/7: Setting up repository..."

if [[ -d "${INSTALL_DIR}/repo/.git" ]]; then
    info "Repo exists — pulling latest..."
    cd "${INSTALL_DIR}/repo"
    # Run git as the joystick user
    sudo -u "${BOT_USER}" git fetch origin
    sudo -u "${BOT_USER}" git checkout "${REPO_BRANCH}"
    sudo -u "${BOT_USER}" git pull origin "${REPO_BRANCH}"
    ok "Repo updated to latest"
else
    info "Cloning repository (this may take a minute)..."
    cd "${INSTALL_DIR}"
    git clone --branch "${REPO_BRANCH}" "${REPO_URL}" repo
    ok "Repo cloned"
fi

# ─── Step 4: Python virtual environment ──────────────────────────────
# Why a venv? It keeps the bot's Python packages separate from the
# system Python. If you install something for the bot, it won't break
# other things on the VPS. And vice versa.
info "Step 4/7: Setting up Python virtual environment..."

VENV_DIR="${INSTALL_DIR}/venv"

if [[ -d "${VENV_DIR}" ]]; then
    ok "Virtual environment already exists"
else
    python3 -m venv "${VENV_DIR}"
    ok "Virtual environment created at ${VENV_DIR}"
fi

# Upgrade pip first (old pip can fail on some packages)
"${VENV_DIR}/bin/pip" install --upgrade pip -q

# Install bot dependencies
info "Installing Python dependencies..."
"${VENV_DIR}/bin/pip" install -q \
    web3 \
    eth-abi \
    pycryptodome \
    requests \
    python-dotenv

# Install dashboard dependencies (if the dashboard directory exists)
DASHBOARD_DIR="${INSTALL_DIR}/repo/scripts/Joystick/dashboard"
if [[ -f "${DASHBOARD_DIR}/requirements.txt" ]]; then
    info "Installing dashboard dependencies..."
    "${VENV_DIR}/bin/pip" install -q -r "${DASHBOARD_DIR}/requirements.txt"
fi

ok "All Python packages installed"

# ─── Step 5: Environment file ────────────────────────────────────────
info "Step 5/7: Setting up environment file..."

ENV_FILE="${INSTALL_DIR}/.env.pulse"
TEMPLATE_FILE="${INSTALL_DIR}/repo/scripts/Joystick/deploy/env.pulse.template"

if [[ -f "${ENV_FILE}" ]]; then
    warn ".env.pulse already exists — NOT overwriting (your key is safe)"
    warn "If you need the fresh template, see: ${TEMPLATE_FILE}"
else
    if [[ -f "${TEMPLATE_FILE}" ]]; then
        cp "${TEMPLATE_FILE}" "${ENV_FILE}"
    else
        # Create a minimal template inline if the file isn't in the repo yet
        cat > "${ENV_FILE}" << 'ENVEOF'
# |>JOYSTICK<| Environment — EDIT THIS FILE
# REQUIRED: Replace YOUR_PRIVATE_KEY_HERE with your actual private key
PRIVATE_KEY=YOUR_PRIVATE_KEY_HERE
CHAIN_ID=369
RPC_URL_READ=https://rpc-pulsechain.g4mm4.io
RPC_URL=https://rpc.pulsechain.com
TGSV8_ADDRESS=0xAD352a27ceaaC5657e3E9127f964F4746A8aAc32
GAS_CEILING_BEATS=50
GAS_BUFFER_FLOOR=100000
BOT_CYCLE_DELAY=30
BOT_DATA_DIR=/opt/joystick/data
LOG_LEVEL=INFO
LOG_FILE=/opt/joystick/logs/joystick.log
ENVEOF
    fi
    # CRITICAL: Only the joystick user can read this file
    # chmod 600 = owner can read/write, nobody else can even see it
    chmod 600 "${ENV_FILE}"
    ok "Environment template created at ${ENV_FILE}"
    warn ">>> YOU MUST EDIT THIS FILE and add your private key <<<"
fi

# ─── Step 6: Install systemd services ───────────────────────────────
info "Step 6/7: Installing systemd services..."

DEPLOY_DIR="${INSTALL_DIR}/repo/scripts/Joystick/deploy"

# Copy service files (or create them inline if deploy dir doesn't exist yet)
for svc in joystick-bot joystick-api; do
    SVC_SRC="${DEPLOY_DIR}/${svc}.service"
    SVC_DST="/etc/systemd/system/${svc}.service"

    if [[ -f "${SVC_SRC}" ]]; then
        cp "${SVC_SRC}" "${SVC_DST}"
        ok "Installed ${svc}.service"
    else
        warn "${SVC_SRC} not found — you'll need to copy it manually later"
    fi
done

# Tell systemd to re-read the service files
systemctl daemon-reload
ok "systemd reloaded"

# Enable services (= start on boot), but don't start yet
systemctl enable joystick-bot 2>/dev/null || true
systemctl enable joystick-api 2>/dev/null || true
ok "Services enabled (will start on boot)"

# ─── Step 7: Fix ownership & permissions ─────────────────────────────
info "Step 7/7: Setting permissions..."

# Everything under /opt/joystick belongs to the joystick user
chown -R "${BOT_USER}:${BOT_USER}" "${INSTALL_DIR}"

# .env.pulse is extra locked down (private key is in there)
chmod 600 "${ENV_FILE}"

# Logs directory needs to be writable
chmod 755 "${INSTALL_DIR}/logs"
chmod 755 "${INSTALL_DIR}/data"

ok "Permissions set"

# ─── Done! ───────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}|>JOYSTICK<| deployment complete!${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Directory:  ${INSTALL_DIR}"
echo "  Repo:       ${INSTALL_DIR}/repo"
echo "  Bot code:   ${INSTALL_DIR}/repo/scripts/Joystick/"
echo "  Env file:   ${INSTALL_DIR}/.env.pulse"
echo "  Data:       ${INSTALL_DIR}/data/"
echo "  Logs:       ${INSTALL_DIR}/logs/"
echo ""
echo "═══════════════════════════════════════════════════"
echo "  NEXT STEPS (do these in order):"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  1. Edit the environment file and add your private key:"
echo ""
echo -e "     ${CYAN}sudo nano /opt/joystick/.env.pulse${NC}"
echo ""
echo "     Replace YOUR_PRIVATE_KEY_HERE with your actual key."
echo "     Press Ctrl+O to save, Ctrl+X to exit nano."
echo ""
echo "  2. Test the connection (without starting the bot):"
echo ""
echo -e "     ${CYAN}sudo -u joystick bash -c 'set -a && source /opt/joystick/.env.pulse && set +a && /opt/joystick/venv/bin/python -c \"from web3 import Web3; w=Web3(Web3.HTTPProvider(\\\"https://rpc-pulsechain.g4mm4.io\\\")); print(f\\\"Block: {w.eth.block_number:,}\\\")\"'${NC}"
echo ""
echo "  3. Dry run the bot (simulates without sending TXs):"
echo ""
echo -e "     ${CYAN}cd /opt/joystick/repo/scripts/Joystick${NC}"
echo -e "     ${CYAN}sudo -u joystick bash -c 'set -a && source /opt/joystick/.env.pulse && set +a && /opt/joystick/venv/bin/python bot.py --dry-run'${NC}"
echo ""
echo "  4. Start the bot service (goes live — real TXs!):"
echo ""
echo -e "     ${CYAN}sudo systemctl start joystick-bot${NC}"
echo ""
echo "  5. Watch the logs:"
echo ""
echo -e "     ${CYAN}journalctl -u joystick-bot -f${NC}"
echo ""
echo "  6. (Optional) Start the dashboard API:"
echo ""
echo -e "     ${CYAN}sudo systemctl start joystick-api${NC}"
echo ""
echo "═══════════════════════════════════════════════════"
echo "  USEFUL COMMANDS:"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Check bot status:       sudo systemctl status joystick-bot"
echo "  Stop the bot:           sudo systemctl stop joystick-bot"
echo "  Restart after update:   sudo systemctl restart joystick-bot"
echo "  View recent logs:       journalctl -u joystick-bot --since '1h ago'"
echo "  Update code from git:   cd /opt/joystick/repo && sudo -u joystick git pull"
echo "                          sudo systemctl restart joystick-bot"
echo ""
echo "═══════════════════════════════════════════════════"
echo -e "  ${GREEN}\"Mess with the best, die like the rest.\"${NC}"
echo "═══════════════════════════════════════════════════"
echo ""
