#!/usr/bin/env python3
"""
AI Visibility Studio — GEO / AEO checker
========================================
One file. No installs. Python 3.9+ standard library only.

WHAT IT DOES (plain English)
  1. You run this file. It opens a small website on YOUR computer only.
  2. You paste in any URL and press "Run check".
  3. It downloads that page the same way an AI crawler would (no JavaScript),
     inspects it, and gives four scores:
        GEO     -> "Can AI systems access, read and trust this page?"
        AEO     -> "Is the content shaped like answers an AI can quote?"
        REVIEWS -> "Do engines see proof: review schema, testimonials,
                    a linked Google Business Profile — and (optionally,
                    with a free Google Places API key) your live Google
                    rating and review count?"
        SOCIAL  -> "Is the brand's social footprint (Instagram, Facebook,
                    LinkedIn, YouTube, TikTok, X, Reddit) linked and
                    declared via sameAs schema so engines connect it all
                    to one entity?"
     Note: Google and Meta block anonymous scraping, so review/social data
     comes from what your SITE declares (the signals engines actually use)
     plus the official Google Places API if you set GOOGLE_PLACES_API_KEY.
  4. It writes a designed, self-contained HTML report (summary + scores +
     prioritized recommendations) into a `reports/` folder next to this file,
     and shows it in your browser.

HOW TO RUN (Mac Terminal)
  cd <folder containing this file>
  python3 ai_visibility_studio.py
  ... then open the address it prints (usually http://localhost:8765)

ALTERNATIVE: one-off check from the command line, no browser UI:
  python3 ai_visibility_studio.py https://example.com
"""

from __future__ import annotations

import datetime as _dt
import gzip
import html as _html
import io
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------------------
# 1. WHO ARE THE AI CRAWLERS?
#    Citation bots fetch pages to ANSWER user questions (this drives traffic
#    and mentions). Training bots only collect data for model training.
#    Blocking citation bots is the single most damaging GEO mistake.
# ---------------------------------------------------------------------------

CITATION_BOTS = [
    ("OAI-SearchBot", "ChatGPT search index"),
    ("ChatGPT-User", "ChatGPT live browsing for a user"),
    ("Claude-SearchBot", "Claude search index"),
    ("Claude-User", "Claude live browsing for a user"),
    ("PerplexityBot", "Perplexity search index"),
    ("Perplexity-User", "Perplexity live browsing for a user"),
]

TRAINING_BOTS = [
    ("GPTBot", "OpenAI model training"),
    ("ClaudeBot", "Anthropic model training"),
    ("Google-Extended", "Gemini training & grounding"),
    ("CCBot", "Common Crawl (feeds many models)"),
    ("Applebot-Extended", "Apple Intelligence training"),
]

REQUEST_UA = (
    "Mozilla/5.0 (compatible; AIVisibilityStudio/1.0; personal diagnostic tool)"
)

# ---------------------------------------------------------------------------
# 2. FETCHING — download a page the way a crawler does (raw HTML, no JS)
# ---------------------------------------------------------------------------


@dataclass
class Fetched:
    ok: bool
    url: str
    final_url: str = ""
    status: int = 0
    body: str = ""
    error: str = ""
    https: bool = False


# Used only to retry a site that turned the scanner away. If this succeeds
# where the honest crawler UA failed, that is itself the finding.
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Interstitials that mean "a bot check ran", not "this is the page".
CHALLENGE_MARKERS = (
    "just a moment", "checking your browser", "cf-browser-verification",
    "enable javascript and cookies to continue", "attention required",
    "ddos protection by", "access denied", "sucuri website firewall",
    "request unsuccessful. incapsula", "verifying you are human",
)


def looks_like_challenge(body: str) -> bool:
    head = body[:4000].lower()
    return any(marker in head for marker in CHALLENGE_MARKERS)


def fetch(url: str, timeout: int = 20, ua: str = "") -> Fetched:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": ua or REQUEST_UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Encoding": "gzip",
            "Accept-Language": "en-US,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(4_000_000)  # cap at ~4 MB
            if resp.headers.get("Content-Encoding", "") == "gzip":
                try:
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                except OSError:
                    pass
            charset = resp.headers.get_content_charset() or "utf-8"
            body = raw.decode(charset, errors="replace")
            final = resp.geturl()
            return Fetched(
                ok=True,
                url=url,
                final_url=final,
                status=resp.status,
                body=body,
                https=final.startswith("https://"),
            )
    except urllib.error.HTTPError as e:
        return Fetched(ok=False, url=url, status=e.code, error=f"HTTP {e.code} {e.reason}")
    except Exception as e:  # noqa: BLE001 — show any failure to the user plainly
        return Fetched(ok=False, url=url, error=str(e))


# ---------------------------------------------------------------------------
# 3. ROBOTS.TXT — which AI crawlers are allowed in?
# ---------------------------------------------------------------------------


def parse_robots(text: str) -> list[dict]:
    """Return [{'agents': [...], 'disallow': [...], 'allow': [...]}] groups."""
    groups: list[dict] = []
    current: dict | None = None
    last_was_agent = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key == "user-agent":
            if current is None or not last_was_agent:
                current = {"agents": [], "disallow": [], "allow": []}
                groups.append(current)
            current["agents"].append(val.lower())
            last_was_agent = True
        elif key in ("disallow", "allow") and current is not None:
            current[key].append(val)
            last_was_agent = False
        else:
            last_was_agent = False
    return groups


def _rule_match(pattern: str, path: str) -> int:
    """
    Length of `pattern` if it matches `path`, else -1.

    Implements the matching rules the search engines actually use: `*` stands
    for any run of characters and `$` anchors the end. An empty pattern
    (`Disallow:` with nothing after it) matches nothing, which is how a site
    says "allow everything".
    """
    if not pattern:
        return -1
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    rx = ".*".join(re.escape(part) for part in body.split("*"))
    if anchored:
        rx += "$"
    return len(pattern) if re.match(rx, path) else -1


def bot_access(groups: list[dict], bot: str, path: str = "/") -> str:
    """
    Can this bot fetch `path`?

      'allowed' — yes, and nothing on the site is disallowed for it
      'partial' — yes, this page is reachable; other paths are disallowed
      'blocked' — no, this page itself is disallowed

    'partial' is informational only. Nearly every WordPress site disallows
    /wp-admin/, which says nothing whatever about whether an AI crawler can
    read the page being scanned — so it must not cost a site any points.
    """
    bot_l = bot.lower()
    matched = None
    for g in groups:
        if any(a == bot_l for a in g["agents"]):
            matched = g
            break
    if matched is None:
        for g in groups:
            if "*" in g["agents"]:
                matched = g
                break
    if matched is None:
        return "allowed"

    # Most specific rule wins; an equally specific Allow beats a Disallow.
    best_dis = max((_rule_match(d, path) for d in matched["disallow"]), default=-1)
    best_allow = max((_rule_match(a, path) for a in matched["allow"]), default=-1)

    if best_dis > best_allow:
        return "blocked"
    # 'partial' means some OTHER path is disallowed — a rule that does not
    # apply to the page we scanned. A Disallow the Allow overrode is not that.
    if any(_rule_match(d, path) < 0 for d in matched["disallow"] if d.strip()):
        return "partial"
    return "allowed"


# ---------------------------------------------------------------------------
# 4. HTML ANALYSIS — read the page like an AI would
# ---------------------------------------------------------------------------

SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head"}
QUESTION_WORDS = ("what", "why", "how", "when", "where", "who", "which", "can", "do", "does", "is", "are", "should")

# Platforms AI assistants connect to a brand's identity.
SOCIAL_PLATFORMS = {
    "instagram.com": "Instagram", "facebook.com": "Facebook", "fb.com": "Facebook",
    "linkedin.com": "LinkedIn", "youtube.com": "YouTube", "youtu.be": "YouTube",
    "tiktok.com": "TikTok", "twitter.com": "X (Twitter)", "x.com": "X (Twitter)",
    "reddit.com": "Reddit", "pinterest.com": "Pinterest",
    "github.com": "GitHub", "threads.net": "Threads", "threads.com": "Threads",
    "bsky.app": "Bluesky", "mastodon.social": "Mastodon", "discord.gg": "Discord",
    "discord.com": "Discord", "substack.com": "Substack", "medium.com": "Medium",
}

# Third-party review surfaces. For anything that isn't a walk-in business these
# matter far more than a Google Business Profile — a SaaS company's reviews live
# on G2, not on Maps.
REVIEW_PLATFORMS = {
    "g2.com": "G2", "capterra.com": "Capterra", "trustradius.com": "TrustRadius",
    "trustpilot.com": "Trustpilot", "producthunt.com": "Product Hunt",
    "getapp.com": "GetApp", "softwareadvice.com": "Software Advice",
    "clutch.co": "Clutch", "glassdoor.com": "Glassdoor",
    "apps.apple.com": "App Store", "play.google.com": "Google Play",
    "yelp.com": "Yelp", "tripadvisor.com": "Tripadvisor",
    "checkatrade.com": "Checkatrade", "angi.com": "Angi", "houzz.com": "Houzz",
}

# ---------------------------------------------------------------------------
# 1b. VERTICALS — what counts as "good" depends on what kind of business it is
#
# A dentist without a Google Business Profile has a real problem. A B2B SaaS
# company without one has nothing wrong at all. Scoring both against the same
# checklist makes the second look broken when it isn't, so each vertical gets
# its own weighting and its own set of applicable review checks.
# ---------------------------------------------------------------------------

VERTICAL_LABELS = {
    "local": "Local / in-person business",
    "services": "Professional services firm",
    "ecommerce": "Online store",
    "saas": "Software / B2B product",
    "publisher": "Publisher / content site",
    "general": "General business",
}

# (website, reviews, social) — each row sums to 1.0
VERTICAL_WEIGHTS = {
    "local":     (0.40, 0.40, 0.20),
    "services":  (0.45, 0.35, 0.20),
    "ecommerce": (0.50, 0.30, 0.20),
    "general":   (0.50, 0.25, 0.25),
    "saas":      (0.65, 0.12, 0.23),
    "publisher": (0.70, 0.05, 0.25),
}

# Verticals where a Google Business Profile is the review signal that matters.
LOCAL_LIKE = {"local", "services"}

# The platforms AI answers cite most, per vertical.
VERTICAL_HIGH_CITATION = {
    "local":     {"YouTube", "Facebook", "Instagram"},
    "services":  {"LinkedIn", "YouTube", "Reddit"},
    "ecommerce": {"YouTube", "Instagram", "TikTok"},
    "saas":      {"LinkedIn", "YouTube", "Reddit"},
    "publisher": {"YouTube", "Reddit", "LinkedIn"},
    "general":   {"YouTube", "LinkedIn", "Reddit"},
}
HIGH_CITATION = {"YouTube", "LinkedIn", "Reddit"}  # kept for backwards compatibility

# --- classification signals -------------------------------------------------

LOCAL_SCHEMA = {
    "localbusiness", "restaurant", "store", "dentist", "physician", "medicalbusiness",
    "autorepair", "plumber", "electrician", "hotel", "lodgingbusiness", "hairsalon",
    "foodestablishment", "cafe", "bakery", "bar", "gym", "exercisegym", "daycare",
    "healthandbeautybusiness", "sportsactivitylocation", "veterinarycare",
    "homeandconstructionbusiness", "childcare", "emergencyservice", "travelagency",
    "realestateagent", "shoppingcenter", "automotivebusiness", "place",
}
SERVICES_SCHEMA = {
    "professionalservice", "attorney", "legalservice", "accountingservice",
    "financialservice", "insuranceagency", "consultingservice", "employmentagency",
}
SAAS_SCHEMA = {"softwareapplication", "webapplication", "mobileapplication", "apireference"}
ECOM_SCHEMA = {"product", "aggregateoffer", "onlinestore"}
PUB_SCHEMA = {"newsarticle", "blogposting", "blog", "techarticle", "liveblogposting"}

ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+[A-Za-z][A-Za-z.'\- ]{2,40}\b"
    r"(street|st|road|rd|avenue|ave|boulevard|blvd|drive|dr|lane|ln|way|court|ct"
    r"|place|pl|highway|hwy|parkway|pkwy|turnpike|pike|circle|cir|square|sq)\b", re.I)
US_PHONE_RE = re.compile(r"(\(\d{3}\)\s*|\b\d{3}[.\-\s])\d{3}[.\-\s]?\d{4}\b")
US_ZIP_RE = re.compile(r"\b[A-Z]{2}\s+\d{5}(-\d{4})?\b")

# Trades and practices people visit in person. On their own these say little;
# with an address on the page they settle it.
PRACTICE_WORDS = (
    "dentist", "dental", "orthodont", "periodont", "chiropract", "physical therapy",
    "attorney", "law firm", "lawyer", "injury", "clinic", "practice", "physician",
    "veterinar", "salon", "barber", "spa", "hvac", "heating and air", "plumbing",
    "roofing", "landscap", "auto repair", "collision", "tire", "pediatric",
    "optometr", "dermatolog", "urgent care", "med spa", "wellness center",
)

TEXT_SIGNALS = [
    ("local", 1.2, [
        "reservations", "order online", "our menu", "view menu", "takeout",
        "dine-in", "catering menu", "byob", "happy hour", "daily specials",
        "opening hours", "store hours", "hours of operation", "our location",
        "get directions", "book an appointment", "walk-ins", "same-day service",
        "free estimate", "call us today", "serving the", "visit our showroom",
    ]),
    ("services", 1.0, [
        "our services", "case studies", "free consultation", "practice areas",
        "our clients", "request a quote", "schedule a consultation",
    ]),
    ("ecommerce", 1.2, [
        "add to cart", "add to bag", "add to basket", "free shipping", "checkout",
        "shop now", "in stock", "size guide", "returns policy", "your cart",
    ]),
    ("saas", 1.0, [
        "free trial", "book a demo", "request a demo", "start for free", "per user",
        "per month", "integrations", "api documentation", "single sign-on",
        "no credit card", "sign up free", "our platform", "developer docs",
    ]),
    ("publisher", 1.0, [
        "subscribe to our newsletter", "latest articles", "view archive",
        "editorial team", "our writers", "read the full story", "most popular",
    ]),
]


def detect_platform(href: str) -> str | None:
    try:
        host = urllib.parse.urlparse(href).netloc.lower().removeprefix("www.")
    except ValueError:
        return None
    for domain, name in SOCIAL_PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def detect_review_platform(href: str) -> str | None:
    try:
        host = urllib.parse.urlparse(href).netloc.lower().removeprefix("www.")
    except ValueError:
        return None
    for domain, name in REVIEW_PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def classify_vertical(jsonld_types: list[str], body_lower: str,
                      gbp_link: bool) -> tuple[str, str]:
    """
    Work out what kind of business this is, so it gets scored against the right
    checklist. Returns (vertical_key, one-line explanation of the evidence).

    Schema.org types are the strongest evidence; on-page language breaks ties.
    When nothing is conclusive we fall back to "general", which keeps the
    original balanced weighting rather than guessing.
    """
    types = {t.lower() for t in jsonld_types}
    scores = {"local": 0.0, "services": 0.0, "ecommerce": 0.0,
              "saas": 0.0, "publisher": 0.0}
    evidence: list[str] = []

    schema_hits = [
        ("local", LOCAL_SCHEMA, 5.0), ("services", SERVICES_SCHEMA, 5.0),
        ("saas", SAAS_SCHEMA, 5.0), ("ecommerce", ECOM_SCHEMA, 3.5),
        ("publisher", PUB_SCHEMA, 2.5),
    ]
    for key, vocabulary, weight in schema_hits:
        matched = types & vocabulary
        if matched:
            scores[key] += weight
            evidence.append(f"{sorted(matched)[0]} schema")

    if "postaladdress" in types or "openinghoursspecification" in types:
        scores["local"] += 3.0
        evidence.append("address/opening-hours schema")

    # A visible street address plus a phone number: a place you can walk into.
    has_address = bool(ADDRESS_RE.search(body_lower) or US_ZIP_RE.search(body_lower.upper()))
    has_phone = bool(US_PHONE_RE.search(body_lower))
    if has_address and has_phone:
        scores["local"] += 3.0
        evidence.append("street address and phone number on the page")
    elif has_address:
        scores["local"] += 1.5
        evidence.append("street address on the page")

    practice = next((w for w in PRACTICE_WORDS if w in body_lower), None)
    if practice and (has_address or has_phone):
        scores["local"] += 2.5
        evidence.append(f"“{practice}” with contact details")
    if gbp_link:
        scores["local"] += 3.0
        evidence.append("Google Business Profile link")

    for key, weight, phrases in TEXT_SIGNALS:
        hits = [p for p in phrases if p in body_lower]
        if hits:
            scores[key] += min(len(hits) * weight, 3.0)
            evidence.append(f"“{hits[0]}” on the page")

    best = max(scores, key=lambda k: scores[k])
    if scores[best] < 3.0:
        return "general", "no strong signals either way, so balanced weighting was used"
    return best, ", ".join(evidence[:3])


def is_gbp_link(href: str) -> bool:
    """
    Does this link point at a Google Business Profile?

    Covers the short links Google itself hands out (goo.gl/maps, maps.app.goo.gl)
    and the embed URL used by an embedded map, both of which owners use far more
    often than the long canonical form.
    """
    h = href.lower()
    return ("maps.google" in h or "google.com/maps" in h or "g.page" in h
            or "search.google.com/local" in h or "g.co/kgs" in h
            or "goo.gl/maps" in h or "maps.app.goo.gl" in h
            or "google.com/maps/embed" in h)


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.in_title = False
        self.heading_level = 0
        self.heading_buf: list[str] = []
        self.in_p = False
        self.p_buf: list[str] = []

        self.title = ""
        self.meta: dict[str, str] = {}
        self.canonical = ""
        self.headings: list[tuple[int, str]] = []
        self.paragraphs: list[str] = []
        self.text_chunks: list[str] = []
        self.jsonld_raw: list[str] = []
        self._in_jsonld = False
        self.lists = 0
        self.tables = 0
        self.imgs = 0
        self.imgs_with_alt = 0
        self.links_internal = 0
        self.links_external = 0
        self.time_tags = 0
        self.base_host = ""
        self.social: dict[str, str] = {}   # platform name -> first URL seen
        self.review_links: dict[str, str] = {}  # review site name -> first URL seen
        self.gbp_link = False              # links to a Google Business Profile

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script":
            if (a.get("type") or "").lower().strip() == "application/ld+json":
                self._in_jsonld = True
                self.jsonld_raw.append("")
            self.skip_depth += 1
            return
        if tag in SKIP_TAGS:
            self.skip_depth += 1
            return
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name and a.get("content"):
                self.meta.setdefault(name, a["content"])
        elif tag == "link" and (a.get("rel") or "").lower() == "canonical":
            self.canonical = a.get("href", "")
        elif tag in ("h1", "h2", "h3", "h4"):
            self.heading_level = int(tag[1])
            self.heading_buf = []
        elif tag == "p":
            self.in_p = True
            self.p_buf = []
        elif tag in ("ul", "ol"):
            self.lists += 1
        elif tag == "table":
            self.tables += 1
        elif tag == "time":
            self.time_tags += 1
        elif tag == "img":
            self.imgs += 1
            if (a.get("alt") or "").strip():
                self.imgs_with_alt += 1
        elif tag == "a":
            href = a.get("href", "")
            if href.startswith(("http://", "https://")):
                host = urllib.parse.urlparse(href).netloc.lower()
                if self.base_host and host.endswith(self.base_host):
                    self.links_internal += 1
                else:
                    self.links_external += 1
                platform = detect_platform(href)
                if platform:
                    self.social.setdefault(platform, href)
                review_site = detect_review_platform(href)
                if review_site:
                    self.review_links.setdefault(review_site, href)
                if is_gbp_link(href):
                    self.gbp_link = True
            elif href and not href.startswith(("#", "mailto:", "javascript:", "tel:")):
                self.links_internal += 1

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            if tag == "script":
                self._in_jsonld = False
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if tag == "title":
            self.in_title = False
        elif tag in ("h1", "h2", "h3", "h4") and self.heading_level:
            text = " ".join("".join(self.heading_buf).split())
            if text:
                self.headings.append((self.heading_level, text))
            self.heading_level = 0
        elif tag == "p" and self.in_p:
            text = " ".join("".join(self.p_buf).split())
            if text:
                self.paragraphs.append(text)
            self.in_p = False

    def handle_data(self, data):
        if self._in_jsonld and self.jsonld_raw:
            self.jsonld_raw[-1] += data
            return
        # <title> sits inside <head>, which is a skipped tag — so this must be
        # checked before the skip guard or the title is silently thrown away.
        if self.in_title:
            self.title += data
        if self.skip_depth:
            return
        if self.heading_level:
            self.heading_buf.append(data)
        if self.in_p:
            self.p_buf.append(data)
        if data.strip():
            self.text_chunks.append(data.strip())


def extract_jsonld(raw_blocks: list[str]) -> tuple[list[str], list[str]]:
    """Return (@type values, sameAs URLs) found across all JSON-LD blocks."""
    types: list[str] = []
    sameas: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            t = node.get("@type")
            if isinstance(t, str):
                types.append(t)
            elif isinstance(t, list):
                types.extend(x for x in t if isinstance(x, str))
            sa = node.get("sameAs")
            if isinstance(sa, str):
                sameas.append(sa)
            elif isinstance(sa, list):
                sameas.extend(x for x in sa if isinstance(x, str))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue
        try:
            walk(json.loads(block))
        except json.JSONDecodeError:
            continue
    return types, sameas


# ---------------------------------------------------------------------------
# 5. SCORING — turn observations into GEO and AEO scores + recommendations
# ---------------------------------------------------------------------------


@dataclass
class Check:
    pillar: str          # which pillar this belongs to
    label: str           # short name shown in the report
    earned: float        # points earned
    possible: float      # max points
    detail: str          # plain-English one-liner of what we saw
    fix: str = ""        # plain-English fix if points were lost
    priority: str = ""   # High / Medium / Low (only when fix needed)


@dataclass
class Result:
    url: str
    final_url: str
    fetched_at: str
    site_title: str
    geo_score: int = 0
    aeo_score: int = 0
    reviews_score: int = 0
    social_score: int = 0
    checks: list[Check] = field(default_factory=list)
    crawler_rows: list[tuple[str, str, str, str]] = field(default_factory=list)
    spa_warning: bool = False
    word_count: int = 0
    summary: str = ""
    google_live: dict | None = None  # live Places data when an API key is set
    vertical: str = "general"
    vertical_evidence: str = ""
    vertical_forced: bool = False    # True when the caller overrode detection


def vertical_weights(res: "Result") -> tuple[float, float, float]:
    return VERTICAL_WEIGHTS.get(res.vertical, VERTICAL_WEIGHTS["general"])


def weighting_sentence(res: "Result") -> str:
    w_site, w_rev, w_soc = vertical_weights(res)
    return (f"{w_site:.0%} website (GEO+AEO) + {w_rev:.0%} reviews + {w_soc:.0%} social")


def overall_score(res: "Result") -> int:
    """
    Overall score, weighted for the kind of business this is.

    A local business lives or dies on reviews, so they carry 40% there. A B2B
    SaaS product is judged almost entirely on its site and its footprint, so
    reviews carry 12%. Using one fixed weighting for both was making
    well-optimized software companies look broken.
    """
    w_site, w_rev, w_soc = vertical_weights(res)
    site = (res.geo_score + res.aeo_score) / 2
    return round(w_site * site + w_rev * res.reviews_score + w_soc * res.social_score)


def google_reviews_lookup(business_query: str) -> dict | None:
    """
    Fetch the business's live Google rating via the OFFICIAL Places API.
    Optional: set the environment variable GOOGLE_PLACES_API_KEY first, e.g.
        export GOOGLE_PLACES_API_KEY="your-key"     (then run the tool)
    Get a free key at https://console.cloud.google.com (enable Places API).
    Without a key the tool still scores on-site review signals — it just
    can't see the live rating and review count.
    """
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not key or not business_query:
        return None
    params = urllib.parse.urlencode({
        "input": business_query, "inputtype": "textquery",
        "fields": "name,rating,user_ratings_total", "key": key,
    })
    url = f"https://maps.googleapis.com/maps/api/place/findplacefromtext/json?{params}"
    try:
        with urllib.request.urlopen(url, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        cand = (data.get("candidates") or [{}])[0]
        if cand.get("name"):
            return {"name": cand["name"], "rating": cand.get("rating"),
                    "total": cand.get("user_ratings_total")}
    except Exception:
        return None
    return None


def business_name_from(title: str, host: str) -> str:
    for sep in ("|", "—", " – ", " - "):
        if sep in title:
            title = title.split(sep)[0]
    return title.strip() or host


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def analyze(url: str, vertical: str | None = None) -> Result | str:
    """
    Run the full audit. Returns a Result, or an error string.

    Pass `vertical` (one of VERTICAL_WEIGHTS) to override auto-detection when
    you already know what kind of business the site is.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    page = fetch(url)

    # Some sites refuse anything that identifies itself as a crawler. Retry
    # once as an ordinary browser: if that works, the site is reachable but
    # hostile to automated readers — which is a finding in its own right,
    # because AI crawlers are turned away by the same rule.
    turned_away_bots = False
    if (not page.ok and page.status in (401, 403, 406, 418, 429, 503)) or \
       (page.ok and looks_like_challenge(page.body)):
        retry = fetch(url, ua=BROWSER_UA)
        if retry.ok and not looks_like_challenge(retry.body):
            page = retry
            turned_away_bots = True

    if not page.ok:
        reason = ("blocked" if page.status in (401, 403, 406, 418) else
                  "rate-limited" if page.status == 429 else
                  "unavailable" if page.status and page.status >= 500 else
                  "not-found" if page.status == 404 else "unreachable")
        return (f"Could not read {url} — {page.error or 'unknown error'} ({reason}). "
                "If the site is up in a browser, its firewall is refusing automated "
                "readers, which means AI crawlers are very likely refused too.")
    if looks_like_challenge(page.body):
        return (f"Could not read {url} — the site returned a bot-check page instead of "
                "the content (challenge). AI crawlers hit the same wall, so this page "
                "cannot currently be cited by them.")

    parsed = urllib.parse.urlparse(page.final_url)
    host = parsed.netloc.lower()
    p = PageParser()
    p.base_host = host.removeprefix("www.")
    try:
        p.feed(page.body)
    except Exception:
        pass  # tolerate broken HTML; keep whatever was parsed

    # Refuse to grade a page we plainly did not receive. Scoring an empty or
    # intercepted response produces an F and a fix list telling the owner to
    # add things their page already has — worse than no answer at all.
    _words = sum(len(c.split()) for c in p.text_chunks)
    if _words < 50 and not p.headings and not p.title.strip():
        return (f"Could not read {page.final_url} the way an AI crawler would — "
                f"the response contained no readable text, headings or title "
                f"({_words} words). The page may be behind a firewall or served "
                "only to browsers. It has not been scored, because a score from "
                "an empty response would be meaningless.")

    # robots.txt
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    robots = fetch(robots_url, timeout=10)
    groups = parse_robots(robots.body) if robots.ok else []

    res = Result(
        url=url,
        final_url=page.final_url,
        fetched_at=_dt.datetime.now().strftime("%B %d, %Y at %H:%M"),
        site_title=" ".join(p.title.split()) or host,
    )
    checks = res.checks

    # ---------------- GEO pillar A: ACCESS (30 pts) ----------------
    # The page we actually scanned — a rule about /wp-admin/ says nothing
    # about whether this page is reachable.
    scanned_path = urllib.parse.urlparse(res.final_url).path or "/"

    cite_total = len(CITATION_BOTS)
    cite_allowed = 0
    for bot, role in CITATION_BOTS:
        status = bot_access(groups, bot, scanned_path) if robots.ok else "allowed"
        # 'partial' means this page is reachable but some other path is not.
        if status in ("allowed", "partial"):
            cite_allowed += 1
        res.crawler_rows.append((bot, role, "Citation", status))
    for bot, role in TRAINING_BOTS:
        status = bot_access(groups, bot, scanned_path) if robots.ok else "allowed"
        res.crawler_rows.append((bot, role, "Training", status))

    access_pts = 30 * (cite_allowed / cite_total)
    blocked_bots = [r[0] for r in res.crawler_rows if r[2] == "Citation" and r[3] == "blocked"]
    checks.append(Check(
        "GEO · Access", "AI citation crawlers allowed",
        round(access_pts, 1), 30,
        (f"{cite_allowed} of {cite_total} citation crawlers can reach this page"
         + (f" (robots.txt blocks: {', '.join(blocked_bots)})" if blocked_bots else "")
         + ("" if robots.ok else " — no robots.txt found, so everything is allowed by default")),
        fix=("Add these lines to robots.txt, above any existing rules:\n\n"
             + "\n".join(f"User-agent: {b}\nAllow: /\n" for b in blocked_bots)
             + "\nThese crawlers fetch pages to answer real user questions — blocking them "
               "removes the site from AI answers entirely. Training-only bots (GPTBot, "
               "ClaudeBot, Google-Extended) can still be blocked separately if you wish."
             ) if blocked_bots else "",
        priority="High" if blocked_bots else "",
    ))

    if turned_away_bots:
        checks.append(Check(
            "GEO · Access", "Firewall turns away automated readers", 0, 0,
            "The site refused a request that identified itself as a crawler, and "
            "answered only when the scan pretended to be a browser",
            fix="Your firewall or bot protection (Cloudflare, Sucuri, or similar) is "
                "challenging automated readers. AI citation crawlers are refused by the "
                "same rule and cannot quote pages they cannot fetch. Ask whoever manages "
                "the site to allow OAI-SearchBot, Claude-SearchBot and PerplexityBot "
                "through the firewall — this is separate from robots.txt.",
            priority="High",
        ))

    https_pts = 5 if page.https else 0
    checks.append(Check(
        "GEO · Access", "Served over HTTPS", https_pts, 5,
        "Page is served over HTTPS" if page.https else "Page is not on HTTPS",
        fix="" if page.https else "Install an SSL certificate; AI engines deprioritize non-HTTPS sources.",
        priority="" if page.https else "High",
    ))

    # ---------------- GEO pillar B: MACHINE-READABLE CONTENT (30 pts) -------
    words = sum(len(c.split()) for c in p.text_chunks)
    res.word_count = words
    word_pts = clamp((words / 600) * 20, 0, 20)
    spa = words < 120 and ("id=\"root\"" in page.body or "id=\"app\"" in page.body or page.body.count("<script") >= 8)
    res.spa_warning = spa
    checks.append(Check(
        "GEO · Content", "Readable text without JavaScript",
        round(word_pts, 1), 20,
        f"{words} words of visible text in the raw HTML"
        + (" — this looks like a JavaScript-rendered app; crawlers that don't run JS may see almost nothing" if spa else ""),
        fix=(("Server-render or pre-render the page so the main content is present in the raw "
              "HTML. Most AI crawlers do not execute JavaScript — content that only appears "
              "after JS runs is invisible to them.") if spa else
             ("Add at least 300 words of real content to this page. There is very little text "
              "for an assistant to quote: cover what you do, who you serve and where, in "
              "sentences someone could lift straight into an answer.")
             ) if words < 300 else "",
        priority="High" if words < 300 else "",
    ))

    ratio = len(" ".join(p.text_chunks)) / max(len(page.body), 1)
    ratio_pts = clamp(ratio / 0.10 * 10, 0, 10)
    checks.append(Check(
        "GEO · Content", "Text-to-code ratio",
        round(ratio_pts, 1), 10,
        f"{ratio:.0%} of the page's HTML is actual readable text",
        fix=("Trim heavy scripts, inline styles and markup bloat. A page that is mostly code makes it "
             "harder and costlier for AI systems to extract the substance.") if ratio < 0.05 else "",
        priority="Low" if ratio < 0.05 else "",
    ))

    # ---------------- GEO pillar C: TRUST (25 pts) ----------------
    author = bool(p.meta.get("author") or p.meta.get("article:author")
                  or re.search(r"\bby\s+[A-Z][a-z]+\s+[A-Z][a-z]+", page.body[:60000]))
    date = bool(p.meta.get("article:published_time") or p.meta.get("article:modified_time")
                or p.time_tags or re.search(r"datePublished", page.body))
    checks.append(Check(
        "GEO · Trust", "Named author / byline", 8 if author else 0, 8,
        "An author or byline is present" if author else "No author or byline detected",
        fix="" if author else "Add a visible byline and an author meta tag or schema author. AI engines weigh accountable, attributed content more heavily.",
        priority="" if author else "Medium",
    ))
    checks.append(Check(
        "GEO · Trust", "Published / updated dates", 8 if date else 0, 8,
        "Publish or update dates are present" if date else "No publish/update dates detected",
        fix="" if date else "Add visible dates plus datePublished/dateModified in schema. Freshness is a major selection signal for AI answers.",
        priority="" if date else "Medium",
    ))
    ext_pts = clamp(p.links_external / 5 * 9, 0, 9)
    checks.append(Check(
        "GEO · Trust", "Outbound references", round(ext_pts, 1), 9,
        f"{p.links_external} outbound links to other sites",
        fix=("Cite sources: link claims and statistics to reputable external references. "
             "Sourced content reads as evidence, not marketing, to AI systems.") if p.links_external < 3 else "",
        priority="Medium" if p.links_external < 3 else "",
    ))

    # ---------------- GEO pillar D: PAGE IDENTITY (15 pts) ----------------
    title_ok = 10 <= len(res.site_title) <= 70
    desc = p.meta.get("description", "")
    desc_ok = 50 <= len(desc) <= 170
    checks.append(Check(
        "GEO · Identity", "Clear page title", 5 if title_ok else (2 if res.site_title else 0), 5,
        f"Title: “{res.site_title[:80]}”" if res.site_title else "No <title> found",
        fix="" if title_ok else "Write a 10–70 character title that states plainly what the page is about.",
        priority="" if title_ok else "Medium",
    ))
    checks.append(Check(
        "GEO · Identity", "Meta description",
        5 if desc_ok else (4 if 170 < len(desc) <= 200 else (2 if desc else 0)), 5,
        f"Description is {len(desc)} characters" if desc else "No meta description",
        fix="" if desc_ok else (
            # A description that exists but runs slightly long is a nitpick,
            # not a problem worth an owner's attention.
            f"Trim the meta description to 170 characters or fewer (it is {len(desc)})."
            if 170 < len(desc) <= 200 else
            "Add a 50–170 character meta description that answers “what is this page?” in one sentence."),
        priority="" if desc_ok else ("Low" if 170 < len(desc) <= 200 else "Medium"),
    ))
    checks.append(Check(
        "GEO · Identity", "Canonical URL", 5 if p.canonical else 0, 5,
        "Canonical link present" if p.canonical else "No canonical link",
        fix="" if p.canonical else "Add <link rel=\"canonical\"> so engines consolidate signals onto one authoritative URL.",
        priority="" if p.canonical else "Low",
    ))

    # ================= AEO =================
    # ---------------- AEO pillar A: STRUCTURE (30 pts) ----------------
    h1s = [h for h in p.headings if h[0] == 1]
    subheads = [h for h in p.headings if h[0] in (2, 3)]
    h1_pts = 8 if len(h1s) == 1 else (4 if h1s else 0)
    checks.append(Check(
        "AEO · Structure", "Single clear H1", h1_pts, 8,
        f"{len(h1s)} H1 heading(s) found",
        fix="" if len(h1s) == 1 else "Use exactly one H1 that names the page's core topic.",
        priority="" if len(h1s) == 1 else "Medium",
    ))
    sub_pts = clamp(len(subheads) / 6 * 12, 0, 12)
    checks.append(Check(
        "AEO · Structure", "Section subheadings (H2/H3)", round(sub_pts, 1), 12,
        f"{len(subheads)} subheadings break the page into sections",
        fix=("Break content into H2/H3 sections of 150–300 words each. AI engines lift self-contained "
             "sections as answers — walls of text rarely get quoted.") if len(subheads) < 3 else "",
        priority="High" if len(subheads) < 3 else "",
    ))
    li_pts = clamp((p.lists + p.tables) / 3 * 10, 0, 10)
    checks.append(Check(
        "AEO · Structure", "Lists and tables", round(li_pts, 1), 10,
        f"{p.lists} lists and {p.tables} tables",
        fix=("Convert steps, comparisons and feature sets into lists or tables — the formats AI engines "
             "extract most reliably.") if (p.lists + p.tables) < 2 else "",
        priority="Medium" if (p.lists + p.tables) < 2 else "",
    ))

    # ---------------- AEO pillar B: QUESTION COVERAGE (25 pts) -------------
    q_heads = [h for (_, h) in p.headings
               if h.rstrip().endswith("?") or h.split(" ")[0].lower() in QUESTION_WORDS]
    q_pts = clamp(len(q_heads) / 4 * 15, 0, 15)
    checks.append(Check(
        "AEO · Questions", "Question-style headings", round(q_pts, 1), 15,
        f"{len(q_heads)} headings phrased as questions (e.g. “How does…”, “What is…”)",
        fix=("Rewrite key headings as the literal questions your customers ask AI assistants "
             "(“What does X cost?”, “How do I…?”). AI engines match user questions to question-shaped sections.") if len(q_heads) < 2 else "",
        priority="High" if len(q_heads) < 2 else "",
    ))
    faq_text = any("faq" in h.lower() or "frequently asked" in h.lower() for (_, h) in p.headings)
    jsonld_types, jsonld_sameas = extract_jsonld(p.jsonld_raw)
    faq_schema = any(t.lower() == "faqpage" for t in jsonld_types)
    faq_pts = 10 if (faq_schema or faq_text) else 0
    checks.append(Check(
        "AEO · Questions", "FAQ section", faq_pts, 10,
        ("FAQ present" + (" with FAQPage schema" if faq_schema else " (text only, no FAQPage schema)"))
        if (faq_schema or faq_text) else "No FAQ section detected",
        fix="" if faq_schema else ("Add an FAQ section answering the 5–8 questions buyers actually ask, "
                                   "and mark it up with FAQPage schema so engines can parse Q→A pairs directly."),
        priority="" if faq_schema else ("Medium" if faq_text else "High"),
    ))

    # ---------------- AEO pillar C: STRUCTURED DATA (30 pts) ---------------
    sd_pts = 0.0
    if jsonld_types:
        sd_pts = 15
        rich = {"article", "newsarticle", "blogposting", "faqpage", "howto", "product",
                "organization", "person", "breadcrumblist", "website", "softwareapplication", "service"}
        bonus = len({t.lower() for t in jsonld_types} & rich)
        sd_pts += clamp(bonus * 4, 0, 15)
    shown_types = ", ".join(sorted(set(jsonld_types))[:8]) if jsonld_types else "none"
    checks.append(Check(
        "AEO · Labels", "Schema.org structured data", round(sd_pts, 1), 30,
        f"JSON-LD types found: {shown_types}",
        fix=("Add JSON-LD structured data (Organization on the home page; Article/BlogPosting with author "
             "and dates on content; FAQPage on FAQs; Product/Service where relevant). Schema is how you "
             "label content so machines understand it without guessing.") if sd_pts < 20 else "",
        priority="High" if sd_pts == 0 else ("Medium" if sd_pts < 20 else ""),
    ))

    # ---------------- AEO pillar D: ANSWER SHAPE (15 pts) ----------------
    crisp = [pp for pp in p.paragraphs if 30 <= len(pp.split()) <= 70]
    crisp_pts = clamp(len(crisp) / 4 * 9, 0, 9)
    checks.append(Check(
        "AEO · Answer shape", "Quotable answer paragraphs", round(crisp_pts, 1), 9,
        f"{len(crisp)} paragraphs are in the 30–70 word “liftable answer” range",
        fix=("Open each section with one 40–60 word paragraph that directly answers the section's question. "
             "This is the unit AI engines quote verbatim.") if len(crisp) < 2 else "",
        priority="Medium" if len(crisp) < 2 else "",
    ))
    alt_pts = 6 * (p.imgs_with_alt / p.imgs) if p.imgs else 6
    checks.append(Check(
        "AEO · Answer shape", "Image alt text", round(alt_pts, 1), 6,
        (f"{p.imgs_with_alt} of {p.imgs} images have alt text" if p.imgs else "No images on the page (nothing to fix)"),
        fix=("Describe every meaningful image in its alt attribute; it is the only way image content "
             "reaches a text-based engine.") if p.imgs and p.imgs_with_alt < p.imgs else "",
        priority="Low" if (p.imgs and p.imgs_with_alt < p.imgs) else "",
    ))

    # ================= REVIEWS (proof signals, per vertical) =============
    body_l = page.body.lower()

    # Work out what kind of business this is before scoring proof signals.
    if vertical and vertical in VERTICAL_WEIGHTS:
        res.vertical = vertical
        res.vertical_forced = True
        res.vertical_evidence = "set manually"
    else:
        res.vertical, res.vertical_evidence = classify_vertical(
            jsonld_types, body_l, p.gbp_link)
    local_like = res.vertical in LOCAL_LIKE

    has_agg = (any(t.lower() in ("aggregaterating", "review") for t in jsonld_types)
               or '"aggregaterating"' in body_l)
    checks.append(Check(
        "Reviews", "Review schema (AggregateRating)", 20 if has_agg else 0, 20,
        "Review/AggregateRating structured data found" if has_agg else "No review structured data",
        fix="" if has_agg else ("Add AggregateRating + Review JSON-LD with your real rating and count. "
                                "This is how AI engines read 'this business is rated 4.8 by 127 customers' "
                                "directly from your site instead of guessing."),
        priority="" if has_agg else ("High" if local_like else "Medium"),
    ))
    proof = bool(re.search(r"testimonial|★|⭐|out of 5|trustpilot|google reviews|customer reviews|case study", body_l))
    checks.append(Check(
        "Reviews", "Customer proof on the page", 15 if proof else 0, 15,
        "Testimonials or review content visible" if proof else "No testimonials or review content detected",
        fix="" if proof else ("Add 3–5 named customer quotes or embedded reviews. AI assistants weigh "
                              "social proof when deciding which business to recommend."),
        priority="" if proof else "Medium",
    ))

    if local_like:
        # A walk-in or appointment business: Google Business Profile is the
        # single most valuable review signal, and Gemini reads it directly.
        checks.append(Check(
            "Reviews", "Google Business Profile link", 20 if p.gbp_link else 0, 20,
            "Site links to a Google Maps / Business Profile" if p.gbp_link
            else "No link to a Google Business Profile found",
            fix="" if p.gbp_link else ("Link your Google Business Profile from the site (footer or contact page) "
                                       "and keep name/address/phone identical in both places. This connects your "
                                       "website to your reviews in the engines' entity graph — and Gemini reads "
                                       "GBP data directly."),
            priority="" if p.gbp_link else "High",
        ))
    else:
        # Software, stores and publishers are reviewed somewhere else entirely.
        found = sorted(p.review_links)
        pts = clamp(len(found) / 2 * 20, 0, 20)
        checks.append(Check(
            "Reviews", "Third-party review profiles", round(pts, 1), 20,
            (f"Linked from the site: {', '.join(found)}" if found
             else "No links to third-party review profiles found"),
            fix=("Link the review profiles buyers in your category actually read — G2, Capterra "
                 "or TrustRadius for software, Trustpilot for consumer brands, the App Store or "
                 "Google Play for apps. AI assistants lean on these when asked to compare options, "
                 "and a link from your own site is what ties the profile to your brand."
                 ) if len(found) < 2 else "",
            priority="" if len(found) >= 2 else ("High" if not found else "Medium"),
        ))

    # The live Google lookup only makes sense for businesses with a storefront.
    live = google_reviews_lookup(business_name_from(res.site_title, host)) if local_like else None
    res.google_live = live
    if live and live.get("rating") is not None:
        rating, total = float(live["rating"]), int(live.get("total") or 0)
        r_pts = 25 if rating >= 4.6 else 18 if rating >= 4.2 else 10 if rating >= 3.5 else 4
        checks.append(Check(
            "Reviews", "Live Google rating", r_pts, 25,
            f"“{live['name']}” is rated {rating:.1f} on Google",
            fix=("" if rating >= 4.2 else
                 "Run a reputation program: respond to every review (AI engines see responsiveness), "
                 "fix the root causes named in negative reviews, and rebuild the average with fresh reviews."),
            priority="" if rating >= 4.2 else "High",
        ))
        v_pts = 20 if total >= 100 else 15 if total >= 50 else 9 if total >= 20 else 4 if total >= 5 else 0
        checks.append(Check(
            "Reviews", "Review volume", v_pts, 20,
            f"{total} Google reviews",
            fix=("" if total >= 50 else
                 "Build a review-request flow: ask at the moment of success (delivery, job done, renewal) "
                 "with a direct link to your Google review form. Volume and recency are strong selection "
                 "signals — aim for a steady trickle, not a burst."),
            priority="" if total >= 50 else ("High" if total < 20 else "Medium"),
        ))
    elif local_like and os.environ.get("GOOGLE_PLACES_API_KEY"):
        # Only shown when the lookup actually ran and found nothing. Without a
        # key there is no finding to report — a customer should never be shown
        # our own configuration notes.
        checks.append(Check(
            "Reviews", "Live Google rating & volume", 0, 0,
            "Google Places lookup found no match for this business",
        ))

    # ================= SOCIAL (the footprint AI engines connect) =========
    sameas_platforms = {detect_platform(u) for u in jsonld_sameas} - {None}
    all_platforms = set(p.social) | sameas_platforms
    plat_pts = clamp(len(all_platforms) / 4 * 25, 0, 25)
    checks.append(Check(
        "Social", "Profiles linked from the site", round(plat_pts, 1), 25,
        (f"{len(all_platforms)} platform(s) connected: {', '.join(sorted(all_platforms))}"
         if all_platforms else "No social profiles linked anywhere on the page"),
        fix=("Link your active social profiles from the site (footer is fine). Unlinked profiles are "
             "invisible to engines trying to verify this is a real, active business.") if len(all_platforms) < 2 else "",
        priority="High" if not all_platforms else ("Medium" if len(all_platforms) < 2 else ""),
    ))
    has_sameas = bool(sameas_platforms or any(is_gbp_link(u) for u in jsonld_sameas))
    checks.append(Check(
        "Social", "sameAs entity links in schema", 25 if has_sameas else 0, 25,
        ("Schema sameAs connects this site to its profiles" if has_sameas
         else "No sameAs links in structured data"),
        fix="" if has_sameas else ("Add a sameAs array to your Organization JSON-LD listing every official "
                                   "profile (Google Business Profile, LinkedIn, Instagram, Facebook, YouTube…). "
                                   "This is the strongest signal that all those profiles are the same entity — "
                                   "it's how AI engines assemble your brand's identity."),
        priority="" if has_sameas else "High",
    ))
    wanted = VERTICAL_HIGH_CITATION.get(res.vertical, HIGH_CITATION)
    hc = all_platforms & wanted
    hc_pts = clamp(len(hc) / 3 * 25, 0, 25)
    missing = sorted(wanted - all_platforms)
    checks.append(Check(
        "Social", "High-citation platforms", round(hc_pts, 1), 25,
        (f"Present on {', '.join(sorted(hc))} — the platforms AI answers cite most for "
         f"{VERTICAL_LABELS[res.vertical].lower()}" if hc
         else f"Not present on {', '.join(sorted(wanted))}"),
        fix=(f"For {VERTICAL_LABELS[res.vertical].lower()}, the platforms AI engines cite most are "
             f"{', '.join(sorted(wanted))}. You're missing {', '.join(missing)}. "
             "Reddit in particular rewards genuine participation in your category's subreddits — "
             "never astroturf.") if len(hc) < 2 else "",
        priority="Medium" if len(hc) < 2 else "",
    ))
    og = [bool(p.meta.get("og:title")), bool(p.meta.get("og:description")), bool(p.meta.get("og:image"))]
    og_pts = round(25 * sum(og) / 3, 1)
    checks.append(Check(
        "Social", "Share metadata (Open Graph)", og_pts, 25,
        f"{sum(og)} of 3 Open Graph tags present (title / description / image)",
        fix=("Add og:title, og:description and og:image. Every share of your pages — including inside "
             "AI chat citations — renders from these tags; without them your links show up bare.") if sum(og) < 3 else "",
        priority="Medium" if sum(og) < 3 else "",
    ))

    # ---------------- totals ----------------
    geo = [c for c in checks if c.pillar.startswith("GEO")]
    aeo = [c for c in checks if c.pillar.startswith("AEO")]
    rev = [c for c in checks if c.pillar == "Reviews" and c.possible > 0]
    soc = [c for c in checks if c.pillar == "Social" and c.possible > 0]
    res.geo_score = round(100 * sum(c.earned for c in geo) / sum(c.possible for c in geo))
    res.aeo_score = round(100 * sum(c.earned for c in aeo) / sum(c.possible for c in aeo))
    res.reviews_score = round(100 * sum(c.earned for c in rev) / sum(c.possible for c in rev))
    res.social_score = round(100 * sum(c.earned for c in soc) / sum(c.possible for c in soc))
    res.summary = build_summary(res, checks)
    return res


def build_summary(res: Result, checks: list[Check]) -> str:
    overall = overall_score(res)
    if overall >= 80:
        opening = "This page is in strong shape for AI visibility."
    elif overall >= 60:
        opening = "This page has a solid foundation for AI visibility, with clear room to improve."
    elif overall >= 40:
        opening = "This page is partially visible to AI engines, but several fundamentals are missing."
    else:
        opening = "As it stands, AI engines will struggle to find, read, or quote this page."
    highs = [c for c in checks if c.priority == "High"]
    scored = [c for c in checks if c.possible > 0]
    strongest = max(scored, key=lambda c: (c.earned / c.possible, c.possible))
    spa_note = (" Important: the page appears to render its content with JavaScript, so crawlers "
                "that don't run JS may see far less than a human visitor does.") if res.spa_warning else ""
    if highs:
        focus = highs[0].label.lower()
        closing = (f" The single biggest win right now is fixing “{highs[0].label}” — see the "
                   f"recommendations below, ordered by impact.")
    else:
        closing = " No critical gaps were found; the recommendations below are refinements."
    return (f"{opening} Scored as {VERTICAL_LABELS[res.vertical].lower()} "
            f"({weighting_sentence(res)}). "
            f"GEO scored {res.geo_score}/100 (can AI systems access, read and trust the page), "
            f"AEO scored {res.aeo_score}/100 (is the content shaped like answers), reviews scored "
            f"{res.reviews_score}/100 (the proof signals engines weigh) and social scored "
            f"{res.social_score}/100 (the footprint engines connect to the brand). "
            f"Its strongest signal is “{strongest.label.lower()}.”{spa_note}{closing}")


# ---------------------------------------------------------------------------
# 6. BENCHMARKS — best-practice targets + comparison with other scanned sites
# ---------------------------------------------------------------------------

# What well-optimized pages typically achieve per pillar (targets, not magic):
BEST_PRACTICE = {
    "GEO · Access": 100, "GEO · Content": 80, "GEO · Trust": 85, "GEO · Identity": 90,
    "AEO · Structure": 85, "AEO · Questions": 75, "AEO · Labels": 80, "AEO · Answer shape": 75,
    "Reviews": 80, "Social": 75,
}
BEST_PRACTICE_OVERALL = 85

HISTORY_FILE = "scan_history.json"


def pillar_percents(res: "Result") -> dict[str, int]:
    pillars: dict[str, list[Check]] = {}
    for c in res.checks:
        pillars.setdefault(c.pillar, []).append(c)
    return {name: round(100 * sum(c.earned for c in cs) / sum(c.possible for c in cs))
            for name, cs in pillars.items()}


def _history_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), HISTORY_FILE)


def load_history() -> list[dict]:
    try:
        with open(_history_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def append_history(res: "Result") -> None:
    hist = load_history()
    hist.append({
        "host": urllib.parse.urlparse(res.final_url).netloc.lower(),
        "url": res.final_url,
        "ts": _dt.datetime.now().isoformat(timespec="seconds"),
        "geo": res.geo_score,
        "aeo": res.aeo_score,
        "overall": overall_score(res),
        "vertical": res.vertical,
        "pillars": pillar_percents(res),
    })
    try:
        with open(_history_path(), "w", encoding="utf-8") as f:
            json.dump(hist[-500:], f, indent=1)  # keep the last 500 scans
    except OSError:
        pass


def peer_stats(res: "Result") -> dict | None:
    """
    Compare against the most recent scan of every OTHER site scanned so far.

    Where we have at least three peers in the same vertical we compare only
    against those — ranking a dentist against a SaaS company tells you nothing.
    Otherwise we fall back to the whole pool and say so.
    """
    me = urllib.parse.urlparse(res.final_url).netloc.lower()
    latest_by_host: dict[str, dict] = {}
    for entry in load_history():           # chronological; later entries overwrite
        if entry.get("host") and entry["host"] != me:
            latest_by_host[entry["host"]] = entry
    peers = list(latest_by_host.values())
    if not peers:
        return None

    same = [p for p in peers if p.get("vertical") == res.vertical]
    like_for_like = len(same) >= 3
    if like_for_like:
        peers = same

    overall = overall_score(res)
    peer_overalls = [p["overall"] for p in peers]
    pillar_avgs: dict[str, float] = {}
    for name in pillar_percents(res):
        vals = [p["pillars"][name] for p in peers if name in p.get("pillars", {})]
        if vals:
            pillar_avgs[name] = sum(vals) / len(vals)
    rank = 1 + sum(1 for v in peer_overalls if v > overall)
    return {
        "n": len(peers),
        "avg": sum(peer_overalls) / len(peer_overalls),
        "best": max(peer_overalls),
        "rank": rank,
        "of": len(peers) + 1,
        "pillar_avgs": pillar_avgs,
        "like_for_like": like_for_like,
        "cohort": (VERTICAL_LABELS[res.vertical].lower() if like_for_like
                   else "all sites scanned"),
    }


# ---------------------------------------------------------------------------
# 7. REPORT — a designed, self-contained HTML page
# ---------------------------------------------------------------------------

def ring_svg(score: int, label: str, color: str) -> str:
    r, circ = 64, 2 * 3.14159 * 64
    dash = circ * score / 100
    return f"""
    <div class="ring">
      <svg viewBox="0 0 160 160" width="160" height="160" role="img" aria-label="{label} score {score} out of 100">
        <circle cx="80" cy="80" r="{r}" fill="none" stroke="#e7e6f4" stroke-width="13"/>
        <circle cx="80" cy="80" r="{r}" fill="none" stroke="{color}" stroke-width="13"
                stroke-linecap="round" stroke-dasharray="{dash:.1f} {circ:.1f}"
                transform="rotate(-90 80 80)"/>
        <text x="80" y="76" text-anchor="middle" class="ring-num">{score}</text>
        <text x="80" y="100" text-anchor="middle" class="ring-sub">/ 100</text>
      </svg>
      <div class="ring-label">{label}</div>
    </div>"""


def grade(score: int) -> tuple[str, str]:
    if score >= 85: return "A", "#0e9f6e"
    if score >= 70: return "B", "#0ea5b7"
    if score >= 55: return "C", "#d97706"
    if score >= 40: return "D", "#ea580c"
    return "F", "#dc2626"


PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def render_report(res: Result) -> str:
    esc = _html.escape
    overall = overall_score(res)
    g_letter, g_color = grade(overall)

    # pillar bars — site bar + best-practice tick + peer-average tick
    peers = peer_stats(res)
    bars = ""
    for name, pct in pillar_percents(res).items():
        bp = BEST_PRACTICE.get(name, 85)
        ticks = f'<span class="tick bp" style="left:{bp}%" title="Best practice: {bp}%"></span>'
        if peers and name in peers["pillar_avgs"]:
            pa = peers["pillar_avgs"][name]
            ticks += f'<span class="tick peer" style="left:{pa:.0f}%" title="Peer average: {pa:.0f}%"></span>'
        bars += f"""
        <div class="bar-row">
          <div class="bar-name">{esc(name)}</div>
          <div class="bar-track">{ticks}<div class="bar-fill" style="width:{pct}%"></div></div>
          <div class="bar-pct">{pct}%</div>
        </div>"""
    legend = ('<div class="legend"><span><i class="sw fill"></i>This site</span>'
              '<span><i class="sw bpsw"></i>Best practice target</span>'
              + ('<span><i class="sw peersw"></i>Peer average</span>' if peers else "")
              + '</div>')

    # comparison section
    if peers:
        pct_better = round(100 * (peers["of"] - peers["rank"]) / max(peers["of"] - 1, 1))
        compare_html = f"""
        <div class="cmp-strip">
          <div class="cmp-stat"><b>#{peers['rank']}</b><span>of {peers['of']} {esc(peers['cohort'])}</span></div>
          <div class="cmp-stat"><b>{overall}</b><span>this site</span></div>
          <div class="cmp-stat"><b>{peers['avg']:.0f}</b><span>peer average</span></div>
          <div class="cmp-stat"><b>{peers['best']}</b><span>best peer</span></div>
          <div class="cmp-stat"><b>{BEST_PRACTICE_OVERALL}</b><span>best practice</span></div>
        </div>
        <p class="muted" style="font-size:14px">This site scores {"above" if overall > peers["avg"] else "below"}
        the average of the {peers['n']} other {esc(peers['cohort'])} checked with this tool
        ({"ahead of" if pct_better >= 50 else "behind"} {max(pct_better, 100 - pct_better)}% of them) and
        {"meets" if overall >= BEST_PRACTICE_OVERALL else f"sits {BEST_PRACTICE_OVERALL - overall} points under"}
        the best-practice target of {BEST_PRACTICE_OVERALL}. Pillar-level gaps are marked on the bars below.</p>"""
    else:
        compare_html = f"""
        <p class="muted" style="font-size:14px">Best-practice targets — what well-optimized pages typically
        achieve — are marked as dark ticks on each bar below (overall target: {BEST_PRACTICE_OVERALL}/100).
        Peer comparison appears here automatically once more sites have been scanned with this tool.</p>"""

    # checks table
    check_rows = ""
    for c in res.checks:
        pct = c.earned / c.possible if c.possible else 0
        dot = "#0e9f6e" if pct >= 0.85 else ("#d97706" if pct >= 0.4 else "#dc2626")
        check_rows += f"""
        <tr>
          <td><span class="dot" style="background:{dot}"></span>{esc(c.label)}</td>
          <td class="muted">{esc(c.detail)}</td>
          <td class="num">{f"{c.earned:g} / {c.possible:g}" if c.possible else "—"}</td>
        </tr>"""

    # crawler table
    crawler_rows = ""
    for bot, role, kind, status in res.crawler_rows:
        badge = {"allowed": ("Allowed", "#0e9f6e"), "blocked": ("Blocked", "#dc2626"),
                 "partial": ("Partial", "#d97706")}[status]
        crawler_rows += f"""
        <tr><td><code>{esc(bot)}</code></td><td class="muted">{esc(role)}</td>
        <td>{esc(kind)}</td><td><span class="pill" style="color:{badge[1]};border-color:{badge[1]}55">{badge[0]}</span></td></tr>"""

    # recommendations
    recs = sorted([c for c in res.checks if c.fix],
                  key=lambda c: (PRIORITY_ORDER.get(c.priority, 3), -(c.possible - c.earned)))
    rec_cards = ""
    for i, c in enumerate(recs, 1):
        pcolor = {"High": "#dc2626", "Medium": "#d97706", "Low": "#64748b"}.get(c.priority, "#64748b")
        rec_cards += f"""
        <div class="rec">
          <div class="rec-head">
            <span class="rec-n">{i:02d}</span>
            <span class="rec-title">{esc(c.label)}</span>
            <span class="pill" style="color:{pcolor};border-color:{pcolor}55">{esc(c.priority)} impact</span>
          </div>
          <p class="rec-why muted">Observed: {esc(c.detail)}</p>
          <p class="rec-fix">{esc(c.fix)}</p>
        </div>"""
    if not recs:
        rec_cards = "<p class='muted'>No fixes needed — every check passed. Re-run after content updates.</p>"

    spa_banner = ("""<div class="warn">⚠️ JavaScript-rendered page detected. The scores below reflect what a
    non-JS crawler sees — likely far less than human visitors see. Fixing server-side rendering should come
    before everything else.</div>""" if res.spa_warning else "")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Visibility Report — {esc(res.site_title)}</title>
<style>
  :root {{
    --ink:#191731; --muted:#5d5a78; --line:#e7e6f4; --bg:#f7f6fc; --card:#ffffff;
    --indigo:#372aac; --violet:#7c3aed; --cyan:#0891b2;
  }}
  * {{ box-sizing:border-box; margin:0; }}
  body {{ font:16px/1.6 "Avenir Next","Segoe UI",system-ui,sans-serif; background:var(--bg); color:var(--ink); }}
  .wrap {{ max-width:880px; margin:0 auto; padding:48px 24px 80px; }}
  header.report {{ background:linear-gradient(135deg,#1c1740 0%, #372aac 70%, #4f46e5 100%); color:#fff;
    border-radius:18px; padding:40px 40px 34px; }}
  .eyebrow {{ font-size:12px; letter-spacing:.18em; text-transform:uppercase; color:#b9c5ff; }}
  header.report h1 {{ font-size:30px; line-height:1.25; margin:10px 0 4px; font-weight:700; }}
  header.report .sub {{ color:#c9c6ec; font-size:14px; }}
  .vertical-tag {{ margin-top:16px; padding-top:14px; border-top:1px solid #ffffff26;
    font-size:13.5px; color:#c9c6ec; }}
  .vertical-tag b {{ color:#fff; }}
  .vt-why {{ color:#9d99c8; }}
  .grade {{ float:right; text-align:center; background:#ffffff14; border:1px solid #ffffff2e;
    border-radius:14px; padding:12px 20px; margin-left:16px; }}
  .grade b {{ display:block; font-size:40px; line-height:1; }}
  .scores {{ display:flex; gap:24px; justify-content:center; flex-wrap:wrap; margin:-46px 0 0; position:relative; }}
  .ring {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:22px 30px 16px;
    text-align:center; box-shadow:0 10px 30px #372aac14; }}
  .ring-num {{ font-size:40px; font-weight:700; fill:var(--ink); }}
  .ring-sub {{ font-size:13px; fill:var(--muted); }}
  .ring-label {{ margin-top:8px; font-weight:600; letter-spacing:.04em; }}
  section {{ background:var(--card); border:1px solid var(--line); border-radius:16px; padding:30px 34px; margin-top:26px; }}
  h2 {{ font-size:14px; letter-spacing:.16em; text-transform:uppercase; color:var(--indigo); margin-bottom:16px; }}
  .muted {{ color:var(--muted); }}
  .summary p {{ font-size:17px; }}
  .warn {{ background:#fff7ed; border:1px solid #fdba74; color:#9a3412; border-radius:12px;
    padding:14px 18px; margin-top:26px; font-size:15px; }}
  .bar-row {{ display:grid; grid-template-columns:170px 1fr 52px; gap:14px; align-items:center; margin:10px 0; }}
  .bar-name {{ font-size:14px; font-weight:600; }}
  .bar-track {{ height:10px; background:var(--line); border-radius:99px; overflow:visible; position:relative; }}
  .bar-fill {{ height:100%; border-radius:99px; background:linear-gradient(90deg,var(--violet),var(--cyan)); }}
  .tick {{ position:absolute; top:-4px; width:3px; height:18px; border-radius:2px; z-index:2; }}
  .tick.bp {{ background:var(--ink); }}
  .tick.peer {{ background:#d97706; }}
  .legend {{ display:flex; gap:20px; flex-wrap:wrap; margin:14px 0 2px; font-size:12.5px; color:var(--muted); }}
  .legend .sw {{ display:inline-block; width:14px; height:10px; border-radius:3px; margin-right:6px; vertical-align:-1px; }}
  .legend .fill {{ background:linear-gradient(90deg,var(--violet),var(--cyan)); }}
  .legend .bpsw {{ background:var(--ink); width:3px; height:14px; vertical-align:-3px; }}
  .legend .peersw {{ background:#d97706; width:3px; height:14px; vertical-align:-3px; }}
  .cmp-strip {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:14px; }}
  .cmp-stat {{ flex:1; min-width:110px; background:#fbfaff; border:1px solid var(--line); border-radius:12px;
    padding:12px 8px; text-align:center; }}
  .cmp-stat b {{ display:block; font-size:24px; color:var(--indigo); }}
  .cmp-stat span {{ font-size:11.5px; color:var(--muted); }}
  .bar-pct {{ font-size:14px; text-align:right; color:var(--muted); }}
  table {{ width:100%; border-collapse:collapse; font-size:14.5px; }}
  td {{ padding:10px 10px 10px 0; border-top:1px solid var(--line); vertical-align:top; }}
  tr:first-child td {{ border-top:none; }}
  td.num {{ white-space:nowrap; text-align:right; color:var(--muted); }}
  .dot {{ display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:9px; }}
  code {{ background:#f1f0fa; padding:2px 7px; border-radius:6px; font-size:13px; }}
  .pill {{ display:inline-block; font-size:12px; font-weight:600; border:1px solid; border-radius:99px; padding:2px 10px; }}
  .rec {{ border:1px solid var(--line); border-radius:14px; padding:18px 22px; margin-top:14px; background:#fbfaff; }}
  .rec-head {{ display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
  .rec-n {{ font-weight:700; color:var(--violet); font-size:15px; }}
  .rec-title {{ font-weight:700; flex:1; }}
  .rec-why {{ font-size:13.5px; margin-top:8px; }}
  .rec-fix {{ margin-top:8px; font-size:15px; }}
  footer {{ margin-top:36px; text-align:center; color:var(--muted); font-size:13px; }}
  @media (max-width:640px) {{ header.report {{ padding:28px 22px; }} .grade {{ float:none; margin:0 0 14px; display:inline-block; }}
    .bar-row {{ grid-template-columns:1fr; gap:4px; }} .bar-pct {{ text-align:left; }} }}
</style></head><body><div class="wrap">

<header class="report">
  <div class="grade"><b style="color:#fff">{g_letter}</b><span style="font-size:12px;color:#c9c6ec">overall {overall}/100</span></div>
  <div class="eyebrow">AI Visibility Report</div>
  <h1>{esc(res.site_title)}</h1>
  <div class="sub">{esc(res.final_url)} · checked {esc(res.fetched_at)} · {res.word_count:,} words seen by crawlers</div>
  <div class="vertical-tag">Scored as <b>{esc(VERTICAL_LABELS[res.vertical])}</b>
  — {esc(weighting_sentence(res))}
  <span class="vt-why">({esc("chosen by you" if res.vertical_forced else "detected from " + res.vertical_evidence)})</span></div>
</header>

<div class="scores" style="margin-top:26px">
  {ring_svg(res.geo_score, "GEO — found & trusted", "#7c3aed")}
  {ring_svg(res.aeo_score, "AEO — shaped as answers", "#0891b2")}
  {ring_svg(res.reviews_score, "Reviews — proof", "#d97706")}
  {ring_svg(res.social_score, "Social — footprint", "#372aac")}
</div>

{spa_banner}

<section class="summary">
  <h2>Summary</h2>
  <p>{esc(res.summary)}</p>
</section>

<section>
  <h2>How this site compares</h2>
  {compare_html}
</section>

<section>
  <h2>Score breakdown</h2>
  {legend}
  {bars}
  <div style="height:14px"></div>
  <table>{check_rows}</table>
</section>

<section>
  <h2>AI crawler access (robots.txt)</h2>
  <p class="muted" style="margin-bottom:12px;font-size:14px">Citation crawlers fetch pages to build AI answers
  — they drive mentions and traffic. Training crawlers only collect data for model training.</p>
  <table>{crawler_rows}</table>
</section>

<section>
  <h2>Recommendations — start at the top</h2>
  {rec_cards}
</section>

<footer>Generated by AI Visibility Studio · raw-HTML view (no JavaScript executed), the same way most AI crawlers read the web<br>
Overall grade for {esc(VERTICAL_LABELS[res.vertical].lower())} = {esc(weighting_sentence(res))}</footer>
</div></body></html>"""


# ---------------------------------------------------------------------------
# 7. THE LOCAL WEB APP — paste a URL, get the report
# ---------------------------------------------------------------------------

HOME_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Visibility Studio</title>
<style>
  * { box-sizing:border-box; margin:0; }
  body { min-height:100vh; display:flex; align-items:center; justify-content:center;
    font:16px/1.6 "Avenir Next","Segoe UI",system-ui,sans-serif; color:#eceaff;
    background:radial-gradient(1100px 700px at 70% -10%, #4f46e5 0%, transparent 55%),
               radial-gradient(900px 600px at 0% 100%, #0e7490 0%, transparent 50%),
               #14112e; }
  .card { width:min(640px, 92vw); padding:8px 16px 32px; text-align:center; }
  .mark { font-size:13px; letter-spacing:.22em; text-transform:uppercase; color:#9aa7ff; }
  h1 { font-size:clamp(30px, 5vw, 44px); line-height:1.15; margin:14px 0 10px; font-weight:700; }
  h1 em { font-style:normal; background:linear-gradient(90deg,#a78bfa,#67e8f9); -webkit-background-clip:text;
    background-clip:text; color:transparent; }
  p.lede { color:#b6b2d8; max-width:46ch; margin:0 auto 30px; }
  form { display:flex; gap:10px; background:#ffffff12; border:1px solid #ffffff26; border-radius:16px;
    padding:10px; backdrop-filter:blur(6px); }
  input { flex:1; min-width:0; background:transparent; border:none; outline:none; color:#fff;
    font-size:17px; padding:10px 12px; }
  input::placeholder { color:#8d89b3; }
  button { border:none; border-radius:11px; padding:12px 22px; font-size:16px; font-weight:700; cursor:pointer;
    color:#14112e; background:linear-gradient(90deg,#a78bfa,#67e8f9); }
  button:hover { filter:brightness(1.07); }
  .hint { margin-top:16px; font-size:13.5px; color:#8d89b3; }
  .hint code { background:#ffffff14; padding:2px 8px; border-radius:6px; }
  #busy { display:none; margin-top:22px; color:#c4bfff; }
  .spin { display:inline-block; width:14px; height:14px; border:2px solid #a78bfa; border-top-color:transparent;
    border-radius:50%; animation:r 0.8s linear infinite; vertical-align:-2px; margin-right:8px; }
  @keyframes r { to { transform:rotate(360deg); } }
</style></head><body>
<div class="card">
  <div class="mark">AI Visibility Studio</div>
  <h1>Will AI assistants <em>find and quote</em> this page?</h1>
  <p class="lede">Paste a URL. Get a GEO score (can AI access &amp; trust it), an AEO score
  (is it shaped like answers), and a prioritized fix list.</p>
  <form action="/check" method="get" onsubmit="document.getElementById('busy').style.display='block'">
    <input name="url" placeholder="https://yourwebsite.com/page" autofocus required>
    <button>Run check</button>
  </form>
  <div id="busy"><span class="spin"></span>Fetching the page like an AI crawler… usually 5–15 seconds.</div>
  <div class="hint">Reports are also saved to the <code>reports/</code> folder next to the script.</div>
</div>
</body></html>"""


def save_report(res: Result) -> str:
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
    os.makedirs(out_dir, exist_ok=True)
    host = urllib.parse.urlparse(res.final_url).netloc.replace(":", "_") or "report"
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:22]
    path = os.path.join(out_dir, f"{host}-{stamp}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_report(res))
    append_history(res)  # remember this scan so future reports can compare against it
    return path


class App(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet the console
        pass

    def _send(self, body: str, status: int = 200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self._send(HOME_HTML)
        elif parsed.path == "/check":
            qs = urllib.parse.parse_qs(parsed.query)
            url = (qs.get("url") or [""])[0].strip()
            if not url:
                self._send(HOME_HTML)
                return
            outcome = analyze(url)
            if isinstance(outcome, str):
                self._send(f"""<body style="font-family:system-ui;max-width:560px;margin:80px auto;line-height:1.6">
                  <h2>Couldn't check that page</h2><p>{_html.escape(outcome)}</p>
                  <p><a href="/">&larr; Try another URL</a></p></body>""", 200)
                return
            path = save_report(outcome)
            print(f"  ✓ {outcome.final_url}  GEO {outcome.geo_score}  AEO {outcome.aeo_score}  "
                  f"REV {outcome.reviews_score}  SOC {outcome.social_score}  →  {path}")
            self._send(render_report(outcome))
        else:
            self._send("<p>Not found. <a href='/'>Home</a></p>", 404)


def main() -> None:
    # CLI: python3 ai_visibility_studio.py https://example.com [--vertical=saas]
    args = list(sys.argv[1:])
    forced = None
    for a in list(args):
        if a.startswith("--vertical="):
            forced = a.split("=", 1)[1].strip().lower()
            args.remove(a)
            if forced not in VERTICAL_WEIGHTS:
                print(f"Unknown vertical “{forced}”. Choose one of: {', '.join(VERTICAL_WEIGHTS)}")
                sys.exit(1)
    if args:
        outcome = analyze(args[0], vertical=forced)
        if isinstance(outcome, str):
            print("✗", outcome)
            sys.exit(1)
        path = save_report(outcome)
        print(f"Scored as {VERTICAL_LABELS[outcome.vertical]} ({weighting_sentence(outcome)})")
        print(f"GEO {outcome.geo_score}  AEO {outcome.aeo_score}  Reviews {outcome.reviews_score}  "
              f"Social {outcome.social_score}  ->  overall {overall_score(outcome)}/100")
        print(f"Report saved: {path}")
        return

    port = 8765
    while True:
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), App)
            break
        except OSError:
            port += 1
    addr = f"http://localhost:{port}"
    print("\nAI Visibility Studio is running.")
    print(f"  Open:  {addr}")
    print("  Stop:  press Ctrl+C in this window\n")
    try:
        webbrowser.open(addr)
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. Bye!")


if __name__ == "__main__":
    main()
