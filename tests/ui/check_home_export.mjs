// Browser check of the static Home export (tests/ui/export_home_static.py). Development tool, loopback only.
//   PLAYWRIGHT_FROM=<folder with node_modules/@playwright/test and axe-core> \
//     node tests/ui/check_home_export.mjs --base http://127.0.0.1:PORT --dir <export folder> --shots <folder>
// Every exported page at 390x844 (touch), 1280x800 and 844x390 landscape, light and dark: axe-core
// (serious and critical fail), sideways scroll, and the smallest tap target on the page. Exit 1 on a finding.
import { createRequire } from 'node:module';
import path from 'node:path';
import fs from 'node:fs';

const from = path.resolve(process.env.PLAYWRIGHT_FROM || '.');
const require = createRequire(path.join(from, 'x.js'));
const { chromium } = require('@playwright/test');
const axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const args = process.argv.slice(2);
const opt = (n, d) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const base = opt('--base'), dir = opt('--dir'), shots = opt('--shots', '');
const SIZES = [['390', 390, 844, true], ['1280', 1280, 800, false], ['844x390', 844, 390, true]];
const walk = d => fs.readdirSync(d, { withFileTypes: true }).flatMap(e =>
  e.isDirectory() ? walk(path.join(d, e.name)) : e.name.endsWith('.html') ? [path.join(d, e.name)] : []);
const pages = walk(dir).map(f => path.relative(dir, f).split(path.sep).join('/')).sort();
const browser = await chromium.launch();
let findings = 0, checked = 0, smallest = 1e9;
for (const scheme of ['light', 'dark']) for (const [label, w, h, touch] of SIZES) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, hasTouch: touch, isMobile: touch,
    colorScheme: scheme, javaScriptEnabled: true });
  const page = await ctx.newPage();
  for (const p of pages) {
    for (let tries = 0; ; tries++) {   // a busy shared machine can refuse a load: retry, never skip a page
      try { await page.goto(`${base}/${p}`); break; }
      catch (e) { if (tries >= 4) throw e; await page.waitForTimeout(1500); }
    }
    await page.addScriptTag({ content: axeSource });
    const r = await page.evaluate(async () => {
      const res = await axe.run(document, { runOnly: ['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice'] });
      const bad = res.violations.filter(v => ['serious', 'critical'].includes(v.impact))
        .map(v => `${v.id}: ${v.nodes.slice(0, 2).map(n => n.target.join(' ')).join(' | ')}`);
      const sideways = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1;
      let min = 1e9;
      for (const a of document.querySelectorAll('a[href], summary, button')) {
        const b = a.getBoundingClientRect();
        if (b.width && b.height) min = Math.min(min, Math.round(Math.min(b.height, 1e9)));
      }
      return { bad, sideways, min };
    });
    checked++; smallest = Math.min(smallest, r.min);
    if (r.bad.length || r.sideways) { findings++; console.log(`FAIL ${scheme} ${label} ${p}: ${r.bad.join('; ')}${r.sideways ? ' [sideways scroll]' : ''}`); }
    if (shots && scheme === 'light' && /\/(home|home-new-[a-z-]+|search[a-z-]*|account|help)\.html$/.test(p)) {
      const tag = p.replace(/\.html$/, '').replace(/\//g, '-');
      fs.mkdirSync(shots, { recursive: true });
      try { await page.screenshot({ path: path.join(shots, `${tag}-${label}.png`), fullPage: true }); }
      catch (e) { console.log(`SHOT-FAIL ${p} ${label}: ${String(e.message).split(" ")[0]}`); }
    }
  }
  await ctx.close();
}
await browser.close();
console.log(`checked ${checked} page views (${pages.length} pages x 3 sizes x light/dark); findings: ${findings}; smallest link/summary height ${smallest}px`);
process.exit(findings ? 1 : 0);
