"""Assemble everything the wall shows into one JSON-able dict."""
import datetime as dt
import statistics as st

from . import analytics as an
from . import calendar as cal
from . import events as evr
from . import sentiment as snt
from .config import (BENCHMARK, BENCHMARK_FALLBACK, GROUPS, INSTRUMENTS, SENTIMENT_SECTORS, SP500_MONTH_NOTES,
                     SP500_SINCE)
from .fetch import diagnose, fetch_all
from .news import collect, tilt

M = an.MONTHS


def fp(x, nd=1, sign=True):
    if x is None:
        return "n/a"
    s = f"{x * 100:+.{nd}f}%" if sign else f"{x * 100:.{nd}f}%"
    return s.replace("-", "−")


def coming_months(today):
    """Calendar months the display treats as 'upcoming' (see analytics.current_odds)."""
    first = today.month if today.day <= 10 else today.month % 12 + 1
    return [(first - 1 + k) % 12 + 1 for k in range(3)]


def pick_narrative(group, upcoming):
    """The narrative whose window is in progress or starts soonest within the coming months."""
    best, best_key = None, None
    for n in group["narratives"]:
        start, length = n["window"]
        covered = [(start - 1 + k) % 12 + 1 for k in range(length)]
        if upcoming[0] in covered:
            key = (0, covered.index(upcoming[0]), length)
        elif start in upcoming:
            key = (1, upcoming.index(start), 0)
        else:
            continue
        if best_key is None or key < best_key:
            best, best_key = n, key
    return best


def signals_for(snap, odds3, news_t):
    sig = []
    if odds3 and odds3.get("seasonal_up_rate") is not None and odds3.get("raw_up_rate") is not None:
        d = odds3["seasonal_up_rate"] - odds3["raw_up_rate"]
        sig.append({"k": "Season", "v": 1 if d >= 0.05 else -1 if d <= -0.05 else 0,
                    "tip": f"{odds3['window']} up {fp(odds3['seasonal_up_rate'], 0, False)} of years vs "
                           f"{fp(odds3['raw_up_rate'], 0, False)} for any {odds3['h']}-month stretch"})
    if snap.get("vs_sma10") is not None:
        v = snap["vs_sma10"]
        sig.append({"k": "Trend", "v": 1 if v > 0.01 else -1 if v < -0.01 else 0,
                    "tip": f"{fp(v)} vs 10-month average"})
    if snap.get("y1") is not None:
        v = snap["y1"]
        sig.append({"k": "Momentum", "v": 1 if v > 0.03 else -1 if v < -0.03 else 0,
                    "tip": f"{fp(v)} over 12 months"})
    if news_t is not None:
        sig.append({"k": "News", "v": 1 if news_t >= 0.25 else -1 if news_t <= -0.25 else 0,
                    "tip": f"headline tone {news_t:+.2f} vs its 12-month norm"})
    return sig


def actionables_for(g, sym, inst, snap, seas, odds, news_t, rs_rank, n_ranked, events, vix):
    a = []
    name = inst["name"]
    o1, o3 = odds.get("1"), odds.get("3")

    def add(kind, text, why=""):
        a.append({"kind": kind, "text": text, "why": why})

    if o1:
        w = seas["1"][o1["start_month"] - 1]
        if w and w["n"] >= 10:
            if w["win"] >= 0.65 and w["mean"] > 0:
                add("tailwind", f"{M[o1['start_month'] - 1]} has been up in {fp(w['win'], 0, False)} of "
                                f"{w['n']} years (avg {fp(w['mean'])})", "Seasonal tailwind for the coming month")
            elif w["win"] <= 0.45:
                add("headwind", f"{M[o1['start_month'] - 1]} has been up in only {fp(w['win'], 0, False)} of "
                                f"{w['n']} years (avg {fp(w['mean'])})", "Seasonal headwind for the coming month")
    best3 = max((x for x in seas["3"] if x and x["n"] >= 10), key=lambda x: x["mean"], default=None)
    if best3 and o1:
        lead = (best3["start"] - o1["start_month"]) % 12
        if lead == 0:
            add("tailwind", f"Entering its strongest 3-month window ({best3['label']}: up {fp(best3['win'], 0, False)}"
                            f" of years, avg {fp(best3['mean'])})")
        elif lead <= 2:
            add("watch", f"Strongest seasonal window ({best3['label']}) starts in {lead} month{'s' * (lead > 1)}",
                "Historically the best time to be positioned; set alerts")
    v10 = snap.get("vs_sma10")
    if v10 is not None:
        sma = snap["sma10"]
        if v10 > 0 and (snap.get("vs_ma200") is None or snap["vs_ma200"] > 0):
            add("tailwind", f"Uptrend: {fp(v10)} above its 10-month average ({sma:,.2f})",
                "Trend-following rule: stay with it while above")
        elif v10 < 0 and (snap.get("vs_ma200") is None or snap["vs_ma200"] < 0):
            add("headwind", f"Downtrend: {fp(v10)} below its 10-month average",
                f"A monthly close back above {sma:,.2f} would flip the trend signal")
        else:
            add("watch", "Mixed trend: monthly and daily averages disagree", "Wait for both to line up")
        if v10 > 0.12:
            add("risk", f"Stretched: {fp(v10)} above trend",
                "Pullbacks are more common from here; scale in rather than chase")
    dd, dd52 = snap.get("dd"), snap.get("dd52")
    if dd is not None and dd > -0.02:
        add("tailwind", "At or near an all-time high", "New highs tend to cluster: strength begets strength")
    elif dd52 is not None:
        if dd52 <= -0.20:
            add("risk", f"{fp(dd52)} from its 52-week high: bear-market territory",
                "Mean reversion vs. falling knife: let the trend confirm first")
        elif dd52 <= -0.10:
            add("watch", f"In correction: {fp(dd52)} from its 52-week high")
    if rs_rank is not None and n_ranked >= 6:
        if rs_rank <= 3:
            add("tailwind", f"Leader: #{rs_rank} of {n_ranked} sectors on 6-month strength vs the S&P 500")
        elif rs_rank > n_ranked - 3:
            add("headwind", f"Laggard: #{rs_rank} of {n_ranked} sectors on 6-month strength vs the S&P 500")
    if news_t is not None:
        up = (v10 or 0) > 0
        if news_t <= -0.4 and up:
            add("watch", "Headlines unusually negative, but price is holding its trend",
                "Price ignoring bad news is often a sign of underlying strength")
        elif news_t >= 0.4 and not up:
            add("watch", "Headlines unusually positive, but price is below trend", "Good news not lifting price: distribution warning")
        elif news_t <= -0.4:
            add("headwind", "News flow more negative than its 12-month norm")
        elif news_t >= 0.4:
            add("tailwind", "News flow more positive than its 12-month norm")
    if vix is not None and g["id"] == "market":
        if vix >= 25:
            add("risk", f"VIX {vix:.1f}: elevated fear", "Big swings both ways; size positions smaller")
        elif vix <= 14:
            add("watch", f"VIX {vix:.1f}: calm/complacent", "Low-vol regimes can end abruptly")
    for e in events:
        if e["group"] == g["id"] and e["days"] <= 21:
            add("watch", f"{e['label']} in {e['days']} day{'s' * (e['days'] != 1)}")
            break
    order = {"risk": 0, "tailwind": 1, "headwind": 2, "watch": 3}
    return sorted(a, key=lambda x: order[x["kind"]])


def sentiment_actionables(sent, radar):
    """Turn gauge extremes, inflection signals and news spikes into actionables for the market card."""
    out = []
    if sent:
        z = next((x for x in sent["zones"] if x["current"]), None)
        base = sent["baseline"]["m3"]
        if z and z["m3"] and base and sent["zone"] in ("Extreme fear", "Extreme greed"):
            out.append({"kind": "watch",
                        "text": f"Sentiment gauge at {sent['value']:.0f}/100: {sent['zone'].lower()}",
                        "why": f"On such days since {sent['first'][:4]} the S&P was higher 3 months later "
                               f"{fp(z['m3']['up'], 0, False)} of the time (avg {fp(z['m3']['avg'])}) vs "
                               f"{fp(base['up'], 0, False)} on all days"})
        for s in sent["signals"]:
            if s["active"]:
                res = s["m3"]
                why = (f"After {res['n']} past signals: S&P up {fp(res['up'], 0, False)} of the time 3 months later, "
                       f"avg {fp(res['avg'])}") if res else s["why"]
                out.append({"kind": s["kind"], "text": f"Inflection signal: {s['title']}", "why": why})
    if radar:
        by = {t["id"]: t for t in radar["themes"]}
        for tid in radar["alerts"][:3]:
            t = by[tid]
            head = t["headlines"][0]["title"] if t["headlines"] else ""
            kind = "risk" if t.get("tone_trend") == "worsening" else "watch"
            out.append({"kind": kind, "text": f"{t['name']}: news coverage {t['attention']}× normal"
                                              f"{', tone worsening' if kind == 'risk' else ''}", "why": head[:140]})
    return out


def build(cache_dir, today=None, log=print):
    today = today or dt.date.today()
    errors = []
    prices = fetch_all(INSTRUMENTS, cache_dir, log=log, errors=errors)
    series = {}
    for sym, data in prices.items():
        try:
            s = an.Series(data, INSTRUMENTS[sym].get("start"))
            if len(s.rows) >= 24:
                series[sym] = s
        except Exception as e:  # noqa: BLE001
            log(f"{sym}: bad series ({e})")
    news = collect(GROUPS, cache_dir, log=log, today=today, errors=errors)

    sent = None
    try:
        daily = {s: [tuple(r) for r in d["daily"]] for s, d in prices.items() if d.get("daily")}
        sent = snt.summarize(snt.compute(daily, SENTIMENT_SECTORS))
        if sent:
            log(f"sentiment gauge {sent['value']} ({sent['zone']}), {sent['available']}/8 components")
    except Exception as e:  # noqa: BLE001
        log(f"sentiment failed: {type(e).__name__}: {e}")
    radar = None
    try:
        radar = evr.collect(cache_dir, log=log, today=today, errors=errors)
    except Exception as e:  # noqa: BLE001
        log(f"events radar failed: {type(e).__name__}: {e}")

    # odds model: pooled across instruments (skip near-duplicates of the S&P and the VIX)
    pool = [s for sym, s in series.items()
            if not INSTRUMENTS[sym].get("no_odds") and not (sym == "SPY" and "^GSPC" in series) and len(s.rows) >= 120]
    evals = {}
    for h in an.HORIZONS:
        ev = an.evaluate(pool, h) if pool else None
        if ev:
            evals[str(h)] = ev
            log(f"model h={h}: n={ev['n_all']} brier {ev['brier_model']} vs base {ev['brier_base']} "
                f"hit {ev['hit_rate']}")

    group_of = {m: g["id"] for g in GROUPS for m in g["members"]}
    tilts = {g["id"]: tilt(news.get(g["id"])) for g in GROUPS}
    bench = series.get(BENCHMARK) or series.get(BENCHMARK_FALLBACK)
    bench_snap = bench.snapshot() if bench else {}
    events = cal.upcoming(today)

    inst_out = {}
    for sym, s in series.items():
        meta = INSTRUMENTS[sym]
        snap = s.snapshot()
        since = SP500_SINCE if sym == "^GSPC" else None
        seas = s.seasonality(since)
        odds = {}
        if not meta.get("no_odds"):
            for h, ev in evals.items():
                o = an.current_odds(s, int(h), ev["_w"], tilts.get(group_of.get(sym)), today)
                if o:
                    o["verdict"] = an.verdict(o["p"])
                    odds[h] = o
        rs6 = None
        if snap.get("m6") is not None and bench_snap.get("m6") is not None and sym not in (BENCHMARK, BENCHMARK_FALLBACK):
            rs6 = round(snap["m6"] - bench_snap["m6"], 4)
        data = prices[sym]
        inst_out[sym] = {
            "sym": sym, "name": meta["name"], "kind": meta["kind"], "group": group_of.get(sym),
            "source": data["source"], "monthly_kind": s.kind, "stale": data.get("stale", False),
            "history_from": f"{max(s.first_year, since or 0)}", "history_to": f"{s.rows[-1][0]}-{s.rows[-1][1]:02d}",
            "snap": snap, "season": seas, "odds": odds, "rs6": rs6,
            "signals": signals_for(snap, odds.get("3"), tilts.get(group_of.get(sym))),
        }

    # rank sector leaders on 6-month relative strength (one representative per group)
    upcoming = coming_months(today)
    groups_out = []
    primaries = {}
    for g in GROUPS:
        avail = [m for m in g["members"] if m in inst_out]
        if avail:
            primaries[g["id"]] = avail[0]
    ranked = sorted((p for p in primaries.values() if inst_out[p]["rs6"] is not None),
                    key=lambda p: -inst_out[p]["rs6"])
    rank_of = {p: i + 1 for i, p in enumerate(ranked)}
    vix = inst_out.get("^VIX", {}).get("snap", {}).get("price")

    for g in GROUPS:
        avail = [m for m in g["members"] if m in inst_out]
        p = avail[0] if avail else None
        narr = pick_narrative(g, upcoming)
        narr_out = None
        all_narr = []
        for n in g["narratives"]:
            stats = None
            if p:
                ser = series[p]
                stats = ser.window_stats(*n["window"], since=SP500_SINCE if p == "^GSPC" else None)
            item = {"title": n["title"], "why": n["why"], "window": list(n["window"]),
                    "label": an.window_label(*n["window"]), "stats": stats, "sym": p}
            all_narr.append(item)
            if n is narr:
                narr_out = item
        out = {"id": g["id"], "name": g["name"], "members": g["members"], "available": avail, "primary": p,
               "narrative": narr_out, "narratives": all_narr, "news": news.get(g["id"]),
               "news_tilt": tilts.get(g["id"]), "news_query": g["news"]}
        if p:
            ip = inst_out[p]
            out["actionables"] = actionables_for(g, p, ip, ip["snap"], ip["season"], ip["odds"], tilts.get(g["id"]),
                                                 rank_of.get(p), len(ranked), events, vix)
        else:
            out["actionables"] = []
        if g["id"] == "market":
            out["actionables"] = sentiment_actionables(sent, radar) + out["actionables"]
        groups_out.append(out)

    sp = series.get("^GSPC")
    sp_out = None
    if sp:
        since = max(SP500_SINCE, sp.first_year + 1)  # first full calendar year of returns
        mt = sp.month_table(since)
        almanac = []
        for m in range(1, 13):
            xs = [mt[y][m] for y in mt if m in mt[y]]
            almanac.append({"m": m, "name": M[m - 1], "note": SP500_MONTH_NOTES[m], "n": len(xs),
                            "mean": an.pct(st.fmean(xs)), "median": an.pct(st.median(xs)),
                            "win": round(sum(x > 0 for x in xs) / len(xs), 4)})
        paths = sp.year_paths(since)
        done = [y for y in paths if len(paths[y]) == 12 and y < today.year]

        def avg_path(years):
            return [an.pct(st.fmean(paths[y][k] for y in years)) for k in range(12)] if years else []
        cur = list(paths.get(today.year, []))
        if sp.partial and sp.partial[0] == today.year:
            base = sp.close.get((today.year - 1, 12))
            if base:
                cur.append(sp.last_price()[0] / base - 1)
        mid = [y for y in done if y % 4 == today.year % 4]
        sp_out = {
            "since": since, "almanac": almanac,
            "cycle": an.presidential_cycle(sp, since, today.year),
            "midterm": an.midterm_stats(sp, since),
            "paths": {"all": avg_path(done), "same_cycle": avg_path(mid), "current": [an.pct(x) for x in cur],
                      "n_all": len(done), "n_cycle": len(mid),
                      "cycle_name": {1: "post-election", 2: "midterm", 3: "pre-election", 0: "election"}[today.year % 4]},
            "monthly_kind": sp.kind,
        }

    missing = [s for s in INSTRUMENTS if s not in inst_out]
    sources = sorted({v["source"] for v in inst_out.values()})
    model = {h: {k: v for k, v in ev.items() if k != "_w"} for h, ev in evals.items()}
    return {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "upcoming_months": upcoming,
        "instruments": inst_out,
        "groups": groups_out,
        "sp500": sp_out,
        "model": {"features": an.FEATURES, "horizons": model,
                  "news_weight": 0.3, "pooled": sorted(s for s, v in series.items() if v in pool)},
        "calendar": events,
        "sentiment": sent,
        "radar": radar,
        "status": {"loaded": len(inst_out), "total": len(INSTRUMENTS), "missing": missing, "sources": sources,
                   "news_groups": len(news), "news_total": len(GROUPS),
                   "errors": [e for e in errors if not e.startswith(("news:", "events:"))][:8],
                   "hint": diagnose(errors),
                   "news_error": next((e[6:] for e in errors if e.startswith("news:")), None),
                   "events_error": next((e[8:] for e in errors if e.startswith("events:")), None)},
    }
