"""Load, validate, and normalize bars. Provider quotes stay in memory."""
from __future__ import annotations
from datetime import date, timedelta
from io import BytesIO
import pandas as pd
import requests

BASE = "https://investo.ng"

class DataError(ValueError):
    pass


def normalize(raw: pd.DataFrame, default_symbol: str = "UNKNOWN") -> pd.DataFrame:
    if raw.empty:
        raise DataError("No price rows were supplied.")
    df = raw.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    renames = {"date": "timestamp", "datetime": "timestamp", "time": "timestamp",
               "ticker": "symbol", "adj_close": "close", "traded_volume": "volume"}
    df = df.rename(columns={k: v for k, v in renames.items() if k in df and v not in df})
    if "timestamp" not in df or "close" not in df:
        raise DataError("Required columns: date (or timestamp), close; optional: symbol, open, high, low, volume.")
    if "symbol" not in df:
        df["symbol"] = default_symbol
    for col in ("open", "high", "low", "volume"):
        if col not in df:
            df[col] = float("nan")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True).dt.tz_localize(None)
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["timestamp", "close"])
    df = df[(df.close > 0) & (df.symbol != "") & (df.symbol != "NAN")]
    for c in ("open", "high", "low"):
        df.loc[df[c].notna() & (df[c] <= 0), c] = float("nan")
    df.loc[df.volume < 0, "volume"] = float("nan")
    invalid_range = df.high.notna() & df.low.notna() & (df.high < df.low)
    df = df.loc[~invalid_range]
    # Inconsistent highs/lows are missing data, not permission to manufacture a range.
    for price_col in ("open", "close"):
        df.loc[df.high.notna() & (df[price_col] > df.high), "high"] = float("nan")
        df.loc[df.low.notna() & (df[price_col] < df.low), "low"] = float("nan")
    df = df.drop_duplicates(["symbol", "timestamp"], keep="last").sort_values(["symbol", "timestamp"])
    if df.empty:
        raise DataError("No usable price rows remained after validation.")
    return df[["timestamp", "symbol", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def csv_to_bars(file) -> pd.DataFrame:
    return normalize(pd.read_csv(file))


def fetch_investo(symbols: list[str], key: str, days: int = 365) -> pd.DataFrame:
    """Investo documented endpoint. No persistent bulk price cache is created."""
    if not key.strip():
        raise DataError("An Investo developer API key is required.")
    start = (date.today() - timedelta(days=days)).isoformat()
    stop = date.today().isoformat()
    outputs = []
    session = requests.Session()
    for symbol in symbols:
        symbol = symbol.strip().upper()
        if not symbol or not symbol.replace("-", "").isalnum():
            raise DataError(f"Invalid symbol: {symbol!r}")
        try:
            response = session.get(f"{BASE}/api/v1/prices/{symbol}",
                headers={"Authorization": f"Bearer {key.strip()}", "Accept": "application/json"},
                params={"from": start, "to": stop}, timeout=25)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise DataError(f"Cannot retrieve {symbol}: {exc}") from exc
        if body.get("ok") is not True:
            err = body.get("error", {})
            raise DataError(f"{symbol}: {err.get('message', 'API returned an error')}")
        rows = body.get("data")
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or not rows:
            continue
        frame = pd.DataFrame(rows)
        frame["symbol"] = symbol
        outputs.append(normalize(frame, default_symbol=symbol))
    if not outputs:
        raise DataError("No usable historical bars returned for these symbols.")
    return normalize(pd.concat(outputs, ignore_index=True))
