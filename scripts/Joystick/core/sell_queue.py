"""
sell_queue.py — Track tokens accumulated in TGSv8 for Seller to liquidate.

After Minter produces tokens via claimTreasury / batchMintAndClaim / createV4,
the tokens land in TGSv8's balance. Seller picks the highest-value sell target
each cycle.

Source of truth: TGSv8 balanceOf() on-chain. The JSON cache is advisory only.
"""
import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path

log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
_QUEUE_FILE = _DATA_DIR / "sell_queue.json"


@dataclass
class SellTarget:
    """A token in TGSv8 that Seller can liquidate."""
    token:          str       # address
    symbol:         str
    amount_wei:     int       # balance in TGSv8
    best_dex:       str       # "V1" or "V2"
    est_pls_out:    int       # expected PLS after swap
    pool_impact:    float     # % of pool consumed


class SellQueue:
    """
    Manages the sell queue: scan TGSv8 for token balances,
    estimate DEX output, pick best target.
    """

    def __init__(self, tgsv8_address: str):
        self.tgsv8_address = tgsv8_address
        self._targets: list[SellTarget] = []
        self._load()

    def scan_tgsv8_balances(self) -> list[SellTarget]:
        """
        Scan TGSv8 for all tokens with nonzero balance.
        Estimate PLS output via getAmountsOut on V1 and V2 routers.
        Returns sorted by est_pls_out descending.
        """
        from .chain import erc20, get_read_pool, multicall
        from .config import WPLS, PULSEX_V1_ROUTER, PULSEX_V1_FACTORY, PULSEX_V2_FACTORY
        from ..oracle.price import get_amounts_out

        if not self.tgsv8_address:
            return []

        # Load known tokens from recon data or imported tokens
        known_tokens = self._load_known_tokens()
        if not known_tokens:
            return self._targets

        # Batch-check balances via multicall
        contracts = [(erc20(addr), "balanceOf", [self.tgsv8_address])
                     for addr, _ in known_tokens]

        try:
            balances = multicall(contracts)
        except Exception as exc:
            log.warning("SellQueue multicall failed: %s", exc)
            return self._targets

        targets = []
        for i, (addr, symbol) in enumerate(known_tokens):
            bal = balances[i] if balances[i] is not None else 0
            if bal <= 0:
                continue

            # Estimate PLS output via both routers
            best_pls = 0
            best_dex = "V2"
            for dex_label, router_addr in [("V1", PULSEX_V1_ROUTER), ("V2", PULSEX_V1_ROUTER)]:
                try:
                    amounts = get_amounts_out(bal, [addr, WPLS], router=router_addr)
                    if amounts and amounts[-1] > best_pls:
                        best_pls = amounts[-1]
                        best_dex = dex_label
                except Exception:
                    pass

            if best_pls > 0:
                targets.append(SellTarget(
                    token=addr,
                    symbol=symbol,
                    amount_wei=bal,
                    best_dex=best_dex,
                    est_pls_out=best_pls,
                    pool_impact=0.0,  # TODO: compute from reserves
                ))

        targets.sort(key=lambda t: t.est_pls_out, reverse=True)
        self._targets = targets
        self._save()
        return targets

    def best_target(self) -> SellTarget | None:
        """Return the highest-value sell target, or None."""
        return self._targets[0] if self._targets else None

    def record_sale(self, token: str, amount: int) -> None:
        """Record that a token was sold (removes/reduces from queue)."""
        self._targets = [t for t in self._targets if t.token.lower() != token.lower()]
        self._save()

    def _load_known_tokens(self) -> list[tuple[str, str]]:
        """Load list of (address, symbol) from recon data or config."""
        # Try loading from v2_federal_tokens.json
        tokens = []
        v2_path = _DATA_DIR / "v2_federal_tokens.json"
        if v2_path.exists():
            try:
                with open(v2_path) as f:
                    data = json.load(f)
                for entry in data:
                    addr = entry.get("address", "")
                    sym = entry.get("symbol", "?")
                    if addr:
                        tokens.append((addr, sym))
            except Exception:
                pass

        # Also add core tokens that might accumulate
        from .config import AFFECTION, WM, GIBS_LAU
        from web3 import Web3
        core = [
            (AFFECTION, "AFF"),
            (WM, "WM"),
            (GIBS_LAU, "GIBS"),
        ]
        existing = {t[0].lower() for t in tokens}
        for addr, sym in core:
            if addr.lower() not in existing:
                tokens.append((addr, sym))

        return tokens

    def _save(self) -> None:
        """Persist queue to disk via atomic write."""
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = [asdict(t) for t in self._targets]
        tmp = _QUEUE_FILE.with_suffix(".tmp")
        try:
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(str(tmp), str(_QUEUE_FILE))
        except Exception as exc:
            log.warning("Failed to save sell queue: %s", exc)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    def _load(self) -> None:
        """Load cached queue from disk (advisory — will be overwritten by scan)."""
        if not _QUEUE_FILE.exists():
            return
        try:
            with open(_QUEUE_FILE) as f:
                data = json.load(f)
            self._targets = [SellTarget(**entry) for entry in data]
        except Exception:
            self._targets = []
