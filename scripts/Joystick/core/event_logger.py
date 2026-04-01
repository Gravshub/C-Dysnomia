"""
event_logger.py — Structured JSON event logger for all Joystick bot activity.

Every engine action, cycle, balance snapshot, error, and TX gets logged
to timestamped JSON files under scripts/Joystick/data/events/.

File layout:
  data/events/joystick_events.jsonl    — all events (append-only JSONL)
  data/events/engine_lau.jsonl         — LAU engine events only
  data/events/engine_arb.jsonl         — Arb engine events only
  data/events/engine_<name>.jsonl      — per-engine event logs
  data/events/cycles.jsonl             — cycle-level summaries

Each event is a single JSON line with:
  {
    "ts":        "2026-03-05T14:23:01.123456Z",  # ISO-8601 UTC
    "epoch":     1741187381.123456,                # Unix timestamp
    "event":     "engine.lau.step",                # dot-delimited event type
    "engine":    "LAU",                            # engine name (if applicable)
    "block":     25943266,                         # chain block number
    "data":      { ... },                          # event-specific payload
    "tx_hash":   "0xabc...",                       # TX hash (if applicable)
    "success":   true,                             # operation outcome
    "gas_used":  123456,                           # gas consumed (if TX)
    "gas_price": 1000000000,                       # gas price wei (if TX)
    "pls_cost":  0.000123,                         # PLS cost (if TX)
    "notes":     "Alpha arg=12345"                 # human-readable notes
  }

Usage from any engine:
    from ..core.event_logger import events

    events.log("engine.lau.step", engine="LAU", data={"step": "Alpha", "arg": 123})
    events.log_tx("engine.lau.step", engine="LAU", receipt=receipt, notes="Alpha done")
    events.log_cycle(cycle_num=5, balances=snap, engines_status=[...])
"""
import json
import logging

from .log_names import get_logger
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from web3.types import TxReceipt

log = get_logger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────
_JOYSTICK_DIR = Path(__file__).parent.parent
_EVENTS_DIR = _JOYSTICK_DIR / "data" / "events"


def _ensure_dirs() -> None:
    _EVENTS_DIR.mkdir(parents=True, exist_ok=True)


class EventLogger:
    """
    Append-only JSONL event logger with per-engine file routing.

    Thread-safe — uses a lock around file writes.
    """

    def __init__(self) -> None:
        _ensure_dirs()
        self._lock = threading.Lock()
        self._handles: dict[str, Any] = {}  # path -> file handle cache

    # ── Core log method ──────────────────────────────────────────────────────

    def log(
        self,
        event: str,
        *,
        engine: str = "",
        data: dict | None = None,
        tx_hash: str = "",
        success: bool = True,
        gas_used: int = 0,
        gas_price: int = 0,
        block: int = 0,
        notes: str = "",
    ) -> dict:
        """
        Write a structured event to the global log and per-engine log.
        Returns the event dict for further processing.
        """
        now = datetime.now(timezone.utc)
        pls_cost = (gas_used * gas_price / 1e18) if gas_used and gas_price else 0.0

        record = {
            "ts": now.isoformat(),
            "epoch": now.timestamp(),
            "event": event,
            "engine": engine,
            "block": block,
            "data": data or {},
            "tx_hash": tx_hash,
            "success": success,
            "gas_used": gas_used,
            "gas_price": gas_price,
            "pls_cost": round(pls_cost, 6),
            "notes": notes,
        }

        # Strip None fields for compactness (keep empty strings, 0, False)
        record = {k: v for k, v in record.items() if v is not None}

        self._write("joystick_events", record)

        # Per-engine log
        if engine:
            engine_file = f"engine_{engine.lower()}"
            self._write(engine_file, record)

        return record

    # ── Convenience methods ──────────────────────────────────────────────────

    def log_tx(
        self,
        event: str,
        *,
        engine: str = "",
        receipt: TxReceipt | None = None,
        data: dict | None = None,
        notes: str = "",
        success: bool = True,
    ) -> dict:
        """Log an event with TX receipt data extracted automatically."""
        tx_hash = ""
        gas_used = 0
        gas_price = 0
        block = 0

        if receipt:
            tx_hash = receipt.get("transactionHash", b"").hex() if receipt.get("transactionHash") else ""
            if tx_hash and not tx_hash.startswith("0x"):
                tx_hash = "0x" + tx_hash
            gas_used = receipt.get("gasUsed", 0)
            gas_price = receipt.get("effectiveGasPrice", 0)
            block = receipt.get("blockNumber", 0)
            success = receipt.get("status", 0) == 1

        return self.log(
            event,
            engine=engine,
            data=data,
            tx_hash=tx_hash,
            success=success,
            gas_used=gas_used,
            gas_price=gas_price,
            block=block,
            notes=notes,
        )

    def log_cycle(
        self,
        cycle_num: int,
        balances: dict | None = None,
        engines_status: list[str] | None = None,
        engine_ran: str = "",
        result_notes: str = "",
        success: bool = True,
    ) -> dict:
        """Log a cycle-level summary."""
        data = {
            "cycle": cycle_num,
            "balances": _sanitize_balances(balances) if balances else {},
            "engines_status": engines_status or [],
            "engine_ran": engine_ran,
        }

        record = self.log(
            "bot.cycle",
            data=data,
            success=success,
            notes=result_notes,
        )

        # Also write to dedicated cycles file
        self._write("cycles", record)
        return record

    def log_engine_result(
        self,
        engine: str,
        result,  # EngineResult
        cycle_num: int = 0,
    ) -> dict:
        """Log the outcome of an engine execution."""
        data = {
            "cycle": cycle_num,
            "profit_pls": round(result.profit_wei / 1e18, 6) if result.profit_wei else 0,
            "gas_pls": round(result.gas_wei / 1e18, 6) if result.gas_wei else 0,
            "net_pls": round((result.profit_wei - result.gas_wei) / 1e18, 6),
            "tx_count": len(result.tx_hashes),
            "tx_hashes": result.tx_hashes,
        }
        return self.log(
            f"engine.{engine.lower()}.result",
            engine=engine,
            data=data,
            success=result.success,
            notes=result.notes,
        )

    def log_error(
        self,
        event: str,
        error: str,
        *,
        engine: str = "",
        data: dict | None = None,
    ) -> dict:
        """Log an error event."""
        return self.log(
            event,
            engine=engine,
            data={**(data or {}), "error": error},
            success=False,
            notes=f"ERROR: {error}",
        )

    def log_balance_snapshot(self, balances: dict, block: int = 0) -> dict:
        """Log a balance snapshot."""
        return self.log(
            "bot.balances",
            data=_sanitize_balances(balances),
            block=block,
        )

    # ── File I/O ─────────────────────────────────────────────────────────────

    def _write(self, name: str, record: dict) -> None:
        """Append a JSON line to the named log file."""
        path = _EVENTS_DIR / f"{name}.jsonl"
        line = json.dumps(record, default=str, separators=(",", ":")) + "\n"

        with self._lock:
            try:
                with open(path, "a") as f:
                    f.write(line)
            except Exception as e:
                log.error("EventLogger write failed (%s): %s", path, e)

    def flush(self) -> None:
        """Flush all open file handles (no-op for append mode)."""
        pass

    # ── Read utilities ───────────────────────────────────────────────────────

    @staticmethod
    def read_events(name: str = "joystick_events", last_n: int = 0) -> list[dict]:
        """Read events from a JSONL log file. If last_n > 0, return only the last N."""
        path = _EVENTS_DIR / f"{name}.jsonl"
        if not path.exists():
            return []

        events = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        if last_n > 0:
            return events[-last_n:]
        return events

    @staticmethod
    def event_count(name: str = "joystick_events") -> int:
        """Count events in a JSONL log file."""
        path = _EVENTS_DIR / f"{name}.jsonl"
        if not path.exists():
            return 0
        count = 0
        with open(path) as f:
            for line in f:
                if line.strip():
                    count += 1
        return count


def _sanitize_balances(balances: dict) -> dict:
    """Convert wei balances to human-readable PLS values for logging."""
    out = {}
    for k, v in balances.items():
        if isinstance(v, int) and v > 10**15:
            out[k] = round(v / 1e18, 6)
        else:
            out[k] = v
    return out


# ── Module-level singleton ────────────────────────────────────────────────────
events = EventLogger()
