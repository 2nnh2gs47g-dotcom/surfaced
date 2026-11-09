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

## The app (iOS / Android, installable)

`/app` is a progressive web app: the same scanner in a phone-shaped interface
that installs to a home screen, runs full screen with no browser chrome, keeps a
local history of recent checks, and opens offline.

**Install on iPhone:** open `https://your-domain/app` in **Safari** (not Chrome)
-> Share -> **Add to Home Screen**. On Android: Chrome -> menu -> **Install app**.

There is no App Store build, and that is deliberate: a native app would need
Xcode, a $99/year Apple Developer account, and review for every change. This
ships with `git push` and updates the moment a user reopens it.

Files: `pwa.py` (app shell, manifest, service worker) and `icon-*.png`.

The app validates the address on the device before it calls the server — no
spaces, no embedded credentials, a host with a real dot in it. A bad address
costs nothing, which matters when a cold start can take a minute. Requests time
out at 90s, a 429 tells the user how long to wait, and every failure that can be
retried offers a Try again button.
The service worker caches the shell only — scans always go to the network, so a
cached result can never be mistaken for a live one.

## Payments (Stripe)

Credit model: a payment grants scan credits, a credit buys one run. The client
is never trusted — credit comes only from a signature-verified Stripe webhook.

### Set up

1. Stripe Dashboard -> **Products** -> create a product, copy its **Price ID**.
2. **Developers -> Webhooks -> Add endpoint**:
   `https://your-domain/api/stripe/webhook`, event `checkout.session.completed`
   (add `invoice.paid` for subscription renewals). Copy the **signing secret**.
3. In Render -> **Environment**:

```
STRIPE_SECRET_KEY              sk_test_...  (switch to sk_live_ when ready)
STRIPE_WEBHOOK_SECRET          whsec_...
STRIPE_PRICE_ID                price_...
SURFACED_CREDITS_PER_PURCHASE  1
SURFACED_DATA_DIR              /var/data     <- must be a persistent disk
```

**The ledger must be on a persistent disk.** It records who paid. On Render's
default ephemeral filesystem every redeploy deletes it and customers lose
credits they paid for. Attach a disk (paid instance types only), mount it at
`/var/data`, and point `SURFACED_DATA_DIR` there. `render.yaml` declares it.

### How exactly-once is enforced

| Where duplication happens | What stops it |
|---|---|
| Stripe delivers webhooks at least once, retrying for up to 3 days | `UNIQUE(stripe_event_id)` — the second INSERT is refused by the database |
| User double-taps Run, or the network retries | `UNIQUE(idempotency_key)` — the replay returns the first run's result |
| Two requests spend the last credit at once | `UPDATE ... WHERE credits > 0` plus a rowcount check — exactly one winner |
| A run fails, or the process dies mid-scan | Credit is reserved, then committed or refunded; `sweep_stale()` recovers orphans on restart |

Each defence is a database constraint, not an `if` statement. Check-then-act has
a race window between the read and the write; a constraint has none.

```bash
python3 test_billing.py     # 28 assertions, incl. 12- and 8-thread races
```

### Paid routes

| Route | Purpose |
|---|---|
| `POST /api/checkout` | Creates a Stripe Checkout Session, returns its URL |
| `POST /api/stripe/webhook` | Stripe's confirmation — the only thing that mints credit |
| `GET /paid?session_id=` | Shows the buyer their scan key, once |
| `GET /api/credits?key=` | Remaining credits |
| `GET /api/scan?...&key=&idempotency=` | A paid run |

## Before you deploy

```bash
python3 test_scoring.py     # 34 scoring regressions (the 9 Nov QA defects)
python3 test_contract.py    # the app/server JSON contract
python3 test_billing.py     # 28 payment guarantees
```

### Scoring defects fixed 9 Nov (from a live QA run)

| Defect | What a customer saw | Fix |
|---|---|---|
| Crawler access | Any `Disallow` (e.g. `/wp-admin/`) scored **0 of 30** and the report claimed "0 of 6 citation crawlers can reach the site" — false on 7 of 17 sites tested | robots.txt is matched against the *scanned path*, per the real spec. `partial` is informational and costs nothing |
| Unreadable pages | An empty or intercepted response still got graded **F**, telling owners to add an H1 they already had | Fewer than 50 words with no title or headings returns an explanation instead of a score |
| Blocked sites | 23% of sites returned an error and no report | Retries once as a browser; if that works, reports the firewall as a High-priority finding |
| Page titles | Every report showed the domain — `<title>` sits in `<head>`, which the parser skipped | Title captured before the skip guard |
| Business type | A dentist with an address and phone scored as "General business" | Street address + phone + practice words detect local without schema |
| Advice wording | Thin static pages were told to "server-render"; Google Maps short links missed; API-key setup notes shown to customers | Each corrected; all covered by `test_scoring.py` |

The app decodes the JSON from `server.result_to_dict`. Rename a key there and
the app breaks silently in a user's hand: the scan succeeds, the screen shows
nothing useful, nothing logs an error. This test fails instead. It also catches
the reverse — the app reading a field the server does not send yet. No network,
runs in under a second.

## Routes

| Route | Purpose |
|---|---|
| `/` | Landing page and scan form |
| `/scan?url=` | Full HTML report |
| `/api/scan?url=` | Same scan as JSON, CORS open |
| `/app` | Installable app (PWA) |
| `/manifest.webmanifest`, `/sw.js`, `/icon-*.png` | App install metadata |
| `/health` | Uptime check |
| `/robots.txt`, `/llms.txt`, `/sitemap.xml`, `/og.svg` | Machine-readable metadata |

Both scan routes accept an optional `&vertical=` parameter.

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

Peer benchmarking compares like with like: once at least three sites of the same
vertical have been scanned, comparisons use only those. Below that it falls back
to the whole pool and labels the report accordingly.

---

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8000` | Set by the host automatically |
| `SURFACED_BASE_URL` | `http://localhost:$PORT` | Canonical and OG tags |
| `SURFACED_DATA_DIR` | repo directory | Where `scan_history.json` lives |
| `SURFACED_RATE_LIMIT` | `12` | Scans per IP per hour |
| `GOOGLE_PLACES_API_KEY` | unset | Enables live Google rating scoring |

---

## Security

The scanner fetches URLs that strangers supply, which is a textbook
server-side request forgery risk. `server.py` refuses any address that resolves
to a private, loopback, link-local, reserved or multicast IP, rejects non-HTTP
schemes and non-standard ports, and re-validates **every redirect hop** so an
open redirect can't smuggle a request into your internal network.

It also caps concurrent scans and rate-limits per IP.

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
