"""Price history: Yahoo Finance first (via yfinance if installed, else its chart API),
then Stooq, then real datasets mirrored on GitHub for the few symbols they cover.

Every series is normalised to:
  {"monthly": [["YYYY-MM", close], ...], "daily": [["YYYY-MM-DD", close], ...],
   "source": "...", "monthly_kind": "close" | "average", "partial_month": "YYYY-MM" | None}
"""
import csv
import datetime as dt
import io
import json
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
TIMEOUT = 20

GITHUB = "https://raw.githubusercontent.com/datasets"
FALLBACKS = {
    # S&P 500 monthly from Robert Shiller's dataset (prices are monthly averages of daily closes)
    "sp500_shiller": (f"{GITHUB}/s-and-p-500/main/data/data.csv", "Date", "SP500", "monthly_avg",
                      "Shiller S&P 500 dataset via datahub.io (monthly average prices)"),
    "wti_daily": (f"{GITHUB}/oil-prices/main/data/wti-daily.csv", "Date", "Price", "daily",
                  "EIA WTI spot via datahub.io"),
    "natgas_daily": (f"{GITHUB}/natural-gas/main/data/daily.csv", "Date", "Price", "daily",
                     "EIA Henry Hub spot via datahub.io"),
    "gold_monthly": (f"{GITHUB}/gold-prices/main/data/monthly.csv", "Date", "Price", "monthly_avg",
                     "Gold monthly average via datahub.io"),
    "vix_daily": (f"{GITHUB}/finance-vix/main/data/vix-daily.csv", "DATE", "CLOSE", "daily",
                  "CBOE VIX via datahub.io"),
}


DAILY_FROM = "1999-01-01"  # daily closes kept from here (sentiment backtest); monthly history goes further back


class FetchError(Exception):
    pass


def _ssl_context():
    try:
        import certifi  # installed alongside yfinance/requests
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_CTX = _ssl_context()


def _curl(url, accept):
    r = subprocess.run(["curl", "-sSfL", "--max-time", str(TIMEOUT), "-A", UA, "-H", f"Accept: {accept}", url],
                       capture_output=True, timeout=TIMEOUT + 5)
    if r.returncode:
        raise FetchError(f"curl: {r.stderr.decode(errors='replace').strip()[:160]}")
    return r.stdout.decode("utf-8", errors="replace")


def http_get(url, accept="*/*"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
            return r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, ssl.SSLError) as e:
        # Python from python.org on macOS ships without CA certificates until you run its
        # "Install Certificates.command"; the system curl uses the Keychain, so try that.
        if isinstance(getattr(e, "reason", e), ssl.SSLError) and shutil.which("curl"):
            return _curl(url, accept)
        raise


def diagnose(errors):
    """One-line, human-readable reason when downloads fail."""
    t = " ".join(errors)
    if "CERTIFICATE_VERIFY_FAILED" in t or "SSLCertVerification" in t or "SSL certificate" in t:
        return ("Python can't verify HTTPS certificates. On a Mac with Python from python.org, run "
                "'Install Certificates.command' in /Applications/Python 3.x (or: pip3 install certifi), then restart.")
    if "Too Many Requests" in t or "429" in t:
        return "Yahoo is rate-limiting this connection; it retries on the next refresh. pip3 install yfinance usually avoids it."
    if "Tunnel connection failed" in t or "403" in t:
        return "A proxy or firewall is blocking these sites for Python."
    if any(x in t for x in ("nodename nor servname", "Name or service not known", "getaddrinfo", "timed out",
                            "Network is unreachable", "Could not resolve")):
        return "Python couldn't reach the internet (DNS failure or timeout)."
    return ""


def _month(d):
    return d[:7]


def daily_to_monthly(daily):
    """Last close of each month."""
    out = {}
    for d, c in daily:
        out[_month(d)] = c
    return sorted(out.items())


def _clean(rows):
    """Sort, drop NaN/None/non-positive, dedupe on date keeping the last value."""
    seen = {}
    for d, c in rows:
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if c != c or c <= 0:
            continue
        seen[d] = c
    return sorted(seen.items())


def _finish(monthly, daily, source, kind):
    monthly = _clean(monthly)
    daily = _clean(daily)
    if not monthly and daily:
        monthly = daily_to_monthly(daily)
    if not monthly:
        raise FetchError("empty series")
    this_month = dt.date.today().strftime("%Y-%m")
    partial = monthly[-1][0] if monthly[-1][0] == this_month else None
    if not partial and daily and daily[-1][0][:7] == monthly[-1][0]:
        last = dt.date.fromisoformat(daily[-1][0])
        month_end = (last.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
        if (month_end - last).days > 3:  # dataset stops mid-month
            partial = monthly[-1][0]
    return {"monthly": [list(x) for x in monthly], "daily": [list(x) for x in daily],
            "source": source, "monthly_kind": kind, "partial_month": partial}


# ---------------------------------------------------------------- Yahoo

def _yahoo_yfinance(sym):
    import yfinance as yf  # optional dependency
    t = yf.Ticker(sym)
    m = t.history(period="max", interval="1mo", auto_adjust=True)
    d = t.history(period="max", interval="1d", auto_adjust=True)
    if d is None or d.empty:
        raise FetchError("yfinance returned no data")
    monthly = [(ix.strftime("%Y-%m"), float(c)) for ix, c in m["Close"].items()] if m is not None else []
    daily = [(ix.strftime("%Y-%m-%d"), float(c)) for ix, c in d["Close"].items()]
    return monthly, daily


def _merge(monthly, daily):
    """Month-end closes from the full daily history, extended back with monthly bars if those start earlier."""
    daily = _clean(daily)
    from_daily = daily_to_monthly(daily)
    first = from_daily[0][0] if from_daily else "9999"
    return [r for r in _clean(monthly) if r[0] < first] + from_daily, [r for r in daily if r[0] >= DAILY_FROM]


def _yahoo_chart(sym, rng, interval):
    q = urllib.parse.urlencode({"range": rng, "interval": interval, "includeAdjustedClose": "true",
                                "events": "div,splits"})
    last = None
    for host in ("query1", "query2"):
        try:
            raw = http_get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?{q}",
                           "application/json")
            res = json.loads(raw)["chart"]["result"][0]
            break
        except Exception as e:  # noqa: BLE001 - try the other host
            last = e
    else:
        raise FetchError(f"yahoo chart: {last}")
    ts = res.get("timestamp") or []
    off = res.get("meta", {}).get("gmtoffset", 0)
    ind = res["indicators"]
    closes = (ind.get("adjclose") or [{}])[0].get("adjclose") or ind["quote"][0]["close"]
    rows = []
    for t, c in zip(ts, closes):
        day = dt.datetime.fromtimestamp(t + off, dt.timezone.utc).strftime("%Y-%m-%d")
        rows.append((day if interval == "1d" else day[:7], c))
    return rows


def fetch_yahoo(sym):
    try:
        monthly, daily = _merge(*_yahoo_yfinance(sym))
        return _finish(monthly, daily, "Yahoo Finance (yfinance)", "close")
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 - fall through to the raw chart API
        pass
    monthly, daily = _merge(_yahoo_chart(sym, "max", "1mo"), _yahoo_chart(sym, "max", "1d"))
    return _finish(monthly, daily, "Yahoo Finance", "close")


# ---------------------------------------------------------------- Stooq

STOOQ_SYMBOLS = {"^GSPC": "^spx", "^VIX": None, "CL=F": "cl.f", "NG=F": "ng.f", "GC=F": "gc.f",
                 "SI=F": "si.f", "HG=F": "hg.f"}


def fetch_stooq(sym):
    s = STOOQ_SYMBOLS.get(sym, sym.lower() + ".us")
    if not s:
        raise FetchError("no stooq symbol")

    def get(interval):
        raw = http_get(f"https://stooq.com/q/d/l/?s={urllib.parse.quote(s)}&i={interval}")
        rows = list(csv.DictReader(io.StringIO(raw)))
        if not rows or "Close" not in rows[0]:
            raise FetchError("stooq: no data")
        return [(r["Date"], r["Close"]) for r in rows]

    monthly = [(d[:7], c) for d, c in get("m")]
    daily = [r for r in get("d") if r[0] >= DAILY_FROM]
    return _finish(monthly, daily, "Stooq", "close")


# ---------------------------------------------------------------- GitHub datasets

def fetch_fallback(key):
    url, dcol, vcol, shape, label = FALLBACKS[key]
    rows = list(csv.DictReader(io.StringIO(http_get(url))))
    pairs = [(r[dcol], r[vcol]) for r in rows if r.get(vcol) not in (None, "", "0", "0.0")]
    if shape == "daily":
        daily = _clean([(d[:10], v) for d, v in pairs])
        return _finish(daily_to_monthly(daily), [r for r in daily if r[0] >= DAILY_FROM], label, "close")
    monthly = [(d[:7], v) for d, v in pairs]
    return _finish(monthly, [], label, "average")


def fetch_instrument(sym, meta, log, sink=None):
    errors = []
    for name, fn in (("yahoo", lambda: fetch_yahoo(sym)), ("stooq", lambda: fetch_stooq(sym))):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:120]}")
    if meta.get("fallback"):
        try:
            data = fetch_fallback(meta["fallback"])
            data["fallback_reason"] = "; ".join(errors)
            return data
        except Exception as e:  # noqa: BLE001
            errors.append(f"github: {type(e).__name__}: {str(e)[:120]}")
    log(f"{sym}: no data ({' | '.join(errors)})")
    if sink is not None:
        sink.append(f"{sym}: {errors[0]}")
    return None


def fetch_all(instruments, cache_dir, max_age_h=6, log=print, errors=None):
    """Fetch every instrument, reusing cached copies younger than max_age_h."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for sym, meta in instruments.items():
        path = cache_dir / ("px3_" + "".join(ch if ch.isalnum() else "_" for ch in sym) + ".json")
        if path.exists() and time.time() - path.stat().st_mtime < max_age_h * 3600:
            out[sym] = json.loads(path.read_text())
            continue
        data = fetch_instrument(sym, meta, log, errors)
        if data:
            path.write_text(json.dumps(data))
            out[sym] = data
        elif path.exists():  # stale beats nothing
            out[sym] = json.loads(path.read_text()) | {"stale": True}
        time.sleep(0.25)
    return out
