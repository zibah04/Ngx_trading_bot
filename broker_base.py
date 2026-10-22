"""
NGX Algorithmic Trading Bot - Abstract Broker Interface
Compatible with Nigerian Stockbroker APIs (CardinalStone, Cowrywise, and Mock Simulator).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class OrderBookLevel:
    price: float
    quantity: int
    orders_count: int = 1


@dataclass
class OrderBook:
    symbol: str
    bids: List[OrderBookLevel]
    asks: List[OrderBookLevel]
    reference_price: float
    timestamp: float
    previous_close_price: Optional[float] = None

    @property
    def is_liquid(self) -> bool:
        return len(self.bids) > 0 and len(self.asks) > 0

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Optional[float]:
        if self.best_ask is not None and self.best_bid is not None:
            return round(self.best_ask - self.best_bid, 2)
        return None


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: float
    quantity: int
    filled_quantity: int
    average_fill_price: float
    status: OrderStatus
    fee_incurred: float
    created_at: float
    updated_at: float
    raw_response: Optional[Dict[str, Any]] = None


class BaseBroker(ABC):
    @abstractmethod
    async def connect(self) -> None:
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        pass

    @abstractmethod
    async def get_order_book(self, symbol: str) -> OrderBook:
        pass

    @abstractmethod
    async def submit_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        price: float,
        quantity: int,
    ) -> OrderResult:
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> OrderResult:
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        pass

    @abstractmethod
    async def get_cash_balance(self) -> float:
        pass
