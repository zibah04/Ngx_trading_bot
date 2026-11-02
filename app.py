"""TradeAssist AI — practical research / prediction-tracking MVP."""
import os
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv
from ngxintel.data import DataError, csv_to_bars, fetch_investo
from ngxintel.demo import generate_demo
from ngxintel.signals import calculate_signal, indicators, MIN_BARS, VERSION
from ngxintel.backtest import run_backtest, metrics
from ngxintel.ledger import connection, record, evaluate, load, summary
from ngxintel.news import fetch_headlines, ai_news_brief, fetch_filings

load_dotenv()
st.set_page_config(page_title="TradeAssist AI", page_icon="📈", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
  .block-container {max-width: 1450px; padding-top: 2rem}
  h1,h2,h3 {letter-spacing: -.035em}
  [data-testid="stMetric"] {border:1px solid #334155; border-radius:12px; padding:14px}
  div[data-testid="stAlert"] {border-radius: 10px}
  .tag {display:inline-block; border:1px solid #365f7d; background: #0c2436;
       color:#b6e0ff; font-weight:600; padding:4px 12px; border-radius: 30px}
</style>""", unsafe_allow_html=True)

st.title("📈 TradeAssist AI")
st.caption(f"Research dashboard · Signal engine {VERSION} · Forward prediction ledger · No broker orders")
st.warning("⚠️ Research and paper testing only. Signals are rules-based, not calibrated AI probabilities or investment advice. No automatic trades are placed.")

with st.sidebar:
    st.header("🔌 Data source")
    source_kind = st.selectbox("Choose data", ["Synthetic demo", "CSV upload", "Investo NGX API"])
    st.divider()
    mode = st.radio("Strategy mode", ["SWING", "DAY"], horizontal=True,
                    help="DAY only works with genuine intraday bars. Never apply it to daily candles.")
    horizon = st.slider("Evaluation horizon (bars)", min_value=2, max_value=30,
                        value=5 if mode == "SWING" else 8)
    min_volume = st.number_input("Minimum mean bar volume", min_value=0, max_value=50_000_000,
                                 value=20_000 if mode == "SWING" else 1000, step=1000)
    stop_pct = st.slider("Stop distance (%)", 1.0, 12.0, 3.0, step=0.5) / 100
    reward_multiple = st.slider("Target / stop distance ratio", 1.0, 4.0, 2.0, step=0.25)
    roundtrip_bps = st.slider("Estimated round-trip costs (basis points)", 0, 400, 100, step=10,
                              help="100 bps = 1.00% of entry value, modelled as a cost deduction. Adjust to your broker.")
    st.caption("The default cost assumption is an illustrative placeholder—not verified broker pricing.")

bars = None
source_id = {"Synthetic demo":"DEMO_SYNTHETIC", "CSV upload":"CSV_USER", "Investo NGX API":"INVESTO"}[source_kind]
if source_kind == "Synthetic demo":
    bars = generate_demo()
    st.error("🧪 **SYNTHETIC DEMO DATA.** DEMO_ALPHA, DEMO_BETA and DEMO_GAMMA are fictional; prices are artificially generated. Never use these signals for real trading.")
elif source_kind == "CSV upload":
    upload = st.file_uploader("Upload CSV with date/timestamp, close, optional symbol/open/high/low/volume", type="csv")
    st.caption("Example: date,symbol,open,high,low,close,volume. Include real timestamps for DAY mode. Price data should be properly licensed.")
    if upload is not None:
        try:
            bars = csv_to_bars(upload)
        except Exception as exc:
            st.error(f"Could not read CSV: {exc}")
else:
    st.info("Optional live API connection. Investo uses **end-of-day** quotes, not real-time execution data. History is kept in memory, not permanently mirrored. Data attribution: Investo — investo.ng")
    key = st.text_input("Investo API key", type="password", value=os.getenv("INVESTO_API_KEY", ""))
    syms = st.text_input("NGX tickers (comma-separated)", "GTCO, UBA, ZENITHBANK")
    days = st.select_slider("History lookback (calendar days)", options=[90, 180, 365, 730], value=365)
    if st.button("Fetch NGX historical prices", type="primary"):
        try:
            with st.spinner("Fetching market data…"):
                st.session_state["investo_bars"] = fetch_investo(
                    [s.strip() for s in syms.split(",") if s.strip()], key, days)
            st.success("NGX data loaded into this app session.")
        except Exception as exc:
            st.error(str(exc))
    bars = st.session_state.get("investo_bars")

if bars is None:
    st.info("Choose a data source above to begin. **Synthetic demo** works without any account or API key.")
    st.stop()

bars = bars.sort_values(["symbol", "timestamp"])
if bars.empty:
    st.stop()

# A day strategy must not quietly use end-of-day prices as if they were intraday.
def is_intraday(data):
    return bool(data.groupby([data.symbol, data.timestamp.dt.date]).size().max() >= 2)

if mode == "DAY" and not is_intraday(bars):
    st.error("⛔ DAY mode requires multiple timestamped bars per trading day (e.g. 5-minute candles). Current data is end-of-day only. Switch to SWING or upload genuine intraday bars.")
    st.stop()

symbols = sorted(bars.symbol.unique())
selected = st.selectbox("Inspect symbol", symbols)
frame = bars[bars.symbol == selected].copy().sort_values("timestamp").reset_index(drop=True)
source_info = f"Source: {source_kind} · Latest observation: {frame.timestamp.max()} · Bars: {len(frame)}"
st.caption(source_info)
if source_kind == "Investo NGX API":
    st.caption("Data: Investo — investo.ng · The latest observation is NOT a live tradeable quote.")

conn = connection()
tabs = st.tabs(["🔍 Market scanner", "🧪 Backtesting", "📒 Accuracy ledger", "🗞️ News research", "📁 Data and methods"])

with tabs[0]:
    st.subheader("Market signals")
    signals = []
    for sym in symbols:
        subset = bars[bars.symbol == sym]
        signals.append(calculate_signal(subset, mode, source_id, min_volume, stop_pct, reward_multiple))
    tabrows = []
    for signal in signals:
        tabrows.append({"Symbol":signal.symbol, "Signal": signal.action,
                        "Last observed price (₦)":round(signal.reference_price, 4),
                        "Strength (not probability)":f"{signal.strength}/{signal.strength_max}",
                        "Target (₦)":signal.target, "Stop (₦)":signal.stop,
                        "Timestamp": signal.signal_time})
    st.dataframe(pd.DataFrame(tabrows), hide_index=True, use_container_width=True)
    selected_signal = next(s for s in signals if s.symbol == selected)
    st.info(f"**{selected}: {selected_signal.action}** · {selected_signal.reason}")
    if len(frame) >= 25:
        tech = indicators(frame)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=tech.timestamp, y=tech.close, name="Observed close", mode="lines"))
        fig.add_trace(go.Scatter(x=tech.timestamp, y=tech.sma10, name="SMA10", mode="lines"))
        fig.add_trace(go.Scatter(x=tech.timestamp, y=tech.sma25, name="SMA25", mode="lines"))
        fig.update_layout(height=390, margin=dict(l=10, r=10, t=20, b=20),
                          yaxis_title="Price (₦)", xaxis_title="Observation time")
        st.plotly_chart(fig, use_container_width=True)
    if st.button("🔒 Record current BUY/SELL alerts", type="primary"):
        count = sum(record(conn, s, horizon) for s in signals)
        st.success(f"Recorded {count} new immutable alert(s). WAIT signals are not recorded; duplicates are ignored. Alerts are reference levels, not executions.")
    st.caption("SMA10 vs SMA25 + RSI14 + five-bar momentum + price above/below SMA10; four conditions required. Missing volume means WAIT. Strength is an indicator count, never a statistical success probability.")

with tabs[1]:
    st.subheader(f"Historical walk-forward-style simulation · {selected}")
    st.caption("Each signal uses only bars available up to its signal timestamp. Entry occurs at the NEXT bar's OPEN. Targets and stops are set from that entry. Nonoverlapping decisions; stop has priority if both levels appear within a bar. This is a basic time-respecting backtest, not an independently validated ML model.")
    if len(frame) < MIN_BARS + horizon + 1:
        st.warning(f"Not enough observations: need at least {MIN_BARS + horizon + 1} bars.")
    else:
        trades, skipped = run_backtest(frame, mode, horizon, min_volume, stop_pct, reward_multiple,
                                       roundtrip_bps, source_id)
        stats = metrics(trades)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Evaluated signals", stats["evaluated"])
        c2.metric("Target-hit accuracy", f"{stats['hit_rate']:.1f}%" if stats["hit_rate"] is not None else "N/A")
        c3.metric("Profitable BUY trades", f"{stats['buy_win_rate']:.1f}%" if stats["buy_win_rate"] is not None else "N/A")
        c4.metric("Avg net BUY result", f"{stats['mean_net_return']:+.2f}%" if stats["mean_net_return"] is not None else "N/A")
        if skipped:
            st.warning(f"Skipped {skipped} signal(s) with missing next-bar OPEN data. Backtest does not invent fills.")
        if stats["evaluated"]:
            st.caption(f"Illustrative sequential BUY trade compounding: {stats['total_compounded']:+.2f}%. BUY-trade peak-to-trough drawdown: {stats['max_drawdown']:.2f}%. These ignore idle cash, portfolio allocations, market impact, corporate actions and live execution differences.")
            st.dataframe(trades, hide_index=True, use_container_width=True)
            st.download_button("⬇️ Export backtest results CSV", trades.to_csv(index=False).encode(),
                               file_name=f"backtest_{selected.lower()}.csv", mime="text/csv")
        else:
            st.info("No valid actionable signals or complete outcomes under the current rules. Try inspecting a different dataset, not weakening the rules solely to manufacture wins.")
        st.caption("SELL = predicted price decline/possible long-position exit, not a simulated short sale. Returns are shown only for theoretical BUY-to-SELL long positions. Net calculations subtract assumed round-trip bps; spread, slippage and taxes may require additional modelling.")

with tabs[2]:
    st.subheader("Forward prediction journal")
    st.write("Record current alerts in **Market scanner**. When newer observations become available, load the updated data and press evaluate. Old alerts cannot be rewritten; future bars resolve them.")
    if st.button("✅ Evaluate pending alerts against newer bars"):
        n = evaluate(conn, bars, source_id)
        st.success(f"Evaluated {n} newly resolved alert(s). Remaining pending alerts need more data.")
    historical = load(conn, source_id)
    report = summary(historical)
    cols = st.columns(4)
    cols[0].metric("Recorded", report["total"])
    cols[1].metric("Evaluated", report["resolved"])
    cols[2].metric("Target-hit accuracy", f"{report['accuracy']:.1f}%" if report["accuracy"] is not None else "N/A")
    cols[3].metric("Pending", report["pending"])
    if historical.empty:
        st.info("No alerts recorded for this data source yet.")
    else:
        breakdown = []
        for strategy_name in ("SWING", "DAY"):
            for direction_name in ("BUY", "SELL"):
                segment = historical[(historical["mode"] == strategy_name) &
                                     (historical["action"] == direction_name)]
                s = summary(segment)
                if s["total"]:
                    breakdown.append({"Mode": strategy_name, "Signal": direction_name,
                        "Evaluated":s["resolved"], "Wins":s["wins"],
                        "Target-hit accuracy (%)":round(s["accuracy"],1) if s["accuracy"] is not None else None,
                        "Pending": s["pending"]})
        if breakdown:
            st.dataframe(pd.DataFrame(breakdown), hide_index=True, use_container_width=True)
        st.dataframe(historical, hide_index=True, use_container_width=True)
        st.download_button("⬇️ Export journal", historical.to_csv(index=False).encode(),
                           file_name="prediction_ledger.csv", mime="text/csv")
        st.caption("Success: take-profit threshold reached first. Failure: stop first or horizon expiry. Pending alerts are excluded from the rate. Both levels reached in one bar => LOSS. The journal uses observed signal-close reference prices, not confirmed fills. A target hit does not imply profitable execution.")
        for k in ("SWING", "DAY"):
            m = summary(historical[historical["mode"] == k])
            if m["resolved"]:
                st.write(f"**{k}:** {m['wins']} of {m['resolved']} evaluated target hits ({m['accuracy']:.1f}%).")

with tabs[3]:
    st.subheader(f"Public financial headlines · {selected}")
    st.caption("RSS headline feed is an unverified news-discovery tool. Headlines can be stale, duplicated, unrelated or misleading; no headlines enter the historical backtest or numeric signal engine in v0.1.")
    if st.button("🗞️ Fetch recent headlines"):
        try:
            st.session_state["headlines"] = fetch_headlines(selected)
            st.session_state["headline_symbol"] = selected
            st.session_state.pop("ai_brief", None)
        except Exception as exc:
            st.error(str(exc))
    news = st.session_state.get("headlines")
    if news is not None and st.session_state.get("headline_symbol") == selected:
        if news.empty:
            st.info("No matching RSS headlines were returned.")
        else:
            st.dataframe(news, use_container_width=True, hide_index=True,
                         column_config={"url": st.column_config.LinkColumn("Read source")})
            st.caption("Positive/negative tags are keyword matching, not trained sentiment probabilities. Check original publications and official NGX disclosures.")
            ai_key = st.text_input("Optional OpenAI API key for cautious headline brief",
                                  type="password", value=os.getenv("OPENAI_API_KEY", ""))
            if st.button("✨ Generate AI research brief"):
                if not ai_key.strip():
                    st.warning("Enter an OpenAI API key first; the RSS and mechanical scanner need no AI key.")
                else:
                    try:
                        with st.spinner("Summarising unverified headlines…"):
                            st.session_state["ai_brief"] = ai_news_brief(
                                news, selected, ai_key, os.getenv("OPENAI_MODEL", "gpt-4.1-mini"))
                    except Exception as exc:
                        st.error(f"AI request failed: {exc}")
            if st.session_state.get("ai_brief"):
                st.markdown(st.session_state["ai_brief"])
                st.caption("Generated from RSS headlines only; NOT verified company financial information and NOT a trade signal.")
    else:
        st.info("Press 'Fetch recent headlines' to begin. Requires internet access.")

    st.divider()
    st.subheader("📑 NGX corporate disclosures")
    st.caption("Optional: discover original company filing PDF links via Investo's documented filings API. View actual filings before making any decision; this tool does not read or verify the PDF contents.")
    filing_key = st.text_input("Investo key for NGX disclosure lookup", type="password",
                               value=os.getenv("INVESTO_API_KEY", ""), key="filing_key")
    if st.button("Fetch official filing links"):
        try:
            st.session_state["filings"] = fetch_filings(selected, filing_key)
            st.session_state["filing_symbol"] = selected
        except Exception as exc:
            st.error(str(exc))
    filings = st.session_state.get("filings")
    if filings is not None and st.session_state.get("filing_symbol") == selected:
        if filings.empty:
            st.info("No filings were returned for this ticker.")
        else:
            st.dataframe(filings, hide_index=True, use_container_width=True,
                column_config={"url":st.column_config.LinkColumn("Official PDF")})
            st.caption("Disclosures via Investo — investo.ng. Original documents are hosted by their publishers, often the NGX document library.")

with tabs[4]:
    st.subheader("Imported observations and methodology")
    st.dataframe(frame.tail(40), use_container_width=True, hide_index=True)
    st.download_button("⬇️ Download selected observations", frame.to_csv(index=False).encode(),
                       file_name=f"bars_{selected.lower()}.csv", mime="text/csv")
    st.markdown("""
    **How this build should be used**

    - **Synthetic demo**: fictional data for testing the UI and algorithms; do not trade from it.
    - **CSV**: import legally obtained daily OHLCV data, or genuine timestamped intraday data for DAY mode.
    - **Investo API**: documented `/api/v1/prices/{symbol}` and `/api/v1/filings/{symbol}` endpoints; key and internet required, EOD only, raw responses remain in session memory.
    - **Signal accuracy**: ratio of target-hit alerts to all resolved alerts; not a predictor's confidence, a trading win rate, or a promise of profitability.
    - **Costs**: hypothetical percentage charged per round trip. Supply your actual broker rates. No spread, slippage, dividends or splits adjustment is performed.
    - **No look-ahead**: historical indicators are calculated only on previous/current bars; backtest enters on the next bar open. RSS is not backfilled as a historical feature.
    - **Bar ambiguity**: when target and stop appear in one bar, stop takes precedence. Missing high/low triggers conservative close-only level checks for that bar.
    - **Not production-ready**: no authenticated brokerage execution, automated scheduling, market-hours validation, live data, compliance checks or monitored risk controls.

    **Provider terms:** Investo — https://investo.ng/api-terms · NGX — https://ngxgroup.com/exchange/data/
    """)

conn.close()
