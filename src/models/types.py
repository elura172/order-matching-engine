"""Domain models and data contracts for the order matching engine."""

from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> "Side":
        return Side.SELL if self == Side.BUY else Side.BUY


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    IOC = "IOC"  # Immediate-or-Cancel
    POST_ONLY = "POST_ONLY"  # Maker-or-Cancel


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class Order(BaseModel):
    order_id: str
    client_order_id: str
    trader_id: str
    symbol: str
    side: Side
    order_type: OrderType
    price: Decimal
    quantity: Decimal
    filled_qty: Decimal = Field(default=Decimal("0"))
    remaining_qty: Decimal = Field(default=Decimal("0"))
    status: OrderStatus = Field(default=OrderStatus.NEW)
    timestamp_ns: int = 0
    sequence_num: int = 0

    def model_post_init(self, __context) -> None:
        if self.remaining_qty == Decimal("0") and self.filled_qty == Decimal("0"):
            self.remaining_qty = self.quantity


class Trade(BaseModel):
    trade_id: str
    symbol: str
    price: Decimal
    quantity: Decimal
    maker_order_id: str
    taker_order_id: str
    maker_trader_id: str
    taker_trader_id: str
    maker_side: Side
    sequence_num: int
    timestamp_ns: int


class OrderBookLevel(BaseModel):
    price: Decimal
    quantity: Decimal
    order_count: int


class OrderBookSnapshot(BaseModel):
    symbol: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    sequence_num: int
    timestamp_ns: int

    @property
    def best_bid(self) -> Optional[Decimal]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[Decimal]:
        return self.asks[0].price if self.asks else None

    @property
    def spread(self) -> Optional[Decimal]:
        if self.best_bid is not None and self.best_ask is not None:
            return self.best_ask - self.best_bid
        return None


class RiskDecision(BaseModel):
    allowed: bool
    code: str = "OK"
    reason: str = "Order passed all pre-trade risk checks"
