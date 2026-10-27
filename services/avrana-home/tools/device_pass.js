// Automated iPhone-size device pass (AVR-585): responsiveness, touch targets, axe (WCAG 2.2 AA), playback hand-offs
// and the way back, and installation (manifest, icons, Apple meta, service worker, offline page). Chrome's iPhone
// emulation, not Safari: it does not replace the real-device pass (M3-DEVICE-REVIEW.md Step C).
//
//   node services/avrana-home/tools/device_pass.js <out-dir>     (dev stack: run_dev.py --dev-identity --port 8099)
//
// UI_TOOLING: a folder with node_modules/playwright and node_modules/axe-core (default: the owner's .ui-tooling).
// DEVICE_PASS_BASE: the site (default http://127.0.0.1:8099). Synthetic data only; never point it at real members.
// Note: touch targets made by a stretched ::after link (search rows, rail cards) read small here; their real tap
// area is the whole row.
const path = require('path');
const fs = require('fs');
const T = (process.env.UI_TOOLING || 'C:/Users/cnech/Projects/avrana-homelab/.ui-tooling').split('\\').join('/') + '/node_modules/';
const { chromium, devices } = require(T + 'playwright');
const AXE = fs.readFileSync(T + 'axe-core/axe.min.js', 'utf8');
const BASE = process.env.DEVICE_PASS_BASE || 'http://127.0.0.1:8099';
const OUT = process.argv[2];
const PAGES = ['/', '/library', '/search?q=synthetic', '/me', '/account', '/help', '/help/trouble'];
const HANDOFF = /^https:\/\/(watch|listen|read|books|request)\.avrana\.net\//;
const report = { viewports: {}, playback: {}, install: {}, axe: {} };

async function newCtx(b, dev, extra = {}) {
  const ctx = await b.newContext({ ...dev, ...extra });
  const p = await ctx.newPage();
  await p.goto(BASE + '/_dev/identity/member-a');
  return { ctx, p };
}

(async () => {
  const b = await chromium.launch({ channel: 'chrome' });
  const vps = {
    'iPhone SE (375)': devices['iPhone SE'], 'iPhone 15 (393)': devices['iPhone 15'],
    'iPhone 15 Pro Max (430)': devices['iPhone 15 Pro Max'],
    'narrow 320': { ...devices['iPhone SE'], viewport: { width: 320, height: 640 } },
    'iPhone 15 landscape': devices['iPhone 15 landscape'],
  };
  // 1. Responsiveness, touch targets, console errors
  for (const [name, dev] of Object.entries(vps)) {
    const { ctx, p } = await newCtx(b, dev);
    const errors = [];
    p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    const rows = [];
    for (const url of PAGES) {
      const r = await p.goto(BASE + url, { waitUntil: 'networkidle' });
      const m = await p.evaluate(() => {
        const vw = window.innerWidth, over = document.documentElement.scrollWidth - vw;
        const small24 = [], small44 = [];
        for (const el of document.querySelectorAll('a[href], button, input, summary, [role=button]')) {
          const s = getComputedStyle(el);
          if (s.display === 'none' || s.visibility === 'hidden') continue;
          const rc = el.getBoundingClientRect();
          if (!rc.width || !rc.height) continue;
          const inline = el.closest('p, li') && s.display === 'inline';     // WCAG 2.5.8 inline exception
          const label = (el.innerText || el.getAttribute('aria-label') || el.tagName).trim().slice(0, 30);
          if (!inline && (rc.width < 24 || rc.height < 24)) small24.push(label);
          else if (!inline && (rc.width < 44 || rc.height < 44)) small44.push(label);
        }
        return { over, small24, small44 };
      });
      rows.push({ url, status: r.status(), overflowPx: m.over, under24: m.small24, under44: m.small44 });
    }
    await p.goto(BASE + '/', { waitUntil: 'networkidle' });
    await p.screenshot({ path: path.join(OUT, name.replace(/[^a-z0-9]+/gi, '_') + '-home.png') });
    report.viewports[name] = { rows, consoleErrors: errors };
    await ctx.close();
  }
  // 2. Accessibility (axe, WCAG 2.2 AA plus best practice) at iPhone 15 with reduced motion
  {
    const { ctx, p } = await newCtx(b, devices['iPhone 15'], { reducedMotion: 'reduce', bypassCSP: true });
    for (const url of PAGES) {
      await p.goto(BASE + url, { waitUntil: 'networkidle' });
      await p.addScriptTag({ content: AXE });
      report.axe[url] = await p.evaluate(async () => (await axe.run(document, {
        runOnly: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'] }))
        .violations.map(v => ({ id: v.id, impact: v.impact, n: v.nodes.length, target: v.nodes[0].target.join(' ') })));
    }
    await ctx.close();
  }
  // 3. Playback navigation: hand-offs, a title page, the way back
  {
    const { ctx, p } = await newCtx(b, devices['iPhone 15']);
    await p.goto(BASE + '/', { waitUntil: 'networkidle' });
    const links = await p.$$eval('a[href]', as => as.map(a => ({
      text: a.innerText.trim().replace(/\s+/g, ' ').slice(0, 40), href: a.href })));
    const handoffs = links.filter(l => /avrana\.net/.test(l.href));
    const titleLinks = links.filter(l => l.href.startsWith('http://127.0.0.1:8099/title/') || /^http:\/\/127\.0\.0\.1:8099\/(watch|listen|read|books)\/[^?]/.test(l.href));
    report.playback.homeHandoffs = handoffs.length;
    report.playback.badHandoffs = handoffs.filter(l => !HANDOFF.test(l.href) && !/^https:\/\/avrana\.net\//.test(l.href));
    report.playback.handoffLabels = [...new Set(handoffs.map(l => l.text))].slice(0, 8);
    report.playback.titleLinks = titleLinks.slice(0, 3).map(l => new URL(l.href).pathname);
    if (titleLinks.length) {
      const r = await p.goto(titleLinks[0].href, { waitUntil: 'networkidle' });
      const t = await p.evaluate(() => ({
        h1: (document.querySelector('h1') || {}).innerText,
        actions: [...document.querySelectorAll('a[href]')].map(a => ({ t: a.innerText.trim(), h: a.href }))
          .filter(a => /avrana\.net/.test(a.h)).slice(0, 3),
        homeLink: !!document.querySelector('a[href="/"]'),
      }));
      report.playback.titlePage = { status: r.status(), ...t };
      await p.screenshot({ path: path.join(OUT, 'title-page.png') });
      await p.click('a[href="/"] >> nth=0');
      await p.waitForLoadState('networkidle');
      report.playback.backHome = new URL(p.url()).pathname;
    }
    await ctx.close();
  }
  // 4. Installation: manifest, icons, Apple meta, service worker, offline page
  {
    const { ctx, p } = await newCtx(b, devices['iPhone 15']);
    await p.goto(BASE + '/', { waitUntil: 'networkidle' });
    const meta = await p.evaluate(() => {
      const q = s => document.querySelector(s);
      return {
        manifest: (q('link[rel=manifest]') || {}).href || null,
        appleIcon: (q('link[rel=apple-touch-icon]') || {}).href || null,
        appleCapable: (q('meta[name=apple-mobile-web-app-capable],meta[name=mobile-web-app-capable]') || {}).content || null,
        appleTitle: (q('meta[name=apple-mobile-web-app-title]') || {}).content || null,
        themeColor: (q('meta[name=theme-color]') || {}).content || null,
        viewport: (q('meta[name=viewport]') || {}).content || null,
      };
    });
    report.install.meta = meta;
    if (meta.manifest) {
      const m = await (await p.request.get(meta.manifest)).json();
      report.install.manifest = { name: m.name, short_name: m.short_name, display: m.display, start_url: m.start_url,
        id: m.id, icons: m.icons.map(i => i.sizes + ' ' + (i.purpose || '')) };
      report.install.iconStatus = [];
      for (const i of m.icons) report.install.iconStatus.push((await p.request.get(new URL(i.src, BASE).href)).status());
    }
    if (meta.appleIcon) report.install.appleIconStatus = (await p.request.get(meta.appleIcon)).status();
    await p.waitForTimeout(2000);
    report.install.serviceWorker = await p.evaluate(async () => {
      const r = await navigator.serviceWorker.getRegistration();
      return r ? (r.active ? 'active' : 'installing') : 'none';
    });
    await p.reload({ waitUntil: 'networkidle' });
    await ctx.setOffline(true);
    try {
      await p.goto(BASE + '/library', { waitUntil: 'load', timeout: 8000 });
      report.install.offlinePage = (await p.innerText('body')).replace(/\s+/g, ' ').slice(0, 140);
    } catch (e) { report.install.offlinePage = 'ERROR ' + e.message.split('\n')[0]; }
    await p.screenshot({ path: path.join(OUT, 'offline.png') });
    await ctx.close();
  }
  await b.close();
  fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 1));
  console.log(JSON.stringify(report, null, 1));
})().catch(e => { console.error(e); process.exit(1); });
