"""The sentiment gauge on a synthetic market: steady rise, sharp crash, recovery."""
import datetime as dt
import math
import pathlib
import random
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from mw import sentiment as snt  # noqa: E402


def market(days=2600, crash_at=2300, seed=7):
    rnd = random.Random(seed)
    start = dt.date(2016, 1, 4)
    dates, d = [], start
    while len(dates) < days:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += dt.timedelta(days=1)
    px, vix, tlt, hyg, ief = [100.0], [15.0], [100.0], [100.0], [100.0]
    secs = {s: [100.0] for s in ("XLK", "XLE", "XLF", "XLV", "XLI", "XLY", "XLP", "XLU", "VNQ", "XLB")}
    for i in range(1, days):
        crash = crash_at <= i < crash_at + 25
        rec = crash_at + 25 <= i < crash_at + 90
        calm = crash_at - 200 <= i < crash_at
        mu = -0.012 if crash else 0.004 if rec else 0.0025 if calm else 0.0004
        r = mu + rnd.gauss(0, 0.025 if crash else 0.004 if calm else 0.008)
        px.append(px[-1] * math.exp(r))
        vix.append(max(9, vix[-1] + (-60 * r) + 0.05 * (15 - vix[-1]) + rnd.gauss(0, 0.3)))
        tlt.append(tlt[-1] * math.exp(-0.4 * r + rnd.gauss(0, 0.004)))
        hyg.append(hyg[-1] * math.exp(0.4 * r + rnd.gauss(0, 0.002)))
        ief.append(ief[-1] * math.exp(-0.1 * r + rnd.gauss(0, 0.002)))
        for k, v in secs.items():
            beta = 1.3 if k in ("XLK", "XLY") else 0.6 if k in ("XLP", "XLU") else 1.0
            v.append(v[-1] * math.exp(beta * r + rnd.gauss(0, 0.006)))
    vix3 = [v * 0.9 + 15 * 0.1 + 1.0 for v in vix]  # 3-month VIX: smoother, usually above spot
    z = lambda a: list(zip(dates, a))  # noqa: E731
    daily = {"^GSPC": z(px), "^VIX": z(vix), "^VIX3M": z(vix3), "TLT": z(tlt), "HYG": z(hyg), "IEF": z(ief)}
    daily.update({k: z(v) for k, v in secs.items()})
    return daily, dates


class Gauge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.daily, cls.dates = market()
        t = time.time()
        cls.r = snt.compute(cls.daily, list(k for k in cls.daily if k.startswith("X") or k == "VNQ"))
        cls.secs = time.time() - t
        cls.s = snt.summarize(cls.r)

    def test_range_and_components(self):
        g = [x for x in self.r["gauge"] if x is not None]
        self.assertTrue(all(0 <= x <= 100 for x in g))
        self.assertEqual(self.s["available"], 8)
        self.assertLess(self.secs, 5)

    def test_crash_reads_as_fear_and_calm_rise_as_greed(self):
        g = self.r["gauge"]
        self.assertLess(min(g[2310:2330]), 20)       # in the crash
        self.assertGreater(st_mean(g[2200:2290]), 50)  # calm uptrend before it

    def test_signals_fire_around_the_crash(self):
        f = self.r["signals"]
        self.assertTrue(any(f["curve_inverted"][2300:2330]))
        washouts = [self.dates[i] for i in snt.events(f["washout"]) if 2320 <= i <= 2400]
        self.assertTrue(washouts, "fear washout should fire during the recovery")

    def test_backtest_tables(self):
        zones = {z["zone"]: z for z in self.s["zones"]}
        self.assertEqual(sum(z["days"] for z in zones.values()), self.s["baseline"]["days"])
        self.assertEqual(len(self.s["series"]), 260)


def st_mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs)


if __name__ == "__main__":
    unittest.main()
