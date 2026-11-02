# TradeAssist AI — Codex project handoff

## Product purpose and distinction

**TradeAssist AI** is a Nigerian Exchange (NGX) research assistant covering market history, news and financial disclosures, technical trading indicators, BUY/SELL/WAIT suggestions, and measurable prediction outcomes. It is **not** the separate pre-existing project `Ngx_trading_bot`, which explores simulated/broker execution. Keep the projects logically independent and do not modify the trading bot as part of TradeAssist AI tasks.

## What the user requested

- Support **short-term/day trading** and **swing trading**, with separate strategies and statistics.
- Gather **historical market prices, volumes**, financial news, company disclosures and macroeconomic context from properly licensed/authorized data sources.
- Provide transparent **BUY/SELL/WAIT research signals** with dates, target/stop conditions, entry assumptions and confidence labels (if and only if statistically calibrated).
- **Measure correctness:** Persist each prediction BEFORE the result is known; later use newly available data to classify target-first, stop-first, expired and still-pending outcomes.
- Show performance by symbol, mode, period and strategy, including hit rate, profitable-trade percentage, net-return assumptions, costs, liquidity and drawdown.
- Use historical backtests and forward/paper validation; do not portray backtest results as live performance.
- Add AI news/disclosure interpretation later, tied to citeable provenance and timestamps; no claims that keyword sentiment is a trained predictive model.
- Eventually integrate with the older trading bot only by an intentional reviewed boundary/API — not now.

## Current code at handoff (v0.1 prototype)

- Streamlit `app.py` with synthetic demo, CSV uploads and optional Investo daily-price fetch.
- `ngxintel/signals.py` supplies transparent rule-based BUY/SELL/WAIT; it is NOT an AI forecasting model.
- `ngxintel/backtest.py` bar-based simulation with next-bar-open entry and stop-first ambiguous-bar convention.
- `ngxintel/ledger.py` journal and delayed outcome evaluation.
- `ngxintel/news.py` headline discovery and optional LLM news brief; **not** a trading-signal input.
- Intraday research only with user-supplied intraday CSV; no real-time NGX feed, no broker trading, no calibrated forecast probability.
- 23 local pytest tests passed on November 2, 2026; live API and full Streamlit browser functionality have not been verified.

## Codex environment

Use Python 3.11 or 3.12. In repository root:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q app.py ngxintel tests
```

For a headless smoke test **if Streamlit installs**:

```bash
python -m streamlit run app.py --server.headless true --server.port 8501
```

Read `AGENTS.md` before edits and `SOURCES_AND_RESOURCES.md` for provider restrictions. No API keys are necessary for deterministic tests. Never commit secrets or bulk licensed market data.

## Suggested first Codex task

"You are taking over TradeAssist AI (NOT the separate Ngx_trading_bot). Read AGENTS.md and HANDOFF_TO_CODEX.md. Install dependencies and run pytest and compileall. Smoke-test Streamlit startup when possible. Fix actual failures, add deterministic tests for future-only prediction evaluation, intraday session boundaries, data normalization and missing/faulty price data. Preserve the existing signal/ledger behaviour. Produce a concise report of exact tests and limitations. Do not add live trading or claim a trained/calibrated AI model exists. Create a pull request containing reviewed fixes."

## Future milestones after baseline verification

1. Validate real end-of-day data quality and permissions; add robust timestamp/corporate-action handling.
2. Create paper trading and out-of-sample forward statistics for DAY versus SWING separately.
3. Add scheduled news ingestion, source attribution, entity matching and publication-time controls.
4. Compare basic technical strategies with genuinely trained, temporally validated models.
5. Add latency/liquidity/execution-feasibility constraints to DAY research (not execution).

**Scope:** Personal research and simulated signals only. It is not investment advice and cannot reliably guarantee profit.
