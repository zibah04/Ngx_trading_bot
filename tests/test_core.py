import numpy as np
import pandas as pd
import pytest
from ngxintel.data import normalize, DataError
from ngxintel.demo import generate_demo
from ngxintel.signals import calculate_signal, indicators
from ngxintel.evaluation import outcome
from ngxintel.backtest import run_backtest, metrics
from ngxintel.ledger import connection, record, evaluate, load, summary


def short_prices(count=5):
    return pd.DataFrame({"timestamp":pd.bdate_range("2026-01-01",periods=count),
                         "symbol":"FAKE", "open":100., "high":102.,
                         "low":98., "close":100., "volume":50000})


def test_normalize_close_only_keeps_missing_range():
    data = normalize(pd.DataFrame({"Date":["2026-01-01", "2026-01-02"], "Close":[20,21]}))
    assert len(data)==2 and data.high.isna().all() and data.open.isna().all()


def test_normalize_deduplicates_and_sorts():
    data = normalize(pd.DataFrame({"date":["2026-01-02", "2026-01-01", "2026-01-01"],
        "close":[22,20,21], "symbol":["FOO","FOO","FOO"]}))
    assert data.close.to_list() == [21,22]


def test_normalize_required():
    with pytest.raises(DataError):
        normalize(pd.DataFrame({"x":[1]}))


def test_signal_insufficient_and_liquidity():
    d = short_prices()
    assert calculate_signal(d).action == "WAIT"
    df = generate_demo().query("symbol=='DEMO_ALPHA'").copy()
    df["volume"] = 0
    assert calculate_signal(df).action == "WAIT"


def test_signal_trending_bull():
    dates = pd.bdate_range('2026-01-01', periods=90)
    close = np.linspace(25,85,len(dates))
    df = pd.DataFrame(dict(timestamp=dates, symbol="FAKE", close=close,
                 open=close*0.999, high=close*1.01,low=close*0.99,volume=100000))
    s = calculate_signal(df)
    # Continuous gains drive RSI to 100 and prudently fail overbought gate.
    assert s.action == 'WAIT'
    assert indicators(df).rsi14.iloc[-1] == 100
    assert s.reference_price == 85
    assert s.strength_max == 4


def test_outcome_buy_stop_priority():
    future=short_prices(1)
    assert outcome("BUY",100,101,99,future,1)[0]=="LOSS"


def test_outcome_buy_win_and_sell_win():
    future=short_prices(1)
    assert outcome("BUY",100,102,95,future,1)[0]=="WIN"
    assert outcome("SELL",100,98,105,future,1)[0]=="WIN"


def test_outcome_pending_expired_and_close_only():
    future=short_prices(2)
    future[["high","low"]] = float("nan")
    assert outcome('BUY',100,105,96,future,3)[0]=='PENDING'
    result = outcome('BUY',100,105,96,future,2)
    assert result[0] == 'EXPIRED' and 'CLOSE-ONLY' in result[3]


def test_backtest_runs_without_future_lookahead():
    df = generate_demo().query("symbol=='DEMO_ALPHA'").copy()
    trades, skips = run_backtest(df, horizon=5)
    assert skips==0
    if not trades.empty:
        assert (pd.to_datetime(trades.entry_time)>pd.to_datetime(trades.signal_time)).all()
        assert trades.status.isin(['WIN','LOSS','EXPIRED']).all()
        assert trades.query("action == 'SELL'").net_long_return_pct.isna().all()
        m=metrics(trades)
        assert 0<=m['hit_rate']<=100


def test_no_fake_entry_when_open_missing():
    df = generate_demo().query("symbol=='DEMO_ALPHA'").copy()
    df['open'] = float('nan')
    trades, skipped = run_backtest(df)
    assert trades.empty


def test_ledger_immutability_future_only(tmp_path):
    df = generate_demo().query("symbol=='DEMO_ALPHA'").copy().iloc[:75]
    s = calculate_signal(df)
    if s.action == 'WAIT':
        # A valid BUY record to explicitly exercise the ledger evaluation semantics.
        from ngxintel.signals import Signal
        s = Signal('DEMO_ALPHA', pd.Timestamp(df.timestamp.iloc[-1]).isoformat(),
                 'SWING','BUY',float(df.close.iloc[-1]),float(df.close.iloc[-1])*1.01,
                 float(df.close.iloc[-1])*0.99,4,4,'test', 'CSV_USER')
    else:
        from dataclasses import replace
        s = replace(s, source='CSV_USER')
    c=connection(tmp_path/'test.sqlite')
    assert record(c,s,5)
    assert not record(c,s,5)
    assert evaluate(c, df, 'CSV_USER')==0
    assert summary(load(c))['pending']==1
    future=df.iloc[[-1]].copy()
    future['timestamp'] = pd.Timestamp(df.timestamp.iloc[-1])+pd.Timedelta(days=1)
    if s.action=='BUY':
        future['high']=s.target*1.01
        future['low']=s.reference_price
    else:
        future['high']=s.reference_price
        future['low']=s.target*.99
    combined=pd.concat([df,future],ignore_index=True)
    assert evaluate(c, combined, 'CSV_USER')==1
    assert summary(load(c))['accuracy']==100
    assert evaluate(c, combined, 'CSV_USER')==0
    c.close()


def test_day_backtest_never_overnight():
    dates = list(pd.date_range('2026-01-01 10:00', periods=50, freq='5min')) + list(pd.date_range('2026-01-02 10:00', periods=50, freq='5min'))
    closes = np.linspace(50,150,len(dates))
    x = pd.DataFrame({'timestamp':dates,'symbol':'FAKE', 'open':closes,
                      'high':closes*1.01,'low':closes*.99,'close':closes,'volume':50000})
    trades,_ = run_backtest(x,mode='DAY',horizon=6)
    if len(trades):
        assert all(pd.Timestamp(a).date() == pd.Timestamp(b).date()
                   for a,b in zip(trades.signal_time,trades.exit_time))
        assert all(pd.Timestamp(a).date() == pd.Timestamp(b).date()
                   for a,b in zip(trades.signal_time,trades.entry_time))


def test_day_ledger_session_expiry(tmp_path):
    from ngxintel.signals import Signal
    signal=Signal('X','2026-01-05T15:55:00','DAY','BUY',100,105,98,4,4,'t','CSV_USER')
    c=connection(tmp_path/'a.sqlite');record(c,signal,8)
    older=normalize(pd.DataFrame({'timestamp':['2026-01-05 15:55:00'], 'close':[100],'symbol':['X']}))
    assert evaluate(c,older,'CSV_USER')==0
    newer=normalize(pd.DataFrame({'timestamp':['2026-01-05 15:55:00','2026-01-06 09:00:00'],
        'close':[100,101], 'symbol':['X','X']}))
    assert evaluate(c,newer,'CSV_USER')==1
    assert load(c).iloc[0].status == 'EXPIRED'
    c.close()


def test_filings_request_requires_key():
    from ngxintel.news import fetch_filings
    with pytest.raises(ValueError):
        fetch_filings('GTCO', '')
