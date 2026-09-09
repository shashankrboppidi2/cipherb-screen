"""
Cipher B daily screen — end-of-day run.

Rules (all must hold for a FULL pass):
  4h:      VuManChu Cipher B big green dot on one of the last 2 completed 4h bars,
           and WT2 trough over the last 6 bars <= WT_TROUGH.
  Zone:    last 4h close inside the bottom AutoFib band  (low .. low + 0.236 * range),
           range = highest/lowest close over FIB_LEN 4h bars.
  Weekly:  Cipher B WT2 on the current weekly bar <= WK_LEVEL.

Near-miss buckets are reported too, so setups can be watched before they complete.
Flagged names are enriched with sector, industry, size, returns, business summary,
and recent headline links.
"""
import os, sys, json, glob, time, smtplib, warnings
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import numpy as np, pandas as pd, yfinance as yf
from cipherb import signals, to_4h_rth
warnings.filterwarnings("ignore")

# ---------------- rule parameters ----------------
WT_TROUGH   = -60      # 4h WT2 trough must reach this (the drawn white line)
WK_LEVEL    = -60      # weekly WT2 must be at or below this
WK_NEAR     = -40      # near-miss band for the weekly
DOT_BARS    = 2        # dot must be on one of the last N completed 4h bars
TROUGH_BARS = 6        # window over which the trough is measured
FIB_LEN     = 265      # AutoFib lookback in 4h bars
FIB_BAND    = 0.236
MIN_BARS    = 270      # skip tickers with less 4h history than this

# income securities to skip (add to this list as you find them)
EXCLUDE = {"NYSE:UNMA","NYSE:DUKB","NYSE:TBB","NYSE:SOJE","NYSE:DTW","NYSE:SREA","NYSE:SOJD","NASDAQ:XELLL",
           "NASDAQ:FCNCN","NYSE:AQNB","NYSE:APOS","NYSE:RZC","NYSE:AEFC","NYSE:ATHS","NYSE:PPLC","NYSE:SOMN","NYSE:EMA",
           "NYSE:BEPI","NYSE:MGRB","NYSE:MGRD","NYSE:BEPH","NYSE:MGRE","NYSE:CMSC","NASDAQ:BPYPO","NYSE:MGR","NYSE:BIPH",
           "NASDAQ:JSM","NYSE:FGN","NYSE:ASBA","NYSE:DTG","NYSE:DTB","NYSE:RWTN","NYSE:RWTQ","NYSE:HCXY","NASDAQ:APXT",
           "NYSE:AFGB","NYSE:KMPB","NYSE:AFGD","NYSE:AFGC","NYSE:AFGE","NYSE:PSUS","NYSE:SSMR","NYSE:AMBQ","NYSE:BMNP","NYSE:PRH","NYSE:PRS"}
# names the low-volatility heuristic would wrongly tag; always keep
KEEP = {"NYSE:NLY","NASDAQ:WBD","NYSE:WY","NYSE:OBDC","TSX:ELF","NYSE:RYN","NASDAQ:GBDC","NYSE:FCPT","NYSE:DBRG",
        "NYSE:ARR","TSX:FRU","NYSE:DX","NYSE:KRP","NYSE:MSDL","NYSE:LADR"}

RESULTS = "results"
TODAY = date.today().isoformat()

def yh(tv):
    ex, t = tv.split(":"); t = t.replace(".", "-")
    return {"TSX": t + ".TO", "NSE": t + ".NS"}.get(ex, t)

def tv_link(tv):
    return f"https://www.tradingview.com/chart/?symbol={tv.replace(':', '%3A')}"

def load_universe():
    syms = []
    files = sorted(glob.glob("watchlists/*.txt")) or sorted(glob.glob("*Watchlist*.txt")) or sorted(glob.glob("**/*Watchlist*.txt", recursive=True))
    for f in files:
        syms += [s.strip() for s in open(f).read().strip().split(",") if s.strip()]
    seen, out = set(), []
    for s in syms:
        if s in EXCLUDE or s in seen: continue
        seen.add(s); out.append(s)
    return out

def evaluate(tv, h1, wk):
    d4 = to_4h_rth(h1); s4 = signals(d4)
    if len(s4) < MIN_BARS: return {"tv": tv, "err": f"only {len(s4)} 4h bars"}
    last = s4.iloc[-DOT_BARS:]
    c = d4.Close.iloc[-FIB_LEN:]; mn, mx = float(c.min()), float(c.max())
    close = float(d4.Close.iloc[-1]); med = float(c.median())
    sw = signals(wk)
    r = dict(tv=tv, err=np.nan, link=tv_link(tv),
             dot_last2=bool(last.buy.any()),
             dot_bar=str(last[last.buy].index[-1])[:16] if last.buy.any() else "",
             wt2_trough=float(s4.wt2.iloc[-TROUGH_BARS:].min()), wt2_now=float(s4.wt2.iloc[-1]),
             close=close, zone_low=mn, zone_top=mn + FIB_BAND * (mx - mn),
             pct_of_range=(close - mn) / (mx - mn) if mx > mn else np.nan,
             wk_wt2=float(sw.wt2.iloc[-1]), wk_wt1=float(sw.wt1.iloc[-1]),
             range_pct=(mx - mn) / med if med else np.nan, med_price=med)
    r["likely_pref"] = (10 <= med <= 30) and r["range_pct"] < 0.15 and tv not in KEEP
    r["in_zone"]  = close <= r["zone_top"]
    r["pass_4h"]  = r["dot_last2"] and r["wt2_trough"] <= WT_TROUGH
    r["pass_wk"]  = r["wk_wt2"] <= WK_LEVEL
    r["flag"]     = r["pass_4h"] and r["in_zone"] and r["pass_wk"] and not r["likely_pref"]
    # near-miss buckets
    if r["flag"]:                                                   r["bucket"] = "FULL PASS"
    elif r["in_zone"] and r["pass_wk"] and r["wt2_trough"] <= WT_TROUGH: r["bucket"] = "WATCH: weekly+band ok, waiting on 4h dot"
    elif r["pass_4h"] and r["in_zone"] and WK_LEVEL < r["wk_wt2"] <= WK_NEAR: r["bucket"] = "NEAR: 4h+band ok, weekly shallow"
    elif r["pass_4h"] and r["pass_wk"]:                             r["bucket"] = "NEAR: 4h+weekly ok, above band"
    else:                                                           r["bucket"] = ""
    return r

def run_screen(universe):
    ymap = {yh(s): s for s in universe}
    ys = list(ymap); rows = []
    start = (date.today() - timedelta(days=400)).isoformat()
    for i in range(0, len(ys), 40):
        chunk = ys[i:i + 40]
        for attempt in range(3):
            try:
                h = yf.download(chunk, start=start, interval="1h", auto_adjust=True, prepost=False,
                                group_by="ticker", threads=True, progress=False)
                w = yf.download(chunk, period="5y", interval="1wk", auto_adjust=True,
                                group_by="ticker", threads=True, progress=False)
                break
            except Exception:
                time.sleep(10 * (attempt + 1))
        else:
            rows += [{"tv": ymap[y], "err": "download failed"} for y in chunk]; continue
        for y in chunk:
            try:
                hh = h[y].dropna(subset=["Close"]); ww = w[y].dropna(subset=["Close"])
                rows.append(evaluate(ymap[y], hh, ww) if len(hh) else {"tv": ymap[y], "err": "no data"})
            except Exception as e:
                rows.append({"tv": ymap[y], "err": str(e)[:60]})
        print(f"{i + len(chunk)}/{len(ys)}", flush=True)
    return pd.DataFrame(rows)

# ---------------- enrichment ----------------
def enrich(tv):
    t = yf.Ticker(yh(tv)); out = {"tv": tv}
    try:
        i = t.info
        out.update(name=i.get("shortName"), sector=i.get("sector"), industry=i.get("industry"),
                   mcap_b=round((i.get("marketCap") or 0) / 1e9, 1),
                   summary=(i.get("longBusinessSummary") or "")[:400])
    except Exception: pass
    try:
        c = t.history(period="1y").Close
        out.update(ret_1m=round((c.iloc[-1] / c.iloc[-22] - 1) * 100, 1),
                   ret_3m=round((c.iloc[-1] / c.iloc[-64] - 1) * 100, 1),
                   off_52w_high=round((c.iloc[-1] / c.max() - 1) * 100, 1))
    except Exception: pass
    try:
        ed = t.get_earnings_dates(limit=8)
        fut = ed[ed.index > pd.Timestamp.now(tz=ed.index.tz)] if ed is not None and len(ed) else None
        out["next_earnings"] = str(fut.index.min().date()) if fut is not None and len(fut) else ""
    except Exception: out["next_earnings"] = ""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=21); heads = []
        for n in (t.news or [])[:15]:
            c = n.get("content", n); ts = c.get("pubDate") or c.get("providerPublishTime")
            when = pd.to_datetime(ts, utc=True) if ts else None
            if when is None or when >= cutoff:
                heads.append({"date": str(when)[:10] if when is not None else "", "title": c.get("title", ""),
                              "url": (c.get("canonicalUrl") or {}).get("url") or c.get("link", "")})
        out["headlines"] = heads[:8]
    except Exception: out["headlines"] = []
    return out

# ---------------- report ----------------
def html_report(df, enriched):
    def table(sub, title):
        if sub.empty: return f"<h3>{title}</h3><p>none</p>"
        rows = "".join(
            f"<tr><td><a href='{r.link}'>{r.tv}</a></td><td>{r.dot_bar}</td><td>{r.wt2_trough:.1f}</td>"
            f"<td>{r.wt2_now:.1f}</td><td>{r.close:.2f}</td><td>{r.zone_top:.2f}</td><td>{r.wk_wt2:.1f}</td></tr>"
            for r in sub.itertuples())
        return (f"<h3>{title} ({len(sub)})</h3><table border=1 cellpadding=4 style='border-collapse:collapse;font-size:13px'>"
                "<tr><th>Ticker</th><th>4h dot</th><th>4h trough</th><th>4h WT2 now</th><th>Close</th><th>Band top</th><th>Weekly WT2</th></tr>"
                f"{rows}</table>")
    parts = [f"<h2>Cipher B screen — {TODAY}</h2><p>{len(df)} evaluated. Rules: 4h dot in last {DOT_BARS} bars, trough ≤ {WT_TROUGH}, "
             f"close in bottom {FIB_BAND} fib band ({FIB_LEN} bars), weekly WT2 ≤ {WK_LEVEL}.</p>"]
    for b in ["FULL PASS", "WATCH: weekly+band ok, waiting on 4h dot", "NEAR: 4h+band ok, weekly shallow", "NEAR: 4h+weekly ok, above band"]:
        parts.append(table(df[df.bucket == b].sort_values(["wt2_trough", "wk_wt2"]), b))
    if enriched:
        parts.append("<h3>Company notes</h3>")
        for e in enriched:
            heads = "".join(f"<li>{h['date']} <a href='{h['url']}'>{h['title']}</a></li>" for h in e.get("headlines", []))
            parts.append(f"<h4>{e['tv']} — {e.get('name','')}</h4>"
                         f"<p><b>{e.get('sector','')} / {e.get('industry','')}</b> · ${e.get('mcap_b','?')}B · "
                         f"1m {e.get('ret_1m','?')}% · 3m {e.get('ret_3m','?')}% · {e.get('off_52w_high','?')}% off 52w high · "
                         f"next earnings {e.get('next_earnings') or 'n/a'}</p>"
                         f"<p>{e.get('summary','')}</p>"
                         + (f"<ul>{heads}</ul>" if heads else ""))
    return "\n".join(parts)

def send_mail(subject, html):
    host, user, pw, to = os.getenv("SMTP_HOST"), os.getenv("SMTP_USER"), os.getenv("SMTP_PASS"), os.getenv("MAIL_TO")
    if not all([host, user, pw, to]):
        print("mail not configured; skipping"); return
    m = MIMEMultipart("alternative"); m["Subject"], m["From"], m["To"] = subject, user, to
    m.attach(MIMEText(html, "html"))
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as s:
        s.starttls(); s.login(user, pw); s.sendmail(user, to.split(","), m.as_string())
    print("mail sent to", to)

def in_et_window(spec):
    """spec like '13:30-14:30'. GitHub cron is UTC-only, so the workflow fires twice an hour apart
    and this guard lets exactly one run proceed regardless of daylight-saving time."""
    if not spec: return True
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%H:%M")
    lo, hi = spec.split("-")
    return lo <= now <= hi

def main():
    if not in_et_window(os.getenv("ET_WINDOW", "")):
        print("outside ET window; skipping"); return
    os.makedirs(RESULTS, exist_ok=True)
    universe = load_universe(); print(f"{len(universe)} symbols")
    df = run_screen(universe)
    ok = df[df.err.isna()].copy()
    ok.to_csv(f"{RESULTS}/screen_{TODAY}.csv", index=False)
    ok.to_csv(f"{RESULTS}/screen_latest.csv", index=False)
    interesting = ok[ok.bucket != ""].copy()
    # enrich full passes and watch-list names (cap to keep the run short)
    to_enrich = interesting.sort_values(["bucket", "wt2_trough"]).head(30)
    enriched = []
    for tv in to_enrich.tv:
        e = enrich(tv)
        e["bucket"] = to_enrich.set_index("tv").loc[tv, "bucket"]; enriched.append(e)
    json.dump(enriched, open(f"{RESULTS}/enriched_{TODAY}.json", "w"), indent=1, default=str)
    json.dump(enriched, open(f"{RESULTS}/enriched_latest.json", "w"), indent=1, default=str)
    html = html_report(interesting, enriched)
    open(f"{RESULTS}/report_{TODAY}.html", "w").write(html)
    open(f"{RESULTS}/report_latest.html", "w").write(html)
    n_full = int((interesting.bucket == "FULL PASS").sum())
    print(f"full passes: {n_full}; watch/near: {len(interesting) - n_full}")
    send_mail(f"Cipher B screen {TODAY}: {n_full} full pass, {len(interesting) - n_full} watch", html)

if __name__ == "__main__":
    main()
