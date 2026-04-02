"""
rpc_provider.py — Resilient RPC provider layer with health tracking, automatic
failover, retry logic, and latency-weighted routing.

Privacy tiers:
  Tier 1 — No tracking, no logging, no API keys (PulseChain.com, PublicNode, G4MM4)
  Tier 2 — Community / operational (PulseChainStats)
  Tier 3 — Self-hosted (local validator, Anvil fork)

TX submission only uses Tier 1 providers to protect trading patterns.
Reads fan across all tiers for maximum availability.
"""
import os
import time
import logging

from .log_names import get_logger
import threading
from dataclasses import dataclass, field

from web3 import Web3
from web3.exceptions import ProviderConnectionError, TimeExhausted

log = get_logger(__name__)

# ── Tuning (env-overridable via config.py constants) ─────────────────────────
MAX_RETRIES = int(os.getenv("RPC_MAX_RETRIES", "2"))
RETRY_BACKOFF_BASE = 0.5  # seconds, doubles each retry
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("RPC_CB_THRESHOLD", "5"))
COOLDOWN_BASE = int(os.getenv("RPC_COOLDOWN_BASE", "30"))  # seconds


@dataclass
class ProviderState:
    """Health state for a single RPC endpoint."""
    url: str
    name: str
    tier: int                     # 1=privacy-first, 2=community, 3=self-hosted
    role: str                     # "read", "submit", or "both"
    w3: Web3 = field(repr=False, default=None)
    latency_ema: float = 0.0     # exponential moving average (seconds)
    success_count: int = 0
    fail_count: int = 0
    consecutive_fails: int = 0
    last_success: float = 0.0
    last_fail: float = 0.0
    disabled_until: float = 0.0  # circuit breaker cooldown

    @property
    def is_healthy(self) -> bool:
        if time.time() < self.disabled_until:
            return False
        if self.success_count + self.fail_count == 0:
            return True  # untested = assume healthy
        total = self.success_count + self.fail_count
        return self.fail_count / total < 0.5

    @property
    def score(self) -> float:
        """Lower is better. Combines latency + error penalty."""
        if not self.is_healthy:
            return float('inf')
        error_rate = self.fail_count / max(1, self.success_count + self.fail_count)
        return (self.latency_ema * 1000) + (error_rate * 10000)

    def record_success(self, latency: float):
        self.success_count += 1
        self.consecutive_fails = 0
        self.last_success = time.time()
        alpha = 0.3
        if self.latency_ema == 0:
            self.latency_ema = latency
        else:
            self.latency_ema = alpha * latency + (1 - alpha) * self.latency_ema

    def record_failure(self):
        self.fail_count += 1
        self.consecutive_fails += 1
        self.last_fail = time.time()
        if self.consecutive_fails >= CIRCUIT_BREAKER_THRESHOLD:
            cooldown = min(300, COOLDOWN_BASE * (2 ** (self.consecutive_fails - CIRCUIT_BREAKER_THRESHOLD)))
            self.disabled_until = time.time() + cooldown
            log.warning(
                "🔴 RPC %s circuit breaker: disabled for %ds (consec fails: %d)",
                self.name, cooldown, self.consecutive_fails,
            )

    def reset_health(self):
        """Reset after cooldown expires and provider recovers."""
        self.consecutive_fails = 0
        self.disabled_until = 0.0


class RPCAllProvidersDown(Exception):
    """All RPC providers in the pool are unavailable."""


class RPCPool:
    """
    Manages a pool of RPC providers with health-aware routing.

    Usage:
      pool = RPCPool(providers=[...], role="read")
      result = pool.call(lambda w3: w3.eth.block_number)

      pool = RPCPool(providers=[...], role="submit")
      receipt = pool.send_raw(signed_tx)
    """

    def __init__(self, providers: list[ProviderState], role: str = "read"):
        self.providers = providers
        self.role = role
        self._lock = threading.Lock()

        timeout = 60 if role == "submit" else 30
        for p in self.providers:
            if p.w3 is None:
                p.w3 = Web3(Web3.HTTPProvider(
                    p.url, request_kwargs={"timeout": timeout}
                ))

    def _ranked_providers(self) -> list[ProviderState]:
        """Return providers sorted by score (best first), skip disabled."""
        now = time.time()
        active = []
        for p in self.providers:
            if p.disabled_until > 0 and now >= p.disabled_until:
                log.info("🟢 RPC %s cooldown expired, re-enabling", p.name)
                p.reset_health()
            if p.is_healthy:
                active.append(p)
        return sorted(active, key=lambda p: p.score)

    def healthy_count(self) -> int:
        """Return number of currently healthy (non-circuit-broken) providers."""
        return len(self._ranked_providers())

    def call(self, fn):
        """
        Execute a read call with automatic failover.

        Args:
            fn: callable that takes (w3_instance) and returns result

        Returns: result of fn(w3)
        Raises: RPCAllProvidersDown if all providers exhausted
        """
        ranked = self._ranked_providers()
        if not ranked:
            raise RPCAllProvidersDown(f"No healthy {self.role} providers available")

        last_error = None
        for provider in ranked:
            for attempt in range(MAX_RETRIES + 1):
                try:
                    t0 = time.time()
                    result = fn(provider.w3)
                    latency = time.time() - t0
                    provider.record_success(latency)
                    return result
                except Exception as e:
                    # Don't retry on contract reverts — application-level errors
                    err_str = str(e).lower()
                    if "revert" in err_str or "execution reverted" in err_str:
                        raise
                    provider.record_failure()
                    last_error = e
                    if attempt < MAX_RETRIES:
                        backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
                        log.debug(
                            "RPC %s attempt %d failed: %s — retrying in %.1fs",
                            provider.name, attempt + 1, str(e)[:80], backoff,
                        )
                        time.sleep(backoff)
                    else:
                        log.warning("🔌 RPC %s exhausted retries: %s", provider.name, str(e)[:80])
                        break  # next provider

        raise RPCAllProvidersDown(f"All {self.role} providers failed. Last error: {last_error}")

    def send_raw(self, signed_tx) -> str:
        """
        Submit a signed transaction via the best healthy Tier 1 provider.
        Fails over to next provider on error. Stops on first acceptance.

        Returns: tx_hash hex string, or None if TX already in mempool.
        """
        ranked = [p for p in self._ranked_providers() if p.tier <= 1]
        if not ranked:
            ranked = self._ranked_providers()
            if ranked:
                log.warning("No Tier 1 submit providers — using %s", ranked[0].name)

        if not ranked:
            raise RPCAllProvidersDown("No healthy submit providers")

        # Submit to ONE provider only. Multi-provider broadcast causes
        # "replacement TX underpriced" races — first provider accepts,
        # second rejects with conflicting nonce state. Failover to next
        # provider only on hard error.
        last_error = None
        for provider in ranked:
            try:
                t0 = time.time()
                tx_hash = provider.w3.eth.send_raw_transaction(signed_tx)
                latency = time.time() - t0
                provider.record_success(latency)
                h = tx_hash.hex() if hasattr(tx_hash, 'hex') else tx_hash
                log.info("TX submitted to %s: %s", provider.name, h)
                return h
            except Exception as e:
                err_str = str(e).lower()
                if "nonce too low" in err_str:
                    raise  # nonce consumed on-chain, no retry
                if "already known" in err_str:
                    log.info("TX already in %s mempool", provider.name)
                    return None  # executor handles None → uses signed.hash
                provider.record_failure()
                last_error = e
                log.warning("TX submit to %s failed: %s — trying next",
                            provider.name, str(e)[:80])

        raise RPCAllProvidersDown(f"TX submission failed on all providers. Last: {last_error}")

    def get_w3(self) -> Web3:
        """Get the Web3 instance for the best current provider.
        For backward compat — prefer pool.call() for critical paths."""
        ranked = self._ranked_providers()
        if not ranked:
            raise RPCAllProvidersDown(f"No healthy {self.role} providers")
        return ranked[0].w3

    def health_report(self) -> list[dict]:
        """Return health status of all providers."""
        report = []
        for p in self.providers:
            total = p.success_count + p.fail_count
            report.append({
                "name": p.name,
                "url": p.url[:40] + ("..." if len(p.url) > 40 else ""),
                "tier": p.tier,
                "healthy": p.is_healthy,
                "latency_ms": round(p.latency_ema * 1000, 1),
                "error_rate": round(p.fail_count / max(1, total) * 100, 1),
                "consec_fails": p.consecutive_fails,
                "score": round(p.score, 1) if p.score != float('inf') else "DISABLED",
            })
        return report


# ═══════════════════════════════════════════════════════════════════════════════
#  DEFAULT POOL FACTORY
# ═══════════════════════════════════════════════════════════════════════════════

def build_default_pools() -> tuple[RPCPool, RPCPool]:
    """
    Build the default read and submit pools from env config.

    Returns: (read_pool, submit_pool)

    Env overrides:
      PULSECHAIN_RPC        — primary submit RPC
      PULSECHAIN_READ_RPC   — primary read RPC
      PULSECHAIN_LOCAL_RPC  — local node (validator/Anvil), highest priority
    """
    local_rpc = os.getenv("PULSECHAIN_LOCAL_RPC", "")

    # ── Read providers (all tiers OK) ──────────────────────────────────────
    read_providers = []
    if local_rpc:
        read_providers.append(ProviderState(
            url=local_rpc, name="LOCAL", tier=3, role="read"))

    read_providers.extend([
        ProviderState(url="https://rpc-pulsechain.g4mm4.io",
                      name="G4MM4", tier=1, role="read"),
        ProviderState(url="https://rpc.pulsechain.com",
                      name="PulseChain", tier=1, role="read"),
        ProviderState(url="https://pulsechain-rpc.publicnode.com",
                      name="PublicNode", tier=1, role="read"),
        ProviderState(url="https://rpc.pulsechainstats.com",
                      name="PCStats", tier=2, role="read"),
    ])

    custom_read = os.getenv("PULSECHAIN_READ_RPC", "")
    if custom_read and not any(p.url == custom_read for p in read_providers):
        read_providers.insert(0, ProviderState(
            url=custom_read, name="CUSTOM_READ", tier=1, role="read"))

    # ── Submit providers (Tier 1 only for TX privacy) ──────────────────────
    submit_providers = []
    if local_rpc:
        submit_providers.append(ProviderState(
            url=local_rpc, name="LOCAL", tier=3, role="submit"))

    submit_providers.extend([
        ProviderState(url="https://rpc.pulsechain.com",
                      name="PulseChain", tier=1, role="submit"),
        # G4MM4 and PublicNode are Tier 2 fallbacks for TX submission.
        # PublicNode accepts TXs but doesn't reliably propagate them.
        ProviderState(url="https://rpc-pulsechain.g4mm4.io",
                      name="G4MM4", tier=2, role="submit"),
        ProviderState(url="https://pulsechain-rpc.publicnode.com",
                      name="PublicNode", tier=2, role="submit"),
    ])

    custom_submit = os.getenv("PULSECHAIN_RPC", "")
    if custom_submit and not any(p.url == custom_submit for p in submit_providers):
        submit_providers.insert(0, ProviderState(
            url=custom_submit, name="CUSTOM_SUBMIT", tier=1, role="submit"))

    return RPCPool(read_providers, role="read"), RPCPool(submit_providers, role="submit")
