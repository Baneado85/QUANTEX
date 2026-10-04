from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    api_keys: Mapped[list["ExchangeApiKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    strategies: Mapped[list["Strategy"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    trades: Mapped[list["Trade"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ExchangeApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    exchange: Mapped[str] = mapped_column(String(50))
    label: Mapped[Optional[str]] = mapped_column(String(100))
    encrypted_key: Mapped[str] = mapped_column(Text)
    encrypted_secret: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="api_keys")


class Strategy(Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(50), default="mean_reversion")
    description: Mapped[Optional[str]] = mapped_column(Text)
    exchange: Mapped[str] = mapped_column(String(50), default="binance")
    symbol: Mapped[str] = mapped_column(String(20), default="BTC/USDT")
    timeframe: Mapped[str] = mapped_column(String(10), default="1h")
    status: Mapped[str] = mapped_column(String(20), default="stopped")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    paper_trading: Mapped[bool] = mapped_column(Boolean, default=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    slug: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(100))
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    slug: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="strategies")
    trades: Mapped[list["Trade"]] = relationship(back_populates="strategy")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    strategy_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("strategies.id", ondelete="SET NULL"), index=True
    )
    exchange: Mapped[str] = mapped_column(String(50))
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[float] = mapped_column(Numeric(20, 8))
    price: Mapped[float] = mapped_column(Numeric(20, 8))
    entry_price: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))
    exit_price: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))
    order_id: Mapped[Optional[str]] = mapped_column(String(100))
    order_type: Mapped[str] = mapped_column(String(20), default="market")
    status: Mapped[str] = mapped_column(String(20), default="filled", index=True)
    z_score_at_entry: Mapped[Optional[float]] = mapped_column(Numeric(10, 6))
    pnl: Mapped[Optional[float]] = mapped_column(Numeric(20, 8))
    fee: Mapped[float] = mapped_column(Numeric(20, 8), default=0)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="trades")
    strategy: Mapped[Optional["Strategy"]] = relationship(back_populates="trades")


class StrategyLog(Base):
    __tablename__ = "logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    strategy_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("strategies.id", ondelete="CASCADE"), index=True
    )
    level: Mapped[str] = mapped_column(String(20), default="INFO", index=True)
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Backtest(Base):
    __tablename__ = "backtests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    strategy_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("strategies.id", ondelete="SET NULL")
    )
    name: Mapped[Optional[str]] = mapped_column(String(100))
    exchange: Mapped[str] = mapped_column(String(50))
    symbol: Mapped[str] = mapped_column(String(20))
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    initial_capital: Mapped[float] = mapped_column(Numeric(20, 2))
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)
    results: Mapped[Optional[dict]] = mapped_column(JSONB)
    total_return: Mapped[Optional[float]] = mapped_column(Float)
    sharpe_ratio: Mapped[Optional[float]] = mapped_column(Float)
    max_drawdown: Mapped[Optional[float]] = mapped_column(Float)
    win_rate: Mapped[Optional[float]] = mapped_column(Float)
    total_trades: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MarketData(Base):
    __tablename__ = "market_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(50), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(10))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    open: Mapped[float] = mapped_column(Numeric(20, 8))
    high: Mapped[float] = mapped_column(Numeric(20, 8))
    low: Mapped[float] = mapped_column(Numeric(20, 8))
    close: Mapped[float] = mapped_column(Numeric(20, 8))
    volume: Mapped[float] = mapped_column(Numeric(20, 8))
