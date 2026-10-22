"""
NGX Algorithmic Trading Bot - CardinalStone Securities API Adapter
Implements asynchronous REST API client for CardinalStone trading gateway.
"""

import aiohttp
import asyncio
import hashlib
import hmac
import time
import logging
from typing import Optional, Dict, Any

from python_bot.broker_base import (
    BaseBroker,
    OrderBook,
    OrderBookLevel,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
)

logger = logging.getLogger("ngx_bot.cardinalstone")


class CardinalStoneBroker(BaseBroker):
    DEFAULT_BASE_URL = "https://trade.cardinalstone.com/api/v2"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        account_number: str,
        cscs_number: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.account_number = account_number
        self.cscs_number = cscs_number
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
        self._auth_token: Optional[str] = None

    async def connect(self) -> None:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "NGX-QuantBot/1.0",
        }
        self._session = aiohttp.ClientSession(
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        )
        try:
            await self._authenticate()
        except Exception:
            await self._session.close()
            self._session = None
            raise

    async def _authenticate(self) -> None:
        timestamp = str(int(time.time() * 1000))
        message = f"{self.api_key}:{timestamp}".encode("utf-8")
        signature = hmac.new(self.api_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

        payload = {
            "api_key": self.api_key,
            "timestamp": timestamp,
            "signature": signature,
            "account_number": self.account_number,
        }
        async with self._session.post(f"{self.base_url}/auth/token", json=payload) as resp:
            if resp.status != 200:
                raise RuntimeError(f"CardinalStone authentication failed with status {resp.status}.")
            data = await resp.json()
            token = data.get("access_token")
            if not token:
                raise RuntimeError("CardinalStone authentication response did not contain an access token.")
            self._auth_token = token

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._auth_token}",
            "X-CS-Account": self.account_number,
            "X-Timestamp": str(int(time.time() * 1000)),
        }

    async def disconnect(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_order_book(self, symbol: str) -> OrderBook:
        url = f"{self.base_url}/market/depth/{symbol}"
        async with self._session.get(url, headers=self._get_headers()) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Error fetching depth: status {resp.status}")
            data = await resp.json()

        bids = [OrderBookLevel(price=float(b["price"]), quantity=int(b["volume"])) for b in data.get("bids", [])]
        asks = [OrderBookLevel(price=float(a["price"]), quantity=int(a["volume"])) for a in data.get("asks", [])]
        ref = float(data.get("reference_price") or (asks[0].price if asks else 0.0))

        return OrderBook(symbol=symbol, bids=bids, asks=asks, reference_price=ref, timestamp=time.time())

    async def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        price: float,
        quantity: int,
    ) -> OrderResult:
        url = f"{self.base_url}/orders"
        payload = {
            "account_number": self.account_number,
            "symbol": symbol,
            "side": side.value,
            "order_type": order_type.value,
            "price": price,
            "quantity": quantity,
            "time_in_force": "DAY",
        }
        async with self._session.post(url, json=payload, headers=self._get_headers()) as resp:
            if resp.status not in (200, 201):
                err = await resp.text()
                raise RuntimeError(f"Order submission failed: {err}")
            res = await resp.json()

        return OrderResult(
            order_id=res["order_id"],
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            filled_quantity=res.get("filled_quantity", 0),
            average_fill_price=res.get("average_fill_price", 0.0),
            status=OrderStatus(res.get("status", "SUBMITTED")),
            fee_incurred=res.get("estimated_fee", price * quantity * 0.015),
            created_at=time.time(),
            updated_at=time.time(),
            raw_response=res,
        )

    async def get_order_status(self, order_id: str) -> OrderResult:
        url = f"{self.base_url}/orders/{order_id}"
        async with self._session.get(url, headers=self._get_headers()) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Order status failed: {resp.status}")
            res = await resp.json()

        return OrderResult(
            order_id=order_id,
            symbol=res["symbol"],
            side=OrderSide(res["side"]),
            order_type=OrderType(res["order_type"]),
            price=float(res["price"]),
            quantity=int(res["quantity"]),
            filled_quantity=int(res.get("filled_quantity", 0)),
            average_fill_price=float(res.get("average_fill_price", 0.0)),
            status=OrderStatus(res.get("status", "SUBMITTED")),
            fee_incurred=float(res.get("fee_incurred", 0.0)),
            created_at=float(res.get("created_at", time.time())),
            updated_at=float(res.get("updated_at", time.time())),
            raw_response=res,
        )

    async def cancel_order(self, order_id: str) -> bool:
        url = f"{self.base_url}/orders/{order_id}/cancel"
        async with self._session.post(url, headers=self._get_headers()) as resp:
            return resp.status in (200, 204)

    async def get_cash_balance(self) -> float:
        url = f"{self.base_url}/accounts/{self.account_number}/balance"
        async with self._session.get(url, headers=self._get_headers()) as resp:
            if resp.status != 200:
                raise RuntimeError(f"CardinalStone balance request failed with status {resp.status}.")
            data = await resp.json()
            return float(data["available_cash_naira"])
