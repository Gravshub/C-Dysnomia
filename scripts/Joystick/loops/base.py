"""
loops/base.py — GameLoopBase: abstract base for all gameplay loops.

Gameplay loops differ from engines:
  - Engines: generate direct PLS profit (arb, mint, sell)
  - Loops:   perform game actions that build position (terraforming, venue chat, etc.)
             They may have indirect profit (CHOA tokens, territory score) but not
             direct PLS return per call.

To add a new gameplay loop:
  1. Create scripts/Joystick/loops/my_loop.py
  2. class MyLoop(GameLoopBase): implement should_run() and run()
  3. Register in bot.py: self.loops.append(MyLoop())
  Zero changes to core/ or any engine required.
"""
import logging

from ..core.log_names import get_logger
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

log = get_logger(__name__)


@dataclass
class LoopResult:
    success:   bool
    tx_hashes: list[str] = field(default_factory=list)
    notes:     str = ""


class GameLoopBase(ABC):
    """
    Abstract base for gameplay loops.

    Subclasses implement:
      should_run() — check game conditions (read-only)
      run()        — execute one loop iteration
    """
    name: str = "UnnamedLoop"
    # Approximate PLS gas cost per run — checked against GasGuard before running
    pls_cost_per_run: int = 1_000 * 10**18
    # Minimum seconds between runs (rate-limit self-imposed)
    min_interval_secs: int = 0

    def __init__(self):
        self._last_run: float = 0.0

    @abstractmethod
    def should_run(self) -> bool:
        """
        Check if game conditions are met to run this loop.
        Read-only — no TXs. Return False to skip this cycle without error.
        """

    @abstractmethod
    def run(self, dry_run: bool = False) -> LoopResult:
        """Execute one iteration of the loop."""

    def is_throttled(self) -> bool:
        """True if min_interval_secs has not elapsed since last run."""
        if self.min_interval_secs <= 0:
            return False
        elapsed = time.time() - self._last_run
        return elapsed < self.min_interval_secs

    def record_run(self) -> None:
        self._last_run = time.time()

    def status_line(self) -> str:
        elapsed = time.time() - self._last_run
        throttled = self.is_throttled()
        return (
            f"{self.name}: {'THROTTLED' if throttled else 'READY'} "
            f"(last_run={elapsed:.0f}s ago)"
        )
