"""Statistics on monthly price history. Pure Python - no numpy needed."""
import datetime as dt
import math
import statistics as st

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HORIZONS = (1, 3, 6)


def ym_add(y, m, k):
    t = y * 12 + (m - 1) + k
    return t // 12, t % 12 + 1


def window_label(start, length):
    end = (start - 1 + length - 1) % 12 + 1
    return MONTHS[start - 1] if length == 1 else f"{MONTHS[start - 1]}–{MONTHS[end - 1]}"


def logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def pct(x, nd=4):
    return None if x is None else round(x, nd)


class Series:
    """Monthly closes keyed by (year, month); the in-progress month is kept separately."""

    def __init__(self, data, start_year=None):
        partial = data.get("partial_month")
        self.kind = data.get("monthly_kind", "close")
        rows = [(int(d[:4]), int(d[5:7]), c) for d, c in data["monthly"] if not start_year or int(d[:4]) >= start_year]
        self.partial = None
        if partial and rows and f"{rows[-1][0]:04d}-{rows[-1][1]:02d}" == partial:
            self.partial = rows.pop()
        self.rows = rows
        self.close = {(y, m): c for y, m, c in rows}
        self.daily = data.get("daily") or []

    @property
    def first_year(self):
        return self.rows[0][0] if self.rows else None

    def last_price(self):
        if self.daily:
            return self.daily[-1][1], self.daily[-1][0]
        if self.partial:
            y, m, c = self.partial
            return c, f"{y:04d}-{m:02d}"
        y, m, c = self.rows[-1]
        return c, f"{y:04d}-{m:02d}"

    def ret(self, y, m, k=1):
        """Return over the k months ending at (y, m)."""
        a = self.close.get(ym_add(y, m, -k))
        b = self.close.get((y, m))
        return None if a is None or b is None else b / a - 1

    # ------------------------------------------------------------ seasonality

    def month_table(self, since=None):
        """{year: {month: return}} for complete months."""
        out = {}
        for y, m, _ in self.rows:
            if since and y < since:
                continue
            r = self.ret(y, m)
            if r is not None:
                out.setdefault(y, {})[m] = r
        return out

    def window_returns(self, start, length, since=None):
        """[(year, return)] for the window starting in calendar month `start` each year."""
        out = []
        for y in range(self.first_year, self.rows[-1][0] + 1):
            if since and y < since:
                continue
            base = self.close.get(ym_add(y, start, -1))
            end = self.close.get(ym_add(y, start, length - 1))
            if base and end:
                out.append((y, end / base - 1))
        return out

    def window_stats(self, start, length, since=None):
        rs = self.window_returns(start, length, since)
        if len(rs) < 3:
            return None
        xs = [r for _, r in rs]
        return {"start": start, "len": length, "label": window_label(start, length), "n": len(xs),
                "win": round(sum(x > 0 for x in xs) / len(xs), 4), "mean": pct(st.fmean(xs)),
                "median": pct(st.median(xs)), "best": pct(max(xs)), "worst": pct(min(xs)),
                "first": rs[0][0], "last": rs[-1][0],
                "recent": [[y, pct(r)] for y, r in rs[-10:]]}

    def seasonality(self, since=None):
        return {str(h): [self.window_stats(s, h, since) for s in range(1, 13)] for h in HORIZONS}

    # ------------------------------------------------------------ current state

    def snapshot(self):
        price, asof = self.last_price()
        out = {"price": pct(price, 4), "asof": asof}
        d = [c for _, c in self.daily]
        if len(d) > 2:
            def back(n):
                return d[-1] / d[-1 - n] - 1 if len(d) > n else None
            out.update(d1=pct(back(1)), w1=pct(back(5)), m1=pct(back(21)), m3=pct(back(63)),
                       m6=pct(back(126)), y1=pct(back(252)))
            ma = lambda n: st.fmean(d[-n:]) if len(d) >= n else None  # noqa: E731
            out["ma50"], out["ma200"] = pct(ma(50), 4), pct(ma(200), 4)
            if len(d) > 64:
                lr = [math.log(d[i] / d[i - 1]) for i in range(len(d) - 63, len(d))]
                out["vol"] = pct(st.pstdev(lr) * math.sqrt(252))
        # monthly-based measures (also fill gaps when there is no daily data)
        closes = [c for _, _, c in self.rows]
        cur = price
        mback = lambda k: cur / closes[-k] - 1 if len(closes) >= k else None  # noqa: E731
        # with a partial month, closes[-1] is last month-end: k months back from "now" is closes[-k]
        offset = 0 if self.partial else 1
        mb = lambda k: mback(k + offset)  # noqa: E731
        for key, k in (("m1", 1), ("m3", 3), ("m6", 6), ("y1", 12)):
            out.setdefault(key, pct(mb(k)))
            if out[key] is None:
                out[key] = pct(mb(k))
        for key, years in (("y3a", 3), ("y5a", 5), ("y10a", 10), ("y20a", 20)):
            r = mb(12 * years)
            out[key] = pct((1 + r) ** (1 / years) - 1) if r is not None else None
        today_year = int(asof[:4])
        dec = self.close.get((today_year - 1, 12))
        out["ytd"] = pct(cur / dec - 1) if dec else None
        if "vol" not in out and len(closes) > 37:
            lr = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - 36, len(closes))]
            out["vol"] = pct(st.pstdev(lr) * math.sqrt(12))
        sma_src = closes[-9:] + [cur] if self.partial else closes[-10:]
        if len(sma_src) == 10:
            sma10 = st.fmean(sma_src)
            out["sma10"] = pct(sma10, 4)
            out["vs_sma10"] = pct(cur / sma10 - 1)
        if out.get("ma200"):
            out["vs_ma200"] = pct(cur / out["ma200"] - 1)
        if out.get("ma50"):
            out["vs_ma50"] = pct(cur / out["ma50"] - 1)
        hi52 = max(d[-252:] + [cur]) if d else max(closes[-12:] + [cur])
        out["hi52"], out["dd52"] = pct(hi52, 4), pct(cur / hi52 - 1)
        ath = max(closes + d + [cur])
        out["ath"] = pct(ath, 4)
        out["dd"] = pct(cur / ath - 1)
        # worst peak-to-trough on month closes
        peak, mdd, mdd_year = closes[0], 0.0, None
        for y, m, c in self.rows:
            peak = max(peak, c)
            if c / peak - 1 < mdd:
                mdd, mdd_year = c / peak - 1, y
        out["max_dd"], out["max_dd_year"] = pct(mdd), mdd_year
        spark = [[f"{y:04d}-{m:02d}", pct(c, 4)] for y, m, c in self.rows[-60:]]
        if self.partial:
            y, m, _ = self.partial
            spark.append([f"{y:04d}-{m:02d}", pct(cur, 4)])
        out["spark"] = spark
        out["daily_spark"] = [[a, pct(b, 4)] for a, b in self.daily[-260:]]
        return out

    # ------------------------------------------------------------ calendar-year paths

    def year_paths(self, since):
        """{year: [cum return through Jan..Dec]} relative to the prior December close."""
        out = {}
        for y in range(since, self.rows[-1][0] + 1):
            base = self.close.get((y - 1, 12))
            if not base:
                continue
            path = []
            for m in range(1, 13):
                c = self.close.get((y, m))
                if c is None:
                    break
                path.append(c / base - 1)
            if path:
                out[y] = path
        return out


# ---------------------------------------------------------------- S&P specials

def presidential_cycle(s, since=1950, this_year=None):
    """Average calendar-year return by year of the US presidential term."""
    names = {1: "Post-election", 2: "Midterm", 3: "Pre-election", 0: "Election"}
    order = [1, 2, 3, 0]
    by = {k: [] for k in order}
    for y in range(since, s.rows[-1][0] + 1):
        a, b = s.close.get((y - 1, 12)), s.close.get((y, 12))
        if a and b:
            by[y % 4].append((y, b / a - 1))  # 2025 -> 1 (post-election), 2026 -> 2 (midterm), ...
    out = []
    for k in order:
        xs = [r for _, r in by[k]]
        out.append({"phase": names[k], "year_mod4": k, "n": len(xs),
                    "mean": pct(st.fmean(xs)) if xs else None,
                    "win": round(sum(x > 0 for x in xs) / len(xs), 4) if xs else None,
                    "current": this_year is not None and this_year % 4 == k})
    return out


def midterm_stats(s, since=1950):
    """Q4 of midterm years and the 12 months that follow (Sep/Oct month-end bases)."""
    q4, after = [], []
    for y in range(since, s.rows[-1][0] + 1):
        if y % 4 != 2:
            continue
        sep, dec, oct_, next_oct = (s.close.get((y, 9)), s.close.get((y, 12)), s.close.get((y, 10)),
                                    s.close.get((y + 1, 10)))
        if sep and dec:
            q4.append((y, dec / sep - 1))
        if oct_ and next_oct:
            after.append((y, next_oct / oct_ - 1))

    def summ(rs):
        if not rs:
            return None
        xs = [r for _, r in rs]
        return {"n": len(xs), "win": round(sum(x > 0 for x in xs) / len(xs), 4), "mean": pct(st.fmean(xs)),
                "worst": pct(min(xs)), "worst_year": min(rs, key=lambda t: t[1])[0],
                "years": [[y, pct(r)] for y, r in rs]}
    return {"q4": summ(q4), "next12": summ(after)}


# ---------------------------------------------------------------- odds model

FEATURES = ["intercept", "base rate", "seasonality", "trend", "momentum"]


def _features(closes, months, t, h, stats):
    """Feature vector at index t (standing at close t, predicting t -> t+h)."""
    wins, n, swins, sn = stats
    if n < 36 or t < 12:
        return None
    p_all = (wins + 1) / (n + 2)
    nxt = months[t] % 12 + 1  # calendar month the forecast window starts in
    k = 8
    p_seas = (swins[nxt] + k * p_all) / (sn[nxt] + k)
    if sn[nxt] < 8:
        return None
    sma = st.fmean(closes[t - 9:t + 1])
    trend = max(-0.3, min(0.3, math.log(closes[t] / sma)))
    mom = max(-0.8, min(0.8, math.log(closes[t] / closes[t - 12])))
    return [1.0, logit(p_all), logit(p_seas) - logit(p_all), trend, mom]


def build_dataset(series_list, h, min_year=1928):
    """Rows of (year, x, y) with features computed only from data available at the time."""
    rows = []
    for s in series_list:
        closes = [c for _, _, c in s.rows]
        months = [m for _, m, _ in s.rows]
        years = [y for y, _, _ in s.rows]
        wins = n = 0
        swins = {m: 0 for m in range(1, 13)}
        sn = {m: 0 for m in range(1, 13)}
        for t in range(len(closes)):
            # windows that have completed by t: base b = t - h
            b = t - h
            if b >= 0:
                up = closes[t] > closes[b]
                first_month = months[b] % 12 + 1
                wins += up
                n += 1
                swins[first_month] += up
                sn[first_month] += 1
            if t + h >= len(closes) or years[t] < min_year:
                continue
            x = _features(closes, months, t, h, (wins, n, swins, sn))
            if x:
                rows.append((years[t], x, 1.0 if closes[t + h] > closes[t] else 0.0))
    return rows


def _solve(a, b):
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for i in range(n):
        p = max(range(i, n), key=lambda r: abs(m[r][i]))
        m[i], m[p] = m[p], m[i]
        for r in range(n):
            if r != i and m[i][i]:
                f = m[r][i] / m[i][i]
                for c in range(i, n + 1):
                    m[r][c] -= f * m[i][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def fit_logistic(rows, ridge=1.0, iters=25):
    k = len(rows[0][1])
    w = [0.0] * k
    for _ in range(iters):
        g = [0.0] * k
        hmat = [[0.0] * k for _ in range(k)]
        for _, x, y in rows:
            p = sigmoid(sum(wi * xi for wi, xi in zip(w, x)))
            r = p * (1 - p)
            for i in range(k):
                g[i] += (y - p) * x[i]
                for j in range(k):
                    hmat[i][j] += r * x[i] * x[j]
        for i in range(1, k):  # don't shrink the intercept
            g[i] -= ridge * w[i]
            hmat[i][i] += ridge
        step = _solve(hmat, g)
        w = [wi + si for wi, si in zip(w, step)]
        if max(abs(s) for s in step) < 1e-7:
            break
    return w


def predict(w, x):
    return sigmoid(sum(wi * xi for wi, xi in zip(w, x)))


def evaluate(series_list, h, split_year=2012):
    rows = build_dataset(series_list, h)
    train = [r for r in rows if r[0] < split_year]
    test = [r for r in rows if r[0] >= split_year]
    if len(train) < 200 or len(test) < 50:
        return None
    w = fit_logistic(train)
    brier = lambda f: st.fmean((f(x) - y) ** 2 for _, x, y in test)  # noqa: E731
    model_b = brier(lambda x: predict(w, x))
    base_b = brier(lambda x: sigmoid(x[1]))
    coin_b = brier(lambda x: 0.5)
    hits = st.fmean((predict(w, x) > 0.5) == (y == 1) for _, x, y in test)
    buckets = []
    for lo, hi in ((0, 0.45), (0.45, 0.55), (0.55, 0.65), (0.65, 1.01)):
        sel = [(predict(w, x), y) for _, x, y in test if lo <= predict(w, x) < hi]
        if sel:
            buckets.append({"range": [lo, min(hi, 1)], "n": len(sel),
                            "predicted": round(st.fmean(p for p, _ in sel), 4),
                            "observed": round(st.fmean(y for _, y in sel), 4)})
    full = fit_logistic(rows)
    return {"h": h, "n_train": len(train), "n_test": len(test), "n_all": len(rows), "split_year": split_year,
            "brier_model": round(model_b, 4), "brier_base": round(base_b, 4), "brier_coin": round(coin_b, 4),
            "skill_vs_base": round(1 - model_b / base_b, 4), "hit_rate": round(hits, 4),
            "test_up_rate": round(st.fmean(y for _, _, y in test), 4),
            "calibration": buckets, "weights": [round(x, 4) for x in full], "_w": full}


def current_odds(s, h, w, news_tilt=None, today=None, news_weight=0.3):
    """Odds the instrument is higher h months from now, with a logit-space breakdown."""
    today = today or dt.date.today()
    closes = [c for _, _, c in s.rows]
    months = [m for _, m, _ in s.rows]
    price, _ = s.last_price()
    cur_month = today.month
    # Early in a month the window that matters is this month; later on, next month.
    if today.day <= 10:
        closes_now, months_now = closes, months
        last_m = months[-1]
    else:
        closes_now, months_now = closes + [price], months + [cur_month]
        last_m = cur_month
    wins = n = 0
    swins = {m: 0 for m in range(1, 13)}
    sn = {m: 0 for m in range(1, 13)}
    for b in range(len(closes) - h):
        up = closes[b + h] > closes[b]
        fm = months[b] % 12 + 1
        wins += up
        n += 1
        swins[fm] += up
        sn[fm] += 1
    t = len(closes_now) - 1
    x = _features(closes_now, months_now, t, h, (wins, n, swins, sn))
    if not x:
        return None
    start_month = last_m % 12 + 1
    steps, z = [], w[0] + w[1] * x[1]
    base = sigmoid(z)
    for i, name in ((2, "seasonality"), (3, "trend"), (4, "momentum")):
        before = sigmoid(z)
        z += w[i] * x[i]
        steps.append({"name": name, "delta": round(sigmoid(z) - before, 4)})
    if news_tilt is not None:
        before = sigmoid(z)
        z += news_weight * news_tilt
        steps.append({"name": "news", "delta": round(sigmoid(z) - before, 4), "heuristic": True})
    return {"h": h, "window": window_label(start_month, h), "start_month": start_month,
            "p": round(sigmoid(z), 4), "base": round(base, 4), "raw_up_rate": round(wins / n, 4) if n else None,
            "seasonal_up_rate": round(swins[start_month] / sn[start_month], 4) if sn[start_month] else None,
            "seasonal_n": sn[start_month], "steps": steps}


def verdict(p):
    if p is None:
        return "n/a"
    if p >= 0.70:
        return "Strong odds up"
    if p >= 0.60:
        return "Favourable"
    if p >= 0.53:
        return "Lean up"
    if p > 0.47:
        return "Coin flip"
    if p > 0.40:
        return "Lean down"
    return "Unfavourable"
