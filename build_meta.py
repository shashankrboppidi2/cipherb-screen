"""Precompute sector/industry/name/summary for every watchlist symbol (Yahoo blocks this endpoint
from cloud IPs, so the scheduled job reads this file instead). Re-run locally now and then."""
import glob, os, json, warnings, concurrent.futures as cf, pandas as pd, yfinance as yf
warnings.filterwarnings("ignore")
from screen import load_universe, yh
OUT = "universe_meta.csv"
prev = pd.read_csv(OUT) if os.path.exists(OUT) else pd.DataFrame(columns=["tv","sector"])
done = prev[prev.sector.notna()].set_index("tv").to_dict("index")
todo = [s for s in load_universe() if s not in done]
def one(tv):
    try:
        i = yf.Ticker(yh(tv)).info
        return dict(tv=tv, name=i.get("shortName"), sector=i.get("sector"), industry=i.get("industry"),
                    mcap_b=round((i.get("marketCap") or 0)/1e9, 1), summary=(i.get("longBusinessSummary") or "")[:400])
    except Exception as e:
        return dict(tv=tv, name=None, sector=None, industry=None, mcap_b=None, summary=None)
rows = [dict(tv=k, **v) for k, v in done.items()]
with cf.ThreadPoolExecutor(3) as ex:
    for k, r in enumerate(ex.map(one, todo), 1):
        r["tv"] = r.get("tv"); rows.append(r)
        if k % 200 == 0: pd.DataFrame(rows).to_csv(OUT, index=False); print(k, "/", len(todo), flush=True)
pd.DataFrame(rows).to_csv(OUT, index=False); print("done", len(rows))
