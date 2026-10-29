#!/usr/bin/env python3
"""Market wall: a seasonality + trend + news display for a wall screen.

    python3 server.py                 # http://localhost:8787
    python3 server.py --host 0.0.0.0  # let another device on your network (TV, tablet) open it
    python3 server.py --build-only    # refresh data/cache and exit

Data refreshes in the background every --refresh minutes (default 60). Prices are cached
for 6 hours, the current month's headlines for 1 hour, older months' headlines for a week.
"""
import argparse
import json
import pathlib
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from mw.build import build

ROOT = pathlib.Path(__file__).resolve().parent
WEB = ROOT / "web"
CACHE = ROOT / "cache"
DATA = CACHE / "data.json"

state = {"building": False, "last_error": None, "log": []}
lock = threading.Lock()


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    state["log"] = (state["log"] + [line])[-200:]


def rebuild():
    if not lock.acquire(blocking=False):
        return
    state["building"] = True
    try:
        t0 = time.time()
        data = build(CACHE, log=log)
        data["build_seconds"] = round(time.time() - t0, 1)
        tmp = DATA.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")))
        tmp.replace(DATA)
        state["last_error"] = None
        log(f"built {DATA.name}: {data['status']['loaded']}/{data['status']['total']} instruments, "
            f"news for {data['status']['news_groups']} sectors, {data['build_seconds']}s")
    except Exception as e:  # noqa: BLE001
        state["last_error"] = f"{type(e).__name__}: {e}"
        log(f"build failed: {state['last_error']}")
        raise
    finally:
        state["building"] = False
        lock.release()


def refresher(minutes):
    while True:
        try:
            rebuild()
        except Exception:  # noqa: BLE001 - logged in rebuild
            pass
        time.sleep(minutes * 60)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/data"):
            if DATA.exists():
                body = DATA.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"pending": True, "building": state["building"], "error": state["last_error"]}, 503)
            return
        if self.path.startswith("/api/status"):
            self._json({k: state[k] for k in ("building", "last_error")} | {"log": state["log"][-40:]})
            return
        if self.path.startswith("/api/refresh"):
            threading.Thread(target=rebuild, daemon=True).start()
            self._json({"started": True})
            return
        super().do_GET()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--refresh", type=float, default=60, help="minutes between data refreshes")
    ap.add_argument("--build-only", action="store_true")
    args = ap.parse_args()
    CACHE.mkdir(exist_ok=True)
    if args.build_only:
        rebuild()
        return
    threading.Thread(target=refresher, args=(args.refresh,), daemon=True).start()
    print(f"Market wall on http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
