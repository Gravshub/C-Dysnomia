"""
JOYSTICK Mission Control — API Server

Entry point for the dashboard data layer.
Run with: uvicorn dashboard.api.server:app --host 0.0.0.0 --port 8369

Or from the repo root:
    python -m dashboard.api.server
"""

import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .chain_reader import get_reader
from .routes import wallet, engines, gas, overview

# ─── Logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("joystick.server")

# ─── App ─────────────────────────────────────────────────────────────
app = FastAPI(
    title="|>JOYSTICK<| Mission Control",
    description="Read-only API for the JOYSTICK arbitrage bot on PulseChain (369)",
    version="0.1.0",
)

# ─── CORS ────────────────────────────────────────────────────────────
# Allow localhost dev servers + future Vercel deployment
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS + [
        "https://*.vercel.app",  # future Vercel deploy
    ],
    allow_credentials=True,
    allow_methods=["GET"],     # read-only API
    allow_headers=["*"],
)

# ─── Routes ──────────────────────────────────────────────────────────
app.include_router(wallet.router, prefix="/api", tags=["wallet"])
app.include_router(engines.router, prefix="/api", tags=["engines"])
app.include_router(gas.router, prefix="/api", tags=["gas"])
app.include_router(overview.router, prefix="/api", tags=["overview"])


# ─── Health check ────────────────────────────────────────────────────
@app.get("/health")
async def health():
    """Health check — also verifies RPC connectivity."""
    try:
        reader = get_reader()
        block = reader.get_block_number()
        return {
            "status": "ok",
            "chain_id": config.CHAIN_ID,
            "rpc": config.RPC_READ,
            "block": block,
        }
    except Exception as e:
        return {
            "status": "degraded",
            "error": str(e),
        }


# ─── Startup / shutdown ─────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    logger.info("=" * 60)
    logger.info("|>JOYSTICK<| Mission Control API starting")
    logger.info(f"  RPC:   {config.RPC_READ}")
    logger.info(f"  Chain: {config.CHAIN_ID}")
    logger.info(f"  Port:  {config.API_PORT}")
    logger.info("=" * 60)

    # Warm up the chain reader (establish connection)
    reader = get_reader()
    block = reader.get_block_number()
    if block > 0:
        logger.info(f"  Chain connected — block {block:,}")
    else:
        logger.warning("  Chain connection failed — running in degraded mode")


@app.on_event("shutdown")
async def shutdown():
    logger.info("|>JOYSTICK<| Mission Control API shutting down")


# ─── Direct run ──────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "dashboard.api.server:app",
        host=config.API_HOST,
        port=config.API_PORT,
        reload=True,
        log_level="info",
    )
