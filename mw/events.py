"""News & events radar: how much the world is talking about each market-moving theme, and in what tone.

Source: the GDELT DOC 2.0 API (api.gdeltproject.org), which monitors news worldwide and scores the
tone of every article. For each theme we pull 90 days of daily coverage share ("volume intensity",
the theme's share of all monitored articles) and average tone, plus the latest headlines. A jump in
coverage versus its own recent normal marks a major event; a shift in tone marks a change in mood.
If GDELT is unreachable, headlines fall back to Google News.
"""
import datetime as dt
import json
import re
import statistics as st
import time
import urllib.parse

from .config import THEMES
from .fetch import FetchError, http_get
from .news import google_news, score_headline

GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
PAUSE = 5.5  # GDELT asks for at most one request every 5 seconds


def gdelt(query, mode, timespan="90d", **extra):
    params = {"query": f"{query} sourcelang:english", "mode": mode, "format": "json", "timespan": timespan}
    params.update(extra)
    raw = http_get(GDELT + "?" + urllib.parse.urlencode(params), "application/json")
    try:
        return json.loads(raw, strict=False)
    except ValueError:  # GDELT reports problems (rate limit, bad query) as plain text
        raise FetchError("GDELT: " + re.sub(r"\s+", " ", raw).strip()[:160]) from None


def daily_timeline(js):
    """[(YYYY-MM-DD, value)] averaged per day (GDELT may return finer intervals)."""
    pts = ((js.get("timeline") or [{}])[0] or {}).get("data") or []
    by = {}
    for p in pts:
        d = re.sub(r"\D", "", str(p.get("date", "")))[:8]
        if len(d) == 8 and p.get("value") is not None:
            by.setdefault(f"{d[:4]}-{d[4:6]}-{d[6:]}", []).append(float(p["value"]))
    return sorted((d, st.fmean(v)) for d, v in by.items())


def articles(js):
    out = []
    for a in js.get("articles") or []:
        d = re.sub(r"\D", "", str(a.get("seendate", "")))[:8]
        if a.get("title") and len(d) == 8:
            out.append({"title": a["title"].strip(), "date": f"{d[:4]}-{d[4:6]}-{d[6:]}",
                        "source": a.get("domain", ""), "link": a.get("url")})
    return out


def _cached(cache_dir, name, max_age, fetch, state, log):
    """JSON cache with a shared failure budget so a blocked or rate-limited API isn't hammered."""
    path = cache_dir / name
    if path.exists() and time.time() - path.stat().st_mtime < max_age:
        return json.loads(path.read_text())
    if state["fail"] >= 2:
        return json.loads(path.read_text()) if path.exists() else None
    try:
        if state["calls"]:
            time.sleep(PAUSE)
        state["calls"] += 1
        data = fetch()
        path.write_text(json.dumps(data))
        state["fail"] = 0
        return data
    except Exception as e:  # noqa: BLE001
        state["fail"] += 1
        state["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        log(f"events {name}: {state['error']}")
        return json.loads(path.read_text()) if path.exists() else None


def metrics(vol, tone):
    """Coverage vs its recent normal, and 7-day tone vs the previous two months."""
    out = {}
    v = [x for _, x in vol]
    if len(v) >= 30:
        now, base = st.fmean(v[-3:]), v[-63:-3]
        med, mu = st.median(base), st.fmean(base)
        sd = st.pstdev(base) or 1e-9
        out.update(attention=round(now / med, 2) if med else None, attention_z=round((now - mu) / sd, 2))
    t = [x for _, x in tone]
    if len(t) >= 30:
        t7 = st.fmean(t[-7:])
        prior = t[-67:-7]
        roll = [st.fmean(prior[k:k + 7]) for k in range(len(prior) - 6)]
        sd = st.pstdev(roll) if len(roll) > 2 else 0
        out.update(tone_7d=round(t7, 2), tone_prior=round(st.fmean(prior), 2),
                   tone_z=round((t7 - st.fmean(roll)) / sd, 2) if sd else 0.0)
    a, az, tz = out.get("attention"), out.get("attention_z"), out.get("tone_z")
    if a is not None:
        out["status"] = ("Spike" if a >= 2 or (az or 0) >= 3 else "Elevated" if a >= 1.4 or (az or 0) >= 1.5
                         else "Quiet" if a <= 0.6 else "Normal")
    if tz is not None:
        out["tone_trend"] = "improving" if tz >= 1 else "worsening" if tz <= -1 else "steady"
    return out


def news_index(themes):
    """Daily news-mood index: each theme's tone vs its own 90-day mean, weighted by its coverage that day."""
    by_day = {}
    for th in themes:
        tone, vol = dict(th["tone"]), dict(th["volume"])
        if len(tone) < 30:
            continue
        mu, sd = st.fmean(tone.values()), st.pstdev(tone.values()) or 1
        for d, x in tone.items():
            w = vol.get(d, 0) or 0
            by_day.setdefault(d, []).append(((x - mu) / sd, w))
    out = []
    for d in sorted(by_day):
        rows = by_day[d]
        wsum = sum(w for _, w in rows)
        out.append([d, round(sum(z * w for z, w in rows) / wsum if wsum else st.fmean(z for z, _ in rows), 3)])
    # 7-day smoothing so one noisy day doesn't read as a turn
    sm = [[d, round(st.fmean(x for _, x in out[max(0, k - 6):k + 1]), 3)] for k, (d, _) in enumerate(out)]
    return sm


def collect(cache_dir, log=print, today=None, errors=None):
    today = today or dt.date.today()
    cache_dir.mkdir(parents=True, exist_ok=True)
    state = {"fail": 0, "calls": 0, "error": None}
    themes = []
    for th in THEMES:
        if state["fail"] < 2:
            log(f"news radar: {th['name']}")
        q = th["gdelt"]
        vol = _cached(cache_dir, f"ev_{th['id']}_vol.json", 3 * 3600,
                      lambda: daily_timeline(gdelt(q, "timelinevol", timelinesmooth=0)), state, log) or []
        tone = _cached(cache_dir, f"ev_{th['id']}_tone.json", 3 * 3600,
                       lambda: daily_timeline(gdelt(q, "timelinetone", timelinesmooth=0)), state, log) or []
        heads = _cached(cache_dir, f"ev_{th['id']}_arts.json", 3600,
                        lambda: articles(gdelt(q, "artlist", timespan="3d", maxrecords=20, sort="datedesc")),
                        state, log)
        if not heads:  # GDELT down: recent headlines from Google News instead
            try:
                heads = google_news(th["google"], today - dt.timedelta(days=3), today + dt.timedelta(days=1))
            except Exception as e:  # noqa: BLE001
                state["error"] = state["error"] or f"{type(e).__name__}: {str(e)[:160]}"
                heads = []
        seen, uniq = set(), []
        for h in heads or []:
            key = re.sub(r"\W+", "", h["title"].lower())[:70]
            if key not in seen:
                seen.add(key)
                uniq.append(h | {"score": round(score_headline(h["title"]), 3)})
        uniq.sort(key=lambda h: h["date"], reverse=True)
        if not (vol or tone or uniq):
            continue
        themes.append({"id": th["id"], "name": th["name"], "volume": [[d, round(x, 4)] for d, x in vol[-90:]],
                       "tone": [[d, round(x, 3)] for d, x in tone[-90:]], "headlines": uniq[:6],
                       **metrics(vol, tone)})
    if state["error"] and errors is not None:
        errors.append(f"events: {state['error']}")
    if not themes:
        return None
    idx = news_index(themes)
    alerts = sorted((t for t in themes if t.get("status") in ("Spike", "Elevated")),
                    key=lambda t: -(t.get("attention") or 0))
    shifts = [t for t in themes if t.get("tone_trend") in ("improving", "worsening")]
    return {"themes": themes, "index": idx[-90:], "alerts": [a["id"] for a in alerts],
            "tone_shifts": [t["id"] for t in shifts],
            "source": "GDELT" if any(t["volume"] for t in themes) else "Google News (headlines only)"}
