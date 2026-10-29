"""Parser tests against fixtures shaped like Yahoo's chart API and Google News RSS.

Run: python3 -m unittest discover -s tests
"""
import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from mw import analytics as an  # noqa: E402
from mw import fetch, news  # noqa: E402


def yahoo_payload(dates, closes, interval):
    ts = [int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp()) + 14400 for d in dates]
    return json.dumps({"chart": {"result": [{
        "meta": {"symbol": "XLE", "gmtoffset": -14400},
        "timestamp": ts,
        "indicators": {"quote": [{"close": closes}], "adjclose": [{"adjclose": closes}]},
    }], "error": None}})


RSS = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>x</title>
<item><title>Oil prices surge to record high as OPEC cuts output - Reuters</title><link>https://example.com/a</link>
<pubDate>Tue, 27 Oct 2026 14:00:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
<item><title>Energy stocks slump on recession fears - Bloomberg</title><link>https://example.com/b</link>
<pubDate>Mon, 05 Oct 2026 09:30:00 GMT</pubDate><source url="https://bloomberg.com">Bloomberg</source></item>
</channel></rss>"""


class YahooParsing(unittest.TestCase):
    def test_chart_api_monthly_and_daily(self):
        months = [f"{y}-{m:02d}-01" for y in range(2015, 2027) for m in range(1, 13)][:142]  # to 2026-10
        mclose = [50 + i * 0.3 for i in range(len(months))]
        days = [(dt.date(2026, 10, 1) + dt.timedelta(days=i)).isoformat() for i in range(28)]
        dclose = [90 + i * 0.1 for i in range(28)]
        dclose[5] = None  # Yahoo leaves gaps as null

        def fake_get(url, accept="*/*"):
            return yahoo_payload(months, mclose, "1mo") if "interval=1mo" in url else yahoo_payload(days, dclose, "1d")

        with mock.patch.object(fetch, "http_get", fake_get), mock.patch.dict(sys.modules, {"yfinance": None}):
            data = fetch.fetch_yahoo("XLE")
        self.assertEqual(data["monthly"][0][0], "2015-01")
        self.assertEqual(data["monthly"][-1][0], "2026-10")
        self.assertEqual(len(data["daily"]), 27)  # null dropped
        s = an.Series(data)
        snap = s.snapshot()
        self.assertAlmostEqual(snap["price"], dclose[-1], places=3)
        self.assertIsNotNone(snap["sma10"])
        self.assertEqual(len(s.seasonality()["3"]), 12)


class MonthlyMerge(unittest.TestCase):
    def test_daily_history_extends_short_monthly_series(self):
        # Yahoo's monthly ^GSPC starts in 1985 while its daily history starts in 1927
        monthly = [("1985-01", 180.0), ("1985-02", 181.0)]
        daily = [("1927-12-30", 17.66), ("1928-01-31", 17.57), ("1985-01-31", 179.6), ("2001-01-31", 1366.0)]
        m, d = fetch._merge(monthly, daily)
        self.assertEqual(m[0], ("1927-12", 17.66))
        self.assertEqual(m[-1], ("2001-01", 1366.0))
        self.assertEqual(d, [("2001-01-31", 1366.0)])  # daily closes are kept from 1999 only


class HttpFallback(unittest.TestCase):
    def test_ssl_failure_falls_back_to_curl(self):
        import ssl
        import urllib.error
        err = urllib.error.URLError(ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED"))
        with mock.patch.object(fetch.urllib.request, "urlopen", side_effect=err), \
                mock.patch.object(fetch, "_curl", return_value="ok") as curl, \
                mock.patch.object(fetch.shutil, "which", return_value="/usr/bin/curl"):
            self.assertEqual(fetch.http_get("https://example.com/x.csv"), "ok")
        curl.assert_called_once()

    def test_diagnose(self):
        self.assertIn("certificates", fetch.diagnose(["x: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED]>"]))
        self.assertIn("rate-limiting", fetch.diagnose(["yahoo: HTTP Error 429: Too Many Requests"]))
        self.assertEqual(fetch.diagnose([]), "")


class NewsParsing(unittest.TestCase):
    def test_rss_and_scoring(self):
        with mock.patch.object(news, "http_get", lambda url, accept="*/*": RSS):
            items = news.google_news('"oil prices"', dt.date(2026, 10, 1), dt.date(2026, 11, 1))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["title"], "Oil prices surge to record high as OPEC cuts output")
        self.assertEqual(items[0]["source"], "Reuters")
        self.assertEqual(items[0]["date"], "2026-10-27")
        self.assertGreater(news.score_headline(items[0]["title"]), 0.5)
        self.assertLess(news.score_headline(items[1]["title"]), -0.5)
        self.assertLess(news.score_headline("Stocks do not rally despite strong earnings"), news.score_headline("Stocks rally"))

    def test_collect_windows(self):
        groups = [{"id": "energy", "news": "x", "members": []}]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(news, "http_get", lambda url, accept="*/*": RSS), \
                mock.patch.object(news.time, "sleep", lambda s: None):
            out = news.collect(groups, pathlib.Path(d), months=2, today=dt.date(2026, 10, 29), log=lambda m: None)
        w = out["energy"]["windows"]
        self.assertEqual(w["1M"]["n"], 2)
        self.assertIsNotNone(news.tilt(out["energy"]))


if __name__ == "__main__":
    unittest.main()
