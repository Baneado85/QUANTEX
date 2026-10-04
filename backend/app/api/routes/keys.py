from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import ExchangeApiKey, User
from app.services.exchange import ExchangeError, exchange_service

router = APIRouter(prefix="/api/keys", tags=["keys"])


class CreateKeyRequest(BaseModel):
    exchange: str
    api_key: str
    api_secret: str
    label: Optional[str] = None


class KeyResponse(BaseModel):
    id: int
    exchange: str
    label: Optional[str] = None
    key_preview: str
    is_active: bool
    last_used_at: Optional[datetime] = None
    created_at: datetime


def _preview(encrypted: str) -> str:
    return f"****{encrypted[-4:]}"


@router.post("", response_model=KeyResponse, status_code=201)
async def create_key(
    payload: CreateKeyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    record = ExchangeApiKey(
        user_id=current_user.id,
        exchange=payload.exchange.lower(),
        label=payload.label,
        encrypted_key=exchange_service.encrypt_api_key(payload.api_key),
        encrypted_secret=exchange_service.encrypt_api_key(payload.api_secret),
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return {
        "id": record.id,
        "exchange": record.exchange,
        "label": record.label,
        "key_preview": _preview(record.encrypted_key),
        "is_active": record.is_active,
        "last_used_at": record.last_used_at,
        "created_at": record.created_at,
    }


@router.get("", response_model=list[KeyResponse])
async def list_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExchangeApiKey)
        .where(ExchangeApiKey.user_id == current_user.id)
        .order_by(ExchangeApiKey.id.desc())
    )
    keys = result.scalars().all()
    return [
        {
            "id": k.id,
            "exchange": k.exchange,
            "label": k.label,
            "key_preview": _preview(k.encrypted_key),
            "is_active": k.is_active,
            "last_used_at": k.last_used_at,
            "created_at": k.created_at,
        }
        for k in keys
    ]


@router.delete("/{key_id}", status_code=204)
async def delete_key(
    key_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExchangeApiKey).where(
            ExchangeApiKey.id == key_id,
            ExchangeApiKey.user_id == current_user.id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="API key no encontrada")
    await db.delete(record)
    return None


@router.post("/{key_id}/validate")
async def validate_key(
    key_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExchangeApiKey).where(
            ExchangeApiKey.id == key_id,
            ExchangeApiKey.user_id == current_user.id,
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="API key no encontrada")

    try:
        outcome = exchange_service.validate_api_key(
            record.exchange,
            exchange_service.decrypt_api_key(record.encrypted_key),
            exchange_service.decrypt_api_key(record.encrypted_secret),
        )
    except ExchangeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record.last_used_at = datetime.now(timezone.utc)
    return outcome
