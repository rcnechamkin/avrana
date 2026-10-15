// Screenshots and browser checks for the member home preview. Optional: it needs Node and a
// Playwright install, which this repository does not carry. Point PLAYWRIGHT_FROM at any folder
// whose node_modules has @playwright/test (the avrana-party checkout does), with the preview
// running:
//
//   PLAYWRIGHT_FROM=../avrana-party node tests/ui/home_preview/check.mjs http://127.0.0.1:8200 tests/ui/home_preview/screens
//
// It writes one full-page PNG per state and size, plus today's portal home (/before), and prints
// what it checked. It exits 1 when a check fails.
import { createRequire } from 'node:module';
import path from 'node:path';
import fs from 'node:fs';
const require = createRequire(path.join(path.resolve(process.env.PLAYWRIGHT_FROM || '.'), 'x.js'));
const { chromium } = require('@playwright/test');

const [base, outdir] = process.argv.slice(2);
if (!base || !outdir) { console.error('usage: check.mjs <baseUrl> <outdir>'); process.exit(2); }
fs.mkdirSync(outdir, { recursive: true });
const STATES = ['healthy', 'slow', 'empty', 'degraded', 'unavailable'];
const SIZES = [
  { tag: 'phone', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  { tag: 'desktop', viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 },
];
const failures = [];
const fail = (where, what) => failures.push(`${where}: ${what}`);

/** Everything measured in the page, in one pass. */
const inspect = () => {
  const lum = (c) => { const [r, g, b] = c.match(/[\d.]+/g).slice(0, 3).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const ground = (el) => { for (let n = el; n; n = n.parentElement) { const bg = getComputedStyle(n).backgroundColor; if (!/rgba\(.*, 0\)|transparent/.test(bg)) return bg; } return 'rgb(0,0,0)'; };
  const out = { sideways: document.documentElement.scrollWidth > innerWidth + 1, scripts: document.scripts.length, small: [], faint: [], noAlt: [], headings: [], h1: document.querySelectorAll('h1').length };
  for (const el of document.querySelectorAll('main a, footer a, .mast a, .mast summary, .menu a, .places a, .preview a')) {
    const r = el.getBoundingClientRect();
    if (r.width && (r.height < 43.5 || r.width < 43.5)) out.small.push(`${el.textContent.trim().slice(0, 30)} ${Math.round(r.width)}x${Math.round(r.height)}`);
  }
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!n.textContent.trim() || !el.getClientRects().length || el.closest('[aria-hidden="true"]')) continue;
    const a = lum(getComputedStyle(el).color), b = lum(ground(el));
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    if (ratio < 4.5) out.faint.push(`${n.textContent.trim().slice(0, 30)} ${ratio.toFixed(2)}`);
  }
  for (const img of document.images) if (!img.hasAttribute('alt')) out.noAlt.push(img.src);
  out.headings = [...document.querySelectorAll('h1,h2,h3,h4')].map((h) => Number(h.tagName[1]));
  out.rails = [...document.querySelectorAll('ul.rail:not(.waiting)')].map((r) => r.scrollWidth > r.clientWidth + 1);
  out.broken = [...document.images].filter((i) => i.complete && !i.naturalWidth).length;
  // the places come first: where the bar of libraries, Request and Help ends, measured from the
  // top of the design (the preview's own bar is not part of it)
  const top = document.querySelector('.preview').getBoundingClientRect().bottom + scrollY;
  out.places = [...document.querySelectorAll('.places > *')].map((el) => [el.textContent.trim().split(',')[0], Math.round(el.getBoundingClientRect().bottom + scrollY - top)]);
  out.height = Math.round(document.documentElement.scrollHeight - top);
  out.cards = [...document.querySelectorAll('ul.rail')].map((r) => r.children.length);
  return out;
};

const browser = await chromium.launch();
try {
  for (const size of SIZES) {
    const { tag, ...options } = size;
    const context = await browser.newContext({ ...options, baseURL: base, javaScriptEnabled: false });
    const page = await context.newPage();
    for (const state of STATES) {
      const where = `${state} ${tag}`;
      const response = await page.goto(`/?state=${state}`);
      if (!/default-src 'none'/.test(response.headers()['content-security-policy'] || '')) fail(where, 'no Content-Security-Policy');
      await page.evaluate(() => Promise.all([...document.images].map((i) => { i.loading = 'eager'; return i.decode().catch(() => {}); })));
      await page.screenshot({ path: path.join(outdir, `after-${state}-${tag}.png`), fullPage: true });
      const seen = await page.evaluate(inspect);
      if (seen.sideways) fail(where, 'the page scrolls sideways');
      if (seen.scripts) fail(where, `${seen.scripts} script element(s)`);
      if (seen.h1 !== 1) fail(where, `${seen.h1} h1 elements`);
      if (seen.broken) fail(where, `${seen.broken} image(s) did not load`);
      seen.headings.reduce((prev, level) => { if (level > prev + 1) fail(where, `heading level jumps ${prev} to ${level}`); return level; }, 0);
      for (const s of seen.small) fail(where, `target under 44px: ${s}`);
      for (const s of seen.faint) fail(where, `text under 4.5:1: ${s}`);
      for (const s of seen.noAlt) fail(where, `image without alt: ${s}`);
      if (tag === 'phone' && state === 'healthy' && !seen.rails.every(Boolean)) fail(where, 'a rail does not scroll inside itself on a phone');
      if (tag === 'desktop' && seen.rails.some(Boolean)) fail(where, 'a rail scrolls on a wide screen');
      // every Tab stop shows the two-ring focus mark
      // links and the account control, counting only what is rendered (a closed menu's links are not)
      const stops = await page.evaluate(() => [...document.querySelectorAll('a[href], summary')].filter((el) => el.getClientRects().length && !el.closest('details:not([open]) > :not(summary)')).length);
      for (let i = 0; i < stops; i++) {
        await page.keyboard.press('Tab');
        const mark = await page.evaluate(() => { const el = document.activeElement; return el === document.body ? 'body' : getComputedStyle(el).boxShadow; });
        if (mark === 'none' || mark === 'body') { fail(where, `Tab stop ${i + 1} shows no focus ring`); break; }
      }
      console.log(`checked ${where}: ${stops} links`);
    }
    // the New page: everything new in one library, one page per state
    for (const state of STATES) {
      const where = `new, ${state} ${tag}`;
      await page.goto(`/new?state=${state}`);
      await page.evaluate(() => Promise.all([...document.images].map((i) => { i.loading = 'eager'; return i.decode().catch(() => {}); })));
      await page.screenshot({ path: path.join(outdir, `after-new-${state}-${tag}.png`), fullPage: true });
      const seen = await page.evaluate(inspect);
      if (seen.sideways) fail(where, 'the page scrolls sideways');
      if (seen.scripts) fail(where, `${seen.scripts} script element(s)`);
      if (seen.h1 !== 1) fail(where, `${seen.h1} h1 elements`);
      if (seen.broken) fail(where, `${seen.broken} image(s) did not load`);
      for (const s of seen.small) fail(where, `target under 44px: ${s}`);
      for (const s of seen.faint) fail(where, `text under 4.5:1: ${s}`);
      console.log(`checked ${where}`);
    }
    await page.goto('/?state=healthy&new=audio');
    await page.screenshot({ path: path.join(outdir, `after-healthy-new-audiobooks-${tag}.png`), fullPage: true });
    await page.goto('/?state=healthy&art=mono');
    await page.screenshot({ path: path.join(outdir, `after-healthy-grey-art-${tag}.png`), fullPage: true });
    await page.goto('/before');
    await page.screenshot({ path: path.join(outdir, `before-${tag}.png`), fullPage: true });
    await context.close();
  }
  // A small phone, 360 by 640: the five places are on the first screen, the rows are bounded and
  // the whole home page is no more than two screens.
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 640 }, deviceScaleFactor: 2, baseURL: base, javaScriptEnabled: false });
    const page = await context.newPage();
    await page.goto('/?state=healthy');
    await page.screenshot({ path: path.join(outdir, 'after-healthy-small-phone.png'), fullPage: true });
    const seen = await page.evaluate(inspect);
    const names = seen.places.map(([name]) => name);
    if (names.join(' ') !== 'Watch Listen Read Request Help') fail('healthy small phone', `the places are ${names.join(', ')}`);
    for (const [name, bottom] of seen.places) if (bottom > 260) fail('healthy small phone', `${name} ends at ${bottom}px, below 260`);
    if (seen.height > 1280) fail('healthy small phone', `the page is ${seen.height}px, more than two screens`);
    if (seen.cards.some((n) => n > 4)) fail('healthy small phone', `a row has more than four things: ${seen.cards}`);
    if (seen.sideways) fail('healthy small phone', 'the page scrolls sideways');
    console.log(`checked healthy small phone: places end at ${Math.max(...seen.places.map(([, y]) => y))}px, page ${seen.height}px, rows of ${seen.cards.join(' and ')}`);
    await context.close();
  }
  // The account control (AVR-478), at 360 by 640 and for every viewer: found by its word, large enough,
  // opened and closed from the keyboard with no script, focus kept on it, the menu inside the screen.
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 640 }, deviceScaleFactor: 2, hasTouch: true, baseURL: base, javaScriptEnabled: false });
    const page = await context.newPage();
    for (const who of ['member', 'books', 'none', 'out']) {
      for (const state of ['healthy', 'degraded', 'unavailable']) {
        const where = `account, ${who}, ${state}, small phone`;
        await page.goto(`/?state=${state}&who=${who}`);
        const seen = await page.evaluate(inspect);
        if (seen.sideways) fail(where, 'the page scrolls sideways');
        for (const s of seen.small) fail(where, `target under 44px: ${s}`);
        for (const s of seen.faint) fail(where, `text under 4.5:1: ${s}`);
        const summary = page.locator('.account summary');
        if (who === 'out') {
          if (await summary.count()) fail(where, 'an account control without a member');
          if (!(await page.locator('.mast a', { hasText: 'Sign in' }).count())) fail(where, 'no Sign in');
          continue;
        }
        await summary.focus();
        await page.keyboard.press('Enter');
        const open = await page.evaluate(() => {
          const d = document.querySelector('.account'), m = d.querySelector('.menu').getBoundingClientRect();
          return { open: d.open, focus: document.activeElement.tagName, left: m.left, right: m.right,
                   links: [...d.querySelectorAll('.menu a')].map((a) => [a.textContent.trim(), Math.round(a.getBoundingClientRect().height)]) };
        });
        if (!open.open) fail(where, 'Enter did not open the account menu');
        if (open.focus !== 'SUMMARY') fail(where, `focus moved to ${open.focus} on opening`);
        if (open.left < 0 || open.right > 360) fail(where, `the menu leaves the screen (${Math.round(open.left)} to ${Math.round(open.right)})`);
        if (open.links.map(([n]) => n).join('|') !== 'Account and security|Help|Sign out') fail(where, `menu is ${open.links.map(([n]) => n)}`);
        for (const [n, h] of open.links) if (h < 44) fail(where, `${n} is ${h}px high`);
        await page.keyboard.press('Tab');
        if ((await page.evaluate(() => document.activeElement.textContent.trim())) !== 'Account and security') fail(where, 'Tab from the open control does not reach the first menu item');
        await summary.focus();
        await page.keyboard.press('Space');
        if (await page.evaluate(() => document.querySelector('.account').open)) fail(where, 'Space did not close the account menu');
        if (state === 'healthy') await page.screenshot({ path: path.join(outdir, `account-${who}-small-phone.png`), fullPage: false });
      }
      console.log(`checked account control for ${who}`);
    }
    await context.close();
  }
  // 200% text: the root size doubled, at phone width
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, baseURL: base });
  const page = await context.newPage();
  await page.goto('/?state=healthy');
  await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
  if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) fail('healthy phone, 200% text', 'the page scrolls sideways');
  await page.screenshot({ path: path.join(outdir, 'after-healthy-200-percent-text-phone.png'), fullPage: true });
  console.log('checked healthy phone at 200% text');
  await context.close();
} finally { await browser.close(); }
if (failures.length) { console.error('\nFAILED\n' + failures.join('\n')); process.exit(1); }
console.log('\nall checks passed');
