"""Upcoming market-calendar events, computed from rules (plus the Fed's published dates)."""
import datetime as dt

from .config import FIXED_EVENTS, FOMC


def nth_weekday(y, m, weekday, n):
    """n-th given weekday (Mon=0) of a month; n=-1 for the last."""
    if n > 0:
        d = dt.date(y, m, 1)
        d += dt.timedelta(days=(weekday - d.weekday()) % 7)
        return d + dt.timedelta(weeks=n - 1)
    d = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
    return d - dt.timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d):
    return d - dt.timedelta(days=1) if d.weekday() == 5 else d + dt.timedelta(days=1) if d.weekday() == 6 else d


def is_trading_day(d):
    if d.weekday() >= 5:
        return False
    y = d.year
    holidays = {_observed(dt.date(y, 1, 1)), _observed(dt.date(y, 12, 25)), _observed(dt.date(y, 7, 4)),
                nth_weekday(y, 11, 3, 4), nth_weekday(y, 1, 0, 3), nth_weekday(y, 2, 0, 3),
                nth_weekday(y, 5, 0, -1), nth_weekday(y, 9, 0, 1), _observed(dt.date(y, 6, 19))}
    return d not in holidays


def santa_window(y):
    """Last five trading days of year y plus the first two of y+1."""
    d, last5 = dt.date(y, 12, 31), []
    while len(last5) < 5:
        if is_trading_day(d):
            last5.append(d)
        d -= dt.timedelta(days=1)
    d, first2 = dt.date(y + 1, 1, 1), []
    while len(first2) < 2:
        if is_trading_day(d):
            first2.append(d)
        d += dt.timedelta(days=1)
    return min(last5), max(first2)


def upcoming(today=None, days=130):
    today = today or dt.date.today()
    ev = []
    for y in (today.year, today.year + 1):
        if y % 2 == 0:
            eday = nth_weekday(y, 11, 0, 1) + dt.timedelta(days=1)
            kind = "Presidential" if y % 4 == 0 else "Midterm"
            ev.append((eday, f"US {kind.lower()} elections", "market", True))
        tg = nth_weekday(y, 11, 3, 4)
        ev.append((tg + dt.timedelta(days=1), "Black Friday: holiday shopping kicks off (half-day session)", "consumer", False))
        ev.append((tg + dt.timedelta(days=4), "Cyber Monday", "consumer", False))
        for m in (3, 6, 9, 12):
            ev.append((nth_weekday(y, m, 4, 3), "Triple witching: quarterly options & futures expiry", "market", False))
        a, b = santa_window(y)
        ev.append((a, f"Santa Claus rally window opens (runs to {b:%b} {b.day})", "market", True))
        ev.append((dt.date(y, 11, 1), "'Best six months' (Nov–Apr) begins", "market", True))
        ev.append((dt.date(y, 5, 1), "'Sell in May' window (May–Oct) begins", "market", False))
        ev.append((dt.date(y, 11, 30), "Atlantic hurricane season ends", "energy", False))
        ev.append((dt.date(y, 12, 31), "Tax-loss selling deadline / year-end window dressing", "market", False))
        ev.append((dt.date(y, 1, 31), "January barometer: 'as January goes, so goes the year'", "market", False))
        for m in (1, 4, 7, 10):
            d = dt.date(y, m, 12)
            d += dt.timedelta(days=(1 - d.weekday()) % 7)  # first Tuesday on/after the 12th
            ev.append((d, "≈ Earnings season kicks off with the big banks", "financials", False))
        for m in range(1, 13):
            d = nth_weekday(y, m, 4, 1)
            if not is_trading_day(d) or d.day <= 2:  # BLS shifts a too-early or holiday Friday
                d += dt.timedelta(days=7)
            ev.append((d, "≈ US jobs report", "market", False))
    for d in FOMC:
        ev.append((dt.date.fromisoformat(d), "FOMC rate decision (2pm ET)", "rates", True))
    for d, label, g in FIXED_EVENTS:
        ev.append((dt.date.fromisoformat(d), label, g, False))
    end = today + dt.timedelta(days=days)
    out = [{"date": d.isoformat(), "label": lab, "group": g, "major": major, "days": (d - today).days}
           for d, lab, g, major in ev if today <= d <= end]
    out.sort(key=lambda e: (e["date"], not e["major"]))
    return out
