"""Live checks against a throwaway local server: heavy image, missing image, no compression, https rule.
    python3 tests/test_live.py
"""
import os, pathlib, subprocess, sys, tempfile, threading, http.server, functools, json

ROOT = pathlib.Path(__file__).resolve().parent.parent
tmp = pathlib.Path(tempfile.mkdtemp())
(tmp / "big.jpg").write_bytes(os.urandom(500 * 1024))
(tmp / "small.jpg").write_bytes(os.urandom(10 * 1024))
page = '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Test page for the live checks</title><meta name="viewport" content="width=device-width"></head><body><h1>Hi</h1>' \
       '<img src="big.jpg" alt="big" width="1" height="1"><img src="small.jpg" alt="s" width="1" height="1"><img src="gone.jpg" alt="x" width="1" height="1">' + "<p>filler text</p>" * 2500 + "</body></html>"
(tmp / "index.html").write_text(page)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a, **k): pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(tmp)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
r = subprocess.run([sys.executable, str(ROOT / "cli/sitecheck.py"), f"http://127.0.0.1:{srv.server_port}/", "--json"], capture_output=True, text=True)
srv.shutdown()
data = json.loads(r.stdout); ids = {i["id"] for i in data["issues"]}
print(sorted(ids), data["score"])
want = {"image-heavy", "image-broken", "no-compression", "no-https", "canonical-missing", "og-missing", "favicon-missing"}
ok = want <= ids and "slow-response" not in ids
print("PASS live" if ok else f"FAIL live, missing {want - ids}")
sys.exit(0 if ok else 1)
