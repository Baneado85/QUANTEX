import base64
import hashlib
import time
from typing import Any, Optional

import ccxt
import pandas as pd

from app.core.config import settings


class ExchangeError(Exception):
    pass


class ExchangeService:
    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}
        self._paper_orders: dict[str, list[dict]] = {}

    def get_client(
        self,
        exchange_id: str,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        sandbox: bool = True,
    ):
        cache_key = f"{exchange_id}:{bool(api_key)}:{sandbox}"
        if cache_key in self._clients and api_key is None:
            return self._clients[cache_key]

        if not hasattr(ccxt, exchange_id):
            raise ExchangeError(f"Exchange desconocido: {exchange_id}")

        client = getattr(ccxt, exchange_id)({
            "enableRateLimit": True,
            "options": {"defaultType": "future"},
        })
        if sandbox and hasattr(client, "set_sandbox_mode"):
            try:
                client.set_sandbox_mode(True)
            except Exception:
                pass
        if api_key and secret:
            client.apiKey = api_key
            client.secret = secret

        if api_key is None:
            self._clients[cache_key] = client
        return client

    def encrypt_api_key(self, plaintext: str) -> str:
        key = hashlib.sha256(settings.ENCRYPTION_KEY.encode("utf-8")).digest()
        cipher = _aes_cipher(key)
        nonce = cipher.nonce
        ciphertext = cipher.encrypt(plaintext.encode("utf-8"))
        return base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")

    def decrypt_api_key(self, token: str) -> str:
        raw = base64.urlsafe_b64decode(token.encode("utf-8"))
        key = hashlib.sha256(settings.ENCRYPTION_KEY.encode("utf-8")).digest()
        cipher = _aes_cipher(key)
        return cipher.decrypt(raw[len(cipher.nonce):]).decode("utf-8")

    def fetch_ohlcv(
        self,
        exchange_id: str,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 500,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
    ) -> pd.DataFrame:
        client = self.get_client(exchange_id, api_key, secret)
        try:
            rows = client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        except Exception as exc:
            raise ExchangeError(f"Error obteniendo OHLCV de {symbol}: {exc}") from exc

        if not rows:
            raise ExchangeError(f"{exchange_id} devolvió OHLCV vacío para {symbol}")

        df = pd.DataFrame(
            rows, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp")
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.dropna(subset=["open", "high", "low", "close"])

    def fetch_ticker(
        self,
        exchange_id: str,
        symbol: str,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
    ) -> dict:
        client = self.get_client(exchange_id, api_key, secret)
        try:
            ticker = client.fetch_ticker(symbol)
        except Exception as exc:
            raise ExchangeError(f"Error obteniendo ticker de {symbol}: {exc}") from exc

        return {
            "symbol": symbol,
            "exchange": exchange_id,
            "last": ticker.get("last"),
            "bid": ticker.get("bid"),
            "ask": ticker.get("ask"),
            "high": ticker.get("high"),
            "low": ticker.get("low"),
            "volume": ticker.get("baseVolume"),
            "change_pct": ticker.get("percentage"),
            "timestamp": ticker.get("timestamp"),
        }

    def list_symbols(self, exchange_id: str) -> list[str]:
        client = self.get_client(exchange_id)
        try:
            markets = client.load_markets()
        except Exception as exc:
            raise ExchangeError(f"Error cargando markets: {exc}") from exc
        return sorted(markets.keys())

    def validate_api_key(
        self, exchange_id: str, api_key: str, secret: str
    ) -> dict:
        client = self.get_client(exchange_id, api_key, secret, sandbox=False)
        try:
            client.fetch_balance()
        except Exception as exc:
            raise ExchangeError(f"API key inválida: {exc}") from exc
        return {"valid": True, "exchange": exchange_id}

    def create_order(
        self,
        exchange_id: str,
        symbol: str,
        side: str,
        quantity: float,
        api_key: Optional[str] = None,
        secret: Optional[str] = None,
        paper: bool = True,
    ) -> dict:
        if paper or settings.PAPER_TRADING:
            return self._create_paper_order(exchange_id, symbol, side, quantity)

        client = self.get_client(exchange_id, api_key, secret, sandbox=False)
        try:
            order = client.create_order(
                symbol, "market", side, quantity, params={}
            )
        except Exception as exc:
            raise ExchangeError(f"Error creando orden: {exc}") from exc

        return {
            "id": order.get("id"),
            "symbol": symbol,
            "side": side,
            "amount": order.get("amount"),
            "price": order.get("average") or order.get("price"),
            "status": order.get("status"),
            "paper": False,
        }

    def _create_paper_order(
        self, exchange_id: str, symbol: str, side: str, quantity: float
    ) -> dict:
        price = self.fetch_ticker(exchange_id, symbol)["last"]
        order_id = f"paper-{int(time.time() * 1000)}"
        order = {
            "id": order_id,
            "symbol": symbol,
            "side": side,
            "amount": quantity,
            "price": price,
            "status": "filled",
            "paper": True,
            "created_at": int(time.time() * 1000),
        }
        self._paper_orders.setdefault(symbol, []).append(order)
        return order


def _aes_cipher(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM(key)


exchange_service = ExchangeService()
