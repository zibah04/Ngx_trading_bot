"""Out-of-sample in time (not independent training): mechanical paper backtest.
Signals are computed at bar close; BUY fills at next bar open only.
SELL signals are bearish research evaluations, NEVER simulated short trades.
"""
import pandas as pd
from .signals import calculate_signal, MIN_BARS
from .evaluation import outcome


def run_backtest(df: pd.DataFrame, mode="SWING", horizon=5, min_volume=20000,
                 stop_pct=0.03, reward_multiple=2.0, roundtrip_bps=100,
                 source="CSV"):
    rows = []
    skipped_missing_open = 0
    data = df.sort_values("timestamp").reset_index(drop=True)
    if horizon < 1:
        raise ValueError("horizon must be positive")
    # Non-overlapping signals; avoid overlapping hypothetical trade exposures.
    i = MIN_BARS - 1
    while i < len(data) - 1:
        signal = calculate_signal(data.iloc[:i+1], mode, source, min_volume, stop_pct, reward_multiple)
        if signal.action == "WAIT":
            i += 1
            continue
        nxt = data.iloc[i+1]
        if pd.isna(nxt.open) or float(nxt.open) <= 0:
            skipped_missing_open += 1
            i += 1
            continue
        entry = float(nxt.open)
        direction = 1 if signal.action == "BUY" else -1
        target = entry * (1 + direction * stop_pct * reward_multiple)
        stop = entry * (1 - direction * stop_pct)
        if mode == "DAY":
            # The signal and hypothetical entry must belong to the same session.
            # Never silently carry a day trade into a subsequent day.
            if pd.Timestamp(data.iloc[i].timestamp).date() != pd.Timestamp(nxt.timestamp).date():
                i += 1
                continue
            session_date = pd.Timestamp(nxt.timestamp).date()
            remaining = data.iloc[i+1:]
            future = remaining[remaining.timestamp.dt.date == session_date].head(horizon)
            if len(future) < horizon:
                i += 1  # not enough same-session bars: no evaluated trade
                continue
        else:
            future = data.iloc[i+1:i+1+horizon]
        status, exit_price, exit_time, method, bars_examined = outcome(
            signal.action, entry, target, stop, future, horizon)
        if status == "PENDING":
            break  # incomplete trades must never be marked successful
        # Theoretical long-side result only. SELL is a bearish signal, not a short sale.
        net_return = None
        if signal.action == "BUY":
            net_return = 100 * (exit_price / entry - 1) - roundtrip_bps / 100
        rows.append(dict(symbol=signal.symbol, signal_time=signal.signal_time,
            action=signal.action, entry_time=pd.Timestamp(nxt.timestamp).isoformat(),
            entry=round(entry, 4), target=round(target, 4), stop=round(stop, 4),
            status=status, exit_time=exit_time, exit_price=round(exit_price, 4),
            net_long_return_pct=round(net_return, 3) if net_return is not None else None,
            evaluation=method, reason=signal.reason))
        # Skip all bars consumed by this event: no overlapping recommendations.
        last_seen_idx = min(i + bars_examined, len(data) - 1)
        if exit_time:
            matches = data.index[data.timestamp == pd.Timestamp(exit_time)]
            if len(matches):
                last_seen_idx = int(matches[0])
        i = max(i + 1, last_seen_idx + 1)
    return pd.DataFrame(rows), skipped_missing_open


def metrics(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return dict(evaluated=0, hits=0, hit_rate=None, buys=0, profitable_buys=0,
                    buy_win_rate=None, mean_net_return=None, total_compounded=None, max_drawdown=None)
    hits = int((trades.status == "WIN").sum())
    longs = trades[trades.action == "BUY"].copy()
    long_returns = pd.to_numeric(longs.net_long_return_pct, errors="coerce").dropna()
    count = len(long_returns)
    # Approximation: all profitable simulated BUY trades compounded sequentially,
    # no idle cash/mark-to-market and no portfolio allocation model.
    equity = (1 + long_returns / 100).cumprod()
    max_dd = ((equity / pd.concat([pd.Series([1.0]), equity]).cummax().iloc[1:].values) - 1).min() * 100 if count else None
    return dict(evaluated=len(trades), hits=hits, hit_rate=100 * hits / len(trades),
        buys=count, profitable_buys=int((long_returns > 0).sum()),
        buy_win_rate=100 * (long_returns > 0).mean() if count else None,
        mean_net_return=float(long_returns.mean()) if count else None,
        total_compounded=float((equity.iloc[-1] - 1)*100) if count else None,
        max_drawdown=float(max_dd) if count else None)
