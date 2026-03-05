#!/usr/bin/env bash
# merge-session.sh — pull latest Claude session into canonical branch
# Usage: ./merge-session.sh <sessionID>
# Example: ./merge-session.sh Ab3Xq
set -euo pipefail
CANONICAL="claude/Joystick-Engines-Lj9Kp"
PREFIX="claude/Joystick-Engines-"
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <sessionID>"
    echo "Available: git fetch origin && git branch -r | grep Joystick-Engines | sort"
    exit 1
fi
SESSION_BRANCH="${PREFIX}$1"
git fetch origin
git checkout "$CANONICAL" 2>/dev/null || git checkout -b "$CANONICAL" "origin/$CANONICAL"
git merge "origin/$SESSION_BRANCH" --no-edit -m "Merge session $1 into canonical"
git push origin "$CANONICAL"
echo "✓ Done. $CANONICAL now includes session $1"
