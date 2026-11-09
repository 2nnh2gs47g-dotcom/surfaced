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

ENVIRONMENT VARIABLES (all optional unless payments are on)
    PORT                         port to bind          (default 8000)
    SURFACED_BASE_URL            public URL, used for canonical/OG tags
                                 and Stripe success/cancel URLs
    SURFACED_DATA_DIR            where scan_history.json lives
    SURFACED_RATE_LIMIT          preview scans per IP per hour (default 12)
    SURFACED_PAID_RATE_LIMIT     full-report loads per IP per hour (default 30)
    SURFACED_CHECKOUT_RATE_LIMIT checkout starts per IP per hour (default 8)
    SURFACED_PAYMENTS            on/true/1/yes to charge; otherwise full reports are free
    STRIPE_SECRET_KEY            sk_test_ or sk_live_; required when payments are on
    STRIPE_PRICE_ID              optional price_ id; otherwise Checkout uses price_data
    SURFACED_PRICE_CENTS         charge and displayed price in cents (default 2000)
    GOOGLE_PLACES_API_KEY        enables live Google rating scoring
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import threading
import time
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ai_visibility_studio as studio
import payments
from pages import ROBOTS_TXT, error_page, landing_page, legal_page, llms_txt, teaser_page

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORT = int(os.environ.get("PORT", "8000"))
DATA_DIR = os.environ.get("SURFACED_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
RATE_LIMIT = int(os.environ.get("SURFACED_RATE_LIMIT", "12"))
PAID_RATE_LIMIT = int(os.environ.get("SURFACED_PAID_RATE_LIMIT", "30"))
CHECKOUT_RATE_LIMIT = int(os.environ.get("SURFACED_CHECKOUT_RATE_LIMIT", "8"))
RATE_WINDOW = 3600          # one hour
MAX_CONCURRENT_SCANS = 4    # protect a small free-tier instance
NO_STORE = {"Cache-Control": "private, no-store"}


def public_base_url() -> str:
    return os.environ.get("SURFACED_BASE_URL", f"http://localhost:{PORT}").rstrip("/")


def _redact_session_ids(line: str) -> str:
    return re.sub(r"(session_id=)[^&\s\"]+", r"\1redacted", line)

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
paid_limiter = RateLimiter(PAID_RATE_LIMIT, RATE_WINDOW)
checkout_limiter = RateLimiter(CHECKOUT_RATE_LIMIT, RATE_WINDOW)
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


def top_fix(res: studio.Result) -> dict | None:
    ranked = sorted(
        (c for c in res.checks if c.fix),
        key=lambda c: (studio.PRIORITY_ORDER.get(c.priority, 3), -(c.possible - c.earned)),
    )
    if not ranked:
        return None
    fix = ranked[0]
    return {
        "label": fix.label,
        "priority": fix.priority,
        "observed": fix.detail,
        "fix": fix.fix,
    }


def teaser_payload(res: studio.Result, payment_error: str = "") -> dict:
    """Preview JSON. Deliberately omits pillar scores, checks, crawlers, and the other fixes."""
    overall = studio.overall_score(res)
    payload = {
        "access": "teaser",
        "paid": False,
        "price": {"amount_cents": payments.price_cents(), "currency": "usd"},
        "url": res.final_url,
        "title": res.site_title,
        "checked_at": res.fetched_at,
        "grade": studio.grade(overall)[0],
        "vertical": {
            "key": res.vertical,
            "label": studio.VERTICAL_LABELS[res.vertical],
            "weighting": studio.weighting_sentence(res),
            "detected_from": "set manually" if res.vertical_forced else res.vertical_evidence,
        },
        "scores": {"overall": overall},
        "top_fix": top_fix(res),
        "checkout": {"method": "POST", "path": "/checkout"},
    }
    if payment_error:
        payload["payment_error"] = payment_error
    return payload


def full_payload(res: studio.Result) -> dict:
    payload = result_to_dict(res)
    if payments.payments_enabled():
        payload["access"] = "full"
        payload["paid"] = True
    return payload


def paid_report_html(res: studio.Result) -> str:
    banner = (
        '<p style="max-width:880px;margin:0 auto;padding:16px 24px 0;'
        'font:14px/1.5 Avenir Next,Segoe UI,sans-serif;color:#5d5a78">'
        "This link is your receipt for this website. Reopen it to see the full report again. "
        "It only unlocks this address.</p>"
    )
    html = studio.render_report(res)
    html = html.replace("<head>", '<head><meta name="robots" content="noindex">', 1)
    return html.replace("</style></head><body>", "</style></head><body>" + banner, 1)


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


def og_image() -> str:
    if payments.payments_enabled():
        subtitle = f"Preview free &#183; full report {payments.price_label()} &#183; GEO &#183; AEO"
    else:
        subtitle = "Free AI visibility check &#183; GEO &#183; AEO &#183; reviews &#183; social"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
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
        font-size="30">{subtitle}</text>
  <rect x="90" y="516" width="220" height="6" rx="3" fill="url(#accent)"/>
</svg>"""


class Surfaced(BaseHTTPRequestHandler):
    server_version = "Surfaced"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"{self.client_ip()} {_redact_session_ids(fmt % args)}", flush=True)

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

    def send_json(self, payload: dict, status: int = 200, extra_headers: dict | None = None) -> None:
        headers = {"Access-Control-Allow-Origin": "*"}
        headers.update(extra_headers or {})
        self.send_body(
            json.dumps(payload, indent=2),
            status,
            "application/json; charset=utf-8",
            headers,
        )

    def redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Cache-Control", "private, no-store")
        self.end_headers()

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
        session_id = (query.get("session_id") or [""])[0].strip()
        canceled = (query.get("canceled") or [""])[0] == "1"
        base = public_base_url()

        if route == "/":
            self.send_body(landing_page(
                base,
                payments_on=payments.payments_enabled(),
                price_cents=payments.price_cents(),
            ))
        elif route == "/health":
            self.send_body("ok", content_type="text/plain; charset=utf-8")
        elif route == "/robots.txt":
            self.send_body(ROBOTS_TXT.replace("{{BASE_URL}}", base),
                           content_type="text/plain; charset=utf-8")
        elif route == "/llms.txt":
            self.send_body(
                llms_txt(base, payments.payments_enabled(), payments.price_label()),
                content_type="text/plain; charset=utf-8",
            )
        elif route == "/og.svg":
            self.send_body(og_image(), content_type="image/svg+xml")
        elif route == "/sitemap.xml":
            locs = ["/", "/terms", "/privacy", "/refunds"]
            body = "".join(
                f"<url><loc>{base}{loc}</loc><lastmod>2026-11-09</lastmod></url>" for loc in locs
            )
            sitemap = ('<?xml version="1.0" encoding="UTF-8"?>'
                       '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                       f"{body}</urlset>")
            self.send_body(sitemap, content_type="application/xml; charset=utf-8")
        elif route in ("/terms", "/privacy", "/refunds"):
            self.send_body(legal_page(route, base))
        elif route == "/scan":
            self.handle_scan(target, as_json=False, vertical=vertical,
                             session_id=session_id, canceled=canceled)
        elif route == "/api/scan":
            self.handle_scan(target, as_json=True, vertical=vertical,
                             session_id=session_id, canceled=canceled)
        elif route == "/checkout":
            self.send_body(error_page(
                "Start from a check",
                "Run a check, then use Get the full report on the preview.",
                base,
            ), 405)
        else:
            self.send_body(error_page("Page not found",
                                      "That address isn't part of Surfaced.", base), 404)

    def do_POST(self):
        parts = urllib.parse.urlparse(self.path)
        route = parts.path.rstrip("/") or "/"
        if route == "/checkout":
            self.handle_checkout()
        else:
            self.send_body(error_page("Page not found",
                                      "That address isn't part of Surfaced.", public_base_url()), 404)

    def handle_checkout(self) -> None:
        base = public_base_url()
        # Read the body first. Rejecting a POST before consuming Content-Length
        # leaves those bytes on a keep-alive connection and the next request breaks.
        try:
            form = self._read_form()
        except ValueError as exc:
            self.send_body(error_page("Checkout failed", str(exc), base), 400)
            return
        if not payments.payments_enabled():
            self.send_body(error_page(
                "Payments are off",
                "Full reports are free right now. Run a check from the home page.",
                base,
            ), 400)
            return
        if not self._origin_allowed():
            self.send_body(error_page(
                "Checkout blocked",
                "Start checkout from the Surfaced site.",
                base,
            ), 403)
            return

        allowed, retry_after = checkout_limiter.allow(self.client_ip())
        if not allowed:
            minutes = max(1, retry_after // 60)
            message = (f"Too many checkout attempts from this network. "
                       f"Try again in about {minutes} minute(s).")
            self.send_body(error_page("Hourly limit reached", message, base), 429,
                           extra_headers={"Retry-After": str(retry_after)})
            return

        raw_url = form.get("url", "")
        vertical = form.get("vertical", "").strip().lower()
        try:
            target = payments.canonical_target(raw_url)
            assert_public_url(target)
            if vertical and vertical not in studio.VERTICAL_WEIGHTS:
                raise ValueError("That business type isn't one we score for.")
            hosted = payments.create_checkout_session(
                target,
                vertical,
                base,
                idempotency_key=_checkout_key(self.client_ip(), target, vertical),
            )
        except (payments.PaymentError, BlockedURL, ValueError) as exc:
            self.send_body(error_page("Checkout couldn't start", str(exc), base), 400)
            return
        self.redirect(hosted)

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parts = urllib.parse.urlparse(origin)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        host_header = self.headers.get("Host", "").split(":")[0].lower()
        base_host = (urllib.parse.urlparse(public_base_url()).hostname or "").lower()
        return parts.hostname.lower() in {host for host in (host_header, base_host) if host}

    def _read_form(self) -> dict[str, str]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.close_connection = True
            raise ValueError("The checkout form couldn't be read.")
        if length <= 0 or length > 8000:
            # Don't buffer a huge body. Close so the unread bytes aren't a new request.
            self.close_connection = True
            raise ValueError("The checkout form couldn't be read.")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        parsed = urllib.parse.parse_qs(raw, keep_blank_values=True)
        return {key: values[0] for key, values in parsed.items() if values}

    def _reject_limited(self, message: str, retry_after: int, as_json: bool) -> None:
        if as_json:
            self.send_json(
                {"error": message, "retry_after_seconds": retry_after},
                429,
                extra_headers={**NO_STORE, "Retry-After": str(retry_after)},
            )
        else:
            self.send_body(
                error_page("Hourly limit reached", message, public_base_url()),
                429,
                extra_headers={**NO_STORE, "Retry-After": str(retry_after)},
            )

    def handle_scan(self, target: str, as_json: bool, vertical: str = "",
                    session_id: str = "", canceled: bool = False) -> None:
        base = public_base_url()
        if not target:
            if as_json:
                self.send_json({"error": "Add a ?url= parameter, e.g. /api/scan?url=example.com"}, 400)
            else:
                self.send_body(landing_page(
                    base,
                    payments_on=payments.payments_enabled(),
                    price_cents=payments.price_cents(),
                ))
            return

        paid = False
        paid_vertical = ""
        notice = ""
        # The iOS client calls GET /api/scan?url= with no session id. While
        # payments are off it still receives result_to_dict. While payments
        # are on, an unpaid call gets teaser_payload and will not decode.
        if payments.payments_enabled() and session_id:
            if not payments.session_id_ok(session_id):
                notice = "That payment reference isn't valid."
            else:
                allowed, retry_after = paid_limiter.allow(self.client_ip())
                if not allowed:
                    minutes = max(1, retry_after // 60)
                    self._reject_limited(
                        "You've reopened the full report too many times this hour. "
                        f"Wait about {minutes} minute(s) and open the same link again.",
                        retry_after,
                        as_json,
                    )
                    return
                check = payments.verify_paid_session(session_id, target, vertical)
                if check.ok:
                    paid = True
                    paid_vertical = check.vertical
                else:
                    notice = check.message

        if not paid:
            allowed, retry_after = limiter.allow(self.client_ip())
            if not allowed:
                minutes = max(1, retry_after // 60)
                if payments.payments_enabled():
                    message = (f"You've used your {RATE_LIMIT} previews for this hour. "
                               f"Try again in about {minutes} minute(s).")
                else:
                    message = (f"You've used your {RATE_LIMIT} free checks for this hour. "
                               f"Try again in about {minutes} minute(s).")
                self._reject_limited(message, retry_after, as_json)
                return

        scan_vertical = paid_vertical if paid else vertical
        try:
            result = run_scan(target, scan_vertical)
        except (BlockedURL, ValueError) as exc:
            message = str(exc)
            if paid:
                message += " Your payment is still valid — reopen this link to try again."
            if as_json:
                self.send_json({"error": message}, 400, extra_headers=NO_STORE)
            else:
                self.send_body(error_page("That page couldn't be checked", message, base), 400,
                               extra_headers=NO_STORE)
            return
        except Exception:
            message = "Something went wrong while fetching that page. Try again in a moment."
            if paid:
                message += " Your payment is still valid — reopen this link to try again."
            if as_json:
                self.send_json({"error": message}, 500, extra_headers=NO_STORE)
            else:
                self.send_body(error_page("Scan failed", message, base), 500, extra_headers=NO_STORE)
            return

        if not payments.payments_enabled() or paid:
            if as_json:
                self.send_json(full_payload(result), extra_headers=NO_STORE)
            else:
                body = studio.render_report(result) if not payments.payments_enabled() else paid_report_html(result)
                self.send_body(body, extra_headers=NO_STORE)
            return

        if as_json:
            self.send_json(teaser_payload(result, notice), extra_headers=NO_STORE)
            return
        try:
            requested = payments.canonical_target(target)
        except payments.PaymentError:
            requested = target.strip()
        self.send_body(teaser_page(
            base_url=base,
            title=result.site_title,
            requested_url=requested,
            final_url=result.final_url,
            grade=studio.grade(studio.overall_score(result))[0],
            overall=studio.overall_score(result),
            vertical_label=studio.VERTICAL_LABELS[result.vertical],
            weighting=studio.weighting_sentence(result),
            detected_from=("set manually" if result.vertical_forced else result.vertical_evidence),
            top_fix=top_fix(result),
            price_label=payments.price_label(),
            vertical=scan_vertical,
            message=notice,
            canceled=canceled,
        ), extra_headers=NO_STORE)


def _checkout_key(ip: str, target: str, vertical: str) -> str:
    window = int(time.time()) // 120
    return hashlib.sha256(f"{ip}|{target}|{vertical}|{window}".encode()).hexdigest()


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Surfaced)
    server.daemon_threads = True
    problem = payments.config_problem()
    if payments.payments_enabled():
        price = payments.price_label()
        using = payments.price_id() or "price_data"
        print(f"Payments on: {price} per report ({using})", flush=True)
    else:
        print("Payments off: full reports are free", flush=True)
        if problem:
            print(problem, flush=True)
    print(f"Surfaced listening on 0.0.0.0:{PORT}  (public URL: {public_base_url()})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
