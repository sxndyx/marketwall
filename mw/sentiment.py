"""Market sentiment gauge built from prices: 0 = extreme fear, 100 = extreme greed.

Eight components, each scored as a percentile against its own trailing year (so 80 means
"greedier than 80% of the last 252 trading days"). The gauge is their average. Inflection
signals are rules on the gauge, breadth and the VIX curve, and every reading and signal is
backtested against what the S&P 500 did over the following 1 and 3 months.
"""
import bisect
import statistics as st
from collections import deque

START = "2000-01-01"

COMPONENTS = [
    ("momentum", "S&P trend", "S&P 500 vs its 125-day average"),
    ("strength", "52-week strength", "Where sector ETFs sit in their 52-week range"),
    ("breadth", "Sector breadth", "Share of sector ETFs above their 50-day average"),
    ("volatility", "Volatility", "VIX vs its 50-day average (higher VIX = more fear)"),
    ("term", "VIX curve", "VIX vs 3-month VIX; above 1.0 means acute stress"),
    ("junk", "Junk-bond demand", "High-yield bonds (HYG) vs Treasuries (IEF), 20 days"),
    ("haven", "Safe-haven demand", "S&P 500 vs long Treasuries (TLT), 20 days"),
    ("appetite", "Risk appetite", "Discretionary (XLY) vs staples (XLP), 20 days"),
]

ZONES = [(25, "Extreme fear"), (45, "Fear"), (55, "Neutral"), (75, "Greed"), (101, "Extreme greed")]


def zone(v):
    if v is None:
        return None
    return next(name for cap, name in ZONES if v < cap)


# ---------------------------------------------------------------- rolling helpers (None only at the start)

def align(daily, dates):
    """Forward-fill a [(date, close)] series onto the master dates; None before it starts."""
    out, j, last = [], 0, None
    for d in dates:
        while j < len(daily) and daily[j][0] <= d:
            last = daily[j][1]
            j += 1
        out.append(last)
    return out


def rmean(a, n):
    out, s, q = [None] * len(a), 0.0, deque()
    for i, v in enumerate(a):
        if v is None:
            s, q = 0.0, deque()
            continue
        q.append(v)
        s += v
        if len(q) > n:
            s -= q.popleft()
        if len(q) == n:
            out[i] = s / n
    return out


def rext(a, n, fn):
    """Rolling max (fn=max) or min over n values using a monotonic deque."""
    out, q = [None] * len(a), deque()
    better = (lambda x, y: x >= y) if fn is max else (lambda x, y: x <= y)
    for i, v in enumerate(a):
        if v is None:
            q.clear()
            continue
        while q and better(v, a[q[-1]]):
            q.pop()
        q.append(i)
        if q[0] <= i - n:
            q.popleft()
        out[i] = a[q[0]]
    return out


def chg(a, n):
    return [a[i] / a[i - n] - 1 if i >= n and a[i] is not None and a[i - n] else None for i in range(len(a))]


def rpct(a, w=252, minp=126):
    """Percentile (0-100) of each value within its trailing w values."""
    out, q, win = [None] * len(a), deque(), []
    for i, v in enumerate(a):
        if v is None:
            continue
        q.append(v)
        bisect.insort(win, v)
        if len(q) > w:
            win.pop(bisect.bisect_left(win, q.popleft()))
        if len(q) >= minp:
            lo, hi = bisect.bisect_left(win, v), bisect.bisect_right(win, v)
            out[i] = 100 * (lo + hi - 1) / 2 / (len(win) - 1)
    return out


# ---------------------------------------------------------------- the gauge

def compute(daily, sector_syms):
    """daily: {sym: [(date, close)]}. Returns None when the S&P or too few inputs are missing."""
    spx_daily = daily.get("^GSPC") or daily.get("SPY")
    if not spx_daily or len(spx_daily) < 400:
        return None
    dates = [d for d, _ in spx_daily if d >= START]
    A = {s: align(v, dates) for s, v in daily.items() if v}
    spx = A.get("^GSPC") or A["SPY"]
    n = len(dates)
    raw = {}

    ma125 = rmean(spx, 125)
    raw["momentum"] = [spx[i] / ma125[i] - 1 if ma125[i] else None for i in range(n)]

    secs = [s for s in sector_syms if s in A]
    pos, above = [], []
    for s in secs:
        c, hi, lo, ma = A[s], rext(A[s], 252, max), rext(A[s], 252, min), rmean(A[s], 50)
        pos.append([(c[i] - lo[i]) / (hi[i] - lo[i]) if c[i] is not None and hi[i] != lo[i] else None for i in range(n)])
        above.append([(1.0 if c[i] > ma[i] else 0.0) if ma[i] else None for i in range(n)])

    def across(rows, need=5):
        out = []
        for i in range(n):
            xs = [r[i] for r in rows if r[i] is not None]
            out.append(st.fmean(xs) if len(xs) >= need else None)
        return out
    raw["strength"] = across(pos)
    breadth = across(above)
    raw["breadth"] = breadth

    vix = A.get("^VIX")
    if vix:
        ma = rmean(vix, 50)
        raw["volatility"] = [-(vix[i] / ma[i] - 1) if ma[i] else None for i in range(n)]
    vix3 = A.get("^VIX3M")
    curve = [vix[i] / vix3[i] if vix and vix3 and vix[i] and vix3[i] else None for i in range(n)]
    if any(c is not None for c in curve):
        raw["term"] = [-c if c is not None else None for c in curve]

    def gap(a, b):
        ra, rb = chg(a, 20), chg(b, 20)
        return [ra[i] - rb[i] if ra[i] is not None and rb[i] is not None else None for i in range(n)]
    if A.get("HYG") and A.get("IEF"):
        raw["junk"] = gap(A["HYG"], A["IEF"])
    if A.get("TLT"):
        raw["haven"] = gap(spx, A["TLT"])
    if A.get("XLY") and A.get("XLP"):
        ratio = [A["XLY"][i] / A["XLP"][i] if A["XLY"][i] and A["XLP"][i] else None for i in range(n)]
        raw["appetite"] = chg(ratio, 20)

    scores = {k: rpct(v) for k, v in raw.items()}
    gauge = []
    for i in range(n):
        xs = [s[i] for s in scores.values() if s[i] is not None]
        gauge.append(st.fmean(xs) if len(xs) >= 4 else None)
    if gauge[-1] is None:
        return None

    hi252 = rext(spx, 252, max)
    fwd = {h: [spx[i + h] / spx[i] - 1 if i + h < n else None for i in range(n)] for h in (21, 63)}
    sig = signal_flags(gauge, breadth, curve, spx, hi252)
    return {
        "dates": dates, "spx": spx, "gauge": gauge, "raw": raw, "scores": scores, "breadth": breadth,
        "curve": curve, "hi252": hi252, "fwd": fwd, "signals": sig, "vix": vix, "vix3": vix3, "A": A,
        "sectors": secs,
    }


# ---------------------------------------------------------------- inflection signals

SIGNALS = {
    "washout": ("tailwind", "Fear washing out",
                "Gauge was in extreme fear (≤20) within 10 days and has bounced 10+ points: a classic bottoming pattern"),
    "greed_fade": ("headwind", "Greed fading",
                   "Gauge was in extreme greed (≥80) within 10 days and has dropped below 70: momentum tiring"),
    "bear_div": ("risk", "Bearish divergence",
                 "S&P within 2% of its 52-week high while the gauge fell 15+ points in a month: a narrowing rally"),
    "bull_div": ("watch", "Bullish divergence",
                 "S&P 8%+ below its high while the gauge rose 15+ points in two weeks: sentiment turning before price"),
    "curve_inverted": ("risk", "VIX curve inverted",
                       "Near-term fear above 3-month fear: acute stress, typical of sell-off climaxes"),
    "curve_normalised": ("tailwind", "VIX curve just normalised",
                         "The VIX curve was inverted within 10 days and is back below 0.95: stress easing"),
    "breadth_thrust": ("tailwind", "Breadth thrust",
                       "Sectors above their 50-day average went from ≤20% to ≥80% within 10 days: broad buying"),
}


def signal_flags(g, breadth, curve, spx, hi252):
    n = len(g)
    flags = {k: [False] * n for k in SIGNALS}
    for i in range(25, n):
        v = g[i]
        if v is None:
            continue
        w10 = [x for x in g[i - 10:i] if x is not None]
        if w10 and min(w10) <= 20 and v >= 25 and g[i - 5] is not None and v - g[i - 5] >= 10:
            flags["washout"][i] = True
        if w10 and max(w10) >= 80 and v <= 70:
            flags["greed_fade"][i] = True
        if hi252[i] and spx[i] >= hi252[i] * 0.98 and g[i - 21] is not None and g[i - 21] - v >= 15:
            flags["bear_div"][i] = True
        if hi252[i] and spx[i] <= hi252[i] * 0.92 and g[i - 10] is not None and v - g[i - 10] >= 15:
            flags["bull_div"][i] = True
        c = curve[i]
        if c is not None:
            if c > 1.0:
                flags["curve_inverted"][i] = True
            recent = [x for x in curve[i - 10:i] if x is not None]
            if c < 0.95 and recent and max(recent) > 1.0:
                flags["curve_normalised"][i] = True
        b10 = [x for x in breadth[i - 10:i] if x is not None]
        if breadth[i] is not None and b10 and min(b10) <= 0.2 and breadth[i] >= 0.8:
            flags["breadth_thrust"][i] = True
    return flags


def events(flag, cooldown=20):
    """First day of each signal episode, ignoring re-triggers within `cooldown` days."""
    out, last = [], -10 ** 9
    for i, f in enumerate(flag):
        if f and i - last > cooldown:
            out.append(i)
        if f:
            last = i
    return out


def _summ(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return {"n": len(xs), "up": round(sum(x > 0 for x in xs) / len(xs), 4), "avg": round(st.fmean(xs), 4),
            "median": round(st.median(xs), 4)}


# ---------------------------------------------------------------- output for the display

def summarize(r, days=260):
    if not r:
        return None
    dates, g, spx, n = r["dates"], r["gauge"], r["spx"], len(r["dates"])
    i = n - 1
    v = g[i]
    back = lambda k: g[i - k] if i >= k and g[i - k] is not None else None  # noqa: E731

    def txt(key):
        A = r["A"]
        x = r["raw"][key][i]
        if x is None:
            return ""
        if key == "momentum":
            return f"{x * 100:+.1f}% vs 125-day avg"
        if key == "strength":
            return f"sectors at {x * 100:.0f}% of their 52-week range"
        if key == "breadth":
            k = round(x * len(r["sectors"]))
            return f"{k} of {len(r['sectors'])} sectors above 50-day avg"
        if key == "volatility":
            return f"VIX {r['vix'][i]:.1f} ({-x * 100:+.0f}% vs 50-day avg)"
        if key == "term":
            return f"VIX/VIX3M {-x:.2f}"
        if key == "junk":
            return f"HYG {x * 100:+.1f}% vs IEF over 20 days"
        if key == "haven":
            return f"S&P {x * 100:+.1f}% vs TLT over 20 days"
        if key == "appetite":
            return f"XLY/XLP {x * 100:+.1f}% over 20 days"
        return f"{x:.3f}" if A else ""

    comps = []
    for key, name, desc in COMPONENTS:
        s = r["scores"].get(key)
        if s is None or s[i] is None:
            comps.append({"id": key, "name": name, "desc": desc, "score": None, "text": "no data"})
        else:
            comps.append({"id": key, "name": name, "desc": desc, "score": round(s[i], 1), "text": txt(key),
                          "chg_1m": round(s[i] - s[i - 21], 1) if i >= 21 and s[i - 21] is not None else None})

    # what the S&P did next, by gauge zone (overlapping windows: every trading day counts)
    by_zone = []
    valid = [k for k in range(n) if g[k] is not None]
    for _, name in ZONES:
        idx = [k for k in valid if zone(g[k]) == name]
        by_zone.append({"zone": name, "days": len(idx), "m1": _summ(r["fwd"][21][k] for k in idx),
                        "m3": _summ(r["fwd"][63][k] for k in idx), "current": zone(v) == name})
    base = {"days": len(valid), "m1": _summ(r["fwd"][21][k] for k in valid), "m3": _summ(r["fwd"][63][k] for k in valid)}

    sig_out, history = [], []
    for key, (kind, title, why) in SIGNALS.items():
        ev = events(r["signals"][key])
        res = _summ(r["fwd"][63][k] for k in ev)
        res1 = _summ(r["fwd"][21][k] for k in ev)
        active = any(r["signals"][key][max(0, i - 2):])  # fired in the last 3 sessions
        sig_out.append({"id": key, "kind": kind, "title": title, "why": why, "active": active,
                        "events": len(ev), "m1": res1, "m3": res, "last": dates[ev[-1]] if ev else None})
        for k in ev:
            if k >= n - days:
                history.append({"date": dates[k], "id": key, "title": title, "kind": kind,
                                "m1": r["fwd"][21][k], "m3": r["fwd"][63][k]})
    history.sort(key=lambda e: e["date"])

    start = max(0, n - days)
    return {
        "value": round(v, 1), "zone": zone(v), "chg_1w": round(v - back(5), 1) if back(5) is not None else None,
        "chg_1m": round(v - back(21), 1) if back(21) is not None else None, "asof": dates[i],
        "components": comps, "available": sum(c["score"] is not None for c in comps),
        "series": [[dates[k], round(g[k], 1) if g[k] is not None else None, round(spx[k], 2)] for k in range(start, n)],
        "zones": by_zone, "baseline": base, "first": dates[valid[0]],
        "signals": sig_out, "history": history[-12:],
        "breadth_now": r["breadth"][i], "curve_now": r["curve"][i],
    }
