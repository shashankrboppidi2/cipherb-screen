"""
Cipher B crypto screen — runs after every 4h bar close (UTC boundaries).

Same rule as the equity screen (see screen.py), on continuous 24/7 bars:
  4h:     big green dot on one of the last 2 closed 4h bars, WT2 trough (last 6 bars) <= -60
  Zone:   last close inside the bottom 0.236 AutoFib band over 265 4h bars (~44 days)
  Weekly: WT2 on the current weekly bar <= -60
Universe: top-N coins by market cap (CoinGecko), stablecoins/wrapped tokens removed,
          priced from Yahoo (SYM-USD). TradingView links point to Coinbase USD pairs when
          the coin trades there, else to the CRYPTO: aggregate.
"""
import os, sys, json, time, warnings, logging
from datetime import datetime, timezone
import numpy as np, pandas as pd, yfinance as yf, requests
from cipherb import signals
from screen import send_mail  # reuse SMTP settings/behaviour
warnings.filterwarnings("ignore"); logging.getLogger("yfinance").setLevel(logging.CRITICAL)

TOP_N       = int(os.getenv("CRYPTO_TOP_N", "250"))
WT_TROUGH, WK_LEVEL, WK_NEAR = -60, -60, -40
DOT_BARS, TROUGH_BARS, FIB_LEN, FIB_BAND, MIN_BARS = 2, 6, 265, 0.236, 300
RESULTS = "results"
NOW = datetime.now(timezone.utc); STAMP = NOW.strftime("%Y-%m-%d_%H") + "Z"

STABLE = {"USDT","USDC","DAI","USDS","USDE","FDUSD","TUSD","PYUSD","USD1","USDD","FRAX","GUSD","USDP","BUSD","EURC",
          "RLUSD","USDY","USD0","USDG","AUSD","USDTB","XAUT","PAXG","CUSD","SUSD","USDX","BUIDL","USDL","EURS","FIGR_HELOC"}
WRAPPED_PREFIX = ("WBTC","WETH","WSTETH","STETH","WEETH","CBBTC","CBETH","RETH","EZETH","RSETH","WBNB","LBTC","TBTC",
                  "SOLVBTC","METH","BNSOL","JITOSOL","MSOL","WHYPE","SUSDE","SDAI","FBTC","BFBTC","WBETH","OSETH","LSETH")

def universe():
    r = requests.get("https://api.coingecko.com/api/v3/coins/markets",
                     params=dict(vs_currency="usd", order="market_cap_desc", per_page=250, page=1), timeout=60)
    r.raise_for_status(); coins = r.json()[:TOP_N]
    try:
        p = requests.get("https://api.exchange.coinbase.com/products", timeout=60).json()
        cb = {x["base_currency"] for x in p if x.get("quote_currency") == "USD" and x.get("status") == "online"}
    except Exception: cb = set()
    out = []
    for c in coins:
        s = c["symbol"].upper()
        if s in STABLE or s.startswith(WRAPPED_PREFIX) or "USD" in s: continue
        out.append(dict(sym=s, name=c["name"], rank=c["market_cap_rank"], mcap_b=round((c["market_cap"] or 0)/1e9, 2),
                        yahoo=f"{s}-USD", tv=(f"COINBASE:{s}USD" if s in cb else f"CRYPTO:{s}USD")))
    return out

CB = "https://api.exchange.coinbase.com"
def cb_candles(product, granularity, n_needed):
    """Coinbase public candles, paged (max 300 per call). Returns OHLCV indexed by UTC time."""
    frames, end = [], NOW
    step = pd.Timedelta(seconds=granularity * 300)
    while sum(len(f) for f in frames) < n_needed:
        start = end - step
        r = requests.get(f"{CB}/products/{product}/candles",
                         params=dict(granularity=granularity, start=start.isoformat(), end=end.isoformat()), timeout=30)
        if r.status_code == 429: time.sleep(2); continue
        r.raise_for_status(); rows = r.json()
        if not rows: break
        frames.append(pd.DataFrame(rows, columns=["t","Low","High","Open","Close","Volume"]))
        end = start; time.sleep(0.12)
    if not frames: return pd.DataFrame()
    d = pd.concat(frames); d.index = pd.to_datetime(d.t, unit="s", utc=True)
    return d.drop(columns="t").sort_index()[~d.index.duplicated()]

def cb_history(sym):
    """1h bars for ~60 days (-> 4h) and daily bars for ~2 years (-> weekly)."""
    h1 = cb_candles(f"{sym}-USD", 3600, 1500)
    d1 = cb_candles(f"{sym}-USD", 86400, 700)
    wk = d1.resample("W-MON", label="left", closed="left").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna(subset=["Close"])
    return h1, wk

def to_4h_utc(d1h):
    d = d1h.copy(); d.index = d.index.tz_convert("UTC")
    o = d.resample("4h", label="left", closed="left").agg({"Open":"first","High":"max","Low":"min","Close":"last","Volume":"sum"}).dropna(subset=["Close"])
    # drop the bar still forming
    if len(o) and o.index[-1] + pd.Timedelta(hours=4) > NOW: o = o.iloc[:-1]
    return o

def evaluate(u, h1, wk):
    d4 = to_4h_utc(h1); s4 = signals(d4)
    if len(s4) < MIN_BARS: return {**u, "err": f"only {len(s4)} 4h bars"}
    last = s4.iloc[-DOT_BARS:]; c = d4.Close.iloc[-FIB_LEN:]; mn, mx = float(c.min()), float(c.max())
    close = float(d4.Close.iloc[-1]); sw = signals(wk)
    r = {**u, "err": np.nan, "link": f"https://www.tradingview.com/chart/?symbol={u['tv'].replace(':', '%3A')}",
         "dot_last2": bool(last.buy.any()), "dot_bar": str(last[last.buy].index[-1])[:16] if last.buy.any() else "",
         "wt2_trough": float(s4.wt2.iloc[-TROUGH_BARS:].min()), "wt2_now": float(s4.wt2.iloc[-1]),
         "close": close, "zone_low": mn, "zone_top": mn + FIB_BAND*(mx-mn),
         "pct_of_range": (close-mn)/(mx-mn) if mx > mn else np.nan, "wk_wt2": float(sw.wt2.iloc[-1]), "bar_close": str(d4.index[-1])[:16]}
    r["in_zone"] = close <= r["zone_top"]; r["pass_4h"] = r["dot_last2"] and r["wt2_trough"] <= WT_TROUGH
    r["pass_wk"] = r["wk_wt2"] <= WK_LEVEL; r["flag"] = r["pass_4h"] and r["in_zone"] and r["pass_wk"]
    if r["flag"]: r["bucket"] = "FULL PASS"
    elif r["in_zone"] and r["pass_wk"] and r["wt2_trough"] <= WT_TROUGH: r["bucket"] = "WATCH: weekly+band ok, waiting on 4h dot"
    elif r["pass_4h"] and r["in_zone"] and WK_LEVEL < r["wk_wt2"] <= WK_NEAR: r["bucket"] = "NEAR: 4h+band ok, weekly shallow"
    elif r["pass_4h"] and r["pass_wk"]: r["bucket"] = "NEAR: 4h+weekly ok, above band"
    else: r["bucket"] = ""
    return r

def run(univ):
    rows = []
    cb_coins = [u for u in univ if u["tv"].startswith("COINBASE:")]
    yh_coins = [u for u in univ if not u["tv"].startswith("COINBASE:")]
    for k, u in enumerate(cb_coins, 1):
        try:
            h1, wk = cb_history(u["sym"])
            rows.append(evaluate({**u, "source": "coinbase"}, h1, wk) if len(h1) else {**u, "err": "no coinbase data"})
        except Exception as e: rows.append({**u, "err": f"coinbase: {str(e)[:50]}"})
        if k % 25 == 0: print(f"coinbase {k}/{len(cb_coins)}", flush=True)
    univ = [{**u, "source": "yahoo"} for u in yh_coins]
    ys = [u["yahoo"] for u in univ]; by = {u["yahoo"]: u for u in univ}
    for i in range(0, len(ys), 40):
        chunk = ys[i:i+40]
        for attempt in range(3):
            try:
                h = yf.download(chunk, period="120d", interval="1h", auto_adjust=True, group_by="ticker", threads=True, progress=False)
                w = yf.download(chunk, period="5y", interval="1wk", auto_adjust=True, group_by="ticker", threads=True, progress=False)
                break
            except Exception: time.sleep(10*(attempt+1))
        else:
            rows += [{**by[y], "err": "download failed"} for y in chunk]; continue
        for y in chunk:
            try:
                hh = h[y].dropna(subset=["Close"]); ww = w[y].dropna(subset=["Close"])
                rows.append(evaluate(by[y], hh, ww) if len(hh) else {**by[y], "err": "no data"})
            except Exception as e: rows.append({**by[y], "err": str(e)[:60]})
        print(f"{i+len(chunk)}/{len(ys)}", flush=True)
    return pd.DataFrame(rows)

def html_report(df):
    def table(sub, title):
        if sub.empty: return f"<h3>{title}</h3><p>none</p>"
        rows = "".join(f"<tr><td><a href='{r.link}'>{r.sym}</a> <small>{r.name} (#{r.rank})</small></td><td>{r.dot_bar}</td>"
                       f"<td>{r.wt2_trough:.1f}</td><td>{r.wt2_now:.1f}</td><td>{r.close:g}</td><td>{r.zone_top:g}</td><td>{r.wk_wt2:.1f}</td></tr>"
                       for r in sub.itertuples())
        return (f"<h3>{title} ({len(sub)})</h3><table border=1 cellpadding=4 style='border-collapse:collapse;font-size:13px'>"
                "<tr><th>Coin</th><th>4h dot (UTC)</th><th>4h trough</th><th>4h WT2 now</th><th>Close</th><th>Band top</th><th>Weekly WT2</th></tr>"
                f"{rows}</table>")
    parts = [f"<h2>Cipher B crypto screen — {NOW:%Y-%m-%d %H:%M} UTC</h2><p>{len(df)} coins evaluated (top {TOP_N} by market cap, stablecoins/wrapped removed). "
             f"Last closed 4h bar: {df.bar_close.dropna().max() if 'bar_close' in df else ''} UTC.</p>"]
    for b in ["FULL PASS", "WATCH: weekly+band ok, waiting on 4h dot", "NEAR: 4h+band ok, weekly shallow", "NEAR: 4h+weekly ok, above band"]:
        parts.append(table(df[df.bucket == b].sort_values(["wt2_trough", "wk_wt2"]), b))
    return "\n".join(parts)

def main():
    os.makedirs(RESULTS, exist_ok=True)
    univ = universe(); print(f"{len(univ)} coins after filtering")
    df = run(univ); ok = df[df.err.isna()].copy()
    ok.to_csv(f"{RESULTS}/crypto_{STAMP}.csv", index=False); ok.to_csv(f"{RESULTS}/crypto_latest.csv", index=False)
    html = html_report(ok); open(f"{RESULTS}/crypto_latest.html", "w").write(html)
    n_full = int((ok.bucket == "FULL PASS").sum()); n_watch = int((ok.bucket != "").sum()) - n_full
    print(f"evaluated {len(ok)}; full passes: {n_full}; watch/near: {n_watch}")
    if n_full or os.getenv("CRYPTO_MAIL_ALWAYS") == "1":
        send_mail(f"Cipher B crypto {NOW:%m-%d %H:%M}Z: {n_full} full pass, {n_watch} watch", html)
    else:
        print("no full pass; e-mail skipped (set CRYPTO_MAIL_ALWAYS=1 to always send)")

if __name__ == "__main__":
    main()
