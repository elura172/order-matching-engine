#!/usr/bin/env python3
"""Interactive terminal demonstration of the Order Matching & Pre-Trade Risk Engine."""

import time
from decimal import Decimal
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from src.engine.matcher import MatchingEngine
from src.evals.harness import EvaluationBenchmarkHarness
from src.models.types import Order, OrderType, Side

console = Console()


def render_banner() -> None:
    console.print(
        Panel(
            "[bold white]HIGH-THROUGHPUT ORDER MATCHING & PRE-TRADE RISK ENGINE[/bold white]\n"
            "[cyan]L3 Price-Time Priority · Continuous Double Auction · Fat-Finger Collars · STP[/cyan]\n"
            "[green]Author: elura172 (@elura172) · Hong Kong & Tokyo Quant/FinTech Pipeline[/green]",
            border_style="bright_blue",
            expand=False,
        )
    )


def demo_live_book() -> None:
    console.print("\n[bold yellow]▶ STEP 1: Live L3 Order Book Construction & Aggressive Sweep[/bold yellow]")
    engine = MatchingEngine("BTC-USDT")

    # Seed book with resting bids and asks
    bids_data = [
        ("trader-a", Decimal("64800.00"), Decimal("2.5")),
        ("trader-b", Decimal("64790.00"), Decimal("5.0")),
        ("trader-c", Decimal("64750.00"), Decimal("10.0")),
    ]
    asks_data = [
        ("trader-d", Decimal("64820.00"), Decimal("1.5")),
        ("trader-e", Decimal("64830.00"), Decimal("4.0")),
        ("trader-f", Decimal("64850.00"), Decimal("8.0")),
    ]

    for t, p, q in bids_data:
        engine.submit_order(
            Order(
                order_id=f"bid-{p}",
                client_order_id=f"cl-bid-{p}",
                trader_id=t,
                symbol="BTC-USDT",
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                price=p,
                quantity=q,
            )
        )

    for t, p, q in asks_data:
        engine.submit_order(
            Order(
                order_id=f"ask-{p}",
                client_order_id=f"cl-ask-{p}",
                trader_id=t,
                symbol="BTC-USDT",
                side=Side.SELL,
                order_type=OrderType.LIMIT,
                price=p,
                quantity=q,
            )
        )

    # Render order book depth
    snap = engine.book.get_snapshot(depth=5)
    book_table = Table(title="BTC-USDT Order Book Snapshot (Depth = 3)", border_style="cyan")
    book_table.add_column("Bid Qty", justify="right", style="green")
    book_table.add_column("Bid Price", justify="right", style="bold green")
    book_table.add_column("Ask Price", justify="left", style="bold red")
    book_table.add_column("Ask Qty", justify="left", style="red")

    max_rows = max(len(snap.bids), len(snap.asks))
    for i in range(max_rows):
        b_qty = f"{snap.bids[i].quantity:.2f}" if i < len(snap.bids) else ""
        b_prc = f"${snap.bids[i].price:,.2f}" if i < len(snap.bids) else ""
        a_prc = f"${snap.asks[i].price:,.2f}" if i < len(snap.asks) else ""
        a_qty = f"{snap.asks[i].quantity:.2f}" if i < len(snap.asks) else ""
        book_table.add_row(b_qty, b_prc, a_prc, a_qty)

    console.print(book_table)
    console.print(f"  [dim]BBO Spread: ${snap.spread:,.2f} | Best Bid: ${snap.best_bid:,.2f} | Best Ask: ${snap.best_ask:,.2f}[/dim]\n")

    # Aggressive Market Order Sweep
    console.print("  [bold]Executing aggressive Market Buy for 6.0 BTC (Sweeps multiple ask levels)...[/bold]")
    sweep_order = Order(
        order_id="taker-sweep",
        client_order_id="cl-sweep-01",
        trader_id="institutional-alpha",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        price=Decimal("0.0"),
        quantity=Decimal("6.0"),
    )
    t0 = time.perf_counter_ns()
    res_order, trades, _ = engine.submit_order(sweep_order)
    dt_us = (time.perf_counter_ns() - t0) / 1000

    trade_table = Table(title=f"Trades Generated in {dt_us:.1f}µs", border_style="magenta")
    trade_table.add_column("Trade ID", style="dim")
    trade_table.add_column("Fill Price", justify="right", style="bold yellow")
    trade_table.add_column("Qty Filled", justify="right", style="bold white")
    trade_table.add_column("Maker Trader", style="cyan")
    trade_table.add_column("Taker Trader", style="green")

    for tr in trades:
        trade_table.add_row(
            tr.trade_id,
            f"${tr.price:,.2f}",
            f"{tr.quantity:.2f} BTC",
            tr.maker_trader_id,
            tr.taker_trader_id,
        )
    console.print(trade_table)


def demo_risk_gates() -> None:
    console.print("\n[bold yellow]▶ STEP 2: Pre-Trade Risk Gate Interceptions[/bold yellow]")
    engine = MatchingEngine("BTC-USDT")
    engine.submit_order(
        Order(
            order_id="ref-maker",
            client_order_id="cl-ref",
            trader_id="market-maker-1",
            symbol="BTC-USDT",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            price=Decimal("65000.00"),
            quantity=Decimal("10.0"),
        )
    )

    # 1. Fat finger collar
    fat_finger = Order(
        order_id="ff-1",
        client_order_id="cl-ff-1",
        trader_id="careless-trader",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("72000.00"),  # > 10% deviation
        quantity=Decimal("1.0"),
    )
    _, _, d1 = engine.submit_order(fat_finger)
    console.print(f"  [bold red]✖ FAT-FINGER COLLAR:[/bold red] Order at $72,000.00 [red]REJECTED[/red]")
    console.print(f"    [dim]Reason: {d1.reason}[/dim]")

    # 2. Self-trade prevention
    wash_trade = Order(
        order_id="wash-1",
        client_order_id="cl-wash-1",
        trader_id="market-maker-1",  # Same as resting sell!
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        price=Decimal("65000.00"),
        quantity=Decimal("2.0"),
    )
    _, _, d2 = engine.submit_order(wash_trade)
    console.print(f"  [bold red]✖ SELF-TRADE PREVENTION:[/bold red] Internal wash trade [red]REJECTED[/red]")
    console.print(f"    [dim]Reason: {d2.reason}[/dim]")


def run_benchmark_suite() -> None:
    console.print("\n[bold yellow]▶ STEP 3: Running 10-Scenario Automated Institutional Benchmark[/bold yellow]")
    harness = EvaluationBenchmarkHarness("BTC-USDT")
    t0 = time.perf_counter()
    results = harness.run_all_scenarios()
    total_time_ms = (time.perf_counter() - t0) * 1000

    table = Table(title="Order Matching & Pre-Trade Risk Evaluation Benchmark", border_style="bright_blue")
    table.add_column("Scenario ID", style="bold cyan")
    table.add_column("Description", style="white")
    table.add_column("Metric / Status Detail", style="dim")
    table.add_column("Verdict", justify="center")

    passed_count = 0
    for r in results:
        if r.passed:
            passed_count += 1
            verdict = "[bold green]PASS[/bold green]"
        else:
            verdict = "[bold red]FAIL[/bold red]"
        table.add_row(r.scenario_id, r.description, r.metric, verdict)

    console.print(table)
    pct = (passed_count / len(results)) * 100
    summary = (
        f"[bold]Total Scenarios:[/bold] {len(results)} | "
        f"[bold green]Passed:[/bold green] {passed_count} | "
        f"[bold red]Failed:[/bold red] {len(results) - passed_count} | "
        f"[bold]Pass Rate:[/bold] [bold green]{pct:.1f}%[/bold green] | "
        f"[bold]Execution Time:[/bold] [bold cyan]{total_time_ms:.2f}ms[/bold cyan]"
    )
    console.print(Panel(summary, border_style="green" if passed_count == len(results) else "red"))


if __name__ == "__main__":
    render_banner()
    demo_live_book()
    demo_risk_gates()
    run_benchmark_suite()
