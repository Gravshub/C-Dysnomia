"""
JOYSTICK Mission Control — Response Models
Pydantic schemas for all API responses.
These define the contract between the data layer and the frontend.
"""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# ─── Enums ───────────────────────────────────────────────────────────

class EngineStatus(str, Enum):
    RUNNING = "running"
    READY = "ready"
    GATED = "gated"       # has a precondition (e.g. E5 needs 150K PLS floor)
    BLOCKED = "blocked"   # missing dependency (e.g. E7 needs OZZY)
    RECON = "recon"       # needs data before it can run
    DESIGN = "design"     # still being built
    DISABLED = "disabled"


class GasCondition(str, Enum):
    CLEAR = "clear"       # gas price well below ceiling
    CAUTION = "caution"   # gas price approaching ceiling
    SKIP = "skip"         # gas price above ceiling — cycle skipped


# ─── Token balance ───────────────────────────────────────────────────

class TokenBalance(BaseModel):
    symbol: str
    balance: float = Field(description="Human-readable balance (divided by 10^18)")
    balance_wei: str = Field(description="Raw wei balance as string (for precision)")
    pls_value: Optional[float] = Field(None, description="Estimated PLS value via DEX price")
    usd_value: Optional[float] = Field(None, description="Estimated USD value")


# ─── Wallet ──────────────────────────────────────────────────────────

class WalletResponse(BaseModel):
    address: str
    pls_balance: float
    pls_balance_wei: str
    pls_usd: Optional[float] = None
    pls_price_usd: Optional[float] = None
    validator_target: int = 32_000_000
    validator_progress_pct: float = Field(description="pls_balance / 32M × 100")
    gas_buffer_ok: bool = Field(description="True if balance >= 100K PLS floor")
    tokens: list[TokenBalance] = []
    tgsv8_balance_pls: Optional[float] = Field(None, description="TGSv8 contract PLS balance")
    block_number: int = 0


# ─── Engine ──────────────────────────────────────────────────────────

class EngineInfo(BaseModel):
    id: str                          # E1, E2, ...
    name: str                        # RAZOR, CEREAL, ...
    engine_type: str                 # Cross-DEX arb, DSS, ...
    description: str
    status: EngineStatus
    enabled: bool = False            # toggle state
    roi_pct: Optional[float] = None  # last cycle ROI %
    total_earned_pls: Optional[float] = None
    last_run_block: Optional[int] = None
    last_run_profit_pls: Optional[float] = None
    error: Optional[str] = None      # last error message if any


class EnginesResponse(BaseModel):
    engines: list[EngineInfo]
    active_engine: Optional[str] = Field(None, description="Engine ID currently executing")
    cycle_count: int = 0


# ─── Gas ─────────────────────────────────────────────────────────────

class GasResponse(BaseModel):
    gas_price_beats: float
    gas_price_impulses: int = Field(description="Raw eth_gasPrice return value")
    gas_ceiling_beats: int
    condition: GasCondition
    aff_breakeven_beats: Optional[float] = Field(
        None, description="Gas price at which AFF generate becomes unprofitable"
    )
    block_number: int = 0


# ─── Strategy ────────────────────────────────────────────────────────

class StrategyResponse(BaseModel):
    active_strategy: str           # e.g. "STRAT_F"
    strategy_name: str             # e.g. "AFF Generate"
    description: str
    gas_cost_pls: Optional[float] = None
    expected_yield_pls: Optional[float] = None
    net_pls: Optional[float] = None
    roi_pct: Optional[float] = None
    notes: Optional[str] = None


# ─── Transaction log ─────────────────────────────────────────────────

class TxRecord(BaseModel):
    tx_hash: str
    block_number: int
    engine_id: str
    engine_name: str
    action: str                    # e.g. "AFF mint+sell", "DSS claim"
    profit_pls: float              # positive = gain, negative = loss
    gas_cost_pls: float
    timestamp: Optional[int] = None  # unix timestamp


class TxHistoryResponse(BaseModel):
    transactions: list[TxRecord]
    total_realized_pls: float
    total_gas_spent_pls: float
    net_pls: float


# ─── Overview (single-call dashboard payload) ────────────────────────

class OverviewResponse(BaseModel):
    """Single endpoint that returns everything the dashboard needs.
    Reduces frontend polling to one call per interval."""
    wallet: WalletResponse
    engines: EnginesResponse
    gas: GasResponse
    strategy: StrategyResponse
    recent_txs: list[TxRecord] = []
    poll_interval_sec: int = 15
    bot_online: bool = False
