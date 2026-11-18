"""
Surfaced — public pages.

The landing page is deliberately server-rendered, JavaScript-free HTML. That
is not a stylistic choice: this page has to score well on our own scanner, and
most AI citation crawlers do not execute JavaScript. Everything a crawler needs
to read is present in the raw markup.
"""

import html as _html
import json

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
- {{BASE_URL}}/app: the installable app (works offline, installs to a phone home screen)

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
        _SHELL.replace("{{TITLE}}", "Surfaced — get recommended by ChatGPT, Claude, Gemini and Perplexity")
        .replace(
            "{{DESCRIPTION}}",
            "More customers now ask AI who to choose. Surfaced checks whether ChatGPT, Claude, Gemini "
            "and Perplexity can read and trust your website. Free score in 10 seconds; full report with fixes $19.99.",
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

  .hero { padding-top:76px; padding-bottom:56px; }

  .scanbox {
    display:flex; gap:10px; margin-top:34px; max-width:780px;
    background:#ffffff12; border:1px solid var(--line); border-radius:15px; padding:9px;
  }
  .scanbox input {
    flex:1 1 240px; min-width:0; background:transparent; border:none; outline:none;
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
  .price { margin-top:28px; border:1px solid var(--line); border-radius:16px; padding:20px 22px;
    background:#ffffff08; display:flex; flex-wrap:wrap; gap:16px 24px; align-items:center; justify-content:space-between; }
  .price > div { flex:1 1 320px; }
  .price-label { font:600 11px var(--mono); letter-spacing:.12em; text-transform:uppercase; color:var(--muted); margin:0; }
  .price-row { display:flex; align-items:baseline; flex-wrap:wrap; gap:10px; margin:8px 0 6px; }
  .price-was { font-size:20px; color:#8d89b3; text-decoration-thickness:2px; }
  .price-now { font-size:34px; font-weight:700; color:var(--paper, #fff); }
  .price-tag { font:600 11px var(--mono); letter-spacing:.08em; text-transform:uppercase; color:var(--amber);
    border:1px solid #fbbf2466; border-radius:99px; padding:3px 9px; }
  .price-sub { margin:0; font-size:14px; color:var(--muted); }
  .price-buy { font:600 15px inherit; padding:13px 22px; border-radius:11px; border:0; cursor:pointer;
    background:var(--amber); color:#1a1530; }
  #buymsg { flex-basis:100%; }

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

  .asks { list-style:none; padding:0; margin:22px 0; display:flex; flex-wrap:wrap; gap:10px; }
  .asks li { border:1px solid var(--line); border-radius:99px; padding:9px 16px; background:#ffffff0a;
    color:var(--paper); font-size:15px; }
  .reasons { grid-template-columns:repeat(2, minmax(0, 1fr)) !important; }
  @media (max-width:640px) { .reasons { grid-template-columns:1fr !important; } }
  .reasons, .who { list-style:none; padding:0; margin:26px 0 0; display:grid; gap:14px;
    grid-template-columns:repeat(auto-fit, minmax(230px, 1fr)); }
  .reasons li, .who li { border:1px solid var(--line); border-radius:14px; padding:20px; background:#ffffff08; }
  .reasons h3, .who h3 { margin:0 0 8px; font-size:16px; color:var(--paper); }
  .reasons p, .who p { margin:0; font-size:14.5px; color:var(--muted); }
  .who p { font-style:italic; }
  .closing h2 { font-size:clamp(26px, 4vw, 38px); }
  a.cta { display:inline-block; text-decoration:none; font:600 16px var(--sans); padding:14px 24px;
    border-radius:12px; background:var(--amber); color:#1a1530; }
  a.cta:hover { color:#1a1530; filter:brightness(1.05); }
  .faq dt { font-weight:600; margin-top:26px; }
  .faq dd { margin:8px 0 0; color:var(--muted); max-width:64ch; }

  footer.site { border-top:1px solid var(--line); margin-top:64px; padding:36px 0 64px;
    font-size:14px; color:#8d89b3; }
  footer.site a { color:var(--muted); }
  footer.site p + p { margin-top:10px; }

  .visually-hidden { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; }
  :focus-visible { outline:2px solid var(--cyan); outline-offset:3px; border-radius:4px; }

  @media (max-width:760px) {
    .hero { padding-top:52px; padding-bottom:40px; }
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
      "offers": [
        { "@type": "Offer", "price": "0", "priceCurrency": "USD",
          "description": "Free single-page AI visibility check: grade and four scores." },
        { "@type": "Offer", "price": "19.99", "priceCurrency": "USD",
          "description": "Full report, one-time purchase: every fix in priority order. Introductory price; regular price $49.99." }
      ]
    },
    {
      "@type": "FAQPage",
      "mainEntity": [
        {
          "@type": "Question",
          "name": "Do I need to be technical?",
          "acceptedAnswer": { "@type": "Answer", "text": "No. The score and the four areas are explained in plain English. The full report is written so you can follow it yourself or hand it straight to whoever manages your website." }
        },
        {
          "@type": "Question",
          "name": "Is the check really free?",
          "acceptedAnswer": { "@type": "Answer", "text": "Yes. The score out of 100 and the four-area breakdown are free, with no signup. The full report, with the comparison and every fix, is a one-time $19.99 purchase." }
        },
        {
          "@type": "Question",
          "name": "Will this guarantee that ChatGPT recommends me?",
          "acceptedAnswer": { "@type": "Answer", "text": "No tool can promise that, and you should be wary of any that does. What Surfaced does is find the things that stop AI from reading and trusting your website, and show you how to fix them, so you have a fair chance of being named." }
        },
        {
          "@type": "Question",
          "name": "Do you change anything on my website?",
          "acceptedAnswer": { "@type": "Answer", "text": "No. Surfaced only reads your public pages, the same way an AI tool would. Nothing is installed and nothing is changed." }
        },
        {
          "@type": "Question",
          "name": "How do I get back to my report later?",
          "acceptedAnswer": { "@type": "Answer", "text": "After you buy, we email you a link that opens your reports directly. You can also save any report as a PDF." }
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
    <p class="eyebrow">Be found by AI</p>
    <h1 class="display">Your next customer probably won't find you on <em>Google</em>.</h1>
    <p class="lede">More and more people ask ChatGPT, Claude, Gemini or Perplexity for a
    recommendation. The answer is short, often just two or three names. Find out in
    about ten seconds whether your website gives AI a reason to name you.</p>

    <form class="scanbox" action="/scan" method="get">
      <label class="visually-hidden" for="url">Your website address</label>
      <input id="url" name="url" type="text" placeholder="yourbusiness.com" autofocus required>
      <label class="visually-hidden" for="vertical">Type of business</label>
      <select id="vertical" name="vertical">
        <option value="">Business type: auto</option>
        <option value="local">Restaurant, shop, practice or local service</option>
        <option value="services">Professional or creative services</option>
        <option value="ecommerce">Online store</option>
        <option value="saas">Software or tech company</option>
        <option value="publisher">Blog, media or content site</option>
        <option value="general">Something else</option>
      </select>
      <button type="submit">Check my website</button>
    </form>
    <p class="note">Free &middot; no signup &middot; about 10 seconds</p>

    <div class="price">
      <div>
        <p class="price-label">Full report &middot; one-time purchase</p>
        <p class="price-row"><s class="price-was" aria-label="Regular price $49.99">$49.99</s>
          <span class="price-now">$19.99</span>
          <span class="price-tag">Introductory offer</span></p>
        <p class="price-sub">The free check gives you a score out of 100 and how you do in four
        key areas. The full report shows how you compare with similar businesses and gives you a
        prioritised list of fixes, with step-by-step instructions your team or web designer can
        act on right away. Save it as a PDF. No subscription.</p>
      </div>
      <button type="button" id="buy" class="price-buy">Get the full report</button>
      <p id="buymsg" class="price-sub" aria-live="polite"></p>
    </div>
    <p class="note">Already bought a report? <a href="/reports">Open it here</a>.</p>
    <script>
    document.getElementById('buy').addEventListener('click', async function () {
      var m = document.getElementById('buymsg'); m.textContent = 'Opening checkout\\u2026';
      try {
        var r = await fetch('/api/checkout', {method: 'POST'});
        var d = await r.json();
        if (d.url) { location.href = d.url; return; }
        m.textContent = d.error || 'Checkout is unavailable right now.';
      } catch (e) { m.textContent = 'Could not reach checkout. Try again.'; }
    });
    </script>
  </div>

  <section class="band">
    <div class="wrap">
      <h2>People are asking AI who to hire, where to eat and what to buy.</h2>
      <p>Questions like these are typed into AI assistants every day:</p>
      <ul class="asks">
        <li>&ldquo;What's the best daycare near me?&rdquo;</li>
        <li>&ldquo;Who caters a 40-person office lunch nearby?&rdquo;</li>
        <li>&ldquo;Recommend a wedding photographer in my area.&rdquo;</li>
        <li>&ldquo;Good Italian restaurant for a family dinner tonight?&rdquo;</li>
        <li>&ldquo;Which CRM suits a 20-person team?&rdquo;</li>
        <li>&ldquo;Who's a reliable IT partner for a small firm?&rdquo;</li>
      </ul>
      <p><strong>The AI gives a short answer, often just two or three names.</strong> If your
      website isn't built so AI can read it and trust it, you aren't one of them, however good
      you are at what you do.</p>
    </div>
  </section>

  <section class="band">
    <div class="wrap">
      <h2>Traditional SEO wasn't designed for this. Surfaced was.</h2>
      <p>Google shows a list of links and lets people choose. An AI assistant reads a few
      websites itself and decides who to mention. A site can rank well on Google and still be
      skipped by AI, usually for one of four reasons:</p>
      <ul class="reasons">
        <li><h3>AI can't get in</h3>
        <p>Many websites block AI tools by accident, through a single setting that nobody
        remembers turning on.</p></li>
        <li><h3>AI can't read it</h3>
        <p>Some sites show text to people but hand AI tools an almost empty page.</p></li>
        <li><h3>AI can't tell what you do</h3>
        <p>What you offer, where, for whom and how to reach you isn't stated in a way AI can
        pick up with confidence.</p></li>
        <li><h3>AI can't find proof</h3>
        <p>Reviews, testimonials and your profiles elsewhere aren't connected to your site,
        so AI has no evidence that customers rate you.</p></li>
      </ul>
    </div>
  </section>

  <section class="band">
    <div class="wrap">
      <h2>How does it work?</h2>
      <ol class="steps">
        <li><strong>Enter your web address</strong>
        Any public website works, whether it was built on Wix, Squarespace, WordPress,
        Shopify or by a developer.</li>
        <li><strong>Surfaced checks your site the way AI tools do</strong>
        In about ten seconds you get a score out of 100 and a breakdown across four key
        areas: whether AI can find and trust you, whether your content answers customer
        questions clearly, whether there's proof customers rate you, and how well your
        presence elsewhere is linked. Free, no signup.</li>
        <li><strong>Get the full report and fix what matters most</strong>
        For $19.99 you see how you compare with similar businesses and get a prioritised
        list of fixes. Each one says why it matters and how to do it, step by step, with
        anything your web designer needs to copy and paste. Save it as a PDF and open it
        again any time from the link we email you.</li>
      </ol>
      <p class="note"><a href="#url">Check your website now &rarr;</a></p>
    </div>
  </section>

  <section class="band">
    <div class="wrap">
      <h2>Who is Surfaced for?</h2>
      <p>Any business that wins customers through recommendations. Your score is weighted by
      the kind of business you run: a restaurant is judged differently from a software company.</p>
      <ul class="who">
        <li><h3>Restaurants &amp; caf&eacute;s</h3><p>&ldquo;Best brunch spot near me?&rdquo;</p></li>
        <li><h3>Caterers &amp; event services</h3><p>&ldquo;Who caters weddings in my area?&rdquo;</p></li>
        <li><h3>Photographers &amp; videographers</h3><p>&ldquo;Affordable family photographer nearby?&rdquo;</p></li>
        <li><h3>Daycares &amp; schools</h3><p>&ldquo;Which daycare has the best reviews?&rdquo;</p></li>
        <li><h3>Dentists, clinics &amp; local practices</h3><p>&ldquo;Family dentist taking new patients?&rdquo;</p></li>
        <li><h3>Salons, spas &amp; fitness</h3><p>&ldquo;Good hair salon for curly hair?&rdquo;</p></li>
        <li><h3>Contractors &amp; home services</h3><p>&ldquo;Reliable plumber who comes same day?&rdquo;</p></li>
        <li><h3>B2B &amp; professional firms</h3><p>&ldquo;Accountant who specialises in small businesses?&rdquo;</p></li>
        <li><h3>Small tech &amp; software companies</h3><p>&ldquo;Best scheduling tool for a clinic?&rdquo;</p></li>
      </ul>
    </div>
  </section>

  <section class="band">
    <div class="wrap">
      <h2>Common questions</h2>
      <dl class="faq">
        <dt>Do I need to be technical?</dt>
        <dd>No. The score and the four areas are explained in plain English. The full report is
        written so you can follow it yourself or hand it straight to whoever manages your
        website.</dd>
        <dt>Is the check really free?</dt>
        <dd>Yes. The score out of 100 and the four-area breakdown are free, with no signup. The
        full report, with the comparison and every fix, is a one-time $19.99 purchase.</dd>
        <dt>Will this guarantee that ChatGPT recommends me?</dt>
        <dd>No tool can promise that, and you should be wary of any that does. What Surfaced
        does is find the things that stop AI from reading and trusting your website, and show
        you how to fix them, so you have a fair chance of being named.</dd>
        <dt>Do you change anything on my website?</dt>
        <dd>No. Surfaced only reads your public pages, the same way an AI tool would. Nothing
        is installed and nothing is changed.</dd>
        <dt>How do I get back to my report later?</dt>
        <dd>After you buy, we email you a link that opens your reports directly. You can also
        save any report as a PDF.</dd>
      </dl>
    </div>
  </section>

  <section class="band closing">
    <div class="wrap">
      <h2>Being recommended by AI is the new front page.</h2>
      <p>Whether you run a restaurant, a photography studio, a daycare, a local practice, a B2B
      firm or a small tech company, Surfaced shows you what's keeping you off it, and how to
      fix it.</p>
      <p style="margin-top:22px"><a class="cta" href="#url">Check my website free</a></p>
    </div>
  </section>
</main>

<footer class="site">
  <div class="wrap">
    <p>Surfaced, by PatnAIQ &middot; <a href="mailto:surfaced@patnaiq.com">surfaced@patnaiq.com</a></p>
    <p><a href="/reports">My reports</a> &middot; <a href="/app">App</a> &middot; <a href="/llms.txt">llms.txt</a> &middot; <a href="/health">Status</a></p>
  </div>
</footer>"""


def paid_page(key: str, credits: int, base_url: str, emailed: str = "") -> str:
    """
    Shown once, after Stripe confirms payment.

    The key is derived from the checkout session, so this page can be reloaded
    from the same link — but it is the only place the key is ever displayed,
    and it is never emailed or logged.
    """
    return (
        _SHELL.replace("{{TITLE}}", "Payment received — Surfaced")
        .replace("{{DESCRIPTION}}", "Your scan credits are ready.")
        .replace("{{BASE_URL}}", base_url)
        .replace("{{SCHEMA}}", "")
        .replace("{{BODY}}", f"""
  <main class="wrap narrow">
    <p class="eyebrow">Payment received</p>
    <h1 class="display">Your scan key</h1>
    <p class="lede">Keep this somewhere safe. It is the only thing that spends
    your credits. You can reopen this page from your receipt link at any time.</p>

    <p style="font:16px var(--mono); background:#ffffff12; border:1px solid var(--line);
              border-radius:12px; padding:18px; word-break:break-all; margin-top:26px;">
      {_html.escape(key)}
    </p>
    <p class="note">{credits} scan credit{"" if credits == 1 else "s"} available.</p>

    {f'<p class="note">A confirmation with this key and your links has been emailed to {_html.escape(emailed)}. Check spam if it has not arrived in a few minutes.</p>' if emailed else ''}

    <p class="lede" style="margin-top:30px"><strong>1.</strong>
    <a href="/app#k={_html.escape(key)}">Run your check</a>. The key is filled in for you.</p>
    <p class="lede"><strong>2.</strong>
    <a href="/reports#k={_html.escape(key)}">View your reports</a> any time. Bookmark this
    link: it opens your reports directly, and each one can be saved as a PDF.</p>
    <p class="note">Anyone with the key or these links can use your credit and see your
    reports, so share them only with people you want to have access.</p>
    <p class="note">If the credit count reads 0, Stripe's confirmation is still
    in flight. Reload in a few seconds — this link stays valid.</p>
    <script>
    try {{ localStorage.setItem('surfaced.key', {json.dumps(key)}); }} catch (e) {{}}
    </script>
  </main>"""))


def reports_page(base_url: str) -> str:
    """Where a buyer reopens reports they have paid for, using their scan key."""
    return (
        _SHELL.replace("{{TITLE}}", "Your reports — Surfaced")
        .replace("{{DESCRIPTION}}", "Reopen the full reports you have bought, using your scan key.")
        .replace("{{BASE_URL}}", base_url)
        .replace("{{SCHEMA}}", "")
        .replace("{{BODY}}", """
  <main class="wrap narrow">
    <p class="eyebrow">Your reports</p>
    <h1 class="display">Reopen a full report</h1>
    <p class="lede">Enter your scan key to see every full report bought with it.
    Reopening a report is free and can be saved as a PDF.</p>

    <form class="scanbox" id="kf">
      <label class="visually-hidden" for="k">Scan key</label>
      <input id="k" type="text" autocapitalize="off" autocorrect="off" spellcheck="false"
             placeholder="sfd_…" required>
      <button type="submit">Show my reports</button>
    </form>
    <p class="note" id="msg" aria-live="polite"></p>
    <div id="list" style="margin-top:22px"></div>

    <form id="open" method="post" action="/report" target="_blank" hidden>
      <input type="hidden" name="key" id="ok"><input type="hidden" name="id" id="oi">
    </form>
    <p class="note" style="margin-top:34px"><a href="/app">Run a new check in the app</a>
    &middot; <a href="/">Home</a></p>
  </main>
  <script>
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); };
  var k = document.getElementById('k'), msg = document.getElementById('msg'), list = document.getElementById('list');
  try { k.value = localStorage.getItem('surfaced.key') || ''; } catch (e) {}
  // A link from the confirmation email carries the key after the #, which
  // browsers never send to a server. Use it, then take it out of the address bar.
  var hk = (location.hash.match(/[#&]k=(sfd_[A-Za-z0-9_-]{20,})/) || [])[1];
  if (hk) {
    k.value = hk;
    try { localStorage.setItem('surfaced.key', hk); } catch (e) {}
    history.replaceState(null, '', location.pathname);
  }
  async function show() {
    var key = k.value.trim(); if (!key) return;
    msg.textContent = 'Looking up your reports\u2026'; list.innerHTML = '';
    try {
      var r = await fetch('/api/reports', { headers: { 'X-Scan-Key': key } });
      var d = await r.json(), rows = d.reports || [];
      if (!rows.length) { msg.textContent = 'No full reports found for that key yet. Run a check in the app to use a credit.'; return; }
      try { localStorage.setItem('surfaced.key', key); } catch (e) {}
      msg.textContent = rows.length + ' report' + (rows.length === 1 ? '' : 's') + ' found.';
      list.innerHTML = rows.map(function (x) {
        var when = x.checked ? new Date(x.checked * 1000).toLocaleDateString(undefined, {year:'numeric', month:'short', day:'numeric'}) : '';
        return '<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;padding:14px 0;border-top:1px solid var(--line)">' +
          '<div style="flex:1;min-width:200px"><strong>' + esc(x.title || x.url) + '</strong><br>' +
          '<span class="note" style="margin:0">' + esc(String(x.url).replace(/^https?:\\/\\//, '')) + ' &middot; ' + esc(when) +
          (x.score != null ? ' &middot; ' + esc(x.score) + '/100, grade ' + esc(x.grade) : '') + '</span></div>' +
          (x.available ? '<button type="button" data-id="' + esc(x.id) + '" class="openbtn" style="font:600 14px inherit;padding:10px 16px;border-radius:10px;border:0;background:var(--amber);color:#1a1530;cursor:pointer">Open report</button>'
                       : '<span class="note" style="margin:0">Not stored</span>') + '</div>';
      }).join('');
    } catch (e) { msg.textContent = 'Could not reach the server. Try again.'; }
  }
  document.getElementById('kf').addEventListener('submit', function (e) { e.preventDefault(); show(); });
  list.addEventListener('click', function (e) {
    var id = e.target.getAttribute && e.target.getAttribute('data-id'); if (!id) return;
    document.getElementById('ok').value = k.value.trim();
    document.getElementById('oi').value = id;
    document.getElementById('open').submit();
  });
  if (k.value) show();
  </script>""")
    )
