// Browser checks for Home's page-to-page motion (MK-6, AVR-720), run in Chromium against the avrana-home dev stack.
// Development tool: loopback only, synthetic identities, never run against production. Normally started by
// motion_run.py (which picks the ports and finds the interpreter):
//   PLAYWRIGHT_FROM=<tooling folder> node tests/ui/harness/motion_check.mjs --tree REPO --python PYTHON --port P --mock-port M
// It starts and stops the dev stack itself (a second time with HOME_MOTION_PROPOSAL=on for the Proposal check).
//
// How a cross-document view transition is seen: an init script (test code, not the page's) listens for the browser's
// `pageswap` (old page) and `pagereveal` (new page) events. Both carry `viewTransition` only when a transition runs.
// On the new page it waits for `viewTransition.ready` (which rejects if, for example, two elements share a name) and
// lists the transition's animations (`document.getAnimations()` on the ::view-transition-* pseudo-elements). On the old
// page a second listener, added after the page script's, records every element that carries a view-transition-name
// at the moment of capture. Results cross the navigation in this test's sessionStorage (the page script uses none).
import { createRequire } from 'node:module';
import { spawn, execFileSync } from 'node:child_process';
import path from 'node:path';

const from = path.resolve(process.env.PLAYWRIGHT_FROM || '.');
const require = createRequire(path.join(from, 'x.js'));
const { chromium } = require('@playwright/test');
const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const TREE = path.resolve(opt('--tree', '.'));
const PYTHON = opt('--python', 'python');
const PORT = Number(opt('--port', '8097'));
const MOCK = Number(opt('--mock-port', '18097'));
const BASE = `http://127.0.0.1:${PORT}`;

const results = [];
const ok = (name, cond, extra = '') => { results.push(!!cond); console.log(cond ? 'PASS' : 'FAIL', name, cond && !process.env.MOTION_VERBOSE ? '' : String(extra).slice(0, 400)); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let server = null;
const gone = async () => { for (let i = 0; i < 40; i++) { try { await fetch(BASE + '/healthz'); await sleep(250); } catch { return; } } };
async function start(env = {}) {
  await gone();
  server = spawn(PYTHON, ['-B', 'services/avrana-home/dev/run_dev.py', '--dev-identity', '--port', String(PORT), '--mock-port', String(MOCK)],
    { cwd: TREE, env: { ...process.env, ...env }, stdio: 'ignore' });
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

// Test instrumentation, injected before any page script (Playwright init scripts are not subject to the page's CSP).
function probe() {
  const put = (k, v) => { try { sessionStorage.setItem('mk6-' + k, JSON.stringify(v)); } catch { /* */ } };
  const named = () => {
    const out = {};
    for (const el of document.querySelectorAll('*')) {
      const n = getComputedStyle(el).viewTransitionName;
      if (n && n !== 'none' && n !== 'root') (out[n] = out[n] || []).push(el.className || el.tagName);   // root: the browser's own
    }
    return out;
  };
  addEventListener('pagereveal', (e) => {
    const rec = { at: location.pathname, vt: !!e.viewTransition, ready: null, anims: [], named: named() };
    put('reveal', rec);
    if (!e.viewTransition) return;
    // the interruption checks hold the transition still (paused at its first frame), so it is certainly running
    const hold = sessionStorage.getItem('mk6-hold') === '1';
    e.viewTransition.ready.then(() => {
      if (hold) document.getAnimations().forEach((a) => a.pause());
      rec.ready = 'ok';
      rec.anims = document.getAnimations().filter((a) => a.effect && String(a.effect.pseudoElement).startsWith('::view-transition'))
        .map((a) => ({ pe: a.effect.pseudoElement, ms: Number(a.effect.getTiming().duration) }));
      put('reveal', rec);
    }, (err) => { rec.ready = 'rejected: ' + err; put('reveal', rec); });
    e.viewTransition.finished.then(() => { rec.finished = true; put('reveal', rec); }, () => { rec.finished = 'rejected'; put('reveal', rec); });
  });
  // Added at DOMContentLoaded, so after the page script's own pageswap listener (defer scripts run before it).
  addEventListener('DOMContentLoaded', () => {
    addEventListener('pageswap', (e) => { put('swap', { at: location.pathname, vt: !!e.viewTransition, named: named() }); });
  });
}

async function context(browser, reducedMotion) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion, serviceWorkers: 'block' });
  await ctx.addCookies([{ name: 'avrana_dev_identity', value: 'member-a', url: BASE }]);
  await ctx.addInitScript(probe);
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  return { ctx, page, errors };
}
const read = (page, k) => page.evaluate((key) => JSON.parse(sessionStorage.getItem('mk6-' + key) || 'null'), k);
const clear = (page) => page.evaluate(() => { for (const k of ['swap', 'reveal']) sessionStorage.removeItem('mk6-' + k); });
async function settle(page, test = (r) => r && (r.vt === false || r.finished !== undefined)) {
  for (let i = 0; i < 40; i++) { const r = await read(page, 'reveal'); if (test(r)) return r; await sleep(100); }
  return read(page, 'reveal');
}
const unique = (named) => Object.values(named || {}).every((els) => els.length === 1);
const has = (rec, pe) => !!rec && rec.anims.some((a) => a.pe === pe);

let browser = null;
try {
  await start();
  browser = await chromium.launch({ headless: true });

  // ---- no-preference: Home -> title page through the hero's Details ---------------------------------------------
  let { ctx, page, errors } = await context(browser, 'no-preference');
  await page.goto(BASE + '/');
  await sleep(300);
  ok('Home with no-preference: the shell names only the lens before any navigation (art is named only while leaving)',
    JSON.stringify(await page.evaluate(() => Object.fromEntries([...document.querySelectorAll('*')].map((el) => [el.className, getComputedStyle(el).viewTransitionName]).filter(([, n]) => n !== 'none' && n !== 'root')))) === JSON.stringify({ lens: 'k-lens' }));
  await clear(page);
  await Promise.all([page.waitForURL(/\/title\//), page.click('a.hero-details')]);
  let reveal = await settle(page);
  let swap = await read(page, 'swap');
  ok('Home -> title: the old page has a view transition at pageswap', swap && swap.vt === true && swap.at === '/', JSON.stringify(swap));
  ok('Home -> title: at capture the hero art and the lens are the only named elements, each name once',
    swap && unique(swap.named) && JSON.stringify(Object.keys(swap.named).sort()) === '["k-art","k-lens"]' && /frame/.test(swap.named['k-art'][0]), JSON.stringify(swap && swap.named));
  ok('Home -> title: the new page reveals with a view transition that becomes ready (no duplicate name) and finishes',
    reveal && reveal.vt === true && reveal.ready === 'ok' && reveal.finished === true, JSON.stringify(reveal));
  ok('Home -> title: the art moves (old and new k-art), the lens has its own group, the page fades (root)',
    has(reveal, '::view-transition-old(k-art)') && has(reveal, '::view-transition-new(k-art)') && has(reveal, '::view-transition-group(k-lens)') && has(reveal, '::view-transition-old(root)'),
    JSON.stringify(reveal && reveal.anims.map((a) => a.pe)));
  ok('Home -> title: every transition animation is tier 3, at most 200 ms', reveal && reveal.anims.length > 0 && reveal.anims.every((a) => a.ms > 0 && a.ms <= 200), JSON.stringify(reveal && reveal.anims.map((a) => a.ms)));
  ok('title page: its one art frame and the lens are named, once each', reveal && unique(reveal.named) && JSON.stringify(Object.keys(reveal.named).sort()) === '["k-art","k-lens"]', JSON.stringify(reveal && reveal.named));

  // ---- title -> Home: no flight back (the first page's large art may be another item) ----------------------------
  await clear(page);
  await Promise.all([page.waitForURL(BASE + '/'), page.click('a.tab >> nth=0')]);
  reveal = await settle(page);
  ok('title -> Home: a transition runs, the title art only fades out (no k-art on Home, so nothing flies back)',
    reveal && reveal.vt === true && reveal.ready === 'ok' && has(reveal, '::view-transition-old(k-art)') && !has(reveal, '::view-transition-new(k-art)'), JSON.stringify(reveal && reveal.anims.map((a) => a.pe)));
  ok('Home after the transition: no element keeps the flight class', (await page.$$('.k-flight')).length === 0);

  // ---- Search -> title: the followed result's art flies -----------------------------------------------------------
  await page.goto(BASE + '/search?q=Synthetic');
  await sleep(300);
  await clear(page);
  const hit = await page.$('ul.hits a.t[href^="/title/"]');
  if (hit) {
    await Promise.all([page.waitForURL(/\/title\//), hit.click()]);
    reveal = await settle(page);
    swap = await read(page, 'swap');
    ok('Search -> title: the followed result\'s art is the one named frame at capture, and it flies into the title art',
      swap && unique(swap.named) && swap.named['k-art'] && swap.named['k-art'].length === 1 && reveal && reveal.ready === 'ok' && has(reveal, '::view-transition-old(k-art)') && has(reveal, '::view-transition-new(k-art)'),
      JSON.stringify({ swap, anims: reveal && reveal.anims.map((a) => a.pe) }));
  } else {
    ok('Search -> title: a result that links to a title page exists for member-a', false, 'no hit');
  }

  ok('no page errors or console errors with motion on', errors.length === 0, errors.join(' | '));
  await ctx.close();

  // ---- interruptible: with the transition held mid-way, a tap and a key still reach the new page at once ---------
  // A phone (touch). The page script ends the transition on the first press, so the tap's click lands on the tab.
  // (A mouse click that starts during a transition is not delivered: its press lands on the pictures; the next works.)
  ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true, reducedMotion: 'no-preference', serviceWorkers: 'block' });
  await ctx.addCookies([{ name: 'avrana_dev_identity', value: 'member-a', url: BASE }]);
  await ctx.addInitScript(probe);
  page = await ctx.newPage();
  errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  for (const how of ['tap', 'key']) {
    await page.goto(BASE + '/');
    await sleep(300);
    await clear(page);
    await page.evaluate(() => sessionStorage.setItem('mk6-hold', '1'));
    await Promise.all([page.waitForURL(/\/title\//), page.tap('a.hero-details')]);
    reveal = await settle(page, (r) => r && r.ready !== null);
    const held = await page.evaluate(() => !!document.activeViewTransition && document.getAnimations().some((a) => a.effect && String(a.effect.pseudoElement).startsWith('::view-transition') && a.playState === 'paused'));
    const t0 = Date.now();
    if (how === 'tap') {
      const box = await page.evaluate(() => { const r = document.querySelectorAll('a.tab')[2].getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; });
      await Promise.all([page.waitForURL(BASE + '/search', { timeout: 5000 }).catch(() => null), page.touchscreen.tap(box[0], box[1])]);
    } else {
      await page.evaluate(() => document.querySelectorAll('a.tab')[2].focus());
      await Promise.all([page.waitForURL(BASE + '/search', { timeout: 5000 }).catch(() => null), page.keyboard.press('Enter')]);
    }
    ok(`interruptible (${how}): during a transition that is still running, the Search tab is reached at once (${Date.now() - t0} ms)`, held && page.url() === BASE + '/search', `held=${held} url=${page.url()}`);
    await page.evaluate(() => sessionStorage.removeItem('mk6-hold'));
  }
  ok('no page errors during the interruption checks', errors.length === 0, errors.join(' | '));
  await ctx.close();

  // ---- reduce: no transition at all ---------------------------------------------------------------------------------
  ({ ctx, page, errors } = await context(browser, 'reduce'));
  await page.goto(BASE + '/');
  await sleep(300);
  await clear(page);
  await Promise.all([page.waitForURL(/\/title\//), page.click('a.hero-details')]);
  reveal = await settle(page);
  swap = await read(page, 'swap');
  ok('reduce: no view transition on the old page (pageswap) or the new page (pagereveal)', swap && swap.vt === false && reveal && reveal.vt === false, JSON.stringify({ swap, reveal }));
  ok('reduce: nothing is named on either page (the names live inside the no-preference query)', swap && reveal && Object.keys(swap.named).length === 0 && Object.keys(reveal.named).length === 0, JSON.stringify({ s: swap && swap.named, r: reveal && reveal.named }));
  await clear(page);
  await Promise.all([page.waitForURL(BASE + '/library'), page.click('a.tab >> nth=1')]);
  reveal = await settle(page);
  ok('reduce: a tab change has no transition either', reveal && reveal.vt === false, JSON.stringify(reveal));
  ok('no page errors or console errors with reduced motion', errors.length === 0, errors.join(' | '));
  await ctx.close();
  stop();

  // ---- the Proposal: off by default (above, 200 ms); HOME_MOTION_PROPOSAL=on gives the 600 ms token ----------------
  await start({ HOME_MOTION_PROPOSAL: 'on' });
  ({ ctx, page, errors } = await context(browser, 'no-preference'));
  await page.goto(BASE + '/');
  await sleep(300);
  await clear(page);
  await Promise.all([page.waitForURL(/\/title\//), page.click('a.hero-details')]);
  reveal = await settle(page, (r) => r && r.ready !== null);
  ok('Proposal on (HOME_MOTION_PROPOSAL=on): the same transition runs at the 600 ms token', reveal && reveal.anims.length > 0 && reveal.anims.every((a) => a.ms === 600), JSON.stringify(reveal && reveal.anims.map((a) => a.ms)));
  await ctx.close();
  ({ ctx, page, errors } = await context(browser, 'reduce'));
  await page.goto(BASE + '/');
  await clear(page);
  await Promise.all([page.waitForURL(/\/title\//), page.click('a.hero-details')]);
  reveal = await settle(page);
  ok('Proposal on, reduce: still no transition', reveal && reveal.vt === false, JSON.stringify(reveal));
  await ctx.close();
} catch (e) {
  console.log('ERROR', e);
  results.push(false);
} finally {
  try { if (browser) await browser.close(); } catch { /* */ }
  stop();
  const failed = results.filter((r) => !r).length;
  console.log(`\nmotion checks: ${results.length - failed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}
