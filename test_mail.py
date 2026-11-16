#!/usr/bin/env python3
"""
The purchase email: what it says, who it goes to, and that it goes once.

    python3 test_mail.py

No real email is sent. The mail API is a stand-in server on localhost.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import threading

sock = socket.socket(); sock.bind(("127.0.0.1", 0)); PORT = sock.getsockname()[1]; sock.close()
received: list[dict] = []


class FakeMailAPI(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        body["_auth"] = self.headers.get("Authorization")
        received.append(body)
        self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers()
        self.wfile.write(b"{}")


threading.Thread(target=http.server.ThreadingHTTPServer(("127.0.0.1", PORT), FakeMailAPI).serve_forever,
                 daemon=True).start()

for v in ("RESEND_API_KEY", "SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SURFACED_EMAIL_FROM"):
    os.environ.pop(v, None)

import mailer

passed = 0
failed: list[str] = []


def check(name: str, ok: bool) -> None:
    global passed
    if ok:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed.append(name); print(f"  FAIL  {name}")


KEY = "sfd_" + "Ab3" * 10
BASE = "https://surfaced.example"

print("\nContent")
subject, text, html = mailer.purchase_email(KEY, 1, BASE)
check("the scan key is in the text and HTML parts", KEY in text and KEY in html)
check("the report link opens directly with the key", f"{BASE}/reports#k={KEY}" in text
      and f"{BASE}/reports#k={KEY}" in html)
check("the run-your-check link carries the key", f"{BASE}/app#k={KEY}" in text)
check("the key is only ever after the #, never a query string", "?key=" not in text + html
      and "&key=" not in text + html)
check("the default sender is surfaced@patnaiq.com", "surfaced@patnaiq.com" in mailer.sender())

print("\nAddresses")
check("a normal address is accepted", mailer.valid_address("buyer@example.com"))
check("a missing address is refused", not mailer.valid_address(None) and not mailer.valid_address(""))
check("an address with a line break is refused (header injection)",
      not mailer.valid_address("a@b.com\nBcc: x@y.com"))

print("\nSending")
check("nothing is sent when email is not configured",
      mailer.send_purchase_async("buyer@example.com", KEY, 1, BASE) is None and not received)

os.environ["RESEND_API_KEY"] = "re_test"
os.environ["RESEND_API_URL"] = f"http://127.0.0.1:{PORT}/emails"
check("nothing is sent to an unusable address",
      mailer.send_purchase_async("not-an-address", KEY, 1, BASE) is None and not received)

t = mailer.send_purchase_async("buyer@example.com", KEY, 1, BASE)
t.join(10)
check("one email is sent to the buyer", len(received) == 1 and received[0]["to"] == ["buyer@example.com"])
check("it is sent from Surfaced <surfaced@patnaiq.com>",
      bool(received) and received[0]["from"] == "Surfaced <surfaced@patnaiq.com>")
check("replies go to the same address", bool(received) and "surfaced@patnaiq.com" in received[0]["reply_to"])
check("the API key is sent as a bearer token", bool(received) and received[0]["_auth"] == "Bearer re_test")

print()
if failed:
    print(f"{len(failed)} FAILURE(S):"); [print("  -", f) for f in failed]; raise SystemExit(1)
print(f"All {passed} email checks pass.")
