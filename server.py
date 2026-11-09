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

import base64
import ipaddress
import json
import os
import secrets
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
from pages import landing_page, LLMS_TXT, ROBOTS_TXT, error_page, paid_page
from pwa import APP_SHELL, MANIFEST, SERVICE_WORKER
import billing

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


LEDGER_PATH = os.path.join(DATA_DIR, "ledger.db")
_ledger_local = threading.local()


def ledger() -> "billing.sqlite3.Connection":
    """One SQLite connection per thread — SQLite objects cannot cross threads."""
    conn = getattr(_ledger_local, "conn", None)
    if conn is None:
        conn = billing.connect(LEDGER_PATH)
        billing.init(conn)
        _ledger_local.conn = conn
    return conn


def access_key_for(session_id: str) -> str:
    """
    Derive the buyer's access key from their Stripe session id.

    Deterministic, so /paid can show the key to whoever completed the checkout
    without the key ever being stored in plaintext — the ledger holds only its
    SHA-256. The Stripe session id is the bearer proof, and it is only ever
    given to the browser that paid.
    """
    secret = (os.environ.get("SURFACED_KEY_SECRET")
              or billing.WEBHOOK_SECRET or "surfaced-dev-only")
    digest = billing.hmac.new(secret.encode(), session_id.encode(),
                              billing.hashlib.sha256).digest()
    return "sk_" + base64.urlsafe_b64encode(digest).decode().rstrip("=")[:32]


ICON_ROUTES = {
    "/icon-192.png": "icon-192.png",
    "/icon-512.png": "icon-512.png",
    "/icon-180.png": "icon-180.png",
    "/icon-maskable.png": "icon-maskable.png",
}
ICON_DIR = os.path.dirname(os.path.abspath(__file__))


class Surfaced(BaseHTTPRequestHandler):
    server_version = "Surfaced"
    protocol_version = "HTTP/1.1"
    paid_key = ""
    idem_key = ""

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

    def send_icon(self, filename: str) -> None:
        try:
            with open(os.path.join(ICON_DIR, filename), "rb") as fh:
                data = fh.read()
        except OSError:
            self.send_body("Icon not found", 404, "text/plain; charset=utf-8")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        route = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if route == "/api/stripe/webhook":
            self.handle_webhook()
        elif route == "/api/checkout":
            self.handle_checkout()
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_GET(self):
        parts = urllib.parse.urlparse(self.path)
        route = parts.path.rstrip("/") or "/"
        query = urllib.parse.parse_qs(parts.query)
        target = (query.get("url") or [""])[0]
        vertical = (query.get("vertical") or [""])[0].strip().lower()
        self.paid_key = (query.get("key") or [""])[0].strip()
        self.idem_key = (query.get("idempotency") or [""])[0].strip()[:120]

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
        elif route == "/paid":
            self.handle_paid_landing((query.get("session_id") or [""])[0].strip())
        elif route == "/api/credits":
            k = self.paid_key
            self.send_json({"credits": billing.balance_of(ledger(), k) if k else 0})
        elif route == "/app":
            self.send_body(APP_SHELL)
        elif route == "/manifest.webmanifest":
            self.send_body(MANIFEST, content_type="application/manifest+json; charset=utf-8")
        elif route == "/sw.js":
            # Scope is the whole site, so the worker must not be cached by the browser.
            self.send_body(SERVICE_WORKER,
                           content_type="application/javascript; charset=utf-8",
                           extra_headers={"Cache-Control": "no-cache",
                                          "Service-Worker-Allowed": "/"})
        elif route in ICON_ROUTES:
            self.send_icon(ICON_ROUTES[route])
        elif route == "/scan":
            self.handle_scan(target, as_json=False, vertical=vertical)
        elif route == "/api/scan":
            self.handle_scan(target, as_json=True, vertical=vertical)
        else:
            self.send_body(error_page("Page not found",
                                      "That address isn't part of Surfaced.", BASE_URL), 404)

    def handle_paid_scan(self, target: str, vertical: str, key: str,
                         idem: str) -> None:
        """
        A scan paid for with a credit.

        The credit is reserved first, then committed only if the scan actually
        produced a report. Any failure refunds it — the customer never pays for
        a run that returned nothing.
        """
        conn = ledger()
        if not idem:
            self.send_json({"error": "An idempotency key is required for a paid scan."}, 400)
            return
        try:
            res = billing.reserve(conn, key, idem, target)
        except ValueError as exc:
            self.send_json({"error": str(exc), "credits": billing.balance_of(conn, key)}, 402)
            return

        # This exact intent already ran: return what it produced, spend nothing.
        if res.replayed:
            if res.result:
                payload = json.loads(res.result)
                payload["replayed"] = True
                self.send_json(payload)
            else:
                self.send_json({"error": "That scan is still running. Try again shortly."}, 409)
            return

        try:
            result = run_scan(target, vertical)
            payload = result_to_dict(result)
            payload["credits"] = billing.balance_of(conn, key)
            billing.commit_run(conn, res.run_id, json.dumps(payload))
            self.send_json(payload)
        except (BlockedURL, ValueError) as exc:
            billing.refund_run(conn, res.run_id)
            self.send_json({"error": str(exc), "credit_refunded": True}, 400)
        except Exception:
            billing.refund_run(conn, res.run_id)
            self.send_json({"error": "The scan failed. Your credit was not used.",
                            "credit_refunded": True}, 500)

    def handle_webhook(self) -> None:
        """
        Stripe's payment notification. The only thing that can mint credit.

        Always answers 200 once the signature checks out, including for events
        already processed — a non-2xx makes Stripe retry for up to three days.
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 1_000_000:
            self.send_json({"error": "Bad request body."}, 400)
            return
        payload = self.rfile.read(length)

        try:
            event = billing.verify_signature(payload, self.headers.get("Stripe-Signature", ""))
        except ValueError as exc:
            # Unverified means unpaid as far as we are concerned.
            self.send_json({"error": str(exc)}, 400)
            return

        mapped = billing.credits_for_event(event)
        if mapped is None:
            self.send_json({"ignored": True})      # 200: nothing to retry
            return

        event_id, object_id, email, credits = mapped
        try:
            billing.grant_credits(
                ledger(), event_id=event_id, object_id=object_id, email=email,
                credits=credits, access_key=access_key_for(object_id))
        except Exception:
            # A real failure: let Stripe retry rather than losing the payment.
            self.send_json({"error": "Could not record the payment."}, 500)
            return
        self.send_json({"received": True})

    def handle_checkout(self) -> None:
        if not billing.configured():
            self.send_json({"error": "Payments are not configured on this server."}, 503)
            return
        try:
            url = billing.create_checkout_session(BASE_URL, secrets.token_urlsafe(12))
        except billing.BillingError as exc:
            self.send_json({"error": str(exc)}, 502)
            return
        self.send_json({"url": url})

    def handle_paid_landing(self, session_id: str) -> None:
        """Shown after checkout: confirms with Stripe, then reveals the key once."""
        if not session_id:
            self.send_body(error_page("No checkout session",
                                      "That link is missing its session id.", BASE_URL), 400)
            return
        try:
            session = billing.retrieve_session(session_id)
        except billing.BillingError as exc:
            self.send_body(error_page("Could not confirm the payment", str(exc), BASE_URL), 502)
            return
        if session.get("payment_status") != "paid":
            self.send_body(error_page("Payment not completed",
                                      "Stripe has not marked this checkout as paid.",
                                      BASE_URL), 402)
            return

        key = access_key_for(session.get("id", session_id))
        credits = billing.balance_of(ledger(), key)
        self.send_body(paid_page(key, credits, BASE_URL))

    def handle_scan(self, target: str, as_json: bool, vertical: str = "") -> None:
        if not target:
            if as_json:
                self.send_json({"error": "Add a ?url= parameter, e.g. /api/scan?url=example.com"}, 400)
            else:
                self.send_body(landing_page(BASE_URL))
            return

        # A paid scan skips the free-tier limiter; its limit is the credit.
        if as_json and self.paid_key:
            self.handle_paid_scan(target, vertical, self.paid_key, self.idem_key)
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
    # A previous process may have died holding customers' credits.
    try:
        swept = billing.sweep_stale(ledger())
        if swept:
            print(f"Refunded {swept} scan credit(s) orphaned by an earlier restart.", flush=True)
    except Exception as exc:
        print(f"Ledger sweep skipped: {exc}", flush=True)

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Surfaced)
    server.daemon_threads = True
    print(f"Surfaced listening on 0.0.0.0:{PORT}  (public URL: {BASE_URL})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
