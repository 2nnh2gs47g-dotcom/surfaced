"""
Surfaced — installable app layer (PWA).

Adds /app (the app shell), /manifest.webmanifest, /sw.js and the icons.
Installs to an iPhone home screen from Safari: Share -> Add to Home Screen.
Runs full screen with no browser chrome, works offline, updates on git push.
"""

MANIFEST = """{
  "name": "Surfaced — AI visibility",
  "short_name": "Surfaced",
  "description": "Check whether AI assistants can find, trust and quote any website.",
  "start_url": "/app",
  "scope": "/",
  "display": "standalone",
  "orientation": "portrait",
  "background_color": "#14112e",
  "theme_color": "#14112e",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any" },
    { "src": "/icon-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}"""

# Cache the shell so the app opens instantly and offline; never cache scans.
SERVICE_WORKER = """const CACHE = 'surfaced-v1';
const SHELL = ['/app', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;

  // Scans must always be live — never served from cache.
  if (url.pathname.startsWith('/api/')) {
    e.respondWith(fetch(e.request));
    return;
  }

  // App shell: network first so updates land, cache as the offline fallback.
  e.respondWith(
    fetch(e.request)
      .then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request).then(hit => hit || caches.match('/app')))
  );
});
"""

APP_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover, maximum-scale=1">
<title>Surfaced</title>
<meta name="description" content="Check whether AI assistants can find, trust and quote any website.">
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#14112e">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Surfaced">
<link rel="apple-touch-icon" href="/icon-180.png">
<style>
  :root {
    --void:#14112e; --deep:#1c1740; --violet:#a78bfa; --cyan:#67e8f9;
    --paper:#f7f6fc; --muted:#b6b2d8; --line:#ffffff1f; --rose:#fb7185; --amber:#fbbf24;
    --mono: ui-monospace,"SF Mono",SFMono-Regular,Menlo,monospace;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    --top: env(safe-area-inset-top); --bot: env(safe-area-inset-bottom);
  }
  * { box-sizing:border-box; margin:0; -webkit-tap-highlight-color:transparent; }
  body {
    font:16px/1.55 var(--sans); color:var(--paper); background:var(--void);
    background-image:
      radial-gradient(760px 520px at 85% -10%, #4f46e5 0%, transparent 60%),
      radial-gradient(620px 440px at -10% 105%, #0e7490 0%, transparent 58%);
    background-attachment:fixed;
    min-height:100vh; -webkit-font-smoothing:antialiased;
    padding: calc(var(--top) + 18px) 18px calc(var(--bot) + 28px);
    overscroll-behavior-y:contain;
  }
  header { display:flex; align-items:baseline; justify-content:space-between; margin-bottom:22px; }
  .brand { font:700 14px/1 var(--mono); letter-spacing:.14em; text-transform:uppercase; }
  .brand span { color:var(--cyan); }
  .offline { font:11px var(--mono); color:var(--amber); display:none; }
  body.is-offline .offline { display:block; }

  h1 { font-size:26px; line-height:1.18; letter-spacing:-.02em; margin-bottom:8px; }
  h1 em { font-style:normal; color:var(--cyan); }
  .lede { color:var(--muted); font-size:15px; margin-bottom:20px; }

  form { display:flex; flex-direction:column; gap:10px; }
  .field { background:#ffffff12; border:1px solid var(--line); border-radius:14px; padding:6px; display:flex; }
  .field:focus-within { border-color:#ffffff4d; }
  input, select, button { font-family:inherit; }
  input {
    flex:1; min-width:0; background:transparent; border:0; outline:none;
    color:var(--paper); font-size:17px; padding:12px;
  }
  input::placeholder { color:#8d89b3; }
  select {
    width:100%; background:#1d1940; color:var(--muted); border:1px solid var(--line);
    border-radius:12px; padding:13px 12px; font-size:15px; outline:none; -webkit-appearance:none;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='8'><path d='M1 1l5 5 5-5' stroke='%23b6b2d8' stroke-width='1.6' fill='none'/></svg>");
    background-repeat:no-repeat; background-position:right 14px center;
  }
  button.go {
    border:0; border-radius:12px; padding:15px; font-size:16px; font-weight:700;
    color:var(--void); background:linear-gradient(96deg,var(--violet),var(--cyan));
  }
  button.go:disabled { opacity:.6; }

  #out { margin-top:24px; }
  .msg { border:1px solid var(--line); border-radius:12px; padding:15px; color:var(--muted); font-size:14.5px; }
  .grade { display:flex; align-items:center; gap:14px; margin-bottom:18px; }
  .gbox {
    width:66px; height:66px; flex:none; border-radius:16px; display:grid; place-items:center;
    background:#ffffff14; border:1px solid var(--line);
  }
  .gbox b { font-size:30px; line-height:1; }
  .ghead { font-size:15px; font-weight:600; word-break:break-all; }
  .gsub { font:11.5px var(--mono); color:var(--muted); margin-top:4px; }

  .bars { display:flex; flex-direction:column; gap:11px; }
  .bar b { font:11px var(--mono); letter-spacing:.12em; text-transform:uppercase; color:var(--muted); font-weight:600; }
  .bar .row { display:flex; justify-content:space-between; align-items:baseline; margin-bottom:5px; }
  .bar i { font-style:normal; font-size:14px; font-weight:700; }
  .track { height:7px; border-radius:99px; background:#ffffff14; overflow:hidden; }
  .fill { height:100%; border-radius:99px; }

  h2 { font-size:16px; margin:26px 0 12px; }
  ol { list-style:none; padding:0; counter-reset:f; }
  ol li { position:relative; padding:0 0 16px 32px; counter-increment:f; color:var(--muted); font-size:14.5px; }
  ol li::before { content:counter(f,decimal-leading-zero); position:absolute; left:0; top:1px; font:700 12px var(--mono); color:var(--violet); }
  ol strong { display:block; color:var(--paper); font-weight:600; margin-bottom:2px; }
  .tag { font:600 9.5px var(--mono); letter-spacing:.1em; text-transform:uppercase; border:1px solid; border-radius:99px; padding:2px 7px; margin-left:7px; }
  .High { color:var(--rose); border-color:#fb718555; }
  .Medium { color:var(--amber); border-color:#fbbf2455; }
  .Low { color:#94a3b8; border-color:#94a3b855; }

  .hist { margin-top:30px; border-top:1px solid var(--line); padding-top:18px; }
  .hist h2 { margin-top:0; }
  .hrow {
    display:flex; align-items:center; gap:12px; padding:11px 0;
    border-bottom:1px solid #ffffff0f; font-size:14px; width:100%;
    background:none; border-left:0; border-right:0; border-top:0; color:var(--paper); text-align:left;
  }
  .hrow .hs { font:700 14px var(--mono); width:30px; flex:none; }
  .hrow .hu { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--muted); }
  .clear { margin-top:14px; background:none; border:1px solid var(--line); color:var(--muted); border-radius:10px; padding:9px 14px; font-size:13px; }
  .why { margin-top:14px; font-size:13.5px; color:var(--muted); }
  .weight { font:10.5px var(--mono); color:#8d89b3; margin-top:3px; }
  .retry { margin-top:12px; background:none; border:1px solid var(--line); color:var(--paper);
           border-radius:10px; padding:10px 16px; font-size:14px; }
  .spin { display:inline-block; width:13px; height:13px; border:2px solid #ffffff40; border-top-color:var(--cyan); border-radius:50%; animation:s .7s linear infinite; vertical-align:-2px; margin-right:7px; }
  @keyframes s { to { transform:rotate(360deg); } }
  @media (prefers-reduced-motion:reduce) { .spin { animation:none; } }
</style>
</head>
<body>

<header>
  <div class="brand">Sur<span>faced</span></div>
  <div class="offline">offline</div>
</header>

<h1>Will AI assistants <em>quote</em> this site?</h1>
<p class="lede">Reads any page the way a crawler does, then ranks what to fix.</p>

<form id="f">
  <div class="field">
    <input id="url" type="text" inputmode="url" autocapitalize="off" autocorrect="off"
           spellcheck="false" placeholder="yourwebsite.com" aria-label="Website address">
  </div>
  <select id="vert" aria-label="Business type">
    <option value="">Detect business type</option>
    <option value="local">Local / in-person business</option>
    <option value="services">Professional services firm</option>
    <option value="ecommerce">Online store</option>
    <option value="saas">Software / B2B product</option>
    <option value="publisher">Publisher / content site</option>
    <option value="general">General business</option>
  </select>
  <button class="go" id="go" type="submit">Run the check</button>
</form>

<div id="out" role="status" aria-live="polite"></div>

<div class="hist" id="hist" hidden>
  <h2>Recent checks</h2>
  <div id="hrows"></div>
  <button class="clear" id="clear">Clear history</button>
</div>

<script>
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const KEY = 'surfaced.history';

const hue = v => v >= 80 ? '#67e8f9' : v >= 60 ? '#a78bfa' : v >= 40 ? '#fbbf24' : '#fb7185';

function store(d) {
  try {
    const h = load().filter(x => x.url !== d.url);
    h.unshift({ url: d.url, score: d.scores.overall, grade: d.grade, at: Date.now() });
    localStorage.setItem(KEY, JSON.stringify(h.slice(0, 12)));
  } catch (e) {}
}
function load() {
  try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (e) { return []; }
}
function drawHistory() {
  const h = load(), box = $('#hist');
  if (!h.length) { box.hidden = true; return; }
  box.hidden = false;
  $('#hrows').innerHTML = h.map(r =>
    `<button class="hrow" data-u="${esc(r.url)}">
       <span class="hs" style="color:${hue(r.score)}">${r.score}</span>
       <span class="hu">${esc(r.url.replace(/^https?:\\/\\//, ''))}</span>
       <span class="hs" style="color:#b6b2d8">${esc(r.grade)}</span>
     </button>`).join('');
}

// Catch bad addresses before spending a network round trip on them — on a
// cold-started instance that round trip can cost the user a full minute.
function normalizeUrl(raw) {
  const t = String(raw).trim();
  if (!t) throw new Error('Enter a website address to check.');
  if (/\\s/.test(t)) throw new Error('The website address cannot contain spaces.');
  const withScheme = t.includes('://') ? t : 'https://' + t;
  let u;
  try { u = new URL(withScheme); } catch (e) { throw new Error('Enter a website address like example.com.'); }
  if (u.protocol !== 'https:' && u.protocol !== 'http:')
    throw new Error('Only http and https addresses can be checked.');
  if (u.username || u.password)
    throw new Error('Remove the username and password from the address.');
  const h = u.hostname.toLowerCase();
  if (!h.includes('.') || h.startsWith('.') || h.endsWith('.') || h.includes('..'))
    throw new Error('Enter a website address like example.com.');
  return u.href;
}

function bar(label, v) {
  return `<div class="bar">
    <div class="row"><b>${label}</b><i style="color:${hue(v)}">${v}</i></div>
    <div class="track" role="img" aria-label="${label.replace(/&amp;/g,'and')}: ${v} out of 100">
      <div class="fill" style="width:${v}%;background:${hue(v)}"></div></div>
  </div>`;
}

function render(d) {
  const s = d.scores, v = d.vertical || {};
  const fixes = (d.recommendations || []).slice(0, 6).map(r =>
    `<li><strong>${esc(r.label)}<span class="tag ${esc(r.priority)}">${esc(r.priority)}</span></strong>${esc(r.fix)}</li>`
  ).join('');

  $('#out').innerHTML = `
    <div class="grade">
      <div class="gbox" role="img" aria-label="Overall score ${s.overall} out of 100, grade ${esc(d.grade)}"><b style="color:${hue(s.overall)}">${s.overall}</b></div>
      <div>
        <div class="ghead">${esc(d.url.replace(/^https?:\\/\\//, ''))}</div>
        <div class="gsub">grade ${esc(d.grade)} &middot; ${esc(v.label || '')}</div>
        ${v.weighting ? `<div class="weight">${esc(v.weighting)}</div>` : ''}
      </div>
    </div>
    <div class="bars">
      ${bar('GEO — found &amp; trusted', s.geo)}
      ${bar('AEO — shaped as answers', s.aeo)}
      ${bar('Reviews — proof', s.reviews)}
      ${bar('Social — footprint', s.social)}
    </div>
    ${d.javascript_rendered ? '<p class="msg" style="margin-top:16px">Most of this page is built by JavaScript, so a crawler sees far less than a visitor does.</p>' : ''}
    ${d.summary ? `<p class="why">${esc(d.summary)}</p>` : ''}
    ${fixes ? `<h2>Fix these first</h2><ol>${fixes}</ol>` : ''}
    <p class="gsub">${d.word_count.toLocaleString()} words visible to crawlers${
      v.detected_from ? ' &middot; business type ' + esc(v.detected_from) : ''}</p>`;
}

let lastAttempt = null;

function fail(message, canRetry) {
  $('#out').innerHTML = `<p class="msg">${esc(message)}</p>` +
    (canRetry ? '<button class="retry" id="retry">Try again</button>' : '');
}

// A cold-started free instance can take about a minute to answer, so the
// request is given 90s before it is called a failure.
const TIMEOUT_MS = 90000;

async function scan(url, vertical) {
  let target;
  try { target = normalizeUrl(url); }
  catch (e) { lastAttempt = null; fail(e.message, false); return; }

  lastAttempt = { url, vertical };
  const go = $('#go');
  go.disabled = true; go.textContent = 'Checking\u2026';
  $('#out').innerHTML = '<p class="msg"><span class="spin"></span>Fetching the page the way an AI crawler would. ' +
    'The first check after a quiet spell can take up to a minute while the server wakes up.</p>';

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort('timeout'), TIMEOUT_MS);

  try {
    const q = `/api/scan?url=${encodeURIComponent(target)}` +
              (vertical ? `&vertical=${encodeURIComponent(vertical)}` : '');
    const res = await fetch(q, { signal: ctrl.signal, headers: { 'Accept': 'application/json' } });

    let d = null;
    try { d = await res.json(); } catch (e) { /* handled below */ }

    if (!res.ok) {
      if (res.status === 429) {
        const secs = (d && d.retry_after_seconds) || 0;
        const mins = Math.max(1, Math.ceil(secs / 60));
        fail(`You have used your free checks for this hour. Try again in about ${mins} minute${mins === 1 ? '' : 's'}.`, false);
      } else if (res.status >= 500) {
        fail('The server could not complete the scan. Try again in a moment.', true);
      } else {
        fail((d && d.error) || `That page could not be checked (HTTP ${res.status}).`, false);
      }
      return;
    }
    if (!d || !d.scores) { fail('The server response was not a scan report.', true); return; }

    render(d); store(d); drawHistory();
  } catch (e) {
    if (!navigator.onLine) {
      fail('You are offline. Reconnect and run the check again.', true);
    } else if (ctrl.signal.aborted) {
      fail('The scan timed out before the server answered. It may still be waking up — try again.', true);
    } else {
      fail('The scanner could not be reached. Check your connection and try again.', true);
    }
  } finally {
    clearTimeout(timer);
    go.disabled = false; go.textContent = 'Run the check';
  }
}

$('#out').addEventListener('click', e => {
  if (e.target.id === 'retry' && lastAttempt) scan(lastAttempt.url, lastAttempt.vertical);
});

$('#f').addEventListener('submit', e => {
  e.preventDefault();
  $('#url').blur();
  scan($('#url').value, $('#vert').value);
});
$('#hrows').addEventListener('click', e => {
  const b = e.target.closest('.hrow');
  if (b) { $('#url').value = b.dataset.u; scan(b.dataset.u, $('#vert').value); window.scrollTo({ top: 0, behavior: 'smooth' }); }
});
$('#clear').addEventListener('click', () => { try { localStorage.removeItem(KEY); } catch (e) {} drawHistory(); });

const net = () => document.body.classList.toggle('is-offline', !navigator.onLine);
addEventListener('online', net); addEventListener('offline', net); net();
drawHistory();

if ('serviceWorker' in navigator) {
  addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
}
</script>
</body>
</html>"""
