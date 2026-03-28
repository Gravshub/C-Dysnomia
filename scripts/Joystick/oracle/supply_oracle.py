"""
supply_oracle.py — Tracks totalSupply() snapshots for treasury tokens.

Flags tokens whose supply grew > threshold since last snapshot.
This is the "Pong" signal — when someone mints new supply, the DEX
price hasn't adjusted yet, creating a buy opportunity.

Usage:
    oracle = SupplyOracle()
    oracle.update()  # call once per bot cycle
    inflated = oracle.get_inflated_tokens()
    # Returns: [{"address": "0x...", "symbol": "...", "supply_old": int,
    #            "supply_new": int, "growth_pct": float}, ...]
"""
import json
import os
import time

from web3 import Web3

from ..core.log_names import get_logger
from ..core.config import (
    DATA_DIR,
    SUPPLY_INFLATION_THRESHOLD,
    SUPPLY_COOLDOWN_SECONDS,
)
from ..core.chain import w3_read, erc20, multicall

log = get_logger(__name__)

_SNAPSHOT_PATH = os.path.join(DATA_DIR, "supply_snapshots.json")
_WATCHLIST_PATH = os.path.join(DATA_DIR, "supply_watchlist.json")


class SupplyOracle:
    """
    Tracks totalSupply() snapshots for treasury tokens.
    Flags tokens whose supply grew > threshold since last snapshot.
    """

    def __init__(self):
        self._snapshots: dict[str, dict] = {}  # addr_lc -> {"supply": int, "timestamp": float}
        self._inflated: list[dict] = []
        self._cooldowns: dict[str, float] = {}  # addr_lc -> last_flagged_time
        self._token_list: list[dict] = []  # [{"address": str, "symbol": str}, ...]
        self._loaded = False

    def _load_token_list(self) -> list[dict]:
        """Build merged token list from v2_federal_tokens.json + supply_watchlist.json."""
        if self._token_list:
            return self._token_list

        seen = set()
        tokens = []

        # Source 1: V2 Federal tokens
        from ..oracle.data_store import DataStore
        v2fed = DataStore.get().v2_federal_tokens()
        for tok in v2fed:
            addr = tok.get("address", "").lower()
            if addr and addr not in seen:
                seen.add(addr)
                tokens.append({"address": addr, "symbol": tok.get("symbol", addr[:8])})

        # Source 2: Optional supply_watchlist.json
        if os.path.exists(_WATCHLIST_PATH):
            try:
                with open(_WATCHLIST_PATH) as f:
                    watchlist = json.load(f)
                for entry in watchlist if isinstance(watchlist, list) else watchlist.get("tokens", []):
                    addr = entry.get("address", "").lower()
                    if addr and addr not in seen:
                        seen.add(addr)
                        tokens.append({"address": addr, "symbol": entry.get("symbol", addr[:8])})
            except Exception as exc:
                log.debug("SupplyOracle: failed to load watchlist: %s", exc)

        self._token_list = tokens
        return tokens

    def _load_snapshots(self):
        """Load persisted snapshots from disk."""
        if self._loaded:
            return
        self._loaded = True
        if not os.path.exists(_SNAPSHOT_PATH):
            return
        try:
            with open(_SNAPSHOT_PATH) as f:
                self._snapshots = json.load(f)
        except Exception as exc:
            log.warning("SupplyOracle: failed to load snapshots: %s", exc)
            self._snapshots = {}

    def _save_snapshots(self):
        """Persist snapshots to disk via atomic write."""
        tmp_path = _SNAPSHOT_PATH + ".tmp"
        try:
            with open(tmp_path, "w") as f:
                json.dump(self._snapshots, f)
            os.replace(tmp_path, _SNAPSHOT_PATH)
        except Exception as exc:
            log.warning("SupplyOracle: failed to save snapshots: %s", exc)

    def update(self):
        """
        Poll totalSupply() for all tracked tokens via Multicall3.
        Compare against previous snapshot and flag inflation.
        Call once per bot cycle.
        """
        self._load_snapshots()
        tokens = self._load_token_list()
        if not tokens:
            log.debug("SupplyOracle: no tokens to track")
            return

        # Batch totalSupply() via multicall
        calls = []
        for tok in tokens:
            c = erc20(Web3.to_checksum_address(tok["address"]))
            calls.append((c, "totalSupply", []))

        results = multicall(calls)

        now = time.time()
        inflated = []

        for i, tok in enumerate(tokens):
            new_supply = results[i]
            if new_supply is None:
                continue

            addr_lc = tok["address"].lower()
            old_entry = self._snapshots.get(addr_lc)

            if old_entry:
                old_supply = old_entry.get("supply", 0)
                if old_supply > 0:
                    growth = (new_supply - old_supply) / old_supply
                    if growth > SUPPLY_INFLATION_THRESHOLD:
                        # Check cooldown
                        last_flagged = self._cooldowns.get(addr_lc, 0)
                        if now - last_flagged >= SUPPLY_COOLDOWN_SECONDS:
                            inflated.append({
                                "address": Web3.to_checksum_address(addr_lc),
                                "symbol": tok["symbol"],
                                "supply_old": old_supply,
                                "supply_new": new_supply,
                                "growth_pct": growth * 100,
                            })
                            self._cooldowns[addr_lc] = now
                            log.info(
                                "SupplyOracle: INFLATION %s (%s) +%.2f%% (%d -> %d)",
                                tok["symbol"], addr_lc[:10], growth * 100,
                                old_supply, new_supply,
                            )

            # Update snapshot
            self._snapshots[addr_lc] = {
                "supply": new_supply,
                "timestamp": now,
            }

        self._inflated = inflated
        self._save_snapshots()

        log.debug("SupplyOracle: snapshot %d tokens, %d inflated", len(tokens), len(inflated))

    def get_inflated_tokens(self) -> list[dict]:
        """Return tokens flagged as inflated since last update()."""
        return list(self._inflated)

    def token_count(self) -> int:
        """Number of tokens being tracked."""
        return len(self._load_token_list())

    def status(self) -> dict:
        """Status dict for logging / --status display."""
        return {
            "tracked": self.token_count(),
            "snapshots": len(self._snapshots),
            "inflated": len(self._inflated),
            "cooldowns_active": sum(
                1 for t in self._cooldowns.values()
                if time.time() - t < SUPPLY_COOLDOWN_SECONDS
            ),
        }
