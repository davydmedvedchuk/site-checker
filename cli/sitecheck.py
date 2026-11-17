#!/usr/bin/env python3
"""Site checker: point it at a page, get a short list of what to fix.

    python3 cli/sitecheck.py https://example.com
    python3 cli/sitecheck.py page.html --url https://example.com/   (a saved file; the address only matters for mixed content)
    python3 cli/sitecheck.py https://example.com --json

No dependencies, Python 3.9+. The HTML rules are the same as the web page (checker.js): tests/fixtures hold the pages both must agree on.
Live checks (page weight, compression, speed, heavy images) only run when you give a web address.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
TEXTY = {"title", "a", "button", "h1", "h2", "h3", "h4", "h5", "h6", "label"}
HEAVY_IMAGE = 300 * 1024
UA = "Mozilla/5.0 (compatible; site-checker/0.1; +https://github.com/davydmedvedchuk/site-checker)"


class El:
    def __init__(self, tag, attrs, in_head):
        self.tag, self.a, self.in_head, self.text = tag, {k: (v or "") for k, v in attrs}, in_head, ""

    def snippet(self):
        keep = " ".join(f'{k}="{self.a[k][:40]}"' for k in ("src", "href", "name", "id", "type") if k in self.a)
        return f"<{self.tag}{' ' + keep if keep else ''}>"


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.els: list[El] = []
        self.stack: list[El] = []
        self.in_head = False
        self.html_lang = None
        self.label_inside = 0
        self.inputs_in_label: set[int] = set()

    def handle_starttag(self, tag, attrs):
        if tag == "head": self.in_head = True
        if tag == "body": self.in_head = False
        el = El(tag, attrs, self.in_head)
        if tag == "html": self.html_lang = el.a.get("lang", "")
        if tag == "label": self.label_inside += 1
        if tag in ("input", "select", "textarea") and self.label_inside: el.a["_in_label"] = "1"
        if tag == "img":
            for s in self.stack:
                if s.tag == "a": s.text += " " + el.a.get("alt", "")
        self.els.append(el)
        if tag in TEXTY: self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in TEXTY: self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "head": self.in_head = False
        if tag == "label" and self.label_inside: self.label_inside -= 1
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        for s in self.stack: s.text += data


def has(attr_dict, name):
    return name in attr_dict


def run_static(html: str, base: str | None = None) -> list[dict]:
    p = Page(); p.feed(html)
    els = p.els
    out: list[dict] = []

    def add(id, level, title, fix, items=()):
        items = list(items)
        out.append({"id": id, "level": level, "title": title, "fix": fix, "count": len(items) or 1,
                    "examples": [x if isinstance(x, str) else x.snippet() for x in items[:3]]})

    by = lambda t: [e for e in els if e.tag == t]
    meta = lambda n: next((e for e in by("meta") if e.a.get("name", "").lower() == n), None)

    titles = by("title")
    ttl = (titles[0].text.strip() if titles else "")
    if not ttl: add("title-missing", "error", "The page has no title", "Add a <title> of about 30 to 60 characters. It is the headline in search results and browser tabs.")
    elif len(ttl) > 60: add("title-long", "info", f"The title is {len(ttl)} characters", "Keep it under about 60 characters, or search engines cut it off.")

    d = meta("description")
    dc = (d.a.get("content", "").strip() if d else "")
    if not dc: add("description-missing", "warn", "No meta description", 'Add <meta name="description" content="…"> with one clear sentence (up to 160 characters).')
    elif len(dc) > 160: add("description-long", "info", f"The description is {len(dc)} characters", "Shorten it to 160 or less so it is not cut off.")

    if not (p.html_lang or "").strip(): add("lang-missing", "warn", "The <html> tag has no lang", 'Write <html lang="en"> (or pt, ru…). Screen readers and translators need it.')
    if not meta("viewport"): add("viewport-missing", "error", "No mobile viewport", 'Add <meta name="viewport" content="width=device-width, initial-scale=1">. Without it phones show a tiny desktop page.')

    h1 = by("h1")
    if not h1: add("h1-missing", "warn", "No <h1> heading", "Give the page one main heading that says what it is about.")
    elif len(h1) > 1: add("h1-multiple", "info", f"{len(h1)} <h1> headings", "Use one <h1> and make the others <h2>.", h1)

    imgs = by("img")
    bad = [i for i in imgs if not has(i.a, "alt") and i.a.get("aria-hidden") != "true" and i.a.get("role") not in ("presentation", "none")]
    if bad: add("img-alt-missing", "error", f"{len(bad)} image{'s' if len(bad) > 1 else ''} without alt text", 'Describe each image in alt="…". For pure decoration write alt="" on purpose.', bad)
    nosize = [i for i in imgs if not (has(i.a, "width") and has(i.a, "height"))]
    if nosize: add("img-size-missing", "warn", f"{len(nosize)} image{'s' if len(nosize) > 1 else ''} without width and height", "Add width and height so the page does not jump while images load.", nosize)
    lazy = [i for i in imgs[2:] if i.a.get("loading", "").lower() != "lazy"]
    if lazy: add("img-lazy-missing", "info", f"{len(lazy)} image{'s' if len(lazy) > 1 else ''} load right away", 'Add loading="lazy" to images below the first screen.', lazy)

    blocking = [s for s in by("script") if s.in_head and has(s.a, "src") and not has(s.a, "defer") and not has(s.a, "async") and s.a.get("type", "").lower() != "module"]
    if blocking: add("script-blocking", "warn", (f"{len(blocking)} scripts block the page" if len(blocking) > 1 else "1 script blocks the page"), "Add defer to scripts in the <head> so the page can show first.", blocking)

    empty = [a for a in by("a") if has(a.a, "href") and not (a.text.strip() or a.a.get("aria-label", "").strip() or a.a.get("title", "").strip())]
    if empty: add("link-empty", "warn", f"{len(empty)} link{'s' if len(empty) > 1 else ''} with no text", "Give each link text or aria-label so people using a screen reader know where it goes.", empty)

    label_for = {l.a["for"] for l in by("label") if l.a.get("for")}
    nolabel = [i for i in els if (i.tag in ("select", "textarea") or (i.tag == "input" and i.a.get("type", "text").lower() not in ("hidden", "submit", "button", "image", "reset")))
               and not (i.a.get("aria-label", "").strip() or i.a.get("aria-labelledby", "").strip() or i.a.get("title", "").strip() or has(i.a, "_in_label") or (i.a.get("id") and i.a["id"] in label_for))]
    if nolabel: add("input-label-missing", "warn", f"{len(nolabel)} form field{'s' if len(nolabel) > 1 else ''} without a label", "Connect each field to a <label for=…>, or add aria-label.", nolabel)

    links = by("link")
    rel = lambda e: e.a.get("rel", "").lower().split()
    if not any("canonical" in rel(l) for l in links): add("canonical-missing", "info", "No canonical link", 'Add <link rel="canonical" href="…"> so search engines know the main address.')
    props = {m.a.get("property", "").lower() for m in by("meta")}
    if not ({"og:title", "og:image"} <= props): add("og-missing", "info", "Link preview is incomplete (og:title or og:image missing)", "Add og:title and og:image meta tags so the page looks right when shared in WhatsApp, Telegram or LinkedIn.")
    if not any("icon" in rel(l) for l in links): add("favicon-missing", "info", "No favicon", 'Add <link rel="icon" href="…">. Browsers ask for one anyway.')

    last, skips = 0, []
    for e in els:
        if re.fullmatch(r"h[1-6]", e.tag):
            n = int(e.tag[1])
            if last and n > last + 1: skips.append(e)
            last = n
    if skips: add("heading-skip", "info", f"Heading levels jump ({len(skips)}×)", "Do not skip levels, for example h1 straight to h3. Screen readers use them as an outline.", skips)

    if base and base.lower().startswith("https://"):
        mixed = [e for e in els if (e.tag in ("img", "script", "iframe", "source") and e.a.get("src", "").lower().startswith("http://"))
                 or (e.tag == "link" and "stylesheet" in rel(e) and e.a.get("href", "").lower().startswith("http://"))]
        if mixed: add("mixed-content", "error", f"{len(mixed)} resource{'s' if len(mixed) > 1 else ''} loaded over http on an https page", "Change http:// to https://. Browsers block or warn about these.", mixed)
    return out


# ---------- live checks (only with a web address) ----------
def fetch(url, method="GET", timeout=15):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept-Encoding": "gzip", "Accept": "*/*"})
    t = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read() if method == "GET" else b""
        secs = time.time() - t
        if body and r.headers.get("Content-Encoding") == "gzip": body = gzip.decompress(body)
        return r, body, secs


def run_live(url: str, html_bytes: int, headers, seconds: float, html: str) -> list[dict]:
    out: list[dict] = []
    add = lambda id, level, title, fix, ex=(): out.append({"id": id, "level": level, "title": title, "fix": fix, "count": len(ex) or 1, "examples": list(ex)[:3]})
    if url.lower().startswith("http://"): add("no-https", "warn", "The page is served over http", "Use https. Browsers mark http pages as not secure.")
    if seconds > 1.5: add("slow-response", "warn", f"The page took {seconds:.1f} s to download", "Aim for under 1 second: cache it, use a CDN, or a faster host.")
    if html_bytes > 500 * 1024: add("page-heavy", "warn", f"The HTML is {html_bytes // 1024} KB", "Large HTML is slow on phones. Move inline data and styles out.")
    if html_bytes > 20 * 1024 and not headers.get("Content-Encoding"): add("no-compression", "warn", "The page is sent without compression", "Turn on gzip or brotli on the server. HTML usually shrinks by 70%.")
    p = Page(); p.feed(html)
    urls, seen = [], set()
    for e in p.els:
        if e.tag == "img" and e.a.get("src") and not e.a["src"].startswith("data:"):
            u = urllib.parse.urljoin(url, e.a["src"])
            if u not in seen: seen.add(u); urls.append(u)
    heavy, broken, total = [], [], 0
    for u in urls[:30]:
        try:
            r, _, _ = fetch(u, "HEAD", 10)
            n = int(r.headers.get("Content-Length") or 0); total += n
            if n > HEAVY_IMAGE: heavy.append((n, u))
        except urllib.error.HTTPError as e:
            if e.code in (404, 410): broken.append(u)
        except Exception:
            pass
    if heavy:
        heavy.sort(reverse=True)
        add("image-heavy", "warn", f"{len(heavy)} image{'s' if len(heavy) > 1 else ''} over 300 KB (biggest {heavy[0][0] // 1024} KB)",
            "Resize to the size shown and save as WebP or compressed JPEG. Photo shrinker does it in the browser.", [f"{u} ({n // 1024} KB)" for n, u in heavy])
    if broken: add("image-broken", "error", f"{len(broken)} image{'s' if len(broken) > 1 else ''} not found", "These images return 404. Fix or remove the links.", broken)
    return out


WEIGHT = {"error": 12, "warn": 5, "info": 1}
ORDER = {"error": 0, "warn": 1, "info": 2}
LABEL = {"error": "Fix first", "warn": "Should fix", "info": "Nice to have"}


def score(issues):
    return max(0, 100 - sum(WEIGHT[i["level"]] for i in issues))


def report(issues, title):
    issues = sorted(issues, key=lambda i: ORDER[i["level"]])
    lines = [f"{title}", f"Score {score(issues)} / 100  ·  {len(issues)} thing{'s' if len(issues) != 1 else ''} to look at", ""]
    cur = None
    for i in issues:
        if i["level"] != cur:
            cur = i["level"]; lines.append(f"== {LABEL[cur]} ==")
        lines.append(f"- {i['title']}")
        lines.append(f"    {i['fix']}")
        for ex in i["examples"]: lines.append(f"    e.g. {ex}")
    if not issues: lines.append("Nothing to fix. Nice.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Check a web page and list what to fix.")
    ap.add_argument("target", help="a web address, or a saved .html file")
    ap.add_argument("--url", help="the real address of a saved file (needed for the https checks)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    ap.add_argument("--no-live", action="store_true", help="skip speed, compression and image-size checks")
    a = ap.parse_args()
    live = a.target.lower().startswith(("http://", "https://"))
    issues: list[dict] = []
    try:
        if live:
            r, body, secs = fetch(a.target)
            html = body.decode(r.headers.get_content_charset() or "utf-8", "replace")
            final = r.geturl()
            issues += run_static(html, final)
            if not a.no_live: issues += run_live(final, len(body), r.headers, secs, html)
            title = f"Checked {final}"
        else:
            html = open(a.target, encoding="utf-8", errors="replace").read()
            issues += run_static(html, a.url)
            title = f"Checked {a.target}"
    except Exception as e:
        print(f"Could not check that: {e}", file=sys.stderr); sys.exit(2)
    if a.json:
        print(json.dumps({"score": score(issues), "issues": sorted(issues, key=lambda i: ORDER[i["level"]])}, indent=2, ensure_ascii=False))
    else:
        print(report(issues, title))


if __name__ == "__main__":
    main()
