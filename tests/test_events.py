"""Events radar against fixtures shaped like GDELT DOC 2.0 responses."""
import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from mw import events  # noqa: E402

DAYS = [(dt.date(2026, 8, 1) + dt.timedelta(days=i)) for i in range(90)]


def timeline(series, values):
    return json.dumps({"query_details": {"title": "x"}, "timeline": [{"series": series, "data": [
        {"date": d.strftime("%Y%m%dT000000Z"), "value": v} for d, v in zip(DAYS, values)]}]})


VOL = timeline("Volume Intensity", [0.5] * 87 + [1.6, 1.8, 1.7])           # coverage triples at the end
TONE = timeline("Average Tone", [-1.0 + 0.01 * (i % 5) for i in range(83)] + [-3.0] * 7)  # tone drops
ARTS = json.dumps({"articles": [
    {"url": "https://example.com/1", "title": "Missile strikes escalate as markets tumble", "seendate": "20261029T081500Z",
     "domain": "example.com", "language": "English"},
    {"url": "https://example.com/2", "title": "Ceasefire talks resume", "seendate": "20261028T120000Z",
     "domain": "example.org", "language": "English"}]})


def fake(url, accept="*/*"):
    if "news.google.com" in url:
        raise OSError("google not used in this test")
    return VOL if "timelinevol" in url else TONE if "timelinetone" in url else ARTS


class Radar(unittest.TestCase):
    def test_parsing_metrics_and_alerts(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(events, "http_get", fake), \
                mock.patch.object(events.time, "sleep", lambda s: None):
            out = events.collect(pathlib.Path(d), log=lambda m: None, today=dt.date(2026, 10, 29))
        t = out["themes"][0]
        self.assertEqual(len(t["volume"]), 90)
        self.assertEqual(t["volume"][0][0], "2026-08-01")
        self.assertEqual(t["status"], "Spike")
        self.assertGreater(t["attention"], 3)
        self.assertEqual(t["tone_trend"], "worsening")
        self.assertEqual(t["headlines"][0]["date"], "2026-10-29")
        self.assertLess(t["headlines"][0]["score"], 0)
        self.assertIn(t["id"], out["alerts"])
        self.assertEqual(out["source"], "GDELT")
        self.assertEqual(len(out["index"]), 90)

    def test_rate_limit_text_is_an_error_not_a_crash(self):
        errors = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(events, "http_get", lambda u, a="*/*": "Please limit requests to one every 5 seconds"), \
                mock.patch.object(events.time, "sleep", lambda s: None), \
                mock.patch.object(events, "google_news", side_effect=OSError("offline")):
            out = events.collect(pathlib.Path(d), log=lambda m: None, errors=errors)
        self.assertIsNone(out)
        self.assertTrue(errors and "limit requests" in errors[0])


if __name__ == "__main__":
    unittest.main()
