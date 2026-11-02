"""Offline checks for financial-data, forecast, and integration boundaries."""

import pandas as pd
import pytest

from ngxintel.data import DataError, fetch_investo, normalize
from ngxintel.evaluation import outcome
from ngxintel.ledger import connection, evaluate, load, record, summary
from ngxintel.signals import Signal
from ngxintel.backtest import metrics


def row(ts, opening=100, high=102, low=98, close=100):
    return pd.DataFrame([{"timestamp": pd.Timestamp(ts), "symbol": "FAKE", "open": opening,
                          "high": high, "low": low, "close": close, "volume": 100000}])


def fake_signal(ts, action="BUY", mode="SWING"):
    return Signal("FAKE", ts, mode, action, 100.0,
                  105.0 if action == "BUY" else 95.0,
                  97.0 if action == "BUY" else 103.0,
                  4, 4, "fixture", "TEST_SOURCE")


def test_both_levels_same_bar_count_loss_in_both_directions():
    bar = row("2026-10-01", high=106, low=94)
    assert outcome("BUY", 100, 105, 97, bar, 1)[0] == "LOSS"
    assert outcome("SELL", 100, 95, 103, bar, 1)[0] == "LOSS"


def test_outcome_without_future_bars_remains_pending():
    bar = row("2026-10-01").iloc[:0]
    assert outcome("BUY", 100, 105, 97, bar, 3)[0] == "PENDING"


def test_outcome_invalid_parameters():
    with pytest.raises(ValueError):
        outcome("WAIT", 100, 105, 97, row("2026-10-01"), 1)
    with pytest.raises(ValueError):
        outcome("BUY", 100, 105, 97, row("2026-10-01"), 0)


def test_future_only_ignores_same_time_price_spike(tmp_path):
    c = connection(tmp_path / "predictions.sqlite")
    prediction = fake_signal("2026-10-01T16:00:00")
    assert record(c, prediction, 2)
    same_time = row("2026-10-01T16:00:00", high=200, low=50)
    assert evaluate(c, same_time, "TEST_SOURCE") == 0
    assert load(c).iloc[0].status == "PENDING"
    later = row("2026-10-02T16:00:00", high=106, low=99)
    assert evaluate(c, pd.concat([same_time, later]), "TEST_SOURCE") == 1
    assert summary(load(c))["accuracy"] == 100
    c.close()


def test_journal_pending_is_excluded_from_accuracy(tmp_path):
    c = connection(tmp_path / "predictions.sqlite")
    assert record(c, fake_signal("2026-10-01"), 3)
    totals = summary(load(c))
    assert totals["total"] == 1
    assert totals["resolved"] == 0
    assert totals["accuracy"] is None
    c.close()


def test_normalize_rejects_reversed_high_low():
    with pytest.raises(DataError):
        normalize(pd.DataFrame({"date": ["2026-10-01"], "close": [100],
                                "high": [90], "low": [110]}))


def test_fetch_investo_requires_key_and_rejects_invalid_symbol():
    with pytest.raises(DataError):
        fetch_investo(["GTCO"], "")
    with pytest.raises(DataError):
        fetch_investo(["../../BAD"], "fake-key")


def test_fetch_investo_mocked_success_without_network(monkeypatch):
    from ngxintel import data
    called = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "data": [
                {"date": "2026-10-01", "close": 100, "open": 98,
                 "high": 101, "low": 97, "volume": 100000},
                {"date": "2026-10-02", "close": 102, "open": 100,
                 "high": 103, "low": 99, "volume": 120000},
            ]}

    class FakeSession:
        def get(self, url, **kwargs):
            called.append((url, kwargs))
            return FakeResponse()

    monkeypatch.setattr(data.requests, "Session", FakeSession)
    result = fetch_investo(["GTCO"], "dummy", 30)
    assert result.symbol.tolist() == ["GTCO", "GTCO"]
    assert result.close.tolist() == [100, 102]
    assert called[0][0].endswith("/prices/GTCO")
    assert called[0][1]["headers"]["Authorization"] == "Bearer dummy"


def test_profitability_is_not_the_same_as_hit_rate():
    trades = pd.DataFrame([
        {"action": "BUY", "status": "WIN", "net_long_return_pct": -0.25},
        {"action": "BUY", "status": "LOSS", "net_long_return_pct": -3.00},
    ])
    result = metrics(trades)
    assert result["hit_rate"] == 50
    assert result["buy_win_rate"] == 0
    assert result["mean_net_return"] < 0
