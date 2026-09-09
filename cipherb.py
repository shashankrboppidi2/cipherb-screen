import pandas as pd, numpy as np, yfinance as yf

def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def wavetrend(df, chlen=9, avg=12, malen=3):
    src = (df.High + df.Low + df.Close) / 3
    esa = ema(src, chlen)
    de = ema((src - esa).abs(), chlen)
    ci = (src - esa) / (0.015 * de)
    wt1 = ema(ci, avg)
    wt2 = wt1.rolling(malen).mean()
    return wt1, wt2

def rsimfi(df, period=60, mult=150, posy=2.5):
    rng = (df.High - df.Low).replace(0, np.nan)
    return (((df.Close - df.Open) / rng) * mult).rolling(period).mean() - posy

def signals(df, os_level=-53, ob_level=53):
    wt1, wt2 = wavetrend(df)
    diff = wt1 - wt2
    cross = (np.sign(diff) != np.sign(diff.shift(1))) & diff.shift(1).notna()
    buy = cross & (diff >= 0) & (wt2 <= os_level)
    sell = cross & (diff <= 0) & (wt2 >= ob_level)
    out = df.copy()
    out['wt1'], out['wt2'], out['buy'], out['sell'] = wt1, wt2, buy, sell
    out['mf'] = rsimfi(df)
    return out

def fetch_1h(sym, period='730d'):
    d = yf.download(sym, period=period, interval='1h', auto_adjust=True, prepost=False, progress=False)
    if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
    return d

def to_4h_rth(d1h, tz='America/New_York'):
    """TradingView-style 4h bars for US equities, RTH: 09:30-13:30 and 13:30-16:00."""
    d = d1h.copy()
    d.index = d.index.tz_convert(tz)
    d = d.between_time('09:30', '15:59')
    key = d.index.to_period('D').astype(str) + np.where(d.index.time < pd.Timestamp('13:30').time(), 'A', 'B')
    g = d.groupby(key)
    out = pd.DataFrame({'Open': g.Open.first(), 'High': g.High.max(), 'Low': g.Low.min(),
                        'Close': g.Close.last(), 'Volume': g.Volume.sum()})
    out['ts'] = g.apply(lambda x: x.index[0])
    out = out.set_index('ts').sort_index()
    return out

def weekly(sym, period='5y'):
    d = yf.download(sym, period=period, interval='1wk', auto_adjust=True, progress=False)
    if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
    return d
