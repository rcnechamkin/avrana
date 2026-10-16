// Browser + axe checks for the platform skip link (portal Home and avrana-home Home).
// Development tool: loopback only, synthetic identities, never run against production.
// Normally started by skip_link_run.py, which starts the servers and passes their URLs:
//   PLAYWRIGHT_FROM=<tooling folder> node tests/ui/harness/skip_link.mjs \
//     --portal http://127.0.0.1:P/p/portal/home/multi --home http://127.0.0.1:H/ --out DIR [--label NAME]
// Home runs twice: "dev-shim" (the page as served, with the development identity banner, whose
// "Switch" link precedes the skip link) and "prod-equivalent" (the banner removed from the response,
// which is what the production template serves).
import { createRequire } from 'node:module';
import path from 'node:path';
import fs from 'node:fs';

const from = path.resolve(process.env.PLAYWRIGHT_FROM || '.');
const require = createRequire(path.join(from, 'x.js'));
const { chromium } = require('@playwright/test');
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const out = opt('--out', 'skip-link-out'), label = opt('--label', 'run');
const axeOnly = args.includes('--axe-only');   // baseline on a tree without the skip link: axe only
for (const u of [opt('--portal'), opt('--home')]) {
  if (u && !/^http:\/\/127\.0\.0\.1:\d+\//.test(u)) { console.error('loopback URLs only'); process.exit(2); }
}
fs.mkdirSync(out, { recursive: true });

const targets = [];
if (opt('--portal')) targets.push({ name: 'portal', url: opt('--portal'), strip: false });
if (opt('--home')) {
  targets.push({ name: 'home-dev-shim', url: opt('--home'), strip: false, headers: { 'x-dev-identity': 'member-a' } });
  targets.push({ name: 'home-prod-equivalent', url: opt('--home'), strip: true, headers: { 'x-dev-identity': 'member-a' } });
}
const VIEWPORTS = [{ tag: '390', width: 390, height: 844, mobile: true }, { tag: '1280', width: 1280, height: 800 }];

const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };

const inPage = () => {
  const parse = (s) => { const m = (s || '').match(/[\d.]+/g); return m ? m.slice(0, 3).map(Number).concat(m.length > 3 ? [Number(m[3])] : [1]) : null; };
  const a = document.activeElement, cs = getComputedStyle(a), r = a.getBoundingClientRect();
  let bg = document.body, pageBg = null;
  while (bg && !pageBg) { const c = parse(getComputedStyle(bg).backgroundColor); if (c && c[3] > 0.99) pageBg = c; bg = bg.parentElement; }
  if (!pageBg) pageBg = parse(getComputedStyle(document.documentElement).backgroundColor) || [255, 255, 255, 1];
  const shadows = [...(cs.boxShadow || '').matchAll(/(rgba?\([^)]*\))([^,]*)/g)]
    .map((s) => ({ color: parse(s[1]), spread: parseFloat((s[2].match(/-?[\d.]+px/g) || []).slice(-1)[0] || '0') }));
  const pts = [[0.05, 0.1], [0.5, 0.5], [0.95, 0.9], [0.05, 0.9], [0.95, 0.1]];
  const obscured = pts.some(([fx, fy]) => { const e = document.elementFromPoint(r.left + r.width * fx, r.top + r.height * fy); return !(e && (e === a || a.contains(e))); });
  let clipAnc = false;
  for (let p = a.parentElement; p; p = p.parentElement) { if (cs.position !== 'fixed' && getComputedStyle(p).overflow !== 'visible') clipAnc = true; }
  const tag = (e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className ? '.' + e.className.split(' ').join('.') : '');
  return { active: tag(a), text: a.textContent.trim(), href: a.getAttribute('href'),
    box: { x: r.x, y: r.y, w: r.width, h: r.height }, vw: innerWidth, vh: innerHeight,
    opacity: cs.opacity, visibility: cs.visibility, display: cs.display, clip: cs.clip, clipPath: cs.clipPath, overflow: cs.overflow, position: cs.position,
    color: parse(cs.color), bg: parse(cs.backgroundColor), pageBg, shadows, obscured, clipAnc };
};

const firstFocusableInMain = () => {
  const sel = 'a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select,textarea,summary,[tabindex]:not([tabindex="-1"])';
  const el = [...document.querySelector('main#main').querySelectorAll(sel)].find((e) => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  return el ? el.tagName.toLowerCase() + ':' + (el.textContent.trim().slice(0, 40) || el.getAttribute('aria-label') || '') : null;
};
const activeDesc = () => { const e = document.activeElement; return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + ':' + (e.textContent.trim().slice(0, 40)); };

const axeRun = async (page, t, info, chk) => {
  await page.goto(t.url, { waitUntil: 'load' });
  await page.evaluate(axeSource);
  info.axe = await page.evaluate(async () => (await axe.run(document, { resultTypes: ['violations'] })).violations.map((x) => ({ id: x.id, impact: x.impact, nodes: x.nodes.map((n) => n.target.join(' ')) })));
  chk('axe: no violations', info.axe.length === 0, info.axe.map((x) => `${x.id}(${x.nodes.length})`).join(', '));
};
const browser = await chromium.launch();
const results = [];
for (const t of targets) for (const v of VIEWPORTS) {
  const id = `${t.name}@${v.tag}`, checks = [], chk = (n, ok, d) => checks.push({ name: n, ok: !!ok, detail: d });
  const ctx = await browser.newContext({ viewport: { width: v.width, height: v.height }, isMobile: !!v.mobile, hasTouch: !!v.mobile, deviceScaleFactor: v.mobile ? 2 : 1, extraHTTPHeaders: t.headers || {} });
  const page = await ctx.newPage();
  if (t.strip) await page.route('**/*', async (route) => {
    const resp = await route.fetch(); const ct = resp.headers()['content-type'] || '';
    if (!ct.startsWith('text/html')) return route.fulfill({ response: resp });
    const body = (await resp.text()).replace(/<div role="note"[^>]*>DEVELOPMENT IDENTITY[\s\S]*?<\/div>/, '');
    route.fulfill({ response: resp, body });
  });
  await page.goto(t.url, { waitUntil: 'load' });
  const info = { id };
  if (axeOnly) { info.checks = checks; await axeRun(page, t, info, chk); results.push(info); await ctx.close(); continue; }
  await page.keyboard.press('Tab');
  info.firstTab = await page.evaluate(activeDesc);
  if (t.name === 'home-dev-shim') {
    chk('dev shim: first Tab lands on the injected "Switch" link; skip link is the second stop', /Switch/.test(info.firstTab), info.firstTab);
    await page.keyboard.press('Tab');
  }
  const m = await page.evaluate(inPage); info.m = m;
  const skip = m.active.startsWith('a.skip-link');
  chk(t.name === 'home-dev-shim' ? 'second Tab focuses the skip link' : 'first Tab focuses the skip link', skip && m.text === 'Skip to main content' && m.href === '#main', m.active + ' ' + m.text);
  const b = m.box;
  chk('bounding box area >= 1px', b.w * b.h >= 1, `${b.w.toFixed(1)}x${b.h.toFixed(1)}`);
  chk('inside viewport', b.x >= 0 && b.y >= 0 && b.x + b.w <= m.vw && b.y + b.h <= m.vh, JSON.stringify(b));
  chk('not clipped (clip, clip-path, overflow, ancestors)', m.clip === 'auto' && m.clipPath === 'none' && m.overflow === 'visible' && !m.clipAnc, `${m.clip} | ${m.clipPath} | ${m.overflow} | anc=${m.clipAnc}`);
  chk('opacity 1 and visibility visible', m.opacity === '1' && m.visibility === 'visible' && m.display !== 'none', `${m.opacity} ${m.visibility} ${m.display}`);
  const text = ratio(m.color, m.bg); chk('text contrast >= 4.5:1', text >= 4.5, text.toFixed(2));
  const fill = ratio(m.bg, m.pageBg); chk('link fill vs page background >= 3:1 (focus indicator)', fill >= 3, fill.toFixed(2));
  const ring = m.shadows.length ? m.shadows[m.shadows.length - 1] : null;
  const ringC = ring ? ratio(ring.color, m.pageBg) : 0; chk('focus ring (outer box-shadow) vs page background >= 3:1', ring && ringC >= 3, ring ? ringC.toFixed(2) + ' spread ' + ring.spread + 'px' : 'no ring');
  chk('not obscured by sticky/fixed content (elementFromPoint, 5 points; 2.4.11)', !m.obscured, m.obscured ? 'obscured' : 'clear');
  chk('target height >= 44px', b.h >= 43.5, b.h.toFixed(1));
  await page.screenshot({ path: path.join(out, `${t.name}-${v.tag}-focused.png`) });
  const aria = await page.locator('body').ariaSnapshot();
  await page.keyboard.press('Enter');
  const after = await page.evaluate(() => ({ a: document.activeElement.tagName.toLowerCase() + (document.activeElement.id ? '#' + document.activeElement.id : ''), hash: location.hash }));
  chk('Enter moves focus to main#main', after.a === 'main#main' && after.hash === '#main', JSON.stringify(after));
  const expected = await page.evaluate(firstFocusableInMain);
  await page.keyboard.press('Tab');
  const next = await page.evaluate(activeDesc);
  const inMain = await page.evaluate(() => !!document.activeElement.closest('main#main'));
  chk('next Tab lands on the first focusable element inside main', inMain && expected && next === expected, `${next} (expected ${expected})`);
  chk('accessibility tree exposes link "Skip to main content"', /link "Skip to main content"/.test(aria), '');
  chk('main is a landmark (one role=main)', /- main/.test(aria) && (await page.getByRole('main').count()) === 1, '');
  chk('exactly one skip link by role and name', (await page.getByRole('link', { name: 'Skip to main content', exact: true }).count()) === 1, '');
  await page.goto(t.url, { waitUntil: 'load' });
  await page.evaluate(axeSource);
  const ax = await page.evaluate(async () => { const r = await axe.run(document, { resultTypes: ['violations'] }); return r.violations.map((x) => ({ id: x.id, impact: x.impact, nodes: x.nodes.map((n) => n.target.join(' ')) })); });
  info.axe = ax;
  chk('axe (focus not on skip link): no violations', ax.length === 0, ax.map((x) => `${x.id}(${x.nodes.length})`).join(', '));
  await page.keyboard.press('Tab');
  if (t.name === 'home-dev-shim') await page.keyboard.press('Tab');
  const ax2 = await page.evaluate(async () => { const r = await axe.run(document, { resultTypes: ['violations'] }); return r.violations.map((x) => ({ id: x.id, impact: x.impact, nodes: x.nodes.map((n) => n.target.join(' ')) })); });
  chk('axe (skip link focused and visible): no violations', ax2.length === 0, ax2.map((x) => `${x.id}(${x.nodes.length})`).join(', '));
  info.axeFocused = ax2;
  info.checks = checks; info.ariaSnapshot = aria; results.push(info);
  await ctx.close();
}
await browser.close();
fs.writeFileSync(path.join(out, `report-${label}.json`), JSON.stringify({ label, results }, null, 1));
let bad = 0;
for (const r of results) { console.log(`\n== ${r.id}`); for (const c of r.checks) { console.log(`${c.ok ? 'PASS' : 'FAIL'}  ${c.name}  ${c.detail}`); if (!c.ok) bad++; } }
console.log(`\n${bad} failing checks`);
process.exit(bad ? 1 : 0);
