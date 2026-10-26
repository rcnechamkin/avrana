/* Avrana Media: the one first-party page script (MK-3, AVR-717). Served from Home's own origin at a versioned path
   (pwa.py), on shell pages only, with `defer`. Every page works without it: this only adds
     1. the navigation lens slide (sets data-at on the tab bar; the browser still navigates normally),
     2. registration of the service worker (/sw.js) and an update banner,
     3. a reload when a page comes back from the back/forward cache, so it goes through sign-in again.
   It reads no member data, uses no browser storage, builds no HTML from text and does nothing when its elements
   are absent. Inline preview behaviour (MK-4) is not here yet. */
(function () {
  'use strict';

  var script = document.currentScript;
  var swOff = !!script && script.getAttribute('data-sw') === 'off';

  function noop() {}

  /* 1. Lens. Contract: <nav class="tabbar" data-at="N"> holds <a class="tab"> links in order. The stylesheet moves
     the lens from data-at; motion is the stylesheet's business, so with reduced motion nothing is touched. */
  function lens() {
    var nav = document.querySelector('nav.tabbar');
    if (!nav) return;
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    nav.addEventListener('click', function (event) {
      if (event.defaultPrevented || event.button !== 0 ||
          event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      var from = event.target;
      var tab = from && typeof from.closest === 'function' ? from.closest('a.tab') : null;
      if (!tab || !nav.contains(tab)) return;
      if (tab.getAttribute('aria-current') === 'page' || tab.hasAttribute('download')) return;
      var target = tab.getAttribute('target');
      if (target && target !== '_self') return;
      var tabs = nav.querySelectorAll('a.tab');
      var at = Array.prototype.indexOf.call(tabs, tab);
      if (at >= 0) nav.setAttribute('data-at', String(at));
    });
  }

  /* 3. A page restored from the back/forward cache is reloaded, so it passes the sign-in check again. */
  function bfcache() {
    window.addEventListener('pageshow', function (event) {
      if (event.persisted) window.location.reload();
    });
  }

  /* 2. Service worker. The update banner appears only when a new worker is waiting while an old one controls the
     page (not on the first install). The button asks the waiting worker to take over, then the page reloads once. */
  function banner(registration) {
    if (document.querySelector('.update-banner')) return;
    var box = document.createElement('div');
    box.className = 'update-banner';
    box.setAttribute('role', 'status');
    var text = document.createElement('span');
    text.textContent = 'A new version of Avrana Media is ready.';
    var button = document.createElement('button');
    button.type = 'button';
    button.textContent = 'Reload';
    var asked = false;
    navigator.serviceWorker.addEventListener('controllerchange', function () {
      if (asked) window.location.reload();
    });
    button.addEventListener('click', function () {
      asked = true;
      if (registration.waiting) registration.waiting.postMessage({ type: 'SKIP_WAITING' });
      else window.location.reload();
    });
    box.appendChild(text);
    box.appendChild(button);
    document.body.appendChild(box);
  }

  function watch(registration) {
    function waiting() {
      if (registration.waiting && navigator.serviceWorker.controller) banner(registration);
    }
    waiting();
    registration.addEventListener('updatefound', function () {
      var worker = registration.installing;
      if (!worker) return;
      worker.addEventListener('statechange', function () {
        if (worker.state === 'installed') waiting();
      });
    });
  }

  function register() {
    try {
      navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' })
        .then(watch, noop);
    } catch (error) { /* a browser that refuses: the site works without it */ }
  }

  function worker() {
    if (!('serviceWorker' in navigator)) return;
    if (swOff) {
      /* Kill switch: remove any worker an earlier visit installed, and the files it stored (names starting
         "avrana-"). /sw.js serves a self-destructing worker too, for browsers that have not loaded this page yet. */
      try {
        navigator.serviceWorker.getRegistrations().then(function (list) {
          list.forEach(function (one) { one.unregister().then(noop, noop); });
        }, noop);
        if (window.caches) {
          window.caches.keys().then(function (keys) {
            keys.forEach(function (key) { if (key.indexOf('avrana-') === 0) window.caches.delete(key).then(noop, noop); });
          }, noop);
        }
      } catch (error) { /* nothing to do */ }
      return;
    }
    if (document.readyState === 'complete') register();
    else window.addEventListener('load', register);
  }

  lens();
  bfcache();
  worker();
})();
