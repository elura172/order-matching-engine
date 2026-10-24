"""Continuous double auction matching engine with price-time priority and trade execution."""

import time
import uuid
from decimal import Decimal
from typing import Optional
from src.engine.book import LimitOrderBook
from src.models.types import Order, OrderStatus, OrderType, RiskDecision, Side, Trade
from src.risk.validator import PreTradeRiskEngine


class MatchingEngine:
    """Core matching engine handling order intake, risk validation, matching, and book maintenance."""

    def __init__(
        self,
        symbol: str,
        risk_engine: Optional[PreTradeRiskEngine] = None,
    ) -> None:
        self.symbol = symbol
        self.book = LimitOrderBook(symbol)
        self.risk_engine = risk_engine or PreTradeRiskEngine()
        self.sequence_num: int = 0
        self.trades: list[Trade] = []
        self._processed_client_orders: dict[str, tuple[Order, list[Trade], RiskDecision]] = {}

    def _next_seq(self) -> int:
        self.sequence_num += 1
        return self.sequence_num

    def submit_order(self, order: Order) -> tuple[Order, list[Trade], RiskDecision]:
        """Intake, validate, cross, and settle an incoming order against the book."""
        # 1. Idempotency check on client_order_id
        if order.client_order_id in self._processed_client_orders:
            return self._processed_client_orders[order.client_order_id]

        if order.timestamp_ns == 0:
            order.timestamp_ns = time.time_ns()

        order.sequence_num = self._next_seq()

        # 2. Pre-trade risk validation
        risk_decision = self.risk_engine.validate_order(order, self.book)
        if not risk_decision.allowed:
            order.status = OrderStatus.REJECTED
            result = (order, [], risk_decision)
            self._processed_client_orders[order.client_order_id] = result
            return result

        # 3. Post-Only check: must not cross opposing book
        if order.order_type == OrderType.POST_ONLY:
            if order.side == Side.BUY:
                best_ask = self.book.get_best_ask()
                if best_ask is not None and order.price >= best_ask:
                    order.status = OrderStatus.CANCELLED
                    decision = RiskDecision(
                        allowed=False,
                        code="POST_ONLY_WOULD_CROSS",
                        reason=f"Post-only buy at ${order.price} would cross resting ask at ${best_ask}",
                    )
                    result = (order, [], decision)
                    self._processed_client_orders[order.client_order_id] = result
                    return result
            elif order.side == Side.SELL:
                best_bid = self.book.get_best_bid()
                if best_bid is not None and order.price <= best_bid:
                    order.status = OrderStatus.CANCELLED
                    decision = RiskDecision(
                        allowed=False,
                        code="POST_ONLY_WOULD_CROSS",
                        reason=f"Post-only sell at ${order.price} would cross resting bid at ${best_bid}",
                    )
                    result = (order, [], decision)
                    self._processed_client_orders[order.client_order_id] = result
                    return result

        # 4. Continuous double auction crossing loop
        executed_trades: list[Trade] = []

        if order.side == Side.BUY:
            while order.remaining_qty > Decimal("0") and self.book._ask_prices:
                best_ask_price = self.book._ask_prices[0]
                if order.order_type != OrderType.MARKET and best_ask_price > order.price:
                    # Best ask price exceeds buy limit: cannot cross
                    break

                ask_level = self.book._levels[Side.SELL][best_ask_price]
                maker_order = ask_level[0]

                fill_qty = min(order.remaining_qty, maker_order.remaining_qty)
                trade_price = best_ask_price  # Passive maker establishes execution price

                trade = Trade(
                    trade_id=f"trd-{uuid.uuid4().hex[:12]}",
                    symbol=self.symbol,
                    price=trade_price,
                    quantity=fill_qty,
                    maker_order_id=maker_order.order_id,
                    taker_order_id=order.order_id,
                    maker_trader_id=maker_order.trader_id,
                    taker_trader_id=order.trader_id,
                    maker_side=Side.SELL,
                    sequence_num=self._next_seq(),
                    timestamp_ns=time.time_ns(),
                )
                executed_trades.append(trade)
                self.trades.append(trade)

                # Deduct inventory
                order.filled_qty += fill_qty
                order.remaining_qty -= fill_qty
                maker_order.filled_qty += fill_qty
                maker_order.remaining_qty -= fill_qty

                if maker_order.remaining_qty == Decimal("0"):
                    maker_order.status = OrderStatus.FILLED
                    self.book.remove_order_from_book(maker_order.order_id)
                else:
                    maker_order.status = OrderStatus.PARTIALLY_FILLED

        elif order.side == Side.SELL:
            while order.remaining_qty > Decimal("0") and self.book._bid_prices:
                best_bid_price = self.book._bid_prices[0]
                if order.order_type != OrderType.MARKET and best_bid_price < order.price:
                    # Best bid price is below sell limit: cannot cross
                    break

                bid_level = self.book._levels[Side.BUY][best_bid_price]
                maker_order = bid_level[0]

                fill_qty = min(order.remaining_qty, maker_order.remaining_qty)
                trade_price = best_bid_price  # Passive maker establishes execution price

                trade = Trade(
                    trade_id=f"trd-{uuid.uuid4().hex[:12]}",
                    symbol=self.symbol,
                    price=trade_price,
                    quantity=fill_qty,
                    maker_order_id=maker_order.order_id,
                    taker_order_id=order.order_id,
                    maker_trader_id=maker_order.trader_id,
                    taker_trader_id=order.trader_id,
                    maker_side=Side.BUY,
                    sequence_num=self._next_seq(),
                    timestamp_ns=time.time_ns(),
                )
                executed_trades.append(trade)
                self.trades.append(trade)

                # Deduct inventory
                order.filled_qty += fill_qty
                order.remaining_qty -= fill_qty
                maker_order.filled_qty += fill_qty
                maker_order.remaining_qty -= fill_qty

                if maker_order.remaining_qty == Decimal("0"):
                    maker_order.status = OrderStatus.FILLED
                    self.book.remove_order_from_book(maker_order.order_id)
                else:
                    maker_order.status = OrderStatus.PARTIALLY_FILLED

        # 5. Handle post-match order settlement
        if order.remaining_qty == Decimal("0"):
            order.status = OrderStatus.FILLED
        else:
            if order.order_type in (OrderType.IOC, OrderType.MARKET):
                # IOC and Market orders cancel any unfilled residual
                order.status = (
                    OrderStatus.PARTIALLY_FILLED if order.filled_qty > Decimal("0") else OrderStatus.CANCELLED
                )
            else:
                # Limit order rests on the book
                order.status = (
                    OrderStatus.PARTIALLY_FILLED if order.filled_qty > Decimal("0") else OrderStatus.NEW
                )
                self.book.add_resting_order(order)

        result = (order, executed_trades, risk_decision)
        self._processed_client_orders[order.client_order_id] = result
        return result

    def cancel_order(self, order_id: str) -> Optional[Order]:
        """Cancel a resting order by order_id."""
        cancelled = self.book.cancel_order(order_id)
        return cancelled

    def cancel_replace(
        self,
        order_id: str,
        new_price: Decimal,
        new_quantity: Decimal,
        new_client_order_id: Optional[str] = None,
    ) -> tuple[Optional[Order], Optional[Order], list[Trade], RiskDecision]:
        """Atomically cancel a resting order and submit a replacement order."""
        cancelled = self.cancel_order(order_id)
        if cancelled is None:
            return (
                None,
                None,
                [],
                RiskDecision(allowed=False, code="ORDER_NOT_FOUND", reason=f"Order '{order_id}' not found on book"),
            )

        replacement_order = Order(
            order_id=f"ord-{uuid.uuid4().hex[:12]}",
            client_order_id=new_client_order_id or f"cl-{uuid.uuid4().hex[:12]}",
            trader_id=cancelled.trader_id,
            symbol=cancelled.symbol,
            side=cancelled.side,
            order_type=cancelled.order_type,
            price=new_price,
            quantity=new_quantity,
        )

        res_order, trades, decision = self.submit_order(replacement_order)
        return (cancelled, res_order, trades, decision)
