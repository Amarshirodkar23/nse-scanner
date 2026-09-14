# Weekly NSE Bullish Shortlist

Runs itself once a week, scans every NSE-listed stock, keeps names under
₹500 that have risen for 2+ straight trading days, drops fake "staircase"
patterns caused by repeated circuit locks, and publishes just the top 20
as a simple webpage. You never run anything by hand.

## One-time setup (10 minutes)

1. **Create a GitHub account** if you don't have one (free) — github.com.
2. **Create a new repository** — name it anything, e.g. `nse-scanner`. Keep it Public (required for free GitHub Pages).
3. **Upload these files** into that repository, keeping the folder structure exactly as given (the `.github/workflows/weekly-scan.yml` path matters — GitHub only picks up workflows from that exact location).
4. **Turn on GitHub Pages**: Settings → Pages → under "Build and deployment", set Source = "Deploy from a branch", Branch = `main`, Folder = `/docs`. Save.
5. **Run it once manually** to seed the page: go to the Actions tab → "Weekly NSE bullish scan" → Run workflow. Wait a couple of minutes.
6. Your shortlist is now live at: `https://<your-github-username>.github.io/<repo-name>/`
   Bookmark that link — that's the only thing you'll ever need to open.

After that, it re-scans and re-publishes automatically every Monday morning (IST). No API keys, no server, no cost.

## Adjusting the filters

Open `scan.py` and change the numbers near the top:

```python
MAX_PRICE = 500     # price ceiling in rupees
MIN_STREAK = 2       # minimum consecutive up-days to qualify
TOP_N = 20            # how many stocks to show
```

Commit the change — next scheduled run (or a manual "Run workflow") picks it up.

## What it is and isn't

- It's a screening tool: it narrows ~2,000 stocks down to a short list worth *looking at*.
- It is **not** investment advice. Always check the news, fundamentals, and sector context on any name yourself before acting on it.
- The circuit-staircase filter is a heuristic (tight trading range + gain near a standard 2/5/10/20% circuit band) — very good at catching repeated lock patterns, but not a substitute for reading the actual news behind a move.
