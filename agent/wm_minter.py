#!/usr/bin/env python3
"""
wm_minter.py — TGSv5 WM (MV) Minting Agent

Off-chain decision layer for WM minting on PulseChain.
Simulates gas cost before every operation; only mints when value > gas cost.

Known Bugs Avoided (from prior bots):
  - Uses Decimal(10**18) NOT Decimal(18) for wei conversions
  - No infinite loop — run_auto() is a single-cycle function (wrap in cron/scheduler)
  - State not shared across calls (each run reads fresh chain state)

Usage:
    python wm_minter.py                       # auto: simulate, pick batch 10 or 5
    python wm_minter.py --count N             # manual: mint exactly N WM
    python wm_minter.py --count N --force     # manual: skip economic gate

Required environment variables:
    TGSV5_ADDRESS         Deployed TGSv5 contract address
    OPERATOR_PRIVATE_KEY  Operator wallet private key (hex, with or without 0x)

Optional environment variables:
    PULSECHAIN_RPC        RPC endpoint (default: https://rpc.pulsechain.com)
    WM_PRICE_PLS          Override WM price in PLS — useful for testing/dry-runs
"""

import os
import sys
import logging
import argparse
from decimal import Decimal, getcontext
from web3 import Web3

# 28-digit precision for PLS/WM price math
getcontext().prec = 28

log = logging.getLogger("wm_minter")

# ── Network constants ──────────────────────────────────────────────────────────

PULSECHAIN_RPC      = "https://rpc.pulsechain.com"
PULSECHAIN_CHAIN_ID = 369

WM_CONTRACT = Web3.to_checksum_address("0xA1BEe1daE9Af77dAC73aA0459eD63b4D93fC6d29")

# ── TGSv5 partial ABI (only what this agent needs) ────────────────────────────

TGSV5_ABI = [
    {
        "name": "mintWM",
        "type": "function",
        "inputs": [{"name": "count", "type": "uint256"}],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "name": "wmBalance",
        "type": "function",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    },
    {
        "name": "paused",
        "type": "function",
        "inputs": [],
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
    },
    {
        "name": "authorized",
        "type": "function",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
    },
    {
        "name": "WMMinted",
        "type": "event",
        "inputs": [
            {"name": "caller",  "type": "address", "indexed": True},
            {"name": "count",   "type": "uint256", "indexed": False},
            {"name": "gasUsed", "type": "uint256", "indexed": False},
        ],
    },
]


# ── WMMinter ──────────────────────────────────────────────────────────────────

class WMMinter:
    """
    Encapsulates all WM minting logic:
      - gas simulation (pre-mint cost estimate)
      - price oracle (WM value in PLS)
      - economic gate (skip when cost >= value)
      - batch selection (10 WM when cheap, 5 WM when expensive)
      - transaction execution with receipt verification
    """

    def __init__(self, rpc_url: str, tgsv5_address: str, private_key: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self.w3.is_connected():
            raise ConnectionError(f"Cannot connect to PulseChain RPC: {rpc_url}")

        self.account = self.w3.eth.account.from_key(private_key)
        self.tgsv5 = self.w3.eth.contract(
            address=Web3.to_checksum_address(tgsv5_address),
            abi=TGSV5_ABI,
        )
        log.info("WMMinter ready | operator=%s | tgsv5=%s", self.account.address, tgsv5_address)

    # ── Pre-flight checks ──────────────────────────────────────────────────────

    def preflight(self) -> bool:
        """Verify contract is not paused and operator is authorized."""
        if self.tgsv5.functions.paused().call():
            log.warning("TGSv5 is paused — aborting")
            return False
        if not self.tgsv5.functions.authorized(self.account.address).call():
            log.error("Operator %s is not authorized on TGSv5", self.account.address)
            return False
        return True

    # ── Gas helpers ────────────────────────────────────────────────────────────

    def estimate_gas(self, count: int) -> int:
        """Estimate gas units required for mintWM(count)."""
        return self.tgsv5.functions.mintWM(count).estimate_gas(
            {"from": self.account.address}
        )

    def gas_price_wei(self) -> int:
        """Current base gas price in wei."""
        return self.w3.eth.gas_price

    def mint_cost_pls(self, count: int) -> Decimal:
        """
        Total estimated PLS cost for mintWM(count).
        Uses Decimal(10**18) — NOT Decimal(18) — for correct wei-to-PLS conversion.
        """
        gas   = self.estimate_gas(count)
        price = self.gas_price_wei()
        return Decimal(gas * price) / Decimal(10 ** 18)

    # ── Price oracle ───────────────────────────────────────────────────────────

    def wm_price_pls(self) -> Decimal:
        """
        WM (MV) price in PLS.

        Checks WM_PRICE_PLS env override first (useful for testing / dry-runs).

        TODO (Phase 2): implement live multi-hop PulseX V2 query:
            WM → AFFECTION (0x24F0154C1dCe548AdF15da2098Fdd8B8A3B8151D) → WPLS
            using PulseX V2 Factory (0x29eA7545DEf87022BAdc76323F373EA1e707C523)
            and Router  (0x165C3410fC91EF562C50559f7d2289fEbed552d9)
            Known intermediates: FED, AFFECTION, WPLS
            Base-10 conversions: divide by 10**18 (NOT 10**10).
        """
        override = os.getenv("WM_PRICE_PLS")
        if override:
            return Decimal(override)
        # Safe placeholder — update once price oracle is wired
        return Decimal("0.001")  # 0.001 PLS per 1 WM

    # ── Economic gate ──────────────────────────────────────────────────────────

    def check_profitable(self, count: int) -> tuple[bool, Decimal, Decimal]:
        """
        Returns (profitable, cost_pls, value_pls).
        Only returns True when the WM tokens gained are worth more than the gas spent.
        """
        cost  = self.mint_cost_pls(count)
        value = self.wm_price_pls() * Decimal(count)
        return value > cost, cost, value

    # ── Batch selection ────────────────────────────────────────────────────────

    def select_batch(self) -> int:
        """
        Simulate cost for batch=10 (cheap gas) and batch=5 (expensive gas).
        Returns the largest profitable batch size, or 0 if neither is worth it.
        """
        for batch in (10, 5):
            profitable, cost, value = self.check_profitable(batch)
            status = "MINT" if profitable else "SKIP"
            log.info(
                "simulate batch=%d | cost=%.6f PLS | value=%.6f PLS | %s",
                batch, cost, value, status,
            )
            if profitable:
                return batch
        return 0

    # ── Execution ──────────────────────────────────────────────────────────────

    def execute_mint(self, count: int) -> str:
        """
        Build, sign, and broadcast mintWM(count) to PulseChain.
        Waits for receipt and verifies success.
        Returns transaction hash (hex string).
        Raises RuntimeError on revert.
        """
        nonce     = self.w3.eth.get_transaction_count(self.account.address, "pending")
        gas       = self.estimate_gas(count)
        gas_price = self.gas_price_wei()

        tx = self.tgsv5.functions.mintWM(count).build_transaction({
            "from":     self.account.address,
            "nonce":    nonce,
            "gas":      gas,
            "gasPrice": gas_price,
            "chainId":  PULSECHAIN_CHAIN_ID,
        })

        signed   = self.account.sign_transaction(tx)
        tx_hash  = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        log.info("Tx broadcast: %s | batch=%d WM ...", tx_hash.hex(), count)

        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            raise RuntimeError(f"mintWM reverted — tx: {tx_hash.hex()}")

        log.info(
            "Minted %d WM | tx=%s | gas_used=%d | block=%d",
            count, tx_hash.hex(), receipt.gasUsed, receipt.blockNumber,
        )
        return tx_hash.hex()

    # ── Public entry points ────────────────────────────────────────────────────

    def run_auto(self) -> str | None:
        """
        Auto mode: run one minting cycle.
          1. Preflight (paused? authorized?)
          2. Simulate batch=10 then batch=5
          3. Execute the first profitable batch, or skip
        Returns tx hash or None.
        """
        if not self.preflight():
            return None
        batch = self.select_batch()
        if batch == 0:
            log.info("No profitable batch — skipping this cycle")
            return None
        return self.execute_mint(batch)

    def run_manual(self, count: int, force: bool = False) -> str | None:
        """
        Manual mode: mint exactly `count` WM.
        Economic gate is enforced unless --force is passed.
        Returns tx hash or None.
        """
        if not self.preflight():
            return None
        profitable, cost, value = self.check_profitable(count)
        if not profitable and not force:
            log.warning(
                "Minting %d WM is unprofitable: cost=%.6f PLS > value=%.6f PLS",
                count, cost, value,
            )
            answer = input("Proceed anyway? [y/N]: ").strip().lower()
            if answer != "y":
                log.info("Aborted by user.")
                return None
        return self.execute_mint(count)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="TGSv5 WM Minting Agent — economically-gated WM minting on PulseChain"
    )
    parser.add_argument(
        "--count", type=int, default=None,
        help="Mint exactly N WM (omit for auto mode: simulates 10 then 5)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip economic gate when used with --count",
    )
    parser.add_argument(
        "--rpc", default=os.getenv("PULSECHAIN_RPC", PULSECHAIN_RPC),
        help="PulseChain RPC URL",
    )
    parser.add_argument(
        "--tgsv5", default=os.getenv("TGSV5_ADDRESS", ""),
        help="TGSv5 contract address (required after deployment)",
    )
    parser.add_argument(
        "--key", default=os.getenv("OPERATOR_PRIVATE_KEY", ""),
        help="Operator wallet private key",
    )
    args = parser.parse_args()

    if not args.key:
        log.error("Operator private key required — set OPERATOR_PRIVATE_KEY or --key")
        sys.exit(1)
    if not args.tgsv5:
        log.error("TGSv5 address required — set TGSV5_ADDRESS or --tgsv5 after deployment")
        sys.exit(1)

    minter = WMMinter(args.rpc, args.tgsv5, args.key)

    tx = minter.run_manual(args.count, force=args.force) if args.count is not None else minter.run_auto()

    print(f"Success: {tx}" if tx else "No transaction executed.")


if __name__ == "__main__":
    main()
