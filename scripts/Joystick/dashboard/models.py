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


# ─── Mint economics ─────────────────────────────────────────────────

class WmMintEconomics(BaseModel):
    mint_cost_1: float = Field(0.0, description="PLS gas cost to mint 1 WM")
    mint_cost_10: float = Field(0.0, description="PLS gas cost to mint 10 WM")
    dex_value_1: float = Field(0.0, description="PLS received selling 1 WM on DEX")
    dex_value_10: float = Field(0.0, description="PLS received selling 10 WM on DEX")


class AffRouteEconomics(BaseModel):
    name: str
    payment_pls: float = Field(0.0, description="PLS cost of payment tokens per 1 AFF")
    gas_pls: float = Field(0.0, description="PLS gas cost per 1 AFF (amortized)")
    total_pls: float = Field(0.0, description="Total PLS cost per 1 AFF")
    profitable: bool = False


class AffMintEconomics(BaseModel):
    dex_value: float = Field(0.0, description="PLS received selling 1 AFF on DEX")
    cheapest_route: Optional[str] = None
    cheapest_cost: Optional[float] = None
    routes: list[AffRouteEconomics] = []


class MintEconomics(BaseModel):
    wm: WmMintEconomics = Field(default_factory=WmMintEconomics)
    aff: AffMintEconomics = Field(default_factory=AffMintEconomics)


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
    mint: Optional[MintEconomics] = Field(None, description="Live WM + AFF mint costs")


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


# ─── TGSv8 ────────────────────────────────────────────────────────────

class TGSv8AuthStatus(BaseModel):
    joey: bool = False
    minter: Optional[bool] = None
    seller: Optional[bool] = None


class TGSv8Response(BaseModel):
    address: str
    owner: Optional[str] = None
    owner_is_joey: bool = False
    paused: bool = False
    authorized: TGSv8AuthStatus = TGSv8AuthStatus()
    op_nonce: int = 0
    registry_len: int = 0
    max_batch: int = 0
    native_pls: float = 0.0
    token_balances: dict[str, float] = {}
    refs: dict[str, Optional[str]] = {}
    refs_valid: bool = False


# ─── TGSv8+ ──────────────────────────────────────────────────────────

class TGSv8PlusAuthStatus(BaseModel):
    joey: bool = False
    minter: Optional[bool] = None


class TGSv8PlusStats(BaseModel):
    total_lau_minted: float = 0.0
    total_pay_token_spent: float = 0.0
    total_lp_burned: float = 0.0
    op_counter: int = 0
    mintable_lau: int = 0
    lau_remaining: int = 0


class TGSv8PlusResponse(BaseModel):
    address: str
    owner: Optional[str] = None
    owner_is_joey: bool = False
    authorized: TGSv8PlusAuthStatus = TGSv8PlusAuthStatus()
    stats: TGSv8PlusStats = TGSv8PlusStats()
    native_pls: float = 0.0
    token_balances: dict[str, float] = {}
    refs: dict[str, Optional[str]] = {}
    refs_valid: bool = False


# ─── Combined TGSv8 + TGSv8+ ─────────────────────────────────────────

class ContractsResponse(BaseModel):
    tgsv8: TGSv8Response
    tgsv8plus: TGSv8PlusResponse


# ─── Balance history ─────────────────────────────────────────────────

class HistoryPoint(BaseModel):
    ts: int
    block: int = 0
    joey_pls: float = 0.0
    tgsv8_pls: float = 0.0
    tgsv8plus_pls: float = 0.0
    total_pls: float = 0.0
    gibs_price: Optional[float] = None
    gas_beats: float = 0.0


class HistoryResponse(BaseModel):
    points: list[HistoryPoint] = []


# ─── Overview (single-call dashboard payload) ────────────────────────

class OverviewResponse(BaseModel):
    """Single endpoint that returns everything the dashboard needs.
    Reduces frontend polling to one call per interval."""
    wallet: WalletResponse
    engines: EnginesResponse
    gas: GasResponse
    strategy: StrategyResponse
    tgsv8: Optional[TGSv8Response] = None
    tgsv8plus: Optional[TGSv8PlusResponse] = None
    recent_txs: list[TxRecord] = []
    poll_interval_sec: int = 15
    bot_online: bool = False
