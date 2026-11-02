"""Append-once prediction journal, with outcome updates only after new bars arrive."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import pandas as pd
from .signals import Signal
from .evaluation import outcome

DEFAULT_DB = Path(__file__).resolve().parents[1] / "storage" / "predictions.sqlite"


def connection(db=DEFAULT_DB):
    path = Path(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL, mode TEXT NOT NULL, signal_time TEXT NOT NULL,
        action TEXT NOT NULL, reference_price REAL NOT NULL,
        target REAL NOT NULL, stop REAL NOT NULL, horizon INTEGER NOT NULL,
        strength INTEGER NOT NULL, strength_max INTEGER NOT NULL,
        reason TEXT NOT NULL, source TEXT NOT NULL, version TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING', exit_price REAL,
        exit_time TEXT, eval_method TEXT,
        UNIQUE(symbol, mode, signal_time, source, version)
    )""")
    conn.commit()
    return conn


def record(conn, signal: Signal, horizon: int) -> bool:
    if signal.action not in ("BUY", "SELL"):
        return False
    with conn:
        cursor = conn.execute("""INSERT OR IGNORE INTO predictions (
          symbol, mode, signal_time, action, reference_price, target, stop,
          horizon, strength, strength_max, reason, source, version, recorded_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
          (signal.symbol, signal.mode, signal.signal_time, signal.action,
           signal.reference_price, signal.target, signal.stop, horizon,
           signal.strength, signal.strength_max, signal.reason, signal.source,
           signal.version, datetime.now(timezone.utc).isoformat()))
    return cursor.rowcount > 0


def evaluate(conn, all_bars: pd.DataFrame, source: str) -> int:
    """Only bars timestamped strictly AFTER the alert can resolve it.
    Important: this tracks close-based alert levels; it is NOT proof of fills.
    """
    rows = conn.execute("SELECT * FROM predictions WHERE status='PENDING' AND source=?", (source,)).fetchall()
    changes = 0
    for alert in rows:
        series = all_bars[all_bars.symbol == alert["symbol"]]
        if series.empty:
            continue
        signal_time = pd.Timestamp(alert["signal_time"])
        future_all = series[series.timestamp > signal_time]
        if alert["mode"] == "DAY":
            session_date = signal_time.date()
            future = future_all[future_all.timestamp.dt.date == session_date]
            next_session_seen = bool((future_all.timestamp.dt.date > session_date).any())
            # An earlier alert is not considered finished until either a level
            # hits or the session definitively ends (new session observed).
            effective_horizon = (min(alert["horizon"], len(future))
                                 if next_session_seen and len(future) else alert["horizon"])
        else:
            future = future_all
            next_session_seen = False
            effective_horizon = alert["horizon"]
        if alert["mode"] == "DAY" and next_session_seen and future.empty:
            # No post-alert bar in that trading session: no observed opportunity.
            status, exit_price, exit_time, method = ("EXPIRED", alert["reference_price"],
                alert["signal_time"], "no subsequent same-session bars")
        else:
            status, exit_price, exit_time, method, _ = outcome(
                alert["action"], alert["reference_price"], alert["target"],
                alert["stop"], future, effective_horizon)
        if status == "PENDING":
            continue
        with conn:
            conn.execute("""UPDATE predictions SET status=?, exit_price=?, exit_time=?,
                           eval_method=? WHERE id=? AND status='PENDING'""",
                         (status, exit_price, exit_time, method, alert["id"]))
        changes += 1
    return changes


def load(conn, source=None) -> pd.DataFrame:
    if source:
        rows = conn.execute("SELECT * FROM predictions WHERE source=? ORDER BY recorded_at DESC, id DESC", (source,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM predictions ORDER BY recorded_at DESC, id DESC").fetchall()
    return pd.DataFrame([dict(row) for row in rows])


def summary(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"total":0, "resolved":0, "wins":0, "accuracy":None, "pending":0}
    resolved = df[df.status != "PENDING"]
    wins = int((resolved.status == "WIN").sum())
    return dict(total=len(df), resolved=len(resolved), wins=wins,
        accuracy=(100 * wins / len(resolved) if len(resolved) else None),
        pending=int((df.status == "PENDING").sum()))
