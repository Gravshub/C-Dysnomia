"""
concurrency.py — Async simulation executor + parallel wallet execution.

Layer 1: asyncio event loop coordinates the 3-wallet cycle.
Layer 2: ThreadPoolExecutor runs all 8 engines' simulate() concurrently
         (I/O-bound RPC calls). ~300ms parallel vs ~2.4s sequential.
Layer 3: Parallel wallet execution — each wallet's TX pipeline runs
         independently in its own thread with its own nonce counter.
"""
import asyncio
import logging

from .log_names import get_logger
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from ..engines.base import SimResult

if TYPE_CHECKING:
    from ..engines.base import EngineBase, EngineResult

log = get_logger(__name__)

# Default max workers for simulation (8 engines)
SIM_WORKERS = 8
# Default timeout per engine simulation in seconds
SIM_TIMEOUT = 5.0
# Per-engine timeout overrides (engines with heavy RPC loads need more time)
SIM_TIMEOUT_MAP: dict[str, float] = {
    "Arb": 15.0,
    "DSS": 15.0,                # ladder oracle + floor quote + sell route = ~8 RPC calls
    "TokenFactory": 15.0,       # 5 routes × 2 DEXes + WM = ~12 RPC calls
    "TreasurySniper": 10.0,     # 30+ RPC calls (direct V1+V2 quotes per target)
    "PHR3AK": 30.0,             # STITCH mode scans full token graph (14-22s)
}

# Engines with 200+ RPC calls per simulate() — skip when RPC pool is degraded
HEAVY_ENGINES = {"Arb", "TreasurySniper"}


class SimExecutor:
    """
    Parallel engine simulation via ThreadPoolExecutor.

    Usage:
        executor = SimExecutor()
        results = await executor.parallel_simulate(engines)
        # results: dict[str, SimResult]
        executor.shutdown()
    """

    def __init__(self, max_workers: int = SIM_WORKERS):
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sim")

    async def parallel_simulate(
        self,
        engines: list["EngineBase"],
    ) -> dict[str, SimResult]:
        """
        Run all ready, non-disabled engines' sim_result() in parallel.

        Returns dict mapping engine.name → SimResult.
        Failed/timed-out engines get SimResult.failed().
        """
        loop = asyncio.get_event_loop()
        t0 = time.monotonic()

        # Filter to eligible engines
        eligible = [e for e in engines if not e.is_disabled() and e.is_ready()]

        if not eligible:
            log.info("Parallel sim: 0/%d engines eligible", len(engines))
            return {}

        # RPC health gate: skip heavy engines when pool is degraded
        try:
            from .chain import get_read_pool
            healthy = get_read_pool().healthy_count()
            if healthy < 2:
                before = len(eligible)
                eligible = [e for e in eligible if e.name not in HEAVY_ENGINES]
                skipped = before - len(eligible)
                if skipped > 0:
                    log.warning(
                        "RPC degraded (%d/%d providers healthy) — skipping %d heavy engines (%s)",
                        healthy, 4, skipped, ", ".join(HEAVY_ENGINES),
                    )
        except Exception:
            pass  # Non-critical — proceed with all engines

        async def _run_one(engine: "EngineBase") -> tuple[str, SimResult]:
            timeout = SIM_TIMEOUT_MAP.get(engine.name, SIM_TIMEOUT)
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(self._pool, engine.sim_result),
                    timeout=timeout,
                )
                return engine.name, result
            except asyncio.TimeoutError:
                log.warning("⏰ %s simulation timed out (>%.1fs)", engine.name, timeout)
                return engine.name, SimResult.failed(f"Timeout after {timeout}s")
            except Exception as exc:
                log.warning("⚠️ %s simulation error: %s", engine.name, exc)
                return engine.name, SimResult.failed(str(exc))

        tasks = [_run_one(e) for e in eligible]
        completed = await asyncio.gather(*tasks)

        results = dict(completed)
        elapsed_ms = (time.monotonic() - t0) * 1000
        ok_count = sum(1 for r in results.values() if r.success)
        log.info(
            "Parallel sim: %d/%d engines in %.0fms (%d OK)",
            len(eligible), len(engines), elapsed_ms, ok_count,
        )
        return results

    async def execute_wallet_actions(
        self,
        actions: list[tuple["EngineBase", bool]],
    ) -> list["EngineResult"]:
        """
        Execute engine actions in parallel across wallets.

        actions: list of (engine, dry_run) tuples — one per wallet.
        Each wallet's TX pipeline is serial within itself, parallel across wallets.

        Returns list of EngineResult in same order as input.
        """
        loop = asyncio.get_event_loop()

        async def _exec_one(engine: "EngineBase", dry_run: bool) -> "EngineResult":
            return await loop.run_in_executor(
                self._pool, lambda: engine.execute(dry_run=dry_run)
            )

        tasks = [_exec_one(e, dr) for e, dr in actions]
        return await asyncio.gather(*tasks)

    def shutdown(self) -> None:
        """Clean shutdown of the thread pool."""
        self._pool.shutdown(wait=False)
        log.debug("SimExecutor pool shut down")
