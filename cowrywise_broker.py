"""
NGX Algorithmic Trading Bot - Cowrywise API Adapter
Implements asynchronous client for Cowrywise investment & brokerage infrastructure.
"""

import aiohttp
import asyncio
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

logger = logging.getLogger("ngx_bot.cowrywise")


class CowrywiseBroker(BaseBroker):
    DEFAULT_BASE_URL = "https://api.cowrywise.com/v1"

    def __init__(
        self,
        api_key: str,
        account_id: str,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key
        self.account_id = account_id
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> None:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Cowrywise-Account": self.account_id,
        }
        self._session = aiohttp.ClientSession(
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        )
        logger.info("Connected to Cowrywise Brokerage Gateway.")

    async def disconnect(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_order_book(self, symbol: str) -> OrderBook:
        url = f"{self.base_url}/stocks/{symbol}/quotes"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Cowrywise quote failed for {symbol}: {resp.status}")
            data = await resp.json()

        bids = [OrderBookLevel(price=float(b["price"]), quantity=int(b["volume"])) for b in data.get("bids", [])]
        asks = [OrderBookLevel(price=float(a["price"]), quantity=int(a["volume"])) for a in data.get("asks", [])]
        ref = float(data.get("last_price") or (asks[0].price if asks else 0.0))

        # Require actual market time and a previous close; local receipt time can
        # make a stale quote appear fresh. Field mappings still need sandbox verification.
        return OrderBook(symbol=symbol, bids=bids, asks=asks, reference_price=ref,
                         timestamp=float(data.get("timestamp", 0)),
                         previous_close_price=(float(data["previous_close_price"])
                                               if data.get("previous_close_price") is not None else None))

    async def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        price: float,
        quantity: int,
    ) -> OrderResult:
        url = f"{self.base_url}/stocks/orders"
        payload = {
            "symbol": symbol,
            "side": side.value.lower(),
            "type": order_type.value.lower(),
            "price": price,
            "units": quantity,
        }
        async with self._session.post(url, json=payload) as resp:
            if resp.status not in (200, 201):
                err = await resp.text()
                raise RuntimeError(f"Cowrywise order error: {err}")
            res = await resp.json()

        return OrderResult(
            order_id=res["id"],
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            filled_quantity=0,
            average_fill_price=0.0,
            status=OrderStatus.SUBMITTED,
            fee_incurred=float(res.get("fees", price * quantity * 0.015)),
            created_at=time.time(),
            updated_at=time.time(),
            raw_response=res,
        )

    async def get_order_status(self, order_id: str) -> OrderResult:
        url = f"{self.base_url}/stocks/orders/{order_id}"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Order status failed: {resp.status}")
            res = await resp.json()

        return OrderResult(
            order_id=order_id,
            symbol=res["symbol"],
            side=OrderSide(res["side"].upper()),
            order_type=OrderType(res["type"].upper()),
            price=float(res["price"]),
            quantity=int(res["units"]),
            filled_quantity=int(res.get("filled_units", 0)),
            average_fill_price=float(res.get("average_price", 0.0)),
            status=OrderStatus(res.get("status", "SUBMITTED").upper()),
            fee_incurred=float(res.get("fees", 0.0)),
            created_at=float(res.get("created_at", time.time())),
            updated_at=float(res.get("updated_at", time.time())),
            raw_response=res,
        )

    async def cancel_order(self, order_id: str) -> bool:
        url = f"{self.base_url}/stocks/orders/{order_id}/cancel"
        async with self._session.post(url) as resp:
            return resp.status in (200, 204)

    async def get_cash_balance(self) -> float:
        url = f"{self.base_url}/wallets/naira"
        async with self._session.get(url) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Cowrywise balance request failed with status {resp.status}.")
            data = await resp.json()
            return float(data["balance"])
