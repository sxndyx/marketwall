# Market Wall

A self-hosted wall display for learning how markets behave month by month: seasonality,
trend, momentum, news tone and the odds of an up move, broken down by sector. It runs on
your own computer at `http://localhost:8787` and rotates through its views on a screen.

Every number on screen is computed from price history when the data refreshes. The
"why" explanations for each seasonal pattern are the commonly cited reasons. They give
context for the stats; they are not where the stats come from.

## Run it

```bash
git clone https://github.com/sxndyx/marketwall.git
cd marketwall
pip install yfinance        # optional, recommended
python3 server.py           # then open http://localhost:8787
```

To update later: stop the server (Ctrl+C), then `git pull` and `python3 server.py` again.

Requires Python 3.9+ and nothing else (`yfinance` is optional). The first start takes a few
minutes: it fetches the daily price history for ~34 tickers, backfills 12 months of headlines
per sector and pulls 90 days of news coverage per theme from GDELT (which allows one request
every 5 seconds). After that, prices are cached for 6 hours, this month's headlines for 1 hour
and older months' headlines for a week. The server rebuilds every 60 minutes
(`--refresh 30` to change).

| Option | |
|---|---|
| `--host 0.0.0.0` | let another device (TV, tablet, Pi) on your network open `http://<this-computer>:8787` |
| `--port 8787` | port |
| `--build-only` | refresh the data once and exit (for cron) |

### On the wall

Any browser in full screen works. For a dedicated screen (old laptop, Raspberry Pi, mini PC):

```bash
chromium --kiosk --noerrdialogs --disable-infobars http://localhost:8787
```

On a Mac: open the page in Chrome and press ⌃⌘F. The cursor hides after 3 seconds.

### URL options and keys

| | |
|---|---|
| `?dwell=30` | seconds per view (default 25) |
| `?view=heatmap` | pin one view: `overview`, `heatmap`, `focus`, `almanac`, `longterm`, `news`, `actions`, `model` |
| `?view=focus&group=energy` | pin one sector (`market`, `tech`, `energy`, `mining`, `gold`, `financials`, `health`, `industrials`, `consumer`, `defensives`, `rates`) |
| `?theme=light` / `?theme=auto` | default is dark (better on a wall at night) |
| `?colors=classic` | green/red instead of the colour-blind-safe blue/red |
| ← → | previous / next view |
| space | pause rotation |
| 1–9, 0 | jump to a view (in the order listed below) |
| f | full screen |

### If the wall is empty ("0/31 series")

Python couldn't download anything. The overview and the Terminal window show the error.
The usual cause on a Mac is Python from python.org, which can't verify HTTPS certificates until
you run its certificate installer:

```bash
open "/Applications/Python 3.13/Install Certificates.command"   # use your version's folder
```

The app now falls back to the Mac's built-in `curl` when that happens, and `pip3 install certifi`
fixes it too. Restart `python3 server.py` afterwards; failed downloads aren't cached, so the next
build retries everything.

## What's on the wall

1. **Overview**: the seasonal headline for the coming months ("Historically, the S&P 500 has
   risen in Nov–Jan in X% of years since 1950…") with the reasons it's usually attributed to,
   the odds the S&P is higher over the next 1/3/6 months, one tile per sector, and upcoming
   calendar events.
2. **Market sentiment**: a fear & greed gauge (0–100) built from eight price signals, with its
   one-year history, each component, the inflection signals that are firing, and what the S&P
   did next after every past reading and signal.
3. **News & events radar**: coverage and tone for war & geopolitics, Trump & Washington, tariffs,
   the Fed, tech & AI, the economy, oil and the stock market, with spikes flagged as events.
4. **Seasonality map**: average return and % of years up for every ticker and calendar month,
   with the next three months outlined. Splits over two pages when every ticker is loaded.
5. **Sector focus** (cycles through each sector): 5-year price against its 10-month average,
   month-by-month bars, the seasonal pattern in play and its record, odds with a breakdown,
   actionables and news tone.
6. **S&P 500 month by month**: each month's average, hit rate and almanac note; this year
   against a typical year and a typical year at the same point in the presidential cycle;
   presidential-cycle returns and what followed past midterm elections.
7. **Long-term trends**: 1/3/5/10/20-year annualised returns, distance from high, worst
   drawdown, volatility, trend.
8. **Sector news tone**: headline tone by sector over 1M/3M/6M/YTD and the latest headlines.
9. **Actionables**: every sector's signals sorted into tailwinds, watch list, headwinds and risks,
   including the market-wide sentiment signals and news spikes.
10. **How the odds work**: the model, its out-of-sample test results and calibration.

The header always shows the current sentiment reading, and news spikes scroll in the ticker.

## Sectors and tickers

Edit `mw/config.py` to add or remove anything. Each group lists its tickers, the Google News
query and its seasonal patterns.

| Group | Tickers |
|---|---|
| Broad market | ^GSPC (S&P 500), IWM |
| Technology | XLK, SMH, QQQ, XLC |
| Energy | XLE, XOP, CL=F (WTI), NG=F (natural gas) |
| Mining & metals | XME, COPX, XLB, HG=F (copper) |
| Gold & precious | GDX, GC=F (gold), SI=F (silver) |
| Financials | XLF, KRE |
| Health care | XLV, XBI |
| Industrials | XLI, ITA |
| Consumer | XLY, XRT |
| Defensives | XLP, XLU |
| Real estate & rates | VNQ, TLT |

## How the numbers are made

**Seasonality**: monthly returns from month-end closes (dividend-adjusted for ETFs). For each
calendar month and each 3- and 6-month window: average, median, best, worst and the share of
years it was up. The S&P uses 1950 onwards (the usual convention); everything else uses its
full history, which for most sector ETFs starts in 1998–2006. That's only ~20–28 years, so
treat their seasonal stats as noisier than the S&P's.

**Odds of an up move**: a logistic regression pooled across all tickers, fitted on monthly data
since 1928 using only information available at each point in time:

- *base rate*: how often this ticker rose over any window of this length
- *seasonality*: how often it rose in this particular calendar window (shrunk toward the base rate)
- *trend*: price vs its 10-month average
- *momentum*: 12-month return

It is fitted on data before 2012 and tested on 2012 onwards (the "How the odds work" view shows
the results), then refitted on all years for the live numbers. Expect most of each number to be the base rate: seasonality and
trend shift it by a few points at most. Out of sample, that's usually about as much edge as
there is.

**News tone**: Google News RSS, one query per sector per calendar month (its `after:`/`before:`
operators let it backfill a year), plus yfinance's per-ticker headlines. Each headline is scored
with a small finance word list, from −1 (bearish) to +1 (bullish). "vs norm" compares the
recency-weighted tone (1M 50%, 3M 30%, 6M 20%) with the sector's own 12-month average, because
headlines skew negative in general. This tilts the odds by up to ±7 points. It isn't backtested,
because there's no free archive of historical headlines to test it on.

**Actionables** are rules on top of the stats: seasonal tailwind/headwind (coming month up
≥65% / ≤45% of years), entering the strongest 3-month window, trend (above or below the 10-month
average, with the level that would flip it), stretched (>12% above trend), correction or bear
territory against the 52-week high, sector leadership vs the S&P over 6 months, news diverging
from price, VIX extremes, and calendar events within 3 weeks.

## Sentiment and inflection

The gauge averages eight components, each scored 0–100 as a percentile against its own last
252 trading days (80 = greedier than 80% of the past year):

| Component | Reading |
|---|---|
| S&P trend | S&P 500 vs its 125-day average |
| 52-week strength | where sector ETFs sit in their 52-week range |
| Sector breadth | share of sector ETFs above their 50-day average |
| Volatility | VIX vs its 50-day average (inverted) |
| VIX curve | VIX ÷ 3-month VIX (inverted); above 1.0 is acute stress |
| Junk-bond demand | high-yield bonds (HYG) vs Treasuries (IEF), 20-day returns |
| Safe-haven demand | S&P 500 vs long Treasuries (TLT), 20-day returns |
| Risk appetite | discretionary (XLY) vs staples (XLP), 20-day change |

Zones: under 25 extreme fear, 25–45 fear, 45–55 neutral, 55–75 greed, over 75 extreme greed.

**Inflection signals** (rules in `mw/sentiment.py`): *fear washing out* (gauge was ≤20 within 10
days and has bounced 10+ points), *greed fading* (was ≥80, now ≤70), *bearish divergence* (S&P near
its high while the gauge fell 15+ points in a month), *bullish divergence* (S&P 8%+ off its high while
the gauge rose 15+ in two weeks), *VIX curve inverted* and *just normalised*, and *breadth thrust*
(sectors above their 50-day average going from ≤20% to ≥80% within 10 days).

**Verifying it**: the sentiment view shows, for every gauge zone and every signal since the data
allow (about 2007), how often the S&P was higher 1 and 3 months later and the average move, next
to the same figures for all days. Hover a dot on the S&P chart to see what followed that signal.

## News & events radar

Source: the [GDELT](https://www.gdeltproject.org/) DOC 2.0 API, which monitors news worldwide and
scores the tone of each article. For each theme in `mw/config.py` (`THEMES`) it pulls 90 days of:

- **coverage**: the theme's share of all monitored articles. "vs normal" compares the last 3 days
  with the median of the 2 months before. 2× or more is a *Spike*, 1.4× *Elevated*.
- **tone**: average article tone. The 7-day average is compared with the spread of 7-day averages
  over the previous 2 months, giving *improving*, *worsening* or *steady*.
- **headlines**: the latest articles. Google News is the fallback if GDELT is unavailable.

The **news mood index** averages each theme's tone relative to its own 90-day norm, weighted by
how much coverage the theme is getting that day. Spikes with worsening tone become *risk*
actionables on the market card. This part isn't backtested: GDELT's API only covers the last
3 months, so there's no long history to test it against.

## Data sources

1. **Yahoo Finance**, through `yfinance` if installed, otherwise its public chart API.
2. **Stooq** CSV as a backup.
3. **GitHub-hosted datasets** (datahub.io) as a last resort for a few series: S&P 500 (Robert
   Shiller's dataset, monthly *average* prices since 1871), EIA WTI and Henry Hub spot prices,
   gold and the VIX. These are real data but lag by a few weeks. Monthly averages also smooth
   out month-to-month moves, so September's weakness looks milder on them than on month-end closes.

4. **GDELT** for news coverage and tone, **Google News RSS** for sector headlines.

Yahoo's endpoints are unofficial and occasionally change. If prices stop loading, run
`pip install -U yfinance` first.

## Tests

```bash
python3 -m unittest discover -s tests
```
