from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.models import Strategy, Trade

router = APIRouter()


class PublicStrategyResponse(BaseModel):
    id: int
    name: str
    type: str
    description: Optional[str] = None
    exchange: str
    symbol: str
    timeframe: str
    status: str
    is_active: bool
    paper_trading: bool
    is_public: bool
    slug: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    class Config:
        from_attributes = True


class TradePublicResponse(BaseModel):
    id: int
    exchange: str
    symbol: str
    side: str
    quantity: float
    price: float
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    order_id: Optional[str] = None
    order_type: str
    status: str
    z_score_at_entry: Optional[float] = None
    pnl: Optional[float] = None
    fee: float
    executed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TrackRecordMetrics(BaseModel):
    total_pnl: float
    win_rate: float
    max_drawdown: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win: float
    avg_loss: float


class TrackRecordResponse(BaseModel):
    strategy: PublicStrategyResponse
    metrics: TrackRecordMetrics
    trades: list[TradePublicResponse]


def _compute_max_drawdown(pnls: list[float]) -> float:
    """Calcula el máximo drawdown a partir de una serie de PnLs acumulados."""
    if not pnls:
        return 0.0
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        drawdown = peak - cumulative
        if drawdown > max_dd:
            max_dd = drawdown
    return round(max_dd, 8)


def _serialize_trade(trade: Trade) -> TradePublicResponse:
    return TradePublicResponse(
        id=trade.id,
        exchange=trade.exchange,
        symbol=trade.symbol,
        side=trade.side,
        quantity=float(trade.quantity or 0),
        price=float(trade.price or 0),
        entry_price=float(trade.entry_price) if trade.entry_price is not None else None,
        exit_price=float(trade.exit_price) if trade.exit_price is not None else None,
        order_id=trade.order_id,
        order_type=trade.order_type,
        status=trade.status,
        z_score_at_entry=(
            float(trade.z_score_at_entry) if trade.z_score_at_entry is not None else None
        ),
        pnl=float(trade.pnl) if trade.pnl is not None else None,
        fee=float(trade.fee or 0),
        executed_at=trade.executed_at,
        created_at=trade.created_at,
    )


@router.get("/strategies", response_model=list[PublicStrategyResponse])
async def list_public_strategies(db: AsyncSession = Depends(get_db)):
    """Devuelve todas las estrategias públicas (track record visible)."""
    stmt = (
        select(Strategy)
        .where(Strategy.is_public.is_(True))
        .order_by(Strategy.created_at.desc())
    )
    result = await db.execute(stmt)
    strategies = result.scalars().all()
    return [
        PublicStrategyResponse(
            id=s.id,
            name=s.name,
            type=s.type,
            description=s.description,
            exchange=s.exchange,
            symbol=s.symbol,
            timeframe=s.timeframe,
            status=s.status,
            is_active=s.is_active,
            paper_trading=s.paper_trading,
            is_public=s.is_public,
            slug=s.slug,
            parameters=s.parameters or {},
            created_at=s.created_at,
        )
        for s in strategies
    ]


@router.get("/strategies/{strategy_id}/track-record", response_model=TrackRecordResponse)
async def get_track_record(strategy_id: int, db: AsyncSession = Depends(get_db)):
    """Devuelve las métricas y el historial de operaciones de una estrategia pública."""
    stmt = select(Strategy).where(Strategy.id == strategy_id)
    result = await db.execute(stmt)
    strategy = result.scalar_one_or_none()

    if strategy is None:
        raise HTTPException(status_code=404, detail="Estrategia no encontrada.")

    if not strategy.is_public:
        raise HTTPException(
            status_code=403,
            detail="Esta estrategia no tiene track record público.",
        )

    trade_stmt = (
        select(Trade)
        .where(Trade.strategy_id == strategy_id)
        .order_by(Trade.created_at.asc())
    )
    trade_result = await db.execute(trade_stmt)
    trades = trade_result.scalars().all()

    # --- Cálculo de métricas ---
    closed_trades = [t for t in trades if t.pnl is not None]

    if closed_trades:
        pnls = [float(t.pnl) for t in closed_trades]
        total_pnl = round(sum(pnls), 8)
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        win_rate = round(len(wins) / len(pnls) * 100, 2)
        max_drawdown = _compute_max_drawdown(pnls)
        avg_win = round(sum(wins) / len(wins), 8) if wins else 0.0
        avg_loss = round(sum(losses) / len(losses), 8) if losses else 0.0

        metrics = TrackRecordMetrics(
            total_pnl=total_pnl,
            win_rate=win_rate,
            max_drawdown=max_drawdown,
            total_trades=len(closed_trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            avg_win=avg_win,
            avg_loss=avg_loss,
        )
    else:
        metrics = TrackRecordMetrics(
            total_pnl=0.0,
            win_rate=0.0,
            max_drawdown=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            avg_win=0.0,
            avg_loss=0.0,
        )

    strategy_response = PublicStrategyResponse(
        id=strategy.id,
        name=strategy.name,
        type=strategy.type,
        description=strategy.description,
        exchange=strategy.exchange,
        symbol=strategy.symbol,
        timeframe=strategy.timeframe,
        status=strategy.status,
        is_active=strategy.is_active,
        paper_trading=strategy.paper_trading,
        is_public=strategy.is_public,
        slug=strategy.slug,
        parameters=strategy.parameters or {},
        created_at=strategy.created_at,
    )

    return TrackRecordResponse(
        strategy=strategy_response,
        metrics=metrics,
        trades=[_serialize_trade(t) for t in trades],
    )
