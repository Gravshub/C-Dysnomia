"""
log_names.py — Short logger name registry for console readability.

Usage in any module:
    from ..core.log_names import get_logger
    log = get_logger(__name__)

Number formatting helpers for PLS/gas display:
    from ..core.log_names import fmt_pls, fmt_int, fmt_pls_short
"""
import logging

# Map full module paths to short display names
_NAME_MAP = {
    "scripts.Joystick.bot":                    "bot",
    "scripts.Joystick.core.chain":             "core.chain",
    "scripts.Joystick.core.config":            "core.config",
    "scripts.Joystick.core.concurrency":       "core.sim",
    "scripts.Joystick.core.executor":          "core.exec",
    "scripts.Joystick.core.gas_guard":         "core.gas",
    "scripts.Joystick.core.gas_oracle":        "gas.oracle",
    "scripts.Joystick.core.rpc_provider":      "core.rpc",
    "scripts.Joystick.core.simulator":         "core.sim",
    "scripts.Joystick.core.strategist":        "strategist",
    "scripts.Joystick.core.wallet":            "core.wallet",
    "scripts.Joystick.core.wallet_manager":    "wallet.mgr",
    "scripts.Joystick.core.sell_queue":        "sell.queue",
    "scripts.Joystick.core.event_logger":      "event.log",
    "scripts.Joystick.core.split_swap":        "core.split",
    "scripts.Joystick.engines.arb":            "E1.razor",
    "scripts.Joystick.engines.dss":            "E2.cereal",
    "scripts.Joystick.engines.beat":           "E3.meridian",
    "scripts.Joystick.engines.token_factory":  "E4.factory",
    "scripts.Joystick.engines.lau":            "E5.abupru",
    "scripts.Joystick.engines.treasury_sniper":"E6.davinci",
    "scripts.Joystick.engines.spine_runner":   "E7.backbone",
    "scripts.Joystick.engines.phreak":         "E8.phreak",
    "scripts.Joystick.engines.base":           "engine.base",
    "scripts.Joystick.oracle.pair_discovery":  "oracle.pairs",
    "scripts.Joystick.oracle.graph":           "oracle.graph",
    "scripts.Joystick.oracle.price":           "oracle.price",
    "scripts.Joystick.oracle.scanner":         "oracle.scan",
    "scripts.Joystick.oracle.data_store":      "oracle.data",
    "scripts.Joystick.oracle.profitability":   "oracle.profit",
    "scripts.Joystick.oracle.route_auditor":   "oracle.route",
    "scripts.Joystick.loops.terraform":        "loop.terra",
    "scripts.Joystick.loops.base":             "loop.base",
    "joystick.strategist":                     "strategist",
    "joystick":                                "bot",
}


def get_logger(module_name: str) -> logging.Logger:
    """Return a logger with a short display name mapped from the full module path."""
    short = _NAME_MAP.get(module_name, module_name.rsplit(".", 1)[-1])
    return logging.getLogger(short)


# ── Number formatting helpers ────────────────────────────────────────────────

def fmt_pls(wei: int) -> str:
    """Format wei to PLS with comma separators and 4 decimal places.
    Example: 1979624600000000000000000 → '1,979,624.6000'
    """
    pls = wei / 1e18
    return f"{pls:,.4f}"


def fmt_int(n: int | float) -> str:
    """Format integer with comma separators.
    Example: 854232 → '854,232'
    """
    return f"{int(n):,}"


def fmt_pls_short(pls_float: float) -> str:
    """Format PLS float with commas and 2 decimal places for result lines."""
    return f"{pls_float:,.2f}"
