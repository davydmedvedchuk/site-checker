"""Both implementations must find the same problems on the same pages.
Python rules are checked directly; the JS rules run in a real browser (needs: pip install playwright && playwright install chromium).
    python3 tests/test_parity.py
"""
import json, pathlib, sys, threading, http.server, functools

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cli"))
import sitecheck

EXP = json.loads((ROOT / "tests/expected.json").read_text())
BASE = "https://example.com/"
fail = 0

def check(name, got, want):
    global fail
    ok = sorted(got) == sorted(want)
    fail += not ok
    print(("PASS " if ok else "FAIL ") + name, "" if ok else f"\n   got  {sorted(got)}\n   want {sorted(want)}")

for n, want in EXP.items():
    html = (ROOT / f"tests/fixtures/{n}.html").read_text()
    check(f"python {n}", [i["id"] for i in sitecheck.run_static(html, BASE)], want)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP javascript (playwright not installed)"); sys.exit(1 if fail else 0)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a, **k): pass
handler = functools.partial(Quiet, directory=str(ROOT))
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page()
    pg.goto(f"http://127.0.0.1:{srv.server_port}/index.html")
    for n, want in EXP.items():
        html = (ROOT / f"tests/fixtures/{n}.html").read_text()
        got = pg.evaluate("([h, b]) => SiteCheck.check(h, b).map(i => i.id)", [html, BASE])
        check(f"javascript {n}", got, want)
    b.close()
srv.shutdown()
sys.exit(1 if fail else 0)
