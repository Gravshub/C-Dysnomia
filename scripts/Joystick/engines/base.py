"""
base.py — EngineBase and EngineResult abstractions.

Every engine (arb, dss, wm, beat) inherits from EngineBase and implements:
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
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


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
        Examples: SHIO balances present, GIBS pair exists, TGSv5 deployed.
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

    def record_failure(self) -> None:
        """Increment failure counter; trip circuit breaker if at limit."""
        self.failure_count += 1
        if self.failure_count >= self.MAX_FAILURES:
            self._disabled_at = time.time()
            log.warning(
                "%s: circuit breaker TRIPPED (%d/%d failures) — disabled for %ds",
                self.name, self.failure_count, self.MAX_FAILURES, self.DISABLE_SECS,
            )

    def status_line(self) -> str:
        """One-line engine status for logging."""
        state = "DISABLED" if self.is_disabled() else ("READY" if self.is_ready() else "NOT READY")
        return f"{self.name}: {state} (failures={self.failure_count})"
