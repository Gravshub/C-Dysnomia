"""
/history — Balance history for the chart.

Accepts ?span= query param in seconds, or shorthand: 10m, 1h, 3h, 6h, 12h, 24h, 1w.
"""

from fastapi import APIRouter, Query
from typing import Optional
from ..models import HistoryResponse, HistoryPoint
from .. import history

router = APIRouter()

_SPAN_MAP = {
    "10m": 600,
    "1h":  3600,
    "3h":  10800,
    "6h":  21600,
    "12h": 43200,
    "24h": 86400,
    "1w":  604800,
}


@router.get("/history", response_model=HistoryResponse)
async def get_history(span: Optional[str] = Query(None, description="Timeframe: 10m, 1h, 3h, 6h, 12h, 24h, 1w, or seconds")):
    """Balance history for the chart, filterable by timeframe."""
    span_seconds = None
    if span:
        if span in _SPAN_MAP:
            span_seconds = _SPAN_MAP[span]
        else:
            try:
                span_seconds = int(span)
            except ValueError:
                span_seconds = 86400  # fallback to 24h

    points_raw = history.get_history(span_seconds=span_seconds)
    points = [HistoryPoint(**p) for p in points_raw]
    return HistoryResponse(points=points)
