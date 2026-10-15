// Layer 2: browser checks for every registry page. Development tool: never run against production,
// never part of tests/run_offline.py. Normally started by run_ui.py, which serves the pages from
// loopback (serve.py) and applies the baseline ratchet to the report this writes.
//
//   PLAYWRIGHT_FROM=<folder whose node_modules has @playwright/test and axe-core> \
//     node tests/ui/harness/check.mjs --base http://127.0.0.1:PORT --out tests/ui/harness/out \
//     [--only portal/home] [--report-only]
//
// For each page at 390x844 (touch) and 1280x800 it: runs axe-core (serious/critical are findings);
// walks the Tab order and checks every interactive element is reachable, in DOM order, with a
// visible focus indicator (computed ring AND a pixel difference between focused and unfocused);
// checks for sideways scroll; measures rendered target sizes and text/edge contrast; and repeats
// at 200% text (root font size doubled) looking for sideways scroll and clipping. Screenshots
// (default, first-Tab-stop focused, 200%) go to <out>/shots (git-ignored); report.json to <out>.
// JavaScript is switched off unless a page's registry entry says it needs it.
import { createRequire } from 'node:module';
import path from 'node:path';
import fs from 'node:fs';

const from = path.resolve(process.env.PLAYWRIGHT_FROM || '.');
const require = createRequire(path.join(from, 'x.js'));
let chromium, axeSource, versions = {};
try {
  ({ chromium } = require('@playwright/test'));
  axeSource = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
  versions.playwright = require('@playwright/test/package.json').version;
  versions.axe = require('axe-core/package.json').version;
} catch (e) {
  console.error(`cannot load @playwright/test and axe-core from PLAYWRIGHT_FROM=${from}: ${e.message}`);
  process.exit(2);
}

const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : dflt; };
const base = opt('--base');
const outdir = opt('--out', 'tests/ui/harness/out');
const only = opt('--only', '');
const reportOnly = args.includes('--report-only');
const verbose = args.includes('--verbose');
const t0 = Date.now();
const log = (m) => { if (verbose) console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${m}`); };
if (!base) { console.error('usage: check.mjs --base <url> [--out dir] [--only substring] [--report-only]'); process.exit(2); }
const shots = path.join(outdir, 'shots');
fs.mkdirSync(shots, { recursive: true });

const VIEWPORTS = [
  { tag: 'phone', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
  { tag: 'desktop', viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 },
];
const MIN_TARGET = 44;
const findings = new Map();      // id -> { id, rule, viewport, message }
const add = (key, rule, vp, detail, message) => {
  const id = `${key}/${rule}/${vp}${detail ? ':' + detail : ''}`;
  if (!findings.has(id)) findings.set(id, { id, rule, viewport: vp, page: key, message });
};
const safe = (s) => s.replace(/[^\w.-]+/g, '_');

// ---- in-page measurements (self-contained: serialised into the page) ------------------------
const measure = (MIN) => {
  const parse = (c) => { const m = (c || '').match(/[\d.]+/g); if (!m || m.length < 3) return null; return [+m[0], +m[1], +m[2], m.length > 3 ? +m[3] : 1]; };
  const lum = (c) => { const [r, g, b] = c.slice(0, 3).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const over = (f, b) => [0, 1, 2].map((i) => f[i] * f[3] + b[i] * (1 - f[3])).concat([1]);
  const label = (el) => el.tagName.toLowerCase() + (el.classList.length ? '.' + [...el.classList].slice(0, 2).join('.') : '') + (el.tagName === 'INPUT' && el.type ? `[${el.type}]` : '');
  const ground = (el) => {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.backgroundImage !== 'none') return null;
      const bg = parse(cs.backgroundColor);
      if (bg && bg[3] > 0) { layers.push(bg); if (bg[3] === 1) break; }
    }
    return layers.reduceRight((acc, l) => over(l, acc), [255, 255, 255, 1]);
  };
  const visible = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const out = { targets: [], text: [], edges: [], count: 0 };
  const interactive = [...document.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea,summary')].filter(visible);
  out.count = interactive.length;
  for (const el of interactive) {
    let rect = el.getBoundingClientRect();
    const lab = el.closest('label');
    if (lab && /^(checkbox|radio)$/.test(el.type || '')) rect = lab.getBoundingClientRect();
    const own = [...el.parentElement.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    const inlineInText = el.tagName === 'A' && getComputedStyle(el).display === 'inline' && own;
    if (!inlineInText) {
      const small = el.tagName === 'A' ? rect.height < MIN - 0.5 : Math.min(rect.width, rect.height) < MIN - 0.5;
      if (small) out.targets.push({ label: label(el), w: Math.round(rect.width), h: Math.round(rect.height), name: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 30) });
    }
    // an interactive edge: its border (or its fill) must be told apart from the ground behind it
    const cs = getComputedStyle(el), g = el.parentElement ? ground(el.parentElement) : null;
    const bw = parseFloat(cs.borderTopWidth) || 0;
    if (g && bw > 0 && cs.borderTopStyle !== 'none') {
      const edge = parse(cs.borderTopColor), fill = parse(cs.backgroundColor);
      const e = edge ? ratio(over(edge, g), g) : 0;
      const f = fill && fill[3] > 0 ? ratio(over(fill, g), g) : 1;
      if (e < 3 && f < 3) out.edges.push({ label: label(el), ratio: +e.toFixed(2) });
    }
  }
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const el = n.parentElement;
    if (!n.textContent.trim() || !el || /^(SCRIPT|STYLE|TITLE)$/.test(el.tagName) || !visible(el) || el.closest('[aria-hidden="true"]')) continue;
    const g = ground(el); if (!g) continue;
    const cs = getComputedStyle(el), fg = parse(cs.color); if (!fg) continue;
    const eff = over(fg, g), r = ratio(eff, g);
    const px = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight, 10) >= 700;
    const need = (px >= 24 || (px >= 18.66 && bold)) ? 3 : 4.5;
    const key = label(el);
    if (r < need && !seen.has(key)) { seen.add(key); out.text.push({ label: key, ratio: +r.toFixed(2), need }); }
  }
  return out;
};

const overflow = () => {
  const label = (el) => el.tagName.toLowerCase() + (el.classList.length ? '.' + [...el.classList].slice(0, 2).join('.') : '');
  const clipped = [], beyond = [];
  const vw = document.documentElement.clientWidth;
  for (const el of document.body.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none') continue;
    if (/^(hidden|clip)$/.test(cs.overflowX) && el.scrollWidth > el.clientWidth + 1) clipped.push(label(el));
    if (/^(hidden|clip)$/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 1) clipped.push(label(el));
    const r = el.getBoundingClientRect();
    if (r.width && (r.right > vw + 1 || r.left < -1) && cs.position !== 'fixed') beyond.push(label(el));
  }
  return { sideways: document.documentElement.scrollWidth > window.innerWidth + 1, clipped: [...new Set(clipped)], beyond: [...new Set(beyond)] };
};

const FOCUSABLE = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[tabindex]:not([tabindex="-1"])';
const markFocusables = (sel) => {
  const label = (el) => el.tagName.toLowerCase() + (el.classList.length ? '.' + [...el.classList].slice(0, 2).join('.') : '') + (el.tagName === 'INPUT' && el.type ? `[${el.type}]` : '');
  const els = [...document.querySelectorAll(sel)].filter((el) => {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && !el.disabled;
  });
  els.forEach((el, i) => el.setAttribute('data-hx', String(i)));
  document.activeElement && document.activeElement.blur && document.activeElement.blur();
  return els.map((el) => label(el));
};
const prepare = (i) => {
  const el = document.querySelector(`[data-hx="${i}"]`);
  // window.scrollTo, not scrollIntoView: scrollIntoView moves the sequential-focus starting point
  // and would make the next Tab skip an element.
  const top = el.getBoundingClientRect().top + window.scrollY;
  window.scrollTo(0, Math.max(0, top - window.innerHeight / 2));
  const r = el.getBoundingClientRect();
  const vw = document.documentElement.clientWidth, vh = window.innerHeight;
  const x = Math.max(0, Math.floor(r.left - 8)), y = Math.max(0, Math.floor(r.top - 8));
  return { x, y, width: Math.max(1, Math.min(vw - x, Math.ceil(r.width + 16))), height: Math.max(1, Math.min(vh - y, Math.ceil(r.height + 16))) };
};
const activeInfo = () => {
  const el = document.activeElement;
  if (!el || el === document.body) return { idx: -1 };
  const cs = getComputedStyle(el);
  const col = (cs.outlineColor.match(/[\d.]+/g) || []);
  const alpha = col.length > 3 ? +col[3] : 1;
  const ring = (cs.boxShadow && cs.boxShadow !== 'none') || (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 && alpha > 0);
  return { idx: el.hasAttribute('data-hx') ? +el.getAttribute('data-hx') : -2, ring: !!ring };
};

// ---- run -----------------------------------------------------------------------------------
let manifest;
try {
  manifest = (await (await fetch(`${base}/manifest.json`)).json()).pages;
} catch (e) { console.error(`cannot read ${base}/manifest.json: ${e.message}`); process.exit(2); }
const todo = manifest.filter((p) => p.available && (!only || p.id.includes(only)));
const skipped = manifest.filter((p) => !p.available).map((p) => ({ id: p.id, reason: p.unavailable }));

const browser = await chromium.launch();
versions.chromium = browser.version();
const report = { generated: new Date().toISOString(), base, versions, viewports: VIEWPORTS.map((v) => v.tag), pages: [], skipped, errors: [] };
let axeSeriousOrCritical = 0;

try {
  for (const vp of VIEWPORTS) {
    const { tag, ...options } = vp;
    for (const p of todo) {
      const key = p.id;
      const rec = { id: key, viewport: tag, status: p.status, axe: {}, tabStops: 0, interactive: 0, targetsUnder44: 0, textBelowContrast: 0, edgesBelow3: 0, sideways: false, sideways200: false, clipped200: 0 };
      const context = await browser.newContext({ ...options, baseURL: base, javaScriptEnabled: !!p.needsJs });
      const page = await context.newPage();
      try {
        await page.goto(p.url, { waitUntil: 'load' });
        const stem = path.join(shots, `${safe(key)}__${tag}`);
        await page.screenshot({ path: `${stem}.png`, fullPage: true });

        log('goto+shot done');
        // axe-core. Running axe in a page with scripting disabled crashes Chromium, so it gets its own
        // JavaScript-enabled context on the same URL (the pages under test carry no script, so the
        // render is identical; pages that do carry script are flagged by script-present).
        const axeCtx = await browser.newContext({ ...options, baseURL: base, javaScriptEnabled: true });
        let axe;
        try {
          const axePage = await axeCtx.newPage();
          await axePage.goto(p.url, { waitUntil: 'load' });
          await axePage.evaluate(axeSource);
          axe = await axePage.evaluate(async () => {
            const r = await window.axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] }, resultTypes: ['violations'] });
            return r.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help }));
          });
        } finally { await axeCtx.close(); }
        rec.axe = { violations: axe.length, serious: axe.filter((v) => v.impact === 'serious').length, critical: axe.filter((v) => v.impact === 'critical').length, list: axe };
        for (const v of axe) if (v.impact === 'serious' || v.impact === 'critical') {
          axeSeriousOrCritical++;
          add(key, `axe-${v.id}`, tag, '', `${v.impact}: ${v.help} (${v.nodes} node(s))`);
        }

        log('axe done');
        // sideways scroll
        const o1 = await page.evaluate(overflow);
        rec.sideways = o1.sideways;
        if (o1.sideways) add(key, 'hscroll', tag, '', 'the page scrolls sideways');

        log('scroll done');
        // rendered targets, text contrast, control edges
        const m = await page.evaluate(measure, MIN_TARGET);
        rec.interactive = m.count; rec.targetsUnder44 = m.targets.length; rec.textBelowContrast = m.text.length; rec.edgesBelow3 = m.edges.length;
        for (const t of m.targets) add(key, 'target-size', tag, t.label, `${t.label} "${t.name}" is ${t.w}x${t.h}px; the floor is ${MIN_TARGET}px`);
        for (const t of m.text) add(key, 'text-contrast', tag, t.label, `${t.label} text is ${t.ratio}:1, needs ${t.need}:1`);
        for (const t of m.edges) add(key, 'control-edge', tag, t.label, `${t.label} edge is ${t.ratio}:1 against the page, needs 3:1`);

        log('measure done');
        // keyboard: Tab order, reachability, visible focus
        const labels = await page.evaluate(markFocusables, FOCUSABLE);
        const order = [];
        for (let i = 0; i < labels.length + 1 && labels.length; i++) {
          const next = i < labels.length ? i : -1;
          let clip = null, before = null;
          if (next >= 0) { clip = await page.evaluate(prepare, next); before = await page.screenshot({ clip }); }
          await page.keyboard.press('Tab');
          await page.waitForTimeout(260);   // the house transition is 160ms
          const info = await page.evaluate(activeInfo);
          if (info.idx < 0 && i >= labels.length) break;
          order.push(info.idx);
          if (info.idx >= 0) {
            const after = await page.screenshot({ clip: (await page.evaluate(() => { const r = document.activeElement.getBoundingClientRect(); const vw = document.documentElement.clientWidth, vh = window.innerHeight; const x = Math.max(0, Math.floor(r.left - 8)), y = Math.max(0, Math.floor(r.top - 8)); return { x, y, width: Math.max(1, Math.min(vw - x, Math.ceil(r.width + 16))), height: Math.max(1, Math.min(vh - y, Math.ceil(r.height + 16))) }; })) });
            const comparable = before && info.idx === next;
            const changed = comparable ? !before.equals(after) : true;
            const lab = labels[info.idx];
            if (comparable && !changed) add(key, 'focus-indicator-missing', tag, lab, `${lab} looks identical focused and unfocused`);
            else if (comparable && !info.ring) add(key, 'focus-ring-missing', tag, lab, `${lab} changes on focus but draws no outline or box-shadow ring`);
            if (i === 0) await page.screenshot({ path: `${stem}__focus1.png`, fullPage: true });
          }
        }
        rec.tabStops = order.filter((x) => x >= 0).length;
        const reached = new Set(order.filter((x) => x >= 0));
        labels.forEach((lab, i) => { if (!reached.has(i)) add(key, 'keyboard-unreachable', tag, lab, `${lab} is never reached with Tab`); });
        const seq = order.filter((x) => x >= 0);
        if (seq.some((x, i) => i && x < seq[i - 1])) add(key, 'keyboard-order', tag, '', `Tab order differs from DOM order: ${seq.join(',')}`);
        if (order.some((x) => x === -2)) add(key, 'keyboard-order', tag, 'unmarked', 'focus reached an element that is not in the focusable list');

        log('keyboard done');
        // 200% text: root font size doubled (rem/em text scales; px text does not, a known limit)
        await page.evaluate(() => document.documentElement.style.setProperty('font-size', '200%', 'important'));
        const o2 = await page.evaluate(overflow);
        rec.sideways200 = o2.sideways; rec.clipped200 = o2.clipped.length;
        if (o2.sideways) add(key, 'hscroll-200', tag, '', 'the page scrolls sideways at 200% text');
        for (const c of o2.clipped) add(key, 'clipped-200', tag, c, `${c} hides overflowing content at 200% text`);
        for (const c of o2.beyond) add(key, 'beyond-viewport-200', tag, c, `${c} extends past the viewport at 200% text`);
        await page.screenshot({ path: `${stem}__200.png`, fullPage: true });
      } catch (e) {
        report.errors.push({ id: key, viewport: tag, error: String(e && e.message || e).slice(0, 300) });
      } finally {
        await context.close();
      }
      report.pages.push(rec);
    }
    console.log(`checked ${todo.length} pages at ${tag}`);
  }
} finally { await browser.close(); }

report.findings = [...findings.values()].sort((a, b) => a.id.localeCompare(b.id));
report.summary = {
  pages: todo.length, viewports: VIEWPORTS.length, runs: report.pages.length, errors: report.errors.length, skipped: skipped.length,
  findings: report.findings.length, axeSeriousOrCritical,
  byRule: report.findings.reduce((acc, f) => { const r = f.rule.replace(/^axe-.*/, 'axe'); acc[r] = (acc[r] || 0) + 1; return acc; }, {}),
};
fs.writeFileSync(path.join(outdir, 'report.json'), JSON.stringify(report, null, 1));
console.log(JSON.stringify(report.summary));
if (report.errors.length) { console.error('page errors:\n' + report.errors.map((e) => `${e.id} ${e.viewport}: ${e.error}`).join('\n')); process.exit(3); }
process.exit(reportOnly || !report.findings.length ? 0 : 1);
