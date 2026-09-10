"""
ETF screen — Cipher B 4h + weekly, over the AUM-ranked ETF list in watchlists/etfs.csv.

Rule (script defaults, no extra trough requirement):
  4h:     big green dot (WT1 crosses above WT2 with WT2 <= -53) on one of the last 2 completed 4h bars
  Zone:   last 4h close inside the bottom 0.236 AutoFib band over 265 4h bars
  Weekly: WT2 on the current weekly bar <= -60
Ranking: HIGH if the 4h WT2 trough (last 6 bars) reached -60 or lower, else STANDARD.
Leveraged and inverse ETFs are included and labelled. Monthly WT2 is shown for context only.
Universe: US + Canada (TSX/NEO). India (NSE) is skipped for now (different session clock).
"""
import os, sys, time, warnings, logging
from datetime import date, timedelta
import numpy as np, pandas as pd, yfinance as yf
from cipherb import signals, to_4h_rth, wavetrend
from screen import send_mail, in_et_window
warnings.filterwarnings("ignore"); logging.getLogger("yfinance").setLevel(logging.CRITICAL)

WK_LEVEL, WK_NEAR, HIGH_TROUGH = -60, -40, -60
DOT_BARS, TROUGH_BARS, FIB_LEN, FIB_BAND, MIN_BARS = 2, 6, 265, 0.236, 270
RESULTS = "results"; TODAY = date.today().isoformat()
INCLUDE_EXCHANGES = {"US", "TSX", "NEO"}

def load_universe():
    df = pd.read_csv("watchlists/etfs.csv")
    df = df[df.exchange.isin(INCLUDE_EXCHANGES)].copy()
    def yh(r):
        t = str(r.ticker).replace(".", "-")
        return {"TSX": t + ".TO", "NEO": t + ".NE"}.get(r.exchange, t)
    def tv(r):
        t = str(r.ticker)
        return {"TSX": f"TSX:{t}", "NEO": f"NEO:{t}"}.get(r.exchange, f"AMEX:{t}")   # most US ETFs list on Arca; TV resolves AMEX: to the right exchange
    df["yahoo"] = df.apply(yh, axis=1); df["tv"] = df.apply(tv, axis=1)
    return df[["rank","ticker","yahoo","tv","exchange","name","aum_usd_bn","category","leverage","avg_volume"]].reset_index(drop=True)

def evaluate(u, h1, wk, mo):
    d4 = to_4h_rth(h1); s4 = signals(d4)
    if len(s4) < MIN_BARS: return {**u, "err": f"only {len(s4)} 4h bars"}
    last = s4.iloc[-DOT_BARS:]; c = d4.Close.iloc[-FIB_LEN:]; mn, mx = float(c.min()), float(c.max())
    close = float(d4.Close.iloc[-1]); sw = signals(wk)
    try: mo_wt2 = float(wavetrend(mo)[1].iloc[-1]) if len(mo) >= 40 else np.nan
    except Exception: mo_wt2 = np.nan
    r = {**u, "err": np.nan, "link": f"https://www.tradingview.com/chart/?symbol={u['tv'].replace(':', '%3A')}",
         "dot_last2": bool(last.buy.any()), "dot_bar": str(last[last.buy].index[-1])[:16] if last.buy.any() else "",
         "wt2_trough": float(s4.wt2.iloc[-TROUGH_BARS:].min()), "wt2_now": float(s4.wt2.iloc[-1]),
         "close": close, "zone_low": mn, "zone_top": mn + FIB_BAND*(mx-mn), "pct_of_range": (close-mn)/(mx-mn) if mx > mn else np.nan,
         "wk_wt2": float(sw.wt2.iloc[-1]), "mo_wt2": mo_wt2}
    r["in_zone"] = close <= r["zone_top"]; r["pass_wk"] = r["wk_wt2"] <= WK_LEVEL
    r["flag"] = r["dot_last2"] and r["in_zone"] and r["pass_wk"]
    r["tier"] = ("HIGH" if r["wt2_trough"] <= HIGH_TROUGH else "STANDARD") if r["flag"] else ""
    if r["flag"]: r["bucket"] = "FULL PASS"
    elif r["in_zone"] and r["pass_wk"] and r["wt2_trough"] <= HIGH_TROUGH: r["bucket"] = "WATCH: weekly+band ok, waiting on 4h dot"
    elif r["dot_last2"] and r["in_zone"] and WK_LEVEL < r["wk_wt2"] <= WK_NEAR: r["bucket"] = "NEAR: 4h+band ok, weekly shallow"
    elif r["dot_last2"] and r["pass_wk"]: r["bucket"] = "NEAR: 4h+weekly ok, above band"
    else: r["bucket"] = ""
    return r

def run(univ):
    rows = []; ys = univ.yahoo.tolist(); by = {r.yahoo: r._asdict() for r in univ.itertuples(index=False)}
    start = (date.today() - timedelta(days=400)).isoformat()
    for i in range(0, len(ys), 40):
        chunk = ys[i:i+40]
        for attempt in range(3):
            try:
                h = yf.download(chunk, start=start, interval="1h", auto_adjust=True, prepost=False, group_by="ticker", threads=True, progress=False)
                w = yf.download(chunk, period="5y", interval="1wk", auto_adjust=True, group_by="ticker", threads=True, progress=False)
                m = yf.download(chunk, period="10y", interval="1mo", auto_adjust=True, group_by="ticker", threads=True, progress=False)
                break
            except Exception: time.sleep(10*(attempt+1))
        else:
            rows += [{**by[y], "err": "download failed"} for y in chunk]; continue
        for y in chunk:
            try:
                hh = h[y].dropna(subset=["Close"]); ww = w[y].dropna(subset=["Close"]); mm = m[y].dropna(subset=["Close"])
                rows.append(evaluate(by[y], hh, ww, mm) if len(hh) else {**by[y], "err": "no data"})
            except Exception as e: rows.append({**by[y], "err": str(e)[:60]})
        print(f"{i+len(chunk)}/{len(ys)}", flush=True)
    return pd.DataFrame(rows)

def html_report(df):
    def fmt(x, n=1): return "" if pd.isna(x) else f"{x:.{n}f}"
    def table(sub, title):
        if sub.empty: return f"<h3>{title}</h3><p>none</p>"
        rows = "".join(
            f"<tr><td>{r.tier}</td><td><a href='{r.link}'>{r.ticker}</a> <small>{r.name[:40]}</small></td><td>{r.leverage}</td><td>{fmt(r.aum_usd_bn,1)}</td>"
            f"<td>{r.dot_bar}</td><td>{fmt(r.wt2_trough)}</td><td>{fmt(r.wt2_now)}</td><td>{fmt(r.close,2)}</td><td>{fmt(r.zone_top,2)}</td>"
            f"<td>{fmt(r.wk_wt2)}</td><td>{fmt(r.mo_wt2)}</td></tr>" for r in sub.itertuples())
        return (f"<h3>{title} ({len(sub)})</h3><table border=1 cellpadding=4 style='border-collapse:collapse;font-size:13px'>"
                "<tr><th>Tier</th><th>ETF</th><th>Lev</th><th>AUM $B</th><th>4h dot</th><th>4h trough</th><th>4h WT2 now</th><th>Close</th><th>Band top</th><th>Weekly WT2</th><th>Monthly WT2</th></tr>"
                f"{rows}</table>")
    df = df.copy(); df["short"] = df.leverage.astype(str).str.contains("Short")
    longs, shorts = df[~df.short], df[df.short]
    parts = [f"<h2>ETF screen — {TODAY}</h2><p>{len(df)} ETFs evaluated (US + Canada, leveraged included). Rule: 4h big green dot in last {DOT_BARS} bars, "
             f"close in bottom {FIB_BAND} fib band ({FIB_LEN} bars), weekly WT2 ≤ {WK_LEVEL}. HIGH tier = 4h trough ≤ {HIGH_TROUGH}. Monthly WT2 is context only.</p>"]
    buckets = ["FULL PASS", "WATCH: weekly+band ok, waiting on 4h dot", "NEAR: 4h+band ok, weekly shallow", "NEAR: 4h+weekly ok, above band"]
    def section(sub, prefix):
        out = []
        for b in buckets:
            x = sub[sub.bucket == b].copy()
            if b == "FULL PASS": x["tier_rank"] = (x.tier != "HIGH").astype(int); x = x.sort_values(["tier_rank", "wt2_trough", "wk_wt2"])
            else: x = x.sort_values(["wt2_trough", "wk_wt2"])
            out.append(table(x, f"{prefix}{b}"))
        return out
    parts += section(longs, "")
    parts.append("<hr><h3>Inverse / short ETFs</h3><p>Listed separately: inverse funds decay structurally, so they sit in the oversold band whenever the market rises. Treat these as a different trade.</p>")
    parts += section(shorts, "Inverse — ")
    return "\n".join(parts)

def main():
    if not in_et_window(os.getenv("ET_WINDOW", "")): print("outside ET window; skipping"); return
    os.makedirs(RESULTS, exist_ok=True)
    univ = load_universe(); print(f"{len(univ)} ETFs")
    df = run(univ); ok = df[df.err.isna()].copy()
    ok.to_csv(f"{RESULTS}/etf_{TODAY}.csv", index=False); ok.to_csv(f"{RESULTS}/etf_latest.csv", index=False)
    html = html_report(ok); open(f"{RESULTS}/etf_report_{TODAY}.html", "w").write(html); open(f"{RESULTS}/etf_latest.html", "w").write(html)
    n_full = int((ok.bucket == "FULL PASS").sum()); n_high = int((ok.tier == "HIGH").sum())
    print(f"evaluated {len(ok)}; full passes: {n_full} (HIGH {n_high}); watch/near: {int((ok.bucket != '').sum()) - n_full}")
    send_mail(f"ETF screen {TODAY}: {n_full} full pass ({n_high} HIGH), {int((ok.bucket != '').sum()) - n_full} watch", html)

if __name__ == "__main__":
    main()
