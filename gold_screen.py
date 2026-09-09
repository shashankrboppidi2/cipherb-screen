"""
Hourly Cipher B GOLD-dot screen — equities (RTH 1h bars) + crypto top 250 (Coinbase 1h bars).

Fires when a gold dot confirms on one of the last 2 closed 1h bars AND WT2 on the confirming bar
is at or below WT_LINE (-60, the drawn white line). Gold dot = bullish WT divergence whose previous
low was <= -75, wave lifted >= 5 points off it, RSI at that low < 30 (VuManChu defaults).
"""
import os, sys, time, warnings, logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, yfinance as yf
from gold import gold_signals
from screen import load_universe, yh, tv_link, send_mail, in_et_window
import crypto_screen as cs
warnings.filterwarnings("ignore"); logging.getLogger("yfinance").setLevel(logging.CRITICAL)

WT_LINE = -60; DOT_BARS = 2; RESULTS = "results"
ET = ZoneInfo("America/New_York"); NOW = datetime.now(timezone.utc); STAMP = NOW.strftime("%Y-%m-%d_%H%M") + "Z"

def closed_bars_equity(d1h):
    d = d1h.copy(); d.index = d.index.tz_convert(ET); d = d.between_time("09:30", "15:59")
    if len(d):
        last = d.index[-1]; end = last.replace(hour=16, minute=0) if last.time() >= pd.Timestamp("15:30").time() else last + timedelta(hours=1)
        if end > NOW.astimezone(ET): d = d.iloc[:-1]
    return d

def check(df, tv, label):
    g = gold_signals(df)
    if len(g) < 120: return None
    last = g.iloc[-DOT_BARS:]; hit = last[last.gold & (last.wt2 <= WT_LINE)]
    raw = last[last.gold]
    return dict(tv=tv, label=label, link=tv_link(tv), gold_any=bool(len(raw)),
                fired=bool(len(hit)), bar=str(hit.index[-1])[:16] if len(hit) else (str(raw.index[-1])[:16] if len(raw) else ""),
                wt2_at_confirm=float(hit.wt2.iloc[-1]) if len(hit) else (float(raw.wt2.iloc[-1]) if len(raw) else np.nan),
                wt2_now=float(g.wt2.iloc[-1]), rsi=float(g.rsi.iloc[-1]), close=float(g.Close.iloc[-1]),
                last_bar=str(g.index[-1])[:16])

def run_equities():
    univ = load_universe(); ymap = {yh(s): s for s in univ}; ys = list(ymap); rows = []
    for i in range(0, len(ys), 50):
        chunk = ys[i:i+50]
        for attempt in range(3):
            try:
                h = yf.download(chunk, period="60d", interval="1h", auto_adjust=True, prepost=False, group_by="ticker", threads=True, progress=False); break
            except Exception: time.sleep(10*(attempt+1))
        else: continue
        for y in chunk:
            try:
                d = h[y].dropna(subset=["Close"])
                if len(d): r = check(closed_bars_equity(d), ymap[y], "equity"); rows.append(r) if r else None
            except Exception: pass
        print(f"equities {i+len(chunk)}/{len(ys)}", flush=True)
    return rows

def run_crypto():
    rows = []
    for k, u in enumerate(cs.universe(), 1):
        if not u["tv"].startswith("COINBASE:"): continue   # Yahoo crypto symbols collide; Coinbase only here
        try:
            h1 = cs.cb_candles(f"{u['sym']}-USD", 3600, 400)
            if len(h1) and h1.index[-1] + timedelta(hours=1) > NOW: h1 = h1.iloc[:-1]
            r = check(h1, u["tv"], "crypto"); rows.append(r) if r else None
        except Exception: pass
    return rows

def html(df):
    def table(sub, title):
        if sub.empty: return f"<h3>{title}</h3><p>none</p>"
        rows = "".join(f"<tr><td><a href='{r.link}'>{r.tv}</a></td><td>{r.label}</td><td>{r.bar}</td><td>{r.wt2_at_confirm:.1f}</td>"
                       f"<td>{r.wt2_now:.1f}</td><td>{r.rsi:.1f}</td><td>{r.close:g}</td></tr>" for r in sub.itertuples())
        return (f"<h3>{title} ({len(sub)})</h3><table border=1 cellpadding=4 style='border-collapse:collapse;font-size:13px'>"
                "<tr><th>Ticker</th><th>Type</th><th>Confirming 1h bar</th><th>WT2 at confirm</th><th>WT2 now</th><th>RSI</th><th>Close</th></tr>"
                f"{rows}</table>")
    return (f"<h2>Cipher B gold-dot screen (1h) — {NOW.astimezone(ET):%Y-%m-%d %H:%M} ET</h2><p>{len(df)} instruments checked.</p>"
            + table(df[df.fired].sort_values("wt2_at_confirm"), f"GOLD DOT with WT2 ≤ {WT_LINE}")
            + table(df[df.gold_any & ~df.fired].sort_values("wt2_at_confirm"), f"Gold dot but WT2 above {WT_LINE} (info only)"))

def main():
    if not in_et_window(os.getenv("ET_WINDOW", "")): print("outside ET window; skipping"); return
    hours = os.getenv("ET_HOURS", "")
    if hours and str(NOW.astimezone(ET).hour) not in hours.split(","): print("not a scheduled ET hour; skipping"); return
    os.makedirs(RESULTS, exist_ok=True)
    scope = os.getenv("GOLD_UNIVERSE", "all")          # all | equity | crypto
    rows = (run_equities() if scope in ("all", "equity") else []) + (run_crypto() if scope in ("all", "crypto") else [])
    tag = "gold" if scope == "all" else f"gold_{scope}"
    df = pd.DataFrame(rows); df.to_csv(f"{RESULTS}/{tag}_latest.csv", index=False)
    hits = df[df.fired] if len(df) else df
    if len(hits): hits.to_csv(f"{RESULTS}/{tag}_hits_{STAMP}.csv", index=False)
    page = html(df); open(f"{RESULTS}/{tag}_latest.html", "w").write(page)
    print(f"[{scope}] checked {len(df)}; gold dots: {int(df.gold_any.sum()) if len(df) else 0}; fired (WT2<={WT_LINE}): {len(hits)}")
    if len(hits) or os.getenv("GOLD_MAIL_ALWAYS") == "1":
        send_mail(f"GOLD dot 1h {scope} {NOW.astimezone(ET):%m-%d %H:%M} ET: {len(hits)} hit(s)", page)

if __name__ == "__main__":
    main()
