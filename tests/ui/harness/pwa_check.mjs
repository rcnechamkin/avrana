// Browser checks for Home's first-party page script and service worker (MK-3, AVR-717), run in Chromium against the
// avrana-home dev stack. Development tool: loopback only, synthetic identities, never run against production.
// Normally started by pwa_run.py (which picks the ports and finds the interpreter):
//   PLAYWRIGHT_FROM=<tooling folder> node tests/ui/harness/pwa_check.mjs --tree REPO --python PYTHON --port P --mock-port M
// It starts and stops the dev stack itself, because some checks need the server gone (offline), restarted with a
// changed worker (update banner) or restarted with HOME_PWA_SW=off (kill switch). The update check runs a second
// stack from a temporary COPY of services/avrana-home whose worker has one extra comment; the repository is not touched.
import { createRequire } from 'node:module';
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const from = path.resolve(process.env.PLAYWRIGHT_FROM || '.');
const require = createRequire(path.join(from, 'x.js'));
const { chromium, request: pwRequest } = require('@playwright/test');
const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const TREE = path.resolve(opt('--tree', '.'));
const PYTHON = opt('--python', 'python');
const PORT = Number(opt('--port', '8096'));
const MOCK = Number(opt('--mock-port', '18096'));
const BASE = `http://127.0.0.1:${PORT}`;
const COOKIE = { name: 'avrana_dev_identity', value: 'member-a', url: BASE };
const HEADERS = { Cookie: 'avrana_dev_identity=member-a' };

const results = [];
const ok = (name, cond, extra = '') => { results.push(!!cond); console.log(cond ? 'PASS' : 'FAIL', name, cond && !process.env.PWA_VERBOSE ? '' : String(extra).slice(0, 220)); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let server = null;
async function start(tree, env = {}) {
  // On POSIX stop() only sends SIGTERM and returns; if the old server still answers /healthz, the loop below would
  // return at once and the next page load would hit a closed port. Wait for it to go first (Windows kills synchronously).
  await gone();
  server = spawn(PYTHON, ['-B', 'services/avrana-home/dev/run_dev.py', '--dev-identity', '--port', String(PORT), '--mock-port', String(MOCK)],
    { cwd: tree, env: { ...process.env, ...env }, stdio: 'ignore' });
  for (let i = 0; i < 120; i++) {
    try { if ((await fetch(BASE + '/healthz')).ok) return; } catch { /* not yet */ }
    await sleep(250);
  }
  throw new Error('dev stack did not start');
}
function stop() {
  if (!server) return;
  try {
    if (process.platform === 'win32') execFileSync('taskkill', ['/PID', String(server.pid), '/T', '/F'], { stdio: 'ignore' });
    else server.kill('SIGTERM');
  } catch { /* already gone */ }
  server = null;
}
const gone = async () => { for (let i = 0; i < 40; i++) { try { await fetch(BASE + '/healthz'); await sleep(250); } catch { return; } } };

// A document that carries the lens contract markup and the real page script (MK-2 builds the real markup).
const lensDoc = (script, tabs, at = 0) => `<!doctype html><html><head><meta charset="utf-8"><script src="${script}" defer></script></head><body>
  <nav class="tabbar" aria-label="Sections" data-at="${at}">${tabs.map((t, i) => `<a class="tab" href="${t}"${i === at ? ' aria-current="page"' : ''}>Tab ${i}</a>`).join('')}<span class="lens" aria-hidden="true"></span></nav></body></html>`;

const tmpDirs = [];
const tmpDir = (prefix) => { const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix)); tmpDirs.push(d); return d; };
const profile = tmpDir('avr-pwa-');
const copyRoot = tmpDir('avr-pwa-copy-');
let ctx = null; let ctx2 = null; let lb = null; let jb = null;
try {
  await start(TREE);
  ctx = await chromium.launchPersistentContext(profile, { headless: true, viewport: { width: 390, height: 800 } });
  await ctx.addCookies([COOKIE]);
  const page = ctx.pages()[0] || await ctx.newPage();
  const consoleErrors = [];
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  page.on('pageerror', (e) => consoleErrors.push(String(e)));

  // ---- shell page, script tag, CSP, worker registers, what the worker stores --------------------------------
  const resp = await page.goto(BASE + '/');
  const csp = resp.headers()['content-security-policy'];
  ok('shell CSP has script-src and worker-src', /script-src 'self'; worker-src 'self'/.test(csp), csp);
  const scriptSrc = await page.evaluate(() => [...document.scripts].map((s) => s.getAttribute('src')));
  ok('exactly one script, at the versioned path', scriptSrc.length === 1 && /^\/static\/home\.[0-9a-f]{12}\.js$/.test(scriptSrc[0]), JSON.stringify(scriptSrc));
  const scope = await page.evaluate(async () => (await navigator.serviceWorker.ready).scope);
  ok('worker registered with scope /', scope === BASE + '/', scope);
  await sleep(500);
  const reg = await page.evaluate(async () => { const r = await navigator.serviceWorker.getRegistration(); return { active: !!r.active, via: r.updateViaCache, url: r.active && r.active.scriptURL }; });
  ok('worker active at /sw.js, updateViaCache none', reg.active && reg.via === 'none' && reg.url === BASE + '/sw.js', JSON.stringify(reg));
  const dump = () => page.evaluate(async () => { const o = {}; for (const k of await caches.keys()) o[k] = (await (await caches.open(k)).keys()).map((r) => new URL(r.url).pathname); return o; });
  const swText = await (await fetch(BASE + '/sw.js', { headers: HEADERS })).text();
  const allow = Object.keys(JSON.parse(swText.match(/const ALLOW = (\{[\s\S]*?\});/)[1]));
  let d = await dump();
  const names = Object.keys(d);
  ok('one cache, named avrana-shell-*, holding exactly the allow-list', names.length === 1 && /^avrana-shell-[0-9a-f]{12}$/.test(names[0]) && JSON.stringify([...d[names[0]]].sort()) === JSON.stringify([...allow].sort()), JSON.stringify(d));
  const artSeen = [];                                                  // member artwork the page asked for: it must never end up in the store
  page.on('request', (r) => { if (new URL(r.url()).pathname.startsWith('/art/')) artSeen.push(r.url()); });
  for (const p of ['/account', '/search?q=Film', '/help', '/watch', '/home.json', '/']) await page.goto(BASE + p);
  await page.reload();
  d = await dump();
  ok('browsing member pages (with their artwork) stores nothing new; no artwork or page is in the store', artSeen.length > 0 && Object.keys(d).length === 1 && d[names[0]].length === allow.length && Object.values(d).flat().every((p) => !p.startsWith('/art')), `art requests: ${artSeen.length} ${JSON.stringify(d)}`);
  const offlineCached = await page.evaluate(async () => (await (await caches.open((await caches.keys())[0])).match('/offline')).text());
  ok('stored offline page has the approved words and no member places or account menu',
    offlineCached.includes('This phone has no connection. Avrana Media needs one to show your libraries.') && !offlineCached.includes('class="places"') && !offlineCached.includes('<details') && !offlineCached.includes('DEVELOPMENT IDENTITY'));

  // ---- sign-out hop headers -----------------------------------------------------------------------------------
  const api = await pwRequest.newContext({ baseURL: BASE, extraHTTPHeaders: HEADERS });
  const so = await api.get('/signout', { maxRedirects: 0 });
  ok('/signout is a 303 to the outpost with Clear-Site-Data "cache", "storage"', so.status() === 303 && so.headers().location === '/outpost.goauthentik.io/sign_out' && so.headers()['clear-site-data'] === '"cache", "storage"', JSON.stringify(so.headers()));
  const sw = await api.get('/sw.js');
  ok('/sw.js CSP has connect-src and no Service-Worker-Allowed', /connect-src 'self'/.test(sw.headers()['content-security-policy']) && !('service-worker-allowed' in sw.headers()));

  // ---- lens (no service worker in this context, so route() can serve the contract markup) -------------------
  lb = await chromium.launch({ headless: true });
  const lc = await lb.newContext({ serviceWorkers: 'block', viewport: { width: 390, height: 800 } });
  await lc.addCookies([COOKIE]);
  const lp = await lc.newPage();
  const lensErrors = [];                  // anything the script throws or logs as an error on these pages
  lp.on('console', (m) => { if (m.type() === 'error') lensErrors.push(m.text()); });
  lp.on('pageerror', (e) => lensErrors.push(String(e)));
  const tabs4 = ['/', '/watch', '/search', '/account'];
  const tabs2 = ['/', '/search'];
  let doc = lensDoc(scriptSrc[0], tabs4);
  await lp.route('**/lens-test', (route) => route.fulfill({ contentType: 'text/html', body: doc }));
  const at = () => lp.getAttribute('nav.tabbar', 'data-at');
  // this listener is added AFTER the script's, so it sees data-at already set, records whether the script prevented the click, and stops the navigation
  const observe = () => lp.evaluate(() => document.querySelector('nav.tabbar').addEventListener('click', (e) => { window.__seen = { at: document.querySelector('nav.tabbar').dataset.at, prevented: e.defaultPrevented }; e.preventDefault(); }));
  for (const [label, tabs] of [['4 tabs', tabs4], ['2 tabs', tabs2]]) {
    doc = lensDoc(scriptSrc[0], tabs);
    await lp.goto(BASE + '/lens-test');
    await observe();
    const last = tabs.length - 1;
    await lp.click(`a.tab >> nth=${last}`);
    let seen = await lp.evaluate(() => window.__seen);
    ok(`lens, ${label}: clicking the last tab sets data-at to ${last} and the script does not prevent the click`, seen.at === String(last) && seen.prevented === false, JSON.stringify(seen));
    if (tabs.length === 4) {
      await lp.click('a.tab >> nth=1');
      ok('lens, 4 tabs: a second click moves data-at to its own index', (await at()) === '1');
    }
    await lp.click(`a.tab >> nth=${last}`, { modifiers: ['Control'] });
    await lp.click('a.tab >> nth=0');                                   // the current tab
    ok(`lens, ${label}: ctrl-click and the current tab leave data-at alone`, (await at()) === (tabs.length === 4 ? '1' : String(last)));
    // leaving the page puts the printed value back (the page kept in the back/forward cache shows the right tab)
    await lp.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true })));
    ok(`lens, ${label}: pagehide restores the server-printed data-at`, (await at()) === '0');
  }
  doc = lensDoc(scriptSrc[0], tabs4);
  await lp.goto(BASE + '/lens-test');
  await observe();
  await lp.emulateMedia({ reducedMotion: 'reduce' });                  // changed AFTER load: read at the click
  await lp.click('a.tab >> nth=2');
  ok('lens: prefers-reduced-motion is read at the click (set after load)', (await at()) === '0');
  await lp.emulateMedia({ reducedMotion: 'no-preference' });
  await lp.click('a.tab >> nth=2');
  ok('lens: and back to no-preference works without a reload', (await at()) === '2');
  // A tab whose URL differs from the document's only by the hash (MK-2's Library tab is "/#h-new" until MK-5) is a
  // same-document jump: the page stays, aria-current stays on Home, so the lens must stay on the printed tab.
  const homeTabs = ['/', '/#h-new', '/?x=1', '/search'];
  await lp.route(BASE + '/', (route) => route.fulfill({ contentType: 'text/html', body: lensDoc(scriptSrc[0], homeTabs) }));
  await lp.goto(BASE + '/');
  await lp.evaluate(() => { window.__m = 1; });
  await lp.click('a.tab >> nth=1');
  ok('lens: a hash-only tab on the same page ("/#h-new" on "/") leaves data-at on the printed tab', (await at()) === '0' && lp.url() === BASE + '/#h-new' && (await lp.evaluate(() => window.__m)) === 1, `${await at()} ${lp.url()}`);
  await observe();
  await lp.click('a.tab >> nth=2');
  ok('lens: the same path with a different query ("/?x=1") does move the lens', (await at()) === '2');
  await lp.click('a.tab >> nth=3');
  ok('lens: and a different path still moves it', (await at()) === '3');
  await lp.unroute(BASE + '/');
  await lp.goto(BASE + '/lens-test');
  await Promise.all([lp.waitForURL(BASE + '/account'), lp.click('a.tab >> nth=3')]);
  ok('lens: a real click still navigates (never prevented)', lp.url() === BASE + '/account');
  await lp.goto(BASE + '/account');                                    // a real shell page: the script is there, the tab bar is not (MK-2)
  await sleep(500);
  ok('a shell page with no tab bar loads the script and nothing throws or logs an error',
    (await lp.evaluate(() => [document.scripts.length, document.querySelector('nav.tabbar')])).join() === '1,' && lensErrors.length === 0, lensErrors.join(' | '));
  await lb.close(); lb = null;

  // ---- pageshow reload only when persisted --------------------------------------------------------------------------
  await page.goto(BASE + '/account');
  await page.evaluate(() => { window.__m = 1; });
  await Promise.all([page.waitForNavigation({ timeout: 8000 }), page.evaluate(() => { window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })); }).catch(() => null)]).catch(() => null);
  await sleep(500);
  ok('pageshow with persisted=true reloads the page', (await page.evaluate(() => window.__m)) === undefined);
  await page.goto(BASE + '/account');
  await page.evaluate(() => { window.__m = 1; window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: false })); });
  await sleep(1500);
  ok('pageshow with persisted=false does nothing', (await page.evaluate(() => window.__m)) === 1);
  ok('no console errors so far', consoleErrors.length === 0, consoleErrors.join(' | '));

  // ---- a navigation that is answered is never the offline page --------------------------------------------------------
  await page.goto(BASE + '/nope');
  ok('a 404 navigation shows the 404 page, not the offline page', /does not exist/.test(await page.innerText('body')) && !/no connection/.test(await page.innerText('body')));

  // ---- OFFLINE: only when the network itself fails --------------------------------------------------------------------
  stop();
  await gone();
  await page.goto(BASE + '/watch');
  const off = await page.innerText('body');
  ok('server down: a navigation shows the offline page', off.includes('This phone has no connection. Avrana Media needs one to show your libraries.'), off.slice(0, 160));
  ok('offline page: Try again links to / and nothing is member-specific', await page.evaluate(() => !![...document.querySelectorAll('a')].find((a) => a.textContent.trim() === 'Try again' && a.getAttribute('href') === '/')) && !/Member A|Account|Continue/.test(off), off);
  // shell-styled: the page's text uses the family its own inlined @font-face declares (whichever font the brand ships),
  // and that font file loaded from the store while the server is down
  const font = await page.evaluate(async () => {
    const face = [...document.styleSheets].flatMap((s) => [...s.cssRules]).find((r) => r instanceof CSSFontFaceRule);
    const declared = face ? face.style.fontFamily.replace(/["']/g, '').trim() : null;
    const used = getComputedStyle(document.querySelector('p.note')).fontFamily.split(',')[0].replace(/["']/g, '').trim();
    await document.fonts.ready;
    return { declared, used, loaded: [...document.fonts].some((f) => f.status === 'loaded' && f.family.replace(/["']/g, '') === declared) };
  });
  ok('offline page is shell-styled: text in the declared brand font, loaded with the server down', !!font.declared && font.used === font.declared && font.loaded, JSON.stringify(font));
  // (the offline page's CSP has no connect-src, so test with images, which img-src 'self' allows)
  const loads = (src) => page.evaluate((s) => new Promise((resolve) => { const i = new Image(); i.onload = () => resolve('loaded ' + i.naturalWidth); i.onerror = () => resolve('error'); i.src = s; }), src);
  ok('offline: an allow-listed icon still loads from the store', (await loads('/icons/avrana-192.png')) === 'loaded 192');

  // ---- UPDATE: a changed worker waits, the banner offers it, Reload swaps it ------------------------------------------------
  fs.cpSync(path.join(TREE, 'services/avrana-home'), path.join(copyRoot, 'services/avrana-home'), { recursive: true, filter: (s) => !/__pycache__|\.pyc$/.test(s) });
  fs.mkdirSync(path.join(copyRoot, 'services/avrana-portal'), { recursive: true });
  fs.copyFileSync(path.join(TREE, 'services/avrana-portal/portal.py'), path.join(copyRoot, 'services/avrana-portal/portal.py'));
  const copySw = path.join(copyRoot, 'services/avrana-home/avrana_home/app/assets/sw.js');
  fs.writeFileSync(copySw, fs.readFileSync(copySw, 'utf8') + '\n/* changed for the update check */\n');
  await start(copyRoot);
  await page.goto(BASE + '/');
  await page.evaluate(async () => (await navigator.serviceWorker.getRegistration()).update());
  await page.waitForSelector('.update-banner', { timeout: 15000 });
  await page.waitForFunction(() => document.querySelector('.update-banner-text')?.textContent.length > 0, null, { timeout: 5000 });
  const banner = await page.evaluate(() => { const b = document.querySelector('.update-banner'); return { kids: [...b.children].map((c) => c.tagName + '.' + c.className), role: b.querySelector('.update-banner-text').getAttribute('role'), text: b.querySelector('.update-banner-text').textContent, button: b.querySelector('button.update-banner-button')?.textContent, parent: b.parentElement.tagName }; });
  ok('update banner: markup and words (live region set after insertion)', banner.kids.join() === 'SPAN.update-banner-text,BUTTON.update-banner-button' && banner.role === 'status' && /new version/i.test(banner.text) && banner.button === 'Reload' && banner.parent === 'BODY', JSON.stringify(banner));
  const oldNames = Object.keys(await dump());
  await Promise.all([page.waitForNavigation({ timeout: 15000 }), page.click('.update-banner-button')]);
  await sleep(1500);
  const newNames = Object.keys(await dump());
  ok('after Reload the new worker owns a new cache and the old one is gone', newNames.length === 1 && newNames[0] !== oldNames[0], `${oldNames} -> ${newNames}`);
  ok('banner is gone after the reload', (await page.$('.update-banner')) === null);

  // ---- SIGN-OUT through a controlled page: the hop is a real navigation, and the device is cleared --------------------------
  await page.goto(BASE + '/account');
  const controlled = await page.evaluate(() => !!navigator.serviceWorker.controller);
  await Promise.all([page.waitForURL(/outpost\.goauthentik\.io\/sign_out/, { timeout: 15000 }), page.click('a[href="/signout"]')]);
  await sleep(1000);
  const cleared = await page.evaluate(async () => ({ regs: (await navigator.serviceWorker.getRegistrations()).length, caches: (await caches.keys()).length }));
  ok(`sign-out from a ${controlled ? 'worker-controlled' : 'uncontrolled'} page ends at the outpost path with the worker and caches cleared (Clear-Site-Data on the 303)`, cleared.regs === 0 && cleared.caches === 0, JSON.stringify(cleared));
  await ctx.close(); ctx = null;
  stop();

  // ---- KILL SWITCH --------------------------------------------------------------------------------------------------------------
  await start(TREE);
  ctx2 = await chromium.launchPersistentContext(tmpDir('avr-pwa-k-'), { headless: true });
  await ctx2.addCookies([COOKIE]);
  const kp = ctx2.pages()[0] || await ctx2.newPage();
  await kp.goto(BASE + '/');
  await kp.evaluate(async () => (await navigator.serviceWorker.ready).scope);
  stop();
  await start(TREE, { HOME_PWA_SW: 'off' });
  await kp.goto(BASE + '/');
  await sleep(2500);
  const killed = await kp.evaluate(async () => ({ regs: (await navigator.serviceWorker.getRegistrations()).length, caches: (await caches.keys()).length, tag: document.querySelector('script[src]').getAttribute('data-sw') }));
  ok('kill switch: script tag says data-sw=off, the page script unregisters the worker and clears its caches', killed.tag === 'off' && killed.regs === 0 && killed.caches === 0, JSON.stringify(killed));
  const killedSw = await (await fetch(BASE + '/sw.js', { headers: HEADERS })).text();
  ok('kill switch: /sw.js is the self-destruct worker', /registration\.unregister\(\)/.test(killedSw) && !/addEventListener\('fetch'/.test(killedSw));
  await ctx2.close(); ctx2 = null;
  stop();
  // the worker alone, on a page that has no script, removes itself
  await start(TREE);
  ctx2 = await chromium.launchPersistentContext(tmpDir('avr-pwa-k2-'), { headless: true });
  await ctx2.addCookies([COOKIE]);
  const kp2 = ctx2.pages()[0] || await ctx2.newPage();
  await kp2.goto(BASE + '/');
  await kp2.evaluate(async () => (await navigator.serviceWorker.ready).scope);
  stop();
  await start(TREE, { HOME_PWA_SW: 'off' });
  await kp2.goto(BASE + '/healthz');                                    // a page without the script
  // update() may reject because the registration removes itself while the update runs: that is the point
  await kp2.evaluate(async () => { try { await (await navigator.serviceWorker.getRegistration()).update(); } catch (e) { /* removed itself */ } });
  let alone = { regs: -1, caches: -1 };
  for (let i = 0; i < 12 && !(alone.regs === 0 && alone.caches === 0); i++) {      // poll: the update runs in the browser's own time
    await sleep(1000);
    alone = await kp2.evaluate(async () => ({ regs: (await navigator.serviceWorker.getRegistrations()).length, caches: (await caches.keys()).length }));
  }
  ok('kill switch: the self-destruct worker alone unregisters and clears caches', alone.regs === 0 && alone.caches === 0, JSON.stringify(alone));
  await ctx2.close(); ctx2 = null;
  stop();

  // ---- JavaScript off --------------------------------------------------------------------------------------------------------------
  await start(TREE);
  jb = await chromium.launch({ headless: true });
  const nj = await jb.newContext({ javaScriptEnabled: false, serviceWorkers: 'block' });
  await nj.addCookies([COOKIE]);
  const jp = await nj.newPage();
  for (const p of ['/', '/account', '/search?q=Film', '/help']) {
    const r = await jp.goto(BASE + p);
    ok(`JS off: ${p} renders`, r.status() === 200 && (await jp.innerText('body')).length > 50);
  }
  await jp.goto(BASE + '/account');
  ok('JS off: Sign out links to /signout', (await jp.$$eval('a', (as) => as.map((a) => a.getAttribute('href')))).includes('/signout'));
  await Promise.all([jp.waitForURL(/outpost\.goauthentik\.io\/sign_out/, { timeout: 15000 }), jp.click('a[href="/signout"]')]);
  ok('JS off: Sign out follows the hop to the outpost path', /outpost\.goauthentik\.io\/sign_out$/.test(jp.url()), jp.url());
  await jb.close(); jb = null;
} catch (e) {
  console.log('ERROR', e);
  results.push(false);
} finally {
  for (const c of [ctx, ctx2, lb, jb]) { try { if (c) await c.close(); } catch { /* */ } }
  stop();
  for (const dir of tmpDirs) { try { fs.rmSync(dir, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch { /* */ } }
  const failed = results.filter((r) => !r).length;
  console.log(`\nbrowser checks: ${results.length - failed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}
