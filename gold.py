"""Cipher B gold-dot logic, ported line-for-line from the VuManChu Pine (v4) source.
Defaults: WT bullish-divergence floor -65, osLevel3 -75, RSI 14, gold needs prior-low RSI < 30."""
import numpy as np, pandas as pd
from cipherb import wavetrend

def rsi(close, n=14):
    d = close.diff(); up = d.clip(lower=0); dn = -d.clip(upper=0)
    au = up.ewm(alpha=1/n, adjust=False).mean(); ad = dn.ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + au / ad.replace(0, np.nan))

def bot_fractal(s):
    # src[4] > src[2] and src[3] > src[2] and src[2] < src[1] and src[2] < src[0]
    s2 = s.shift(2)
    return (s.shift(4) > s2) & (s.shift(3) > s2) & (s2 < s.shift(1)) & (s2 < s)

def valuewhen_prev(cond, src):
    """valuewhen(cond, src, 0)[2]: value of src at the most recent True in cond, as of 2 bars ago."""
    return src.where(cond).ffill().shift(2)

def gold_signals(df, os3=-75, div_floor=-65, rsi_floor=30):
    wt1, wt2 = wavetrend(df); r = rsi(df.Close)
    fb = bot_fractal(wt2) & (wt2.shift(2) <= div_floor)          # fractalBot with OS limit
    low_prev  = valuewhen_prev(fb, wt2.shift(2))                 # previous fractal's WT2
    low_price = valuewhen_prev(fb, df.Low.shift(2))              # previous fractal's price low
    last_rsi  = valuewhen_prev(fb, r.shift(2))                   # RSI at previous fractal
    bull_div = fb & (df.Low.shift(2) < low_price) & (wt2.shift(2) > low_prev)
    gold = bull_div & (low_prev <= os3) & (wt2 > os3) & ((low_prev - wt2) <= -5) & (last_rsi < rsi_floor)
    out = df.copy(); out["wt1"], out["wt2"], out["rsi"] = wt1, wt2, r
    out["bull_div"], out["gold"] = bull_div, gold
    out["gold_wt2_at_dot"] = wt2.shift(2).where(gold)             # where the dot is drawn (offset -2)
    return out
