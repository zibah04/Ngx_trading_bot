# Instructions for Codex: TradeAssist AI research prototype

This is a research-only Python/Streamlit prototype for Nigerian Exchange stocks.

## How to work
- Run `python -m pip install -r requirements-dev.txt` before executing tests.
- Run `python -m pytest -q` after changes and report test numbers and failures.
- Run `python -m compileall -q app.py ngxintel tests` for syntax checks.
- For dashboard smoke tests, run `streamlit run app.py --server.headless true --server.port 8501` and inspect startup logs; do not describe this as a browser/UI test unless browser interaction actually happened.
- Keep implementation changes small, tests deterministic, and fixtures fictional. Never treat synthetic demo symbols as real market quotes.
- Do not require API keys or network access for unit tests. Use mocks for providers and LLM calls.

## Critical safeguards
- Research / paper testing ONLY; never place actual market orders or add live order execution without separate explicit authorization and verification.
- Do not imply signal strength (4/4) is calibrated probability or that backtest accuracy guarantees profitability.
- No historical lookahead: calculate signals from bars at or before signal timestamp; entry cannot precede the signal; judge outcomes using only subsequent timestamps.
- For ambiguous high-low candles where both stop and target are hit, apply documented stop-first assumption.
- Treat SELL as bearish/exit research only; never model short-selling as available by default on NGX.
- Data from external services must respect provider licensing, rate limits, and credential confidentiality. Never commit `.env`, database files, API keys, or raw licensed data.
- Do not switch DAY mode onto daily OHLCV bars or let a day trade silently carry into a new session.
- Explain missing market prices / unsupported claims clearly. No invented quotes, performance statistics, or live-data availability.

## Core files
- `app.py`: Streamlit user interface
- `ngxintel/data.py`: CSV normalization and optional market-data API
- `ngxintel/signals.py`: deterministic signals and indicators
- `ngxintel/evaluation.py`: target/stop evaluation
- `ngxintel/backtest.py`: historical bar-based simulation
- `ngxintel/ledger.py`: prediction journal and evaluations
- `ngxintel/news.py`: optional public headlines / research summaries
- `tests/`: offline deterministic tests

## Good next milestones
1. Fully cover data validation, session boundaries, and API failure paths with unit tests.
2. Separate prediction hit rate from **net** simulated profitability and benchmark comparisons.
3. Add walk-forward evaluation that stores predictions prior to outcomes.
4. Add explicit execution-feasibility checks for spreads, volume, costs, and missing quotes, before contemplating broker integration.
