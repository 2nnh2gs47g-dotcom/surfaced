#!/usr/bin/env python3
"""Check the iOS scan models against a real /api/scan payload.

The success body is produced by server.result_to_dict (the same function
GET /api/scan uses). The Result is constructed in-process and labeled SAMPLE.
It is not a live website score, and the app does not load the fixture.

Error bodies are fetched from a local server.py with no outbound scan.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IOS = Path(__file__).resolve().parent
MODELS = IOS / "Surfaced" / "Surfaced" / "ScanModels.swift"
FIXTURE = IOS / "Fixtures" / "sample-scan-response.json"
CLIENT = IOS / "Surfaced" / "Surfaced" / "ScanClient.swift"
APP = IOS / "Surfaced" / "Surfaced" / "ContentView.swift"

sys.path.insert(0, str(ROOT))

import ai_visibility_studio as studio  # noqa: E402
import server  # noqa: E402


def sample_result() -> studio.Result:
    return studio.Result(
        url="https://sample.example",
        final_url="https://sample.example/",
        fetched_at="2026-01-01T00:00:00Z",
        site_title="SAMPLE — not a live scan",
        geo_score=40,
        aeo_score=50,
        reviews_score=20,
        social_score=30,
        checks=[
            studio.Check(
                pillar="Content",
                label="Answer-first summary",
                earned=0,
                possible=8,
                detail="SAMPLE: no summary found.",
                fix="SAMPLE: add a short answer at the top.",
                priority="High",
            ),
            studio.Check(
                pillar="Content",
                label="Heading structure",
                earned=4,
                possible=4,
                detail="SAMPLE: headings present.",
                fix="",
                priority="",
            ),
        ],
        crawler_rows=[("GPTBot", "AI assistant", "ai", "allowed")],
        spa_warning=False,
        word_count=120,
        summary="SAMPLE payload for parser checks. Not a real website score.",
        vertical="local",
        vertical_evidence="SAMPLE schema.org Dentist",
        vertical_forced=False,
    )


def coding_keys(source: str, struct: str) -> list[str]:
    start = source.index(f"struct {struct}")
    nxt = source.find("\nstruct ", start + 1)
    chunk = source[start:] if nxt == -1 else source[start:nxt]
    match = re.search(r"enum CodingKeys: String, CodingKey \{(.+?)\n    \}", chunk, re.S)
    if not match:
        raise SystemExit(f"No CodingKeys on {struct}")
    keys = re.findall(r'"([^"]+)"', match.group(1))
    if not keys:
        raise SystemExit(f"No JSON keys on {struct}")
    return keys


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def require_types(payload: dict, keys: list[str], expected: type, label: str) -> None:
    for key in keys:
        require(key in payload, f"{label} missing {key}")
        require(isinstance(payload[key], expected), f"{label}.{key} is {type(payload[key]).__name__}, want {expected.__name__}")


def build_payload() -> dict:
    payload = server.result_to_dict(sample_result())
    require("SAMPLE" in payload["title"], "sample title was not labeled SAMPLE")
    require("SAMPLE" in payload["summary"], "sample summary was not labeled SAMPLE")
    require(payload["scores"]["overall"] == 32, f"unexpected overall {payload['scores']}")
    require(payload["grade"] == "F", f"unexpected grade {payload['grade']}")
    require(payload["vertical"]["key"] == "local", "vertical key")
    require(payload["pillars"] == {"Content": 33}, f"pillars {payload['pillars']}")
    require(len(payload["recommendations"]) == 1, "fix with empty text should be omitted")
    require(payload["recommendations"][0]["priority"] == "High", "priority sort")
    require("checks" in payload and "crawlers" in payload, "serializer dropped fields the API returns")
    return payload


def check_models(payload: dict) -> None:
    source = MODELS.read_text(encoding="utf-8")
    report_keys = coding_keys(source, "ScanReport")
    vertical_keys = coding_keys(source, "ScanVertical")
    score_keys = coding_keys(source, "ScanScores")
    rec_keys = coding_keys(source, "ScanRecommendation")
    error_keys = coding_keys(source, "APIErrorBody")

    strings = {"url", "title", "checked_at", "summary", "grade"}
    ints = {"word_count"}
    bools = {"javascript_rendered"}
    objects = {"vertical", "scores", "pillars"}
    arrays = {"recommendations"}
    require(set(report_keys) == strings | ints | bools | objects | arrays, f"report keys {report_keys}")
    require_types(payload, sorted(strings), str, "report")
    require_types(payload, sorted(ints), int, "report")
    require_types(payload, sorted(bools), bool, "report")
    for key in objects:
        require(isinstance(payload[key], dict), key)
    require(isinstance(payload["recommendations"], list), "recommendations")

    require(set(vertical_keys) == {"key", "label", "weighting", "detected_from"}, vertical_keys)
    require_types(payload["vertical"], vertical_keys, str, "vertical")
    require(set(score_keys) == {"overall", "geo", "aeo", "reviews", "social"}, score_keys)
    require_types(payload["scores"], score_keys, int, "scores")
    require(set(rec_keys) == {"label", "priority", "observed", "fix"}, rec_keys)
    for item in payload["recommendations"]:
        require_types(item, rec_keys, str, "recommendation")
    for value in payload["pillars"].values():
        require(isinstance(value, int), "pillar percent")

    require(set(error_keys) == {"error", "retry_after_seconds"}, error_keys)
    # Optional retry field must be declared optional in Swift.
    require("let retryAfterSeconds: Int?" in source, "retry_after_seconds must be optional")

    # The shipped UI must not treat the SAMPLE preview as a scan result.
    app = APP.read_text(encoding="utf-8")
    require("ScanReport.sample" not in app and ".sample" not in app.split("#if DEBUG", 1)[0], "app uses the sample report")
    client = CLIENT.read_text(encoding="utf-8")
    require("sample-scan-response" not in client and "Fixtures" not in client, "client loads the fixture")


def check_error_route() -> None:
    port = "8765"
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "server.py")],
        cwd=ROOT,
        env={
            **dict(**{k: v for k, v in __import__("os").environ.items()}),
            "PORT": port,
            "SURFACED_DATA_DIR": "/tmp/surfaced-ios-validate",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 8
        body = None
        while time.time() < deadline:
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ""
                raise SystemExit(f"server exited early:\n{output}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/scan", timeout=1) as response:
                    body = response.read()
                    status = response.status
                    break
            except urllib.error.HTTPError as exc:
                body = exc.read()
                status = exc.code
                break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(0.1)
        require(body is not None, "server did not answer /api/scan")
        require(status == 400, f"missing url status {status}")
        decoded = json.loads(body)
        require(isinstance(decoded.get("error"), str) and decoded["error"], f"error body {decoded}")
        require("retry_after_seconds" not in decoded or isinstance(decoded["retry_after_seconds"], int), "retry type")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> None:
    payload = build_payload()
    check_models(payload)
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2) + "\n"
    if "--write" in sys.argv:
        FIXTURE.write_text(text, encoding="utf-8")
        print(f"wrote {FIXTURE}")
    else:
        require(FIXTURE.is_file(), f"missing {FIXTURE}; run with --write")
        saved = json.loads(FIXTURE.read_text(encoding="utf-8"))
        require(saved == payload, "committed SAMPLE fixture does not match result_to_dict")
    check_error_route()
    print("ok: result_to_dict payload matches ScanModels; /api/scan error JSON is an error string")


if __name__ == "__main__":
    main()
