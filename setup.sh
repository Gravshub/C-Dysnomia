#!/bin/bash
# setup.sh — one-shot local setup for Dysnomia / atropa_pulsechain client
# Connects to live PulseChain (chain 369). Run once after cloning.
set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "[setup] Repo root: $REPO"

# ── 1. .NET 10 ──────────────────────────────────────────────────────────────
if ! command -v dotnet &>/dev/null; then
    echo "[setup] Installing .NET 10 SDK..."
    wget -q https://dot.net/v1/dotnet-install.sh -O /tmp/dotnet-install.sh
    bash /tmp/dotnet-install.sh --channel 10.0
    export PATH="$HOME/.dotnet:$PATH"
    echo "export PATH=\"\$HOME/.dotnet:\$PATH\"" >> ~/.bashrc
else
    echo "[setup] .NET $(dotnet --version) already installed"
fi

# ── 2. solc 0.8.21 ──────────────────────────────────────────────────────────
if ! command -v solc &>/dev/null; then
    echo "[setup] Installing solc 0.8.21 via solc-select..."
    pip3 install -q solc-select
    solc-select install 0.8.21
    solc-select use 0.8.21
else
    echo "[setup] solc $(solc --version | head -1) already installed"
fi

# ── 3. Compile Solidity → ABI artifacts ──────────────────────────────────────
echo "[setup] Compiling Solidity contracts..."
cd "$REPO/solidity"
bash compile_linux.sh
cd "$REPO"

# ── 4. .env check ────────────────────────────────────────────────────────────
if [ ! -f "$REPO/.env" ]; then
    echo ""
    echo "[setup] ERROR: .env file not found."
    echo "  Create $REPO/.env with:"
    echo "    DYSNOMIA_PRIVATE_KEY=0x<your_private_key>"
    echo "    DYSNOMIA_WALLET_ADDRESS=0x<your_address>"
    echo "    DYSNOMIA_RPC=https://rpc.pulsechain.com"
    exit 1
fi

# ── 5. Build ─────────────────────────────────────────────────────────────────
echo "[setup] Building C# project..."
export PATH="$HOME/.dotnet:$PATH"
dotnet build "$REPO/linux/linux.csproj" -c Release

echo ""
echo "[setup] Done. To run:"
echo "  source $REPO/.env && export DYSNOMIA_PRIVATE_KEY DYSNOMIA_RPC"
echo "  dotnet run --project $REPO/linux/linux.csproj"
echo ""
echo "  Wallet: $(grep DYSNOMIA_WALLET_ADDRESS $REPO/.env | cut -d= -f2)"
echo "  Fund this address with PLS (gas) before entering the Void."
