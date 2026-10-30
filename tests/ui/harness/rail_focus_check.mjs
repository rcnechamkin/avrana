// Behavioural check of the Rail Focus Rule (DESIGN.md "Media cards and rails"; RC2 U-03, RC1 A11Y-1), run in Chromium
// against an avrana-home dev stack that is already running on loopback. Development tool: synthetic identities only,
// never run against production, not part of run_offline.py or CI (layer 2). Start the stack first, for example
//   python -B services/avrana-home/dev/run_dev.py --dev-identity --port 8796 --mock-port 18796 \
//       --abs-mock-port 18797 --komga-mock-port 18798 --calibre-mock-port 18799
// then
//   PLAYWRIGHT_FROM=<tooling folder> node tests/ui/harness/rail_focus_check.mjs --base http://127.0.0.1:8796 \
//       [--out result.json] [--shots DIR] [--css EXTRA.css] [--no-axe] [--quick]
//
// For member-a and member-b, on /, /?for=watch, /?for=listen and /library, at 320, 360, 390 and 430 px wide with 100 %
// and 200 % text (the root font size doubled, as layer 2 does), it presses Tab through the page and then Shift+Tab back,
// and counts every stop on a rail card that is not wholly inside its rail's box with room for the 4px focus ring
// (a "clipped stop"). It also checks: no sideways page scroll; a pointer click on a peeking card does not move the
// rail; after a wheel turn and after an arrow key the rail comes to rest with a card start-aligned to the rail's
// scroll-padding (the snap still holds); axe-core shows no serious or critical violation on Home at 390 and 1280.
// --shots saves 390 at 200 % with the second card of the first rail focused. --css injects extra CSS after load
// (for trying a stylesheet change without editing the tree). Exit 1 on any finding.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const from = path.resolve(process.env.PLAYWRIGHT_FROM || '.');
const require = createRequire(path.join(from, 'x.js'));
const { chromium } = require('@playwright/test');
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const BASE = opt('--base', 'http://127.0.0.1:8796').replace(/\/$/, '');
const OUT = opt('--out', null);
const SHOTS = opt('--shots', null);
const CSS = opt('--css', null) ? fs.readFileSync(opt('--css'), 'utf8') : '';
const QUICK = args.includes('--quick');
const NO_AXE = args.includes('--no-axe');

const IDS = QUICK ? ['member-a'] : ['member-a', 'member-b'];
const PAGES = ['/', '/?for=watch', '/?for=listen', '/library'];
const WIDTHS = [320, 360, 390, 430];
const SCALES = [100, 200];
const result = { base: BASE, css: !!CSS, focus: [], hscroll: [], click: [], snap: [], axe: [], findings: 0 };
const fail = (msg) => { result.findings++; console.log('FAIL', msg); };

async function open(ctx, url, scale) {
  const page = await ctx.newPage();
  await page.goto(BASE + url, { waitUntil: 'load' });
  if (scale !== 100) await page.addStyleTag({ content: `html{font-size:${scale}%}` });
  if (CSS) await page.addStyleTag({ content: CSS });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(150);
  return page;
}

// Where the focused element sits against its rail, or null when focus is not on a rail card.
const where = () => {
  const a = document.activeElement;
  if (!a || !a.matches('.rail a.card')) return null;
  const rail = a.closest('.rail'), ar = a.getBoundingClientRect(), rr = rail.getBoundingClientRect();
  const rails = Array.from(document.querySelectorAll('.rail'));
  const all = Array.from(document.querySelectorAll('.rail a.card')).filter(x => x.offsetParent);
  return { rail: rails.indexOf(rail), card: Array.from(rail.querySelectorAll('a.card')).indexOf(a),
           g: all.indexOf(a), last: all.length - 1,
           ok: ar.left >= rr.left + 4 - 0.5 && ar.right <= rr.right - 4 + 0.5,
           at: `${Math.round(ar.left)}..${Math.round(ar.right)} in ${Math.round(rr.left)}..${Math.round(rr.right)}` };
};

// Each visible rail that overflows: is a card resting start-aligned to the rail's scroll-padding?
const rest = () => Array.from(document.querySelectorAll('.rail')).filter(r => r.offsetParent && r.scrollWidth > r.clientWidth + 1).map(r => {
  const rr = r.getBoundingClientRect();
  const sp = parseFloat(getComputedStyle(r).scrollPaddingLeft) || 0;
  const items = Array.from(r.children).filter(li => li.offsetParent);
  const first = items.find(li => li.getBoundingClientRect().right > rr.left + sp + 1);
  const off = first ? first.getBoundingClientRect().left - (rr.left + sp) : 0;
  const end = r.scrollLeft >= r.scrollWidth - r.clientWidth - 1;
  return { scrollLeft: Math.round(r.scrollLeft), off: Math.round(off * 10) / 10, end };
});

const browser = await chromium.launch();
try {
  for (const id of IDS) {
    for (const w of WIDTHS) for (const scale of SCALES) {
      const ctx = await browser.newContext({ viewport: { width: w, height: 844 }, reducedMotion: 'reduce' });
      await ctx.addCookies([{ name: 'avrana_dev_identity', value: id, url: BASE }]);
      for (const url of PAGES) {
        const page = await open(ctx, url, scale);
        const label = `${id} ${url} ${w}@${scale}%`;
        const h = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        result.hscroll.push({ id, url, w, scale, overflow: h });
        if (h > 0) fail(`hscroll ${label}: page scrolls sideways by ${h}px`);
        const cards = await page.locator('.rail a.card:visible').count();
        let stops = 0; const bad = [];
        for (const key of ['Tab', 'Shift+Tab']) {
          for (let i = 0; i < cards + 60; i++) {
            await page.keyboard.press(key);
            const r = await page.evaluate(where);
            if (!r) continue;
            stops++;
            if (!r.ok) bad.push(`${key} rail${r.rail} card${r.card} ${r.at}`);
            if (key === 'Tab' ? r.g === r.last : r.g === 0) break;   // walked every card in this direction
          }
        }
        result.focus.push({ id, url, w, scale, stops, clipped: bad.length, examples: bad.slice(0, 4) });
        if (bad.length) fail(`focus ${label}: ${bad.length} of ${stops} stops clipped, e.g. ${bad[0]}`);
        await page.close();
      }
      // A pointer click on the peeking card does not move its rail (the handler acts on keyboard focus only).
      // Snap: a wheel turn, then an arrow key, must leave a card start-aligned.
      if (w <= 430) {
        const page = await open(ctx, '/', scale);
        const info = await page.evaluate(() => {
          const r = Array.from(document.querySelectorAll('.rail')).find(x => x.offsetParent && x.scrollWidth > x.clientWidth + 1);
          if (!r) return null;
          r.scrollIntoView({ block: 'center' });
          const rr = r.getBoundingClientRect();
          const peek = Array.from(r.querySelectorAll('a.card')).find(a => { const b = a.getBoundingClientRect(); return b.left < rr.right && b.right > rr.right; });
          const pb = peek && peek.getBoundingClientRect();
          return { x: rr.left + rr.width / 2, y: rr.top + 60, px: pb ? (pb.left + Math.min(rr.right, pb.right)) / 2 : null, py: pb ? pb.top + 40 : null };
        });
        if (info && info.px !== null) {
          await page.evaluate(() => document.addEventListener('click', e => e.preventDefault(), { capture: true }));
          const before = await page.evaluate(() => Array.from(document.querySelectorAll('.rail')).map(r => r.scrollLeft));
          await page.mouse.click(info.px, info.py);
          await page.waitForTimeout(300);
          const after = await page.evaluate(() => Array.from(document.querySelectorAll('.rail')).map(r => r.scrollLeft));
          const moved = before.some((v, i) => Math.abs(v - after[i]) > 1);
          result.click.push({ id, w, scale, moved });
          if (moved) fail(`click ${id} ${w}@${scale}%: a pointer click on a peeking card moved the rail`);
        }
        if (info) {
          await page.mouse.move(info.x, info.y);
          await page.mouse.wheel(170, 0);
          await page.waitForTimeout(900);
          const wheel = await page.evaluate(rest);
          // arrow key: focus the first card of the first overflowing rail with the keyboard, then ArrowRight
          await page.evaluate(() => { const r = Array.from(document.querySelectorAll('.rail')).find(x => x.offsetParent && x.scrollWidth > x.clientWidth + 1); r.scrollLeft = 0; r.querySelector('a.card').focus({ focusVisible: true }); });
          await page.waitForTimeout(200);
          await page.keyboard.press('ArrowRight');
          await page.waitForTimeout(900);
          const arrow = await page.evaluate(rest);
          for (const [how, list] of [['wheel', wheel], ['arrow', arrow]]) {
            const off = list.filter(x => !x.end && Math.abs(x.off) > 1);
            result.snap.push({ id, w, scale, how, rails: list.length, misaligned: off.length, sample: list.slice(0, 3) });
            if (off.length) fail(`snap ${id} ${w}@${scale}% ${how}: ${off.length} rail(s) rest off a card start (${off.map(x => x.off).join(', ')})`);
          }
        }
        await page.close();
      }
      await ctx.close();
    }
  }

  if (!NO_AXE) for (const id of IDS) for (const w of [390, 1280]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: 900 } });
    await ctx.addCookies([{ name: 'avrana_dev_identity', value: id, url: BASE }]);
    const page = await open(ctx, '/', 100);
    await page.evaluate(AXE);
    const v = await page.evaluate(async () => (await window.axe.run(document, { resultTypes: ['violations'] })).violations
      .filter(x => x.impact === 'serious' || x.impact === 'critical').map(x => `${x.id} (${x.nodes.length})`));
    result.axe.push({ id, w, serious_or_critical: v });
    if (v.length) fail(`axe ${id} / ${w}: ${v.join(', ')}`);
    await ctx.close();
  }

  if (SHOTS) {
    fs.mkdirSync(SHOTS, { recursive: true });
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
    await ctx.addCookies([{ name: 'avrana_dev_identity', value: 'member-a', url: BASE }]);
    const page = await open(ctx, '/', 200);
    let r = null;
    for (let i = 0; i < 200; i++) { await page.keyboard.press('Tab'); r = await page.evaluate(where); if (r && r.card === 1) break; }
    await page.waitForTimeout(200);
    const file = path.join(SHOTS, 'rail-focus-390-200.png');
    await page.screenshot({ path: file });
    result.shot = { file, focused: r };
    console.log('shot', file, r ? r.at : 'no card focused');
    await ctx.close();
  }
} finally {
  await browser.close();
}

const sum = {};
for (const f of result.focus) { const k = `${f.w}@${f.scale}%`; sum[k] = sum[k] || { stops: 0, clipped: 0 }; sum[k].stops += f.stops; sum[k].clipped += f.clipped; }
result.summary = sum;
console.log('clipped focused stops by size:', JSON.stringify(sum));
console.log(`findings: ${result.findings}`);
if (OUT) fs.writeFileSync(OUT, JSON.stringify(result, null, 2));
process.exit(result.findings ? 1 : 0);
