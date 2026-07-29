# Surfaced Outreach Campaign Kit
*Targeting low-scoring websites with their own audit as the hook*

## The campaign in one sentence

You run `prospect_scan.py` on a list of sites in your target vertical, and every site that scores under 60/100 gets a short, personal email whose first line is their real score and their single biggest problem, with their full audit report attached — the product sells the product.

## Weekly rhythm (about 90 minutes total)

Monday, build the list: pick 25–40 businesses in your beachhead vertical from public directories, industry association member lists, "best X in NJ" roundups, or exhibitor lists from trade shows. Put their URLs in `urls.txt` and run the scanner. Tuesday, send: take everyone under 60, send Touch 1 using the generated hook and the attached report. Following Monday, send Touch 2 to non-responders. Four days later, Touch 3, then stop — three touches is the line between persistent and annoying. Expect roughly 40–60% of a typical SMB list to score under 60, a 3–8% reply rate on well-targeted cold email, and your goal at this stage is conversations and design partners, not closed revenue.

## Who exactly to target

Send to the business owner or marketing lead at companies where the finding is *fixable and felt*: scores under 60, especially sites with blocked citation crawlers (a five-minute fix with dramatic framing) or JavaScript-rendered content (a real project, bigger deal size). Skip sites under construction, hobby sites, and anyone you'd be embarrassed to invoice. Find the human via the website's contact page, their LinkedIn company page, or the business's public listing — address a person, not info@.

## Touch 1 — the audit email (day 0)

Subject options (rotate, track which gets replies):
- ChatGPT can't see {{Company}}'s website — here's proof
- {{Company}} scored {{score}}/100 for AI visibility
- Quick finding about {{website}}

Body:

> Hi {{FirstName}},
>
> {{PASTE THE GENERATED HOOK FROM outreach_hooks.txt — it already contains their score and biggest gap}}
>
> Why this matters: when your customers ask ChatGPT, Claude or Gemini "{{a question their buyers actually ask, e.g. 'who's the best commercial HVAC supplier near Morristown'}}", the AI composes one answer from a handful of sites it can read and trust. Right now, yours mostly isn't one of them.
>
> The attached report shows exactly what an AI crawler sees on your site and the fixes, in priority order. The top items are usually a week of work — some take five minutes.
>
> If you'd like, I'll walk you through it on a 15-minute call — no charge, and the report is yours either way.
>
> Dilip Kumar
> Surfaced — AI visibility for growing brands
> {{phone}} · {{city, state}}
> If you'd rather not hear from me again, just reply "no thanks" and I won't follow up.

Attach: their HTML report from `reports/`.

## Touch 2 — the one-fix nudge (day 7, non-responders)

Subject: Re: {{original subject}}

> Hi {{FirstName}},
>
> One concrete thing from the report I sent: {{their #1 recommendation, paraphrased — e.g. "your robots.txt currently blocks PerplexityBot, which means Perplexity literally cannot cite you — that's a two-line change"}}.
>
> Happy to tell whoever manages your site exactly what to change — takes one email. Worth a quick call?

## Touch 3 — the breakup (day 11, non-responders)

> Hi {{FirstName}},
>
> Last note from me. AI assistants are answering more of your customers' questions every month, and the brands they cite are being chosen right now. The report I sent stays valid — if it becomes a priority this quarter, I'm easy to find.
>
> Either way, good luck with {{Company}}.

## LinkedIn track (manual only — never automated)

LinkedIn restricts accounts for automated outreach, so this track is by hand and works best as air cover for the email: connect with the owner with a note ("Ran {{Company}} through an AI-visibility audit — sent the report to {{email/your site's contact form}}, happy to walk you through it"), and post one piece of content weekly sharing an anonymized finding from your scans ("Scored 30 {{vertical}} websites this week. 70% block at least one AI citation crawler. Here's what that costs them…"). The posts compound; the DMs convert warm.

## Compliance guardrails (non-negotiable)

Every email: your real name and contact info, a truthful subject line, and a working opt-out (the "reply no thanks" line) — that's CAN-SPAM. Honor opt-outs immediately and keep a do-not-contact list. Email business addresses about a business matter; don't scrape personal emails in bulk. If a prospect is in the EU/UK, you need a defensible legitimate-interest basis — at your stage, simplest is to focus on US prospects. And never send from a domain you can't afford to burn: use a separate sending domain (e.g. getsurfaced.com) with SPF/DKIM/DMARC set up, warm it up slowly (10–15/day for the first two weeks), and keep volume under ~30/day per inbox.

## Tracking

A simple spreadsheet beats a CRM right now: company, URL, score, top issue, contact name, touch 1/2/3 dates, reply (Y/N), outcome. The metric that decides your next move is replies per 100 sends by vertical — when one vertical doubles the others, that's your beachhead answering for itself.
