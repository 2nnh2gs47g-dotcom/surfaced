#!/usr/bin/env python3
"""
Stripe Checkout for one Surfaced report.

Payments stay off unless SURFACED_PAYMENTS is on and STRIPE_SECRET_KEY is a
secret key. The paid credential is the Checkout Session id. On return we
retrieve that session from Stripe and require:

  * payment_status paid and status complete
  * metadata url equal to the requested website
  * metadata vertical equal to the requested business type, when one was sent
  * amount_total equal to SURFACED_PRICE_CENTS and currency usd
  * livemode matching the key (sk_test_ vs sk_live_)

Nothing about the purchase is stored on disk. Render can restart and the
same success link still verifies, because Stripe holds the session.

A webhook is not used. The report is the HTTP response after this check.
A webhook cannot show that page if the browser never comes back, and marking
a URL as paid for everyone would let the next visitor skip payment. The
success link is the receipt. The teaser page can accept the session id again.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


class PaymentError(Exception):
    """A checkout or verification failure with a message safe to show."""


SESSION_ID_RE = re.compile(r"^cs_(?:test|live)_[A-Za-z0-9]{10,200}$")
PRICE_ID_RE = re.compile(r"^price_[A-Za-z0-9]+$")
_CHECKOUT_HOSTS = {"checkout.stripe.com"}

# Tests assign a callable(method, path, params, idempotency_key) -> dict.
_transport = None


def set_transport(fn) -> None:
    global _transport
    _transport = fn


def flag_requested() -> bool:
    return os.environ.get("SURFACED_PAYMENTS", "").strip().lower() in {"1", "true", "on", "yes"}


def secret_key() -> str:
    return os.environ.get("STRIPE_SECRET_KEY", "").strip()


def price_id() -> str:
    return os.environ.get("STRIPE_PRICE_ID", "").strip()


def price_cents() -> int:
    raw = os.environ.get("SURFACED_PRICE_CENTS", "2000").strip() or "2000"
    try:
        return int(raw)
    except ValueError:
        return 0


def price_label(cents: int | None = None) -> str:
    amount = price_cents() if cents is None else cents
    if amount % 100 == 0:
        return f"${amount // 100}"
    return f"${amount / 100:.2f}"


def config_problem() -> str | None:
    """Why payments cannot turn on, or None when the flag is off or config is valid."""
    if not flag_requested():
        return None
    key = secret_key()
    if not key:
        return "SURFACED_PAYMENTS is on but STRIPE_SECRET_KEY is empty."
    if not key.startswith(("sk_test_", "sk_live_")):
        return "STRIPE_SECRET_KEY must be a Stripe secret key (sk_test_ or sk_live_)."
    cents = price_cents()
    if cents < 50:
        return "SURFACED_PRICE_CENTS must be a whole number of cents, at least 50 (2000 = $20)."
    pid = price_id()
    if pid and not PRICE_ID_RE.fullmatch(pid):
        return "STRIPE_PRICE_ID must look like price_..."
    return None


def payments_enabled() -> bool:
    return flag_requested() and config_problem() is None


def canonical_target(raw: str) -> str:
    """
    Normalize a scan target so the value stored in Checkout metadata matches
    the value on the success URL. This does not fetch the URL.
    """
    url = (raw or "").strip()
    if not url:
        raise PaymentError("Enter a website address to check.")
    if "://" in url and not url.startswith(("http://", "https://")):
        raise PaymentError("Only http:// and https:// addresses can be checked.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parts = urllib.parse.urlsplit(url)
    if parts.username or parts.password:
        raise PaymentError("That address can't include a username or password.")
    host = parts.hostname
    if not host:
        raise PaymentError("That address is missing a domain name.")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise PaymentError("That domain name isn't valid.")
    host = host.lower().rstrip(".")
    if parts.port is not None and parts.port not in (80, 443):
        raise PaymentError("Only the standard web ports (80 and 443) can be checked.")
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    canon = urllib.parse.urlunsplit((parts.scheme.lower(), host, path, parts.query, ""))
    if len(canon) > 500:
        raise PaymentError("That address is too long to attach to a payment.")
    return canon


def session_id_ok(session_id: str) -> bool:
    return bool(SESSION_ID_RE.fullmatch(session_id or ""))


class PaidSession:
    def __init__(self, ok: bool, message: str = "", vertical: str = "") -> None:
        self.ok = ok
        self.message = message
        self.vertical = vertical


def verify_paid_session(session_id: str, raw_url: str, vertical: str = "") -> PaidSession:
    """Retrieve the Checkout Session from Stripe. The redirect alone is not trusted."""
    if not session_id_ok(session_id):
        return PaidSession(False, "That payment reference isn't valid.")
    try:
        target = canonical_target(raw_url)
    except PaymentError as exc:
        return PaidSession(False, str(exc))
    try:
        session = stripe_request("GET", "/v1/checkout/sessions/" + urllib.parse.quote(session_id, safe=""))
    except PaymentError as exc:
        return PaidSession(False, str(exc))
    return _assess_session(session, target, (vertical or "").strip().lower())


def _assess_session(session: dict, target: str, vertical: str) -> PaidSession:
    if not isinstance(session, dict):
        return PaidSession(False, "Stripe didn't return a payment we could read.")
    meta = session.get("metadata") or {}
    if not isinstance(meta, dict):
        return PaidSession(False, "That payment is missing the website it was for.")
    if meta.get("product") != "surfaced-report":
        return PaidSession(False, "That payment isn't for a Surfaced report.")
    if session.get("mode") != "payment":
        return PaidSession(False, "That payment isn't a one-time report purchase.")
    if session.get("payment_status") != "paid" or session.get("status") != "complete":
        return PaidSession(False, "That payment isn't complete.")
    if meta.get("url") != target:
        return PaidSession(False, "That payment is for a different website.")
    meta_vertical = (meta.get("vertical") or "").strip().lower()
    if vertical and vertical != meta_vertical:
        return PaidSession(False, "That payment is for a different business type.")
    currency = str(session.get("currency") or "").lower()
    amount = session.get("amount_total")
    if currency != "usd" or amount != price_cents():
        return PaidSession(False, "That payment doesn't match the report price.")
    livemode = session.get("livemode")
    key = secret_key()
    if key.startswith("sk_test_") and livemode is not False:
        return PaidSession(False, "That payment doesn't match this server's Stripe test mode.")
    if key.startswith("sk_live_") and livemode is not True:
        return PaidSession(False, "That payment doesn't match this server's Stripe live mode.")
    return PaidSession(True, "", meta_vertical)


def create_checkout_session(raw_url: str, vertical: str, base_url: str, idempotency_key: str) -> str:
    """Create a Checkout Session and return its hosted page URL."""
    if not payments_enabled():
        raise PaymentError("Payments are not turned on.")
    target = canonical_target(raw_url)
    vertical = (vertical or "").strip().lower()
    base = base_url.rstrip("/")
    query = urllib.parse.urlencode({"url": target})
    if vertical:
        query += "&" + urllib.parse.urlencode({"vertical": vertical})
    success = f"{base}/scan?{query}&session_id={{CHECKOUT_SESSION_ID}}"
    cancel = f"{base}/scan?{query}&canceled=1"
    params = {
        "mode": "payment",
        "success_url": success,
        "cancel_url": cancel,
        "client_reference_id": "surfaced-report",
        "metadata[product]": "surfaced-report",
        "metadata[url]": target,
        "payment_method_types[0]": "card",
        "line_items[0][quantity]": "1",
    }
    # Omit an empty vertical. Stripe drops or rejects blank metadata values,
    # and a missing key means the scan should detect the business type.
    if vertical:
        params["metadata[vertical]"] = vertical
    pid = price_id()
    if pid:
        params["line_items[0][price]"] = pid
    else:
        params["line_items[0][price_data][currency]"] = "usd"
        params["line_items[0][price_data][unit_amount]"] = str(price_cents())
        params["line_items[0][price_data][product_data][name]"] = "Surfaced full AI visibility report"
        params["line_items[0][price_data][product_data][description]"] = (
            "One report for one website. Overall scores, crawler access, and the fix list."
        )
    session = stripe_request("POST", "/v1/checkout/sessions", params, idempotency_key=idempotency_key)
    hosted = session.get("url") if isinstance(session, dict) else None
    if not _hosted_checkout_url(hosted):
        raise PaymentError("Stripe didn't return a checkout page.")
    return hosted


def _hosted_checkout_url(url: object) -> bool:
    if not isinstance(url, str) or not url.startswith("https://"):
        return False
    host = urllib.parse.urlparse(url).hostname
    return host in _CHECKOUT_HOSTS


def stripe_request(method: str, path: str, params: dict | None = None, idempotency_key: str | None = None) -> dict:
    if _transport is not None:
        result = _transport(method, path, params or {}, idempotency_key)
        if not isinstance(result, dict):
            raise PaymentError("Stripe didn't return a payment we could read.")
        return result
    key = secret_key()
    if not key:
        raise PaymentError("Stripe isn't configured.")
    body = None
    headers = {"Authorization": "Bearer " + key}
    if method != "GET":
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = _encode_form(params or {}).encode("utf-8")
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(
        "https://api.stripe.com" + path,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        print(f"stripe {method} {path} -> {exc.code} {detail}", flush=True)
        raise PaymentError("Stripe couldn't complete that step. Try again in a moment.")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        raise PaymentError("We couldn't reach Stripe. Try again in a moment.")
    if not isinstance(payload, dict):
        raise PaymentError("Stripe didn't return a payment we could read.")
    return payload


def _encode_form(params: dict) -> str:
    # Bracket keys stay literal so Stripe nests metadata[url]. The session
    # placeholder must also stay literal; Stripe does not expand %7B...%7D.
    parts = []
    for key, value in params.items():
        encoded_key = urllib.parse.quote(str(key), safe="[]")
        encoded_value = urllib.parse.quote(str(value), safe="")
        parts.append(f"{encoded_key}={encoded_value}")
    return "&".join(parts).replace("%7BCHECKOUT_SESSION_ID%7D", "{CHECKOUT_SESSION_ID}")
