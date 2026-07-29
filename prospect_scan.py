#!/usr/bin/env python3
"""
Prospect Scanner — find the websites that need you most
=======================================================
Companion to ai_visibility_studio.py (must be in the same folder).

WHAT IT DOES
  Reads a list of website URLs, scores every one with the GEO/AEO engine,
  and produces:
    1. prospects.csv         — all sites ranked WORST-FIRST (your call list)
    2. reports/<site>.html   — a full designed report per site (your outreach
                               attachment: "here's your free audit")
    3. outreach_hooks.txt    — a ready-to-paste personalized opening line
                               per site, citing their real score and their
                               single biggest problem

HOW TO USE (Mac Terminal)
  1. Create a plain text file called  urls.txt  in this folder,
     one website per line, e.g.:
         acmeplumbingsupply.com
         https://www.brightlawnsoftware.com
  2. Run:
         python3 prospect_scan.py
  3. Open prospects.csv (Numbers/Excel) — lowest scores at the top.

Be a good citizen: this fetches each site once, politely, with a pause
between requests. Scan prospect lists you compiled from public business
directories or your own research — quality beats volume.
"""

import csv
import os
import sys
import time

try:
    from ai_visibility_studio import (analyze, save_report, overall_score,
                                  VERTICAL_LABELS, weighting_sentence)
except ImportError:
    print("Put this file in the same folder as ai_visibility_studio.py and try again.")
    sys.exit(1)

URLS_FILE = "urls.txt"
PAUSE_SECONDS = 2  # politeness delay between sites


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    urls_path = os.path.join(here, URLS_FILE)
    if not os.path.exists(urls_path):
        print(f"No {URLS_FILE} found. Create it with one website per line, then re-run.")
        sys.exit(1)

    with open(urls_path, encoding="utf-8") as f:
        urls = [u.strip() for u in f if u.strip() and not u.strip().startswith("#")]

    if not urls:
        print(f"{URLS_FILE} is empty.")
        sys.exit(1)

    print(f"Scanning {len(urls)} site(s)…\n")
    rows = []
    hooks = []

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url} … ", end="", flush=True)
        outcome = analyze(url)
        if isinstance(outcome, str):
            print("skipped (couldn't fetch)")
            rows.append({"url": url, "vertical": "", "geo": "", "aeo": "", "reviews": "",
                         "social": "", "overall": "",
                         "top_issue": f"FETCH FAILED: {outcome[:80]}", "report": ""})
            continue

        overall = overall_score(outcome)
        highs = [c for c in outcome.checks if c.priority == "High"]
        meds = [c for c in outcome.checks if c.priority == "Medium"]
        top = (highs or meds or [None])[0]
        top_issue = top.label if top else "No major issues"
        report_path = save_report(outcome)

        rows.append({
            "url": outcome.final_url,
            "vertical": VERTICAL_LABELS[outcome.vertical],
            "geo": outcome.geo_score,
            "aeo": outcome.aeo_score,
            "reviews": outcome.reviews_score,
            "social": outcome.social_score,
            "overall": overall,
            "top_issue": top_issue,
            "report": os.path.basename(report_path),
        })

        if overall < 60 and top is not None:
            hooks.append(
                f"### {outcome.final_url}  (overall {overall}/100)\n"
                f"I ran {outcome.site_title or 'your site'} through an AI-visibility check — "
                f"it scored {overall}/100 for how well AI assistants like ChatGPT and Claude "
                f"can find and quote it, scored as {VERTICAL_LABELS[outcome.vertical].lower()}. "
                f"The biggest gap: {top.label.lower()} "
                f"({top.detail}). Full report attached — the top three fixes are usually "
                f"a week of work.\n"
            )
        print(f"GEO {outcome.geo_score}  AEO {outcome.aeo_score}  REV {outcome.reviews_score}  "
              f"SOC {outcome.social_score}  overall {overall}  [{outcome.vertical}]")
        if i < len(urls):
            time.sleep(PAUSE_SECONDS)

    # worst-first ranking; fetch failures sink to the bottom
    rows.sort(key=lambda r: (r["overall"] == "", r["overall"] if r["overall"] != "" else 999))

    csv_path = os.path.join(here, "prospects.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["url", "vertical", "geo", "aeo", "reviews",
                                          "social", "overall", "top_issue", "report"])
        w.writeheader()
        w.writerows(rows)

    hooks_path = os.path.join(here, "outreach_hooks.txt")
    with open(hooks_path, "w", encoding="utf-8") as f:
        f.write("Personalized opening lines for every site scoring under 60.\n"
                "Paste into your email's first paragraph, then attach the matching report.\n\n")
        f.writelines(h + "\n" for h in hooks)

    scored = [r for r in rows if r["overall"] != ""]
    low = [r for r in scored if r["overall"] < 60]
    print(f"\nDone. {len(scored)} scored, {len(low)} are strong prospects (under 60/100).")
    print(f"  Call list:  {csv_path}")
    print(f"  Hooks:      {hooks_path}")
    print(f"  Reports:    {os.path.join(here, 'reports')}/")


if __name__ == "__main__":
    main()
