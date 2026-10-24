"""Unit test suite for limit order book, risk gates, and matching engine."""

from decimal import Decimal
import pytest
from src.engine.book import LimitOrderBook
from src.engine.matcher import MatchingEngine
from src.journal.ledger import AuditLedger
from src.models.types import Order, OrderStatus, OrderType, Side
from src.risk.validator import PreTradeRiskEngine


def test_order_creation_and_remaining_qty_defaults():
    order = Order(
        order_id="ord-1",
        client_order_id="cl-1",
        trader_id="t1",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("50000.00"),
        quantity=Decimal("2.5"),
    )
    assert order.remaining_qty == Decimal("2.5")
    assert order.filled_qty == Decimal("0")
    assert order.status == OrderStatus.NEW


def test_limit_order_placement_on_empty_book():
    book = LimitOrderBook("BTC-USDT")
    order = Order(
        order_id="ord-1",
        client_order_id="cl-1",
        trader_id="t1",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("50000.00"),
        quantity=Decimal("1.0"),
    )
    book.add_resting_order(order)
    assert book.get_best_bid() == Decimal("50000.00")
    assert book.get_best_ask() is None
    assert book.get_best_bid_trader() == "t1"


def test_crossing_orders_generate_trade_at_maker_price():
    engine = MatchingEngine("BTC-USDT")
    maker = Order(
        order_id="m-1",
        client_order_id="cl-m-1",
        trader_id="maker",
        symbol="BTC-USDT",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("100.00"),
        quantity=Decimal("5.0"),
    )
    engine.submit_order(maker)

    # Taker bids $105.00: trade executes at maker's passive price ($100.00)
    taker = Order(
        order_id="t-1",
        client_order_id="cl-t-1",
        trader_id="taker",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("105.00"),
        quantity=Decimal("5.0"),
    )
    order, trades, decision = engine.submit_order(taker)

    assert decision.allowed
    assert len(trades) == 1
    assert trades[0].price == Decimal("100.00")
    assert trades[0].quantity == Decimal("5.0")
    assert order.status == OrderStatus.FILLED
    assert engine.book.get_best_ask() is None


def test_fifo_price_time_priority():
    engine = MatchingEngine("BTC-USDT")
    m1 = Order(
        order_id="m1",
        client_order_id="cl-m1",
        trader_id="maker1",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("50.00"),
        quantity=Decimal("10.0"),
    )
    m2 = Order(
        order_id="m2",
        client_order_id="cl-m2",
        trader_id="maker2",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("50.00"),
        quantity=Decimal("10.0"),
    )
    engine.submit_order(m1)
    engine.submit_order(m2)

    # Taker sell crosses: must fill against m1 first
    taker = Order(
        order_id="t1",
        client_order_id="cl-t1",
        trader_id="seller",
        symbol="BTC-USDT",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("50.00"),
        quantity=Decimal("10.0"),
    )
    _, trades, _ = engine.submit_order(taker)
    assert len(trades) == 1
    assert trades[0].maker_order_id == "m1"
    # m2 remains on the book
    assert engine.book.get_order("m2") is not None


def test_ioc_order_cancels_unfilled_residual():
    engine = MatchingEngine("BTC-USDT")
    maker = Order(
        order_id="m-ioc",
        client_order_id="cl-m-ioc",
        trader_id="m1",
        symbol="BTC-USDT",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("200.00"),
        quantity=Decimal("3.0"),
    )
    engine.submit_order(maker)

    ioc = Order(
        order_id="ioc-1",
        client_order_id="cl-ioc-1",
        trader_id="taker",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.IOC,
        price=Decimal("200.00"),
        quantity=Decimal("10.0"),
    )
    res_order, trades, _ = engine.submit_order(ioc)

    assert len(trades) == 1
    assert trades[0].quantity == Decimal("3.0")
    assert res_order.filled_qty == Decimal("3.0")
    assert res_order.remaining_qty == Decimal("7.0")
    assert engine.book.get_best_bid() is None  # Residue must not rest on book!


def test_post_only_cancellation_when_crossing():
    engine = MatchingEngine("BTC-USDT")
    maker = Order(
        order_id="m-post",
        client_order_id="cl-m-post",
        trader_id="maker",
        symbol="BTC-USDT",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        price=Decimal("100.00"),
        quantity=Decimal("5.0"),
    )
    engine.submit_order(maker)

    # Post-only buy at 100 would cross: must be rejected
    post_buy = Order(
        order_id="po-1",
        client_order_id="cl-po-1",
        trader_id="maker-2",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.POST_ONLY,
        price=Decimal("100.00"),
        quantity=Decimal("2.0"),
    )
    res_order, trades, decision = engine.submit_order(post_buy)
    assert len(trades) == 0
    assert not decision.allowed
    assert decision.code == "POST_ONLY_WOULD_CROSS"
    assert res_order.status == OrderStatus.CANCELLED


def test_cancel_replace_flow():
    engine = MatchingEngine("BTC-USDT")
    orig = Order(
        order_id="cr-orig",
        client_order_id="cl-cr-orig",
        trader_id="trader",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("90.00"),
        quantity=Decimal("5.0"),
    )
    engine.submit_order(orig)

    cancelled, replaced, _, _ = engine.cancel_replace("cr-orig", Decimal("92.00"), Decimal("8.0"))
    assert cancelled.status == OrderStatus.CANCELLED
    assert replaced.price == Decimal("92.00")
    assert replaced.quantity == Decimal("8.0")
    assert engine.book.get_best_bid() == Decimal("92.00")


def test_rejected_cancel_replace_restores_original_fifo_priority():
    engine = MatchingEngine("BTC-USDT")
    original = Order(
        order_id="replace-first", client_order_id="replace-first-client", trader_id="maker",
        symbol="BTC-USDT", side=Side.BUY, order_type=OrderType.LIMIT,
        price=Decimal("90"), quantity=Decimal("2"),
    )
    second = Order(
        order_id="replace-second", client_order_id="replace-second-client", trader_id="maker-2",
        symbol="BTC-USDT", side=Side.BUY, order_type=OrderType.LIMIT,
        price=Decimal("90"), quantity=Decimal("2"),
    )
    ask = Order(
        order_id="replace-ask", client_order_id="replace-ask-client", trader_id="seller",
        symbol="BTC-USDT", side=Side.SELL, order_type=OrderType.LIMIT,
        price=Decimal("100"), quantity=Decimal("1"),
    )
    engine.submit_order(original)
    engine.submit_order(second)
    engine.submit_order(ask)

    restored, replacement, _, decision = engine.cancel_replace(
        "replace-first", Decimal("106"), Decimal("2"), "replace-rejected-client"
    )
    assert not decision.allowed
    assert decision.code == "PRICE_COLLAR_EXCEEDED"
    assert replacement.status == OrderStatus.REJECTED
    assert restored.status == OrderStatus.NEW
    assert engine.book.get_best_bid() == Decimal("90")

    taker = Order(
        order_id="priority-taker", client_order_id="priority-taker-client", trader_id="taker",
        symbol="BTC-USDT", side=Side.SELL, order_type=OrderType.LIMIT,
        price=Decimal("90"), quantity=Decimal("1"),
    )
    _, trades, _ = engine.submit_order(taker)
    assert trades[0].maker_order_id == "replace-first"


def test_self_trade_prevention_gate():
    engine = MatchingEngine("BTC-USDT")
    engine.submit_order(
        Order(
            order_id="stp-m",
            client_order_id="cl-stp-m",
            trader_id="firm_prop_1",
            symbol="BTC-USDT",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("100.00"),
            quantity=Decimal("5.0"),
        )
    )

    wash = Order(
        order_id="stp-t",
        client_order_id="cl-stp-t",
        trader_id="firm_prop_1",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("100.00"),
        quantity=Decimal("2.0"),
    )
    res_order, trades, decision = engine.submit_order(wash)
    assert len(trades) == 0
    assert not decision.allowed
    assert decision.code == "SELF_TRADE_PREVENTION"
    assert res_order.status == OrderStatus.REJECTED


def test_price_collar_rejection():
    engine = MatchingEngine("BTC-USDT")
    engine.submit_order(
        Order(
            order_id="ref",
            client_order_id="cl-ref",
            trader_id="maker",
            symbol="BTC-USDT",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("100.00"),
            quantity=Decimal("10.0"),
        )
    )

    fat_finger = Order(
        order_id="ff",
        client_order_id="cl-ff",
        trader_id="taker",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("108.00"),  # 8% divergence > 5% collar
        quantity=Decimal("1.0"),
    )
    _, trades, decision = engine.submit_order(fat_finger)
    assert len(trades) == 0
    assert not decision.allowed
    assert decision.code == "PRICE_COLLAR_EXCEEDED"


def test_max_notional_breach():
    engine = MatchingEngine("BTC-USDT")
    oversized = Order(
        order_id="whale",
        client_order_id="cl-whale",
        trader_id="whale",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("2000.00"),
        quantity=Decimal("1000.0"),  # $2,000,000 > $1,000,000
    )
    _, _, decision = engine.submit_order(oversized)
    assert not decision.allowed
    assert decision.code == "MAX_NOTIONAL_BREACH"


def test_client_order_id_idempotency():
    engine = MatchingEngine("BTC-USDT")
    order = Order(
        order_id="idemp-1",
        client_order_id="duplicate-key-123",
        trader_id="trader",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("50.00"),
        quantity=Decimal("1.0"),
    )
    res1, trades1, d1 = engine.submit_order(order)
    res2, trades2, d2 = engine.submit_order(order)

    assert res1.sequence_num == res2.sequence_num
    assert res1.status == res2.status
    assert d1.code == d2.code


def test_reused_client_order_id_with_different_payload_is_rejected():
    engine = MatchingEngine("BTC-USDT")
    first = Order(
        order_id="idem-a", client_order_id="same-client-id", trader_id="t1",
        symbol="BTC-USDT", side=Side.BUY, order_type=OrderType.LIMIT,
        price=Decimal("50"), quantity=Decimal("1"),
    )
    engine.submit_order(first)
    conflicting = Order(
        order_id="idem-b", client_order_id="same-client-id", trader_id="t1",
        symbol="BTC-USDT", side=Side.BUY, order_type=OrderType.LIMIT,
        price=Decimal("51"), quantity=Decimal("1"),
    )

    result, trades, decision = engine.submit_order(conflicting)
    assert result.status == OrderStatus.REJECTED
    assert trades == []
    assert decision.code == "CLIENT_ORDER_ID_CONFLICT"
    assert engine.book.get_best_bid() == Decimal("50")


def test_market_order_notional_sums_executable_book_depth():
    engine = MatchingEngine("BTC-USDT")
    for order_id, price, quantity in (
        ("market-maker-a", Decimal("100"), Decimal("5000")),
        ("market-maker-b", Decimal("110"), Decimal("5000")),
    ):
        engine.submit_order(Order(
            order_id=order_id, client_order_id=f"{order_id}-client", trader_id="maker",
            symbol="BTC-USDT", side=Side.SELL, order_type=OrderType.LIMIT,
            price=price, quantity=quantity,
        ))
    oversized = Order(
        order_id="large-market", client_order_id="large-market-client", trader_id="taker",
        symbol="BTC-USDT", side=Side.BUY, order_type=OrderType.MARKET,
        price=Decimal("0"), quantity=Decimal("10000"),
    )

    result, trades, decision = engine.submit_order(oversized)
    assert result.status == OrderStatus.REJECTED
    assert trades == []
    assert decision.code == "MAX_NOTIONAL_BREACH"
    assert engine.book.get_best_ask() == Decimal("100")


def test_market_order_without_reference_liquidity_is_rejected():
    engine = MatchingEngine("BTC-USDT")
    order = Order(
        order_id="market-empty", client_order_id="market-empty-client", trader_id="taker",
        symbol="BTC-USDT", side=Side.BUY, order_type=OrderType.MARKET,
        price=Decimal("0"), quantity=Decimal("1"),
    )
    _, trades, decision = engine.submit_order(order)
    assert trades == []
    assert decision.code == "MARKET_REFERENCE_UNAVAILABLE"


def test_engine_rejects_symbol_mismatch_and_duplicate_order_id():
    engine = MatchingEngine("BTC-USDT")
    wrong_symbol = Order(
        order_id="shared-id", client_order_id="wrong-symbol-client", trader_id="t1",
        symbol="ETH-USDT", side=Side.BUY, order_type=OrderType.LIMIT,
        price=Decimal("50"), quantity=Decimal("1"),
    )
    _, _, symbol_decision = engine.submit_order(wrong_symbol)
    assert symbol_decision.code == "SYMBOL_MISMATCH"

    valid = Order(
        order_id="shared-id", client_order_id="valid-client", trader_id="t1",
        symbol="BTC-USDT", side=Side.BUY, order_type=OrderType.LIMIT,
        price=Decimal("50"), quantity=Decimal("1"),
    )
    engine.submit_order(valid)
    duplicate = Order(
        order_id="shared-id", client_order_id="duplicate-client", trader_id="t2",
        symbol="BTC-USDT", side=Side.SELL, order_type=OrderType.LIMIT,
        price=Decimal("60"), quantity=Decimal("1"),
    )
    result, _, duplicate_decision = engine.submit_order(duplicate)
    assert result.status == OrderStatus.REJECTED
    assert duplicate_decision.code == "DUPLICATE_ORDER_ID"
    assert engine.book.get_best_bid() == Decimal("50")


def test_audit_ledger_cryptographic_chain():
    ledger = AuditLedger()
    ledger.record_event("ORDER_NEW", {"order_id": "1"}, sequence_num=1, timestamp_ns=1000)
    ledger.record_event("TRADE_EXEC", {"trade_id": "t1"}, sequence_num=2, timestamp_ns=1001)
    ledger.record_event("ORDER_CANCEL", {"order_id": "2"}, sequence_num=3, timestamp_ns=1002)

    assert len(ledger.entries) == 3
    assert ledger.verify_chain_integrity()

    # Tamper with an entry payload to ensure tampering is detected
    ledger.entries[1].payload["trade_id"] = "tampered"
    assert not ledger.verify_chain_integrity()


def test_audit_ledger_detects_timestamp_and_truncation_tampering():
    ledger = AuditLedger()
    ledger.record_event("ORDER_NEW", {"order_id": "1"}, sequence_num=1, timestamp_ns=1000)
    ledger.record_event("ORDER_CANCEL", {"order_id": "1"}, sequence_num=2, timestamp_ns=1001)
    ledger.entries[0].timestamp_ns += 1
    assert not ledger.verify_chain_integrity()

    intact = AuditLedger()
    intact.record_event("ORDER_NEW", {"order_id": "1"}, sequence_num=1, timestamp_ns=1000)
    intact.record_event("ORDER_CANCEL", {"order_id": "1"}, sequence_num=2, timestamp_ns=1001)
    intact.entries.pop()
    assert not intact.verify_chain_integrity()


def test_audit_ledger_requires_strictly_increasing_sequences():
    ledger = AuditLedger()
    with pytest.raises(ValueError, match="positive integer"):
        ledger.record_event("INVALID", {}, sequence_num=0, timestamp_ns=999)
    ledger.record_event("ORDER_NEW", {}, sequence_num=3, timestamp_ns=1000)
    with pytest.raises(ValueError, match="increase strictly"):
        ledger.record_event("ORDER_CANCEL", {}, sequence_num=3, timestamp_ns=1001)
