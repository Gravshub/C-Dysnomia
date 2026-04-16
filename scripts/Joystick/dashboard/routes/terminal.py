"""
/terminal — WebSocket terminal for live bot output + command input.

Streams JSONL event logs in real-time and accepts commands from the frontend.
Also provides a REST endpoint for initial log load.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status

from .. import config
from ..auth import check_ws_token

router = APIRouter()
logger = logging.getLogger("joystick.routes.terminal")

# ── Paths ────────────────────────────────────────────────────────────
_JOYSTICK_DIR = Path(__file__).parent.parent.parent  # scripts/Joystick
_SCRIPTS_DIR = _JOYSTICK_DIR.parent                  # scripts/
_REPO_DIR = _SCRIPTS_DIR.parent                      # repo root
_EVENTS_DIR = _JOYSTICK_DIR / "data" / "events"
_MAIN_LOG = _EVENTS_DIR / "joystick_events.jsonl"
_TESTS_DIR = _JOYSTICK_DIR / "tests"
_TOOLS_DIR = _JOYSTICK_DIR / "tools"

# Python executable — prefer venv if available
_VENV_PYTHON = _REPO_DIR / ".venv" / "bin" / "python"
_PYTHON = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable

# ── Running background processes ─────────────────────────────────────
_bg_processes: dict[str, subprocess.Popen] = {}

# ── Connected WebSocket clients ──────────────────────────────────────
_clients: set[WebSocket] = set()


async def broadcast(message: dict):
    """Send a message to all connected terminal clients."""
    dead = set()
    for ws in _clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.add(ws)
    _clients -= dead


def _read_tail(path: Path, n: int = 100) -> list[dict]:
    """Read last N lines from a JSONL file."""
    if not path.exists():
        return []
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        tail = lines[-n:] if len(lines) > n else lines
        events = []
        for line in tail:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return events
    except Exception as e:
        logger.error(f"Failed to read {path}: {e}")
        return []


def _format_event(ev: dict) -> str:
    """Format a JSONL event into a human-readable terminal line."""
    from datetime import datetime, timezone, timedelta
    _EST = timezone(timedelta(hours=-5))

    ts = ev.get("ts", "")
    if ts and "T" in ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            ts = dt.astimezone(_EST).strftime("%H:%M:%S")
        except Exception:
            ts = ts.split("T")[1][:8]
    elif ev.get("epoch"):
        try:
            ts = datetime.fromtimestamp(ev["epoch"], tz=_EST).strftime("%H:%M:%S")
        except Exception:
            pass

    event_type = ev.get("event", "unknown")
    engine = ev.get("engine", "")
    success = ev.get("success")
    notes = ev.get("notes", "")
    tx_hash = ev.get("tx_hash", "")
    pls_cost = ev.get("pls_cost")

    # Build prefix
    prefix = f"[{ts}]" if ts else ""
    if engine:
        prefix += f" {engine}:"

    # Build body from event type
    body = event_type
    if notes:
        body = notes
    elif ev.get("data"):
        data = ev["data"]
        # Smart summarization for known event types
        if "profit_pls" in data:
            body = f"{event_type} → {data['profit_pls']:.2f} PLS"
        elif "action_taken" in data:
            body = f"{event_type} → {data['action_taken']}"
        elif "pls" in data:
            body = f"{event_type} — {data['pls']:,.0f} PLS"

    # Status indicator
    status = ""
    if success is True:
        status = " ✓"
    elif success is False:
        status = " ✗"

    # TX hash suffix
    tx_suffix = ""
    if tx_hash:
        tx_suffix = f" [{tx_hash[:10]}...]"

    # Cost suffix
    cost_suffix = ""
    if pls_cost and pls_cost > 0:
        cost_suffix = f" ({pls_cost:.2f} PLS)"

    return f"{prefix} {body}{status}{tx_suffix}{cost_suffix}"


# ── REST: Initial log load ───────────────────────────────────────────

@router.get("/logs")
async def get_logs(
    n: int = Query(100, ge=1, le=500, description="Number of recent log lines"),
    engine: Optional[str] = Query(None, description="Filter by engine name"),
):
    """Return recent log entries for initial terminal population."""
    engine_filter = None
    if engine:
        log_file = _EVENTS_DIR / f"engine_{engine.lower()}.jsonl"
        engine_filter = engine.lower()
    else:
        log_file = _MAIN_LOG

    events = _read_tail(log_file, n)

    # Fallback: if per-engine file is empty/missing, search main log
    if not events and engine_filter:
        all_events = _read_tail(_MAIN_LOG, 500)
        events = [
            ev for ev in all_events
            if ev.get("engine", "").lower() == engine_filter
               or ev.get("engine_ran", "").lower() == engine_filter
        ][-n:]

    lines = []
    for ev in events:
        lines.append({
            "type": "log",
            "text": _format_event(ev),
            "raw": ev,
            "ts": ev.get("epoch", 0),
        })
    return {"lines": lines, "count": len(lines), "source": str(log_file.name)}


# ── WebSocket: Live terminal ────────────────────────────────────────

@router.websocket("/ws/terminal")
async def terminal_ws(ws: WebSocket, token: Optional[str] = Query(default=None)):
    """
    WebSocket terminal.

    Auth: requires ?token=<DASHBOARD_TERMINAL_TOKEN>. Connections without a
    matching token are closed with policy-violation (1008). If the server
    token is unset, ALL connections are closed — the endpoint is effectively
    disabled, which is the safe default for public deploys.

    Server → Client messages:
      {"type": "log",    "text": "...", "ts": epoch}
      {"type": "system", "text": "...", "ts": epoch}
      {"type": "result", "text": "...", "ts": epoch, "success": bool}

    Client → Server messages:
      {"type": "command", "text": "..."}
    """
    if not check_ws_token(token):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("Terminal WS rejected (invalid/missing token)")
        return

    await ws.accept()
    _clients.add(ws)
    logger.info(f"Terminal client connected ({len(_clients)} total)")

    # Send welcome
    await ws.send_json({
        "type": "system",
        "text": "|>JOYSTICK<| Terminal — Connected to Gibson",
        "ts": time.time(),
    })

    # Start log tail task
    tail_task = asyncio.create_task(_tail_logs(ws))

    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "command":
                cmd = data.get("text", "").strip()
                if cmd:
                    await _handle_command(ws, cmd)
    except WebSocketDisconnect:
        logger.info(f"Terminal client disconnected ({len(_clients) - 1} remaining)")
    except Exception as e:
        logger.error(f"Terminal WS error: {e}")
    finally:
        _clients.discard(ws)
        tail_task.cancel()


async def _tail_logs(ws: WebSocket):
    """Tail the main event log and push new lines to the client."""
    last_size = 0
    if _MAIN_LOG.exists():
        last_size = _MAIN_LOG.stat().st_size

    try:
        while True:
            await asyncio.sleep(2)  # poll interval
            if not _MAIN_LOG.exists():
                continue

            current_size = _MAIN_LOG.stat().st_size
            if current_size <= last_size:
                if current_size < last_size:
                    last_size = 0  # file was truncated/rotated
                continue

            # Read new bytes
            try:
                with open(_MAIN_LOG, "r") as f:
                    f.seek(last_size)
                    new_data = f.read()
                last_size = current_size

                for line in new_data.strip().split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                        await ws.send_json({
                            "type": "log",
                            "text": _format_event(ev),
                            "raw": ev,
                            "ts": ev.get("epoch", time.time()),
                        })
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                logger.debug(f"Tail read error: {e}")
    except asyncio.CancelledError:
        pass


# ── Async subprocess runner ──────────────────────────────────────────

async def _run_script(ws: WebSocket, cmd: list[str], label: str, cwd: str = None,
                      env_extra: dict = None, timeout: int = 120):
    """Run a subprocess and stream stdout/stderr to the terminal in real-time."""
    now = time.time()
    await ws.send_json({"type": "system", "ts": now,
                        "text": f"▶ Running: {label}..."})

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if env_extra:
        env.update(env_extra)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd or str(_REPO_DIR),
            env=env,
        )

        lines_sent = 0
        try:
            while True:
                line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=timeout
                )
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    # Color test results
                    cls = "t-log"
                    if "PASSED" in text or "passed" in text:
                        cls = "t-result"
                    elif "FAILED" in text or "ERROR" in text or "failed" in text:
                        cls = "t-error"
                    elif text.startswith("=") or text.startswith("-"):
                        cls = "t-system"
                    await ws.send_json({"type": "log", "ts": time.time(), "text": text})
                    lines_sent += 1
        except asyncio.TimeoutError:
            proc.kill()
            await ws.send_json({"type": "result", "success": False, "ts": time.time(),
                                "text": f"✗ {label} timed out after {timeout}s"})
            return

        await proc.wait()
        status = "✓" if proc.returncode == 0 else "✗"
        color_ok = proc.returncode == 0
        await ws.send_json({
            "type": "result", "success": color_ok, "ts": time.time(),
            "text": f"{status} {label} finished (exit {proc.returncode}, {lines_sent} lines)"
        })

    except Exception as e:
        await ws.send_json({"type": "result", "success": False, "ts": time.time(),
                            "text": f"✗ {label} error: {e}"})


# ── Command handler ─────────────────────────────────────────────────

HELP_TEXT = """
|>JOYSTICK<| Command & Control
════════════════════════════════════════

 ── Status ──────────────────────────
  status             Bot & engine overview
  engines            All 8 engines w/ status
  wallet             Joey wallet balances
  gas                Gas conditions
  tgsv8              TGSv8 contract state
  hub                JoystickHub module status

 ── Engines ─────────────────────────
  bot <engine>       Run engine (bot help)
  bot cycle          Full cycle (dry-run)
  bot run / stop     Background loop

 ── Recon ───────────────────────────
  recon <target>     Chain scans (recon help)

 ── Scripts ─────────────────────────
  scripts            List all by category
  scripts <category> Filter (tx, recon, deploy...)
  run <script> [args] Execute a script

 ── Oracle ──────────────────────────
  price <token>      DEX price in PLS
  reserves <pair>    LP pair reserves
  pair <tokenA> <tokenB>  Find/create pair info

 ── Wallet ──────────────────────────
  balance [token] [addr]   Token or PLS balance
  nonce [addr]             Current nonce
  approve <tok> <spender>  Check allowance

 ── Logs ────────────────────────────
  logs [N]           Last N events (default 20)
  logs engine <name> Engine-specific logs
  tail               Live log stream

 ── Tests ───────────────────────────
  test [target]      Run tests (test help)

 ── Process ─────────────────────────
  ps                 Background jobs
  kill <job>         Kill a job

 ── Terminal ────────────────────────
  clear              Clear terminal
  help               This message
  help <section>     Detailed section help
════════════════════════════════════════
""".strip()


HELP_SECTIONS = {
    "status": """
──── STATUS COMMANDS ────────────────────
  status           Full bot overview: PLS balance, engine summary,
                   gas conditions, strategist state, validator %
  engines          All 8 engines with: status, last run time,
                   profit, gas spent, win rate, circuit breaker
  wallet           Joey + Minter + Seller balances (PLS + all tokens)
  gas              Gas price (Beats), ceiling, trend, skip condition
  tgsv8            TGSv8 contract: owner, paused, authorized wallets,
                   opNonce, registry, native PLS, token balances
  hub              JoystickHub: deployed modules, selectors, balances
─────────────────────────────────────────""",

    "engines": """
──── ENGINE COMMANDS ────────────────────
  All engines default to dry-run. Add --live for real TXs.

  bot razor          E1 Cross-DEX arb scan           [seller]
  bot cereal         E2 GIBS harvest (DSS)           [joey]
  bot beat           E3 Territory Beat positioning   [joey]
  bot factory        E4 AFF/WM dual-mode mint        [minter]
  bot lau            E5 ABUPRU state loop            [joey]
  bot davinci        E6 Treasury sniper              [minter]
  bot backbone       E7 Spine runner                 [minter]
  bot phreak         E8 Web weaver (DEPLOY/ARM/STITCH) [minter]

  bot cycle          Run full strategist cycle
  bot cycle --live   Live-fire cycle (real TXs!)
  bot status         Engine/strategist P&L table
  bot wallet-status  3-wallet balances + auth check
  bot rpc-status     RPC provider health + latency
  bot log-status     Event log statistics
  bot run            Start bot loop (background)
  bot stop           Stop background bot

  Aliases: e1=razor e2=cereal e3=beat e4=factory
           e5=lau e6=davinci e7=backbone e8=phreak
─────────────────────────────────────────""",

    "recon": """
──── RECON COMMANDS ─────────────────────
  All recon is read-only. No TXs sent.

  recon arb          Scan 272 QINGs for arb opps
  recon aff          AFF + WM profitability check
  recon beat         Beat prerequisites (SHIO, CHEON)
  recon tgsv8        TGSv8 state verification
  recon pairs        GIBS LP pair reserve scan
  recon players      Active player balance scan
  recon crows        CROWS bouncer analysis
  recon shio         SHIO availability + pricing
  recon void         VOID active users
  recon fornax       Fornax whale mapping
  recon player       Single player deep scan
  recon zuo          ZUO ownership
  recon zurich       Zurich sources
─────────────────────────────────────────""",

    "scripts": """
──── SCRIPTS ────────────────────────────
  scripts            List all scripts by category
  scripts tx         Transaction scripts only
  scripts recon      Recon/scan scripts only
  scripts deploy     Contract deployment scripts
  scripts chat       VOID chat scripts
  scripts intel      Competitor analysis scripts
  scripts lp         LP management scripts
  scripts tools      Bot tools (tests, diagnostics)

  run <script.py> [args]     Execute any script
  run <script.py> --help     Script-specific help

  Scripts live in two locations:
    scripts/              <- standalone ops
    scripts/Joystick/tools/  <- bot-integrated tools
─────────────────────────────────────────""",

    "oracle": """
──── ORACLE COMMANDS ────────────────────
  price <token>        Get token price in PLS via DEX
                       Accepts: symbol (AFF, GIBS, WM, ATROPA...)
                       or address (0x...)
  price <token> --usd  Include USD conversion

  reserves <pair_addr> Raw reserves for any LP pair

  pair <tokenA> <tokenB>       Find pair on V1+V2
  pair <tokenA> <tokenB> --v2  V2 only
─────────────────────────────────────────""",

    "wallet": """
──── WALLET COMMANDS ────────────────────
  balance                All token balances (Joey)
  balance <token>        Specific token balance
  balance <token> <addr> Balance for any address
  balance pls [addr]     Native PLS balance

  nonce                  Joey's current nonce
  nonce <addr>           Nonce for any address
  nonce all              All 3 wallets + TGSv8

  approve <token> <spender>       Check allowance
  approve <token> <spender> --set Set max approval (TX!)

  Token shortcuts: aff, gibs, wm, atropa, wpls, void,
                   fed, prvx, fornax, crows
─────────────────────────────────────────""",

    "logs": """
──── LOG COMMANDS ───────────────────────
  logs               Last 20 events
  logs <N>           Last N events
  logs engine razor  E1 RAZOR logs only
  logs engine cereal E2 CEREAL logs only
  logs tx            Transaction logs only
  logs error         Errors/warnings only
  tail               Toggle live streaming
                     (always active via WebSocket)
─────────────────────────────────────────""",

    "tests": """
──── TEST COMMANDS ──────────────────────
  test               Full test suite
  test anvil         Anvil fork integration
  test data          Data store tests
  test engines       Engine simulation tests
  test tgsv8         TGSv8+ contract tests
  test razor         RAZOR PulseChain tests
  test hub           JoystickHub tests
  test <file.py>     Run specific test file
─────────────────────────────────────────""",

    "process": """
──── PROCESS COMMANDS ───────────────────
  ps                 List all background jobs
                     Shows: name, PID, status
  kill <job>         Kill by name
  kill all           Kill all background jobs
─────────────────────────────────────────""",
}


async def _handle_command(ws: WebSocket, cmd: str):
    """Process a command from the terminal input."""
    now = time.time()

    parts = cmd.split()
    verb = parts[0].lower() if parts else ""

    try:
        # ── Help ──
        if verb in ("help", "?"):
            if len(parts) >= 2:
                section = parts[1].lower()
                if section in HELP_SECTIONS:
                    await ws.send_json({"type": "result", "success": True, "ts": now,
                                        "text": HELP_SECTIONS[section].strip()})
                else:
                    available = ", ".join(sorted(HELP_SECTIONS.keys()))
                    await ws.send_json({"type": "result", "success": True, "ts": now,
                                        "text": f"Unknown section: {section}\nAvailable: {available}"})
            else:
                await ws.send_json({"type": "result", "success": True, "ts": now, "text": HELP_TEXT})

        # ── Status commands ──
        elif verb == "status":
            await _cmd_status(ws, now)
        elif verb == "engines":
            await _cmd_engines(ws, now)
        elif verb == "wallet":
            await _cmd_wallet(ws, now)
        elif verb == "gas":
            await _cmd_gas(ws, now)
        elif verb == "tgsv8":
            await _cmd_tgsv8(ws, now)
        elif verb == "hub":
            await _cmd_hub(ws, now)

        # ── Bot control ──
        elif verb == "bot":
            await _cmd_bot(ws, parts, now)

        # ── Oracle ──
        elif verb == "price":
            await _cmd_price(ws, parts, now)
        elif verb == "reserves":
            await _cmd_reserves(ws, parts, now)
        elif verb == "pair":
            await _cmd_pair(ws, parts, now)

        # ── Wallet ──
        elif verb == "balance":
            await _cmd_balance(ws, parts, now)
        elif verb == "nonce":
            await _cmd_nonce(ws, parts, now)
        elif verb == "approve":
            await _cmd_approve(ws, parts, now)

        # ── Scripts ──
        elif verb == "scripts":
            await _cmd_scripts(ws, parts, now)

        # ── Logs ──
        elif verb == "logs":
            await _cmd_logs(ws, parts, now)
        elif verb == "tail":
            await ws.send_json({"type": "system", "ts": now,
                                "text": "Live log streaming is always active via WebSocket."})

        # ── Tests ──
        elif verb == "test":
            await _cmd_test(ws, parts, now)

        # ── Recon ──
        elif verb == "recon":
            await _cmd_recon(ws, parts, now)

        # ── Run script ──
        elif verb == "run":
            await _cmd_run(ws, parts, now)

        # ── Process management ──
        elif verb == "ps":
            await _cmd_ps(ws, now)
        elif verb == "kill":
            await _cmd_kill(ws, parts, now)

        # ── Terminal ──
        elif verb == "clear":
            await ws.send_json({"type": "clear", "ts": now})

        else:
            await ws.send_json({
                "type": "result", "success": False, "ts": now,
                "text": f"Unknown command: {verb}. Type 'help' for commands.",
            })

    except Exception as e:
        await ws.send_json({
            "type": "result", "success": False, "ts": now,
            "text": f"Command error: {e}",
        })


async def _cmd_status(ws: WebSocket, now: float):
    """Fetch /api/overview and display a compact status."""
    import httpx
    port = config.API_PORT
    async with httpx.AsyncClient() as client:
        r = await client.get(f"http://127.0.0.1:{port}/api/overview")
        d = r.json()

    w = d["wallet"]
    g = d["gas"]
    bot = "ONLINE" if d.get("bot_online") else "OFFLINE"
    engines_running = sum(1 for e in d["engines"]["engines"] if e["status"] == "running")
    engines_ready = sum(1 for e in d["engines"]["engines"] if e["status"] == "ready")

    text = f"""
──── STATUS ─────────────────────────
  Bot:       {bot}
  Block:     {w['block_number']:,}
  PLS:       {w['pls_balance']:,.2f}
  Validator: {w['validator_progress_pct']:.2f}%
  Gas:       {g['gas_price_beats']:,.0f} Beats [{g['condition'].upper()}]
  Engines:   {engines_running} running, {engines_ready} ready
─────────────────────────────────────""".strip()
    await ws.send_json({"type": "result", "success": True, "ts": now, "text": text})


async def _cmd_engines(ws: WebSocket, now: float):
    """List all engines with status."""
    import httpx
    port = config.API_PORT
    async with httpx.AsyncClient() as client:
        r = await client.get(f"http://127.0.0.1:{port}/api/engines")
        d = r.json()

    lines = ["──── ENGINES ────────────────────────"]
    for e in d["engines"]:
        status = e["status"].upper().ljust(8)
        roi = f"ROI: {e['roi_pct']}%" if e.get("roi_pct") is not None else ""
        earned = f"  Earned: {e['total_earned_pls']:,.0f} PLS" if e.get("total_earned_pls") else ""
        lines.append(f"  {e['id']} {e['name']:12s} [{status}] {roi}{earned}")
    lines.append("─────────────────────────────────────")
    await ws.send_json({"type": "result", "success": True, "ts": now, "text": "\n".join(lines)})


async def _cmd_wallet(ws: WebSocket, now: float):
    """Show wallet balances."""
    import httpx
    port = config.API_PORT
    async with httpx.AsyncClient() as client:
        r = await client.get(f"http://127.0.0.1:{port}/api/wallet")
        w = r.json()

    lines = [
        "──── WALLET ─────────────────────────",
        f"  Address:  {w['address'][:10]}...{w['address'][-4:]}",
        f"  PLS:      {w['pls_balance']:,.2f}",
        f"  Buffer:   {'✓ OK' if w['gas_buffer_ok'] else '✗ LOW'}",
    ]
    for t in w.get("tokens", []):
        if t["balance"] > 0:
            lines.append(f"  {t['symbol']:10s} {t['balance']:,.4f}")
    lines.append("─────────────────────────────────────")
    await ws.send_json({"type": "result", "success": True, "ts": now, "text": "\n".join(lines)})


async def _cmd_gas(ws: WebSocket, now: float):
    """Show gas conditions."""
    import httpx
    port = config.API_PORT
    async with httpx.AsyncClient() as client:
        r = await client.get(f"http://127.0.0.1:{port}/api/gas")
        g = r.json()

    text = f"""
──── GAS ────────────────────────────
  Price:     {g['gas_price_beats']:,.0f} Beats
  Ceiling:   {g['gas_ceiling_beats']} Beats
  Condition: {g['condition'].upper()}
─────────────────────────────────────""".strip()
    await ws.send_json({"type": "result", "success": True, "ts": now, "text": text})


async def _cmd_tgsv8(ws: WebSocket, now: float):
    """Show TGSv8 contract state."""
    import httpx
    port = config.API_PORT
    async with httpx.AsyncClient() as client:
        r = await client.get(f"http://127.0.0.1:{port}/api/tgsv8")
        v8 = r.json()

    auth = v8.get("authorized", {})
    lines = [
        "──── TGSv8 ──────────────────────────",
        f"  Owner:    {'✓ Joey' if v8['owner_is_joey'] else v8.get('owner', '?')}",
        f"  Paused:   {'YES' if v8['paused'] else 'No'}",
        f"  Auth:     Joey={'✓' if auth.get('joey') else '✗'}  Minter={'✓' if auth.get('minter') else '✗'}  Seller={'✓' if auth.get('seller') else '✗'}",
        f"  Nonce:    {v8['op_nonce']}",
        f"  Registry: {v8['registry_len']} tokens",
        f"  PLS:      {v8['native_pls']:,.2f}",
    ]
    bals = v8.get("token_balances", {})
    for sym, bal in bals.items():
        if bal > 0:
            lines.append(f"  {sym:10s} {bal:,.4f}")
    lines.append("─────────────────────────────────────")
    await ws.send_json({"type": "result", "success": True, "ts": now, "text": "\n".join(lines)})


# ── Token shortcuts for oracle/wallet commands ──────────────────────

TOKEN_SHORTCUTS = {
    "gibs":    "0x66a08aa12da955eb63d7ac121a88b2b210a07b03",
    "aff":     "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D",
    "wm":      "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29",
    "atropa":  "0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6",
    "wpls":    "0xA1077a294dDE1B09bB078844df40758a5D0f9a27",
    "void":    "0x965B0d74591bF30327075A247C47dBf487dCff08",
    "fed":     "0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff",
    "prvx":    "0xf6f8db0aba00007681f8faf16a0fda1c9b030b11",
    "fornax":  "0xF6C50fFE7efbDeE63A92E52A4D5E9afF7fb4A4D7",
    "crows":   "0x203e366A1821570b2f84Ff5ae8B3BdeB48Dc4fa1",
    "dai":     "0x6B175474E89094C44Da98b954EedeAC495271d0F",
    "affection": "0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D",
}

JOEY_WALLET = "0x17367877aF5A8D0Eb33ba5689A880f696386E24D"
READ_RPC = "https://rpc-pulsechain.g4mm4.io"

PULSEX_V1_FACTORY = "0x1715a3E4A142d8b698131108995174F37aEBA10D"
PULSEX_V2_FACTORY = "0x29eA7545DEf87022BAdc76323F373EA1e707C523"
PULSEX_V2_ROUTER = "0x165C3410fC91EF562C50559f7d2289fEbed552d9"


def _resolve_token(token_str: str) -> str:
    """Resolve a token shortcut or address to a checksummed address."""
    lower = token_str.lower()
    if lower in TOKEN_SHORTCUTS:
        return TOKEN_SHORTCUTS[lower]
    if token_str.startswith("0x") and len(token_str) == 42:
        return token_str
    return ""


# ── Hub command ─────────────────────────────────────────────────────

async def _cmd_hub(ws: WebSocket, now: float):
    """JoystickHub module status."""
    script = '''
import json, os, requests

RPC = "{rpc}"
JOEY = "{joey}"

def eth_call(to, data):
    r = requests.post(RPC, json={{"jsonrpc":"2.0","method":"eth_call","params":[{{"to":to,"data":data}},"latest"],"id":1}})
    return json.loads(r.text).get("result","0x")

def balance_of(token, holder):
    sel = "0x70a08231"
    data = sel + holder[2:].lower().zfill(64)
    res = eth_call(token, data)
    if len(res) < 66: return 0
    return int(res, 16) / 1e18

hub_addr = os.getenv("JOYSTICK_HUB_ADDRESS", "")
if not hub_addr:
    print("JoystickHub address not configured.")
    print("Set JOYSTICK_HUB_ADDRESS env var to enable.")
else:
    print(f"──── JOYSTICK HUB ───────────────────")
    print(f"  Address: {{hub_addr[:10]}}...{{hub_addr[-4:]}}")
    # Check PLS balance
    pls_r = requests.post(RPC, json={{"jsonrpc":"2.0","method":"eth_getBalance","params":[hub_addr,"latest"],"id":1}})
    pls_bal = int(json.loads(pls_r.text).get("result","0x0"), 16) / 1e18
    print(f"  PLS:     {{pls_bal:,.2f}}")
    # Check owner
    owner_res = eth_call(hub_addr, "0x8da5cb5b")
    if len(owner_res) >= 42:
        owner = "0x" + owner_res[-40:]
        is_joey = owner.lower() == JOEY.lower()
        print(f"  Owner:   {{'Joey' if is_joey else owner[:14]+'...'}}")
    print(f"─────────────────────────────────────")
'''.format(rpc=READ_RPC, joey=JOEY_WALLET)

    cmd = [_PYTHON, "-c", script]
    await _run_script(ws, cmd, "JoystickHub Status", timeout=30)


# ── Oracle commands ─────────────────────────────────────────────────

async def _cmd_price(ws: WebSocket, parts: list, now: float):
    """Get DEX price for a token."""
    if len(parts) < 2:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": "Usage: price <token|address> [--usd]\n"
                                    "Shortcuts: " + ", ".join(sorted(TOKEN_SHORTCUTS.keys()))})
        return

    token_arg = parts[1]
    show_usd = "--usd" in parts
    token_addr = _resolve_token(token_arg)
    if not token_addr:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": f"Unknown token: {token_arg}\n"
                                    "Use address (0x...) or shortcut: " +
                                    ", ".join(sorted(TOKEN_SHORTCUTS.keys()))})
        return

    script = '''
import json, requests

RPC = "{rpc}"
TOKEN = "{token}"
TOKEN_NAME = "{name}"
WPLS = "0xA1077a294dDE1B09bB078844df40758a5D0f9a27"
ROUTER_V2 = "{router}"
SHOW_USD = {show_usd}

def eth_call(to, data):
    r = requests.post(RPC, json={{"jsonrpc":"2.0","method":"eth_call","params":[{{"to":to,"data":data}},"latest"],"id":1}})
    return json.loads(r.text).get("result","0x")

# getAmountsOut(uint256,address[]) on V2 Router
amount_in = 1 * 10**18  # 1 token
path = [TOKEN, WPLS]
# Encode: selector + amountIn + offset + length + addr0 + addr1
sel = "0xd06ca61f"
data = sel + hex(amount_in)[2:].zfill(64) + "0000000000000000000000000000000000000000000000000000000000000040" + "0000000000000000000000000000000000000000000000000000000000000002" + TOKEN[2:].lower().zfill(64) + WPLS[2:].lower().zfill(64)
res = eth_call(ROUTER_V2, data)
if len(res) < 194 or res == "0x":
    print(f"No V2 liquidity found for {{TOKEN_NAME}}/WPLS")
else:
    # Parse amounts array: offset(32) + length(32) + amount0(32) + amount1(32)
    amounts_offset = int(res[2:66], 16) * 2 + 2
    amounts_len = int(res[amounts_offset:amounts_offset+64], 16)
    amount_out = int(res[amounts_offset+128:amounts_offset+192], 16)
    pls_price = amount_out / 1e18
    print(f"{{TOKEN_NAME}}: {{pls_price:,.4f}} PLS per token")
    if SHOW_USD:
        print(f"  (USD conversion requires external price feed)")
'''.format(rpc=READ_RPC, token=token_addr, name=token_arg.upper(),
           router=PULSEX_V2_ROUTER, show_usd=show_usd)

    cmd = [_PYTHON, "-c", script]
    await _run_script(ws, cmd, f"Price: {token_arg}", timeout=30)


async def _cmd_reserves(ws: WebSocket, parts: list, now: float):
    """Get raw reserves for an LP pair."""
    if len(parts) < 2:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": "Usage: reserves <pair_address>"})
        return

    pair_addr = parts[1]
    if not pair_addr.startswith("0x") or len(pair_addr) != 42:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": "Invalid pair address. Must be 0x... (42 chars)"})
        return

    script = '''
import json, requests

RPC = "{rpc}"
PAIR = "{pair}"

def eth_call(to, data):
    r = requests.post(RPC, json={{"jsonrpc":"2.0","method":"eth_call","params":[{{"to":to,"data":data}},"latest"],"id":1}})
    return json.loads(r.text).get("result","0x")

# getReserves()
res = eth_call(PAIR, "0x0902f1ac")
if len(res) < 194:
    print(f"Failed to read reserves from {{PAIR}}")
else:
    r0 = int(res[2:66], 16)
    r1 = int(res[66:130], 16)
    # token0/token1
    t0 = eth_call(PAIR, "0x0dfe1681")
    t1 = eth_call(PAIR, "0xd21220a7")
    t0_addr = "0x" + t0[-40:] if len(t0) >= 42 else "?"
    t1_addr = "0x" + t1[-40:] if len(t1) >= 42 else "?"
    print(f"──── PAIR RESERVES ──────────────────")
    print(f"  Pair:    {{PAIR[:10]}}...{{PAIR[-4:]}}")
    print(f"  Token0:  {{t0_addr[:10]}}...  Reserve: {{r0/1e18:,.4f}}")
    print(f"  Token1:  {{t1_addr[:10]}}...  Reserve: {{r1/1e18:,.4f}}")
    if r0 > 0 and r1 > 0:
        print(f"  Rate:    1 T0 = {{r1/r0:,.6f}} T1")
        print(f"           1 T1 = {{r0/r1:,.6f}} T0")
    print(f"─────────────────────────────────────")
'''.format(rpc=READ_RPC, pair=pair_addr)

    cmd = [_PYTHON, "-c", script]
    await _run_script(ws, cmd, f"Reserves: {pair_addr[:10]}...", timeout=30)


async def _cmd_pair(ws: WebSocket, parts: list, now: float):
    """Find LP pair for two tokens."""
    if len(parts) < 3:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": "Usage: pair <tokenA> <tokenB> [--v2]\n"
                                    "Accepts shortcuts or addresses."})
        return

    token_a = _resolve_token(parts[1])
    token_b = _resolve_token(parts[2])
    if not token_a or not token_b:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": f"Unknown token. Available shortcuts: " +
                                    ", ".join(sorted(TOKEN_SHORTCUTS.keys()))})
        return

    v2_only = "--v2" in parts

    script = '''
import json, requests

RPC = "{rpc}"
TOKEN_A = "{token_a}"
TOKEN_B = "{token_b}"
NAME_A = "{name_a}"
NAME_B = "{name_b}"
V2_ONLY = {v2_only}

FACTORIES = {{}}
if not V2_ONLY:
    FACTORIES["V1"] = "{v1_factory}"
FACTORIES["V2"] = "{v2_factory}"

def eth_call(to, data):
    r = requests.post(RPC, json={{"jsonrpc":"2.0","method":"eth_call","params":[{{"to":to,"data":data}},"latest"],"id":1}})
    return json.loads(r.text).get("result","0x")

def get_pair(factory, t0, t1):
    sel = "0xe6a43905"
    data = sel + t0[2:].lower().zfill(64) + t1[2:].lower().zfill(64)
    res = eth_call(factory, data)
    if len(res) < 66: return None
    addr = "0x" + res[-40:]
    return addr if addr != "0x" + "0"*40 else None

print(f"──── PAIR LOOKUP: {{NAME_A}}/{{NAME_B}} ──────")
found = False
for dex, factory in FACTORIES.items():
    pair = get_pair(factory, TOKEN_A, TOKEN_B)
    if pair:
        found = True
        # Get reserves
        res = eth_call(pair, "0x0902f1ac")
        if len(res) >= 194:
            r0 = int(res[2:66], 16) / 1e18
            r1 = int(res[66:130], 16) / 1e18
            print(f"  {{dex}}: {{pair}}")
            print(f"       R0: {{r0:,.4f}}  R1: {{r1:,.4f}}")
        else:
            print(f"  {{dex}}: {{pair}} (empty)")
    else:
        print(f"  {{dex}}: No pair found")
if not found:
    print(f"  No pairs exist for {{NAME_A}}/{{NAME_B}}")
print(f"─────────────────────────────────────")
'''.format(rpc=READ_RPC, token_a=token_a, token_b=token_b,
           name_a=parts[1].upper(), name_b=parts[2].upper(),
           v2_only=v2_only, v1_factory=PULSEX_V1_FACTORY,
           v2_factory=PULSEX_V2_FACTORY)

    cmd = [_PYTHON, "-c", script]
    await _run_script(ws, cmd, f"Pair: {parts[1]}/{parts[2]}", timeout=30)


# ── Wallet commands ─────────────────────────────────────────────────

async def _cmd_balance(ws: WebSocket, parts: list, now: float):
    """Check token or PLS balance."""
    if len(parts) == 1:
        # No args — show full wallet (reuse existing handler)
        await _cmd_wallet(ws, now)
        return

    token_arg = parts[1].lower()
    addr = parts[2] if len(parts) >= 3 else JOEY_WALLET

    if token_arg == "pls":
        script = '''
import json, requests
RPC = "{rpc}"
ADDR = "{addr}"
r = requests.post(RPC, json={{"jsonrpc":"2.0","method":"eth_getBalance","params":[ADDR,"latest"],"id":1}})
bal = int(json.loads(r.text).get("result","0x0"), 16) / 1e18
print(f"PLS balance: {{bal:,.2f}}")
print(f"Address: {{ADDR[:10]}}...{{ADDR[-4:]}}")
'''.format(rpc=READ_RPC, addr=addr)
    else:
        token_addr = _resolve_token(token_arg)
        if not token_addr:
            await ws.send_json({"type": "result", "success": False, "ts": now,
                                "text": f"Unknown token: {token_arg}\n"
                                        "Shortcuts: " + ", ".join(sorted(TOKEN_SHORTCUTS.keys()))})
            return
        script = '''
import json, requests
RPC = "{rpc}"
TOKEN = "{token}"
ADDR = "{addr}"
NAME = "{name}"

def eth_call(to, data):
    r = requests.post(RPC, json={{"jsonrpc":"2.0","method":"eth_call","params":[{{"to":to,"data":data}},"latest"],"id":1}})
    return json.loads(r.text).get("result","0x")

sel = "0x70a08231"
data = sel + ADDR[2:].lower().zfill(64)
res = eth_call(TOKEN, data)
bal = int(res, 16) / 1e18 if len(res) >= 66 else 0
print(f"{{NAME}} balance: {{bal:,.6f}}")
print(f"Address: {{ADDR[:10]}}...{{ADDR[-4:]}}")
'''.format(rpc=READ_RPC, token=token_addr, addr=addr, name=token_arg.upper())

    cmd = [_PYTHON, "-c", script]
    await _run_script(ws, cmd, f"Balance: {token_arg}", timeout=30)


async def _cmd_nonce(ws: WebSocket, parts: list, now: float):
    """Check current nonce."""
    if len(parts) >= 2 and parts[1].lower() == "all":
        # Show all wallets
        script = '''
import json, os, requests
RPC = "{rpc}"
wallets = {{
    "Joey": "{joey}",
}}
minter = os.getenv("MINTER_WALLET", "")
seller = os.getenv("SELLER_WALLET", "")
if minter: wallets["Minter"] = minter
if seller: wallets["Seller"] = seller

tgsv8 = os.getenv("TGSV8_ADDRESS", "")
print("──── NONCES ─────────────────────────")
for name, addr in wallets.items():
    r = requests.post(RPC, json={{"jsonrpc":"2.0","method":"eth_getTransactionCount","params":[addr,"latest"],"id":1}})
    nonce = int(json.loads(r.text).get("result","0x0"), 16)
    print(f"  {{name:10s}} {{addr[:10]}}...{{addr[-4:]}}  nonce={{nonce}}")
if tgsv8:
    # Read opNonce from TGSv8
    def eth_call(to, data):
        r = requests.post(RPC, json={{"jsonrpc":"2.0","method":"eth_call","params":[{{"to":to,"data":data}},"latest"],"id":1}})
        return json.loads(r.text).get("result","0x")
    # opNonce() selector
    res = eth_call(tgsv8, "0x5fd0d1e3")
    if len(res) >= 66:
        op_nonce = int(res, 16)
        print(f"  TGSv8      {{tgsv8[:10]}}...{{tgsv8[-4:]}}  opNonce={{op_nonce}}")
print("─────────────────────────────────────")
'''.format(rpc=READ_RPC, joey=JOEY_WALLET)
        cmd = [_PYTHON, "-c", script]
        await _run_script(ws, cmd, "All Nonces", timeout=30)
    else:
        addr = parts[1] if len(parts) >= 2 else JOEY_WALLET
        script = '''
import json, requests
RPC = "{rpc}"
ADDR = "{addr}"
r = requests.post(RPC, json={{"jsonrpc":"2.0","method":"eth_getTransactionCount","params":[ADDR,"latest"],"id":1}})
nonce = int(json.loads(r.text).get("result","0x0"), 16)
print(f"Nonce: {{nonce}}")
print(f"Address: {{ADDR[:10]}}...{{ADDR[-4:]}}")
'''.format(rpc=READ_RPC, addr=addr)
        cmd = [_PYTHON, "-c", script]
        await _run_script(ws, cmd, "Nonce", timeout=30)


async def _cmd_approve(ws: WebSocket, parts: list, now: float):
    """Check or set token approval."""
    if len(parts) < 3:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": "Usage: approve <token> <spender> [--set]\n"
                                    "  approve gibs 0x1234...  (check allowance)\n"
                                    "  approve gibs 0x1234... --set  (set max approval - TX!)"})
        return

    token_addr = _resolve_token(parts[1])
    if not token_addr:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": f"Unknown token: {parts[1]}"})
        return

    spender = parts[2]
    if not spender.startswith("0x") or len(spender) != 42:
        # Try resolving as shortcut
        spender = _resolve_token(parts[2])
        if not spender:
            await ws.send_json({"type": "result", "success": False, "ts": now,
                                "text": f"Invalid spender address: {parts[2]}"})
            return

    if "--set" in parts:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": "Approval TX not available from terminal. Use:\n"
                                    "  run tx_approve.py --token <addr> --spender <addr>"})
        return

    script = '''
import json, requests
RPC = "{rpc}"
TOKEN = "{token}"
OWNER = "{owner}"
SPENDER = "{spender}"
TOKEN_NAME = "{name}"

def eth_call(to, data):
    r = requests.post(RPC, json={{"jsonrpc":"2.0","method":"eth_call","params":[{{"to":to,"data":data}},"latest"],"id":1}})
    return json.loads(r.text).get("result","0x")

# allowance(address,address)
sel = "0xdd62ed3e"
data = sel + OWNER[2:].lower().zfill(64) + SPENDER[2:].lower().zfill(64)
res = eth_call(TOKEN, data)
allowance = int(res, 16) / 1e18 if len(res) >= 66 else 0
max_uint = 2**256 - 1
raw = int(res, 16) if len(res) >= 66 else 0
status = "MAX" if raw > max_uint / 2 else f"{{allowance:,.4f}}"
print(f"{{TOKEN_NAME}} allowance: {{status}}")
print(f"  Owner:   {{OWNER[:10]}}...{{OWNER[-4:]}}")
print(f"  Spender: {{SPENDER[:10]}}...{{SPENDER[-4:]}}")
'''.format(rpc=READ_RPC, token=token_addr, owner=JOEY_WALLET,
           spender=spender, name=parts[1].upper())

    cmd = [_PYTHON, "-c", script]
    await _run_script(ws, cmd, f"Allowance: {parts[1]}", timeout=30)


# ── Scripts command ─────────────────────────────────────────────────

_SCRIPT_CATEGORIES = {
    "tx":      ("Transaction Scripts",        lambda f: f.startswith("tx_")),
    "recon":   ("Recon & Scanning",           lambda f: f.startswith("recon_") or f.endswith("_recon.py")),
    "deploy":  ("Contract Deployment",        lambda f: f.startswith("deploy_")),
    "chat":    ("VOID Chat",                  lambda f: f.startswith("chat_")),
    "intel":   ("Intelligence & Analysis",    lambda f: f.startswith("intel_") or f.startswith("analyze_")),
    "lp":      ("LP Management",              lambda f: f.startswith("lp_")),
    "scan":    ("Token/Arb Scanning",         lambda f: f.startswith("scan_")),
    "browser": ("Browser Console (JS)",       lambda f: f.endswith(".js")),
}


def _get_script_docstring(path: Path) -> str:
    """Extract first line of module docstring."""
    try:
        text = path.read_text(errors="replace")
        for marker in ('"""', "'''"):
            idx = text.find(marker)
            if idx >= 0:
                end = text.find(marker, idx + 3)
                if end > idx:
                    doc = text[idx+3:end].strip().split("\n")[0]
                    return doc[:60]
        return ""
    except Exception:
        return ""


def _categorize_scripts() -> dict:
    """Scan scripts/ and tools/ directories, return {category: [(filename, docstring)]}."""
    result = {k: [] for k in list(_SCRIPT_CATEGORIES.keys()) + ["tools", "misc"]}

    # Scan scripts/ directory (Python files, exclude archive/ and __*)
    for f in sorted(_SCRIPTS_DIR.glob("*.py")):
        if f.name.startswith("__"):
            continue
        name = f.name
        doc = _get_script_docstring(f)
        matched = False
        for cat, (label, matcher) in _SCRIPT_CATEGORIES.items():
            if matcher(name):
                result[cat].append((name, doc))
                matched = True
                break
        if not matched:
            result["misc"].append((name, doc))

    # Scan JS files
    for f in sorted(_SCRIPTS_DIR.glob("*.js")):
        doc = _get_script_docstring(f)
        result["browser"].append((f.name, doc))

    # Scan tools/ directory
    for f in sorted(_TOOLS_DIR.glob("*.py")):
        if f.name.startswith("__"):
            continue
        doc = _get_script_docstring(f)
        result["tools"].append((f"tools/{f.name}", doc))

    # Remove empty categories
    return {k: v for k, v in result.items() if v}


async def _cmd_scripts(ws: WebSocket, parts: list, now: float):
    """List available scripts by category."""
    filter_cat = parts[1].lower() if len(parts) >= 2 else None
    cats = _categorize_scripts()

    if filter_cat and filter_cat not in cats:
        available = ", ".join(sorted(cats.keys()))
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": f"Unknown category: {filter_cat}\nAvailable: {available}"})
        return

    lines = ["──── SCRIPTS ────────────────────────────────"]

    cat_labels = {k: v[0] for k, v in _SCRIPT_CATEGORIES.items()}
    cat_labels["tools"] = "Bot Tools"
    cat_labels["misc"] = "Miscellaneous"

    for cat, scripts in cats.items():
        if filter_cat and cat != filter_cat:
            continue
        label = cat_labels.get(cat, cat.title())
        lines.append(f"\n  {label} ({len(scripts)}):")
        for fname, doc in scripts:
            doc_str = f" -- {doc}" if doc else ""
            lines.append(f"    {fname:<35s}{doc_str}")

    lines.append("\n─────────────────────────────────────────────")
    lines.append("  run <script.py> [args]")
    lines.append("  scripts <category> to filter")

    await ws.send_json({"type": "result", "success": True, "ts": now,
                        "text": "\n".join(lines)})


async def _cmd_logs(ws: WebSocket, parts: list, now: float):
    """Show recent log entries."""
    n = 20
    engine = None
    if len(parts) >= 2:
        if parts[1] == "engine" and len(parts) >= 3:
            engine = parts[2]
        else:
            try:
                n = int(parts[1])
            except ValueError:
                engine = parts[1]

    if engine:
        log_file = _EVENTS_DIR / f"engine_{engine.lower()}.jsonl"
    else:
        log_file = _MAIN_LOG

    events = _read_tail(log_file, n)
    if not events:
        await ws.send_json({"type": "result", "success": True, "ts": now,
                            "text": f"No logs found in {log_file.name}"})
        return

    lines = [f"──── LOGS ({log_file.name}, last {len(events)}) ────"]
    for ev in events:
        lines.append("  " + _format_event(ev))
    await ws.send_json({"type": "result", "success": True, "ts": now, "text": "\n".join(lines)})


# ── Bot commands ─────────────────────────────────────────────────────

_BOT_MODULE = "scripts.Joystick.bot"


async def _run_engine(ws: WebSocket, engine_name: str, label: str, is_live: bool, now: float):
    """Run a specific engine via --engine flag."""
    flags = ["--engine", engine_name]
    if not is_live:
        flags.append("--dry-run")
    mode = "LIVE" if is_live else "dry-run"
    if is_live:
        await ws.send_json({"type": "system", "ts": now,
                            "text": f"⚠ LIVE MODE — {label} will send real transactions!"})
    cmd = [_PYTHON, "-m", _BOT_MODULE] + flags
    await _run_script(ws, cmd, f"{label} ({mode})", timeout=180)


async def _cmd_bot(ws: WebSocket, parts: list, now: float):
    """Bot control commands."""
    sub = parts[1].lower() if len(parts) >= 2 else "help"
    is_live = "--live" in parts

    if sub == "help":
        await ws.send_json({"type": "result", "success": True, "ts": now, "text": """
──── BOT COMMANDS ───────────────────
  bot cycle          Dry-run one cycle
  bot cycle --live   Live-fire one cycle
  bot status         Engine/strategist status
  bot wallet-status  3-wallet balances + auth
  bot rpc-status     RPC provider health
  bot log-status     Event log statistics

 ── Per-Engine (dry-run, add --live) ──
  bot razor          E1 Cross-DEX arb scan
  bot cereal         E2 GIBS harvest
  bot beat           E3 Territory Beat
  bot factory        E4 AFF/WM mint
  bot lau            E5 ABUPRU state loop
  bot davinci        E6 Treasury sniper
  bot backbone       E7 Spine runner
  bot phreak         E8 Web weaver

 ── Control ─────────────────────────
  bot run            Start bot loop (background)
  bot stop           Stop background bot
─────────────────────────────────────""".strip()})

    elif sub == "cycle":
        flags = ["--once"]
        if not is_live:
            flags.append("--dry-run")
        label = "Bot cycle (LIVE)" if is_live else "Bot cycle (dry-run)"
        if is_live:
            await ws.send_json({"type": "system", "ts": now,
                                "text": "⚠ LIVE MODE — real transactions will be sent!"})
        cmd = [_PYTHON, "-m", _BOT_MODULE] + flags
        await _run_script(ws, cmd, label, timeout=300)

    elif sub == "status":
        cmd = [_PYTHON, "-m", _BOT_MODULE, "--status"]
        await _run_script(ws, cmd, "Bot Status", timeout=60)

    elif sub in ("wallet-status", "wallet"):
        cmd = [_PYTHON, "-m", _BOT_MODULE, "--wallet-status"]
        await _run_script(ws, cmd, "Wallet Status", timeout=60)

    elif sub in ("rpc-status", "rpc"):
        cmd = [_PYTHON, "-m", _BOT_MODULE, "--rpc-status"]
        await _run_script(ws, cmd, "RPC Status", timeout=30)

    elif sub in ("log-status", "log"):
        cmd = [_PYTHON, "-m", _BOT_MODULE, "--log-status"]
        await _run_script(ws, cmd, "Log Status", timeout=30)

    elif sub == "beat":
        flags = ["--beat-only"]
        if not is_live:
            flags.append("--dry-run")
        label = "Beat Engine (LIVE)" if is_live else "Beat Engine (dry-run)"
        if is_live:
            await ws.send_json({"type": "system", "ts": now,
                                "text": "⚠ LIVE MODE — real transactions will be sent!"})
        cmd = [_PYTHON, "-m", _BOT_MODULE] + flags
        await _run_script(ws, cmd, label, timeout=180)

    elif sub == "lau":
        flags = ["--lau-only"]
        if not is_live:
            flags.append("--dry-run")
        label = "LAU Engine (LIVE)" if is_live else "LAU Engine (dry-run)"
        if is_live:
            await ws.send_json({"type": "system", "ts": now,
                                "text": "⚠ LIVE MODE — real transactions will be sent!"})
        cmd = [_PYTHON, "-m", _BOT_MODULE] + flags
        await _run_script(ws, cmd, label, timeout=180)

    elif sub in ("razor", "e1"):
        await _run_engine(ws, "Arb", "E1 RAZOR", is_live, now)
    elif sub in ("cereal", "dss", "e2"):
        await _run_engine(ws, "DSS", "E2 CEREAL", is_live, now)
    elif sub in ("factory", "e4", "e4-test", "factory-test"):
        if sub in ("e4-test", "factory-test"):
            cmd = [_PYTHON, "-m", _BOT_MODULE, "--force-test", "--dry-run", "--once"]
            await _run_script(ws, cmd, "E4 TokenFactory Test", timeout=180)
        else:
            await _run_engine(ws, "TokenFactory", "E4 FACTORY", is_live, now)
    elif sub in ("davinci", "treasury", "e6"):
        await _run_engine(ws, "TreasurySniper", "E6 DaVINCI", is_live, now)
    elif sub in ("backbone", "spine", "e7"):
        await _run_engine(ws, "SpineRunner", "E7 BACKBONE", is_live, now)
    elif sub in ("phreak", "e8"):
        await _run_engine(ws, "PHR3AK", "E8 PHR3AK", is_live, now)

    elif sub == "run":
        # Start bot as a background process
        if "bot" in _bg_processes and _bg_processes["bot"].poll() is None:
            await ws.send_json({"type": "result", "success": False, "ts": now,
                                "text": "Bot is already running (PID "
                                        f"{_bg_processes['bot'].pid}). Use 'bot stop' first."})
            return

        await ws.send_json({"type": "system", "ts": now,
                            "text": "▶ Starting bot loop in background (dry-run)..."})
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            [_PYTHON, "-m", _BOT_MODULE, "--dry-run"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(_REPO_DIR),
            env=env,
        )
        _bg_processes["bot"] = proc
        await ws.send_json({"type": "result", "success": True, "ts": now,
                            "text": f"✓ Bot started (PID {proc.pid}, dry-run). "
                                    f"Logs stream via WebSocket. Use 'bot stop' to halt."})

    elif sub == "stop":
        proc = _bg_processes.get("bot")
        if not proc or proc.poll() is not None:
            await ws.send_json({"type": "result", "success": False, "ts": now,
                                "text": "No bot process running."})
            _bg_processes.pop("bot", None)
            return

        pid = proc.pid
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        _bg_processes.pop("bot", None)
        await ws.send_json({"type": "result", "success": True, "ts": now,
                            "text": f"✓ Bot stopped (PID {pid})"})

    else:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": f"Unknown bot command: {sub}. Type 'bot help' for options."})


# ── Test commands ────────────────────────────────────────────────────

# Map short names to test files
_TEST_MAP = {
    "anvil": "test_anvil_full.py",
    "data": "test_data_store.py",
    "engines": "test_engines_5_6.py",
    "tgsv8": "test_tgsv8plus.py",
    "razor": "test_razor_pulsechain.py",
    "hub": "test_joystick_hub.py",
}


async def _cmd_test(ws: WebSocket, parts: list, now: float):
    """Run pytest test suite."""
    target = parts[1].lower() if len(parts) >= 2 else "all"

    # Resolve test file
    if target == "all":
        test_path = str(_TESTS_DIR)
        label = "Full test suite"
    elif target in _TEST_MAP:
        test_path = str(_TESTS_DIR / _TEST_MAP[target])
        label = f"Test: {target}"
    elif target.endswith(".py"):
        # Direct file — check both tests/ and tools/
        if (_TESTS_DIR / target).exists():
            test_path = str(_TESTS_DIR / target)
        elif (_TOOLS_DIR / target).exists():
            test_path = str(_TOOLS_DIR / target)
        else:
            await ws.send_json({"type": "result", "success": False, "ts": now,
                                "text": f"Test file not found: {target}\n"
                                        f"Available: {', '.join(_TEST_MAP.keys())}"})
            return
        label = f"Test: {target}"
    else:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": f"Unknown test target: {target}\n"
                                    f"Available: all, {', '.join(_TEST_MAP.keys())}, <file.py>"})
        return

    # Check test file exists
    if not Path(test_path).exists():
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": f"Test path not found: {test_path}"})
        return

    cmd = [_PYTHON, "-m", "pytest", test_path, "-v", "--tb=short", "--no-header", "-q"]
    await _run_script(ws, cmd, label, cwd=str(_REPO_DIR), timeout=300)


# ── Recon commands ───────────────────────────────────────────────────

_RECON_SCRIPTS = {
    "tgsv8":     ("scripts/Joystick/tools/tgsv8_recon.py",       "TGSv8 Recon"),
    "arb":       ("scripts/scan_lau_arb.py",                      "QING Arb Scanner (272 venues)"),
    "beat":      ("scripts/recon_beat.py",                         "Beat Prerequisites"),
    "players":   ("scripts/recon_players.py",                      "Player Scanner"),
    "crows":     ("scripts/recon_crows.py",                        "CROWS Recon"),
    "shio":      ("scripts/recon_shio.py",                         "SHIO Acquisition Recon"),
    "aff":       ("scripts/Joystick/tools/test_aff_wm_cycle.py",  "AFF + WM Profitability"),
    "void":      ("scripts/recon_void.py",                         "VOID Active Users"),
    "fornax":    ("scripts/recon_fornax.py",                       "Fornax Whale Mapping"),
    "player":    ("scripts/recon_player.py",                       "Single Player Deep Scan"),
    "zuo":       ("scripts/recon_zuo.py",                          "ZUO Ownership"),
    "zurich":    ("scripts/recon_zurich.py",                       "Zurich Sources"),
}


async def _cmd_recon(ws: WebSocket, parts: list, now: float):
    """Run a recon script."""
    target = parts[1].lower() if len(parts) >= 2 else ""

    if target == "pairs":
        await _cmd_recon_pairs(ws, now)
        return

    if not target or target == "help":
        lines = ["──── RECON TARGETS ──────────────────"]
        for name, (script, label) in _RECON_SCRIPTS.items():
            exists = "✓" if (_REPO_DIR / script).exists() else "✗"
            lines.append(f"  {exists} {name:10s} — {label}")
        lines.append(f"  ✓ {'pairs':10s} — GIBS LP pair discovery")
        lines.append("─────────────────────────────────────")
        lines.append("Usage: recon <target>")
        await ws.send_json({"type": "result", "success": True, "ts": now, "text": "\n".join(lines)})
        return

    if target not in _RECON_SCRIPTS:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": f"Unknown recon target: {target}. Type 'recon help' for list."})
        return

    script, label = _RECON_SCRIPTS[target]
    script_path = _REPO_DIR / script

    if not script_path.exists():
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": f"Script not found: {script}"})
        return

    await _run_script(ws, [_PYTHON, str(script_path)], label, timeout=180)


async def _cmd_recon_pairs(ws: WebSocket, now: float):
    """Quick LP pair reserves check inline (no external script needed)."""
    await ws.send_json({"type": "system", "ts": now, "text": "▶ Scanning GIBS LP pairs..."})

    # Use the dashboard's own chain_reader for pair data
    script = '''
import json, sys
sys.path.insert(0, "{joystick}")
from web3 import Web3
import requests

RPC = "https://rpc-pulsechain.g4mm4.io"
GIBS = "0x66a08aa12da955eb63d7ac121a88b2b210a07b03"

FACTORIES = {{
    "V1": "0x1715a3E4A142d8b698131108995174F37aEBA10D",
    "V2": "0x29eA7545DEf87022BAdc76323F373EA1e707C523",
}}
TOKENS = {{
    "WPLS":   "0xA1077a294dDE1B09bB078844df40758a5D0f9a27",
    "FED":    "0x1d177cb9efeea49a8b97ab1c72785a3a37abc9ff",
    "PRVX":   "0xf6f8db0aba00007681f8faf16a0fda1c9b030b11",
    "ATROPA": "0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6",
    "WM":     "0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29",
    "VOID":   "0x965B0d74591bF30327075A247C47dBf487dCff08",
    "ZHENG":  "0xbF7E0181E5eB036C33e42D2Bd8133cb6Ce0f4837",
    "DFM":    "0x5fDbcD61bC9bd4B6D3FDeB3aF0AD7d0F28A96833",
    "PARADE": "0x6d53F435BAC02Dae3a4Fda6345dC070d3e2a87cf",
    "TLRz":   "0x2CBada1260e1F62e012f6F5b2fD8E2a53F37aab2",
}}

def eth_call(to, data):
    r = requests.post(RPC, json={{"jsonrpc":"2.0","method":"eth_call","params":[{{"to":to,"data":data}},"latest"],"id":1}})
    return json.loads(r.text).get("result","0x")

def get_pair(factory, t0, t1):
    sel = "0xe6a43905"
    data = sel + t0[2:].lower().zfill(64) + t1[2:].lower().zfill(64)
    res = eth_call(factory, data)
    if len(res) < 66: return None
    addr = "0x" + res[-40:]
    return addr if addr != "0x" + "0"*40 else None

def get_reserves(pair):
    res = eth_call(pair, "0x0902f1ac")
    if len(res) < 194: return (0, 0)
    r0 = int(res[2:66], 16)
    r1 = int(res[66:130], 16)
    return (r0, r1)

def token0(pair):
    res = eth_call(pair, "0x0dfe1681")
    if len(res) < 42: return ""
    return "0x" + res[-40:]

# Scan all pairs
results = []
for name, addr in TOKENS.items():
    for dex, factory in FACTORIES.items():
        pair = get_pair(factory, GIBS, addr)
        if not pair:
            continue
        r0, r1 = get_reserves(pair)
        if r0 == 0 and r1 == 0:
            results.append(f"  {{name:10s}} {{dex}}  EMPTY")
            continue
        t0 = token0(pair)
        if t0.lower() == GIBS.lower():
            gibs_r, other_r = r0 / 1e18, r1 / 1e18
        else:
            gibs_r, other_r = r1 / 1e18, r0 / 1e18
        health = "HEALTHY" if gibs_r >= 5 else ("THIN" if gibs_r > 0 else "EMPTY")
        results.append(f"  {{name:10s}} {{dex}}  GIBS: {{gibs_r:>10,.2f}}  {{name}}: {{other_r:>14,.2f}}  [{{health}}]")

print("──── GIBS LP PAIRS ──────────────────────────────────────────────")
print(f"  {{\"Token\":10s}} DEX  {{\"GIBS Reserve\":>14s}}  {{\"Partner Reserve\":>16s}}  Status")
print("  " + "─" * 65)
for r in results:
    print(r)
print("─────────────────────────────────────────────────────────────────")
'''.format(joystick=str(_JOYSTICK_DIR))

    cmd = [_PYTHON, "-c", script]
    await _run_script(ws, cmd, "GIBS LP Pairs", timeout=60)


# ── Run arbitrary script ─────────────────────────────────────────────

async def _cmd_run(ws: WebSocket, parts: list, now: float):
    """Run a Python script from the scripts/ directory."""
    if len(parts) < 2:
        # List available scripts
        scripts = []
        for f in sorted(_SCRIPTS_DIR.glob("*.py")):
            scripts.append(f"  {f.name}")
        for f in sorted(_TOOLS_DIR.glob("*.py")):
            scripts.append(f"  tools/{f.name}")
        text = "──── AVAILABLE SCRIPTS ──────────────\n"
        text += "\n".join(scripts[:30])
        if len(scripts) > 30:
            text += f"\n  ... and {len(scripts) - 30} more"
        text += "\n─────────────────────────────────────"
        text += "\nUsage: run <script.py>"
        await ws.send_json({"type": "result", "success": True, "ts": now, "text": text})
        return

    script_name = parts[1]

    # Resolve script path — check multiple locations
    candidates = [
        _SCRIPTS_DIR / script_name,
        _TOOLS_DIR / script_name,
        _JOYSTICK_DIR / script_name,
    ]
    # Also handle "tools/foo.py" prefix
    if script_name.startswith("tools/"):
        candidates.insert(0, _TOOLS_DIR / script_name[6:])

    script_path = None
    for c in candidates:
        if c.exists() and c.suffix == ".py":
            script_path = c
            break

    if not script_path:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": f"Script not found: {script_name}\nType 'run' to list available scripts."})
        return

    # Extra args after the script name
    extra_args = parts[2:] if len(parts) > 2 else []
    cmd = [_PYTHON, str(script_path)] + extra_args
    label = f"Script: {script_path.name}"
    await _run_script(ws, cmd, label, timeout=180)


# ── Process management ───────────────────────────────────────────────

async def _cmd_ps(ws: WebSocket, now: float):
    """Show running background processes."""
    if not _bg_processes:
        await ws.send_json({"type": "result", "success": True, "ts": now,
                            "text": "No background jobs running."})
        return

    lines = ["──── BACKGROUND JOBS ────────────────"]
    dead = []
    for name, proc in _bg_processes.items():
        if proc.poll() is None:
            lines.append(f"  {name:20s} PID {proc.pid}  RUNNING")
        else:
            lines.append(f"  {name:20s} PID {proc.pid}  EXITED ({proc.returncode})")
            dead.append(name)
    lines.append("─────────────────────────────────────")
    # Clean up dead processes
    for name in dead:
        del _bg_processes[name]
    await ws.send_json({"type": "result", "success": True, "ts": now, "text": "\n".join(lines)})


async def _cmd_kill(ws: WebSocket, parts: list, now: float):
    """Kill a background job."""
    if len(parts) < 2:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": "Usage: kill <job_name>. Type 'ps' to list jobs."})
        return

    name = parts[1]
    proc = _bg_processes.get(name)
    if not proc:
        await ws.send_json({"type": "result", "success": False, "ts": now,
                            "text": f"No job named '{name}'. Type 'ps' to list."})
        return

    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    del _bg_processes[name]
    await ws.send_json({"type": "result", "success": True, "ts": now,
                        "text": f"✓ Killed job: {name}"})
