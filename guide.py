"""
Developer guidance for each finding in a Surfaced report.

One entry per check label. Each entry explains why the check matters, gives
numbered steps a developer can follow, a paste-ready snippet where one helps,
and a way to verify the fix. Snippets use three tokens that the report fills
in from the scanned site:

    [[NAME]]    the site's title
    [[URL]]     the scanned address
    [[DOMAIN]]  the bare domain

Anything in CAPITALS inside a snippet is a placeholder the developer must
replace with real information. Nothing here promises a ranking or a citation:
these steps remove obstacles; they do not guarantee an outcome.
"""

from __future__ import annotations

GUIDE: dict[str, dict] = {

    "AI citation crawlers allowed": {
        "who": "Developer", "effort": "10 minutes",
        "why": "Assistants such as ChatGPT, Claude and Perplexity fetch pages with their own "
               "crawlers. A crawler that robots.txt turns away cannot read the page, so the "
               "assistant has nothing of yours to quote.",
        "steps": [
            "Open the robots.txt file at the root of the site (often managed by an SEO plugin "
            "or the hosting platform's settings).",
            "Remove any Disallow: / rule that applies to the crawlers named in the crawler table "
            "of this report, or to User-agent: *.",
            "Add the block below so the citation crawlers are allowed by name.",
            "Check the CDN or firewall (Cloudflare, Sucuri, Wordfence) for a separate "
            "\"block AI bots\" setting and turn it off for these crawlers.",
        ],
        "code_title": "robots.txt",
        "code": "User-agent: OAI-SearchBot\nAllow: /\n\nUser-agent: ChatGPT-User\nAllow: /\n\n"
                "User-agent: ClaudeBot\nAllow: /\n\nUser-agent: Claude-SearchBot\nAllow: /\n\n"
                "User-agent: PerplexityBot\nAllow: /\n\nUser-agent: Google-Extended\nAllow: /\n\n"
                "Sitemap: https://[[DOMAIN]]/sitemap.xml",
        "verify": "Open https://[[DOMAIN]]/robots.txt in a browser and confirm the new rules are "
                  "there, then run this scan again: the crawler table should read Allowed.",
    },

    "Firewall turns away automated readers": {
        "who": "Developer or hosting provider", "effort": "15–30 minutes",
        "why": "The site answered an ordinary browser but refused our crawler-style request. "
               "AI crawlers identify themselves honestly, so they meet the same refusal.",
        "steps": [
            "Find what is blocking: usually a CDN bot-protection feature (Cloudflare Bot Fight "
            "Mode, \"Block AI Scrapers and Crawlers\"), a security plugin, or a host-level rule.",
            "Add an allow rule for verified AI search crawlers. In Cloudflare: Security → Bots → "
            "turn off \"Block AI bots\", or add a WAF skip rule for the user agents below.",
            "Keep protection on for everything else; only these named crawlers need to pass.",
        ],
        "code_title": "User agents to allow",
        "code": "OAI-SearchBot\nChatGPT-User\nClaudeBot\nClaude-SearchBot\nPerplexityBot",
        "verify": "From a terminal run:  curl -I -A \"ClaudeBot\" [[URL]]  — the first line "
                  "should be HTTP 200, not 403 or 503.",
    },

    "Served over HTTPS": {
        "who": "Developer or hosting provider", "effort": "15 minutes",
        "why": "Engines treat an unencrypted page as less trustworthy, and some crawlers will "
               "not follow a link to plain http at all.",
        "steps": [
            "Turn on the free TLS certificate in the hosting control panel (most hosts offer "
            "Let's Encrypt in one click).",
            "Redirect every http:// request to https:// with a permanent (301) redirect.",
            "Update internal links, the canonical tag and the sitemap to use https://.",
        ],
        "verify": "Visit http://[[DOMAIN]] — it should land on https://[[DOMAIN]] with a padlock.",
    },

    "Readable text without JavaScript": {
        "who": "Developer and content owner", "effort": "Half a day to several days",
        "why": "Most AI crawlers do not run JavaScript. They read the HTML the server sends. "
               "Text that only appears after scripts run, or that is not there at all, cannot "
               "be quoted.",
        "steps": [
            "View the page source (right-click → View Page Source) and search for a sentence "
            "you can see on screen. If it is missing, the content is added by JavaScript.",
            "If it is missing: enable server-side rendering or static generation in the "
            "framework (Next.js, Nuxt, Astro, SvelteKit), or use a pre-rendering service.",
            "If the page is simply short: add at least 300 words covering what you offer, who "
            "it is for, where you operate and how to get in touch, written as full sentences.",
        ],
        "verify": "Run:  curl -s [[URL]] | grep -c \"A PHRASE FROM YOUR PAGE\"  — the count "
                  "should be 1 or more.",
    },

    "Text-to-code ratio": {
        "who": "Developer", "effort": "1–3 hours",
        "why": "When a page is mostly scripts, styles and markup, the readable text is a small "
               "share of what a crawler downloads, and crawlers with size limits may stop early.",
        "steps": [
            "Move inline <script> and <style> blocks into external files.",
            "Remove unused plugins, trackers and page-builder leftovers.",
            "Put the main content high in the HTML, before large script bundles.",
        ],
        "verify": "Run this scan again and compare the ratio shown under Observed.",
    },

    "Schema.org structured data": {
        "who": "Developer", "effort": "30 minutes",
        "why": "Structured data states in a machine-readable way who you are, what you offer "
               "and where. It removes guesswork for an engine deciding whether to trust and "
               "name you.",
        "steps": [
            "Choose the type that fits: LocalBusiness (or a subtype such as Dentist, "
            "Restaurant), Organization, SoftwareApplication, or Product.",
            "Paste the block below into the <head> of the home page and replace every "
            "CAPITALISED placeholder with real details.",
            "Use only facts that also appear on the visible page.",
        ],
        "code_title": "HTML <head> — JSON-LD",
        "code": '<script type="application/ld+json">\n{\n  "@context": "https://schema.org",\n'
                '  "@type": "Organization",\n  "name": "[[NAME]]",\n  "url": "https://[[DOMAIN]]/",\n'
                '  "logo": "https://[[DOMAIN]]/LOGO.png",\n  "description": "ONE SENTENCE ON WHAT YOU DO AND FOR WHOM",\n'
                '  "telephone": "+1-000-000-0000",\n  "address": {\n    "@type": "PostalAddress",\n'
                '    "streetAddress": "STREET",\n    "addressLocality": "CITY",\n    "addressRegion": "STATE",\n'
                '    "postalCode": "ZIP",\n    "addressCountry": "US"\n  },\n'
                '  "sameAs": [\n    "https://www.linkedin.com/company/YOUR-PAGE",\n'
                '    "https://www.facebook.com/YOUR-PAGE"\n  ]\n}\n</script>',
        "verify": "Paste the page address into Google's Rich Results Test "
                  "(search.google.com/test/rich-results) or validator.schema.org — no errors.",
    },

    "Clear page title": {
        "who": "Developer or content owner", "effort": "5 minutes",
        "why": "The title is the first label an engine reads and the text it most often shows "
               "when it names a source.",
        "steps": [
            "Write a title of 30–60 characters: the business or page name first, then what "
            "it is, then the place if you serve a local area.",
            "Make it unique on every page.",
        ],
        "code_title": "HTML <head>",
        "code": "<title>[[NAME]] — WHAT YOU DO, WHERE</title>",
        "verify": "The browser tab shows the new title; this scan shows it in the report header.",
    },

    "Meta description": {
        "who": "Developer or content owner", "effort": "5 minutes",
        "why": "The description is a ready-made summary. Engines use it when they need one "
               "sentence about the page.",
        "steps": [
            "Write 120–160 characters that say what the page offers and for whom.",
            "State a fact, not a slogan: service, audience, place.",
        ],
        "code_title": "HTML <head>",
        "code": '<meta name="description" content="WHAT YOU OFFER, WHO IT IS FOR, AND WHERE — 120 TO 160 CHARACTERS.">',
        "verify": "View Page Source and search for name=\"description\".",
    },

    "Canonical URL": {
        "who": "Developer", "effort": "5 minutes",
        "why": "The same page is often reachable at several addresses (with and without www, "
               "with tracking parameters). A canonical tag tells engines which one counts, so "
               "trust is not split between copies.",
        "steps": [
            "Add the tag below to the <head> of every page, pointing at that page's own "
            "preferred address.",
            "Use the https:// version and be consistent about www.",
        ],
        "code_title": "HTML <head>",
        "code": '<link rel="canonical" href="[[URL]]">',
        "verify": "View Page Source and search for rel=\"canonical\".",
    },

    "Share metadata (Open Graph)": {
        "who": "Developer", "effort": "10 minutes",
        "why": "Open Graph tags give a clean title, summary and image to anything that "
               "previews or cites the page, including chat assistants that show link cards.",
        "steps": [
            "Add the four tags below to the <head>.",
            "Use an image of at least 1200 × 630 pixels.",
        ],
        "code_title": "HTML <head>",
        "code": '<meta property="og:title" content="[[NAME]]">\n'
                '<meta property="og:description" content="ONE OR TWO SENTENCES ABOUT THIS PAGE">\n'
                '<meta property="og:url" content="[[URL]]">\n'
                '<meta property="og:image" content="https://[[DOMAIN]]/SHARE-IMAGE.png">\n'
                '<meta property="og:type" content="website">',
        "verify": "Paste the address into opengraph.xyz or the LinkedIn Post Inspector and "
                  "check the preview.",
    },

    "Named author / byline": {
        "who": "Content owner", "effort": "15 minutes",
        "why": "Engines weigh who is speaking. A named person or organisation with stated "
               "credentials is easier to trust than anonymous text.",
        "steps": [
            "Add a visible byline or \"About the author / About us\" line with a real name "
            "and role.",
            "Link the name to a profile page (an About page or LinkedIn).",
            "Add the author tag below, or an author property in your structured data.",
        ],
        "code_title": "HTML <head>",
        "code": '<meta name="author" content="FULL NAME OR ORGANISATION">',
        "verify": "The name is visible on the page and appears in View Page Source.",
    },

    "Published / updated dates": {
        "who": "Developer or content owner", "effort": "15 minutes",
        "why": "Assistants prefer sources they can tell are current. A page with no date looks "
               "the same as one abandoned years ago.",
        "steps": [
            "Show a \"Last updated\" date on the page.",
            "Mark it up with a <time> element so machines can read it.",
            "Change the date only when the content really changes.",
        ],
        "code_title": "HTML",
        "code": '<p>Last updated <time datetime="2026-11-16">November 16, 2026</time></p>',
        "verify": "The date is visible and View Page Source shows a datetime attribute.",
    },

    "Outbound references": {
        "who": "Content owner", "effort": "20 minutes",
        "why": "Linking to recognised sources (a licensing body, a standard, a study) shows "
               "the claims on the page can be checked.",
        "steps": [
            "Find two or three factual claims on the page.",
            "Link each to an authoritative source: a professional association, government "
            "page or original research.",
        ],
        "verify": "Run this scan again; the count of outbound references should rise.",
    },

    "Single clear H1": {
        "who": "Developer", "effort": "10 minutes",
        "why": "The H1 tells an engine the single subject of the page. None, or several, "
               "leaves the subject unclear.",
        "steps": [
            "Make sure the page has exactly one <h1>.",
            "Have it say plainly what the page is about, in the words a customer would use.",
            "Change any extra <h1> elements (often a logo or slider text) to <h2> or <div>.",
        ],
        "code_title": "HTML",
        "code": "<h1>[[NAME]]: WHAT YOU DO, IN PLAIN WORDS</h1>",
        "verify": "In the browser console run:  document.querySelectorAll('h1').length  — "
                  "the answer should be 1.",
    },

    "Section subheadings (H2/H3)": {
        "who": "Content owner", "effort": "30 minutes",
        "why": "Subheadings split a page into labelled parts. Engines lift answers one "
               "section at a time, so unlabelled text is harder to quote.",
        "steps": [
            "Break the page into sections of 100–300 words.",
            "Give each a real <h2> (not bold text) that names the topic.",
            "Use <h3> for sub-points inside a section.",
        ],
        "verify": "Run this scan again; the heading count is shown under Observed.",
    },

    "Question-style headings": {
        "who": "Content owner", "effort": "30 minutes",
        "why": "People ask assistants questions. A heading that is itself the question, "
               "followed directly by the answer, is the easiest thing for an engine to match "
               "and quote.",
        "steps": [
            "List the five questions customers ask most (ask whoever answers the phone).",
            "Rewrite section headings as those questions.",
            "Answer in the first one or two sentences under each heading, then add detail.",
        ],
        "code_title": "HTML",
        "code": "<h2>How much does SERVICE cost?</h2>\n"
                "<p>SERVICE costs between $X and $Y, depending on Z. THE REST OF THE ANSWER.</p>",
        "verify": "Run this scan again; question headings are counted under Observed.",
    },

    "Quotable answer paragraphs": {
        "who": "Content owner", "effort": "1 hour",
        "why": "Assistants quote short, complete statements. A paragraph of 40–80 words that "
               "answers one question on its own can be lifted whole; a long wandering one "
               "cannot.",
        "steps": [
            "Under each heading, open with a direct answer of two to four sentences.",
            "Name the subject in the sentence (\"[[NAME]] offers…\") instead of \"we\" or "
            "\"it\", so the sentence still makes sense out of context.",
            "Include the specific fact: a price range, a time, a place, a number.",
        ],
        "verify": "Read each opening paragraph on its own. If it answers the heading without "
                  "the rest of the page, it is quotable.",
    },

    "FAQ section": {
        "who": "Developer and content owner", "effort": "1 hour",
        "why": "An FAQ pairs real questions with short answers, which is the exact shape "
               "assistants look for. Marking it up as FAQPage makes each pair unambiguous.",
        "steps": [
            "Write five to eight questions customers really ask, each with a two-to-four "
            "sentence answer.",
            "Put them on the page as visible text.",
            "Add the JSON-LD below, with the same wording as the visible text.",
        ],
        "code_title": "HTML — JSON-LD",
        "code": '<script type="application/ld+json">\n{\n  "@context": "https://schema.org",\n'
                '  "@type": "FAQPage",\n  "mainEntity": [\n    {\n      "@type": "Question",\n'
                '      "name": "YOUR FIRST QUESTION?",\n      "acceptedAnswer": {\n'
                '        "@type": "Answer",\n        "text": "THE ANSWER, IN TWO TO FOUR SENTENCES."\n'
                '      }\n    },\n    {\n      "@type": "Question",\n      "name": "YOUR SECOND QUESTION?",\n'
                '      "acceptedAnswer": {\n        "@type": "Answer",\n        "text": "THE ANSWER."\n'
                '      }\n    }\n  ]\n}\n</script>',
        "verify": "Test the page at validator.schema.org — it should list a FAQPage with "
                  "your questions.",
    },

    "Lists and tables": {
        "who": "Content owner", "effort": "30 minutes",
        "why": "Steps, options and comparisons are easier to extract from a real list or "
               "table than from a paragraph.",
        "steps": [
            "Turn any sequence of steps into a numbered list (<ol>).",
            "Turn services, features or options into a bulleted list (<ul>).",
            "Put prices, hours or comparisons into a <table> with header cells.",
        ],
        "code_title": "HTML",
        "code": "<table>\n  <tr><th>Service</th><th>Price</th><th>Time</th></tr>\n"
                "  <tr><td>SERVICE ONE</td><td>$X</td><td>N minutes</td></tr>\n</table>",
        "verify": "Run this scan again; lists and tables are counted under Observed.",
    },

    "Image alt text": {
        "who": "Developer or content owner", "effort": "20 minutes",
        "why": "Crawlers cannot see images. The alt attribute is the only description they "
               "get, and it also serves visitors using screen readers.",
        "steps": [
            "Give every meaningful image an alt attribute that says what it shows.",
            "Give purely decorative images an empty alt (alt=\"\").",
        ],
        "code_title": "HTML",
        "code": '<img src="team.jpg" alt="DESCRIBE WHAT THE IMAGE SHOWS IN ONE SHORT SENTENCE">',
        "verify": "In the browser console run:  "
                  "document.querySelectorAll('img:not([alt])').length  — the answer should be 0.",
    },

    "Review schema (AggregateRating)": {
        "who": "Developer", "effort": "30 minutes",
        "why": "Rating markup states your review score in a form engines can read. Only use "
               "it for genuine reviews collected on your own site: marking up invented or "
               "copied ratings breaks search-engine guidelines and can get rich results removed.",
        "steps": [
            "Confirm you show real customer reviews on the page.",
            "Add the block below inside your existing business or product structured data, "
            "with the true average and count.",
            "Update the numbers whenever the visible reviews change.",
        ],
        "code_title": "JSON-LD — add inside your business markup",
        "code": '"aggregateRating": {\n  "@type": "AggregateRating",\n'
                '  "ratingValue": "YOUR REAL AVERAGE, E.G. 4.8",\n'
                '  "reviewCount": "YOUR REAL NUMBER OF REVIEWS"\n}',
        "verify": "Google's Rich Results Test shows a rating with no errors.",
    },

    "Customer proof on the page": {
        "who": "Content owner", "effort": "1 hour",
        "why": "Testimonials and named customers are evidence that real people chose you. "
               "Engines look for that evidence in the page text.",
        "steps": [
            "Ask three recent customers for permission to quote them.",
            "Add each quote as text (not an image), with a name and, where it helps, a "
            "town or company.",
            "Place them near the service they describe.",
        ],
        "verify": "The quotes are selectable text on the page and appear in View Page Source.",
    },

    "Google Business Profile link": {
        "who": "Business owner", "effort": "10 minutes (longer if the profile is unclaimed)",
        "why": "A Google Business Profile is where local reviews, hours and location live. "
               "Linking it from the site connects the two for engines that use Google data.",
        "steps": [
            "Claim or open the profile at business.google.com.",
            "Copy the share link (Share → Copy link).",
            "Add it to the site footer or contact page.",
        ],
        "code_title": "HTML",
        "code": '<a href="https://maps.app.goo.gl/YOUR-SHARE-LINK">Find [[NAME]] on Google Maps</a>',
        "verify": "The link opens your profile, and this scan shows the check as passed.",
    },

    "Third-party review profiles": {
        "who": "Business owner", "effort": "30 minutes",
        "why": "Engines cross-check a business against independent review sites. Profiles "
               "you link to are easier for them to connect to you.",
        "steps": [
            "Claim your profile on the review sites that matter in your field (for example "
            "Yelp, Healthgrades, Trustpilot, G2, Houzz).",
            "Make the name, address and phone identical to those on your site.",
            "Link each profile from the site footer.",
        ],
        "verify": "Run this scan again; linked review profiles are listed under Observed.",
    },

    "Review volume": {
        "who": "Business owner", "effort": "Ongoing",
        "why": "A handful of reviews carries little weight. Steady, recent reviews are one of "
               "the strongest signals for local and service businesses.",
        "steps": [
            "Ask every satisfied customer for a review, at the moment the job is done.",
            "Send a direct link to the review form (your Google profile has a \"Ask for "
            "reviews\" link).",
            "Reply to every review, good or bad.",
            "Never buy reviews or offer rewards for them: it breaks platform rules.",
        ],
        "verify": "Track the review count monthly; this scan reports it when live data is "
                  "available.",
    },

    "Profiles linked from the site": {
        "who": "Developer", "effort": "10 minutes",
        "why": "Links from your site to your own social profiles confirm those profiles are "
               "yours, which helps engines treat them as one entity.",
        "steps": [
            "Add links to your active profiles in the site footer.",
            "List the same addresses in the sameAs property of your structured data.",
            "Leave out profiles you no longer update.",
        ],
        "code_title": "HTML",
        "code": '<a href="https://www.linkedin.com/company/YOUR-PAGE" rel="me">LinkedIn</a>\n'
                '<a href="https://www.facebook.com/YOUR-PAGE" rel="me">Facebook</a>',
        "verify": "Run this scan again; linked profiles are listed under Observed.",
    },

    "sameAs entity links in schema": {
        "who": "Developer", "effort": "10 minutes",
        "why": "The sameAs property lists your official profiles inside your structured data. "
               "It tells an engine that the site and those profiles are the same organisation.",
        "steps": [
            "Open the Organization or LocalBusiness JSON-LD block on the home page.",
            "Add a sameAs array with the full address of each active profile.",
            "List only profiles you control.",
        ],
        "code_title": "JSON-LD — add inside your business markup",
        "code": '"sameAs": [\n  "https://www.linkedin.com/company/YOUR-PAGE",\n'
                '  "https://www.facebook.com/YOUR-PAGE",\n  "https://www.youtube.com/@YOUR-CHANNEL"\n]',
        "verify": "validator.schema.org shows the sameAs addresses under your organisation.",
    },

    "High-citation platforms": {
        "who": "Business owner or marketer", "effort": "Ongoing",
        "why": "Assistants draw heavily on a small set of platforms such as YouTube, LinkedIn, "
               "Reddit and Wikipedia. A presence there gives them more places to learn about "
               "you.",
        "steps": [
            "Pick the one or two platforms your customers already use.",
            "Post useful, specific material there: a short how-to video, an answer to a "
            "common question.",
            "Link those profiles from your site.",
            "Take part honestly: no fake accounts or undisclosed promotion.",
        ],
        "verify": "Run this scan again; platforms linked from the site are listed under "
                  "Observed.",
    },
}

# Checks that share guidance with another label.
ALIASES = {
    "Live Google rating": "Review volume",
    "Live Google rating & volume": "Review volume",
    "Reviews": "Review volume",
}


def guidance_for(label: str) -> dict | None:
    return GUIDE.get(label) or GUIDE.get(ALIASES.get(label, ""))


def fill(text: str, name: str, url: str, domain: str) -> str:
    return (text.replace("[[NAME]]", name).replace("[[URL]]", url)
            .replace("[[DOMAIN]]", domain))
