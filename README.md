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
| `/scan?url=` | Full HTML report |
| `/api/scan?url=` | Same scan as JSON, CORS open |
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
