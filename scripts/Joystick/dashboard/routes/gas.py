"""
/gas — Gas conditions.
Current gas price in Beats, ceiling, condition status.
Direct chain read — no bot state needed.
"""

from fastapi import APIRouter
from ..models import GasResponse, GasCondition
from ..chain_reader import get_reader
from .. import config

router = APIRouter()

# AFF generate break-even gas estimate:
# multiGenerate(100) costs ~4,273 PLS at ~12 Beats.
# Linear approximation: breakeven ≈ 38 Beats
# (yield stays constant, gas cost scales linearly with gas price)
AFF_BREAKEVEN_BEATS = 38.0


@router.get("/gas", response_model=GasResponse)
async def get_gas():
    reader = get_reader()
    gas_impulses = reader.get_gas_price_impulses()
    gas_beats = gas_impulses / 1e9
    block = reader.get_block_number()

    # Determine condition
    ceiling = config.GAS_CEILING_BEATS
    if gas_beats > ceiling:
        condition = GasCondition.SKIP
    elif gas_beats > ceiling * 0.75:
        condition = GasCondition.CAUTION
    else:
        condition = GasCondition.CLEAR

    return GasResponse(
        gas_price_beats=round(gas_beats, 2),
        gas_price_impulses=gas_impulses,
        gas_ceiling_beats=ceiling,
        condition=condition,
        aff_breakeven_beats=AFF_BREAKEVEN_BEATS,
        block_number=block,
    )
