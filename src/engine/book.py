"""L3 Limit Order Book implementing price-time priority (FIFO) per price level."""

import bisect
from collections import deque
from decimal import Decimal
from typing import Optional
from src.models.types import Order, OrderBookLevel, OrderBookSnapshot, OrderStatus, Side


class LimitOrderBook:
    """High-performance L3 Limit Order Book with continuous double auction state."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        # Orders indexed by order_id for O(1) lookup and cancellation
        self._orders: dict[str, Order] = {}
        # Orders grouped by price level in FIFO deques: side -> price -> deque[Order]
        self._levels: dict[Side, dict[Decimal, deque[Order]]] = {
            Side.BUY: {},
            Side.SELL: {},
        }
        # Sorted price lists for O(1) BBO and efficient book traversal
        # Bids sorted descending (highest bid first)
        self._bid_prices: list[Decimal] = []
        # Asks sorted ascending (lowest ask first)
        self._ask_prices: list[Decimal] = []

    def get_best_bid(self, symbol: str = "") -> Optional[Decimal]:
        return self._bid_prices[0] if self._bid_prices else None

    def get_best_ask(self, symbol: str = "") -> Optional[Decimal]:
        return self._ask_prices[0] if self._ask_prices else None

    def get_best_bid_trader(self, symbol: str = "") -> Optional[str]:
        if self._bid_prices:
            best_level = self._levels[Side.BUY].get(self._bid_prices[0])
            if best_level and len(best_level) > 0:
                return best_level[0].trader_id
        return None

    def get_best_ask_trader(self, symbol: str = "") -> Optional[str]:
        if self._ask_prices:
            best_level = self._levels[Side.SELL].get(self._ask_prices[0])
            if best_level and len(best_level) > 0:
                return best_level[0].trader_id
        return None

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def add_resting_order(self, order: Order, priority_index: Optional[int] = None) -> None:
        """Add an unfilled or partially filled limit order to rest on the book."""
        if order.remaining_qty <= Decimal("0"):
            return

        order.status = (
            OrderStatus.PARTIALLY_FILLED if order.filled_qty > Decimal("0") else OrderStatus.NEW
        )
        self._orders[order.order_id] = order
        side = order.side
        price = order.price

        if price not in self._levels[side]:
            self._levels[side][price] = deque()
            if side == Side.BUY:
                # Maintain descending order for bids: negate for bisect or insert manually
                # Custom bisect insertion to keep bids strictly descending
                self._insert_bid_price(price)
            else:
                # Maintain ascending order for asks
                bisect.insort_left(self._ask_prices, price)

        level = self._levels[side][price]
        if priority_index is None:
            level.append(order)
        else:
            level.insert(priority_index, order)

    def get_order_priority(self, order_id: str) -> Optional[int]:
        """Return an order's FIFO position within its price level, if it is resting."""
        order = self._orders.get(order_id)
        if order is None:
            return None
        level = self._levels[order.side].get(order.price)
        if level is None:
            return None
        try:
            return next(index for index, resting in enumerate(level) if resting.order_id == order_id)
        except StopIteration:
            return None

    def estimate_market_notional(self, side: Side, quantity: Decimal) -> Decimal:
        """Return the notional that a market order can execute against current depth."""
        opposite = Side.SELL if side == Side.BUY else Side.BUY
        prices = self._ask_prices if side == Side.BUY else self._bid_prices
        remaining = quantity
        notional = Decimal("0")
        for price in prices:
            for resting in self._levels[opposite][price]:
                fill_qty = min(remaining, resting.remaining_qty)
                notional += price * fill_qty
                remaining -= fill_qty
                if remaining <= 0:
                    return notional
        return notional

    def cancel_order(self, order_id: str) -> Optional[Order]:
        """Cancel a resting order from the book."""
        order = self._orders.pop(order_id, None)
        if order is None:
            return None

        order.status = OrderStatus.CANCELLED
        side = order.side
        price = order.price

        if price in self._levels[side]:
            level = self._levels[side][price]
            # Remove order from deque
            try:
                level.remove(order)
            except ValueError:
                pass

            if len(level) == 0:
                del self._levels[side][price]
                if side == Side.BUY:
                    if price in self._bid_prices:
                        self._bid_prices.remove(price)
                else:
                    if price in self._ask_prices:
                        self._ask_prices.remove(price)

        return order

    def remove_order_from_book(self, order_id: str) -> Optional[Order]:
        """Remove a fully filled order from the book."""
        return self.cancel_order(order_id)

    def _insert_bid_price(self, price: Decimal) -> None:
        """Insert price into bids maintaining strictly descending order."""
        # Find index where price should be inserted
        for idx, p in enumerate(self._bid_prices):
            if price > p:
                self._bid_prices.insert(idx, price)
                return
            elif price == p:
                return
        self._bid_prices.append(price)

    def get_snapshot(self, depth: int = 10, sequence_num: int = 0, timestamp_ns: int = 0) -> OrderBookSnapshot:
        """Generate a L2/L3 aggregated depth snapshot of the book."""
        bids: list[OrderBookLevel] = []
        for price in self._bid_prices[:depth]:
            level = self._levels[Side.BUY][price]
            total_qty = sum(o.remaining_qty for o in level)
            bids.append(OrderBookLevel(price=price, quantity=total_qty, order_count=len(level)))

        asks: list[OrderBookLevel] = []
        for price in self._ask_prices[:depth]:
            level = self._levels[Side.SELL][price]
            total_qty = sum(o.remaining_qty for o in level)
            asks.append(OrderBookLevel(price=price, quantity=total_qty, order_count=len(level)))

        return OrderBookSnapshot(
            symbol=self.symbol,
            bids=bids,
            asks=asks,
            sequence_num=sequence_num,
            timestamp_ns=timestamp_ns,
        )
