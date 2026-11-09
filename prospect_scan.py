#!/usr/bin/env python3
"""
Prospect Scanner — find the websites that need you most
=======================================================
Companion to ai_visibility_studio.py (must be in the same folder).

WHAT IT DOES
  Reads a list of website URLs, scores every one with the GEO/AEO engine,
  and produces:
    1. prospects.csv         — all sites ranked WORST-FIRST (your call list)
    2. reports/<site>.html   — a full designed report per site (for YOUR review
                               before any outreach; do not attach to cold email)
    3. outreach_hooks.txt    — a ready-to-paste personalized opening line
                               per site, citing their real score and their
                               single biggest problem, plus a CAN-SPAM footer

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

# --- outreach identity (required before sending) ---------------------------
SCAN_URL = "https://surfaced.patnaiq.com"
SENDER_NAME = "Dilip Patnaik"
SENDER_COMPANY = "PatnAIQ LLC"
SENDER_POSTAL = "[postal address — required by CAN-SPAM]"
REF_CODE = "email"  # appended as ?ref= so scans from outreach can be counted


# Check labels name the test, not the problem. Owners need the problem in plain words.
PLAIN_ISSUE = {
    "AI citation crawlers allowed": "the site blocks some of the AI tools that look up businesses",
    "Served over HTTPS": "the site isn't on a secure (https) address",
    "Readable text without JavaScript": "most of the page's words are invisible to AI tools",
    "Section subheadings (H2/H3)": "the page isn't broken into clear sections AI tools can quote",
    "Question-style headings": "the page doesn't answer the questions customers ask AI assistants",
    "FAQ section": "there's no FAQ section AI tools can read",
    "Schema.org structured data": "the site doesn't label its key facts in a way AI tools can read",
    "Review schema (AggregateRating)": "AI tools can't see your star rating on the site",
    "Google Business Profile link": "the site doesn't link to your Google Business Profile",
    "Profiles linked from the site": "the site doesn't link to your social profiles",
    "sameAs entity links in schema": "AI tools can't tell that your website and social profiles are the same business",
    "Third-party review profiles": "AI tools can't find your reviews on the sites buyers check",
}


def hook_for(outcome, overall: int, top) -> str:
    """
    One personalised opening line.

    Links to the live scan rather than attaching the report: an unknown
    attachment in a cold email reads as phishing and wrecks deliverability.
    Makes no promise about how long a fix takes — no customer work has proven
    one yet. Says "homepage" because the engine reads one page today.
    """
    name = outcome.site_title or "your site"
    issue = PLAIN_ISSUE.get(top.label, top.detail[:1].lower() + top.detail[1:])
    kind = VERTICAL_LABELS[outcome.vertical].lower()
    return (
        f"### {outcome.final_url}  (overall {overall}/100)\n"
        f"Subject: {name} and ChatGPT\n\n"
        f"I checked how ready {name}'s homepage is for AI assistants like ChatGPT "
        f"and Claude. Scored as a {kind}, it came out at {overall}/100. "
        f"The biggest gap: {issue}. "
        f"You can run the same check yourself in about a minute: "
        f"{SCAN_URL}/?ref={REF_CODE}. If it's useful, I'm happy to walk you "
        f"through it for 15 minutes, free.\n\n"
        f"{SENDER_NAME} · {SENDER_COMPANY} · {SENDER_POSTAL}\n"
        f"Reply \"no thanks\" and I won't write again.\n"
    )


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

    if "[" in SENDER_POSTAL:
        print("Note: SENDER_POSTAL is still a placeholder — fill it in before sending any hook.\n")

    print(f"Scanning {len(urls)} site(s)…\n")
    rows = []
    hooks = []

    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url} … ", end="", flush=True)
        outcome = analyze(url)
        if isinstance(outcome, str):
            # A site whose firewall turns away readers is not a failed scan —
            # it is the strongest prospect on the list, because AI crawlers are
            # refused by the same rule. Rank it first, not last.
            low = outcome.lower()
            refused = any(w in low for w in
                          ("blocked", "challenge", "bot-check", "firewall",
                           "refusing automated", "could not read"))
            if refused:
                print("BLOCKED to crawlers — strong prospect")
                rows.append({"url": url, "vertical": "unknown (site refused the scan)",
                             "geo": 0, "aeo": "", "reviews": "", "social": "", "overall": 0,
                             "top_issue": "Site refuses automated readers — AI crawlers "
                                          "are almost certainly refused too",
                             "report": ""})
                hooks.append(
                    f"### {url}  (could not be read)\n"
                    f"Subject: {url} and ChatGPT\n\n"
                    f"I tried to check how {url} looks to AI assistants like ChatGPT and "
                    f"Claude, and the site turned the reader away before it saw any content. "
                    f"That usually means a firewall setting is refusing automated visitors — "
                    f"and the crawlers those assistants use get the same treatment, so the "
                    f"site can't be quoted in their answers. It's usually a small change for "
                    f"whoever manages the site. Happy to show you what I saw, free, in 15 "
                    f"minutes.\n\n"
                    f"{SENDER_NAME} · {SENDER_COMPANY} · {SENDER_POSTAL}\n"
                    f'Reply "no thanks" and I won\'t write again.\n'
                )
            else:
                print("skipped (couldn't fetch)")
                rows.append({"url": url, "vertical": "", "geo": "", "aeo": "", "reviews": "",
                             "social": "", "overall": "",
                             "top_issue": f"FETCH FAILED: {outcome[:80]}", "report": ""})
            if i < len(urls):
                time.sleep(PAUSE_SECONDS)
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
            hooks.append(hook_for(outcome, overall, top))
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
