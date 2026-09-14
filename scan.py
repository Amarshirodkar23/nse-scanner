"""
Weekly NSE bullish-streak scanner.

Scans the FULL NSE equity list, keeps stocks under a price cap that have
been rising for several consecutive trading days, drops any stock whose
"streak" is really just a repeated upper-circuit lock (gap up, lock,
gap up, lock -- not organic buying), and writes out only a top-20
shortlist as a simple webpage (docs/index.html) and a CSV backup.

Runs unattended on a schedule (see .github/workflows/weekly-scan.yml).
You never need to look at this file day-to-day -- just open the
published page.
"""

import io
import time
import datetime
import requests
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------- config --
MAX_PRICE = 500        # rupees
MIN_STREAK = 2          # minimum consecutive bullish days to qualify
TOP_N = 20
LOOKBACK_DAYS = "1mo"   # history window pulled per stock
BATCH_SIZE = 150        # symbols per yfinance batch download

NSE_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_HOME_URL = "https://www.nseindia.com"

# Small backup list used ONLY if the live NSE list fetch fails outright,
# so a scheduled run still produces something instead of silently dying.
FALLBACK_SYMBOLS = [
    "TATAMOTORS", "SUZLON", "IRFC", "YESBANK", "IDEA", "PNB", "BANKBARODA",
    "IOC", "ONGC", "GAIL", "NHPC", "SAIL", "RVNL", "IRCTC", "BHEL",
    "UNIONBANK", "CANBK", "FEDERALBNK", "IDFCFIRSTB", "PFC", "RECLTD",
]


# --------------------------------------------------------------- fetching --
def get_full_nse_symbol_list() -> list[str]:
    """Pull the full list of NSE-listed equity symbols.

    NSE blocks plain requests without first establishing a browser-like
    session, so we hit the homepage once to collect cookies before asking
    for the archive CSV.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/csv,application/json,text/plain,*/*",
    }
    session = requests.Session()
    session.headers.update(headers)
    try:
        session.get(NSE_HOME_URL, timeout=10)
        resp = session.get(NSE_LIST_URL, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        symbols = df["SYMBOL"].dropna().astype(str).str.strip().tolist()
        if len(symbols) > 500:  # sanity check it's really the full list
            print(f"Fetched {len(symbols)} symbols from NSE.")
            return symbols
        raise ValueError("NSE list looked too short, falling back.")
    except Exception as e:
        print(f"Could not fetch full NSE list ({e}). Using fallback list.")
        return FALLBACK_SYMBOLS


def download_history(symbols: list[str]) -> dict:
    """Batch-download recent daily OHLCV for every symbol via yfinance."""
    histories = {}
    tickers = [f"{s}.NS" for s in symbols]
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        print(f"Downloading {i + 1}-{i + len(batch)} of {len(tickers)}...")
        try:
            data = yf.download(
                batch, period=LOOKBACK_DAYS, interval="1d",
                group_by="ticker", threads=True, progress=False,
            )
        except Exception as e:
            print(f"Batch download failed ({e}), skipping batch.")
            continue

        for t in batch:
            symbol = t.replace(".NS", "")
            try:
                df = data[t] if len(batch) > 1 else data
                df = df.dropna(subset=["Close"])
                if len(df) >= 6:
                    histories[symbol] = df
            except Exception:
                continue
        time.sleep(1)  # be polite between batches
    return histories


# -------------------------------------------------------------- analysis --
def is_circuit_day(prev_close, high, low, close) -> bool:
    """Flag a day that looks like a locked upper circuit rather than
    organic trading: almost no intraday range, and the gain sits right on
    a standard NSE circuit band (2/5/10/20%)."""
    if prev_close <= 0 or close <= 0:
        return False
    day_range = (high - low) / close
    change_pct = ((close - prev_close) / prev_close) * 100
    near_band = any(abs(abs(change_pct) - b) < 0.4 for b in (2, 5, 10, 20))
    return day_range < 0.008 and near_band and change_pct > 0


def analyze(symbol: str, df: pd.DataFrame) -> dict | None:
    closes = df["Close"].tolist()
    highs = df["High"].tolist()
    lows = df["Low"].tolist()
    vols = df["Volume"].tolist()

    price = closes[-1]
    if price > MAX_PRICE:
        return None

    # consecutive up-days counting back from the latest session
    streak = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] > closes[i - 1]:
            streak += 1
        else:
            break
    if streak < MIN_STREAK:
        return None

    # circuit-staircase check over the streak window
    window = range(len(closes) - streak, len(closes))
    circuit_days = sum(
        1 for i in window if i > 0 and is_circuit_day(closes[i - 1], highs[i], lows[i], closes[i])
    )
    if circuit_days >= max(1, streak - 1):
        return None  # this is a locked staircase, not organic momentum

    day_change = ((closes[-1] - closes[-2]) / closes[-2]) * 100
    week_ref = closes[max(0, len(closes) - 6)]
    week_change = ((closes[-1] - week_ref) / week_ref) * 100
    avg_vol = sum(vols[:-1]) / max(1, len(vols) - 1)
    vol_ratio = vols[-1] / avg_vol if avg_vol else 1

    return {
        "symbol": symbol,
        "price": round(price, 2),
        "streak": streak,
        "day_change": round(day_change, 2),
        "week_change": round(week_change, 2),
        "volume": int(vols[-1]),
        "vol_ratio": round(vol_ratio, 2),
    }


# ---------------------------------------------------------------- output --
def render_html(rows: list[dict], universe_size: int, matched_before_top: int) -> str:
    generated = datetime.datetime.now().strftime("%d %b %Y, %H:%M")
    body_rows = "".join(f"""
      <tr>
        <td class="rank">{i + 1}</td>
        <td class="sym">{r['symbol']}</td>
        <td class="num">&#8377;{r['price']}</td>
        <td><span class="pill">{r['streak']}d</span></td>
        <td class="num {'up' if r['day_change'] >= 0 else 'down'}">{r['day_change']:+.2f}%</td>
        <td class="num {'up' if r['week_change'] >= 0 else 'down'}">{r['week_change']:+.2f}%</td>
        <td class="num">{r['vol_ratio']}x</td>
      </tr>""" for i, r in enumerate(rows))

    if not rows:
        body_rows = '<tr><td colspan="7" class="empty">No stocks cleared the filters this week.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Weekly NSE Bullish Shortlist</title>
<style>
  body{{font-family:'Helvetica Neue',Arial,sans-serif;background:linear-gradient(120deg,#eef3ea,#f6efe4);
       margin:0;padding:28px 24px 60px;color:#12140f;}}
  .eyebrow{{font-size:12px;font-weight:700;letter-spacing:.08em;color:#0f5c37;text-transform:uppercase;margin:0 0 8px;}}
  h1{{font-size:38px;font-weight:800;margin:0 0 6px;letter-spacing:-0.02em;}}
  .sub{{color:#5c6255;font-size:14px;margin:0 0 20px;}}
  table{{width:100%;max-width:820px;border-collapse:collapse;background:#fff;border:1px solid #d9ddd1;border-radius:12px;overflow:hidden;}}
  th{{text-align:left;font-size:11px;font-weight:700;letter-spacing:.05em;color:#5c6255;text-transform:uppercase;
      background:#e5ece0;padding:12px 14px;}}
  td{{padding:11px 14px;font-size:14px;border-top:1px solid #d9ddd1;}}
  td.num,th.num{{text-align:right;}}
  .rank{{font-weight:800;color:#5c6255;}}
  .sym{{font-weight:700;}}
  .up{{color:#1e8a4c;font-weight:700;}}
  .down{{color:#a5321f;font-weight:700;}}
  .pill{{background:#e5ece0;color:#0b4128;font-weight:700;padding:3px 9px;border-radius:20px;font-size:12px;}}
  .empty{{text-align:center;padding:30px;color:#5c6255;}}
  .footer{{max-width:820px;font-size:12px;color:#5c6255;margin-top:16px;line-height:1.6;}}
</style></head>
<body>
  <p class="eyebrow">Weekly NSE momentum scan &middot; generated {generated}</p>
  <h1>Top {len(rows)} bullish picks under &#8377;{MAX_PRICE}</h1>
  <p class="sub">Scanned {universe_size} NSE stocks &middot; {matched_before_top} matched the streak &amp; price filters before ranking &middot; circuit-staircase names removed automatically.</p>
  <table>
    <thead><tr><th>Rank</th><th>Stock</th><th class="num">Price</th><th>Streak</th>
    <th class="num">1D</th><th class="num">Week</th><th class="num">Vol vs avg</th></tr></thead>
    <tbody>{body_rows}</tbody>
  </table>
  <p class="footer">For your own screening only -- not investment advice. Check each name yourself (news, fundamentals, sector) before acting on this list.</p>
</body></html>"""


def main():
    symbols = get_full_nse_symbol_list()
    histories = download_history(symbols)
    print(f"Got usable history for {len(histories)} of {len(symbols)} symbols.")

    matches = []
    for symbol, df in histories.items():
        result = analyze(symbol, df)
        if result:
            matches.append(result)

    matches.sort(key=lambda r: (r["streak"], r["vol_ratio"], r["week_change"]), reverse=True)
    top = matches[:TOP_N]

    import os
    os.makedirs("docs", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(render_html(top, len(symbols), len(matches)))

    pd.DataFrame(top).to_csv("data/latest_top20.csv", index=False)
    print(f"Done. {len(top)} stocks written to docs/index.html")


if __name__ == "__main__":
    main()
