/* Avrana Media: the one first-party page script (MK-3, AVR-717). Served from Home's own origin at a versioned path
   (pwa.py), on shell pages only, with `defer`. Every page works without it: this only adds
     1. the navigation lens slide (sets data-at on the tab bar; the browser still navigates normally),
     2. registration of the service worker (/sw.js) and an update banner,
     3. a reload when a page comes back from the back/forward cache, so it goes through sign-in again,
     4. the art flight into a title page during a page-to-page transition, and 5. where the browser exposes the
        active transition, ending it on the first press, so a touch tap then reaches the page (MK-6, AVR-720).
   It reads no member data, uses no browser storage, builds no HTML from text and does nothing when its elements
   are absent. Inline preview behaviour (MK-4) is not here yet. */
(function () {
  'use strict';

  var script = document.currentScript;
  var swOff = !!script && script.getAttribute('data-sw') === 'off';

  function noop() {}

  /* 1. Lens. Contract: <nav class="tabbar" data-at="N"> holds <a class="tab"> links in order. The stylesheet moves
     the lens from data-at; motion is the stylesheet's business, so with reduced motion nothing is touched (the
     preference is read at each click, so a change while the page is open counts). When the page is left, data-at
     goes back to the value the server printed, so the page kept in the back/forward cache shows the right tab. */
  function lens() {
    var nav = document.querySelector('nav.tabbar');
    if (!nav) return;
    var printed = nav.getAttribute('data-at');
    window.addEventListener('pagehide', function () {
      if (printed === null) nav.removeAttribute('data-at');
      else nav.setAttribute('data-at', printed);
    });
    nav.addEventListener('click', function (event) {
      if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      if (event.defaultPrevented || event.button !== 0 ||
          event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      var from = event.target;
      var tab = from && typeof from.closest === 'function' ? from.closest('a.tab') : null;
      if (!tab || !nav.contains(tab)) return;
      if (tab.getAttribute('aria-current') === 'page' || tab.hasAttribute('download')) return;
      var target = tab.getAttribute('target');
      if (target && target !== '_self') return;
      /* A link to another place on this same page (the URL differs only by its hash) does not load a page: the browser
         just scrolls, aria-current stays where it is and no pagehide comes, so the lens stays on the printed tab. */
      if (tab.origin + tab.pathname + tab.search === window.location.origin + window.location.pathname + window.location.search) return;
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
    /* The live region goes into the page empty and gets its words a moment later, so screen readers announce it. */
    var text = document.createElement('span');
    text.className = 'update-banner-text';
    text.setAttribute('role', 'status');
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'update-banner-button';
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
    window.setTimeout(function () {
      text.textContent = 'A new version of Avrana Media is ready.';
    }, 100);
  }

  function watch(registration) {
    if (!registration) return;
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

  /* 4. Art flight (MK-6, AVR-720). The stylesheet turns page-to-page transitions on (never with Reduce Motion, so then
     no transition reaches this) and names the title page's one art frame. When the page being left links to that
     title page, the art beside the followed link (the first page's large art, or a search result's) takes the same
     name, so the browser carries one picture into the other. Exactly one element is named, only while the old page
     is captured (pageswap comes just before that); the class is the stylesheet's, so no style is written here. A
     title page names nothing more, and art that is off screen or hidden is left out. Nothing delays, stops or
     changes the navigation; a browser without these events never runs any of it. */
  function visible(element) {
    var box = element.getBoundingClientRect();
    return box.width > 0 && box.height > 0 && box.bottom > 0 && box.top < window.innerHeight &&
      box.right > 0 && box.left < window.innerWidth;
  }

  function tag(art, transition) {
    art.classList.add('k-flight');
    transition.finished.then(function () { art.classList.remove('k-flight'); }, noop);
  }

  function flight() {
    window.addEventListener('pageswap', function (event) {
      var transition = event.viewTransition;
      var entry = event.activation ? event.activation.entry : null;
      if (!transition || !entry || !entry.url || document.querySelector('.title-page .frame')) return;
      var to;
      try { to = new URL(entry.url); } catch (error) { return; }
      if (to.origin !== window.location.origin || to.pathname.indexOf('/title/') !== 0) return;
      var links = document.querySelectorAll('a[href]');
      for (var i = 0; i < links.length; i++) {
        var link = links[i];
        if (link.origin + link.pathname + link.search !== to.origin + to.pathname + to.search) continue;
        var holder = link.closest('.hero, li');
        var art = holder ? holder.querySelector('.frame') : null;
        if (art && visible(art)) { tag(art, transition); return; }
      }
    });
  }

  /* 5. Interruptible (MK-6). While a page-to-page transition runs, the browser shows pictures of the two pages, so a
     press lands on nothing. Where the browser exposes the active transition (document.activeViewTransition, or the
     pagereveal event when this deferred script happens to run before it), the first press ends it at once (the new
     page is already there, and that is what shows); a touch tap then reaches what is under the finger. A mouse or pen
     click during the 200 ms may still be lost, and so may a tap where the transition is not exposed. Keys and the
     browser's own back and forward navigate regardless. */
  function interrupt() {
    var revealed = null;
    window.addEventListener('pagereveal', function (event) {
      revealed = event.viewTransition || null;
      if (revealed) revealed.finished.then(function () { revealed = null; }, noop);
    });
    document.addEventListener('pointerdown', function () {
      var transition = document.activeViewTransition || revealed;
      if (transition) transition.skipTransition();
    }, { capture: true, passive: true });
  }

  lens();
  bfcache();
  worker();
  flight();
  interrupt();
})();
