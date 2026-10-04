from typing import Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from app.services.exchange import ExchangeError, exchange_service

router = APIRouter(prefix="/api/market", tags=["market"])

_ALLOWED_TF = {"1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"}


@router.get("/ticker/{exchange}/{symbol}")
async def get_ticker(exchange: str, symbol: str):
    try:
        return {"data": exchange_service.fetch_ticker(exchange.lower(), symbol)}
    except ExchangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/ohlcv/{exchange}/{symbol}")
async def get_ohlcv(
    exchange: str,
    symbol: str,
    tf: str = Query("1h", description="Timeframe"),
    limit: int = Query(500, ge=10, le=1000),
):
    if tf not in _ALLOWED_TF:
        raise HTTPException(
            status_code=422,
            detail=f"timeframe inválido, usa uno de: {sorted(_ALLOWED_TF)}",
        )
    try:
        df = exchange_service.fetch_ohlcv(
            exchange.lower(), symbol, timeframe=tf, limit=limit
        )
    except ExchangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    df = df.tail(limit)
    return {
        "data": {
            "exchange": exchange.lower(),
            "symbol": symbol,
            "timeframe": tf,
            "candles": [
                {
                    "time": int(ts.timestamp()),
                    "open": float(row.open),
                    "high": float(row.high),
                    "low": float(row.low),
                    "close": float(row.close),
                    "volume": float(row.volume),
                }
                for ts, row in df.iterrows()
            ],
        }
    }


@router.get("/symbols/{exchange}")
async def get_symbols(exchange: str, quote: Optional[str] = Query("USDT")):
    try:
        symbols = exchange_service.list_symbols(exchange.lower())
    except ExchangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if quote:
        symbols = [s for s in symbols if s.endswith(f"/{quote}")]
    return {"data": {"exchange": exchange.lower(), "symbols": symbols[:500]}}
