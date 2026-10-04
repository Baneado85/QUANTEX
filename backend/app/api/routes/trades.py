from datetime import datetime
from typing import Optional

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import StrategyLog, Trade, User

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("")
async def list_trades(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Trade).where(Trade.user_id == current_user.id)
    if symbol:
        query = query.where(Trade.symbol == symbol)
    if status:
        query = query.where(Trade.status == status)

    result = await db.execute(
        query.order_by(Trade.created_at.desc()).offset(skip).limit(limit)
    )
    trades = result.scalars().all()
    return {
        "data": [_serialize(t) for t in trades],
        "message": "ok",
        "meta": {"skip": skip, "limit": limit, "count": len(trades)},
    }


@router.get("/open")
async def open_positions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Trade).where(
            Trade.user_id == current_user.id,
            Trade.status == "open",
        )
    )
    trades = result.scalars().all()
    return {"data": [_serialize(t) for t in trades], "message": "ok"}


@router.get("/stats")
async def trade_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Trade).where(
            Trade.user_id == current_user.id,
            Trade.pnl.isnot(None),
        )
    )
    trades = result.scalars().all()

    if not trades:
        return {
            "data": {
                "total_pnl": 0.0,
                "win_rate": 0.0,
                "sharpe": 0.0,
                "total_trades": 0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
            },
            "message": "ok",
        }

    pnls = np.array([float(t.pnl or 0) for t in trades])
    wins = pnls[pnls > 0]
    mean = float(pnls.mean())
    std = float(pnls.std(ddof=0))
    sharpe = float(mean / std * np.sqrt(365)) if std > 0 else 0.0

    return {
        "data": {
            "total_pnl": float(pnls.sum()),
            "win_rate": float(len(wins) / len(pnls) * 100),
            "sharpe": sharpe,
            "total_trades": len(pnls),
            "best_trade": float(pnls.max()),
            "worst_trade": float(pnls.min()),
        },
        "message": "ok",
    }


@router.get("/logs")
async def list_logs(
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StrategyLog)
        .where(StrategyLog.user_id == current_user.id)
        .order_by(StrategyLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()
    return {
        "data": [
            {
                "id": log.id,
                "strategy_id": log.strategy_id,
                "level": log.level,
                "message": log.message,
                "context": log.context,
                "created_at": log.created_at,
            }
            for log in logs
        ],
        "message": "ok",
    }


def _serialize(trade: Trade) -> dict:
    return {
        "id": trade.id,
        "strategy_id": trade.strategy_id,
        "exchange": trade.exchange,
        "symbol": trade.symbol,
        "side": trade.side,
        "quantity": float(trade.quantity or 0),
        "price": float(trade.price or 0),
        "entry_price": float(trade.entry_price) if trade.entry_price is not None else None,
        "exit_price": float(trade.exit_price) if trade.exit_price is not None else None,
        "order_id": trade.order_id,
        "order_type": trade.order_type,
        "status": trade.status,
        "z_score_at_entry": (
            float(trade.z_score_at_entry)
            if trade.z_score_at_entry is not None
            else None
        ),
        "pnl": float(trade.pnl) if trade.pnl is not None else None,
        "fee": float(trade.fee or 0),
        "executed_at": trade.executed_at,
        "created_at": trade.created_at,
    }
