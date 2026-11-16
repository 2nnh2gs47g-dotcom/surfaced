"""
The purchase confirmation email.

Sent once per payment, from the webhook, after the credit is granted. It
carries the scan key and two links that work without typing the key:

    {base}/app#k=<key>       run the check
    {base}/reports#k=<key>   reopen reports later

The key rides in the URL fragment (after #). A fragment is never sent to a
server, so the key does not appear in access logs or Referer headers.

Two ways to send, chosen by which environment variables are set:

    RESEND_API_KEY                         Resend's HTTPS API
    SMTP_HOST, SMTP_USER, SMTP_PASS        any SMTP mailbox (SMTP_PORT, default 587)

    SURFACED_EMAIL_FROM   default "Surfaced <surfaced@patnaiq.com>"

Standard library only. Sending happens on a background thread so a slow mail
server can never delay the answer Stripe is waiting for.
"""

from __future__ import annotations

import html as _html
import json
import os
import re
import smtplib
import ssl
import threading
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

DEFAULT_FROM = "Surfaced <surfaced@patnaiq.com>"
ADDRESS_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def sender() -> str:
    return _env("SURFACED_EMAIL_FROM", DEFAULT_FROM)


def configured() -> bool:
    return bool(_env("RESEND_API_KEY") or
                (_env("SMTP_HOST") and _env("SMTP_USER") and _env("SMTP_PASS")))


def valid_address(addr: str | None) -> bool:
    # Also rejects line breaks, which is what keeps a hostile address from
    # injecting extra headers.
    return bool(addr) and len(addr) <= 254 and bool(ADDRESS_RE.match(addr))


# ---------------------------------------------------------------------------
# What the email says
# ---------------------------------------------------------------------------

def purchase_email(key: str, credits: int, base_url: str) -> tuple[str, str, str]:
    """(subject, plain text, HTML) for a completed purchase."""
    base = base_url.rstrip("/")
    app = f"{base}/app#k={key}"
    reports = f"{base}/reports#k={key}"
    n = f"{credits} full report{'' if credits == 1 else 's'}"
    subject = "Your Surfaced scan key and report link"

    text = f"""Thank you for your purchase.

Your payment is confirmed and {n} {'is' if credits == 1 else 'are'} ready to use.

YOUR SCAN KEY
{key}

1. RUN YOUR CHECK
Open this link, enter the website address, and run the check. The key is
filled in for you.
{app}

2. VIEW YOUR REPORT ANY TIME
This link opens your reports directly. Reopening a report is free, and each
one can be saved as a PDF.
{reports}

Keep this email. Anyone with the key or these links can use your credit and
see your reports, so share them only with people you want to have access.

Questions? Reply to this email.

Surfaced, by PatnAIQ
{base}
"""

    e = _html.escape
    button = ("display:inline-block;background:#372aac;color:#ffffff;text-decoration:none;"
              "font-weight:600;padding:12px 22px;border-radius:10px;")
    html = f"""<!DOCTYPE html><html><body style="margin:0;background:#f7f6fc;">
<div style="max-width:560px;margin:0 auto;padding:32px 20px;font:16px/1.6 -apple-system,'Segoe UI',Arial,sans-serif;color:#191731;">
  <p style="font-size:20px;font-weight:700;margin:0 0 4px;">Surfaced</p>
  <p style="color:#5d5a78;margin:0 0 24px;">Purchase confirmation</p>
  <p>Thank you for your purchase. Your payment is confirmed and <strong>{e(n)}</strong>
  {'is' if credits == 1 else 'are'} ready to use.</p>

  <p style="margin:24px 0 6px;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:#5d5a78;">Your scan key</p>
  <p style="margin:0;background:#ffffff;border:1px solid #e7e6f4;border-radius:10px;padding:14px 16px;
            font:15px ui-monospace,Menlo,Consolas,monospace;word-break:break-all;">{e(key)}</p>

  <p style="margin:28px 0 8px;font-weight:700;">1. Run your check</p>
  <p style="margin:0 0 12px;">Enter the website address and run the check. The key is filled in for you.</p>
  <p style="margin:0;"><a href="{e(app)}" style="{button}">Run my check</a></p>

  <p style="margin:28px 0 8px;font-weight:700;">2. View your report any time</p>
  <p style="margin:0 0 12px;">This link opens your reports directly. Reopening a report is free,
  and each one can be saved as a PDF.</p>
  <p style="margin:0;"><a href="{e(reports)}" style="{button}background:#ffffff;color:#372aac;border:1px solid #372aac;">View my reports</a></p>

  <p style="margin:28px 0 0;color:#5d5a78;font-size:14px;">Keep this email. Anyone with the key or
  these links can use your credit and see your reports, so share them only with people you want
  to have access. Questions? Reply to this email.</p>
  <p style="margin:24px 0 0;color:#5d5a78;font-size:13px;">Surfaced, by PatnAIQ &middot;
  <a href="{e(base)}" style="color:#5d5a78;">{e(base.replace('https://', ''))}</a></p>
</div></body></html>"""
    return subject, text, html


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

class MailError(Exception):
    pass


def _send_resend(to: str, subject: str, text: str, html: str) -> None:
    url = _env("RESEND_API_URL", "https://api.resend.com/emails")
    body = json.dumps({"from": sender(), "to": [to], "subject": subject,
                       "text": text, "html": html, "reply_to": sender()}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {_env('RESEND_API_KEY')}",
        "Content-Type": "application/json",
        "User-Agent": "Surfaced/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status >= 300:
                raise MailError(f"mail API answered {resp.status}")
    except urllib.error.HTTPError as exc:
        raise MailError(f"mail API answered {exc.code}: {exc.read()[:200]!r}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise MailError(f"mail API unreachable: {exc}") from None


def _send_smtp(to: str, subject: str, text: str, html: str) -> None:
    msg = EmailMessage()
    msg["From"] = sender()
    msg["To"] = to
    msg["Subject"] = subject
    msg["Reply-To"] = sender()
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=sender().split("@")[-1].strip("> "))
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    host, port = _env("SMTP_HOST"), int(_env("SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=20, context=ctx) as s:
                s.login(_env("SMTP_USER"), _env("SMTP_PASS"))
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(_env("SMTP_USER"), _env("SMTP_PASS"))
                s.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"SMTP failed: {exc}") from None


def send(to: str, subject: str, text: str, html: str) -> None:
    """Send one email, or raise MailError. Never logs the body (it holds the key)."""
    if not valid_address(to):
        raise MailError("not a usable email address")
    if _env("RESEND_API_KEY"):
        _send_resend(to, subject, text, html)
    elif configured():
        _send_smtp(to, subject, text, html)
    else:
        raise MailError("email is not configured on this server")


def send_purchase_async(to: str | None, key: str, credits: int, base_url: str,
                        attempts: int = 3) -> threading.Thread | None:
    """
    Send the confirmation on a background thread, retrying briefly.

    Returns None without sending when email is not configured or the address
    is unusable: the payment still stands, and /paid still shows the key.
    """
    if not configured() or not valid_address(to):
        why = "email not configured" if not configured() else "no usable buyer address"
        print(f"Purchase email skipped: {why}.", flush=True)
        return None

    subject, text, html = purchase_email(key, credits, base_url)

    def work() -> None:
        for i in range(attempts):
            try:
                send(to, subject, text, html)
                print("Purchase email sent.", flush=True)
                return
            except MailError as exc:
                print(f"Purchase email attempt {i + 1} failed: {exc}", flush=True)
                time.sleep(2 * (i + 1))

    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t
