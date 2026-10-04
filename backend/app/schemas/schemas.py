from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Any
from datetime import datetime
from enum import Enum

class ExchangeType(str, Enum):
    BINANCE = "binance"
    BYBIT = "bybit"
    OKX = "okx"
    KRAKEN = "kraken"

class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

class TradeStatus(str, Enum):
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    PARTIALLY_FILLED = "partially_filled"

# --- USER SCHEMAS ---
class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

# --- API KEY SCHEMAS ---
class APIKeyCreate(BaseModel):
    exchange: ExchangeType
    api_key: str
    api_secret: str

class APIKeyResponse(BaseModel):
    id: int
    exchange: ExchangeType
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

# --- STRATEGY SCHEMAS ---
class StrategyCreate(BaseModel):
    api_key_id: Optional[int] = None
    name: str
    type: str = "mean_reversion"
    description: Optional[str] = None
    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    paper_trading: bool = True
    interval_seconds: int = 3600
    parameters: dict[str, Any] = Field(default_factory=dict)
    bollinger_period: Optional[int] = None
    bollinger_std_dev: Optional[float] = None
    allocation_percentage: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None

class StrategyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    exchange: Optional[str] = None
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    interval_seconds: Optional[int] = None
    parameters: Optional[dict[str, Any]] = None
    is_public: Optional[bool] = None
    slug: Optional[str] = None

class StrategyResponse(BaseModel):
    id: int
    user_id: int
    name: str
    type: str
    description: Optional[str] = None
    exchange: str
    symbol: str
    timeframe: str
    status: str
    is_active: bool
    paper_trading: bool
    interval_seconds: int
    parameters: dict[str, Any]
    is_public: bool
    slug: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# --- TRADE SCHEMAS ---
class TradeResponse(BaseModel):
    id: int
    strategy_id: Optional[int] = None
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
