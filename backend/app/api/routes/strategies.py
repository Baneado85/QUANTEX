from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import Strategy, User
from app.services.exchange import ExchangeError, exchange_service
from app.strategies.mean_reversion import MeanReversionConfig, MeanReversionEngine

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


class StrategyCreate(BaseModel):
    name: str
    type: str = "mean_reversion"
    description: Optional[str] = None
    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    paper_trading: bool = True
    interval_seconds: int = 3600
    parameters: dict[str, Any] = Field(default_factory=dict)


class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    timeframe: Optional[str] = None
    paper_trading: Optional[bool] = None
    interval_seconds: Optional[int] = None
    parameters: Optional[dict[str, Any]] = None


class StrategyResponse(BaseModel):
    id: int
    name: str
    type: str
    description: Optional[str]
    exchange: str
    symbol: str
    timeframe: str
    status: str
    is_active: bool
    paper_trading: bool
    interval_seconds: int
    parameters: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class AnalyzeRequest(BaseModel):
    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    limit: int = 500
    parameters: dict[str, Any] = Field(default_factory=dict)


class BacktestRequest(AnalyzeRequest):
    initial_capital: float = 10_000.0


@router.post("", response_model=StrategyResponse, status_code=201)
async def create_strategy(
    payload: StrategyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    strategy = Strategy(
        user_id=current_user.id,
        name=payload.name,
        type=payload.type,
        description=payload.description,
        exchange=payload.exchange.lower(),
        symbol=payload.symbol,
        timeframe=payload.timeframe,
        paper_trading=payload.paper_trading,
        interval_seconds=payload.interval_seconds,
        status="stopped",
        parameters=payload.parameters,
    )
    db.add(strategy)
    await db.flush()
    await db.refresh(strategy)
    return strategy


@router.get("", response_model=list[StrategyResponse])
async def list_strategies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Strategy)
        .where(Strategy.user_id == current_user.id)
        .order_by(Strategy.id.desc())
    )
    return list(result.scalars().all())


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _get_owned(db, current_user.id, strategy_id)


@router.put("/{strategy_id}", response_model=StrategyResponse)
async def update_strategy(
    strategy_id: int,
    payload: StrategyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    strategy = await _get_owned(db, current_user.id, strategy_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(strategy, field, value)
    await db.flush()
    await db.refresh(strategy)
    return strategy


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    strategy = await _get_owned(db, current_user.id, strategy_id)
    await db.delete(strategy)
    return None


@router.post("/{strategy_id}/start", response_model=StrategyResponse)
async def start_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.strategy_runner import schedule_strategy

    strategy = await _get_owned(db, current_user.id, strategy_id)
    task_id = schedule_strategy(strategy.id, strategy.interval_seconds)
    strategy.status = "active"
    strategy.celery_task_id = task_id
    await db.flush()
    await db.refresh(strategy)
    return strategy


@router.post("/{strategy_id}/stop", response_model=StrategyResponse)
async def stop_strategy(
    strategy_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.strategy_runner import cancel_strategy

    strategy = await _get_owned(db, current_user.id, strategy_id)
    cancel_strategy(strategy.id, strategy.celery_task_id)
    strategy.status = "stopped"
    strategy.celery_task_id = None
    await db.flush()
    await db.refresh(strategy)
    return strategy


@router.post("/mean-reversion/analyze")
async def analyze_mean_reversion(
    payload: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
):
    engine = MeanReversionEngine(_build_config(payload))
    try:
        df = exchange_service.fetch_ohlcv(
            payload.exchange.lower(),
            payload.symbol,
            timeframe=payload.timeframe,
            limit=payload.limit,
        )
    except ExchangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = engine.analyze(df)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": result, "message": "ok"}


@router.post("/mean-reversion/backtest")
async def backtest_mean_reversion(
    payload: BacktestRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    config = _build_config(payload)
    engine = MeanReversionEngine(config)
    try:
        df = exchange_service.fetch_ohlcv(
            payload.exchange.lower(),
            payload.symbol,
            timeframe=payload.timeframe,
            limit=payload.limit,
        )
    except ExchangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = engine.backtest(df)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    from app.models.models import Backtest

    record = Backtest(
        user_id=current_user.id,
        name=f"Backtest {payload.symbol} {payload.timeframe}",
        exchange=payload.exchange.lower(),
        symbol=payload.symbol,
        start_date=df.index[0].to_pydatetime(),
        end_date=df.index[-1].to_pydatetime(),
        initial_capital=config.initial_capital,
        parameters=payload.parameters,
        results={
            "total_return_pct": result["total_return_pct"],
            "sharpe_ratio": result["sharpe_ratio"],
            "max_drawdown_pct": result["max_drawdown_pct"],
            "win_rate": result["win_rate"],
            "total_trades": result["total_trades"],
        },
        total_return=result["total_return_pct"],
        sharpe_ratio=result["sharpe_ratio"],
        max_drawdown=result["max_drawdown_pct"],
        win_rate=result["win_rate"],
        total_trades=result["total_trades"],
    )
    db.add(record)

    return {"data": result, "message": "ok"}


def _build_config(payload: AnalyzeRequest) -> MeanReversionConfig:
    params = dict(payload.parameters or {})
    params.setdefault("initial_capital", getattr(payload, "initial_capital", 10_000.0))
    allowed = set(MeanReversionConfig().to_dict().keys())
    filtered = {k: v for k, v in params.items() if k in allowed}
    return MeanReversionConfig(**filtered)


async def _get_owned(db: AsyncSession, user_id: int, strategy_id: int) -> Strategy:
    result = await db.execute(
        select(Strategy).where(
            Strategy.id == strategy_id, Strategy.user_id == user_id
        )
    )
    strategy = result.scalar_one_or_none()
    if strategy is None:
        raise HTTPException(status_code=404, detail="Estrategia no encontrada")
    return strategy
