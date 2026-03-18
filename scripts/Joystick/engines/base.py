"""
base.py — EngineBase, EngineResult, and SimResult abstractions.

Every engine (arb, dss, beat, token_factory, lau, treasury_sniper, spine_runner, phreak)
inherits from EngineBase and implements:
  is_ready()  — prerequisite check, read-only, no TX
  simulate()  — (expected_profit_wei, expected_gas_wei) via eth_call
  execute()   — full TX sequence, returns EngineResult

The orchestrator (bot.py) calls simulate() to rank engines by ROI,
then calls execute() only on the top-ranked profitable engine per cycle.

Circuit breaker: failure_count increments on each execute() failure.
After MAX_FAILURES consecutive failures the engine is disabled until
the bot is restarted (prevents endless retry loops on broken conditions).
"""
import logging

from ..core.log_names import get_logger
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..core.event_logger import events as _events

log = get_logger(__name__)

# ── Display name mapping ──────────────────────────────────────────────────────
ENGINE_DISPLAY_NAMES: dict[str, str] = {
    "Arb":            "E1 RAZOR",
    "DSS":            "E2 CEREAL",
    "Beat":           "E3 MERIDIAN",
    "TokenFactory":   "E4 FACTORY",
    "LAU":            "E5 ABUPRU",
    "TreasurySniper": "E6 DaVINCI",
    "SpineRunner":    "E7 BACKBONE",
    "PHR3AK":         "E8 PHR3AK",
}

# ── Default wallet role mapping ───────────────────────────────────────────────
ENGINE_WALLET_ROLES: dict[str, str] = {
    "Arb":            "seller",
    "DSS":            "joey",
    "Beat":           "joey",
    "TokenFactory":   "minter",
    "LAU":            "joey",
    "TreasurySniper": "minter",
    "SpineRunner":    "minter",
    "PHR3AK":         "minter",
}


@dataclass
class SimResult:
    """Structured simulation result from an engine."""
    success:          bool   = True
    profit_wei:       int    = 0
    gas_wei:          int    = 0
    pool_impact_pct:  float  = 0.0
    mode:             str    = ""         # e.g. "arm", "deploy", "stitch"
    confidence:       float  = 1.0        # engine self-assessed 0.0-1.0
    notes:            str    = ""
    wallet_role:      str    = ""         # "joey" | "minter" | "seller"

    @property
    def roi(self) -> float:
        return self.profit_wei / self.gas_wei if self.gas_wei > 0 else 0.0

    @staticmethod
    def failed(reason: str) -> "SimResult":
        return SimResult(success=False, notes=reason)


@dataclass
class EngineResult:
    success:    bool
    profit_wei: int        # Actual PLS gained in wei (parsed from TX events)
    gas_wei:    int        # Actual gas spent in wei
    tx_hashes:  list[str] = field(default_factory=list)
    notes:      str = ""

    @property
    def profit_pls(self) -> float:
        return self.profit_wei / 1e18

    @property
    def gas_pls(self) -> float:
        return self.gas_wei / 1e18

    @property
    def net_pls(self) -> float:
        return (self.profit_wei - self.gas_wei) / 1e18


class EngineBase(ABC):
    """
    Abstract base for all Joystick income engines.

    Subclasses must implement is_ready(), simulate(), execute().
    All other behaviour (circuit breaker, ROI ranking) is provided here.
    """
    name: str = "UnnamedEngine"
    MAX_FAILURES: int = 3      # Disable after this many consecutive failures
    DISABLE_SECS: int = 600    # Re-enable after 10 minutes (0 = never auto-re-enable)

    def __init__(self):
        self.failure_count: int = 0
        self._disabled_at: float = 0.0

    # ── Abstract interface ────────────────────────────────────────────────────

    @abstractmethod
    def is_ready(self) -> bool:
        """
        Prerequisite check. Read-only (no TXs).
        Return False to skip this engine this cycle without counting as a failure.
        Examples: SHIO balances present, GIBS pair exists, TGSv8 wired.
        """

    @abstractmethod
    def simulate(self) -> tuple[int, int]:
        """
        Estimate (expected_profit_wei, expected_gas_wei) using eth_call only.
        Both values in wei. No TX sent.
        Raise SimulationFailed if the TX would revert.
        """

    @abstractmethod
    def execute(self, dry_run: bool = False) -> EngineResult:
        """
        Execute the engine's TX sequence.
        Must call simulate() internally before sending TXs.
        Returns EngineResult. Never raise — catch internally and return success=False.
        """

    # ── Provided behaviour ────────────────────────────────────────────────────

    def roi(self) -> float:
        """
        Simulated return-on-investment ratio: profit / gas.
        Returns 0.0 on any error (engine will be skipped but not penalised).
        """
        try:
            profit, gas = self.simulate()
            return profit / gas if gas > 0 else 0.0
        except Exception as exc:
            log.debug("%s.roi() failed: %s", self.name, exc)
            return 0.0

    def is_disabled(self) -> bool:
        """
        True if the circuit breaker has tripped.
        Auto-recovers after DISABLE_SECS if configured.
        """
        if self.failure_count < self.MAX_FAILURES:
            return False
        if self.DISABLE_SECS > 0:
            elapsed = time.time() - self._disabled_at
            if elapsed >= self.DISABLE_SECS:
                log.info("%s: circuit breaker reset after %.0fs cooldown", self.name, elapsed)
                self.failure_count = 0
                return False
        return True

    def record_success(self) -> None:
        """Reset failure counter after a successful execute()."""
        self.failure_count = 0
        _events.log(
            f"engine.{self.name.lower()}.success",
            engine=self.name,
            data={"failures_reset": True},
        )

    def record_failure(self) -> None:
        """Increment failure counter; trip circuit breaker if at limit."""
        self.failure_count += 1
        tripped = self.failure_count >= self.MAX_FAILURES
        if tripped:
            self._disabled_at = time.time()
            log.warning(
                "%s: circuit breaker TRIPPED (%d/%d failures) — disabled for %ds",
                self.name, self.failure_count, self.MAX_FAILURES, self.DISABLE_SECS,
            )
        _events.log(
            f"engine.{self.name.lower()}.failure",
            engine=self.name,
            success=False,
            data={
                "failure_count": self.failure_count,
                "max_failures": self.MAX_FAILURES,
                "circuit_breaker_tripped": tripped,
            },
        )

    @property
    def display_name(self) -> str:
        """Return E{N} {CODENAME} display name for this engine."""
        return ENGINE_DISPLAY_NAMES.get(self.name, self.name)

    @property
    def wallet_role(self) -> str:
        """Default wallet role for this engine's primary action."""
        return ENGINE_WALLET_ROLES.get(self.name, "joey")

    def sim_result(self) -> SimResult:
        """Normalize simulate() output to SimResult. Handles legacy tuple returns."""
        try:
            result = self.simulate()
            if isinstance(result, SimResult):
                return result
            profit, gas = result  # legacy (int, int) return
            return SimResult(
                profit_wei=profit,
                gas_wei=gas,
                wallet_role=self.wallet_role,
                pool_impact_pct=getattr(self, '_last_pool_impact_pct', 0.0),
            )
        except Exception as e:
            return SimResult.failed(str(e))

    def status_line(self) -> str:
        """One-line engine status for logging."""
        state = "DISABLED" if self.is_disabled() else ("READY" if self.is_ready() else "NOT READY")
        return f"{self.display_name} ({self.name}): {state} (failures={self.failure_count})"
