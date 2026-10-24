"""Pre-trade risk validator enforcing price collars, notional limits, and self-trade prevention."""

from decimal import Decimal
from typing import Optional, Protocol
from src.models.types import Order, OrderType, RiskDecision, Side


class BookBBOProvider(Protocol):
    """Protocol for reading the best bid and ask prices and resting top-of-book trader."""

    def get_best_bid(self, symbol: str) -> Optional[Decimal]:
        ...

    def get_best_ask(self, symbol: str) -> Optional[Decimal]:
        ...

    def get_best_bid_trader(self, symbol: str) -> Optional[str]:
        ...

    def get_best_ask_trader(self, symbol: str) -> Optional[str]:
        ...


class PreTradeRiskEngine:
    """Pre-trade risk gateway enforcing institutional safety boundaries."""

    def __init__(
        self,
        max_notional: Decimal = Decimal("1000000.00"),
        max_price_divergence_pct: Decimal = Decimal("0.05"),  # 5% collar from BBO
        enforce_stp: bool = True,
    ) -> None:
        self.max_notional = max_notional
        self.max_price_divergence_pct = max_price_divergence_pct
        self.enforce_stp = enforce_stp

    def validate_order(self, order: Order, bbo_provider: BookBBOProvider) -> RiskDecision:
        """Evaluate pre-trade risk rules against order parameters and current book state."""
        # 1. Basic sanity: Price and Quantity must be positive
        if order.quantity <= Decimal("0"):
            return RiskDecision(
                allowed=False,
                code="INVALID_QUANTITY",
                reason=f"Order quantity must be strictly positive (got {order.quantity})",
            )

        if order.order_type != OrderType.MARKET and order.price <= Decimal("0"):
            return RiskDecision(
                allowed=False,
                code="INVALID_PRICE",
                reason=f"Limit order price must be strictly positive (got {order.price})",
            )

        # 2. Maximum single-order notional check
        notional = order.price * order.quantity
        if notional > self.max_notional:
            return RiskDecision(
                allowed=False,
                code="MAX_NOTIONAL_BREACH",
                reason=(
                    f"Order notional value of ${notional:,.2f} exceeds "
                    f"maximum allowed limit of ${self.max_notional:,.2f}"
                ),
            )

        # 3. Price Collar Check (Fat-finger protection vs BBO)
        if order.order_type == OrderType.LIMIT:
            if order.side == Side.BUY:
                best_ask = bbo_provider.get_best_ask(order.symbol)
                if best_ask is not None:
                    max_allowed_buy_price = best_ask * (Decimal("1") + self.max_price_divergence_pct)
                    if order.price > max_allowed_buy_price:
                        divergence = ((order.price - best_ask) / best_ask) * Decimal("100")
                        return RiskDecision(
                            allowed=False,
                            code="PRICE_COLLAR_EXCEEDED",
                            reason=(
                                f"Buy price ${order.price} deviates by {divergence:.2f}% from Best Ask "
                                f"${best_ask}, exceeding allowed collar of {self.max_price_divergence_pct * 100}%"
                            ),
                        )
            elif order.side == Side.SELL:
                best_bid = bbo_provider.get_best_bid(order.symbol)
                if best_bid is not None:
                    min_allowed_sell_price = best_bid * (Decimal("1") - self.max_price_divergence_pct)
                    if order.price < min_allowed_sell_price:
                        divergence = ((best_bid - order.price) / best_bid) * Decimal("100")
                        return RiskDecision(
                            allowed=False,
                            code="PRICE_COLLAR_EXCEEDED",
                            reason=(
                                f"Sell price ${order.price} deviates by {divergence:.2f}% from Best Bid "
                                f"${best_bid}, exceeding allowed collar of {self.max_price_divergence_pct * 100}%"
                            ),
                        )

        # 4. Self-Trade Prevention (STP - Cancel Taker)
        if self.enforce_stp:
            if order.side == Side.BUY:
                best_ask = bbo_provider.get_best_ask(order.symbol)
                best_ask_trader = bbo_provider.get_best_ask_trader(order.symbol)
                if (
                    best_ask is not None
                    and best_ask_trader == order.trader_id
                    and (order.order_type == OrderType.MARKET or order.price >= best_ask)
                ):
                    return RiskDecision(
                        allowed=False,
                        code="SELF_TRADE_PREVENTION",
                        reason=(
                            f"Self-trade intercepted: Trader '{order.trader_id}' would cross own "
                            f"resting ask at ${best_ask}"
                        ),
                    )
            elif order.side == Side.SELL:
                best_bid = bbo_provider.get_best_bid(order.symbol)
                best_bid_trader = bbo_provider.get_best_bid_trader(order.symbol)
                if (
                    best_bid is not None
                    and best_bid_trader == order.trader_id
                    and (order.order_type == OrderType.MARKET or order.price <= best_bid)
                ):
                    return RiskDecision(
                        allowed=False,
                        code="SELF_TRADE_PREVENTION",
                        reason=(
                            f"Self-trade intercepted: Trader '{order.trader_id}' would cross own "
                            f"resting bid at ${best_bid}"
                        ),
                    )

        return RiskDecision(allowed=True, code="OK", reason="Order passed pre-trade risk checks")
