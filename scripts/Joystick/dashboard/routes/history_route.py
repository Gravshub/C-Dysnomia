"""
/history — 24H balance history for the chart.
"""

from fastapi import APIRouter
from ..models import HistoryResponse, HistoryPoint
from .. import history

router = APIRouter()


@router.get("/history", response_model=HistoryResponse)
async def get_history():
    """24H balance history for the chart."""
    points_raw = history.get_history()
    points = [HistoryPoint(**p) for p in points_raw]
    return HistoryResponse(points=points)
