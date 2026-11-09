#!/usr/bin/env python3
"""
Contract test: /api/scan must keep returning what the app reads.

The app shell in pwa.py decodes the JSON from server.result_to_dict. If a key
is renamed or dropped on the Python side, the app breaks silently in a user's
hand — the scan succeeds, the screen shows nothing useful, and nothing logs an
error. This test fails the moment that drift happens.

Run it before every deploy:

    python3 test_contract.py

No network. The sample Result is built in-process and labelled SAMPLE, so it
can never be mistaken for a real website score.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import ai_visibility_studio as studio
import server

ROOT = Path(__file__).resolve().parent

# Every key the app shell reads, and the type it expects.
# (path, type) — a dotted path walks into nested objects.
CONTRACT: list[tuple[str, type | tuple[type, ...]]] = [
    ("url", str),
    ("grade", str),
    ("summary", str),
    ("word_count", int),
    ("javascript_rendered", bool),
    ("scores.overall", int),
    ("scores.geo", int),
    ("scores.aeo", int),
    ("scores.reviews", int),
    ("scores.social", int),
    ("vertical.label", str),
    ("vertical.weighting", str),
    ("vertical.detected_from", str),
]

# Each recommendation the app renders.
REC_CONTRACT: list[tuple[str, type]] = [
    ("label", str), ("priority", str), ("fix", str),
]

# The error body the app reads on a 429.
ERROR_CONTRACT = ["error", "retry_after_seconds"]

failures: list[str] = []


def sample_result() -> studio.Result:
    """A fabricated Result, labelled SAMPLE throughout. Never a real score."""
    return studio.Result(
        url="https://sample.example",
        final_url="https://sample.example/",
        fetched_at="2026-01-01T00:00:00Z",
        site_title="SAMPLE — not a live scan",
        geo_score=40,
        aeo_score=50,
        reviews_score=20,
        social_score=30,
        word_count=120,
        checks=[
            studio.Check(
                pillar="AEO",
                label="SAMPLE: question-style headings",
                earned=0,
                possible=8,
                detail="SAMPLE: no question headings found.",
                fix="SAMPLE: rewrite headings as the questions people ask.",
                priority="High",
            )
        ],
    )


def walk(obj, path: str):
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None, False
        cur = cur[part]
    return cur, True


def check(payload: dict) -> None:
    for path, expected in CONTRACT:
        value, present = walk(payload, path)
        if not present:
            failures.append(f"missing key: {path}")
        elif not isinstance(value, expected):
            failures.append(
                f"{path}: expected {getattr(expected, '__name__', expected)}, "
                f"got {type(value).__name__}"
            )

    recs = payload.get("recommendations")
    if not isinstance(recs, list):
        failures.append("recommendations: expected a list")
        return
    if recs:
        for key, expected in REC_CONTRACT:
            if key not in recs[0]:
                failures.append(f"recommendations[].{key}: missing")
            elif not isinstance(recs[0][key], expected):
                failures.append(
                    f"recommendations[].{key}: expected {expected.__name__}, "
                    f"got {type(recs[0][key]).__name__}"
                )


def check_error_shape() -> None:
    """server.py must still send the fields the app's 429 message depends on."""
    src = (ROOT / "server.py").read_text()
    for key in ERROR_CONTRACT:
        if f'"{key}"' not in src:
            failures.append(f"server.py no longer sends '{key}' in error bodies")


def check_no_drift() -> None:
    """
    The app must not read payload keys the contract does not cover.

    Catches the reverse failure: someone adds `d.mention_rate` to the app and
    ships before the server sends it.
    """
    shell = (ROOT / "pwa.py").read_text()
    try:
        body = shell.split("APP_SHELL", 1)[1]
    except IndexError:
        failures.append("pwa.py: APP_SHELL not found")
        return

    known = {p.split(".")[0] for p, _ in CONTRACT} | {
        "recommendations", "scores", "vertical", "error", "retry_after_seconds"
    }
    # Keys read straight off the decoded payload, e.g. d.word_count
    for key in set(re.findall(r"\bd\.([a-z_]+)", body)):
        if key not in known:
            failures.append(f"app reads 'd.{key}' but the contract does not cover it")


def main() -> int:
    payload = server.result_to_dict(sample_result())
    check(payload)
    check_error_shape()
    check_no_drift()

    if failures:
        print("CONTRACT BROKEN — the app would misread /api/scan:\n")
        for f in failures:
            print(f"  - {f}")
        print(f"\n{len(failures)} problem(s).")
        return 1

    print(f"Contract OK — {len(CONTRACT)} fields, "
          f"{len(REC_CONTRACT)} recommendation fields, error body, no drift.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
