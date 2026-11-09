#!/usr/bin/env python3
"""Gating, Checkout session checks, and the paid HTTP routes. Stripe is mocked."""

from __future__ import annotations

import json
import os
import re
import threading
import unittest
import urllib.parse
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import ai_visibility_studio as studio
import payments
import server
from pages import landing_page, legal_page

SESSION = "cs_test_abcdefghij"
TARGET = "https://example.com/"


def sample_result(url: str = TARGET) -> studio.Result:
    return studio.Result(
        url=url,
        final_url=url,
        fetched_at="January 01, 2026 at 00:00",
        site_title="Example Co",
        geo_score=80,
        aeo_score=60,
        reviews_score=40,
        social_score=40,
        checks=[
            studio.Check(
                "GEO · Access", "AI citation crawlers allowed", 0, 30,
                "0 of 6 citation crawlers can reach the site",
                fix="UNIQUE_TOP_FIX allow the citation crawlers.",
                priority="High",
            ),
            studio.Check(
                "GEO · Trust", "Visible byline", 0, 5,
                "No byline found",
                fix="UNIQUE_HIDDEN_FIX add a byline.",
                priority="Low",
            ),
            studio.Check(
                "GEO · Trust", "Title length", 5, 5,
                "Title is fine", fix="", priority="",
            ),
        ],
        crawler_rows=[("UNIQUEBOT", "training", "Training", "allowed")],
        word_count=400,
        summary="UNIQUE_SUMMARY_SHOULD_STAY_HIDDEN GEO 80 AEO 60.",
        vertical="general",
        vertical_evidence="schema.org Organization",
        vertical_forced=False,
    )


def paid_session(url: str = TARGET, vertical: str = "", amount: int = 2000,
                 livemode: bool = False, status: str = "complete",
                 payment_status: str = "paid", currency: str = "usd",
                 product: str = "surfaced-report") -> dict:
    return {
        "id": SESSION,
        "object": "checkout.session",
        "mode": "payment",
        "status": status,
        "payment_status": payment_status,
        "amount_total": amount,
        "currency": currency,
        "livemode": livemode,
        "metadata": {"product": product, "url": url, "vertical": vertical},
    }


class StripeFake:
    def __init__(self, session=None, create=None, error: str = "") -> None:
        self.session = session if session is not None else paid_session()
        self.create = create or {
            "id": SESSION,
            "url": "https://checkout.stripe.com/c/pay/" + SESSION,
        }
        self.error = error
        self.calls: list[tuple] = []

    def __call__(self, method, path, params, idempotency_key):
        self.calls.append((method, path, dict(params), idempotency_key))
        if self.error:
            raise payments.PaymentError(self.error)
        if method == "POST":
            return self.create
        return self.session


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            name: os.environ.get(name)
            for name in ("SURFACED_PAYMENTS", "STRIPE_SECRET_KEY", "STRIPE_PRICE_ID", "SURFACED_PRICE_CENTS")
        }

    def tearDown(self) -> None:
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_off_without_a_key(self) -> None:
        os.environ.pop("SURFACED_PAYMENTS", None)
        os.environ.pop("STRIPE_SECRET_KEY", None)
        self.assertFalse(payments.payments_enabled())
        self.assertIsNone(payments.config_problem())

    def test_flag_without_key_stays_off(self) -> None:
        os.environ["SURFACED_PAYMENTS"] = "on"
        os.environ["STRIPE_SECRET_KEY"] = ""
        self.assertFalse(payments.payments_enabled())
        self.assertIn("STRIPE_SECRET_KEY", payments.config_problem() or "")

    def test_test_key_enables_default_price(self) -> None:
        os.environ["SURFACED_PAYMENTS"] = "yes"
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_unit"
        os.environ.pop("STRIPE_PRICE_ID", None)
        os.environ["SURFACED_PRICE_CENTS"] = "2000"
        self.assertTrue(payments.payments_enabled())
        self.assertEqual(payments.price_label(), "$20")

    def test_bad_price_or_id_stays_off(self) -> None:
        os.environ["SURFACED_PAYMENTS"] = "on"
        os.environ["STRIPE_SECRET_KEY"] = "sk_live_unit"
        os.environ["SURFACED_PRICE_CENTS"] = "20"
        self.assertFalse(payments.payments_enabled())
        os.environ["SURFACED_PRICE_CENTS"] = "2000"
        os.environ["STRIPE_PRICE_ID"] = "not-a-price"
        self.assertFalse(payments.payments_enabled())


class CanonicalAndSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["SURFACED_PAYMENTS"] = "on"
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_unit"
        os.environ["SURFACED_PRICE_CENTS"] = "2000"
        os.environ.pop("STRIPE_PRICE_ID", None)
        self.fake = StripeFake()
        payments.set_transport(self.fake)

    def tearDown(self) -> None:
        payments.set_transport(None)

    def test_canonical_target(self) -> None:
        self.assertEqual(payments.canonical_target("Example.com/path/"), "https://example.com/path")
        self.assertEqual(payments.canonical_target("https://example.com:443/"), "https://example.com/")
        self.assertEqual(payments.canonical_target("http://example.com:80/a"), "http://example.com/a")
        with self.assertRaises(payments.PaymentError):
            payments.canonical_target("https://user:pass@example.com/")
        with self.assertRaises(payments.PaymentError):
            payments.canonical_target("https://example.com:22/")
        with self.assertRaises(payments.PaymentError):
            payments.canonical_target("ftp://example.com/")

    def test_malformed_session_does_not_call_stripe(self) -> None:
        result = payments.verify_paid_session("cs_test_abc/../../x", TARGET)
        self.assertFalse(result.ok)
        self.assertEqual(self.fake.calls, [])

    def test_paid_session_matches_url_and_amount(self) -> None:
        result = payments.verify_paid_session(SESSION, "Example.com")
        self.assertTrue(result.ok)
        self.assertEqual(self.fake.calls[0][0], "GET")
        self.assertEqual(self.fake.calls[0][1], "/v1/checkout/sessions/" + SESSION)

    def test_rejects_unpaid_wrong_url_wrong_amount_and_live_mode(self) -> None:
        self.fake.session = paid_session(payment_status="unpaid", status="complete")
        self.assertFalse(payments.verify_paid_session(SESSION, TARGET).ok)

        self.fake.session = paid_session(url="https://other.example/")
        message = payments.verify_paid_session(SESSION, TARGET).message
        self.assertIn("different website", message)

        self.fake.session = paid_session(amount=500)
        self.assertIn("price", payments.verify_paid_session(SESSION, TARGET).message)

        self.fake.session = paid_session(amount="2000")  # type: ignore[arg-type]
        self.assertFalse(payments.verify_paid_session(SESSION, TARGET).ok)

        self.fake.session = paid_session(livemode=True)
        self.assertIn("test mode", payments.verify_paid_session(SESSION, TARGET).message)

        self.fake.session = paid_session(vertical="saas")
        self.assertFalse(payments.verify_paid_session(SESSION, TARGET, "local").ok)
        self.assertTrue(payments.verify_paid_session(SESSION, TARGET, "").ok)
        self.assertEqual(payments.verify_paid_session(SESSION, TARGET, "").vertical, "saas")

    def test_stripe_error_fails_closed(self) -> None:
        self.fake.error = "Stripe couldn't complete that step. Try again in a moment."
        result = payments.verify_paid_session(SESSION, TARGET)
        self.assertFalse(result.ok)
        self.assertIn("Stripe", result.message)

    def test_checkout_params_and_literal_placeholder(self) -> None:
        hosted = payments.create_checkout_session(
            "Example.com/path/", "SaaS", "https://surfaced.example", "idem-1",
        )
        self.assertEqual(hosted, "https://checkout.stripe.com/c/pay/" + SESSION)
        params = self.fake.calls[0][2]
        self.assertEqual(params["metadata[url]"], "https://example.com/path")
        self.assertEqual(params["metadata[vertical]"], "saas")
        self.assertEqual(params["metadata[product]"], "surfaced-report")
        self.assertEqual(params["line_items[0][price_data][unit_amount]"], "2000")
        self.assertEqual(params["line_items[0][price_data][currency]"], "usd")
        self.assertNotIn("line_items[0][price]", params)
        self.assertIn("{CHECKOUT_SESSION_ID}", params["success_url"])
        self.assertIn("vertical=saas", params["success_url"])
        self.assertTrue(params["cancel_url"].endswith("&canceled=1"))
        self.assertEqual(self.fake.calls[0][3], "idem-1")

        body = payments._encode_form(params)
        decoded = urllib.parse.parse_qs(body)
        self.assertTrue(decoded["success_url"][0].endswith("session_id={CHECKOUT_SESSION_ID}"))
        self.assertNotIn("%7BCHECKOUT_SESSION_ID%7D", body)
        self.assertIn("metadata[url]=https%3A%2F%2Fexample.com%2Fpath", body)

    def test_price_id_is_sent_when_set(self) -> None:
        os.environ["STRIPE_PRICE_ID"] = "price_123abc"
        payments.create_checkout_session(TARGET, "", "https://surfaced.example", "idem-2")
        params = self.fake.calls[0][2]
        self.assertEqual(params["line_items[0][price]"], "price_123abc")
        self.assertNotIn("line_items[0][price_data][unit_amount]", params)

    def test_refuses_a_non_stripe_redirect(self) -> None:
        self.fake.create = {"id": SESSION, "url": "https://evil.example/phish"}
        with self.assertRaises(payments.PaymentError):
            payments.create_checkout_session(TARGET, "", "https://surfaced.example", "idem-3")

    def test_top_fix_is_highest_priority_not_largest_gap(self) -> None:
        res = sample_result()
        res.checks.append(studio.Check(
            "AEO", "Big medium gap", 0, 80, "observed",
            fix="UNIQUE_MEDIUM_FIX", priority="Medium",
        ))
        self.assertEqual(server.top_fix(res)["fix"], "UNIQUE_TOP_FIX allow the citation crawlers.")


class GatingPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["SURFACED_PAYMENTS"] = "on"
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_unit"
        os.environ["SURFACED_PRICE_CENTS"] = "2000"

    def test_teaser_omits_the_paid_fields(self) -> None:
        payload = server.teaser_payload(sample_result())
        self.assertEqual(set(payload), {
            "access", "paid", "price", "url", "title", "checked_at", "grade",
            "vertical", "scores", "top_fix", "checkout",
        })
        self.assertEqual(payload["access"], "teaser")
        self.assertFalse(payload["paid"])
        self.assertEqual(set(payload["scores"]), {"overall"})
        self.assertEqual(payload["scores"]["overall"], 55)
        self.assertEqual(payload["grade"], "C")
        self.assertEqual(payload["vertical"]["key"], "general")
        self.assertEqual(payload["top_fix"]["priority"], "High")
        self.assertNotIn("UNIQUE_HIDDEN_FIX", json.dumps(payload))
        self.assertNotIn("UNIQUE_SUMMARY", json.dumps(payload))
        self.assertNotIn("UNIQUEBOT", json.dumps(payload))

    def test_full_payload_adds_paid_flag_only_when_charging(self) -> None:
        full = server.full_payload(sample_result())
        self.assertEqual(full["access"], "full")
        self.assertTrue(full["paid"])
        self.assertIn("checks", full)
        self.assertEqual(len(full["recommendations"]), 2)
        os.environ["SURFACED_PAYMENTS"] = "off"
        plain = server.full_payload(sample_result())
        self.assertEqual(plain, server.result_to_dict(sample_result()))
        self.assertNotIn("access", plain)

    def test_redacts_session_id(self) -> None:
        line = server._redact_session_ids('GET /scan?url=a&session_id=cs_test_abcdefghij HTTP/1.1')
        self.assertNotIn(SESSION, line)
        self.assertIn("session_id=redacted", line)


class LandingTests(unittest.TestCase):
    def test_paid_copy_and_schema(self) -> None:
        html = landing_page("https://surfaced.example", payments_on=True, price_cents=2000)
        self.assertNotIn("{{", html)
        self.assertNotIn("Free, no signup", html)
        self.assertIn("https://surfaced.example/", html)
        self.assertIn("one-time $20", html)
        self.assertNotIn("points", html.lower())
        block = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        self.assertIsNotNone(block)
        data = json.loads(block.group(1))
        offer = next(node["offers"] for node in data["@graph"] if node["@type"] == "SoftwareApplication")
        self.assertEqual(offer["price"], "20")
        self.assertEqual(offer["priceCurrency"], "USD")
        self.assertIn("/terms", html)
        self.assertIn("owner's real text", html)

    def test_free_copy_stays_free(self) -> None:
        html = landing_page("https://surfaced.example", payments_on=False)
        self.assertIn("Free, no signup", html)
        self.assertIn('"price": "0"', html)
        self.assertNotIn('"price": "20"', html)
        self.assertIn("/api/scan?url=example.com", html)

    def test_legal_pages_are_placeholders(self) -> None:
        for route in ("/terms", "/privacy", "/refunds"):
            html = legal_page(route, "https://surfaced.example")
            self.assertIn("Placeholder — not legal text", html)
            self.assertIn("does not describe fees", html)
            self.assertNotIn("all sales", html.lower())


class HttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = {
            name: os.environ.get(name)
            for name in ("SURFACED_PAYMENTS", "STRIPE_SECRET_KEY", "STRIPE_PRICE_ID",
                         "SURFACED_PRICE_CENTS", "SURFACED_BASE_URL")
        }
        os.environ["SURFACED_PAYMENTS"] = "on"
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_unit"
        os.environ["SURFACED_PRICE_CENTS"] = "2000"
        os.environ["SURFACED_BASE_URL"] = "https://surfaced.example"
        os.environ.pop("STRIPE_PRICE_ID", None)
        self.real_run_scan = server.run_scan
        self.real_assert = server.assert_public_url
        self.fake = StripeFake()
        payments.set_transport(self.fake)
        server.run_scan = lambda url, vertical=None: sample_result(TARGET)
        self._reset_limits()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Surfaced)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        server.run_scan = self.real_run_scan
        server.assert_public_url = self.real_assert
        payments.set_transport(None)
        for name, value in self._env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def _reset_limits(self) -> None:
        server.limiter = server.RateLimiter(server.RATE_LIMIT, server.RATE_WINDOW)
        server.paid_limiter = server.RateLimiter(server.PAID_RATE_LIMIT, server.RATE_WINDOW)
        server.checkout_limiter = server.RateLimiter(server.CHECKOUT_RATE_LIMIT, server.RATE_WINDOW)

    def request(self, method: str, path: str, body: bytes | None = None,
                headers: dict | None = None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        payload = response.read()
        status = response.status
        header_map = {key.lower(): value for key, value in response.getheaders()}
        conn.close()
        return status, payload, header_map

    def test_api_teaser_then_full_report(self) -> None:
        status, body, headers = self.request("GET", "/api/scan?url=https://example.com/")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("x-content-type-options"), "nosniff")
        self.assertIn("no-store", headers.get("cache-control", ""))
        payload = json.loads(body)
        self.assertEqual(payload["access"], "teaser")
        self.assertEqual(payload["scores"], {"overall": 55})
        self.assertNotIn("checks", payload)
        self.assertNotIn("crawlers", payload)
        self.assertEqual(self.fake.calls, [])

        status, body, _ = self.request(
            "GET", f"/api/scan?url=https://example.com/&session_id={SESSION}",
        )
        self.assertEqual(status, 200)
        full = json.loads(body)
        self.assertEqual(full["access"], "full")
        self.assertTrue(full["paid"])
        self.assertIn("checks", full)
        self.assertEqual(full["crawlers"][0]["bot"], "UNIQUEBOT")
        self.assertEqual(self.fake.calls[0][0], "GET")

    def test_html_teaser_hides_the_rest_of_the_report(self) -> None:
        status, body, _ = self.request("GET", "/scan?url=example.com")
        self.assertEqual(status, 200)
        html = body.decode()
        self.assertIn("Get the full report for $20", html)
        self.assertIn("UNIQUE_TOP_FIX", html)
        self.assertIn("Grade C", html)
        self.assertIn("General business", html)
        self.assertNotIn("UNIQUE_HIDDEN_FIX", html)
        self.assertNotIn("UNIQUE_SUMMARY_SHOULD_STAY_HIDDEN", html)
        self.assertNotIn("AI crawler access", html)
        self.assertIn('name="url" value="https://example.com/"', html)
        self.assertIn('action="/checkout"', html)

    def test_paid_html_is_the_full_report(self) -> None:
        self.fake.session = paid_session(vertical="saas")
        seen = {}

        def capture(url, vertical=None):
            seen["url"] = url
            seen["vertical"] = vertical
            return sample_result()

        server.run_scan = capture
        status, body, _ = self.request("GET", f"/scan?url=Example.com&session_id={SESSION}")
        self.assertEqual(status, 200)
        html = body.decode()
        self.assertIn("UNIQUE_HIDDEN_FIX", html)
        self.assertIn("AI crawler access", html)
        self.assertIn("This link is your receipt", html)
        self.assertIn('content="noindex"', html)
        self.assertEqual(seen["vertical"], "saas")
        self.assertEqual(seen["url"], "Example.com")

    def test_other_url_and_bad_session_stay_on_the_preview(self) -> None:
        self.fake.session = paid_session(url="https://other.example/")
        status, body, _ = self.request(
            "GET", f"/api/scan?url=https://example.com/&session_id={SESSION}",
        )
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["access"], "teaser")
        self.assertIn("different website", payload["payment_error"])
        self.assertNotIn("checks", payload)

        status, body, _ = self.request("GET", "/api/scan?url=https://example.com/&session_id=nope")
        payload = json.loads(body)
        self.assertEqual(payload["access"], "teaser")
        self.assertIn("isn't valid", payload["payment_error"])
        self.assertEqual(len(self.fake.calls), 1)

    def test_payments_off_keeps_the_full_api_shape(self) -> None:
        os.environ["SURFACED_PAYMENTS"] = "off"
        status, body, _ = self.request("GET", "/api/scan?url=https://example.com/")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload, server.result_to_dict(sample_result()))
        self.assertNotIn("access", payload)
        status, html, _ = self.request("GET", "/scan?url=https://example.com/")
        self.assertEqual(status, 200)
        text = html.decode()
        self.assertIn("UNIQUE_HIDDEN_FIX", text)
        self.assertNotIn("This link is your receipt", text)

    def test_private_url_is_still_blocked(self) -> None:
        server.run_scan = self.real_run_scan
        status, body, _ = self.request("GET", "/scan?url=http://127.0.0.1/")
        self.assertEqual(status, 400)
        self.assertIn("private network", body.decode().lower())
        self.assertNotIn("UNIQUE_TOP_FIX", body.decode())
        self.assertEqual(self.fake.calls, [])

    def test_preview_limit_does_not_block_a_paid_report(self) -> None:
        server.limiter = server.RateLimiter(1, server.RATE_WINDOW)
        first, _, _ = self.request("GET", "/api/scan?url=https://example.com/")
        self.assertEqual(first, 200)
        second, limited, limited_headers = self.request("GET", "/api/scan?url=https://example.com/")
        self.assertEqual(second, 429)
        self.assertIn("previews", limited.decode())
        self.assertIn("retry-after", limited_headers)
        third, full, _ = self.request(
            "GET", f"/api/scan?url=https://example.com/&session_id={SESSION}",
        )
        self.assertEqual(third, 200)
        self.assertEqual(json.loads(full)["access"], "full")

    def test_checkout_redirects_to_stripe_and_is_limited(self) -> None:
        server.assert_public_url = lambda url: None
        server.checkout_limiter = server.RateLimiter(1, server.RATE_WINDOW)
        body = urllib.parse.urlencode({"url": "Example.com", "vertical": "local"}).encode()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(body)),
        }
        status, _, response_headers = self.request("POST", "/checkout", body, headers)
        self.assertEqual(status, 303)
        self.assertEqual(
            response_headers.get("location"),
            "https://checkout.stripe.com/c/pay/" + SESSION,
        )
        params = self.fake.calls[0][2]
        self.assertEqual(params["metadata[url]"], TARGET)
        self.assertEqual(params["metadata[vertical]"], "local")
        self.assertIn("{CHECKOUT_SESSION_ID}", params["success_url"])
        self.assertTrue(params["success_url"].startswith("https://surfaced.example/scan?"))
        again, _, _ = self.request("POST", "/checkout", body, headers)
        self.assertEqual(again, 429)
        self.assertEqual(len(self.fake.calls), 1)

    def test_checkout_blocks_private_urls_and_foreign_origins(self) -> None:
        body = urllib.parse.urlencode({"url": "http://127.0.0.1/"}).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body))}
        status, page, _ = self.request("POST", "/checkout", body, headers)
        self.assertEqual(status, 400)
        self.assertIn("private network", page.decode().lower())
        self.assertEqual(self.fake.calls, [])

        body = urllib.parse.urlencode({"url": "https://example.com/"}).encode()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Content-Length": str(len(body)),
            "Origin": "https://evil.example",
        }
        status, _, _ = self.request("POST", "/checkout", body, headers)
        self.assertEqual(status, 403)
        self.assertEqual(self.fake.calls, [])

    def test_checkout_rejects_a_phish_redirect(self) -> None:
        server.assert_public_url = lambda url: None
        self.fake.create = {"id": SESSION, "url": "https://evil.example/phish"}
        body = urllib.parse.urlencode({"url": "https://example.com/"}).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body))}
        status, page, response_headers = self.request("POST", "/checkout", body, headers)
        self.assertEqual(status, 400)
        self.assertNotIn("evil.example", response_headers.get("location", ""))
        self.assertNotIn("https://evil.example", page.decode())

    def test_terms_and_paid_home_page(self) -> None:
        status, body, _ = self.request("GET", "/terms")
        self.assertEqual(status, 200)
        self.assertIn("Placeholder — not legal text", body.decode())
        status, home, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        text = home.decode()
        self.assertIn('"price": "20"', text)
        self.assertNotIn("Free, no signup", text)
        status, image, _ = self.request("GET", "/og.svg")
        self.assertIn(b"full report $20", image)
        self.assertNotIn(b"Free AI visibility", image)


if __name__ == "__main__":
    unittest.main()
