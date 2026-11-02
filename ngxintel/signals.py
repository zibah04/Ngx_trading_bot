"""Transparent, deterministic research signals; NO calibrated probabilities."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import pandas as pd
import numpy as np

VERSION = "sma-rsi-mom-v1"
MIN_BARS = 35

@dataclass(frozen=True)
class Signal:
    symbol: str
    signal_time: str
    mode: str
    action: str
    reference_price: float
    target: float | None
    stop: float | None
    strength: int
    strength_max: int
    reason: str
    source: str
    version: str = VERSION

    def to_dict(self):
        return asdict(self)


def indicators(bars: pd.DataFrame) -> pd.DataFrame:
    x = bars.sort_values("timestamp").copy().reset_index(drop=True)
    c = x.close
    x["sma10"] = c.rolling(10, min_periods=10).mean()
    x["sma25"] = c.rolling(25, min_periods=25).mean()
    delta = c.diff()
    ups = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    downs = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = ups / downs.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    # Standard RSI edge cases: no losses => 100, no gains => 0,
    # perfectly flat market => neutral 50. Values are only used after warm-up.
    rsi = rsi.mask((downs == 0) & (ups > 0), 100)
    rsi = rsi.mask((ups == 0) & (downs > 0), 0)
    x["rsi14"] = rsi.fillna(50)
    x["momentum5"] = c.pct_change(5)
    x["vol20"] = x.volume.rolling(20, min_periods=20).mean()
    return x


def calculate_signal(bars: pd.DataFrame, mode="SWING", source="CSV", min_volume=20000,
                     stop_pct=0.03, reward_multiple=2.0) -> Signal:
    if len(bars) == 0:
        raise ValueError("No bars for symbol")
    x = indicators(bars)
    now = x.iloc[-1]
    symbol = str(now.symbol)
    price = float(now.close)
    timestamp = pd.Timestamp(now.timestamp).isoformat()
    if len(x) < MIN_BARS:
        return Signal(symbol, timestamp, mode, "WAIT", price, None, None, 0, 4,
                      f"Need at least {MIN_BARS} price bars (have {len(x)}).", source)
    if pd.isna(now.vol20) or now.vol20 < min_volume:
        return Signal(symbol, timestamp, mode, "WAIT", price, None, None, 0, 4,
                      "Insufficient or unknown 20-bar average volume; liquidity gate failed.", source)
    bull = [now.sma10 > now.sma25, now.momentum5 > 0, 42 <= now.rsi14 <= 75,
            now.close > now.sma10]
    bear = [now.sma10 < now.sma25, now.momentum5 < 0, 25 <= now.rsi14 <= 58,
            now.close < now.sma10]
    b, s = sum(bool(v) for v in bull), sum(bool(v) for v in bear)
    if b == 4:
        action = "BUY"
    elif s == 4:
        action = "SELL"
    else:
        action = "WAIT"
    strength = max(b, s)
    reason = (f"SMA10 ₦{now.sma10:.2f}, SMA25 ₦{now.sma25:.2f}; "
              f"RSI14 {now.rsi14:.1f}; 5-bar momentum {now.momentum5:+.1%}; "
              f"20-bar avg. volume {now.vol20:,.0f}. {strength}/4 aligned factors. "
              "SELL is a bearish/exit research signal, not a short-sale order.")
    if action == "WAIT":
        return Signal(symbol, timestamp, mode, action, price, None, None, strength, 4, reason, source)
    direction = 1 if action == "BUY" else -1
    stop = round(price * (1 - direction * stop_pct), 4)
    target = round(price * (1 + direction * stop_pct * reward_multiple), 4)
    return Signal(symbol, timestamp, mode, action, price, target, stop, strength, 4, reason, source)
