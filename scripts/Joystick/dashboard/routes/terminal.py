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

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from .. import config

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
async def terminal_ws(ws: WebSocket):
    """
    WebSocket terminal.

    Server → Client messages:
      {"type": "log",    "text": "...", "ts": epoch}
      {"type": "system", "text": "...", "ts": epoch}
      {"type": "result", "text": "...", "ts": epoch, "success": bool}

    Client → Server messages:
      {"type": "command", "text": "..."}
    """
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
  engines            All 8 engines with status
  wallet             Joey wallet balances
  gas                Gas conditions
  tgsv8              TGSv8 contract state

 ── Bot Control ─────────────────────
  bot cycle          Dry-run one cycle (no TXs)
  bot cycle --live   Live-fire one cycle (real TXs!)
  bot status         Bot engine/strategist status
  bot wallet-status  3-wallet balances + auth + nonces
  bot rpc-status     RPC provider health check
  bot log-status     Event log statistics
  bot beat           Run Beat engine only (dry-run)
  bot beat --live    Run Beat engine only (live)
  bot lau            Run LAU engine only (dry-run)
  bot lau --live     Run LAU engine only (live)
  bot e4-test        Force E4 TokenFactory test cycle
  bot run            Start bot loop (background)
  bot stop           Stop background bot

 ── Logs ────────────────────────────
  logs [N]           Last N events (default 20)
  logs engine <name> Logs for specific engine
  tail               Toggle live log streaming

 ── Tests ───────────────────────────
  test               Run full test suite
  test anvil         Anvil fork integration tests
  test data          Data store tests
  test engines       Engine simulation tests
  test tgsv8         TGSv8+ contract tests
  test razor         RAZOR PulseChain tests
  test <file.py>     Run specific test file

 ── Recon (read-only) ───────────────
  recon tgsv8        TGSv8 deployment verification
  recon arb          Scan 272 QINGs for arb routes
  recon pairs        Discover GIBS LP pairs
  recon beat         Beat prerequisites check
  recon players      Active player scan

 ── Tools ───────────────────────────
  run <script.py>    Run a script from scripts/
  ps                 Show running background jobs
  kill <job>         Kill a background job

 ── Terminal ────────────────────────
  clear              Clear terminal
  help               This message
════════════════════════════════════════
""".strip()


async def _handle_command(ws: WebSocket, cmd: str):
    """Process a command from the terminal input."""
    now = time.time()

    parts = cmd.split()
    verb = parts[0].lower() if parts else ""

    try:
        # ── Help ──
        if verb in ("help", "?"):
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

        # ── Bot control ──
        elif verb == "bot":
            await _cmd_bot(ws, parts, now)

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
  bot beat           Beat engine (dry-run)
  bot beat --live    Beat engine (live)
  bot lau            LAU engine (dry-run)
  bot lau --live     LAU engine (live)
  bot e4-test        Force E4 test cycle
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

    elif sub in ("e4-test", "e4", "factory-test"):
        cmd = [_PYTHON, "-m", _BOT_MODULE, "--force-test", "--dry-run", "--once"]
        await _run_script(ws, cmd, "E4 TokenFactory Test", timeout=180)

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
    "tgsv8":   ("scripts/Joystick/tools/tgsv8_recon.py", "TGSv8 Recon"),
    "arb":     ("scripts/scan_lau_arb.py",                "QING Arb Scanner"),
    "beat":    ("scripts/beat_recon.py",                   "Beat Prerequisites"),
    "players": ("scripts/player_recon.py",                 "Player Scanner"),
    "crows":   ("scripts/crows_recon.py",                  "CROWS Recon"),
    "shio":    ("scripts/shio_acquisition_recon.py",       "SHIO Acquisition Recon"),
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
