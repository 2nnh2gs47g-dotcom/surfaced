#!/usr/bin/env python3
"""
Surfaced — public web server
============================
Wraps the ai_visibility_studio scoring engine in a public, hardened HTTP
server suitable for hosting on Render / Railway / any PaaS.

Standard library only. No pip install required.

RUN LOCALLY
    python3 server.py
    # then open http://localhost:8000

RUN IN PRODUCTION
    The host sets $PORT; we bind 0.0.0.0 so the platform can route to us.

ENVIRONMENT VARIABLES (all optional)
    PORT                    port to bind          (default 8000)
    SURFACED_BASE_URL       public URL, used for canonical/OG tags
    SURFACED_DATA_DIR       where scan_history.json lives
    SURFACED_RATE_LIMIT     scans per IP per hour (default 12)
    GOOGLE_PLACES_API_KEY   enables live Google rating scoring
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ai_visibility_studio as studio
from pages import landing_page, LLMS_TXT, ROBOTS_TXT, error_page

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORT = int(os.environ.get("PORT", "8000"))
BASE_URL = os.environ.get("SURFACED_BASE_URL", f"http://localhost:{PORT}").rstrip("/")
DATA_DIR = os.environ.get("SURFACED_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
RATE_LIMIT = int(os.environ.get("SURFACED_RATE_LIMIT", "12"))
RATE_WINDOW = 3600          # one hour
MAX_CONCURRENT_SCANS = 4    # protect a small free-tier instance

# Keep scan history wherever the operator wants it (a mounted disk in prod).
os.makedirs(DATA_DIR, exist_ok=True)
studio._history_path = lambda: os.path.join(DATA_DIR, "scan_history.json")


# ---------------------------------------------------------------------------
# SSRF protection
#
# A public "paste any URL" scanner is a server-side request forgery vector:
# without this, a visitor could point it at 127.0.0.1 or at a cloud metadata
# endpoint (169.254.169.254) and read secrets through our server. We refuse
# to fetch anything that does not resolve to a public IP address, and we
# re-check on every redirect hop so an open redirect can't smuggle us inward.
# ---------------------------------------------------------------------------


class BlockedURL(Exception):
    """Raised when a URL points somewhere we refuse to fetch."""


def _ip_is_public(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_public_url(url: str) -> None:
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedURL("Only http:// and https:// addresses can be checked.")
    host = parts.hostname
    if not host:
        raise BlockedURL("That address is missing a domain name.")
    if parts.port is not None and parts.port not in (80, 443):
        raise BlockedURL("Only the standard web ports (80 and 443) can be checked.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise BlockedURL(f"“{host}” did not resolve. Check the spelling and try again.")
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise BlockedURL(f"“{host}” did not resolve.")
    for address in addresses:
        if not _ip_is_public(address):
            raise BlockedURL("That address points to a private network, so it can't be checked.")


class GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate the destination of every redirect before following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


urllib.request.install_opener(urllib.request.build_opener(GuardedRedirectHandler()))


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class RateLimiter:
    def __init__(self, limit: int, window: int) -> None:
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """Return (allowed, seconds_until_reset)."""
        now = time.time()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False, int(self.window - (now - bucket[0])) + 1
            bucket.append(now)
            if len(self._hits) > 5000:          # cheap memory bound
                for stale in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale]
            return True, 0


limiter = RateLimiter(RATE_LIMIT, RATE_WINDOW)
scan_slots = threading.Semaphore(MAX_CONCURRENT_SCANS)


# ---------------------------------------------------------------------------
# Serialising a scan for the JSON API
# ---------------------------------------------------------------------------


def result_to_dict(res: studio.Result) -> dict:
    overall = studio.overall_score(res)
    return {
        "url": res.final_url,
        "title": res.site_title,
        "checked_at": res.fetched_at,
        "word_count": res.word_count,
        "javascript_rendered": res.spa_warning,
        "summary": res.summary,
        "grade": studio.grade(overall)[0],
        "vertical": {
            "key": res.vertical,
            "label": studio.VERTICAL_LABELS[res.vertical],
            "weighting": studio.weighting_sentence(res),
            "detected_from": "set manually" if res.vertical_forced else res.vertical_evidence,
        },
        "scores": {
            "overall": overall,
            "geo": res.geo_score,
            "aeo": res.aeo_score,
            "reviews": res.reviews_score,
            "social": res.social_score,
        },
        "pillars": studio.pillar_percents(res),
        "checks": [asdict(c) for c in res.checks],
        "recommendations": [
            {"label": c.label, "priority": c.priority, "observed": c.detail, "fix": c.fix}
            for c in sorted(
                [c for c in res.checks if c.fix],
                key=lambda c: (studio.PRIORITY_ORDER.get(c.priority, 3), -(c.possible - c.earned)),
            )
        ],
        "crawlers": [
            {"bot": bot, "role": role, "kind": kind, "status": status}
            for bot, role, kind, status in res.crawler_rows
        ],
    }


def run_scan(raw_url: str, vertical: str | None = None) -> studio.Result:
    """Validate, then scan. Raises BlockedURL or ValueError with a plain message."""
    url = raw_url.strip()
    if not url:
        raise ValueError("Enter a website address to check.")
    if vertical and vertical not in studio.VERTICAL_WEIGHTS:
        raise ValueError("That business type isn't one we score for.")
    if "://" in url and not url.startswith(("http://", "https://")):
        raise BlockedURL("Only http:// and https:// addresses can be checked.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    assert_public_url(url)

    if not scan_slots.acquire(blocking=True, timeout=25):
        raise ValueError("The scanner is busy right now. Try again in a moment.")
    try:
        outcome = studio.analyze(url, vertical=vertical or None)
    finally:
        scan_slots.release()

    if isinstance(outcome, str):
        raise ValueError(outcome)
    try:
        studio.append_history(outcome)
    except Exception:
        pass  # history is a nice-to-have, never break a scan over it
    return outcome


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


OG_IMAGE = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#1c1740"/><stop offset="70%" stop-color="#372aac"/>
      <stop offset="100%" stop-color="#0e7490"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#a78bfa"/><stop offset="100%" stop-color="#67e8f9"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <text x="90" y="150" fill="#67e8f9" font-family="monospace" font-size="26"
        letter-spacing="7">SURFACED</text>
  <text x="90" y="290" fill="#ffffff" font-family="Avenir Next, Segoe UI, sans-serif"
        font-size="70" font-weight="700">Will AI assistants</text>
  <text x="90" y="372" fill="#ffffff" font-family="Avenir Next, Segoe UI, sans-serif"
        font-size="70" font-weight="700">find and <tspan fill="url(#accent)">quote</tspan> you?</text>
  <text x="90" y="462" fill="#c9c6ec" font-family="Avenir Next, Segoe UI, sans-serif"
        font-size="30">Free AI visibility check &#183; GEO &#183; AEO &#183; reviews &#183; social</text>
  <rect x="90" y="516" width="220" height="6" rx="3" fill="url(#accent)"/>
</svg>"""


class Surfaced(BaseHTTPRequestHandler):
    server_version = "Surfaced"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"{self.client_ip()} {fmt % args}", flush=True)

    def client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def send_body(self, body: str, status: int = 200, content_type: str = "text/html; charset=utf-8",
                  extra_headers: dict | None = None) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict, status: int = 200) -> None:
        self.send_body(
            json.dumps(payload, indent=2),
            status,
            "application/json; charset=utf-8",
            {"Access-Control-Allow-Origin": "*"},
        )

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parts = urllib.parse.urlparse(self.path)
        route = parts.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parts.query)
        target = (query.get("url") or [""])[0]
        vertical = (query.get("vertical") or [""])[0].strip().lower()

        if route == "/":
            self.send_body(landing_page(BASE_URL))
        elif route == "/health":
            self.send_body("ok", content_type="text/plain; charset=utf-8")
        elif route == "/robots.txt":
            self.send_body(ROBOTS_TXT.replace("{{BASE_URL}}", BASE_URL),
                           content_type="text/plain; charset=utf-8")
        elif route == "/llms.txt":
            self.send_body(LLMS_TXT.replace("{{BASE_URL}}", BASE_URL),
                           content_type="text/plain; charset=utf-8")
        elif route == "/og.svg":
            self.send_body(OG_IMAGE, content_type="image/svg+xml")
        elif route == "/sitemap.xml":
            sitemap = ('<?xml version="1.0" encoding="UTF-8"?>'
                       '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                       f"<url><loc>{BASE_URL}/</loc><lastmod>2026-07-28</lastmod></url>"
                       "</urlset>")
            self.send_body(sitemap, content_type="application/xml; charset=utf-8")
        elif route == "/scan":
            self.handle_scan(target, as_json=False, vertical=vertical)
        elif route == "/api/scan":
            self.handle_scan(target, as_json=True, vertical=vertical)
        else:
            self.send_body(error_page("Page not found",
                                      "That address isn't part of Surfaced.", BASE_URL), 404)

    def handle_scan(self, target: str, as_json: bool, vertical: str = "") -> None:
        if not target:
            if as_json:
                self.send_json({"error": "Add a ?url= parameter, e.g. /api/scan?url=example.com"}, 400)
            else:
                self.send_body(landing_page(BASE_URL))
            return

        allowed, retry_after = limiter.allow(self.client_ip())
        if not allowed:
            minutes = max(1, retry_after // 60)
            message = f"You've used your {RATE_LIMIT} free checks for this hour. Try again in about {minutes} minute(s)."
            if as_json:
                self.send_json({"error": message, "retry_after_seconds": retry_after}, 429)
            else:
                self.send_body(error_page("Hourly limit reached", message, BASE_URL), 429,
                               extra_headers={"Retry-After": str(retry_after)})
            return

        try:
            result = run_scan(target, vertical)
        except (BlockedURL, ValueError) as exc:
            if as_json:
                self.send_json({"error": str(exc)}, 400)
            else:
                self.send_body(error_page("That page couldn't be checked", str(exc), BASE_URL), 400)
            return
        except Exception:
            message = "Something went wrong while fetching that page. Try again in a moment."
            if as_json:
                self.send_json({"error": message}, 500)
            else:
                self.send_body(error_page("Scan failed", message, BASE_URL), 500)
            return

        if as_json:
            self.send_json(result_to_dict(result))
        else:
            self.send_body(studio.render_report(result))


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Surfaced)
    server.daemon_threads = True
    print(f"Surfaced listening on 0.0.0.0:{PORT}  (public URL: {BASE_URL})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
