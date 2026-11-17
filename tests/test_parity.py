"""Both implementations must find the same problems on the same pages.
Python rules are checked directly; the JS rules run in a real browser (needs: pip install playwright && playwright install chromium).
    python3 tests/test_parity.py
"""
import json, pathlib, sys, threading, http.server, functools

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cli"))
import sitecheck

EXP = json.loads((ROOT / "tests/expected.json").read_text())
SEC = json.loads((ROOT / "tests/expected_security.json").read_text())
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

for n, want in SEC.items():
    html = (ROOT / f"tests/fixtures/{n}.html").read_text()
    check(f"python security {n}", [i["id"] for i in sitecheck.run_static(html, BASE, True)], want)
    # without the switch, security rules stay silent
    check(f"python no-security {n}", [i["id"] for i in sitecheck.run_static(html, BASE) if i["id"].startswith("sec-")], [])

hdr = lambda d: [i["id"] for i in sitecheck.run_security_live("https://example.com/", d)]
check("headers: none set", hdr({}), ["sec-hsts", "sec-csp", "sec-frame", "sec-nosniff", "sec-referrer"])
check("headers: all set", hdr({"Strict-Transport-Security": "max-age=1", "Content-Security-Policy": "default-src 'self'; frame-ancestors 'self'", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}), [])
check("headers: version leak", hdr({"Strict-Transport-Security": "x", "Content-Security-Policy": "frame-ancestors 'none'", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "x", "Server": "nginx/1.18.0"}), ["sec-server-version"])

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
    for n, want in SEC.items():
        html = (ROOT / f"tests/fixtures/{n}.html").read_text()
        got = pg.evaluate("([h, b]) => SiteCheck.check(h, b, {security: true}).map(i => i.id)", [html, BASE])
        check(f"javascript security {n}", got, want)
        got = pg.evaluate("([h, b]) => SiteCheck.check(h, b).map(i => i.id).filter(x => x.startsWith('sec-'))", [html, BASE])
        check(f"javascript no-security {n}", got, [])
    b.close()
srv.shutdown()
sys.exit(1 if fail else 0)
