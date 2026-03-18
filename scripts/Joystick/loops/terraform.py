"""
loops/terraform.py — CHOA.Chat terraforming loop.

⚠️  DISABLED — CHOA.Chat ABI mismatch causes revert every cycle.
    Registration commented out in bot.py. Do not re-enable until
    the correct CHOA ABI is confirmed on-chain.

Calls CHOA.Chat(QING, message) which:
  - Calls QING.Chat(UserToken, msg) to log the message
  - Calls CHAN.ReactYue → CHOA._mintToCap() → mints 1 CHOA token
  - Calls MAI.React()
  → Costs ~700K gas (~1,469 PLS at current prices)
  → Mints 1 CHOA token + 1 venue QING token per call

This is a gameplay action, not a direct profit engine. It builds territorial
presence and earns CHOA tokens which may be valuable as game-layer assets.

Template for adding new gameplay loops — copy/adapt this file.
"""
import logging

from ..core.log_names import get_logger
import time

from web3 import Web3

from .base import GameLoopBase, LoopResult
from ..core.config import (
    JOEY_WALLET, CHOA, GIBS_LAU, PLS_GAS_FLOOR,
)
from ..core.chain import w3_submit, safe
from ..core.executor import send_tx
from ..core.simulator import SimulationFailed
from ..core.wallet import pls_balance

log = get_logger(__name__)

# CHOA contract ABI — Chat(address QingAddr, string message)
CHOA_ABI = [
    {"inputs": [
        {"name": "Qing", "type": "address"},
        {"name": "_text", "type": "string"},
    ], "name": "Chat",
     "outputs": [], "stateMutability": "nonpayable", "type": "function"},
]

# Default QING to terraform — can be overridden at init
DEFAULT_QING = Web3.to_checksum_address("0x6152e1b7A3b9F5ABCA66b0de9eaB1CF11e49b7CF")  # Grav QING

# Gas cost estimate: ~700K units at ~2 Beats ≈ 1,400-2,000 PLS
TERRAFORM_GAS_EST = 700_000


class TerraformLoop(GameLoopBase):
    """
    Calls CHOA.Chat(QING, message) periodically to terraform a venue.
    Earns CHOA tokens + venue supply mints per call.

    Template example: demonstrates the GameLoopBase pattern.
    Copy this file to add new loops (void_chat, venue_trade, etc.).
    """
    name = "Terraform"
    pls_cost_per_run = 2_000 * 10**18  # ~2K PLS gas budget per run
    min_interval_secs = 60             # Don't terraform more than once per minute

    def __init__(self, qing_addr: str = DEFAULT_QING, messages: list[str] | None = None):
        super().__init__()
        self.qing_addr = Web3.to_checksum_address(qing_addr)
        self.messages = messages or [
            "the gibson knows all",
            "terraforming block {block}",
            "zero cool online — |>JOYSTICK<|",
            "hack the planet",
            "joey was here",
        ]
        self._msg_index = 0

    def _next_message(self) -> str:
        block = safe(
            w3_submit.eth.contract(address=CHOA, abi=CHOA_ABI),
            "Chat",  # won't work as view — just use w3 block number
        )
        block_num = w3_submit.eth.block_number
        msg = self.messages[self._msg_index % len(self.messages)].format(block=block_num)
        self._msg_index += 1
        return msg

    def should_run(self) -> bool:
        """Run if: PLS above floor+gas, not throttled."""
        if self.is_throttled():
            return False

        bal = pls_balance()
        min_needed = PLS_GAS_FLOOR + self.pls_cost_per_run
        if bal < min_needed:
            log.debug("TerraformLoop: PLS too low (%.0f < %.0f PLS)",
                      bal / 1e18, min_needed / 1e18)
            return False

        return True

    def run(self, dry_run: bool = False) -> LoopResult:
        """Call CHOA.Chat(QING, msg) once."""
        choa_c = w3_submit.eth.contract(address=CHOA, abi=CHOA_ABI)
        msg = self._next_message()

        try:
            r = send_tx(
                choa_c.functions.Chat(self.qing_addr, msg),
                f"CHOA.Chat ({self.qing_addr[:8]}…)",
                dry_run=dry_run,
            )
            self.record_run()
            tx_hash = r["transactionHash"].hex() if r else None
            log.info("Terraform: '%s' → block %d", msg, r["blockNumber"] if r else 0)
            return LoopResult(
                success=True,
                tx_hashes=[tx_hash] if tx_hash else [],
                notes=f"Terraform msg: {msg}",
            )
        except (SimulationFailed, AssertionError, Exception) as exc:
            log.error("TerraformLoop.run() failed: %s", exc)
            return LoopResult(success=False, notes=str(exc))
