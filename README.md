# High-Throughput Order Matching & Pre-Trade Risk Engine

[![Test Suite](https://img.shields.io/badge/pytest-12%2F12%20passed-brightgreen.svg)]()
[![Evaluation Accuracy](https://img.shields.io/badge/eval%20accuracy-100%25%20(10%2F10)-blue.svg)]()
[![Architecture](https://img.shields.io/badge/matching-L3%20Price--Time%20FIFO-orange.svg)]()
[![Integrity](https://img.shields.io/badge/audit-SHA--256%20Cryptographic%20Root-purple.svg)]()

A high-performance limit order book (LOB) matching engine and real-time pre-trade risk gateway featuring **L3 price-time priority (FIFO)**, continuous double auction matching, **sub-millisecond execution**, **fat-finger price collars**, **self-trade prevention (STP)**, and an **append-only cryptographic audit ledger**.

Engineered specifically as demonstrable systems proof for quantitative trading platforms, market makers, and licensed digital asset exchanges in **Hong Kong** and **Tokyo** (*Flow Traders, HashKey Group, Jane Street HK, Rakuten FinTech, Sony Block Solutions / Soneium, and SBI / B2C2 Japan*).

---

## Architecture Overview

```mermaid
flowchart TD
    subgraph Ingestion
        Ord["Client Order\n(cl_ord_id, trader_id, side, price, qty)"]
    end

    subgraph Pre-Trade Risk Gateway
        G1{"Sanity Check\n(price > 0, qty > 0)"}
        G2{"Max Notional Gate\n($1M Single Order Cap)"}
        G3{"Price Collar Gate\n(BBO ±5% Fat-Finger Filter)"}
        G4{"Self-Trade Prevention\n(Wash-Trade Interception)"}
    end

    subgraph L3 Limit Order Book
        LOB["Continuous Double Auction\nPrice-Time Priority (FIFO)"]
        Crossing{"Price Cross\nCondition Met?"}
        Fill["Execute Trade\n(Passive Maker Price)"]
        Rest["Rest on Book\n(Residual Quantity)"]
    end

    subgraph Settlement & Audit
        Ledger["Append-Only Cryptographic Ledger\n(Monotonic 64-bit Seq + SHA-256 State Root)"]
    end

    Ord --> G1
    G1 -- Pass --> G2
    G2 -- Pass --> G3
    G3 -- Pass --> G4
    G4 -- Pass --> LOB

    G1 -- Reject --> Ledger
    G2 -- Reject --> Ledger
    G3 -- Reject --> Ledger
    G4 -- Reject --> Ledger

    LOB --> Crossing
    Crossing -- Yes --> Fill --> Ledger
    Crossing -- Residual --> Rest --> Ledger
```

---

## Core Capabilities

1. **L3 Limit Order Book:**
   - Strict continuous double auction adhering to price-time priority (FIFO per price tick).
   - Fast $O(1)$ BBO resolution and $O(1)$ order cancellation indexing.
   - L3 depth aggregation and order book snapshots.

2. **Pre-Trade Risk Gateway:**
   - **Price Collar Protection:** Rejects fat-finger aggressive limit orders deviating by more than 5% from the Best Bid/Offer (BBO).
   - **Self-Trade Prevention (STP):** Intercepts and halts internal wash trades between identical trader accounts.
   - **Max Notional Filter:** Rejects orders exceeding single-order capitalization thresholds ($1,000,000 / ¥150,000,000 cap).

3. **Advanced Order Types & Lifecycle:**
   - **Limit Orders (`LIMIT`):** Crosses matching passive liquidity; rests remainder on book.
   - **Market Orders (`MARKET`):** Aggressive liquidity taker that sweeps opposing price levels down the book.
   - **Immediate-or-Cancel (`IOC`):** Fills available resting shares and cancels unfilled residual without resting.
   - **Post-Only (`POST_ONLY`):** Maker-or-cancel; rejects immediately if the order would cross resting orders.
   - **Atomic Cancel/Replace:** Atomically cancels an active resting order and submits a replacement at a new price level.

4. **Cryptographic Audit Ledger & Replay:**
   - Append-only event journal capturing order acceptances, cancellations, rejections, and trade fills.
   - Rolling SHA-256 state root ensuring tamper-evident state verification and 100% deterministic replay.

---

## Quickstart

### Installation
```bash
git clone https://github.com/elura172/order-matching-engine.git
cd order-matching-engine
uv sync
```

### Running the Test Suite
```bash
uv run pytest -v
```

### Running the Interactive Demonstration
```bash
uv run python demo.py
```

---

## Automated Institutional Evaluation Suite (10 Scenarios)

The engine features a built-in automated institutional trading benchmark covering 10 strict production scenarios:

| # | Scenario ID | Description | Specification & Metric |
|---|---|---|---|
| 01 | `01_SIMPLE_LIMIT_MATCH` | Crossing limit orders execute full fill at maker price | 10.0 filled @ $100.00 |
| 02 | `02_PARTIAL_FILL_AND_REST` | Taker partially fills resting maker; residual rests as new maker bid | 10.0 filled / 5.0 resting |
| 03 | `03_PRICE_TIME_PRIORITY` | Orders at identical price fill in strict arrival FIFO order | FIFO Priority Verified |
| 04 | `04_MARKET_ORDER_SWEEP` | Market buy sweeps multiple ask levels down the book | Swept 3 Price Levels |
| 05 | `05_IOC_CANCELLATION` | Immediate-or-Cancel fills available liquidity, cancels remainder | 5 filled / 5 cancelled |
| 06 | `06_CANCEL_REPLACE` | Resting order is cancelled and replaced atomically at new price | Atomic Cancel/Replace Verified |
| 07 | `07_SELF_TRADE_PREVENTION` | Pre-trade risk gate halts self-match between identical trader accounts | Wash Trade Intercepted |
| 08 | `08_PRICE_COLLAR_FAT_FINGER` | Fat-finger price (+10% from BBO) rejected by pre-trade collar gate | Price Collar Enforced (>5%) |
| 09 | `09_MAX_NOTIONAL_BREACH` | Order exceeding $1,000,000 maximum single-order notional rejected | Notional Limit Enforced |
| 10 | `10_DETERMINISTIC_REPLAY_HASH` | Replaying deterministic order stream produces identical SHA-256 state root | Deterministic Replay Certified |

---

## Author
**Paul Trafford (`elura172`)**  
*AI Systems & Distributed Infrastructure Engineer*  
GitHub: [github.com/elura172](https://github.com/elura172) · LinkedIn: [linkedin.com/in/paul-trafford-352068434](https://www.linkedin.com/in/paul-trafford-352068434)
