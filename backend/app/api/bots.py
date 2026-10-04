from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional

from app.core.database import get_db
from app.models.models import Strategy, User, ExchangeApiKey
from app.schemas.schemas import StrategyCreate, StrategyResponse

router = APIRouter()

# Aquí en producción se usaría un middleware de autenticación para obtener el usuario actual
# Por ahora simulamos el user_id = 1
async def get_current_user() -> int:
    return 1

@router.post("/", response_model=StrategyResponse)
async def create_bot(bot_in: StrategyCreate, db: AsyncSession = Depends(get_db), current_user_id: int = Depends(get_current_user)):
    """Crea una nueva configuración de estrategia de trading."""

    # Validar que la API Key exista y pertenezca al usuario
    stmt = select(ExchangeApiKey).where(
        ExchangeApiKey.id == bot_in.api_key_id,
        ExchangeApiKey.user_id == current_user_id
    )
    result = await db.execute(stmt)
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API Key no encontrada o no válida.")

    # Los parámetros específicos del bot se guardan en el JSONB parameters
    parameters: dict = dict(bot_in.parameters or {})
    if bot_in.bollinger_period is not None:
        parameters["bollinger_period"] = bot_in.bollinger_period
    if bot_in.bollinger_std_dev is not None:
        parameters["bollinger_std_dev"] = bot_in.bollinger_std_dev
    if bot_in.allocation_percentage is not None:
        parameters["allocation_percentage"] = bot_in.allocation_percentage
    if bot_in.stop_loss_pct is not None:
        parameters["stop_loss_pct"] = bot_in.stop_loss_pct
    if bot_in.take_profit_pct is not None:
        parameters["take_profit_pct"] = bot_in.take_profit_pct

    # Crear la estrategia
    new_strategy = Strategy(
        user_id=current_user_id,
        name=bot_in.name,
        symbol=bot_in.symbol,
        timeframe=bot_in.timeframe,
        parameters=parameters,
        is_active=False,  # Inicia apagado
        status="stopped",
        paper_trading=bot_in.paper_trading,
    )

    db.add(new_strategy)
    await db.commit()
    await db.refresh(new_strategy)
    return new_strategy

@router.get("/", response_model=List[StrategyResponse])
async def list_bots(db: AsyncSession = Depends(get_db), current_user_id: int = Depends(get_current_user)):
    """Lista todas las estrategias del usuario."""
    stmt = select(Strategy).where(Strategy.user_id == current_user_id)
    result = await db.execute(stmt)
    bots = result.scalars().all()
    return bots

@router.post("/{bot_id}/start")
async def start_bot(bot_id: int, db: AsyncSession = Depends(get_db), current_user_id: int = Depends(get_current_user)):
    """Activa una estrategia y lanza la tarea asíncrona de Celery."""
    stmt = select(Strategy).where(Strategy.id == bot_id, Strategy.user_id == current_user_id)
    result = await db.execute(stmt)
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado.")

    bot.is_active = True
    bot.status = "active"
    await db.commit()

    # Aquí es donde llamaríamos a Celery:
    # from app.tasks.trading_tasks import run_trading_bot
    # run_trading_bot.delay(bot.id)

    return {"message": f"Bot {bot.name} iniciado correctamente."}

@router.post("/{bot_id}/stop")
async def stop_bot(bot_id: int, db: AsyncSession = Depends(get_db), current_user_id: int = Depends(get_current_user)):
    """Detiene una estrategia de trading."""
    stmt = select(Strategy).where(Strategy.id == bot_id, Strategy.user_id == current_user_id)
    result = await db.execute(stmt)
    bot = result.scalar_one_or_none()

    if not bot:
        raise HTTPException(status_code=404, detail="Bot no encontrado.")

    bot.is_active = False
    bot.status = "stopped"
    await db.commit()
    return {"message": f"Bot {bot.name} detenido."}
