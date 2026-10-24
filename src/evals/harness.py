"""10-Scenario Institutional Trading Evaluation Benchmark Suite for Order Matching Engine."""

from decimal import Decimal
from typing import Any
from pydantic import BaseModel
from src.engine.matcher import MatchingEngine
from src.journal.ledger import AuditLedger
from src.models.types import Order, OrderStatus, OrderType, Side
from src.risk.validator import PreTradeRiskEngine


class ScenarioResult(BaseModel):
    scenario_id: str
    description: str
    passed: bool
    details: str
    metric: str


class EvaluationBenchmarkHarness:
    """Benchmark harness executing 10 deterministic institutional trading scenarios."""

    def __init__(self, symbol: str = "BTC-USDT") -> None:
        self.symbol = symbol

    def run_all_scenarios(self) -> list[ScenarioResult]:
        """Execute all 10 evaluation scenarios and return structured results."""
        return [
            self.eval_01_simple_limit_match(),
            self.eval_02_partial_fill_and_rest(),
            self.eval_03_price_time_priority(),
            self.eval_04_market_order_sweep(),
            self.eval_05_ioc_cancellation(),
            self.eval_06_cancel_replace(),
            self.eval_07_self_trade_prevention(),
            self.eval_08_price_collar_fat_finger(),
            self.eval_09_max_notional_breach(),
            self.eval_10_deterministic_replay_hash(),
        ]

    def eval_01_simple_limit_match(self) -> ScenarioResult:
        engine = MatchingEngine(self.symbol)
        # 1. Maker sell: 10 units at $100.00
        maker = Order(
            order_id="m-01",
            client_order_id="cl-m-01",
            trader_id="maker-1",
            symbol=self.symbol,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("100.00"),
            quantity=Decimal("10.0"),
        )
        engine.submit_order(maker)

        # 2. Taker buy: 10 units at $100.00
        taker = Order(
            order_id="t-01",
            client_order_id="cl-t-01",
            trader_id="taker-1",
            symbol=self.symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("100.00"),
            quantity=Decimal("10.0"),
        )
        order, trades, _ = engine.submit_order(taker)

        passed = (
            len(trades) == 1
            and trades[0].quantity == Decimal("10.0")
            and trades[0].price == Decimal("100.00")
            and order.status == OrderStatus.FILLED
            and engine.book.get_best_ask() is None
        )
        return ScenarioResult(
            scenario_id="01_SIMPLE_LIMIT_MATCH",
            description="Two crossing limit orders execute full fill at maker price",
            passed=passed,
            details=f"Trades: {len(trades)}, Executed Price: ${trades[0].price if trades else 0}",
            metric="10.0 filled @ $100.00",
        )

    def eval_02_partial_fill_and_rest(self) -> ScenarioResult:
        engine = MatchingEngine(self.symbol)
        maker = Order(
            order_id="m-02",
            client_order_id="cl-m-02",
            trader_id="maker-1",
            symbol=self.symbol,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("100.00"),
            quantity=Decimal("10.0"),
        )
        engine.submit_order(maker)

        taker = Order(
            order_id="t-02",
            client_order_id="cl-t-02",
            trader_id="taker-1",
            symbol=self.symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("100.00"),
            quantity=Decimal("15.0"),
        )
        order, trades, _ = engine.submit_order(taker)

        passed = (
            len(trades) == 1
            and trades[0].quantity == Decimal("10.0")
            and order.status == OrderStatus.PARTIALLY_FILLED
            and order.remaining_qty == Decimal("5.0")
            and engine.book.get_best_bid() == Decimal("100.00")
        )
        return ScenarioResult(
            scenario_id="02_PARTIAL_FILL_AND_REST",
            description="Taker partially fills resting maker; residual rests as new maker bid",
            passed=passed,
            details=f"Filled: {order.filled_qty}, Resting Bid: {order.remaining_qty} @ $100",
            metric="10.0 filled / 5.0 resting",
        )

    def eval_03_price_time_priority(self) -> ScenarioResult:
        engine = MatchingEngine(self.symbol)
        # Maker A at $100.00
        maker_a = Order(
            order_id="m-a",
            client_order_id="cl-m-a",
            trader_id="maker-a",
            symbol=self.symbol,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("100.00"),
            quantity=Decimal("5.0"),
        )
        engine.submit_order(maker_a)

        # Maker B at $100.00
        maker_b = Order(
            order_id="m-b",
            client_order_id="cl-m-b",
            trader_id="maker-b",
            symbol=self.symbol,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("100.00"),
            quantity=Decimal("5.0"),
        )
        engine.submit_order(maker_b)

        # Taker buy for 5.0 units: MUST fill against Maker A first (FIFO)
        taker = Order(
            order_id="t-03",
            client_order_id="cl-t-03",
            trader_id="taker-1",
            symbol=self.symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("100.00"),
            quantity=Decimal("5.0"),
        )
        _, trades, _ = engine.submit_order(taker)

        passed = (
            len(trades) == 1
            and trades[0].maker_order_id == "m-a"
            and trades[0].maker_trader_id == "maker-a"
        )
        return ScenarioResult(
            scenario_id="03_PRICE_TIME_PRIORITY",
            description="Orders at identical price fill in strict arrival FIFO order",
            passed=passed,
            details=f"Matched against: {trades[0].maker_trader_id if trades else 'None'}",
            metric="FIFO Priority Verified",
        )

    def eval_04_market_order_sweep(self) -> ScenarioResult:
        engine = MatchingEngine(self.symbol)
        # Book: 5 @ 100, 5 @ 101, 5 @ 102
        for p in [Decimal("100.00"), Decimal("101.00"), Decimal("102.00")]:
            engine.submit_order(
                Order(
                    order_id=f"m-{p}",
                    client_order_id=f"cl-{p}",
                    trader_id="maker",
                    symbol=self.symbol,
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    price=p,
                    quantity=Decimal("5.0"),
                )
            )

        # Market buy for 12 units: sweeps 100 (5), 101 (5), and 102 (2)
        mkt_order = Order(
            order_id="mkt-01",
            client_order_id="cl-mkt-01",
            trader_id="taker",
            symbol=self.symbol,
            side=Side.BUY,
            order_type=OrderType.MARKET,
            price=Decimal("0.0"),
            quantity=Decimal("12.0"),
        )
        order, trades, _ = engine.submit_order(mkt_order)

        passed = (
            len(trades) == 3
            and sum(t.quantity for t in trades) == Decimal("12.0")
            and order.status == OrderStatus.FILLED
            and engine.book.get_best_ask() == Decimal("102.00")
        )
        return ScenarioResult(
            scenario_id="04_MARKET_ORDER_SWEEP",
            description="Market buy sweeps multiple ask levels down the book",
            passed=passed,
            details=f"Levels swept: {len(trades)}, Total Filled: {order.filled_qty}",
            metric="Swept 3 Price Levels",
        )

    def eval_05_ioc_cancellation(self) -> ScenarioResult:
        engine = MatchingEngine(self.symbol)
        # Resting sell: 5 @ 100
        engine.submit_order(
            Order(
                order_id="m-ioc",
                client_order_id="cl-m-ioc",
                trader_id="maker",
                symbol=self.symbol,
                side=Side.SELL,
                order_type=OrderType.LIMIT,
                price=Decimal("100.00"),
                quantity=Decimal("5.0"),
            )
        )

        # IOC buy for 10 units @ 100: should fill 5, cancel remaining 5 immediately
        ioc_order = Order(
            order_id="ioc-01",
            client_order_id="cl-ioc-01",
            trader_id="taker",
            symbol=self.symbol,
            side=Side.BUY,
            order_type=OrderType.IOC,
            price=Decimal("100.00"),
            quantity=Decimal("10.0"),
        )
        order, trades, _ = engine.submit_order(ioc_order)

        passed = (
            len(trades) == 1
            and order.filled_qty == Decimal("5.0")
            and order.remaining_qty == Decimal("5.0")
            and order.status == OrderStatus.PARTIALLY_FILLED
            and engine.book.get_best_bid() is None  # Nothing rested on the book!
        )
        return ScenarioResult(
            scenario_id="05_IOC_CANCELLATION",
            description="Immediate-or-Cancel fills available liquidity, cancels remainder",
            passed=passed,
            details=f"Filled: {order.filled_qty}, Unfilled residual cancelled without resting",
            metric="5 filled / 5 cancelled",
        )

    def eval_06_cancel_replace(self) -> ScenarioResult:
        engine = MatchingEngine(self.symbol)
        original = Order(
            order_id="orig-01",
            client_order_id="cl-orig-01",
            trader_id="trader-1",
            symbol=self.symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("95.00"),
            quantity=Decimal("10.0"),
        )
        engine.submit_order(original)

        cancelled, replaced, _, _ = engine.cancel_replace(
            order_id="orig-01",
            new_price=Decimal("96.00"),
            new_quantity=Decimal("12.0"),
        )

        passed = (
            cancelled is not None
            and cancelled.status == OrderStatus.CANCELLED
            and replaced is not None
            and engine.book.get_best_bid() == Decimal("96.00")
            and engine.book.get_order("orig-01") is None
        )
        return ScenarioResult(
            scenario_id="06_CANCEL_REPLACE",
            description="Resting order is cancelled and replaced atomically at new price",
            passed=passed,
            details="Original cancelled, replaced with 12 @ $96.00",
            metric="Atomic Cancel/Replace Verified",
        )

    def eval_07_self_trade_prevention(self) -> ScenarioResult:
        engine = MatchingEngine(self.symbol)
        # Resting sell from trader_alpha
        engine.submit_order(
            Order(
                order_id="stp-m",
                client_order_id="cl-stp-m",
                trader_id="trader_alpha",
                symbol=self.symbol,
                side=Side.SELL,
                order_type=OrderType.LIMIT,
                price=Decimal("100.00"),
                quantity=Decimal("10.0"),
            )
        )

        # Incoming buy from SAME trader_alpha
        self_buyer = Order(
            order_id="stp-t",
            client_order_id="cl-stp-t",
            trader_id="trader_alpha",
            symbol=self.symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("100.00"),
            quantity=Decimal("5.0"),
        )
        order, trades, decision = engine.submit_order(self_buyer)

        passed = (
            len(trades) == 0
            and not decision.allowed
            and decision.code == "SELF_TRADE_PREVENTION"
            and order.status == OrderStatus.REJECTED
        )
        return ScenarioResult(
            scenario_id="07_SELF_TRADE_PREVENTION",
            description="Pre-trade risk gate halts self-match between identical trader accounts",
            passed=passed,
            details=f"Decision Code: {decision.code}, Trades executed: {len(trades)}",
            metric="Wash Trade Intercepted",
        )

    def eval_08_price_collar_fat_finger(self) -> ScenarioResult:
        engine = MatchingEngine(self.symbol)
        # Best ask is $100.00
        engine.submit_order(
            Order(
                order_id="m-ref",
                client_order_id="cl-m-ref",
                trader_id="maker-1",
                symbol=self.symbol,
                side=Side.SELL,
                order_type=OrderType.LIMIT,
                price=Decimal("100.00"),
                quantity=Decimal("10.0"),
            )
        )

        # Fat-finger buy at $110.00 (10% higher than best ask, collar allows max 5%)
        fat_finger = Order(
            order_id="ff-01",
            client_order_id="cl-ff-01",
            trader_id="taker-1",
            symbol=self.symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("110.00"),
            quantity=Decimal("1.0"),
        )
        order, trades, decision = engine.submit_order(fat_finger)

        passed = (
            len(trades) == 0
            and not decision.allowed
            and decision.code == "PRICE_COLLAR_EXCEEDED"
            and order.status == OrderStatus.REJECTED
        )
        return ScenarioResult(
            scenario_id="08_PRICE_COLLAR_FAT_FINGER",
            description="Fat-finger price (+10% from BBO) rejected by pre-trade collar gate",
            passed=passed,
            details=f"Code: {decision.code}, Reason: {decision.reason}",
            metric="Price Collar Enforced (>5%)",
        )

    def eval_09_max_notional_breach(self) -> ScenarioResult:
        engine = MatchingEngine(self.symbol)
        # Order for $500.00 x 3,000 qty = $1,500,000 notional (exceeds $1,000,000 cap)
        oversized = Order(
            order_id="notional-01",
            client_order_id="cl-notional-01",
            trader_id="whale-1",
            symbol=self.symbol,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("500.00"),
            quantity=Decimal("3000.0"),
        )
        order, trades, decision = engine.submit_order(oversized)

        passed = (
            len(trades) == 0
            and not decision.allowed
            and decision.code == "MAX_NOTIONAL_BREACH"
            and order.status == OrderStatus.REJECTED
        )
        return ScenarioResult(
            scenario_id="09_MAX_NOTIONAL_BREACH",
            description="Order exceeding $1,000,000 maximum single-order notional rejected",
            passed=passed,
            details=f"Notional: $1,500,000 | Max allowed: $1,000,000 | Code: {decision.code}",
            metric="Notional Limit Enforced",
        )

    def eval_10_deterministic_replay_hash(self) -> ScenarioResult:
        # Run identical deterministic sequence through two independent engines and journals
        def run_sim():
            engine = MatchingEngine(self.symbol)
            ledger = AuditLedger()
            # Feed 100 alternating bid/ask orders
            for i in range(1, 101):
                p = Decimal("100.00") + Decimal(str(i % 5))
                q = Decimal("1.0")
                side = Side.BUY if i % 2 == 0 else Side.SELL
                o = Order(
                    order_id=f"det-{i}",
                    client_order_id=f"cl-det-{i}",
                    trader_id=f"trader-{i % 3}",
                    symbol=self.symbol,
                    side=side,
                    order_type=OrderType.LIMIT,
                    price=p,
                    quantity=q,
                )
                res_o, trades, decision = engine.submit_order(o)
                ledger.record_event(
                    event_type="ORDER_SUBMITTED",
                    payload={"order_id": res_o.order_id, "status": res_o.status.value, "trades": len(trades)},
                    sequence_num=res_o.sequence_num,
                    timestamp_ns=1700000000000000000 + i,
                )
            return engine, ledger

        engine1, ledger1 = run_sim()
        engine2, ledger2 = run_sim()

        root1 = ledger1.state_root
        root2 = ledger2.state_root
        passed = (
            root1 == root2
            and len(engine1.trades) == len(engine2.trades)
            and ledger1.verify_chain_integrity()
        )
        return ScenarioResult(
            scenario_id="10_DETERMINISTIC_REPLAY_HASH",
            description="Replaying deterministic order stream produces identical SHA-256 state root",
            passed=passed,
            details=f"Ledger Root: {root1[:16]}... (Integrity Verified)",
            metric="Deterministic Replay Certified",
        )
