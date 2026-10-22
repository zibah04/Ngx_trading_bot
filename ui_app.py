import asyncio
import os
import threading
from concurrent.futures import Future
from typing import Any

import streamlit as st

from bot_engine import NGXQuantTradingEngine
from config import DEFAULT_CONFIG_DICT, load_config
from database import TradingDatabase
from mock_broker import MockBroker


st.set_page_config(page_title="NGX Bot Dashboard", page_icon="🇳🇬", layout="wide")


@st.cache_resource
def build_runtime() -> dict[str, Any]:
    config = load_config(DEFAULT_CONFIG_DICT)
    config.safety.database_path = os.getenv("NGX_DATABASE_PATH", "data/ngx_dashboard.db")
    engine = NGXQuantTradingEngine(
        config=config,
        broker=MockBroker(initial_cash_naira=2_000_000.0),
        database=TradingDatabase(config.safety.database_path),
    )

    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run_loop() -> None:
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()

    thread = threading.Thread(target=run_loop, name="ngx-bot-event-loop", daemon=True)
    thread.start()
    if not ready.wait(timeout=5):
        raise RuntimeError("Background event loop failed to start.")

    return {"engine": engine, "loop": loop, "thread": thread, "start_future": None, "error": None}


runtime = build_runtime()


@st.fragment(run_every="2s")
def render_dashboard() -> None:
    engine: NGXQuantTradingEngine = runtime["engine"]
    loop: asyncio.AbstractEventLoop = runtime["loop"]
    start_future: Future[Any] | None = runtime["start_future"]

    if start_future is not None and start_future.done():
        try:
            start_future.result()
        except Exception as exc:
            runtime["error"] = str(exc)
        runtime["start_future"] = None
        start_future = None

    running = start_future is not None
    try:
        cash_balance = asyncio.run_coroutine_threadsafe(
            engine.broker.get_cash_balance(), loop
        ).result(timeout=5)
    except Exception as exc:
        cash_balance = 0.0
        runtime["error"] = f"Balance check failed: {exc}"

    st.title("NGX Trading Bot Dashboard")
    col1, col2, col3 = st.columns(3)
    col1.metric("Broker", "MockBroker (simulation)")
    col2.metric("Cash", f"₦{cash_balance:,.2f}")
    col3.metric("Status", "Running" if running else "Stopped")

    if runtime["error"]:
        st.error(runtime["error"])

    start_col, stop_col = st.columns(2)
    if start_col.button("Start simulation", disabled=running, use_container_width=True):
        runtime["error"] = None
        runtime["start_future"] = asyncio.run_coroutine_threadsafe(engine.start(), loop)
        st.rerun()

    if stop_col.button("Stop simulation", disabled=not running, use_container_width=True):
        asyncio.run_coroutine_threadsafe(engine.stop(), loop)
        st.rerun()

    st.subheader("Watchlist")
    for symbol, strategy in engine.config.watchlists.items():
        st.write(
            f"{symbol}: {strategy.n_cycle_count} cycles, "
            f"{strategy.x_buy_discount_pct}% buy discount, "
            f"{strategy.y_profit_target_pct}% target"
        )


render_dashboard()