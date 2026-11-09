#!/usr/bin/env python3
"""
Proof that one payment grants exactly one run's worth of credit, and that one
credit buys exactly one run — under retries, double-taps, races and crashes.

Run it:   python3 test_billing.py

No network and no Stripe keys. The ledger is real SQLite in a temp file; the
webhook signatures are computed locally with a test secret, so the signature
path is exercised for real rather than stubbed out.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import tempfile
import threading
import time

import billing

SECRET = "whsec_test_secret_for_local_verification_only"
passed = 0
failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global passed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed.append(f"{name}{' — ' + detail if detail else ''}")
        print(f"  FAIL  {name}  {detail}")


def fresh_db() -> tuple[sqlite3.Connection, str]:
    path = os.path.join(tempfile.mkdtemp(), "ledger.db")
    conn = billing.connect(path)
    billing.init(conn)
    return conn, path


def signed(payload: dict, secret: str = SECRET, age: int = 0) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    ts = int(time.time()) - age
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={ts},v1={sig}"


# ---------------------------------------------------------------------------
print("\nDefence 1 — Stripe delivers webhooks at least once")
# ---------------------------------------------------------------------------
conn, _ = fresh_db()
key, granted = billing.grant_credits(
    conn, event_id="evt_1", object_id="cs_1", email="a@b.com", credits=1)
check("first delivery grants credit", granted and billing.balance_of(conn, key) == 1)

_, granted_again = billing.grant_credits(
    conn, event_id="evt_1", object_id="cs_1", email="a@b.com", credits=1)
check("replayed delivery grants nothing", granted_again is False)
check("balance unchanged after replay", billing.balance_of(conn, key) == 1,
      f"balance={billing.balance_of(conn, key)}")

# The hard version: the same event arriving on several threads at once.
conn2, path2 = fresh_db()
shared = billing.secrets.token_urlsafe(24)
results: list[bool] = []
lock = threading.Lock()


def deliver() -> None:
    c = billing.connect(path2)
    try:
        _, ok = billing.grant_credits(
            c, event_id="evt_race", object_id="cs_race", email="a@b.com",
            credits=1, access_key=shared)
        with lock:
            results.append(ok)
    finally:
        c.close()


threads = [threading.Thread(target=deliver) for _ in range(12)]
[t.start() for t in threads]
[t.join() for t in threads]
check("12 concurrent deliveries of one event grant exactly once",
      results.count(True) == 1, f"granted {results.count(True)} times")
check("balance is 1 after the race", billing.balance_of(conn2, shared) == 1,
      f"balance={billing.balance_of(conn2, shared)}")


# ---------------------------------------------------------------------------
print("\nDefence 2 — the user double-taps Run")
# ---------------------------------------------------------------------------
conn, _ = fresh_db()
key, _ = billing.grant_credits(conn, event_id="e", object_id="o", email=None, credits=2)

r1 = billing.reserve(conn, key, "intent-abc", "https://example.com")
check("first tap reserves", r1.replayed is False and billing.balance_of(conn, key) == 1)

r2 = billing.reserve(conn, key, "intent-abc", "https://example.com")
check("second tap is recognised as a replay", r2.replayed is True)
check("second tap spends nothing", billing.balance_of(conn, key) == 1,
      f"balance={billing.balance_of(conn, key)}")
check("replay points at the same run", r2.run_id == r1.run_id)

billing.commit_run(conn, r1.run_id, json.dumps({"scores": {"overall": 71}}))
r3 = billing.reserve(conn, key, "intent-abc", "https://example.com")
check("replay after completion returns the stored result",
      r3.replayed and r3.result and json.loads(r3.result)["scores"]["overall"] == 71)
check("still spends nothing", billing.balance_of(conn, key) == 1)


# ---------------------------------------------------------------------------
print("\nDefence 3 — two requests spend the last credit at once")
# ---------------------------------------------------------------------------
conn, path = fresh_db()
key, _ = billing.grant_credits(conn, event_id="e2", object_id="o2", email=None, credits=1)

wins: list[bool] = []
barrier = threading.Barrier(8)


def spend(n: int) -> None:
    c = billing.connect(path)
    try:
        barrier.wait()                    # all threads arrive together
        c_res = billing.reserve(c, key, f"intent-{n}", "https://example.com")
        with lock:
            wins.append(not c_res.replayed)
    except ValueError:
        with lock:
            wins.append(False)
    finally:
        c.close()


threads = [threading.Thread(target=spend, args=(i,)) for i in range(8)]
[t.start() for t in threads]
[t.join() for t in threads]
check("exactly one of 8 racing requests gets the last credit",
      wins.count(True) == 1, f"{wins.count(True)} winners")
check("balance cannot go negative", billing.balance_of(conn, key) == 0,
      f"balance={billing.balance_of(conn, key)}")


# ---------------------------------------------------------------------------
print("\nDefence 4 — the customer must not pay for a run that produced nothing")
# ---------------------------------------------------------------------------
conn, _ = fresh_db()
key, _ = billing.grant_credits(conn, event_id="e3", object_id="o3", email=None, credits=1)
r = billing.reserve(conn, key, "intent-fail", "https://example.com")
check("credit held during the run", billing.balance_of(conn, key) == 0)

billing.refund_run(conn, r.run_id)
check("failed run refunds the credit", billing.balance_of(conn, key) == 1)

billing.refund_run(conn, r.run_id)
check("refunding twice does not mint credit", billing.balance_of(conn, key) == 1,
      f"balance={billing.balance_of(conn, key)}")

# A run that completed cannot then be refunded.
conn, _ = fresh_db()
key, _ = billing.grant_credits(conn, event_id="e4", object_id="o4", email=None, credits=1)
r = billing.reserve(conn, key, "intent-done", "https://example.com")
billing.commit_run(conn, r.run_id, "{}")
billing.refund_run(conn, r.run_id)
check("a completed run cannot be refunded", billing.balance_of(conn, key) == 0,
      f"balance={billing.balance_of(conn, key)}")

# Crash mid-scan: the reservation is orphaned and must come back.
conn, _ = fresh_db()
key, _ = billing.grant_credits(conn, event_id="e5", object_id="o5", email=None, credits=1)
r = billing.reserve(conn, key, "intent-crash", "https://example.com")
conn.execute("UPDATE run SET created = ? WHERE id = ?", (time.time() - 9999, r.run_id))
swept = billing.sweep_stale(conn)
check("crash-orphaned reservation is swept back", swept == 1 and billing.balance_of(conn, key) == 1)


# ---------------------------------------------------------------------------
print("\nWebhook signature — the endpoint must not mint credit for strangers")
# ---------------------------------------------------------------------------
event = {"id": "evt_x", "type": "checkout.session.completed",
         "data": {"object": {"id": "cs_x", "payment_status": "paid",
                             "customer_details": {"email": "x@y.com"}}}}

body, header = signed(event)
try:
    parsed = billing.verify_signature(body, header, SECRET)
    check("a correctly signed event verifies", parsed["id"] == "evt_x")
except ValueError as exc:
    check("a correctly signed event verifies", False, str(exc))


def rejects(name: str, payload: bytes, hdr: str, secret: str = SECRET) -> None:
    try:
        billing.verify_signature(payload, hdr, secret)
        check(name, False, "it was accepted")
    except ValueError:
        check(name, True)


rejects("an unsigned request is rejected", body, "")
rejects("a wrong signature is rejected", body, f"t={int(time.time())},v1={'0' * 64}")
rejects("a forged secret is rejected", *signed(event, "whsec_attacker_guess"))
rejects("a tampered body is rejected", json.dumps({**event, "id": "evt_evil"}).encode(), header)
rejects("a replayed old request is rejected", *signed(event, SECRET, age=3600))
rejects("a malformed header is rejected", body, "garbage")

# Only money actually received grants credit.
check("an unpaid checkout session grants nothing",
      billing.credits_for_event({"id": "e", "type": "checkout.session.completed",
                                 "data": {"object": {"id": "cs", "payment_status": "unpaid"}}}) is None)
check("an unrelated event grants nothing",
      billing.credits_for_event({"id": "e", "type": "customer.created",
                                 "data": {"object": {"id": "cus"}}}) is None)
check("a paid session grants credit",
      billing.credits_for_event(event) is not None)


# ---------------------------------------------------------------------------
print()
if failed:
    print(f"{len(failed)} FAILURE(S):")
    for f in failed:
        print(f"  - {f}")
    raise SystemExit(1)
print(f"All {passed} billing guarantees hold.")
