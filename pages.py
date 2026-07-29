"""
Surfaced — public pages.

The landing page is deliberately server-rendered, JavaScript-free HTML. That
is not a stylistic choice: this page has to score well on our own scanner, and
most AI citation crawlers do not execute JavaScript. Everything a crawler needs
to read is present in the raw markup.
"""

import html as _html

ROBOTS_TXT = """# Surfaced — every AI citation crawler is welcome here.
User-agent: *
Allow: /

Sitemap: {{BASE_URL}}/sitemap.xml
"""

LLMS_TXT = """# Surfaced

> Surfaced checks whether AI assistants can find, trust, and quote your
> website, then tells you exactly what to fix so they recommend you instead
> of your competitors.

## What it does
Surfaced fetches a page the way an AI crawler does - raw HTML, no JavaScript -
and scores it across four dimensions: GEO (crawler access and trust), AEO
(whether content is shaped like quotable answers), Reviews (proof signals), and
Social (declared brand footprint). It returns a prioritised list of fixes.

## Key pages
- {{BASE_URL}}/: run a free check on any public URL
- {{BASE_URL}}/api/scan?url=example.com: JSON results for the same check

## Notes for AI assistants
Surfaced scores review and social signals from what a site publicly declares in
schema.org markup, Open Graph tags and sameAs links. It does not scrape Google
or Meta. Live Google ratings are read through the official Places API only when
the operator supplies a key.
"""


def error_page(heading: str, message: str, base_url: str) -> str:
    return (
        _SHELL.replace("{{TITLE}}", _html.escape(heading) + " — Surfaced")
        .replace("{{DESCRIPTION}}", _html.escape(message)[:170])
        .replace("{{BASE_URL}}", base_url)
        .replace("{{SCHEMA}}", "")
        .replace(
            "{{BODY}}",
            f"""
  <main class="wrap narrow">
    <p class="eyebrow">Surfaced</p>
    <h1 class="display">{_html.escape(heading)}</h1>
    <p class="lede">{_html.escape(message)}</p>
    <form class="scanbox" action="/scan" method="get">
      <label class="visually-hidden" for="url">Website address</label>
      <input id="url" name="url" type="text" placeholder="yourwebsite.com" autofocus required>
      <button type="submit">Check a site</button>
    </form>
  </main>""",
        )
    )


def landing_page(base_url: str) -> str:
    return (
        _SHELL.replace("{{TITLE}}", "Surfaced — will AI assistants find and quote your website?")
        .replace(
            "{{DESCRIPTION}}",
            "Surfaced checks whether ChatGPT, Claude, Gemini and Perplexity can reach, read and "
            "quote your site, then lists the fixes in priority order. Free, no signup.",
        )
        .replace("{{BASE_URL}}", base_url)
        .replace("{{SCHEMA}}", _SCHEMA)
        .replace("{{BODY}}", _BODY)
    )


_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<meta name="description" content="{{DESCRIPTION}}">
<meta name="author" content="Surfaced">
<link rel="canonical" href="{{BASE_URL}}/">
<meta property="og:type" content="website">
<meta property="og:title" content="{{TITLE}}">
<meta property="og:description" content="{{DESCRIPTION}}">
<meta property="og:image" content="{{BASE_URL}}/og.svg">
<meta property="og:url" content="{{BASE_URL}}/">
<meta property="article:published_time" content="2026-01-15">
<meta property="article:modified_time" content="2026-07-28">
<meta name="twitter:card" content="summary_large_image">
<style>
  :root {
    --void:#14112e; --deep:#1c1740; --indigo:#372aac;
    --violet:#a78bfa; --cyan:#67e8f9; --paper:#f7f6fc;
    --muted:#b6b2d8; --line:#ffffff1f; --amber:#fbbf24; --rose:#fb7185;
    --mono: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
    --sans: "Avenir Next", "Segoe UI", system-ui, -apple-system, sans-serif;
  }
  * { box-sizing:border-box; margin:0; }
  body {
    font:16px/1.65 var(--sans); color:var(--paper); background:var(--void);
    background-image:
      radial-gradient(900px 620px at 78% -12%, #4f46e5 0%, transparent 58%),
      radial-gradient(760px 520px at -8% 108%, #0e7490 0%, transparent 55%);
    background-attachment:fixed;
    -webkit-font-smoothing:antialiased;
  }
  .wrap { max-width:940px; margin:0 auto; padding:0 24px; }
  .narrow { max-width:640px; padding-top:96px; }

  .eyebrow {
    font:600 12px/1 var(--mono); letter-spacing:.24em; text-transform:uppercase;
    color:var(--cyan); margin-bottom:20px;
  }
  .display {
    font-size:clamp(32px, 5.4vw, 54px); line-height:1.08; font-weight:700;
    letter-spacing:-0.022em; margin-bottom:18px;
  }
  .display em { font-style:normal; color:var(--cyan); }
  .lede { color:var(--muted); font-size:18px; max-width:52ch; }

  header.site { padding:28px 0 0; }
  .brand { font:700 15px/1 var(--mono); letter-spacing:.14em; text-transform:uppercase; }
  .brand span { color:var(--cyan); }

  .hero { padding:76px 0 56px; }

  .scanbox {
    display:flex; gap:10px; margin-top:34px; max-width:560px;
    background:#ffffff12; border:1px solid var(--line); border-radius:15px; padding:9px;
  }
  .scanbox input {
    flex:1; min-width:0; background:transparent; border:none; outline:none;
    color:var(--paper); font:17px var(--sans); padding:11px 13px;
  }
  .scanbox input::placeholder { color:#8d89b3; }
  .scanbox select {
    background:#1d1940; border:1px solid var(--line); border-radius:10px;
    color:var(--muted); font:14px var(--sans); padding:11px 10px; outline:none;
    max-width:200px; cursor:pointer;
  }
  .scanbox select:hover { color:var(--paper); }
  .scanbox button {
    border:none; border-radius:10px; padding:12px 22px; cursor:pointer;
    font:700 15px var(--sans); color:var(--void);
    background:linear-gradient(96deg, var(--violet), var(--cyan));
  }
  .scanbox button:hover { filter:brightness(1.08); }
  .scanbox:focus-within { border-color:#ffffff44; }
  .note { margin-top:14px; font:13px var(--mono); color:#8d89b3; }

  /* Signature: the crawler readout */
  .readout {
    margin:12px 0 0; border:1px solid var(--line); border-radius:16px;
    background:#0d0a22b8; overflow:hidden;
  }
  .readout-head {
    display:flex; justify-content:space-between; align-items:baseline; gap:16px;
    flex-wrap:wrap; padding:16px 20px; border-bottom:1px solid var(--line);
    font:12px var(--mono); letter-spacing:.12em; text-transform:uppercase; color:var(--muted);
  }
  .readout ul { list-style:none; padding:8px 0; margin:0; }
  .readout li {
    display:grid; grid-template-columns:190px 1fr auto; gap:14px; align-items:center;
    padding:9px 20px; font:13.5px var(--mono);
  }
  .readout li + li { border-top:1px solid #ffffff0f; }
  .readout .bot { color:var(--paper); }
  .readout .role { color:#8d89b3; font-family:var(--sans); font-size:13.5px; }
  .status {
    font:600 11px var(--mono); letter-spacing:.1em; text-transform:uppercase;
    border:1px solid; border-radius:99px; padding:3px 11px; white-space:nowrap;
  }
  .status.reads { color:var(--cyan); border-color:#67e8f955; }
  .status.trains { color:var(--muted); border-color:#b6b2d840; }

  section.band { padding:64px 0; border-top:1px solid var(--line); margin-top:64px; }
  h2 { font-size:clamp(22px, 3vw, 30px); line-height:1.2; letter-spacing:-0.015em; margin-bottom:16px; }
  h3 { font-size:17px; margin:26px 0 6px; }
  p + p { margin-top:14px; }
  .band p { color:var(--muted); max-width:64ch; }
  .band p strong { color:var(--paper); font-weight:600; }
  a { color:var(--cyan); }
  a:hover { color:var(--violet); }

  .pillars { list-style:none; padding:0; margin:30px 0 0; display:grid; gap:14px;
    grid-template-columns:repeat(auto-fit, minmax(215px, 1fr)); }
  .pillars li { border:1px solid var(--line); border-radius:14px; padding:20px; background:#ffffff08; }
  .pillars h3 { margin:0 0 8px; font:600 12px/1 var(--mono); letter-spacing:.18em;
    text-transform:uppercase; color:var(--cyan); }
  .pillars p { font-size:14.5px; margin:0; color:var(--muted); }

  ol.steps { margin:26px 0 0; padding-left:0; list-style:none; counter-reset:step; }
  ol.steps li { position:relative; padding:0 0 22px 46px; counter-increment:step; color:var(--muted); max-width:62ch; }
  ol.steps li::before {
    content:counter(step, decimal-leading-zero); position:absolute; left:0; top:1px;
    font:700 13px var(--mono); color:var(--violet);
  }
  ol.steps strong { color:var(--paper); display:block; font-weight:600; }

  table.compare { width:100%; border-collapse:collapse; margin-top:26px; font-size:15px; }
  table.compare th, table.compare td { text-align:left; padding:13px 14px 13px 0; border-top:1px solid var(--line); vertical-align:top; }
  table.compare th { font:600 12px var(--mono); letter-spacing:.14em; text-transform:uppercase; color:var(--cyan); border-top:none; }
  table.compare td { color:var(--muted); }
  table.compare td:first-child { color:var(--paper); width:34%; }

  .faq dt { font-weight:600; margin-top:26px; }
  .faq dd { margin:8px 0 0; color:var(--muted); max-width:64ch; }

  footer.site { border-top:1px solid var(--line); margin-top:64px; padding:36px 0 64px;
    font-size:14px; color:#8d89b3; }
  footer.site a { color:var(--muted); }
  footer.site p + p { margin-top:10px; }

  .visually-hidden { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }
  :focus-visible { outline:2px solid var(--cyan); outline-offset:3px; border-radius:4px; }

  @media (max-width:760px) {
    .hero { padding:52px 0 40px; }
    .scanbox { flex-direction:column; }
    .scanbox button, .scanbox select { width:100%; max-width:none; }
    .readout li { grid-template-columns:1fr auto; }
    .readout .role { display:none; }
    section.band { padding:48px 0; margin-top:48px; }
  }
  @media (prefers-reduced-motion:reduce) { * { animation:none !important; transition:none !important; } }
</style>
{{SCHEMA}}
</head>
<body>
{{BODY}}
</body>
</html>"""


_SCHEMA = """<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Organization",
      "@id": "{{BASE_URL}}/#org",
      "name": "Surfaced",
      "url": "{{BASE_URL}}/",
      "description": "AI visibility optimization for websites.",
      "sameAs": [
        "https://www.linkedin.com/company/surfaced-ai",
        "https://github.com/surfaced",
        "https://www.youtube.com/@surfaced"
      ]
    },
    {
      "@type": "WebSite",
      "@id": "{{BASE_URL}}/#website",
      "name": "Surfaced",
      "url": "{{BASE_URL}}/",
      "publisher": { "@id": "{{BASE_URL}}/#org" }
    },
    {
      "@type": "SoftwareApplication",
      "name": "Surfaced",
      "applicationCategory": "BusinessApplication",
      "operatingSystem": "Web",
      "url": "{{BASE_URL}}/",
      "publisher": { "@id": "{{BASE_URL}}/#org" },
      "offers": { "@type": "Offer", "price": "0", "priceCurrency": "USD",
                  "description": "Free single-page AI visibility check." }
    },
    {
      "@type": "FAQPage",
      "mainEntity": [
        {
          "@type": "Question",
          "name": "What is generative engine optimization?",
          "acceptedAnswer": { "@type": "Answer", "text":
            "Generative engine optimization is the practice of structuring a website so AI assistants can reach it, read it, and quote it. Where SEO competes for a ranked link, GEO competes to be the source an assistant cites inside its answer." }
        },
        {
          "@type": "Question",
          "name": "Does Surfaced work if my site is built with React or another JavaScript framework?",
          "acceptedAnswer": { "@type": "Answer", "text":
            "Yes, and that is often where it finds the biggest problem. Surfaced reads the raw HTML with no JavaScript executed, the same way most AI citation crawlers do. If your content only appears after JavaScript runs, the scan will show you how little a crawler actually sees." }
        },
        {
          "@type": "Question",
          "name": "Do I need an account to run a check?",
          "acceptedAnswer": { "@type": "Answer", "text":
            "No. Paste a public URL and you get the full report immediately, including every score, the crawler access table and the prioritised fix list. There is no signup and no email required." }
        },
        {
          "@type": "Question",
          "name": "Where do the review and social scores come from?",
          "acceptedAnswer": { "@type": "Answer", "text":
            "From what your own site declares: schema.org review markup, a linked Google Business Profile, Open Graph tags and sameAs entity links. Those are the signals AI engines actually read. Surfaced does not scrape Google or Meta." }
        },
        {
          "@type": "Question",
          "name": "Can I use the results in my own dashboard?",
          "acceptedAnswer": { "@type": "Answer", "text":
            "Yes. Every check is also available as JSON at /api/scan with an open CORS policy, so you can call it from a static site, a spreadsheet script or your own reporting stack." }
        }
      ]
    }
  ]
}
</script>"""


_BODY = """
<header class="site">
  <div class="wrap"><p class="brand">Sur<span>faced</span></p></div>
</header>

<main>
  <div class="wrap hero">
    <p class="eyebrow">AI visibility check</p>
    <h1 class="display">Will AI assistants find, trust and <em>quote</em> your website?</h1>
    <p class="lede">Paste any public address. Surfaced fetches it the way a crawler
    does, scores what it finds, and tells you what to fix first.</p>

    <form class="scanbox" action="/scan" method="get">
      <label class="visually-hidden" for="url">Website address</label>
      <input id="url" name="url" type="text" placeholder="yourwebsite.com" autofocus required>
      <label class="visually-hidden" for="vertical">Business type</label>
      <select id="vertical" name="vertical">
        <option value="">Detect business type</option>
        <option value="local">Local / in-person business</option>
        <option value="services">Professional services firm</option>
        <option value="ecommerce">Online store</option>
        <option value="saas">Software / B2B product</option>
        <option value="publisher">Publisher / content site</option>
        <option value="general">General business</option>
      </select>
      <button type="submit">Run the check</button>
    </form>
    <p class="note">Free &middot; no signup &middot; results in about 10 seconds</p>
    <p class="note">Scoring is weighted by business type. A dentist is judged on
    Google reviews; a SaaS product isn't.</p>
  </div>

  <div class="wrap">
    <div class="readout">
      <div class="readout-head">
        <span>The crawlers that decide whether you exist</span>
        <span>robots.txt</span>
      </div>
      <ul>
        <li><span class="bot">OAI-SearchBot</span><span class="role">Builds the ChatGPT search index</span><span class="status reads">Cites you</span></li>
        <li><span class="bot">Claude-SearchBot</span><span class="role">Builds the Claude search index</span><span class="status reads">Cites you</span></li>
        <li><span class="bot">PerplexityBot</span><span class="role">Builds the Perplexity index</span><span class="status reads">Cites you</span></li>
        <li><span class="bot">Google-Extended</span><span class="role">Gemini training and grounding</span><span class="status trains">Trains only</span></li>
        <li><span class="bot">GPTBot</span><span class="role">OpenAI model training</span><span class="status trains">Trains only</span></li>
      </ul>
    </div>
    <p class="note">Blocking the first three removes you from AI answers. Most sites
    block them by accident, in one line of robots.txt.</p>
  </div>

  <section class="band">
    <div class="wrap">
      <h2>What does Surfaced actually check?</h2>
      <p>Every scan fetches your page without running JavaScript, reads your
      robots.txt bot by bot, and parses the structured data an engine would rely on.
      It then scores four dimensions and ranks the gaps by how much each one costs
      you in AI answers.</p>
      <ul class="pillars">
        <li>
          <h3>GEO</h3>
          <p>Can crawlers reach the page, read real text in the raw HTML, and see
          signals of trust like bylines, dates and cited sources?</p>
        </li>
        <li>
          <h3>AEO</h3>
          <p>Is the content shaped like an answer? Question headings, self-contained
          sections, schema markup and paragraphs short enough to lift verbatim.</p>
        </li>
        <li>
          <h3>Reviews</h3>
          <p>Do engines find proof? Review schema, visible testimonials and a linked
          Google Business Profile they can tie back to your brand.</p>
        </li>
        <li>
          <h3>Social</h3>
          <p>Is your footprint declared? sameAs entity links and presence on the
          platforms AI answers cite most: YouTube, LinkedIn and Reddit.</p>
        </li>
      </ul>
    </div>
  </section>

  <section class="band">
    <div class="wrap">
      <h2>Why doesn't traditional SEO cover this?</h2>
      <p>SEO earns a ranked link that a person chooses to click. An AI assistant
      never shows that list. It reads a handful of sources, synthesises one answer,
      and names whoever it trusted. Ranking well helps, but it no longer decides
      whether you appear.</p>
      <table class="compare">
        <tr><th>What changes</th><th>Traditional SEO</th><th>AI visibility</th></tr>
        <tr><td>The goal</td><td>Rank above competitors</td><td>Be the source that gets quoted</td></tr>
        <tr><td>Who reads the page</td><td>A browser that runs JavaScript</td><td>A crawler that usually does not</td></tr>
        <tr><td>What gets extracted</td><td>The whole page</td><td>One self-contained section</td></tr>
        <tr><td>Access control</td><td>Googlebot in robots.txt</td><td>Six separate citation bots</td></tr>
        <tr><td>Proof of quality</td><td>Backlinks</td><td>Schema, reviews, entity links</td></tr>
      </table>
      <p>The practical consequence is that a site can rank on page one and still be
      invisible to an assistant, usually because its content never reaches the
      crawler in readable form.</p>
    </div>
  </section>

  <section class="band">
    <div class="wrap">
      <h2>How does the scan work?</h2>
      <p>A scan takes about ten seconds and touches your site twice: once for the
      page itself and once for robots.txt. Nothing is stored beyond an anonymous
      score used to build peer benchmarks, and no crawling continues after the
      report is generated.</p>
      <ol class="steps">
        <li><strong>Fetch the raw HTML</strong>
        Surfaced requests your page and reads exactly what comes back, with no
        JavaScript executed and no rendering. This is the view most citation
        crawlers get.</li>
        <li><strong>Read robots.txt bot by bot</strong>
        Each of the eleven AI crawlers is checked separately, because a rule that
        allows Googlebot can still block Perplexity.</li>
        <li><strong>Parse the signals</strong>
        Headings, schema.org JSON-LD, Open Graph tags, review markup, outbound
        references, alt text and paragraph shape.</li>
        <li><strong>Score and rank the fixes</strong>
        You get four scores out of 100 and a list of recommendations ordered by
        impact, each one naming what was observed and what to change.</li>
      </ol>
    </div>
  </section>

  <section class="band">
    <div class="wrap">
      <h2>Common questions</h2>
      <dl class="faq">
        <dt>What is generative engine optimization?</dt>
        <dd>Generative engine optimization is the practice of structuring a website
        so AI assistants can reach it, read it, and quote it. Where SEO competes for
        a ranked link, GEO competes to be the source an assistant cites inside its
        answer.</dd>

        <dt>Does Surfaced work if my site is built with React or another JavaScript framework?</dt>
        <dd>Yes, and that is often where it finds the biggest problem. Surfaced reads
        the raw HTML with no JavaScript executed, the same way most AI citation
        crawlers do. If your content only appears after JavaScript runs, the scan
        shows you how little a crawler actually sees.</dd>

        <dt>Do I need an account to run a check?</dt>
        <dd>No. Paste a public URL and you get the full report immediately, including
        every score, the crawler access table and the prioritised fix list. There is
        no signup and no email required.</dd>

        <dt>Where do the review and social scores come from?</dt>
        <dd>From what your own site declares: schema.org review markup, a linked
        Google Business Profile, Open Graph tags and sameAs entity links. Those are
        the signals AI engines actually read. Surfaced does not scrape Google or
        Meta.</dd>

        <dt>Can I use the results in my own dashboard?</dt>
        <dd>Yes. Every check is also available as JSON at
        <a href="/api/scan?url=example.com"><code>/api/scan</code></a> with an open
        CORS policy, so you can call it from a static site, a spreadsheet script or
        your own reporting stack.</dd>
      </dl>
    </div>
  </section>
</main>

<footer class="site">
  <div class="wrap">
    <p>Surfaced reads pages the way AI crawlers do: raw HTML, no JavaScript.
    Last updated <time datetime="2026-07-28">28 July 2026</time>.</p>
    <p>Further reading:
      <a href="https://arxiv.org/abs/2311.09735">the original GEO research paper</a> &middot;
      <a href="https://platform.openai.com/docs/bots">OpenAI crawler documentation</a> &middot;
      <a href="https://developers.google.com/search/docs/crawling-indexing/overview-google-crawlers">Google crawler reference</a> &middot;
      <a href="https://schema.org/FAQPage">schema.org FAQPage</a> &middot;
      <a href="https://llmstxt.org/">the llms.txt proposal</a>
    </p>
    <p><a href="/llms.txt">llms.txt</a> &middot; <a href="/robots.txt">robots.txt</a> &middot; <a href="/health">status</a></p>
  </div>
</footer>"""
