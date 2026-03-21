---
name: engine-check
description: "Check status, readiness, and blockers for all 8 Joystick engines or a specific engine. Read-only."
argument-hint: "[engine: E1|E2|E3|E4|E5|E6|E7|E8|all]"
user-invocable: true
disable-model-invocation: true
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
---

# /engine-check — Joystick Engine Status Report

Check readiness, prerequisites, and blockers for Joystick's 8 PLS generation engines. Read-only — no transactions.

## Context Files — Read First

- `/opt/joystick/repo/scripts/Joystick/CLAUDE.md` — engine descriptions, wallet roles, architecture
- `/opt/joystick/repo/scripts/Joystick/engines/base.py` — EngineBase, display names, wallet mapping
- `/opt/joystick/repo/scripts/Joystick/core/config.py` — addresses, thresholds, env vars

## Arguments

`$ARGUMENTS` accepts:
- `E1` / `RAZOR` / `arb` — E1 RAZOR (cross-DEX arbitrage)
- `E2` / `CEREAL` / `dss` — E2 CEREAL (GIBS harvest via TGSv8+)
- `E3` / `MERIDIAN` / `beat` — E3 MERIDIAN (territory positioning)
- `E4` / `FACTORY` / `token_factory` — E4 Token Factory (AFF + WM minting)
- `E5` / `ABUPRU` / `lau` — E5 ABUPRU (math state loop)
- `E6` / `DaVINCI` / `treasury_sniper` — E6 DaVINCI (treasury sniping)
- `E7` / `BACKBONE` / `spine_runner` — E7 BACKBONE (spine running)
- `E8` / `PHR3AK` / `phreak` — E8 PHR3AK (web weaver)
- `all` or empty — check all 8 engines

## Per-Engine Checks

For each engine, read its source file FIRST, then check on-chain prerequisites via Python RPC calls.

### E1 RAZOR (`engines/arb.py`)
- **Wallet**: Seller
- **Check**: `data/pair_registry.json` exists, GIBS pairs have non-zero reserves
- **Check**: TGSv8 `atomicArb()` is callable (eth_call simulation)
- **Context**: Currently net-negative per recon

### E2 CEREAL (`engines/dss.py`)
- **Wallet**: Joey
- **Check**: TGSv8+ deployed and authorized
- **Check**: GIBS_LAU self-balance (can tokens be harvested?)
- **Check**: GIBS/WPLS or GIBS/FED pair has reserves for the sell step
- **Profitability**: 17 GIBS sell value vs gas cost at current prices

### E3 MERIDIAN (`engines/beat.py`)
- **Wallet**: Joey
- **Check**: SHIO balances (Fornax `0x9a7b0c0f`, Fomalhaute `0xf615e036`, CHO `0xB6be11F0`) at GIBS_LAU and GIBS_QING > 0
- **Check**: RING.Moments[Soul] != 0 (needs CHEON.Su if zero)
- **Report**: Current Dione value from META.Beat simulation

### E4 FACTORY (`engines/token_factory.py`)
- **Wallet**: Minter
- **Check**: WM balance at TGSv8
- **Check**: AFF BuyWith route profitability (compare AFF DEX price vs mint cost)
- **Context**: All routes currently unprofitable (AFF needs to be >118 PLS)

### E5 ABUPRU (`engines/lau.py`)
- **Wallet**: Joey
- **Check**: PLS balance > 150K floor (gated below this)
- **Check**: LAU state readiness for ABUPRU loop

### E6 DaVINCI (`engines/treasury_sniper.py`)
- **Wallet**: Minter
- **Check**: `data/recon_results.json` exists with targets
- **Check**: Any tokens with selfBalance > 0 that are cheaply acquirable

### E7 BACKBONE (`engines/spine_runner.py`)
- **Wallet**: Minter
- **Check**: V2 Federal tokens with Debenture=true (currently only OZZY)
- **Context**: Blocked — needs OZZY spine via E8

### E8 PHR3AK (`engines/phreak.py`)
- **Wallet**: Minter
- **Check**: TGSv8 `createV4` readiness, WM balance for deployment
- **Check**: V3 family targets (MXDAI at 118 PLS/tok, S&500 at 44K PLS/tok)

## RPC Details

- Use `https://rpc-pulsechain.g4mm4.io` for all reads
- Use Multicall3 (`0xcA11bde05977b3631167028862bE2a173976CA11`) for batching
- `balanceOf` selector: `0x70a08231`
- `getReserves` selector: `0x0902f1ac`
- NEVER send transactions

## Output Format

```
========================================
  JOYSTICK ENGINE STATUS — Block NNNNNN
========================================

E1 RAZOR      [READY|BLOCKED|DEGRADED]  — one-line reason
E2 CEREAL     [READY|BLOCKED|DEGRADED]  — one-line reason
E3 MERIDIAN   [READY|BLOCKED|DEGRADED]  — one-line reason
E4 FACTORY    [READY|BLOCKED|DEGRADED]  — one-line reason
E5 ABUPRU     [READY|BLOCKED|DEGRADED]  — one-line reason
E6 DaVINCI    [READY|BLOCKED|DEGRADED]  — one-line reason
E7 BACKBONE   [READY|BLOCKED|DEGRADED]  — one-line reason
E8 PHR3AK     [READY|BLOCKED|DEGRADED]  — one-line reason

─── Detailed Report ───

## E2 CEREAL (GIBS Harvest)
Status:    READY
Wallet:    Joey
Revenue:   ~X,XXX PLS/cycle (17 GIBS @ NNN PLS/GIBS, NNN PLS gas)
Blockers:  None
Notes:     ...
```
