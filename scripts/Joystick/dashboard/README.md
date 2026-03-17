# |>JOYSTICK<| Mission Control

> *"Hack the planet."*

Real-time dashboard for the JOYSTICK arbitrage bot on PulseChain (369).

## Architecture

```
┌─────────────────────────────────────────┐
│  Frontend (React / HTML)                │  ← Layer 2 (future)
│  Polls /api/overview every 15s          │
└──────────────┬──────────────────────────┘
               │ HTTP GET
┌──────────────▼──────────────────────────┐
│  FastAPI Server (this package)          │  ← Layer 1 (this)
│  Read-only API, ~4 RPC calls per poll   │
└──────────────┬──────────────────────────┘
               │ Multicall3 batch + eth_*
┌──────────────▼──────────────────────────┐
│  PulseChain (Chain 369)                 │
│  g4mm4.io reads / pulsechain.com txs    │
└─────────────────────────────────────────┘
               │ (optional) file read
┌──────────────▼──────────────────────────┐
│  Bot Process (scripts/Joystick/bot.py)  │
│  Writes engine_state.json, tx_log.json  │
└─────────────────────────────────────────┘
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | RPC connectivity check + block number |
| GET | `/api/overview` | **Single-call dashboard payload** (wallet + engines + gas + strategy + txs) |
| GET | `/api/wallet` | Joey's balances, validator progress, gas buffer |
| GET | `/api/engines` | All 8 engine statuses, ROI, earnings |
| GET | `/api/gas` | Gas price (Beats), ceiling, condition |

## Quick Start

```bash
# From the repo root:
cd dashboard
pip install -r requirements.txt

# Run the API server (port 8369 — for chain 369)
python -m api.server

# Or with uvicorn directly:
uvicorn api.server:app --host 0.0.0.0 --port 8369 --reload
```

Then visit: `http://localhost:8369/docs` for the interactive API docs.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RPC_URL_READ` | `https://rpc-pulsechain.g4mm4.io` | Read RPC (Multicall3 batches) |
| `RPC_URL` | `https://rpc.pulsechain.com` | Fallback RPC |
| `API_PORT` | `8369` | Server port |
| `API_HOST` | `0.0.0.0` | Bind address |
| `CORS_ORIGINS` | `http://localhost:3000,...` | Comma-separated allowed origins |
| `GAS_CEILING_BEATS` | `50` | Gas price ceiling for condition calc |
| `BOT_DATA_DIR` | *(empty)* | Path to bot's data/ directory for state files |

## Data Flow

The API is **read-only** and makes ~4 RPC round-trips per `/api/overview` call:

1. `eth_blockNumber` — current block
2. `eth_gasPrice` — gas in Impulses (÷ 10^9 → Beats)
3. `eth_getBalance` × 2 — Joey wallet + TGSv8 contract
4. **Multicall3.aggregate3** — all ERC20 balanceOf calls in one batch

If `BOT_DATA_DIR` is set and the bot writes `engine_state.json` / `tx_log.json`,
the API reads those files for engine runtime state and TX history.
Without the bot running, it falls back to known static states from the diary entries.

## Roadmap

- [ ] **Layer 2: Frontend** — React or plain HTML dashboard (see mockup in chat)
- [ ] **PLS/USD price feed** — CoinGecko or DEX oracle for USD values
- [ ] **GIBS price oracle** — read GIBS/WPLS pair reserves for PLS value
- [ ] **TX history from chain** — scan BlockScout API for Joey wallet TXs
- [ ] **WebSocket push** — replace polling with server-push for real-time updates
- [ ] **Token gate** — Vercel deployment with GIBSON-token-gated access
- [ ] **Engine controls** — Layer 3: start/stop toggles, strategy override (write API)

## Token Gate Vision (Vercel)

Future: deploy frontend to Vercel, gate access behind a GIBSON (GIBS) token check.
Hold GIBS → access the dashboard. Ecosystem value loop:
GIBS demand ↑ → LP fees ↑ → Joey's income ↑ → dashboard shows more green.

---

*|>JOYSTICK<| — the machine is deployed. now it earns.*
