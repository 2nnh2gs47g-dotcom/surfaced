#!/usr/bin/env python3
"""
Regression tests for the scoring defects found in the 9 Nov live QA run.

    python3 test_scoring.py

No internet. Pages are served by a fixture server on localhost, so every test
runs in well under a second and gives the same answer every time.

Each test names the defect it guards. They are here because each of these bugs
reached a real report and told a real business something untrue.
"""

from __future__ import annotations

import http.server
import socket
import threading

import ai_visibility_studio as s

passed = 0
failed: list[str] = []


def check(name: str, got, want, note: str = "") -> None:
    global passed
    if got == want:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed.append(f"{name}: got {got!r}, want {want!r}{' — ' + note if note else ''}")
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")


# ---------------------------------------------------------------------------
# Fixture server
# ---------------------------------------------------------------------------

WP_ROBOTS = b"User-agent: *\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\n"

GOOD_PAGE = b"""<!DOCTYPE html><html lang="en"><head>
<title>Bright Smile Dental - Your Bernardsville Dentist</title>
<meta name="description" content="Family and cosmetic dentistry in Bernardsville, New Jersey.">
</head><body>
<h1>Bright Smile Dental</h1>
<h2>What services do you offer?</h2>
<p>We provide cleanings, fillings, crowns and whitening for families across Somerset County.
New patients are welcome and most insurance plans are accepted at our Bernardsville office.</p>
<h2>Where are you located?</h2>
<p>Our office is at 12 Mine Brook Road, Bernardsville, NJ 07924. Call 908-555-0147 to book
an appointment. Office hours are Monday to Friday, 8am to 5pm.</p>
<a href="https://maps.app.goo.gl/abc123">Find us on Google Maps</a>
</body></html>"""

EMPTY_PAGE = b"<!DOCTYPE html><html><head></head><body><div id=root></div></body></html>"

CHALLENGE_PAGE = b"""<!DOCTYPE html><html><head><title>Just a moment...</title></head>
<body>Checking your browser before accessing the site.</body></html>"""


class Fixtures(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):            # keep the test output clean
        pass

    def _send(self, body: bytes, status: int = 200, ctype: str = "text/html") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        ua = self.headers.get("User-Agent", "")
        path = self.path

        if path == "/robots.txt":
            self._send(WP_ROBOTS, ctype="text/plain")
        elif path == "/good":
            self._send(GOOD_PAGE)
        elif path == "/empty":
            self._send(EMPTY_PAGE)
        elif path == "/challenge":
            self._send(CHALLENGE_PAGE)
        elif path == "/firewalled":
            # Refuses the scanner, answers an ordinary browser — the exact
            # behaviour that made 23% of the QA run return nothing at all.
            if s.REQUEST_UA.split(";")[1].strip().split("/")[0] in ua:
                self._send(b"Access denied", 403)
            else:
                self._send(GOOD_PAGE)
        else:
            self._send(b"not found", 404)


def start_server() -> str:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Fixtures)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}"


BASE = start_server()


# ---------------------------------------------------------------------------
print("\nD1 — a normal robots.txt must not read as 'no AI crawler can reach you'")
# ---------------------------------------------------------------------------
wp = s.parse_robots(WP_ROBOTS.decode())
check("WordPress /wp-admin/ leaves the homepage reachable",
      s.bot_access(wp, "OAI-SearchBot", "/"), "partial")
check("a blanket Disallow: / is still blocked",
      s.bot_access(s.parse_robots("User-agent: *\nDisallow: /\n"), "OAI-SearchBot", "/"), "blocked")
check("Allow: / overrides Disallow: /",
      s.bot_access(s.parse_robots("User-agent: *\nDisallow: /\nAllow: /\n"), "OAI-SearchBot", "/"), "allowed")
check("a rule naming another bot does not apply",
      s.bot_access(s.parse_robots("User-agent: PerplexityBot\nDisallow: /\n"), "OAI-SearchBot", "/"), "allowed")
check("a rule naming this bot does apply",
      s.bot_access(s.parse_robots("User-agent: PerplexityBot\nDisallow: /\n"), "PerplexityBot", "/"), "blocked")
check("the scanned path itself being disallowed is a block",
      s.bot_access(s.parse_robots("User-agent: *\nDisallow: /blog/\n"), "OAI-SearchBot", "/blog/post"), "blocked")
check("a wildcard rule that does not match the page",
      s.bot_access(s.parse_robots("User-agent: *\nDisallow: /*.pdf$\n"), "OAI-SearchBot", "/"), "partial")
check("a wildcard rule that does match",
      s.bot_access(s.parse_robots("User-agent: *\nDisallow: /*.pdf$\n"), "OAI-SearchBot", "/a.pdf"), "blocked")
check("an empty Disallow allows everything",
      s.bot_access(s.parse_robots("User-agent: *\nDisallow:\n"), "OAI-SearchBot", "/"), "allowed")
check("a more specific Allow beats a general Disallow",
      s.bot_access(s.parse_robots("User-agent: *\nDisallow: /p/\nAllow: /p/ok\n"), "OAI-SearchBot", "/p/ok"), "allowed")

good = s.analyze(f"{BASE}/good")
assert not isinstance(good, str), good
access = [c for c in good.checks if c.label == "AI citation crawlers allowed"][0]
check("'partial' costs a site nothing", access.earned, access.possible,
      "a /wp-admin/ rule must not zero the access score")
check("the finding counts every reachable crawler",
      access.detail.startswith("6 of 6"), True)
check("no false 'blocked' fix is offered", access.fix, "")


# ---------------------------------------------------------------------------
print("\nD2 — a page we could not read must not be graded")
# ---------------------------------------------------------------------------
check("a Cloudflare interstitial is recognised",
      s.looks_like_challenge(CHALLENGE_PAGE.decode()), True)
check("a real page is not", s.looks_like_challenge(GOOD_PAGE.decode()), False)

empty = s.analyze(f"{BASE}/empty")
check("an empty response returns an explanation, not a grade",
      isinstance(empty, str), True)
check("the explanation says it could not read the page",
      isinstance(empty, str) and "could not read" in empty.lower(), True)

challenge = s.analyze(f"{BASE}/challenge")
check("a bot-check page returns an explanation, not an F",
      isinstance(challenge, str), True)


# ---------------------------------------------------------------------------
print("\nD3 — a site that refuses crawlers should still produce a report")
# ---------------------------------------------------------------------------
fw = s.analyze(f"{BASE}/firewalled")
check("the scan retries as a browser and succeeds", not isinstance(fw, str), True,
      str(fw)[:80] if isinstance(fw, str) else "")
if not isinstance(fw, str):
    finding = [c for c in fw.checks if c.label == "Firewall turns away automated readers"]
    check("and reports the firewall as a High-priority finding", len(finding), 1)
    check("explaining AI crawlers hit the same wall",
          bool(finding) and finding[0].priority == "High", True)


# ---------------------------------------------------------------------------
print("\nD4 — reports must show the business name, not the domain")
# ---------------------------------------------------------------------------
check("the <title> inside <head> is captured",
      good.site_title, "Bright Smile Dental - Your Bernardsville Dentist")


# ---------------------------------------------------------------------------
print("\nD5 — business type must be recognised without schema markup")
# ---------------------------------------------------------------------------
check("a dentist with an address and phone scores as local", good.vertical, "local")
check("and says why", "address" in good.vertical_evidence.lower(), True)
check("OfferCatalog is not an online-store signal",
      s.classify_vertical(["OfferCatalog"], "our services", False)[0] != "ecommerce", True)
check("restaurant wording is recognised",
      s.classify_vertical([], "view menu reservations order online takeout daily specials", False)[0],
      "local")


# ---------------------------------------------------------------------------
print("\nD6 — advice must fit the page it is about")
# ---------------------------------------------------------------------------
for link, want in [("https://maps.app.goo.gl/abc", True), ("https://goo.gl/maps/xyz", True),
                   ("https://www.google.com/maps/embed?pb=1", True),
                   ("https://example.com/contact", False)]:
    check(f"Google Business Profile link: {link.split('/')[2]}", s.is_gbp_link(link), want)

check("an embedded Google map counts as a profile link",
      [c for c in good.checks if c.label == "Google Business Profile link"][0].earned > 0, True)

thin = [c for c in good.checks if c.label == "Readable text without JavaScript"][0]
check("a thin static page is not told to server-render",
      "server-render" in thin.fix.lower(), False, thin.fix[:60])
check("it is told to add content instead",
      "300 words" in thin.fix, True)

check("customers never see our API-key setup note",
      any("GOOGLE_PLACES_API_KEY" in c.detail for c in good.checks), False)


# ---------------------------------------------------------------------------
print()
if failed:
    print(f"{len(failed)} FAILURE(S):")
    for f in failed:
        print(f"  - {f}")
    raise SystemExit(1)
print(f"All {passed} scoring regressions pass.")
