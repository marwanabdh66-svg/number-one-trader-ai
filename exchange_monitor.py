"""Read-only Binance Spot account monitor for NUMBER ONE TRADER AI.

This module intentionally exposes GET-only operations. It cannot place, cancel,
or modify orders and never requests withdrawal permissions.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from typing import Any
from urllib.parse import urlencode

import requests


class ExchangeMonitorError(RuntimeError):
    """Safe, user-facing exchange monitor error."""


class BinanceReadOnlyMonitor:
    """Minimal Binance Spot REST client limited to read-only endpoints."""

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        *,
        testnet: bool | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("BINANCE_API_KEY", "")).strip()
        self.api_secret = (api_secret if api_secret is not None else os.getenv("BINANCE_API_SECRET", "")).strip()
        use_testnet = (
            testnet if testnet is not None
            else os.getenv("BINANCE_TESTNET", "false").lower() in {"1", "true", "yes"}
        )
        self.base_url = "https://testnet.binance.vision" if use_testnet else "https://api.binance.com"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "NUMBER-ONE-TRADER-AI/1.0",
            "Accept": "application/json",
        })
        if self.api_key:
            self.session.headers["X-MBX-APIKEY"] = self.api_key

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _get(self, path: str, *, signed: bool = False, params: dict[str, Any] | None = None) -> Any:
        query = dict(params or {})
        if signed:
            if not self.configured:
                raise ExchangeMonitorError(
                    "لم يتم إعداد مفاتيح Binance. أضف مفتاح API والسر إلى أسرار الخادم."
                )
            query["timestamp"] = int(time.time() * 1000)
            query["recvWindow"] = 5000
            payload = urlencode(query)
            query["signature"] = hmac.new(
                self.api_secret.encode("utf-8"),
                payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

        try:
            response = self.session.get(
                self.base_url + path,
                params=query,
                timeout=self.timeout,
            )
            if response.status_code in (401, 403):
                raise ExchangeMonitorError(
                    "رفضت Binance الوصول. تحقق من المفتاح، وصلاحية القراءة، وقيود عنوان IP."
                )
            response.raise_for_status()
            return response.json()
        except ExchangeMonitorError:
            raise
        except requests.Timeout as exc:
            raise ExchangeMonitorError("انتهت مهلة الاتصال بمنصة Binance.") from exc
        except requests.RequestException as exc:
            # Do not expose request URLs, headers, signatures, or credentials.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 400:
                raise ExchangeMonitorError(
                    "رفضت Binance الطلب. تحقق من صلاحية المفتاح ووقت الخادم."
                ) from exc
            raise ExchangeMonitorError("تعذر الاتصال بمنصة Binance حالياً.") from exc
        except ValueError as exc:
            raise ExchangeMonitorError("وصل رد غير مفهوم من منصة Binance.") from exc

    def ping(self) -> bool:
        """Check public exchange connectivity; no credentials required."""
        self._get("/api/v3/ping")
        return True

    def account(self) -> dict[str, Any]:
        """Return spot balances and account permissions from a signed GET."""
        raw = self._get("/api/v3/account", signed=True)
        balances = []
        for item in raw.get("balances", []):
            free = float(item.get("free", 0) or 0)
            locked = float(item.get("locked", 0) or 0)
            if free or locked:
                balances.append({
                    "asset": str(item.get("asset", "")),
                    "free": free,
                    "locked": locked,
                    "total": free + locked,
                })
        permissions = raw.get("permissions", [])
        return {
            "can_trade": bool(raw.get("canTrade", False)),
            "can_withdraw": bool(raw.get("canWithdraw", False)),
            "can_deposit": bool(raw.get("canDeposit", False)),
            "account_type": raw.get("accountType", "SPOT"),
            "permissions": permissions,
            "balances": balances,
            "update_time": raw.get("updateTime"),
        }

    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Read open spot orders. This method never changes an order."""
        params: dict[str, Any] = {}
        if symbol:
            normalized = symbol.strip().upper()
            if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized):
                raise ExchangeMonitorError("رمز العملة غير صالح.")
            params["symbol"] = normalized
        rows = self._get("/api/v3/openOrders", signed=True, params=params)
        return [{
            "symbol": row.get("symbol"),
            "order_id": row.get("orderId"),
            "side": row.get("side"),
            "type": row.get("type"),
            "status": row.get("status"),
            "price": row.get("price"),
            "orig_qty": row.get("origQty"),
            "executed_qty": row.get("executedQty"),
            "time": row.get("time"),
        } for row in rows]

    def recent_trades(self, symbol: str, limit: int = 20) -> list[dict[str, Any]]:
        """Read the user's recent fills for one symbol."""
        normalized = symbol.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized):
            raise ExchangeMonitorError("رمز العملة غير صالح.")
        safe_limit = max(1, min(int(limit), 100))
        rows = self._get(
            "/api/v3/myTrades",
            signed=True,
            params={"symbol": normalized, "limit": safe_limit},
        )
        return [{
            "symbol": row.get("symbol"),
            "side": "شراء" if row.get("isBuyer") else "بيع",
            "price": row.get("price"),
            "quantity": row.get("qty"),
            "quote_quantity": row.get("quoteQty"),
            "commission": row.get("commission"),
            "commission_asset": row.get("commissionAsset"),
            "time": row.get("time"),
        } for row in rows]

    def market_price(self, symbol: str) -> float:
        """Read a public spot ticker price."""
        normalized = symbol.strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized):
            raise ExchangeMonitorError("رمز العملة غير صالح.")
        raw = self._get("/api/v3/ticker/price", params={"symbol": normalized})
        return float(raw["price"])
