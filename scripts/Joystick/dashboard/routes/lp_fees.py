"""
/api/lp-fees — GIBS LP fee accrual endpoints.

Read-only views on top of oracle/lp_fees.py + lp_fee_history.py + lp_il.py.
Plus a POST /reset-baseline that re-snapshots current positions as the new
baseline (auth TODO — no auth pattern exists in the dashboard yet).
"""

import logging
from dataclasses import asdict
from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import require_admin
from ...oracle.lp_fees import (
    compute_fee_accrual,
    load_baseline,
    save_baseline,
    scan_joey_lp_positions,
)
from ...oracle.lp_fee_history import (
    compute_history_deltas,
    load_history,
    record_snapshot,
)
from ...oracle.lp_il import compute_il_report
from ..models import (
    LPFeeHistoryResponse,
    LPFeeReportResponse,
    LPFeeResetResponse,
    LPPositionsResponse,
)

router = APIRouter()
logger = logging.getLogger("joystick.routes.lp_fees")


@router.get("/lp-fees/positions", response_model=LPPositionsResponse)
async def get_lp_positions():
    try:
        positions = scan_joey_lp_positions()
    except Exception as exc:
        logger.exception("lp_fees.positions scan failed")
        raise HTTPException(status_code=503, detail=str(exc))

    payload = [asdict(p) for p in positions]
    total_value = sum(p.value_pls for p in positions)
    return LPPositionsResponse(
        positions=payload,
        total_value_pls=total_value,
        count=len(payload),
    )


@router.get("/lp-fees/report", response_model=LPFeeReportResponse)
async def get_lp_fee_report():
    try:
        positions = scan_joey_lp_positions()
    except Exception as exc:
        logger.exception("lp_fees.report scan failed")
        raise HTTPException(status_code=503, detail=str(exc))

    baseline = load_baseline()
    if not baseline:
        return LPFeeReportResponse(
            has_baseline=False,
            report=None,
            il=[],
            positions=[asdict(p) for p in positions],
        )

    report = compute_fee_accrual(baseline, positions)
    il = compute_il_report(baseline, positions)

    return LPFeeReportResponse(
        has_baseline=True,
        report={
            "total_k_growth_pls_low": report.total_k_growth_pls_low,
            "total_k_growth_pls_high": report.total_k_growth_pls_high,
            "total_value_delta_pls": report.total_value_delta_pls,
            "baseline_ts": report.baseline_ts,
            "current_ts": report.current_ts,
            "blocks_elapsed": report.blocks_elapsed,
            "per_pair": [asdict(d) for d in report.per_pair],
        },
        il=il,
        positions=[asdict(p) for p in positions],
    )


@router.get("/lp-fees/history", response_model=LPFeeHistoryResponse)
async def get_lp_fee_history(max_entries: int = 1000):
    history = load_history(max_entries=max_entries)
    baseline = load_baseline()
    baseline_k_map = (baseline or {}).get("baselines", {}) if baseline else {}
    deltas = compute_history_deltas(history, baseline_k_map) if baseline_k_map else []
    return LPFeeHistoryResponse(
        snapshots=history,
        deltas=deltas,
        count=len(history),
    )


@router.post("/lp-fees/reset-baseline", response_model=LPFeeResetResponse)
async def reset_lp_fee_baseline(request: Request, _: None = Depends(require_admin)):
    try:
        positions = scan_joey_lp_positions()
        save_baseline(positions)
        # Also record an initial history entry so the chart has an origin point.
        record_snapshot(positions)
    except Exception as exc:
        logger.exception("lp_fees.reset-baseline failed")
        raise HTTPException(status_code=500, detail=str(exc))
    return LPFeeResetResponse(
        ok=True,
        pairs=len(positions),
        total_value_pls=sum(p.value_pls for p in positions),
    )
