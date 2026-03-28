"""
gas_oracle.py — Rolling-window gas price tracker with trend detection.

Polls eth_gasPrice each bot cycle and maintains a sliding window of
the last N readings. Exposes current(), average(), trend(), and
should_wait() for engines to make gas-timing decisions.


PulseChain gas context:
  - Gas is denominated in Beats (not Gwei), but eth_gasPrice returns
    Impulses (wei-equivalent), same as Ethereum.
  - Typical PulseChain gas prices: 500K-2M Beats range, and 100's of Millions to Billions during heavy use.
  - PLS is very cheap (~$0.00001), so even "high" gas in Beats terms
    translates to fractions of a cent. The ceiling is about preventing
    runaway costs during chain congestion, not about saving pennies.

Usage:
    oracle = GasOracle()
    oracle.update()              # call once per bot cycle
    price = oracle.current()     # latest gas price in wei
    avg   = oracle.average()     # rolling average in wei
    trend = oracle.trend()       # "rising" | "falling" | "stable"
    wait  = oracle.should_wait() # True if trend is falling (save gas)
    cost  = oracle.estimate_tx_cost_pls(gas_units)  # PLS cost estimate
"""
import time
import logging

from .log_names import get_logger
from collections import deque
from decimal import Decimal

from .chain import w3_read
from .config import GAS_PRICE_CEIL, MEMPOOL_CACHE_SECONDS

log = get_logger(__name__)

# Rolling window: 20 readings × 30s cycle = ~10 minutes of history
WINDOW_SIZE = 20

# Trend thresholds: if latest is >5% above/below average, it's trending
TREND_THRESHOLD = 0.05


class GasOracle:
    """
    Stateful gas price tracker. One instance lives in DysnomiaBot,
    updated once per cycle via update(). All methods are read-only
    after update() except update() itself.
    """

    def __init__(self, window_size: int = WINDOW_SIZE):
        self._window: deque[int] = deque(maxlen=window_size)
        self._timestamps: deque[float] = deque(maxlen=window_size)
        self._last_price: int = 0
        self._mempool_data: dict | None = None
        self._mempool_ts: float = 0.0

    def update(self) -> int:
        """
        Poll eth_gasPrice and add to rolling window.
        Call once per bot cycle. Returns current gas price in wei.
        """
        try:
            price = w3_read.eth.gas_price
        except Exception as exc:
            log.warning("GasOracle: eth_gasPrice failed (%s), using last known", exc)
            price = self._last_price or 1_000_000 * 10**9  # 1M Beats fallback

        self._window.append(price)
        self._timestamps.append(time.time())
        self._last_price = price

        # Sample pending block (best-effort)
        now = time.time()
        if now - self._mempool_ts >= MEMPOOL_CACHE_SECONDS:
            mempool = self._sample_pending_block()
            if mempool:
                self._mempool_data = mempool
                self._mempool_ts = now

        log.debug(
            "⛽ GasOracle: %.0f Beats (avg=%.0f, trend=%s, window=%d)",
            price / 1e9, self.average() / 1e9, self.trend(), len(self._window),
        )
        return price

    def current(self) -> int:
        """Latest gas price in wei. 0 if no readings yet."""
        return self._last_price

    def current_beats(self) -> float:
        """Latest gas price in Beats (human-readable)."""
        return self._last_price / 1e9

    # Keep alias for backward compat
    current_gwei = current_beats

    def average(self) -> int:
        """Rolling average gas price in wei."""
        if not self._window:
            return 0
        return sum(self._window) // len(self._window)

    def average_beats(self) -> float:
        """Rolling average in Beats."""
        return self.average() / 1e9

    # Keep alias for backward compat
    average_gwei = average_beats

    def trend(self) -> str:
        """
        Gas price trend: "rising", "falling", or "stable".
        Based on comparing latest price to rolling average.
        Needs at least 3 readings to be meaningful.
        """
        if len(self._window) < 3:
            return "stable"  # Not enough data

        avg = self.average()
        if avg == 0:
            return "stable"

        ratio = self._last_price / avg
        if ratio > (1 + TREND_THRESHOLD):
            return "rising"
        elif ratio < (1 - TREND_THRESHOLD):
            return "falling"
        return "stable"

    def should_wait(self) -> bool:
        """
        Returns True if gas is actively falling — engines should delay
        non-urgent operations by one cycle to get a better price.
        Does NOT apply to time-sensitive arbs (those should execute immediately).
        """
        return self.trend() == "falling"

    def is_above_ceiling(self) -> bool:
        """True if current gas price exceeds GAS_PRICE_CEIL."""
        return self._last_price > GAS_PRICE_CEIL

    def estimate_tx_cost_pls(self, gas_units: int) -> Decimal:
        """
        Estimate PLS cost for a TX using current gas price.
        Uses Decimal for precision (same pattern as wm_minter.py).
        """
        return Decimal(gas_units * self._last_price) / Decimal(10**18)

    def estimate_tx_cost_pls_avg(self, gas_units: int) -> Decimal:
        """Same but using rolling average — useful for ROI projections."""
        return Decimal(gas_units * self.average()) / Decimal(10**18)

    # ── Mempool gas sampling ────────────────────────────────────────────────

    def _sample_pending_block(self) -> dict | None:
        """
        Read the pending block's transactions and compute gas price percentiles.

        Returns percentile dict or None if pending block unavailable.
        """
        try:
            block = w3_read.eth.get_block('pending', full_transactions=True)
        except Exception:
            log.debug("GasOracle: pending block not available from RPC")
            return None

        txs = block.get("transactions", [])
        if not txs:
            return None

        prices = []
        for tx in txs:
            if isinstance(tx, dict):
                # Prefer maxFeePerGas (EIP-1559), fall back to gasPrice
                gp = tx.get("maxFeePerGas") or tx.get("gasPrice", 0)
                if gp and gp > 0:
                    prices.append(gp)

        if not prices:
            return None

        prices.sort()
        n = len(prices)

        def percentile(p):
            idx = min(int(n * p / 100), n - 1)
            return prices[idx]

        return {
            "p10": percentile(10),
            "p25": percentile(25),
            "p50": percentile(50),
            "p70": percentile(70),
            "p80": percentile(80),
            "p90": percentile(90),
            "tx_count": n,
            "timestamp": time.time(),
        }

    def mempool_price(self, speed: str = "standard") -> int | None:
        """Get mempool-derived gas price. speed: 'slow'|'standard'|'fast'|'rapid'."""
        if not self._mempool_data:
            return None
        mapping = {"slow": "p25", "standard": "p50", "fast": "p70", "rapid": "p80"}
        return self._mempool_data.get(mapping.get(speed, "p50"))

    def recommended_gas_price(self) -> int:
        """Best available gas price: mempool p50 if available, else eth_gasPrice."""
        mp = self.mempool_price("standard")
        return mp if mp else self._last_price

    def status(self) -> dict:
        """Full status dict for logging / --status display."""
        s = {
            "current_beats":    self.current_beats(),
            "average_beats":    self.average_beats(),
            "trend":           self.trend(),
            "should_wait":     self.should_wait(),
            "above_ceiling":   self.is_above_ceiling(),
            "ceiling_beats":    GAS_PRICE_CEIL / 1e9,
            "window_size":     len(self._window),
            "window_max_beats": max(self._window) / 1e9 if self._window else 0,
            "window_min_beats": min(self._window) / 1e9 if self._window else 0,
        }
        if self._mempool_data:
            s["mempool_p50"] = self._mempool_data.get("p50", 0) / 1e9
            s["mempool_tx_count"] = self._mempool_data.get("tx_count", 0)
        return s

    def __repr__(self) -> str:
        s = self.status()
        return (
            f"GasOracle(current={s['current_beats']:.0f} Beats, "
            f"avg={s['average_beats']:.0f}, trend={s['trend']}, "
            f"wait={s['should_wait']})"
        )
