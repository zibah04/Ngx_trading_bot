"""
NGX Algorithmic Trading Bot - Realistic Mock Broker Simulator
Simulates live Level-2 order book depth, liquidity conditions, and realistic fill latency.
"""

import asyncio
import time
import uuid
import random
from typing import Dict, List, Optional
from python_bot.broker_base import (
    BaseBroker,
    OrderBook,
    OrderBookLevel,
    OrderResult,
    OrderSide,
    OrderStatus,
    OrderType,
)


class MockBroker(BaseBroker):
    INITIAL_STOCKS = {
        "DANGCEM": 750.00,
        "MTNN": 240.00,
        "ACCESSCORP": 22.50,
        "GTCO": 48.20,
        "ZENITHBANK": 41.50,
        "AIRTELAFRI": 1950.00,
    }

    def __init__(self, initial_cash_naira: float = 2_000_000.0):
        if initial_cash_naira <= 0:
            raise ValueError("Initial cash must be positive.")
        self.cash_balance = initial_cash_naira
        self.reference_prices: Dict[str, float] = self.INITIAL_STOCKS.copy()
        self.active_orders: Dict[str, OrderResult] = {}
        self.liquidity_override: Dict[str, bool] = {s: True for s in self.INITIAL_STOCKS}
        self.portfolio: Dict[str, int] = {s: 0 for s in self.INITIAL_STOCKS}
        self._market_task: Optional[asyncio.Task] = None
        self._connected = False

    async def connect(self) -> None:
        self._connected = True
        self._market_task = asyncio.create_task(self._market_price_oscillator())

    async def disconnect(self) -> None:
        self._connected = False
        if self._market_task:
            self._market_task.cancel()
            try:
                await self._market_task
            except asyncio.CancelledError:
                pass

    def set_liquidity(self, symbol: str, is_liquid: bool) -> None:
        self.liquidity_override[symbol] = is_liquid

    def _apply_fill(self, order: OrderResult, filled_quantity: int, timestamp: float) -> None:
        additional_quantity = filled_quantity - order.filled_quantity
        if additional_quantity <= 0:
            return

        order.filled_quantity = filled_quantity
        order.average_fill_price = order.price
        order.status = (
            OrderStatus.FILLED
            if filled_quantity == order.quantity
            else OrderStatus.PARTIALLY_FILLED
        )
        order.updated_at = timestamp
        gross_value = round(order.price * additional_quantity, 2)
        fee = round(gross_value * 0.015, 2)
        order.fee_incurred += fee

        if order.side == OrderSide.BUY:
            self.portfolio[order.symbol] = self.portfolio.get(order.symbol, 0) + additional_quantity
        else:
            self.cash_balance += gross_value - fee
            self.portfolio[order.symbol] = self.portfolio.get(order.symbol, 0) - additional_quantity

    async def _market_price_oscillator(self) -> None:
        while self._connected:
            try:
                await asyncio.sleep(0.8)
                for symbol in self.reference_prices:
                    drift = random.uniform(-0.004, 0.004)
                    current = self.reference_prices[symbol]
                    new_price = round(max(1.0, current * (1 + drift)), 2)
                    self.reference_prices[symbol] = new_price

                now = time.time()
                for order in list(self.active_orders.values()):
                    if order.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED):
                        curr_ref = self.reference_prices.get(order.symbol, order.price)

                        if order.side == OrderSide.BUY:
                            if curr_ref <= order.price * 1.002:
                                if order.status == OrderStatus.SUBMITTED and random.random() < 0.4:
                                    partial_qty = order.quantity // 2
                                    if partial_qty > 0 and partial_qty < order.quantity:
                                        self._apply_fill(order, partial_qty, now)
                                        continue

                                self._apply_fill(order, order.quantity, now)

                        elif order.side == OrderSide.SELL:
                            if curr_ref >= order.price * 0.998:
                                self._apply_fill(order, order.quantity, now)

            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(1.0)

    async def get_order_book(self, symbol: str) -> OrderBook:
        ref = self.reference_prices.get(symbol, 100.0)

        if not self.liquidity_override.get(symbol, True):
            return OrderBook(symbol=symbol, bids=[], asks=[], reference_price=ref, timestamp=time.time())

        spread_kobo = max(0.05, round(ref * 0.003, 2))
        best_bid = round(ref - (spread_kobo / 2), 2)
        best_ask = round(ref + (spread_kobo / 2), 2)

        bids = [
            OrderBookLevel(price=round(best_bid - (i * 0.10), 2), quantity=random.randint(5_000, 45_000))
            for i in range(5)
        ]
        asks = [
            OrderBookLevel(price=round(best_ask + (i * 0.10), 2), quantity=random.randint(5_000, 45_000))
            for i in range(5)
        ]

        return OrderBook(symbol=symbol, bids=bids, asks=asks, reference_price=ref, timestamp=time.time())

    async def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        price: float,
        quantity: int,
    ) -> OrderResult:
        if quantity <= 0:
            raise ValueError(f"Quantity must be a positive integer, got {quantity}")

        fee_pct = 0.015
        gross_value = round(price * quantity, 2)
        fee = round(gross_value * fee_pct, 2)
        total_outlay = gross_value + fee

        if side == OrderSide.BUY:
            if self.cash_balance < total_outlay:
                raise ValueError(
                    f"Insufficient funds: Required ₦{total_outlay:,.2f} (including fee ₦{fee:,.2f}), Available: ₦{self.cash_balance:,.2f}"
                )
            self.cash_balance -= total_outlay
        else:
            reserved_quantity = sum(
                active.quantity - active.filled_quantity
                for active in self.active_orders.values()
                if active.symbol == symbol
                and active.side == OrderSide.SELL
                and active.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED)
            )
            available_quantity = self.portfolio.get(symbol, 0) - reserved_quantity
            if quantity > available_quantity:
                raise ValueError(
                    f"Insufficient shares: Requested {quantity}, available {available_quantity}."
                )

        order_id = f"MOCK-{symbol}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
        now = time.time()

        result = OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
            filled_quantity=0,
            average_fill_price=0.0,
            status=OrderStatus.SUBMITTED,
            fee_incurred=0.0,
            created_at=now,
            updated_at=now,
        )
        self.active_orders[order_id] = result
        return result

    async def get_order_status(self, order_id: str) -> OrderResult:
        if order_id not in self.active_orders:
            raise KeyError(f"Order ID {order_id} not found")
        return self.active_orders[order_id]

    async def cancel_order(self, order_id: str) -> bool:
        if order_id in self.active_orders:
            order = self.active_orders[order_id]
            if order.status in (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED):
                order.status = OrderStatus.CANCELLED
                order.updated_at = time.time()
                if order.side == OrderSide.BUY:
                    unfilled = order.quantity - order.filled_quantity
                    refund = round(unfilled * order.price, 2)
                    refund += round(refund * 0.015, 2)
                    self.cash_balance += refund
                return True
        return False

    async def get_cash_balance(self) -> float:
        return self.cash_balance
