"""Conservative target-first evaluation of future bars only."""
from __future__ import annotations
import math
import pandas as pd


def outcome(action: str, entry: float, target: float, stop: float, future: pd.DataFrame,
            horizon: int):
    """Return (status, exit_price, exit_time, method, bars_examined).

    WIN means target touched before stop; LOSS means stop touched before target;
    EXPIRED means horizon ended without target; PENDING means insufficient future bars.
    Intrabar ambiguity is resolved against the strategy (stop first).
    Missing high/low means CLOSE-ONLY evaluation for that bar, never invented OHLC.
    Close-only evaluation may understate BOTH target and stop touches.
    """
    if action not in ("BUY", "SELL"):
        raise ValueError("Only BUY/SELL can be evaluated")
    if horizon < 1 or entry <= 0:
        raise ValueError("Invalid horizon or entry")
    future = future.sort_values("timestamp").head(horizon)
    close_only = False
    for _, bar in future.iterrows():
        high, low = bar.high, bar.low
        if pd.isna(high) or pd.isna(low):
            high = low = float(bar.close)
            close_only = True
        high, low = float(high), float(low)
        if action == "BUY":
            hit_stop, hit_target = low <= stop, high >= target
        else:
            hit_stop, hit_target = high >= stop, low <= target
        moment = pd.Timestamp(bar.timestamp).isoformat()
        method = "CLOSE-ONLY (at least one bar)" if close_only else "OHLC, stop-first"
        if hit_stop:  # same-bar ambiguity always counts against the strategy
            return ("LOSS", float(stop), moment, method, len(future))
        if hit_target:
            return ("WIN", float(target), moment, method, len(future))
    if len(future) >= horizon:
        last = future.iloc[-1]
        method = "CLOSE-ONLY (at least one bar)" if close_only else "OHLC, stop-first"
        return ("EXPIRED", float(last.close), pd.Timestamp(last.timestamp).isoformat(), method, horizon)
    return ("PENDING", None, None, "insufficient subsequent bars", len(future))
