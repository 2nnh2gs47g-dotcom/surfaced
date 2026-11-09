# Surfaced

Checks whether AI assistants can find, trust, and quote a website — then lists
the fixes in priority order.

Standard library only. No `pip install`, no build step.

---

## Why this isn't just GitHub Pages

GitHub Pages serves static files. It cannot run Python, and browser JavaScript
cannot fetch another site's HTML or `robots.txt` because of CORS. The scan has
to happen server-side.

So the split is:

| Piece | Where it lives |
|---|---|
| Source code | GitHub |
| The scanner (Python) | Render free web service, auto-deployed from GitHub |
| Public website | The same Render URL |
| Optional extra front-end | GitHub Pages (`docs/`), calling the Render API |

---

## Deploy in about ten minutes

### 1. Put the code on GitHub

```bash
cd surfaced-web
git init
git add .
git commit -m "Surfaced: public AI visibility scanner"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/surfaced.git
git push -u origin main
```

### 2. Create the Render service

1. Sign up at [render.com](https://render.com) and connect your GitHub account.
2. **New +** → **Web Service** → pick the `surfaced` repo.
3. Confirm the settings (Render reads `render.yaml`, so these should prefill):
   - Runtime: **Python 3**
   - Build command: leave as is — there's nothing to build
   - Start command: `python3 server.py`
   - Instance type: **Free**
4. **Create Web Service**.

You get a URL like `https://surfaced.onrender.com`. HTTPS is automatic.

### 3. Set your public URL

In Render → **Environment**, add:

```
SURFACED_BASE_URL = https://surfaced.onrender.com
```

This drives the canonical link, Open Graph tags and `llms.txt`. Without it those
tags point at localhost, which costs you points on your own scanner.

Every `git push` to `main` now redeploys automatically.

---

## Known limits of the free tier

- **Cold starts.** Free services sleep after 15 minutes idle; the next request
  takes 30–60 seconds to wake them. Fine for testing, bad for a demo in front of
  a prospect. Upgrade to the paid instance (~$7/mo) before any live demo, or ping
  `/health` on a schedule to keep it warm.
- **Ephemeral disk.** `scan_history.json` is wiped on redeploy, so peer
  benchmarking resets. Attach a Render disk and set `SURFACED_DATA_DIR` to its
  mount path, or move history to a database when you add accounts.
- **750 free instance hours** per workspace per month.

---

## Optional: GitHub Pages front-end

`docs/index.html` is a static page that calls the API. Use it if you want a
separate marketing domain, or a client-branded scanner.

1. Edit `docs/index.html` and set `API_BASE` to your Render URL.
2. GitHub repo → **Settings** → **Pages** → Source: `main` branch, `/docs` folder.
3. It publishes at `https://YOUR-USERNAME.github.io/surfaced/`.

The API sends `Access-Control-Allow-Origin: *`, so this works from any domain.

---

## Routes

| Route | Purpose |
|---|---|
| `/` | Landing page and scan form |
| `/scan?url=` | HTML preview, or the full report when the request has a paid Checkout Session |
| `/api/scan?url=` | Same scan as JSON, CORS open. Preview unless `session_id` is a paid session for that URL |
| `POST /checkout` | Starts Stripe Checkout for one website (payments on only) |
| `/terms`, `/privacy`, `/refunds` | Placeholder pages. Replace them before taking live payments |
| `/health` | Uptime check |
| `/robots.txt`, `/llms.txt`, `/sitemap.xml`, `/og.svg` | Machine-readable metadata |

Both scan routes accept an optional `&vertical=` parameter. With payments on, a paid session is also tied to that business type: omit it on the receipt link and the stored type is used; send a different one and the full report stays locked.

While `SURFACED_PAYMENTS` is off, `/scan` and `/api/scan` still return the full report with no session id. That is the current free behavior.

---

## Vertical-aware scoring

A dentist without a Google Business Profile has a real problem. A B2B SaaS
company without one has nothing wrong at all. Scoring both against the same
checklist made well-optimised software companies look broken, so weighting and
applicable checks now depend on the kind of business.

| Vertical | Website | Reviews | Social | Review signal used |
|---|---|---|---|---|
| `local` | 40% | 40% | 20% | Google Business Profile |
| `services` | 45% | 35% | 20% | Google Business Profile |
| `ecommerce` | 50% | 30% | 20% | Trustpilot, App Store, Google Play |
| `general` | 50% | 25% | 25% | Third-party profiles |
| `saas` | 65% | 12% | 23% | G2, Capterra, TrustRadius |
| `publisher` | 70% | 5% | 25% | Third-party profiles |

The vertical is detected from schema.org types first, then on-page language.
When nothing is conclusive it falls back to `general`, which keeps the original
balanced weighting rather than guessing. The report always states which vertical
was used and what evidence chose it.

High-citation social platforms also vary: LinkedIn, YouTube and Reddit for
software; YouTube, Facebook and Instagram for local businesses; YouTube,
Instagram and TikTok for stores.

Override detection when you already know:

```bash
python3 ai_visibility_studio.py https://example.com --vertical=saas
curl "https://your-app.onrender.com/api/scan?url=example.com&vertical=local"
```

With payments on, that `curl` returns the preview unless you also pass a paid
`session_id` for the same URL. The command-line scanner is unchanged and does
not check Stripe.

Peer benchmarking compares like with like: once at least three sites of the same
vertical have been scanned, comparisons use only those. Below that it falls back
to the whole pool and labels the report accordingly.

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Set by the host automatically |
| `SURFACED_BASE_URL` | `http://localhost:$PORT` | Canonical, OG tags, and Stripe return URLs |
| `SURFACED_DATA_DIR` | repo directory | Where `scan_history.json` lives |
| `SURFACED_RATE_LIMIT` | `12` | Preview scans per IP per hour (full scans, while payments are off) |
| `SURFACED_PAID_RATE_LIMIT` | `30` | Full-report loads per IP per hour, including Stripe verification |
| `SURFACED_CHECKOUT_RATE_LIMIT` | `8` | Checkout sessions started per IP per hour |
| `SURFACED_PAYMENTS` | off | `on`, `true`, `1`, or `yes` to charge. Anything else keeps full reports free |
| `STRIPE_SECRET_KEY` | unset | `sk_test_…` or `sk_live_…`. Required when payments are on. Never commit it |
| `STRIPE_PRICE_ID` | unset | `price_…` from the Stripe Dashboard. Optional; see below |
| `SURFACED_PRICE_CENTS` | `2000` | Price in US cents. `2000` is $20. Must match the Stripe Price |
| `GOOGLE_PLACES_API_KEY` | unset | Enables live Google rating scoring |

There is no `STRIPE_WEBHOOK_SECRET`. Fulfillment does not use a webhook. See below.

---

## Payments

One report is $20 USD, one website per payment, card only, on Stripe Checkout.
The server is still the Python standard library: Checkout is a form POST to
`https://api.stripe.com/v1/checkout/sessions`. No Stripe package.

Payments stay **off** until both of these are true:

- `SURFACED_PAYMENTS` is `on` (also accepts `true`, `1`, `yes`)
- `STRIPE_SECRET_KEY` is an `sk_test_` or `sk_live_` key

If the flag is on but the key, the price in cents, or the price id is unusable,
the process logs the reason and keeps serving full reports for free. Fix the
env and restart. Do not put keys in the repo. `.env` is gitignored for local use.

### What a visitor gets

With payments on:

1. They submit a URL. The server scans it and shows a preview: overall score,
   grade, business type, and the single top fix, plus **Get the full report for $20**.
2. That button POSTs to `/checkout`. The server checks the URL (same SSRF rules
   as a scan), then creates a Checkout Session whose metadata stores the
   canonical URL, the business type, and `product=surfaced-report`.
3. Stripe hosts the card page. Surfaced never sees the card.
4. Stripe sends the browser to `/scan?url=…&session_id={CHECKOUT_SESSION_ID}`.
5. The server **retrieves that session from Stripe**. The redirect is not
   trusted. The full HTML report is returned only when the session is paid,
   complete, USD, exactly `SURFACED_PRICE_CENTS`, in the same mode as the key
   (test key with `livemode: false`, live key with `livemode: true`), and the
   metadata URL matches the page they are opening.
6. `/api/scan` uses the same rule. Without a valid `session_id` it returns the
   preview JSON (`access: "teaser"`) and does not include pillar scores, the
   check list, crawlers, or the other fixes.

The success link is the receipt. Opening it again re-checks Stripe and scans
again. Nothing about the purchase is written to disk, so a Render restart does
not strand a customer who still has the link. The preview has an **I already
paid** field for the `cs_test_…` or `cs_live_…` id from that link.

Canceled Checkout returns to the preview. A session paid for one URL does not
unlock a different URL.

### Why there is no webhook

A webhook cannot hand the customer the report if their browser never returns,
unless the server stores the payment or sends email. The disk on Render is
wiped on restart, and unlocking a URL for every later visitor would let them
skip paying. Card payments are complete when Stripe redirects, and the server
confirms that by reading the Checkout Session. Add a webhook later only if you
start emailing reports or recording payments in a database. Verify its signature
if you do. This version does not.

### Create the Stripe product (test mode first)

1. Open the [Stripe Dashboard](https://dashboard.stripe.com) and turn **Test mode** on.
2. **Product catalog** → **Add product**.
   - Name: `Surfaced full report`
   - Description: one AI visibility report for one website
   - Pricing: **One time**, **USD**, **$20.00**
3. Save, then copy the **Price ID** (`price_…`). The amount must be 2000 cents.
   Do not add a coupon. A discounted total will not match `SURFACED_PRICE_CENTS`,
   and the report will stay locked after a real charge.
4. **Developers** → **API keys** → reveal the **Secret key** (`sk_test_…`).
   Use the secret key, not the publishable key.

Leave `STRIPE_PRICE_ID` unset only if you want Checkout to send an inline
`price_data` charge of `SURFACED_PRICE_CENTS` instead of a Dashboard price.
Prefer a real Price so the payment shows up under that product. When the price
id is set, Checkout charges that price, and the return check still requires
`amount_total` to equal `SURFACED_PRICE_CENTS`.

### Render environment

In the Render service → **Environment**, set:

```
SURFACED_BASE_URL=https://surfaced.patnaiq.com
SURFACED_PAYMENTS=on
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PRICE_ID=price_...
SURFACED_PRICE_CENTS=2000
```

`SURFACED_BASE_URL` must be the public https origin customers use. It is written
into the Checkout success and cancel URLs. Save changes so Render restarts.
Do not deploy from this branch to find out; merging to `main` is what
auto-deploys.

### Test-mode card

With the test key in place:

1. Open the site and run a check. Confirm the page is a preview, not the full
   score breakdown, and that `/api/scan?url=that-site` is preview JSON.
2. Choose **Get the full report for $20**.
3. Pay with `4242 4242 4242 4242`, any future expiry, any CVC, any ZIP.
   More test cards: [Stripe testing docs](https://docs.stripe.com/testing).
4. You should land on the full report. Refresh that URL and it should load
   again. Change the `url` parameter and it should drop back to a preview.
5. Call `/api/scan` with the same `url` and `session_id` and confirm the full
   JSON. Call it without `session_id` and confirm the preview.

No live card is required for that. This repo's tests mock Stripe; they do not
call Stripe and they do not charge a card.

### Go-live checklist

- Terms, Privacy, and Refunds still say they are placeholders. Replace
  `/terms`, `/privacy`, and `/refunds` in `pages.py` with the owner's real
  text before charging live cards. Do not ship invented policy.
- Create a **live** product and a one-time **$20** price. Copy the live `price_…`.
- Swap `STRIPE_SECRET_KEY` to `sk_live_…` and `STRIPE_PRICE_ID` to the live price.
- Confirm `SURFACED_PRICE_CENTS` is `2000` and the live price is exactly $20.00.
- Confirm `SURFACED_BASE_URL` is `https://surfaced.patnaiq.com` (https, no path).
- Run one live $20 payment you are willing to refund from the Dashboard, and
  confirm the receipt link still works after a restart.
- Confirm `/scan` and `/api/scan` without `session_id` do not show pillar
  scores, the crawler table, or the rest of the fixes.
- Keep `SURFACED_PAYMENTS` off until the steps above are done.

Changing `SURFACED_PRICE_CENTS` later invalidates older receipt links, because
the stored charge no longer matches.

### iOS client

Branch `cursor/ios-swiftui-mvp-72cd`
([PR 1](https://github.com/2nnh2gs47g-dotcom/surfaced/pull/1)) is unchanged.
Its client calls `GET /api/scan?url=` and decodes the full report: `url`,
`title`, `checked_at`, `word_count`, `javascript_rendered`, `summary`, `grade`,
`vertical`, `scores` (`overall`, `geo`, `aeo`, `reviews`, `social`), `pillars`,
and `recommendations`. Extra JSON keys are ignored.

- Payments **off**: the response is still that full object. The app keeps working.
- Payments **on**, no `session_id`: the response is the preview object. It will
  not decode. The app shows "The server response was not a Surfaced scan report."
- The app does not send `session_id` and this change does not add a purchase
  flow. Apple in-app purchase rules apply to selling inside the iOS app; that
  is out of scope. Do not put a card checkout in the app.

A later iOS change could decode `access: "teaser"` and, for a report bought on
the website, call `/api/scan` with that `session_id`. That work is not in this
branch.

---

## Security

The scanner fetches URLs that strangers supply, which is a textbook
server-side request forgery risk. `server.py` refuses any address that resolves
to a private, loopback, link-local, reserved or multicast IP, rejects non-HTTP
schemes and non-standard ports, and re-validates **every redirect hop** so an
open redirect can't smuggle a request into your internal network.

It also caps concurrent scans and rate-limits per IP. Preview scans, paid report
loads, and checkout starts each have their own hourly cap, so a receipt link
cannot skip the limit and checkout cannot mint unlimited Stripe sessions. The
Checkout Session id is the credential for that one URL, and the access log
redacts it.

One residual gap: a hostile DNS server could return a public address for the
validation lookup and a private one for the fetch (DNS rebinding). Closing that
needs IP pinning at the socket layer — worth doing before you advertise the tool
widely.

---

## Run locally

```bash
python3 server.py
# http://localhost:8000
```

The original tools still work unchanged:

```bash
python3 ai_visibility_studio.py https://example.com   # one-off CLI scan
python3 prospect_scan.py                              # batch scan urls.txt
```
