import atexit
import os

import streamlit as st

from simulation_runtime import SimulationRuntime

st.set_page_config(page_title="NGX Bot Dashboard", page_icon="🇳🇬", layout="wide")


@st.cache_resource
def build_runtime() -> SimulationRuntime:
    runtime = SimulationRuntime(os.getenv("NGX_DATABASE_PATH", "data/ngx_dashboard.db"))
    atexit.register(runtime.close)
    return runtime


runtime = build_runtime()


@st.fragment(run_every="2s")
def render_dashboard() -> None:
    state = runtime.call('snapshot')
    st.title("NGX Trading Bot Dashboard")
    st.caption("Shared private simulation. All signed-in viewers control the same mock account.")
    col1, col2, col3 = st.columns(3)
    col1.metric("Broker", "MockBroker (simulation)")
    col2.metric("Cash", f"₦{state['cash']:,.2f}")
    col3.metric("Status", state['status'])
    if state['error']:
        st.error(state['error'])
    start_col, stop_col, new_col = st.columns(3)
    if start_col.button("Start simulation", disabled=state['busy'] or state['status'] in ('Blocked', 'Error'), use_container_width=True):
        runtime.call('start')
        st.rerun()
    if stop_col.button("Stop simulation", disabled=not state['busy'] or state['status'] == 'Stopping', use_container_width=True):
        runtime.call('stop')
        st.rerun()
    if new_col.button("New simulation", disabled=state['busy'], use_container_width=True):
        runtime.call('new')
        st.rerun()
    st.caption("New simulation creates a fresh mock account and keeps the previous run's records.")
    st.subheader("Watchlist")
    for symbol, strategy in state['watchlists'].items():
        st.write(f"{symbol}: {strategy.n_cycle_count} cycles, "
                 f"{strategy.x_buy_discount_pct}% buy discount, "
                 f"{strategy.y_profit_target_pct}% target")


render_dashboard()
