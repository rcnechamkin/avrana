// Behaviour checks for the Avrana Media service worker (MK-3, AVR-717). No browser and no server: the worker source
// that Home serves at /sw.js is run inside a Node `vm` context with fake `caches`, `fetch`, `Request` and `Response`,
// and its install, activate, message and fetch handlers are driven directly. Development tool, synthetic data only.
// Normally started by pwa_run.py, which writes the files it is given:
//   node tests/ui/harness/pwa_sw_check.mjs --worker W.js --self-destruct S.js
import fs from 'node:fs';
import vm from 'node:vm';

const args = process.argv.slice(2);
const opt = (n) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : undefined; };
const workerSrc = fs.readFileSync(opt('--worker'), 'utf8');
const destructSrc = fs.readFileSync(opt('--self-destruct'), 'utf8');
const ORIGIN = 'https://home.test';

const results = [];
const ok = (name, cond, extra = '') => { results.push(!!cond); console.log(cond ? 'PASS' : 'FAIL', name, cond ? '' : extra); };

function makeEnv(src) {
  const handlers = {};
  const stores = new Map();                       // cache name -> Map(absolute url -> response)
  const log = { skipWaiting: 0, deleted: [], unregistered: 0, claimed: 0, fetched: [] };
  const abs = (x) => new URL(typeof x === 'string' ? x : x.url, ORIGIN).href;
  const store = (name) => { if (!stores.has(name)) stores.set(name, new Map()); return stores.get(name); };
  const env = { handlers, stores, log, fetchImpl: async () => { throw new Error('no fetch expected'); } };
  const sandbox = {
    self: {
      addEventListener: (type, fn) => { handlers[type] = fn; },
      location: { origin: ORIGIN },
      skipWaiting: () => { log.skipWaiting += 1; },
      registration: { unregister: async () => { log.unregistered += 1; return true; } },
      clients: { claim: () => { log.claimed += 1; } },
    },
    caches: {
      open: async (name) => {
        const s = store(name);
        return { put: async (req, res) => { s.set(abs(req), res); }, match: async (req) => s.get(abs(req)),
                 keys: async () => [...s.keys()].map((url) => ({ url })) };
      },
      keys: async () => [...stores.keys()],
      delete: async (name) => { log.deleted.push(name); return stores.delete(name); },
    },
    fetch: (req) => { log.fetched.push(req); return env.fetchImpl(req); },
    Request: class { constructor(url, init = {}) { this.url = abs(url); this.method = 'GET'; this.mode = 'cors'; Object.assign(this, init); } },
    Response: { error: () => ({ type: 'error', status: 0, isErrorResponse: true }) },
    URL,
  };
  env.ctx = vm.createContext(sandbox);
  vm.runInContext(src, env.ctx);
  env.run = (code) => vm.runInContext(code, env.ctx);
  env.networkError = () => env.run("new TypeError('Failed to fetch')");        // from the worker's own realm
  env.otherError = () => env.run("new Error('aborted')");
  return env;
}

// A response as the worker's guard sees it.
function res(o = {}) {
  const r = { status: 200, type: 'basic', redirected: false, ctype: 'text/plain', vary: null, size: 1000, ...o };
  r.headers = { get: (n) => ({ 'content-type': r.ctype, vary: r.vary })[n.toLowerCase()] ?? null };
  r.clone = () => ({ blob: async () => ({ size: r.size }) });
  return r;
}

const nav = (path) => ({ mode: 'navigate', method: 'GET', url: ORIGIN + path });
const sub = (path, o = {}) => ({ mode: 'no-cors', method: 'GET', url: (o.origin || ORIGIN) + path, ...o });

async function runInstall(env) {
  let waited;
  env.handlers.install({ waitUntil: (p) => { waited = p; } });
  try { await waited; return null; } catch (e) { return e; }
}
async function runActivate(env) {
  let waited;
  env.handlers.activate({ waitUntil: (p) => { waited = p; } });
  await waited;
}
function runFetch(env, request) {
  const ev = { request, responded: false, respondWith(p) { ev.responded = true; ev.promise = Promise.resolve(p); } };
  env.handlers.fetch(ev);
  return ev;
}
const settle = async (p) => { try { return { value: await p }; } catch (error) { return { error }; } };

// ---------------------------------------------------------------------------------------------------------------
const probe = makeEnv(workerSrc);
const ALLOW = probe.run('ALLOW');
const CACHE = probe.run('CACHE');
const paths = Object.keys(ALLOW);
const goodFor = (path, o = {}) => res({ ctype: ALLOW[path], ...o });
const fontPath = paths.find((p) => /woff2$/.test(p));
ok('allow-list has the script, offline page, brand and icons', paths.includes('/offline') && paths.some((p) => /^\/static\/home\.[0-9a-f]{12}\.js$/.test(p)) && fontPath && paths.some((p) => /^\/icons\//.test(p)), paths.join());
ok('allow-list holds no member route', !paths.some((p) => /^\/(art|title|search|account|help|watch|read|request|home\.json|manifest|signout|sw\.js)/.test(p) || p === '/'), paths.join());
ok('cache name is avrana-shell-<12 hex>', /^avrana-shell-[0-9a-f]{12}$/.test(CACHE), CACHE);

// ---- install --------------------------------------------------------------------------------------------------
{
  const env = makeEnv(workerSrc);
  env.fetchImpl = async (req) => goodFor(new URL(req.url).pathname);
  const err = await runInstall(env);
  ok('install stores every allow-listed file', err === null && env.stores.get(CACHE)?.size === paths.length, String(err));
  ok('install requests use redirect "error", cache "reload" and credentials "same-origin"', env.log.fetched.length === paths.length && env.log.fetched.every((r) => r.redirect === 'error' && r.cache === 'reload' && r.credentials === 'same-origin' && r.method === 'GET'));
  ok('install does not skipWaiting or claim', env.log.skipWaiting === 0 && env.log.claimed === 0);
}
const badResponses = {
  'redirected response': () => res({ redirected: true }),
  'status 404': () => res({ status: 404 }),
  'status 302': () => res({ status: 302 }),
  'status 206': () => res({ status: 206 }),
  'opaque response': () => res({ type: 'opaque' }),
  'opaqueredirect response': () => res({ type: 'opaqueredirect', status: 0 }),
  'cors response': () => res({ type: 'cors' }),
  'Vary: *': () => res({ vary: '*' }),
  'oversize body': () => res({ size: 524289 }),
  'empty body': () => res({ size: 0 }),
};
for (const [label, make] of Object.entries(badResponses)) {
  const env = makeEnv(workerSrc);
  // the bad one has the right content type, to prove it is refused for its own reason
  const bad = make();
  bad.ctype = ALLOW[fontPath];
  env.fetchImpl = async (req) => { const p = new URL(req.url).pathname; return p === fontPath ? bad : goodFor(p); };
  const err = await runInstall(env);
  ok(`install refuses ${label}, stores nothing`, err !== null && !env.stores.has(CACHE), String(err));
}
{
  const env = makeEnv(workerSrc);
  env.fetchImpl = async (req) => { const p = new URL(req.url).pathname; return p === fontPath ? goodFor(p, { ctype: 'text/html; charset=utf-8' }) : goodFor(p); };
  ok('install refuses a login page served as a font', (await runInstall(env)) !== null && !env.stores.has(CACHE));
}
{
  const env = makeEnv(workerSrc);
  env.fetchImpl = async (req) => { if (new URL(req.url).pathname === '/offline') throw env.networkError(); return goodFor(new URL(req.url).pathname); };
  ok('install fails when a fetch throws (redirect "error" is a network error)', (await runInstall(env)) !== null && !env.stores.has(CACHE));
}
{
  const env = makeEnv(workerSrc);
  env.fetchImpl = async (req) => goodFor(new URL(req.url).pathname, { ctype: ALLOW[new URL(req.url).pathname] + '; charset=utf-8' });
  ok('install accepts the expected type with a charset parameter', (await runInstall(env)) === null);
}

// ---- activate / message -----------------------------------------------------------------------------------------
{
  const env = makeEnv(workerSrc);
  env.stores.set('avrana-shell-old', new Map()); env.stores.set('avrana-other', new Map());
  env.stores.set(CACHE, new Map()); env.stores.set('someone-elses-cache', new Map());
  await runActivate(env);
  ok('activate deletes old avrana-* caches only', !env.stores.has('avrana-shell-old') && !env.stores.has('avrana-other') && env.stores.has(CACHE) && env.stores.has('someone-elses-cache'), [...env.stores.keys()].join());
  ok('activate does not claim clients', env.log.claimed === 0);
  env.handlers.message({ data: { type: 'SKIP_WAITING' } });
  ok('exact SKIP_WAITING message calls skipWaiting', env.log.skipWaiting === 1);
  for (const data of [{ type: 'SKIP_WAITING', extra: 1 }, { type: 'other' }, 'SKIP_WAITING', null, undefined, 42, { type: ['SKIP_WAITING'] }]) env.handlers.message({ data });
  ok('every other message is ignored', env.log.skipWaiting === 1);
}

// ---- navigations ------------------------------------------------------------------------------------------------
{
  const env = makeEnv(workerSrc);
  env.fetchImpl = async (req) => goodFor(new URL(req.url).pathname);
  await runInstall(env);
  const offline = env.stores.get(CACHE).get(ORIGIN + '/offline');
  const request = nav('/account');
  for (const [label, value] of [['a 302 (opaque redirect)', res({ type: 'opaqueredirect', status: 0 })], ['a 401', res({ status: 401 })], ['a 403', res({ status: 403 })],
    ['a 404', res({ status: 404 })], ['a 500', res({ status: 500 })], ['a 200 page', res({ status: 200, ctype: 'text/html' })]]) {
    env.log.fetched.length = 0;
    env.fetchImpl = async () => value;
    const ev = runFetch(env, request);
    const out = await settle(ev.promise);
    ok(`navigation answered with ${label} is returned untouched, not the offline page`, ev.responded && out.value === value && out.value !== offline && env.log.fetched[0] === request && env.log.fetched.length === 1);
  }
  env.fetchImpl = async () => { throw env.networkError(); };
  let out = await settle(runFetch(env, request).promise);
  ok('navigation with a network TypeError answers the cached offline page', out.value === offline && offline !== undefined);
  env.fetchImpl = async () => { throw env.otherError(); };
  out = await settle(runFetch(env, request).promise);
  ok('navigation failing for another reason is not turned into the offline page', out.error !== undefined && out.value === undefined);
  // no cached offline page (cache lost): an error response, never a made-up page
  env.stores.delete(CACHE);
  env.fetchImpl = async () => { throw env.networkError(); };
  out = await settle(runFetch(env, request).promise);
  ok('network failure with no stored offline page gives a network error response', out.value && out.value.isErrorResponse === true);
}
{
  const env = makeEnv(workerSrc);
  for (const p of ['/signout', '/signout/', '//signout', '///signout/', '/outpost.goauthentik.io/sign_out', '//outpost.goauthentik.io/x', '/outpost.goauthentik.io/start', '/outpost.goauthentik.io/']) {
    const ev = runFetch(env, nav(p));
    ok(`navigation to ${p} is left to the browser (no respondWith, no fetch)`, !ev.responded && env.log.fetched.length === 0);
  }
  for (const p of ['/signouts', '/signout/x', '/outpost.goauthentik.io', '/x/outpost.goauthentik.io/y']) {
    env.fetchImpl = async () => res({ status: 200 });
    const ev = runFetch(env, nav(p));
    ok(`navigation to ${p} is handled like any page`, ev.responded);
  }
}

// ---- everything that is not a navigation --------------------------------------------------------------------------
{
  const env = makeEnv(workerSrc);
  env.fetchImpl = async (req) => goodFor(new URL(req.url).pathname);
  await runInstall(env);
  env.log.fetched.length = 0;
  const left = ['/', '/home.json', '/search', '/account', '/art/jellyfin/primary/aaaa', '/title/jellyfin/aaaa', '/manifest.webmanifest', '/signout', '/readyz',
    '/healthz', '/sw.js', '/offline', fontPath + '?v=1', fontPath + '/x', '/static/home.000000000000.js'];
  ok('member data, manifest, sw.js, /offline and near-misses get no respondWith', left.every((p) => !runFetch(env, sub(p)).responded) && env.log.fetched.length === 0, left.filter((p) => runFetch(env, sub(p)).responded).join());
  ok('non-GET requests get no respondWith', !runFetch(env, sub(fontPath, { method: 'POST' })).responded);
  ok('a cross-origin copy of an allow-listed path gets no respondWith', !runFetch(env, sub(fontPath, { origin: 'https://other.test' })).responded);
  const ev = runFetch(env, sub(fontPath));
  const out = await settle(ev.promise);
  ok('an allow-listed file is served from the store without touching the network', ev.responded && out.value === env.stores.get(CACHE).get(ORIGIN + fontPath) && env.log.fetched.length === 0);
}
{
  // a miss: stored only when the guard accepts it
  const env = makeEnv(workerSrc);
  const goodOne = goodFor(fontPath);
  env.fetchImpl = async () => goodOne;
  let out = await settle(runFetch(env, sub(fontPath)).promise);
  ok('a guarded miss is returned and stored (a clone of it)', out.value === goodOne && env.stores.get(CACHE)?.has(ORIGIN + fontPath) === true);
  const env2 = makeEnv(workerSrc);
  for (const [label, bad] of [['redirected', goodFor(fontPath, { redirected: true })], ['non-200', goodFor(fontPath, { status: 503 })], ['wrong type', goodFor(fontPath, { ctype: 'text/html' })], ['opaque', goodFor(fontPath, { type: 'opaque' })]]) {
    env2.fetchImpl = async () => bad;
    out = await settle(runFetch(env2, sub(fontPath)).promise);
    ok(`a ${label} miss is returned to the page but never stored`, out.value === bad && !(env2.stores.get(CACHE)?.has(ORIGIN + fontPath)));
  }
}

// ---- the kill-switch worker --------------------------------------------------------------------------------------------
{
  const env = makeEnv(destructSrc);
  env.stores.set('avrana-shell-x', new Map()); env.stores.set('keep-me', new Map());
  ok('self-destruct worker has no fetch handler', env.handlers.fetch === undefined);
  env.handlers.install({ waitUntil: () => {} });
  ok('self-destruct worker skips waiting on install', env.log.skipWaiting === 1);
  await runActivate(env);
  ok('self-destruct worker deletes avrana-* caches only and unregisters', !env.stores.has('avrana-shell-x') && env.stores.has('keep-me') && env.log.unregistered === 1);
}

const failed = results.filter((r) => !r).length;
console.log(`\nservice worker logic: ${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
