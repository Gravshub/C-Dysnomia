#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# fix_imports.sh — Fix relative import error on VPS
#
# The problem: bot.py uses relative imports (from .core.config)
# but the deploy scripts ran it as `python bot.py` (standalone).
# Python needs `python -m scripts.Joystick.bot` (module mode)
# so it knows the package tree.
#
# Run as root on the VPS:
#   bash fix_imports.sh
# ═══════════════════════════════════════════════════════════════

set -e
REPO="/opt/joystick/repo"

echo "╔══════════════════════════════════════════╗"
echo "║  |>JOYSTICK<| Import Fix                 ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. Create missing scripts/__init__.py ─────────────────────
INIT="$REPO/scripts/__init__.py"
if [ ! -f "$INIT" ]; then
    echo '# Package marker — required for python -m scripts.Joystick.bot' > "$INIT"
    chown joystick:joystick "$INIT"
    echo "✓ Created $INIT"
else
    echo "• $INIT already exists"
fi

# ── 2. Fix joystick-bot.service ───────────────────────────────
SVC="/etc/systemd/system/joystick-bot.service"
if [ -f "$SVC" ]; then
    # Fix WorkingDirectory
    sed -i 's|WorkingDirectory=/opt/joystick/repo/scripts/Joystick|WorkingDirectory=/opt/joystick/repo|' "$SVC"
    # Fix ExecStart — replace `python -u bot.py` with `python -u -m scripts.Joystick.bot`
    sed -i 's|python -u bot\.py|python -u -m scripts.Joystick.bot|' "$SVC"
    echo "✓ Fixed $SVC"
    systemctl daemon-reload
    echo "✓ Reloaded systemd"
else
    echo "• $SVC not found (service not installed yet — that's OK)"
fi

# ── 3. Verify the fix ────────────────────────────────────────
echo ""
echo "Testing import chain..."
cd "$REPO"
sudo -u joystick /opt/joystick/venv/bin/python -c "
from scripts.Joystick.core.config import JOEY_WALLET
print(f'✓ Import OK — JOEY_WALLET = {JOEY_WALLET}')
" 2>&1 || echo "✗ Import still failing — check output above"

echo ""
echo "═══════════════════════════════════════════"
echo "Now run the dry-run:"
echo ""
echo "  cd /opt/joystick/repo"
echo "  sudo -u joystick bash -c '"
echo "    set -a && source /opt/joystick/.env.pulse && set +a"
echo "    /opt/joystick/venv/bin/python -m scripts.Joystick.bot --dry-run"
echo "  '"
echo "═══════════════════════════════════════════"
