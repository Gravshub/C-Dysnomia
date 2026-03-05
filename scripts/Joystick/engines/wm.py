"""
wm.py — Engine 3: TGSv5 WM Batch Minting

Thin wrapper around agent/wm_minter.py WMMinter class.
WM is required to deploy new V2/V4 tokens → feeds the token-creation arb pipeline.

WM itself is not sold immediately — it's accumulated as collateral for new token
deployments. The engine is profitable when WM DEX price > gas cost per mint.

is_ready():  TGSV5_ADDRESS set in env AND contract not paused AND caller authorized
simulate():  WMMinter.check_profitable(10) → (value_pls, gas_cost_pls)
execute():   WMMinter.run_auto() → batch mint 10 or 5 WM
"""
import sys
import os
import logging
from decimal import Decimal

from .base import EngineBase, EngineResult
from ..core.config import TGSV5
from ..core.simulator import SimulationFailed

log = logging.getLogger(__name__)


def _load_wm_minter():
    """Lazy import WMMinter from agent/wm_minter.py (sibling of scripts/)."""
    agent_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "agent")
    agent_dir = os.path.normpath(agent_dir)
    if agent_dir not in sys.path:
        sys.path.insert(0, agent_dir)
    try:
        from wm_minter import WMMinter
        return WMMinter
    except ImportError as exc:
        raise ImportError(f"Cannot import WMMinter from {agent_dir}: {exc}") from exc


class WMEngine(EngineBase):
    """
    Engine 3: Batch-mint WM tokens via TGSv5 when economically profitable.
    WM is accumulated for new token deployments (not sold directly).
    """
    name = "WM"

    def __init__(self):
        super().__init__()
        self._minter = None

    def _get_minter(self):
        if self._minter is not None:
            return self._minter
        if not TGSV5:
            return None
        try:
            WMMinter = _load_wm_minter()
            key = os.getenv("DYSNOMIA_PRIVATE_KEY", "")
            rpc = os.getenv("PULSECHAIN_RPC", "https://rpc.pulsechain.com")
            self._minter = WMMinter(rpc, TGSV5, key)
            return self._minter
        except Exception as exc:
            log.debug("WMEngine: minter init failed: %s", exc)
            return None

    def is_ready(self) -> bool:
        if not TGSV5:
            log.debug("WMEngine not ready: TGSV5_ADDRESS not set")
            return False
        minter = self._get_minter()
        if minter is None:
            return False
        try:
            return minter.preflight()
        except Exception as exc:
            log.debug("WMEngine preflight failed: %s", exc)
            return False

    def simulate(self) -> tuple[int, int]:
        """
        Returns (value_of_10_wm_in_pls_wei, gas_cost_wei).
        Profitable = value > cost.
        """
        minter = self._get_minter()
        if minter is None:
            raise SimulationFailed("WMMinter not available — check TGSV5_ADDRESS and key")

        profitable, cost, value = minter.check_profitable(10)
        cost_wei  = int(cost  * Decimal(10**18))
        value_wei = int(value * Decimal(10**18))

        if not profitable:
            raise SimulationFailed(
                f"WM mint unprofitable: value={float(value):.6f} PLS <= cost={float(cost):.6f} PLS"
            )
        return value_wei, cost_wei

    def execute(self, dry_run: bool = False) -> EngineResult:
        """Batch-mint WM. Returns EngineResult with tx_hash from WMMinter."""
        minter = self._get_minter()
        if minter is None:
            return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                notes="WMMinter unavailable")

        try:
            value_wei, cost_wei = self.simulate()
        except SimulationFailed as exc:
            return EngineResult(success=False, profit_wei=0, gas_wei=0, notes=str(exc))

        if dry_run:
            log.info("[dry-run] WM mint: would mint, profit %.4f PLS", (value_wei - cost_wei) / 1e18)
            return EngineResult(success=True, profit_wei=value_wei, gas_wei=cost_wei,
                                notes="dry-run")

        try:
            tx_hash = minter.run_auto()
            if tx_hash is None:
                return EngineResult(success=False, profit_wei=0, gas_wei=0,
                                    notes="WMMinter.run_auto() returned None")

            log.info("WM mint complete: tx=%s", tx_hash)
            return EngineResult(
                success=True,
                profit_wei=value_wei,
                gas_wei=cost_wei,
                tx_hashes=[tx_hash],
                notes="WM batch minted",
            )
        except Exception as exc:
            log.error("WMEngine execute failed: %s", exc)
            return EngineResult(success=False, profit_wei=0, gas_wei=0, notes=str(exc))
