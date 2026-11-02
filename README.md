# TradeAssist AI — NGX research and prediction tracker (v0.1)

A runnable Python/Streamlit research tool for the Nigerian Exchange. It **does not** connect to a broker, place orders, predict with calibrated AI probabilities, or make financial decisions for you.

### What is already working

- **Three data routes:** built-in **fictional synthetic demo**, manually uploaded **CSV historical OHLCV**, and documented **Investo API** daily price-history endpoint (requires your own key).
- **Daily swing signals** based on SMA(10/25), RSI(14), five-bar momentum, price trend and average trading-volume gate.
- **Day research mode** for genuine intraday bars uploaded by CSV — daily bars are explicitly rejected in DAY mode.
- **Time-respecting historical simulation:** signal uses only bars known at close; theoretical entry occurs at the *following* bar's open; target/stop evaluated from actual subsequent OHLC, stopping before duplicate overlapping signals.
- **SQLite prediction journal:** records BUY/SELL alerts immutably and only resolves them when newer bars are supplied.
- **Accuracy evaluation:** target-hit rate, profitable BUY-trade percentage and indicative BUY-only net returns with user-specified round-trip cost assumptions.
- **Financial news discovery:** live Google News RSS headlines and basic keyword tags; optional Investo API links to original corporate disclosure PDFs. Optional OpenAI API summary of the headlines; it does **not** feed the historical model.
- **CSV downloads** of signals history and backtests.

## Run it (Windows / PowerShell)

1. Install Python 3.11+ and unzip this folder. Open a terminal in it.
2. Install dependencies in a virtual environment:

   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Start the application:

   ```powershell
   streamlit run app.py
   ```

4. Alternatively, double-click `RUN_ON_WINDOWS.bat` in File Explorer to set up and launch automatically (Python and internet required for the first install).

5. The browser usually opens at `http://localhost:8501`. Choose **Synthetic demo** to explore the interface immediately; **none of its prices are real NGX quotes**.

### Connect actual NGX daily prices

- Request an Investo developer key at https://investo.ng/developers (API use/availability controlled by provider).
- In the app select **Investo NGX API**, paste your key, choose ticker names, and press **Fetch NGX historical prices**.
- Alternatively, choose **CSV upload** and upload a licensed dataset with `date,symbol,open,high,low,close,volume`. For intraday uploads use `timestamp` rather than `date`, e.g. `2026-10-29 09:05:00`.
- Credentials may also be placed in a local `.env` file copied from `.env.example` (never commit it).
- Official NGX historic datasets may require purchase/license: https://ngxgroup.com/exchange/data/historical-data/.

### How predictions are judged

A BUY forecast expects the target (above the reference) *before* the stop (below it). A SELL forecast expects a price decline to the lower target before the higher invalidation stop; it is an **exit/bearish signal, not a short position**.

Prediction journal: after clicking **Record current BUY/SELL alerts**, later reload a dataset with more observations and click **Evaluate pending alerts**. The journal never uses prior/current bars to judge a newly created alert; it looks exclusively at timestamps **after** the recorded alert. If the target comes first = `WIN`; if stop first = `LOSS`; if horizon bars pass without either = `EXPIRED`. Pending alerts are excluded from the hit rate; expired alerts count as non-hits. Both hit in one bar = `LOSS`. When OHLC high/low is missing, only the close is checked for that bar, and this is indicated; either stop or target touches can be missed, so interpret such outcomes cautiously.

Historical backtest: fills BUY hypothetically at the **next bar OPEN** (it skips missing opens rather than pretending to know the price). It applies take-profit and stop thresholds calculated from that entry, then deducts a *hypothetical* round-trip cost in bps from BUY results. SELL signals are tested as directional forecasts and excluded from trade returns since ordinary NGX equities can't simply be assumed to be shortable. Signals are non-overlapping, not recalculated with future price information.

Accuracy is **not** calibrated confidence. It measures past target-before-stop frequency, not expected returns or a guarantee. Even high accuracy can lose money once transaction costs, spreads, slippage, taxes and low liquidity are accounted for. Long-side cumulative returns are schematic and assume full sequential reinvestment of each BUY-only trade.

### Important limitations / future milestones

- **No actual intraday feed** comes with the app. The Investo API route returns daily bars only. High-frequency NGX trading needs licensed live intraday and bid/ask data, liquidity controls, and a broker execution API. DAY mode accepts user-supplied intraday candles for research only; ensure a chosen evaluation horizon remains within the trading session. DAY-mode backtesting requires an entry and complete evaluation window within the same calendar trading day; otherwise it skips the alert. The journal expires outstanding DAY alerts when it sees observations from a later session. Never interpret it as a real execution simulator.
- Backtests need adjusted prices/corporate action info and fully time-consistent source availability to be trustworthy; raw close may miss split/dividend effects. Bar-level stop-first assumptions remain approximations; gaps can produce worse fills.
- Current signal strength is simply a count of aligned indicators (`4/4`) — **not a 75% or 80% probability**. No neural network / trained price forecaster is included yet.
- Headline sources are unverified and may contain irrelevant results. Do not treat keyword tags as predictive sentiment. LLM brief costs are determined by your OpenAI API account and may be unavailable.
- Local Streamlit + SQLite is a *single-user* research setup, not a secure hosted product. Forecast history can be lost when the database is removed. Back it up if needed.
- No automatic updates or trade execution. Data licenses and Nigerian SEC regulatory rules matter if commercializing.
- **Investo terms** allow transient caching for personal app analysis, but not permanent mirrors or redistribution of raw data: https://investo.ng/api-terms. This app doesn't persist the raw API price response to disk. Only derived prediction records are saved locally.

### Project structure

```text
app.py                    Dashboard
ngxintel/data.py          CSV and Investo client with strict validation
ngxintel/signals.py       Transparent rules-based signals
ngxintel/evaluation.py    Future-only target/stop evaluator
ngxintel/backtest.py      Historical simulation
ngxintel/ledger.py        SQLite immutable prediction log
ngxintel/news.py          RSS, corporate filings discovery, optional LLM brief
ngxintel/demo.py          Explicitly fictional test candles
tests/                     Automated tests
storage/                   SQLite data (ignored by Git)
```

## Test

```bash
python -m pytest -q
```

**Use for learning and research; there is no assurance of accuracy, suitability or profitability.**

## Codex Cloud and automated testing

The project contains `AGENTS.md` (repo-specific coding rules), `CODEX_START.md` (setup and first-task prompt), `requirements-dev.txt` (test dependencies), and `.github/workflows/tests.yml` (GitHub Actions CI). Connect a GitHub repository in Codex Cloud or open the local folder in Codex for VS Code. Run:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q app.py ngxintel tests
```

**Important:** GitHub Actions runs checks on GitHub; it is distinct from a Codex task. A Codex task can also run these commands inside its own cloud environment. Both use synthetic/mocked data and neither constitutes a live-data or broker-integration test.

## Resources and handoff

- [`SOURCES_AND_RESOURCES.md`](SOURCES_AND_RESOURCES.md): one-stop links to install tools, legal price data and official macro/filings sources.
- [`HANDOFF_TO_CODEX.md`](HANDOFF_TO_CODEX.md): project goals, current progress, gaps and a ready-made Codex task prompt.
- The old `Ngx_trading_bot` remains a separate project. TradeAssist AI does not contain or call live broker execution.
