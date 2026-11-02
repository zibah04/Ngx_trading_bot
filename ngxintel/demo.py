"""Reproducible SYNTHETIC samples. Never represent them as real NGX observations."""
import numpy as np
import pandas as pd


def generate_demo():
    dates = pd.bdate_range(end="2026-10-30", periods=250)
    frames = []
    for seed, symbol, trend in [(17, "DEMO_ALPHA", 0.001), (23, "DEMO_BETA", -0.0005),
                                (51, "DEMO_GAMMA", 0.0002)]:
        rng = np.random.default_rng(seed)
        ret = rng.normal(trend, 0.024, len(dates))
        close = 50 * np.exp(np.cumsum(ret))
        open_ = np.r_[50., close[:-1]] * (1 + rng.normal(0, .007, len(dates)))
        hi = np.maximum(open_, close) * (1 + rng.uniform(.001, .023, len(dates)))
        lo = np.minimum(open_, close) * (1 - rng.uniform(.001, .023, len(dates)))
        vol = rng.integers(70000, 2_000_000, len(dates))
        frames.append(pd.DataFrame(dict(timestamp=dates, symbol=symbol, open=open_,
            high=hi, low=lo, close=close, volume=vol)))
    return pd.concat(frames, ignore_index=True)
