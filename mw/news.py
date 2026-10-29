"""Headline sentiment per sector.

Headlines come from Google News RSS, one query per sector per calendar month (Google News
supports after:/before: operators, so past months can be backfilled), plus the latest
per-ticker headlines from yfinance when it is installed. Each headline is scored with a
small finance lexicon; scores are averaged over 1M / 3M / 6M / YTD windows.

The lexicon is deliberately simple and transparent: it reads tone, not meaning
("oil prices jump" scores positive even though it hurts airlines).
"""
import datetime as dt
import email.utils
import json
import math
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET

from .fetch import http_get

PHRASES = {
    "all-time high": 2.5, "record high": 2.5, "record highs": 2.5, "bull market": 2, "rate cut": 1.5,
    "rate cuts": 1.5, "cuts rates": 1.5, "beats estimates": 2, "tops estimates": 2, "raises guidance": 2.5,
    "raises outlook": 2.5, "strong demand": 2, "short squeeze": 1, "dividend hike": 2, "soft landing": 1.5,
    "sell-off": -2, "selloff": -2, "bear market": -2.5, "rate hike": -1.5, "rate hikes": -1.5,
    "raises rates": -1.5, "misses estimates": -2, "profit warning": -3, "cuts guidance": -2.5,
    "lowers guidance": -2.5, "cuts outlook": -2.5, "trade war": -2, "job cuts": -2, "cuts jobs": -2,
    "weak demand": -2, "supply glut": -2, "price war": -1.5, "hard landing": -2, "worst day": -2.5,
    "best day": 2.5, "worst week": -2, "best week": 2, "record low": -2, "52-week low": -1.5,
    "52-week high": 1.5, "death cross": -1.5, "golden cross": 1.5,
}

WORDS = {
    # positive
    "surge": 2, "surges": 2, "surged": 2, "soar": 2.5, "soars": 2.5, "soared": 2.5, "jump": 1.5,
    "jumps": 1.5, "jumped": 1.5, "rally": 2, "rallies": 2, "rallied": 2, "gain": 1, "gains": 1,
    "gained": 1, "rise": 1, "rises": 1, "rose": 1, "rising": 1, "climb": 1, "climbs": 1, "climbed": 1,
    "beat": 1.5, "beats": 1.5, "upbeat": 2, "strong": 1, "stronger": 1, "strength": 1, "boost": 1.5,
    "boosts": 1.5, "boosted": 1.5, "upgrade": 2, "upgrades": 2, "upgraded": 2, "bullish": 2,
    "optimism": 2, "optimistic": 2, "rebound": 1.5, "rebounds": 1.5, "recovery": 1, "recovers": 1,
    "outperform": 1.5, "outperforms": 1.5, "growth": 1, "expands": 1, "expansion": 1, "profit": 1,
    "profits": 1, "record": 1, "tops": 1, "higher": 1, "boom": 2, "booming": 2, "robust": 1.5,
    "accelerates": 1, "approval": 1, "approves": 1, "approved": 1, "wins": 1, "breakthrough": 2,
    "buyback": 1, "easing": 1, "stimulus": 1, "advance": 1, "advances": 1, "upside": 1, "best": 1,
    "resilient": 1.5, "momentum": 0.5, "inflows": 1,
    # negative
    "plunge": -3, "plunges": -3, "plunged": -3, "plummet": -3, "plummets": -3, "tumble": -2,
    "tumbles": -2, "tumbled": -2, "slump": -2, "slumps": -2, "slumped": -2, "sink": -2, "sinks": -2,
    "sank": -2, "fall": -1, "falls": -1, "fell": -1, "falling": -1, "drop": -1, "drops": -1,
    "dropped": -1, "decline": -1, "declines": -1, "declined": -1, "slide": -1.5, "slides": -1.5,
    "slid": -1.5, "loss": -1, "losses": -1, "loses": -1, "crash": -3, "crashes": -3, "rout": -3,
    "bearish": -2, "fear": -2, "fears": -2, "worry": -1.5, "worries": -1.5, "concern": -1,
    "concerns": -1, "warn": -2, "warns": -2, "warning": -2, "downgrade": -2, "downgrades": -2,
    "downgraded": -2, "miss": -1.5, "misses": -1.5, "missed": -1.5, "weak": -1.5, "weaker": -1.5,
    "weakness": -1.5, "layoffs": -2, "layoff": -2, "lawsuit": -1, "probe": -1, "investigation": -1,
    "fraud": -3, "bankruptcy": -3, "bankrupt": -3, "default": -2, "recession": -2, "slowdown": -2,
    "slowing": -1, "tariff": -1, "tariffs": -1, "sanctions": -1, "volatility": -1, "volatile": -1,
    "uncertainty": -1.5, "turmoil": -2, "crisis": -2.5, "glut": -2, "oversupply": -2, "lower": -1,
    "lowest": -1.5, "worst": -2, "risk": -0.5, "risks": -0.5, "cut": -0.5, "cuts": -0.5,
    "shutdown": -1.5, "outflows": -1, "headwinds": -1.5, "downside": -1, "bubble": -1.5,
    "selloffs": -2, "slashes": -1.5, "halts": -1, "plunging": -3, "sliding": -1.5,
}

NEGATORS = {"not", "no", "never", "without", "isn't", "won't", "doesn't", "didn't", "can't", "fails", "failed"}
_tok = re.compile(r"[a-z0-9][a-z0-9'\-]*")


def score_headline(text):
    t = text.lower()
    total = 0.0
    for p, w in PHRASES.items():
        if p in t:
            total += w
            t = t.replace(p, " ")
    toks = _tok.findall(t)
    for i, w in enumerate(toks):
        if w in WORDS:
            s = WORDS[w]
            if any(x in NEGATORS for x in toks[max(0, i - 3):i]):
                s = -s * 0.7
            total += s
    return math.tanh(total / 2.5)


def _strip_source(title):
    # Google News titles end in " - Publisher"
    return re.sub(r"\s+-\s+[^-]{2,60}$", "", title).strip()


def _month_bounds(today, k):
    """First day of the month k months ago and first day of the following month."""
    y, m = today.year, today.month - k
    while m <= 0:
        m += 12
        y -= 1
    start = dt.date(y, m, 1)
    end = dt.date(y + (m == 12), m % 12 + 1, 1)
    return start, end


def google_news(query, start, end):
    q = f"{query} after:{start.isoformat()} before:{end.isoformat()}"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    root = ET.fromstring(http_get(url, "application/rss+xml"))
    items = []
    for it in root.iter("item"):
        title = it.findtext("title") or ""
        pub = it.findtext("pubDate")
        try:
            d = email.utils.parsedate_to_datetime(pub).date().isoformat()
        except Exception:  # noqa: BLE001
            continue
        src = it.find("source")
        items.append({"title": _strip_source(title), "date": d, "link": it.findtext("link"),
                      "source": src.text if src is not None else ""})
    return items


def yfinance_news(syms):
    try:
        import yfinance as yf
    except ImportError:
        return []
    out = []
    for s in syms:
        try:
            for n in yf.Ticker(s).news or []:
                c = n.get("content", n)
                title = c.get("title")
                when = c.get("pubDate") or c.get("displayTime")
                if when:
                    d = when[:10]
                elif n.get("providerPublishTime"):
                    d = dt.datetime.fromtimestamp(n["providerPublishTime"], dt.timezone.utc).date().isoformat()
                else:
                    continue
                prov = c.get("provider") or {}
                link = (c.get("canonicalUrl") or {}).get("url") or n.get("link")
                if title:
                    out.append({"title": title, "date": d, "link": link,
                                "source": prov.get("displayName") or n.get("publisher", "Yahoo Finance")})
        except Exception:  # noqa: BLE001
            continue
    return out


def _window_stats(items, since):
    xs = [i["score"] for i in items if i["date"] >= since]
    if not xs:
        return None
    n = len(xs)
    return {"n": n, "mean": round(sum(xs) / n, 3),
            "pos": round(sum(x > 0.15 for x in xs) / n, 3), "neg": round(sum(x < -0.15 for x in xs) / n, 3)}


def collect(groups, cache_dir, months=12, log=print, today=None, errors=None):
    """Return {group_id: {...}} with windowed sentiment and recent headlines."""
    today = today or dt.date.today()
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    failures = 0
    for g in groups:
        items = []
        for k in range(months):
            start, end = _month_bounds(today, k)
            path = cache_dir / f"news_{g['id']}_{start:%Y-%m}.json"
            # past months rarely change: refresh weekly; this month: hourly
            max_age = 3600 if k == 0 else 7 * 86400
            if path.exists() and time.time() - path.stat().st_mtime < max_age:
                items += json.loads(path.read_text())
                continue
            if failures >= 3:  # network clearly down - don't hammer
                if path.exists():
                    items += json.loads(path.read_text())
                continue
            try:
                got = google_news(g["news"], start, min(end, today + dt.timedelta(days=1)))
                if not got and k == 0 and errors is not None:
                    errors.append(f"news: Google News returned no headlines for {g['news']}")
                path.write_text(json.dumps(got))
                items += got
                time.sleep(0.6)
            except Exception as e:  # noqa: BLE001
                failures += 1
                log(f"news {g['id']} {start:%Y-%m}: {type(e).__name__}: {str(e)[:100]}")
                if errors is not None:
                    errors.append(f"news: {type(e).__name__}: {str(e)[:120]}")
                if path.exists():
                    items += json.loads(path.read_text())
        items += yfinance_news(g["members"][:2])
        seen, uniq = set(), []
        for i in items:
            key = re.sub(r"\W+", "", i["title"].lower())[:80]
            if key and key not in seen:
                seen.add(key)
                i["score"] = round(score_headline(i["title"]), 3)
                uniq.append(i)
        if failures < 3:
            log(f"sector headlines: {g.get('name', g['id'])} ({len(uniq)})")
        if not uniq:
            continue
        uniq.sort(key=lambda i: i["date"], reverse=True)
        d = lambda days: (today - dt.timedelta(days=days)).isoformat()  # noqa: E731
        windows = {"1M": _window_stats(uniq, d(30)), "3M": _window_stats(uniq, d(91)),
                   "6M": _window_stats(uniq, d(182)), "YTD": _window_stats(uniq, f"{today.year}-01-01"),
                   "12M": _window_stats(uniq, d(365))}
        monthly = []
        for k in range(months - 1, -1, -1):
            start, end = _month_bounds(today, k)
            xs = [i["score"] for i in uniq if start.isoformat() <= i["date"] < end.isoformat()]
            monthly.append([f"{start:%Y-%m}", round(sum(xs) / len(xs), 3) if xs else None, len(xs)])
        recent = [i for i in uniq if i["date"] >= d(30)]
        out[g["id"]] = {
            "windows": windows,
            "monthly": monthly,
            "latest": uniq[:8],
            "most_positive": sorted(recent, key=lambda i: -i["score"])[:3],
            "most_negative": sorted(recent, key=lambda i: i["score"])[:3],
        }
    return out


def tilt(news):
    """Recency-weighted sentiment versus the sector's own 12-month baseline, in [-1, 1].

    Headlines skew negative in general, so the tilt measures whether tone is better or worse
    than usual for this sector rather than its absolute level."""
    if not news:
        return None
    w = news["windows"]
    base = (w.get("12M") or {}).get("mean")
    parts = [(w.get("1M"), 0.5), (w.get("3M"), 0.3), (w.get("6M"), 0.2)]
    num = sum(x["mean"] * wt for x, wt in parts if x)
    den = sum(wt for x, wt in parts if x)
    if not den or base is None:
        return None
    return max(-1.0, min(1.0, (num / den - base) * 4))
