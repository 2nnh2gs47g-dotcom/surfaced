"""
Surfaced — Stripe billing and the credit ledger.

Standard library only: Stripe's REST API over urllib, webhook signatures via
hmac, the ledger in SQLite.

THE GUARANTEE: one payment grants credits exactly once, and one credit buys
exactly one run. Duplication can happen in three independent places, so each
gets its own defence, and each defence is a database constraint rather than an
application-level check — a check like "if not already recorded, record it" has
a race window between the read and the write. A constraint has none.

  1. Stripe delivers webhooks AT LEAST once, and retries for up to three days
     on any non-2xx. The same event will arrive again.
         -> UNIQUE(stripe_event_id) on `grant`. The second INSERT raises
            IntegrityError, which we treat as success and ignore.

  2. The user double-taps Run, or the network retries a request that already
     succeeded server-side.
         -> UNIQUE(idempotency_key) on `run`. The second attempt returns the
            first run's outcome and spends nothing.

  3. Two requests spend the last credit at the same moment.
         -> Conditional UPDATE: `SET credits = credits - 1 WHERE credits > 0`,
            then check rowcount. SQLite serialises the writers, so exactly one
            of them sees rowcount 1.

And the money-losing case nobody remembers until it happens:

  4. A run fails, or the process dies mid-scan. The customer must not pay for
     nothing. A credit is RESERVED before the scan and only committed after it
     succeeds; a failure refunds it, and `sweep_stale()` refunds reservations
     orphaned by a crash.

The client is never trusted. A browser saying "I paid" grants nothing; credit
comes only from a signature-verified Stripe webhook.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

STRIPE_API = "https://api.stripe.com/v1"

SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")
CREDITS_PER_PURCHASE = int(os.environ.get("SURFACED_CREDITS_PER_PURCHASE", "1"))

# A reservation older than this is assumed orphaned by a crash and refunded.
RESERVATION_TTL = 600          # seconds
# Stripe signature timestamp tolerance, to blunt replay attacks.
SIGNATURE_TOLERANCE = 300      # seconds


class BillingError(Exception):
    """Something went wrong talking to Stripe."""


def configured() -> bool:
    return bool(SECRET_KEY and WEBHOOK_SECRET and PRICE_ID)


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # WAL lets a reader run while a writer holds the lock; without it a slow
    # scan can block the webhook, and a blocked webhook is a Stripe retry.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS grant (
  id               INTEGER PRIMARY KEY,
  stripe_event_id  TEXT    NOT NULL UNIQUE,   -- defence 1: exactly-once credit
  stripe_object_id TEXT    NOT NULL,
  email            TEXT,
  credits          INTEGER NOT NULL,
  created          REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS balance (
  key_hash   TEXT PRIMARY KEY,                -- sha256 of the access key
  email      TEXT,
  credits    INTEGER NOT NULL DEFAULT 0,
  reserved   INTEGER NOT NULL DEFAULT 0,
  created    REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS run (
  id              INTEGER PRIMARY KEY,
  key_hash        TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,       -- defence 2: one run per intent
  url             TEXT NOT NULL,
  status          TEXT NOT NULL,              -- reserved | done | refunded
  result          TEXT,                       -- JSON of the completed scan
  created         REAL NOT NULL,
  settled         REAL
);

CREATE INDEX IF NOT EXISTS idx_run_status ON run(status, created);
CREATE INDEX IF NOT EXISTS idx_grant_object ON grant(stripe_object_id);
"""


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Granting credit — only ever called from a verified webhook
# ---------------------------------------------------------------------------

def grant_credits(conn: sqlite3.Connection, *, event_id: str, object_id: str,
                  email: str | None, credits: int,
                  access_key: str | None = None) -> tuple[str | None, bool]:
    """
    Record a payment and add credits. Returns (access_key, granted).

    `granted` is False when this event was already processed — the normal and
    expected result of a Stripe retry, not an error. The caller must still
    answer 200 so Stripe stops retrying.

    The UNIQUE constraint on stripe_event_id is what enforces exactly-once.
    We do not check first and insert second; we insert and let the database
    refuse. That closes the window where two concurrent deliveries of the same
    event both pass the check.
    """
    key = access_key or secrets.token_urlsafe(24)
    kh = _hash(key)
    now = time.time()

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO grant (stripe_event_id, stripe_object_id, email, credits, created)"
            " VALUES (?,?,?,?,?)",
            (event_id, object_id, email, credits, now),
        )
        conn.execute(
            "INSERT INTO balance (key_hash, email, credits, created) VALUES (?,?,?,?)"
            " ON CONFLICT(key_hash) DO UPDATE SET credits = credits + excluded.credits",
            (kh, email, credits, now),
        )
        conn.execute("COMMIT")
        return key, True
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        return None, False          # already granted; nothing to do
    except Exception:
        conn.execute("ROLLBACK")
        raise


def balance_of(conn: sqlite3.Connection, key: str) -> int:
    row = conn.execute("SELECT credits FROM balance WHERE key_hash = ?", (_hash(key),)).fetchone()
    return row["credits"] if row else 0


# ---------------------------------------------------------------------------
# Spending credit — reserve, then commit or refund
# ---------------------------------------------------------------------------

class Reservation:
    __slots__ = ("run_id", "replayed", "result")

    def __init__(self, run_id: int | None, replayed: bool, result: str | None = None):
        self.run_id = run_id
        self.replayed = replayed      # this idempotency key was already used
        self.result = result          # the earlier run's stored result, if any


def reserve(conn: sqlite3.Connection, key: str, idempotency_key: str,
            url: str) -> Reservation:
    """
    Take one credit for this run, or raise ValueError when there is none.

    Returns a Reservation. If `replayed` is true the caller must NOT scan: this
    exact intent already ran, and the stored result (if the first run finished)
    is returned instead. That is defence 2 — a double-tap costs one credit, not
    two.
    """
    kh = _hash(key)
    now = time.time()

    conn.execute("BEGIN IMMEDIATE")
    try:
        prior = conn.execute(
            "SELECT id, status, result FROM run WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if prior is not None:
            conn.execute("COMMIT")
            return Reservation(prior["id"], True, prior["result"])

        # Defence 3: the WHERE clause is the check. A read-then-write would let
        # two requests both see "1 credit left" and both decrement.
        cur = conn.execute(
            "UPDATE balance SET credits = credits - 1, reserved = reserved + 1"
            " WHERE key_hash = ? AND credits > 0",
            (kh,),
        )
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            raise ValueError("No scan credits left on this key.")

        cur = conn.execute(
            "INSERT INTO run (key_hash, idempotency_key, url, status, created)"
            " VALUES (?,?,?,'reserved',?)",
            (kh, idempotency_key, url, now),
        )
        conn.execute("COMMIT")
        return Reservation(cur.lastrowid, False)
    except ValueError:
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise


def commit_run(conn: sqlite3.Connection, run_id: int, result_json: str) -> None:
    """The scan succeeded: the credit is spent for good."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT key_hash, status FROM run WHERE id = ?", (run_id,)).fetchone()
        if row is None or row["status"] != "reserved":
            conn.execute("ROLLBACK")
            return
        conn.execute(
            "UPDATE run SET status='done', result=?, settled=? WHERE id = ?",
            (result_json, time.time(), run_id),
        )
        conn.execute(
            "UPDATE balance SET reserved = reserved - 1 WHERE key_hash = ? AND reserved > 0",
            (row["key_hash"],),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def refund_run(conn: sqlite3.Connection, run_id: int) -> None:
    """
    The scan failed: give the credit back.

    Defence 4. A customer must never pay for a run that produced nothing, and a
    scan can fail for reasons that are entirely ours — the target timed out,
    the renderer was down, the process was restarted mid-request.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT key_hash, status FROM run WHERE id = ?", (run_id,)).fetchone()
        if row is None or row["status"] != "reserved":
            conn.execute("ROLLBACK")
            return                                   # already settled; refunding twice would mint credit
        conn.execute(
            "UPDATE run SET status='refunded', settled=? WHERE id = ?",
            (time.time(), run_id),
        )
        conn.execute(
            "UPDATE balance SET credits = credits + 1,"
            " reserved = CASE WHEN reserved > 0 THEN reserved - 1 ELSE 0 END"
            " WHERE key_hash = ?",
            (row["key_hash"],),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def sweep_stale(conn: sqlite3.Connection, ttl: int = RESERVATION_TTL) -> int:
    """
    Refund reservations orphaned by a crash. Called on startup and periodically.

    Without this, a process killed mid-scan silently keeps the customer's
    credit, and nothing ever reports it.
    """
    cutoff = time.time() - ttl
    stale = conn.execute(
        "SELECT id FROM run WHERE status='reserved' AND created < ?", (cutoff,)
    ).fetchall()
    for row in stale:
        refund_run(conn, row["id"])
    return len(stale)


# ---------------------------------------------------------------------------
# Stripe REST — no SDK, no dependency
# ---------------------------------------------------------------------------

def _stripe_post(path: str, fields: list[tuple[str, str]],
                 idempotency_key: str | None = None) -> dict:
    if not SECRET_KEY:
        raise BillingError("STRIPE_SECRET_KEY is not set.")
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(f"{STRIPE_API}{path}", data=body, method="POST")
    req.add_header("Authorization", f"Bearer {SECRET_KEY}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    # Stripe's own idempotency: a retried create does not make a second session.
    if idempotency_key:
        req.add_header("Idempotency-Key", idempotency_key)
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise BillingError(f"Stripe returned HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise BillingError(f"Could not reach Stripe: {exc.reason}")


def create_checkout_session(base_url: str, client_ref: str) -> str:
    """Create a Checkout Session and return its hosted URL."""
    if not PRICE_ID:
        raise BillingError("STRIPE_PRICE_ID is not set.")
    data = _stripe_post(
        "/checkout/sessions",
        [
            ("mode", "payment"),
            ("line_items[0][price]", PRICE_ID),
            ("line_items[0][quantity]", "1"),
            ("success_url", f"{base_url}/paid?session_id={{CHECKOUT_SESSION_ID}}"),
            ("cancel_url", f"{base_url}/"),
            ("client_reference_id", client_ref),
        ],
        idempotency_key=f"checkout:{client_ref}",
    )
    url = data.get("url")
    if not url:
        raise BillingError("Stripe did not return a checkout URL.")
    return url


def retrieve_session(session_id: str) -> dict:
    if not SECRET_KEY:
        raise BillingError("STRIPE_SECRET_KEY is not set.")
    safe = urllib.parse.quote(session_id, safe="")
    req = urllib.request.Request(f"{STRIPE_API}/checkout/sessions/{safe}")
    req.add_header("Authorization", f"Bearer {SECRET_KEY}")
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode())
    except urllib.error.HTTPError as exc:
        raise BillingError(f"Stripe returned HTTP {exc.code}")
    except urllib.error.URLError as exc:
        raise BillingError(f"Could not reach Stripe: {exc.reason}")


# ---------------------------------------------------------------------------
# Webhook signature
# ---------------------------------------------------------------------------

def verify_signature(payload: bytes, header: str,
                     secret: str = "", tolerance: int = SIGNATURE_TOLERANCE) -> dict:
    """
    Verify Stripe's `Stripe-Signature` header and return the parsed event.

    Raises ValueError on anything suspect. Without this check the webhook is an
    open endpoint that mints credit for anyone who can POST to it — this single
    function is the difference between a payment system and a giveaway.
    """
    secret = secret or WEBHOOK_SECRET
    if not secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET is not set.")
    if not header:
        raise ValueError("Missing Stripe-Signature header.")

    timestamp = None
    signatures: list[str] = []
    for part in header.split(","):
        if "=" not in part:
            continue
        label, _, value = part.strip().partition("=")
        if label == "t":
            timestamp = value
        elif label == "v1":
            signatures.append(value)

    if timestamp is None or not signatures:
        raise ValueError("Malformed Stripe-Signature header.")
    try:
        sent_at = int(timestamp)
    except ValueError:
        raise ValueError("Malformed timestamp in Stripe-Signature.")

    # Replay guard: an attacker who captures one valid request cannot resend it
    # tomorrow. Stripe's own retries always carry a fresh timestamp.
    if abs(time.time() - sent_at) > tolerance:
        raise ValueError("Stripe signature timestamp is outside the tolerance window.")

    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()

    # compare_digest, not ==, so the comparison does not leak the signature
    # one byte at a time through timing.
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise ValueError("Stripe signature did not match.")

    try:
        return json.loads(payload.decode())
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Webhook body was not valid JSON.")


def credits_for_event(event: dict) -> tuple[str, str, str | None, int] | None:
    """
    Map a Stripe event to (event_id, object_id, email, credits), or None when
    the event is not one we grant credit for.

    Only events that represent money actually received are honoured:
    `checkout.session.completed` with payment_status 'paid', and `invoice.paid`
    for subscription renewals. A created-but-unpaid session grants nothing.
    """
    event_id = event.get("id")
    kind = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}
    if not event_id or not kind:
        return None

    if kind == "checkout.session.completed":
        if obj.get("payment_status") != "paid":
            return None
        email = (obj.get("customer_details") or {}).get("email") or obj.get("customer_email")
        return event_id, obj.get("id", ""), email, CREDITS_PER_PURCHASE

    if kind == "invoice.paid":
        email = obj.get("customer_email")
        return event_id, obj.get("id", ""), email, CREDITS_PER_PURCHASE

    return None
