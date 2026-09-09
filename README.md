# Cipher B daily screen

End-of-day screen over the CORE watchlists (~2,600 symbols) for the
VuManChu Cipher B 4h + weekly buy setup, with sector/industry enrichment,
and recent headline links.

## The rule

| Gate | Condition |
|---|---|
| 4h | Big green dot (WT1 crosses above WT2 with WT2 ≤ −53) on one of the last 2 completed 4h bars, and the WT2 trough over the last 6 bars ≤ −60 |
| Zone | Last 4h close inside the bottom AutoFib band: low → low + 0.236 × (highest close − lowest close) over 265 4h bars |
| Weekly | Cipher B WT2 on the current weekly bar ≤ −60 |

4h bars are regular-session, TradingView-style (09:30–13:30 and 13:30–16:00 ET).
Every parameter is at the top of `screen.py`.

Buckets reported each day:

* **FULL PASS** — all three gates.
* **WATCH** — weekly and band satisfied, trough ≤ −60, no dot in the last 2 bars yet. One cross-up from qualifying.
* **NEAR (weekly shallow)** — 4h and band satisfied, weekly between −60 and −40.
* **NEAR (above band)** — 4h and weekly satisfied, close above the band.

## Schedule

Two runs per weekday, on your own GitHub account, no Claude login or API key needed:

| Run | ET time | What it does |
|---|---|---|
| Mid-day | ~13:40 | Full screen, right after the 09:30 4h bar closes. |
| Post-close | ~16:20 | Full screen, both 4h bars complete. The main run. |

GitHub cron is UTC-only, so each run is scheduled twice an hour apart and `screen.py`'s
`ET_WINDOW` guard lets exactly one proceed, summer or winter.

## Setup (once)

1. Create a private GitHub repo and push this folder.
2. Settings → Secrets and variables → Actions. Add:
   * `SMTP_USER`, `SMTP_PASS`, `MAIL_TO` — for the e-mailed report. For Gmail use an
     **app password** (Google Account → Security → 2-Step Verification → App passwords), not your login.
3. Actions tab → "Cipher B screen (2x daily)" → Run workflow, to test.

The schedule is `45 21 * * 1-5` (UTC): 17:45 ET in summer, 16:45 ET in winter — always after the close,
so the 13:30 4h bar is complete and nothing is evaluated on a forming bar.

## Output

Committed to `results/` on every run (and attached as a workflow artifact):

* `screen_<date>.csv` — every evaluated symbol with all gate values.
* `enriched_<date>.json` — sector, industry, market cap, 1m/3m returns, distance from 52-week high,
  next earnings date, business summary and headline links, for full passes and watch names.
  next earnings date, business summary, headlines, and the drop note, for full passes and watch names.
* `report_<date>.html` — the e-mailed report.

`screen_latest.csv` and `report_latest.html` always point at the newest run, so a MotherDuck/Metabase
job can read a stable path.

## Tuning

* Weekly gate too strict? Change `WK_LEVEL` (−60) — at −50 the NEAR bucket moves into FULL PASS.
* Missing dots that TradingView shows? Data feeds differ slightly; the dot dates agree within ±1 bar
  in testing. Verify full passes on the chart before acting.
* Preferreds and notes: add to `EXCLUDE`. Low-volatility common stocks that the heuristic
  wrongly tags go in `KEEP`.
* Watchlists: drop any TradingView watchlist export (comma-separated `EXCHANGE:SYMBOL`) into `watchlists/`.

## Known limits

* Yahoo's free data has thin news for some small caps, so the headline list may be short or empty.
  so the drop note may say the headlines don't explain the move.
* Recent IPOs with fewer than 270 4h bars are skipped until they have enough history for the 265-bar fib.
* Nothing here is a trade recommendation; the screen finds candidates for your own review.
