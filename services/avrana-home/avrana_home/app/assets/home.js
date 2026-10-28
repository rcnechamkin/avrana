/* Avrana Media: the one first-party page script (MK-3, AVR-717). Served from Home's own origin at a versioned path
   (pwa.py), on shell pages only, with `defer`. Every page works without it: this only adds
     1. the navigation lens slide (sets data-at on the tab bar; the browser still navigates normally),
     2. registration of the service worker (/sw.js) and an update banner,
     3. a reload when a page comes back from the back/forward cache, so it goes through sign-in again,
     4. the art flight into a title page during a page-to-page transition, 5. where the browser exposes the
        active transition, ending it on the first press, so a touch tap then reaches the page (MK-6, AVR-720), and
     6. art that fades in once it has loaded, and the letter back in its frame if an image fails (owner review
        2026-10-27),
     7. a press state on iPhone (Safari shows :active only when the page listens for touches),
     8. the title sheet: a title link on a shell page opens the title page as a sheet that grows out of the art that
        was tapped, over the page, which stays as it was underneath (owner decision 2026-10-27). It is the one request
        this script makes and the one place it prevents the browser's navigation: it fetches the same-origin title
        page the link names, with the member's own cookies, and shows that page's title section. Anything unexpected
        (a redirect, an error, an older browser) and the link simply navigates, as it does with the script off, and
     9. chrome that follows the scroll: two marks on <html> the stylesheet reads (part 9), and
     10. the Library's layout menu: choosing a layout rearranges the cards in place, each gliding from where it was
        to where it now is, and puts the choice in the address (owner decision 2026-10-27).
   It uses no browser storage, writes no HTML from text and does nothing when its elements are absent; only the
   title sheet (8) reads member data, and only the title page the member asked for. Inline preview behaviour (MK-4) is not here yet. */
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

  /* 6. Art arrival. An image not yet loaded gets the stylesheet's k-wait class (hidden) until it loads, so it fades
     in; one already loaded is left alone. An image that fails is taken out of its frame, so the frame's letter shows
     again (the stylesheet hides the letter only while the frame holds an image). Lazy images below the fold are
     covered too: they are simply incomplete until the browser fetches them. */
  function arrive(root) {
    var images = (root || document).querySelectorAll('img.art');
    Array.prototype.forEach.call(images, function (img) {
      function done() { img.classList.remove('k-wait'); }
      function failed() { if (img.parentNode) img.parentNode.removeChild(img); }
      if (img.complete) {
        if (img.getAttribute('src') && img.naturalWidth === 0) failed();
        return;
      }
      img.classList.add('k-wait');
      img.addEventListener('load', done);
      img.addEventListener('error', failed);
    });
  }

  /* 7. iPhone press state. Safari applies :active to a tapped element only when the document has a touch listener;
     this one does nothing else. */
  function press() {
    document.addEventListener('touchstart', noop, { passive: true });
  }

  /* 8. Title sheet. Contract: a link on a shell page (one with the tab bar, and not itself a title page) whose
     same-origin path starts /title/. On a plain press it opens <dialog class="k-sheet"> (modal: focus stays inside,
     Escape closes, the page behind is inert), pushes the title's own URL (so Back closes it, and a reload or a shared
     link is the full title page), and grows a card from the tapped art to the sheet. The art stands in, blurred,
     until the title page arrives; its .title-page section (or .title-down, when the library is unavailable) is
     brought in without any script, frame, object or form it might contain. Closing (the close button, Escape, a press
     outside, Back, or a downward pull from the top of the sheet, which follows the finger) shrinks the card back into
     the art when that is still on screen, or lets it fall away. With Reduce Motion everything happens at once. No
     style is written: movement is Web Animations, the look is the stylesheet's. */
  var EASE_SHEET = 'cubic-bezier(0.32, 0.72, 0, 1)';
  var OPEN_MS = 380;
  var CLOSE_MS = 300;

  function still() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function svgClose() {
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('width', '20');
    svg.setAttribute('height', '20');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    var path = document.createElementNS(ns, 'path');
    path.setAttribute('d', 'M6 6l12 12M18 6 6 18');
    svg.appendChild(path);
    return svg;
  }

  function sheet() {
    if (!document.querySelector('nav.tabbar') || document.querySelector('.title-page, .title-down')) return;
    if (typeof window.HTMLDialogElement !== 'function' || typeof window.fetch !== 'function' ||
        typeof window.DOMParser !== 'function' || !window.history || !window.history.pushState) return;
    if (typeof document.createElement('div').animate !== 'function') return;

    var dialog = null, scrim = null, card = null, body = null;
    var origin = null, opener = null, pageTitle = document.title, busy = false, pushed = false, generation = 0, pendingFrom = null;

    function build() {
      dialog = document.createElement('dialog');
      dialog.className = 'k-sheet';
      dialog.setAttribute('aria-label', 'Title');
      scrim = document.createElement('div');
      scrim.className = 'k-sheet-scrim';
      card = document.createElement('div');
      card.className = 'k-sheet-card';
      var closer = document.createElement('button');
      closer.type = 'button';
      closer.className = 'k-sheet-close glass';
      closer.setAttribute('aria-label', 'Close');
      closer.appendChild(svgClose());
      body = document.createElement('div');
      body.className = 'k-sheet-body';
      card.appendChild(closer);
      card.appendChild(body);
      dialog.appendChild(scrim);
      dialog.appendChild(card);
      document.body.appendChild(dialog);
      closer.addEventListener('click', ask);
      scrim.addEventListener('click', ask);
      dialog.addEventListener('cancel', function (event) { event.preventDefault(); ask(); });
      pull();
    }

    /* The card's own box, untransformed (the dialog fills the viewport, so this is its place on screen). */
    function box() {
      return { left: card.offsetLeft, top: card.offsetTop, width: card.offsetWidth, height: card.offsetHeight };
    }

    function full() {
      var r = window.getComputedStyle(card).borderTopLeftRadius || '0px';
      return 'inset(0px 0px 0px 0px round ' + r + ' ' + r + ' 0px 0px)';
    }

    /* The card scaled evenly (so nothing distorts) onto `rect`, and cropped to its height. */
    function onto(rect) {
      var b = box();
      var scale = rect.width / b.width;
      var cut = Math.max(0, b.height - rect.height / scale);
      return {
        transform: 'translate(' + (rect.left - b.left) + 'px, ' + (rect.top - b.top) + 'px) scale(' + scale + ')',
        clipPath: 'inset(0px 0px ' + cut + 'px 0px round ' + (12 / scale) + 'px)'
      };
    }

    function shown(element) {
      return !!element && element.isConnected && visible(element);
    }

    function standIn(src) {
      var holder = document.createElement('div');
      holder.className = 'k-sheet-standin';
      holder.setAttribute('aria-hidden', 'true');
      if (src) {
        var img = document.createElement('img');
        img.alt = '';
        img.src = src;
        holder.appendChild(img);
      }
      return holder;
    }

    function clean(section) {
      Array.prototype.forEach.call(section.querySelectorAll('script, iframe, object, embed, form'), function (bad) {
        bad.parentNode.removeChild(bad);
      });
      return section;
    }

    function load(href, mine) {
      return window.fetch(href, { credentials: 'same-origin', redirect: 'manual', cache: 'no-store' })
        .then(function (response) {
          if (!response.ok || response.type !== 'basic' || response.redirected) throw new Error('not a title page');
          return response.text();
        })
        .then(function (text) {
          if (mine !== generation) return null;
          var doc = new window.DOMParser().parseFromString(text, 'text/html');
          var section = doc.querySelector('main .title-page, main .title-down');
          if (!section) throw new Error('not a title page');
          return { section: document.importNode(clean(section), true), title: doc.title };
        });
    }

    function open(link) {
      if (busy) return;
      busy = true;
      var mine = ++generation;
      if (!dialog) build();
      opener = link;
      var holder = link.closest('.hero, li');
      origin = holder ? holder.querySelector('.frame, .hero-backdrop') : null;
      if (!shown(origin)) origin = shown(link) ? link : null;
      var img = origin ? origin.querySelector('img.art') : null;
      var href = link.href;
      while (body.firstChild) body.removeChild(body.firstChild);
      var stand = standIn(img && img.complete && img.naturalWidth ? img.currentSrc || img.src : null);
      card.insertBefore(stand, body);
      dialog.removeAttribute('aria-labelledby');
      dialog.setAttribute('aria-label', 'Title');
      dialog.setAttribute('aria-busy', 'true');
      dialog.showModal();
      card.scrollTop = 0;
      window.history.pushState({ kSheet: true }, '', href);
      pushed = true;

      var moving = Promise.resolve();
      if (!still()) {
        var from = origin ? onto(origin.getBoundingClientRect()) : { transform: 'translateY(100%)', clipPath: full() };
        var grow = card.animate([from, { transform: 'none', clipPath: full() }], { duration: OPEN_MS, easing: EASE_SHEET });
        /* A hidden page may hold animations still: the title shows when the growth ends, or shortly after it should
           have, whichever comes first. */
        moving = Promise.race([grow.finished.catch(noop), new Promise(function (resolve) {
          window.setTimeout(resolve, OPEN_MS + 120);
        })]);
        scrim.animate([{ opacity: 0 }, { opacity: 1 }], { duration: OPEN_MS, easing: 'ease-out' });
      }
      Promise.all([load(href, mine), moving]).then(function (done) {
        var page = done[0];
        if (!page || mine !== generation) return;
        body.appendChild(page.section);
        arrive(body);
        if (body.querySelector('#h-title')) {
          dialog.removeAttribute('aria-label');
          dialog.setAttribute('aria-labelledby', 'h-title');
        }
        dialog.removeAttribute('aria-busy');
        if (page.title) document.title = page.title;
        busy = false;
        if (still()) { stand.parentNode.removeChild(stand); return; }
        body.animate([{ opacity: 0, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }],
          { duration: 200, easing: EASE_SHEET });
        stand.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200, easing: 'ease-out', fill: 'forwards' })
          .finished.then(function () { if (stand.parentNode) stand.parentNode.removeChild(stand); }, noop);
      }, function () {
        /* Not a title page this script can show (signed out, a redirect, an error): load it for real. */
        if (mine === generation) window.location.assign(href);
      });
    }

    /* Close from the sheet's own controls: going back pops the title's URL, and that closes it (popstate, below). */
    function ask() {
      if (!dialog || !dialog.open) return;
      if (pushed) window.history.back();
      else shut(null);
    }

    function finish() {
      generation++;
      busy = false;
      pushed = false;
      var inside = dialog.contains(document.activeElement);
      if (dialog.open) dialog.close();
      /* Focus goes back to the link that opened the sheet (the dialog returns it only to what had focus before). */
      if (inside && opener && opener.isConnected) opener.focus({ preventScroll: true });
      while (body.firstChild) body.removeChild(body.firstChild);
      var stand = card.querySelector('.k-sheet-standin');
      if (stand) stand.parentNode.removeChild(stand);
      card.getAnimations().forEach(function (a) { a.cancel(); });
      scrim.getAnimations().forEach(function (a) { a.cancel(); });
      document.title = pageTitle;
    }

    /* `from`: the dragged state to start from, or null for the card at rest. */
    function shut(from) {
      if (!dialog || !dialog.open) return;
      if (still()) { finish(); return; }
      var home = shown(origin);
      var to = home ? onto(origin.getBoundingClientRect()) : { transform: 'translateY(100%)', clipPath: full() };
      var scrimFrom = window.getComputedStyle(scrim).opacity;
      card.getAnimations().forEach(function (a) { a.cancel(); });
      scrim.getAnimations().forEach(function (a) { a.cancel(); });
      card.animate([from || { transform: 'none', clipPath: full() }, to],
        { duration: CLOSE_MS, easing: EASE_SHEET, fill: 'forwards' });
      if (home) {
        card.animate([{ opacity: 1, offset: 0 }, { opacity: 1, offset: 0.7 }, { opacity: 0, offset: 1 }],
          { duration: CLOSE_MS, fill: 'forwards' });
      }
      var mine = generation, done = false;
      function once() { if (!done && mine === generation) { done = true; finish(); } }
      scrim.animate([{ opacity: scrimFrom }, { opacity: 0 }], { duration: CLOSE_MS, easing: 'ease-out', fill: 'forwards' })
        .finished.then(once, once);
      window.setTimeout(once, CLOSE_MS + 120);       /* a hidden page may hold the animation still */
    }

    /* A downward pull that starts with the sheet scrolled to its top follows the finger: the card drops and shrinks
       a little and the page behind clears. Let go past a third of the way (or with a flick) and it closes; otherwise
       it settles back. Touch only: a mouse uses the close button, Escape or a press outside. */
    function pull() {
      var startY = 0, lastY = 0, lastT = 0, speed = 0, dragging = false, armed = false, drag = null, dim = null;
      var reach = 1;
      function state(progress) {
        var k = 1 - 0.3 * progress;
        return {
          transform: 'translate(' + (box().width * (1 - k) / 2) + 'px, ' + (progress * reach) + 'px) scale(' + k + ')',
          clipPath: full()
        };
      }
      card.addEventListener('touchstart', function (event) {
        armed = !busy && event.touches.length === 1 && card.scrollTop <= 0;
        if (!armed) return;
        startY = lastY = event.touches[0].clientY;
        lastT = Date.now();
        speed = 0;
      }, { passive: true });
      card.addEventListener('touchmove', function (event) {
        if (!armed) return;
        var y = event.touches[0].clientY;
        var dy = y - startY;
        if (!dragging) {
          if (dy < -4) { armed = false; return; }
          if (dy <= 4) return;
          dragging = true;
          reach = window.innerHeight * 0.6;
          drag = card.animate([state(0), state(1)], { duration: 1000, fill: 'both' });
          drag.pause();
          dim = scrim.animate([{ opacity: 1 }, { opacity: 0.15 }], { duration: 1000, fill: 'both' });
          dim.pause();
        }
        event.preventDefault();
        var now = Date.now();
        speed = (y - lastY) / Math.max(1, now - lastT);
        lastY = y;
        lastT = now;
        var progress = Math.max(0, Math.min(1, dy / reach));
        drag.currentTime = progress * 1000;
        dim.currentTime = progress * 1000;
      }, { passive: false });
      function release() {
        armed = false;
        if (!dragging) return;
        dragging = false;
        var progress = (drag.currentTime || 0) / 1000;
        if (progress > 0.33 || (speed > 0.6 && progress > 0.05)) {
          var from = state(progress);
          drag.cancel();
          if (pushed) { pendingFrom = from; window.history.back(); }
          else shut(from);
        } else {
          drag.reverse();
          dim.reverse();
          var settling = drag, clearing = dim;
          settling.finished.then(function () { settling.cancel(); clearing.cancel(); }, noop);
        }
      }
      card.addEventListener('touchend', release, { passive: true });
      card.addEventListener('touchcancel', release, { passive: true });
    }

    window.addEventListener('popstate', function (event) {
      if (dialog && dialog.open) {
        var from = pendingFrom;
        pendingFrom = null;
        pushed = false;
        shut(from);
        return;
      }
      /* Forward onto a title's URL while the sheet is closed: show that title page for real. */
      if (event.state && event.state.kSheet) window.location.reload();
    });

    document.addEventListener('click', function (event) {
      if (event.defaultPrevented || event.button !== 0 ||
          event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      var from = event.target;
      var link = from && typeof from.closest === 'function' ? from.closest('a[href]') : null;
      if (!link || (dialog && dialog.contains(link))) return;
      if (link.origin !== window.location.origin || link.pathname.indexOf('/title/') !== 0) return;
      var target = link.getAttribute('target');
      if ((target && target !== '_self') || link.hasAttribute('download')) return;
      event.preventDefault();
      open(link);
    });
  }

  /* 9. Chrome that follows the scroll (owner decision 2026-10-27, after streaming and community apps). Two marks on
     <html>, read only by the stylesheet: data-scrolled once the page is off its top, and data-chrome="tucked" while
     the reader is moving down the page. The stylesheet slims the header, tucks the places (or the Library's filters)
     under it and shrinks the tab bar down and in; scrolling up a little, reaching the top or the end, or moving focus
     into any of them brings everything back at once. Small movements are ignored (the run must pass 12px down or
     10px up), and so is the overscroll bounce past either end. Nothing changes size, so the page never jumps. */
  function chrome() {
    if (!document.querySelector('.mast')) return;
    var root = document.documentElement;
    var last = Math.max(0, window.scrollY || 0), run = 0, tucked = false, scrolled = false;

    function mark(tuck, off) {
      if (tuck !== tucked) {
        tucked = tuck;
        if (tuck) root.setAttribute('data-chrome', 'tucked');
        else root.removeAttribute('data-chrome');
      }
      if (off !== scrolled) {
        scrolled = off;
        if (off) root.setAttribute('data-scrolled', '');
        else root.removeAttribute('data-scrolled');
      }
    }

    /* Scroll events come at most once a frame, and this reads two numbers and writes at most two attributes. */
    function update() {
      var y = window.scrollY || 0;
      var end = root.scrollHeight - window.innerHeight;
      if (y <= 8) { mark(false, false); last = Math.max(0, y); run = 0; return; }
      if (end > 0 && y >= end - 4) { mark(false, true); last = Math.min(y, end); run = 0; return; }
      var dy = y - last;
      last = y;
      if ((dy > 0 && run < 0) || (dy < 0 && run > 0)) run = 0;
      run += dy;
      if (run > 12 && y > 64) { mark(true, true); run = 0; }
      else if (run < -10) { mark(false, true); run = 0; }
      else mark(tucked, true);
    }

    window.addEventListener('scroll', update, { passive: true });
    document.addEventListener('focusin', function (event) {
      var to = event.target;
      if (to && typeof to.closest === 'function' && to.closest('header, nav.tabbar, nav.chips')) mark(false, scrolled);
    });
    update();
  }

  /* 10. The Library's layout menu. Contract: <details class="lib-layout"> holds <a class="lib-view" data-view="...">
     links (each a full page address that works on its own), and every list of cards carries data-lib-list. A plain
     click on a layout gives each list the class that layout's page would print (the same rule as viewmodel.py
     LIBRARY_LIST_CLASS and list_class_of), replaces the address, moves aria-current, keeps the chosen layout in the
     library links, closes the menu and returns focus to its button. Each card then glides from its old box to its
     new one (Web Animations on transform only: first, last, invert, play); with reduced motion it simply changes.
     A click outside the open menu, or Escape, closes it. Without this, each layout is an ordinary link. */
  var LIST_CLASS = { grid: 'lib-grid', compact: 'lib-grid lib-v-compact', list: 'lib-grid lib-v-list' };
  var GLIDE = { duration: 420, easing: 'cubic-bezier(0.32, 0.72, 0, 1)' };

  function boxes(lists) {
    var out = [];
    for (var i = 0; i < lists.length; i += 1) {
      var items = lists[i].children;
      for (var j = 0; j < items.length; j += 1) {
        var frame = items[j].querySelector('.frame');
        out.push({ li: items[j], frame: frame, at: items[j].getBoundingClientRect(),
                   art: frame ? frame.getBoundingClientRect() : null });
      }
    }
    return out;
  }

  function onScreen(rect) {
    return rect.bottom > -200 && rect.top < window.innerHeight + 200 && rect.right > -200 && rect.left < window.innerWidth + 200;
  }

  function glide(before) {
    for (var i = 0; i < before.length; i += 1) {
      var b = before[i];
      var now = b.li.getBoundingClientRect();
      if (!onScreen(now) && !onScreen(b.at)) continue;
      var dx = b.at.left - now.left, dy = b.at.top - now.top;
      if (typeof b.li.animate !== 'function') return;
      b.li.animate([{ transform: 'translate(' + dx + 'px, ' + dy + 'px)' }, { transform: 'none' }], GLIDE);
      var art = b.frame ? b.frame.getBoundingClientRect() : null;
      if (art && b.art && art.width > 0 && b.art.width > 0) {
        var tx = (b.art.left - art.left) - dx, ty = (b.art.top - art.top) - dy;
        b.frame.animate([
          { transform: 'translate(' + tx + 'px, ' + ty + 'px) scale(' + (b.art.width / art.width) + ', ' +
            (b.art.height / art.height) + ')', transformOrigin: '0 0' },
          { transform: 'none', transformOrigin: '0 0' }], GLIDE);
      }
    }
  }

  function withView(href, view) {
    var url = new URL(href, window.location.href);
    if (view === 'shelves') url.searchParams.delete('view');
    else url.searchParams.set('view', view);
    return url.pathname + url.search + url.hash;
  }

  function layout() {
    var menu = document.querySelector('details.lib-layout');
    if (!menu || !window.history || typeof window.history.replaceState !== 'function') return;
    var button = menu.querySelector('summary');

    function close(refocus) {
      if (!menu.hasAttribute('open')) return;
      menu.removeAttribute('open');
      if (refocus && button) button.focus();
    }

    menu.addEventListener('click', function (event) {
      var link = event.target && event.target.closest ? event.target.closest('a.lib-view') : null;
      if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey ||
          event.altKey) return;
      var view = link.getAttribute('data-view');
      var lists = document.querySelectorAll('[data-lib-list]');
      if (!view || !lists.length || (view !== 'shelves' && !LIST_CLASS[view])) return;
      event.preventDefault();
      var cls = view === 'shelves' ? (lists.length > 1 ? 'rail' : 'lib-grid') : LIST_CLASS[view];
      var motion = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      var before = motion ? boxes(lists) : null;
      for (var i = 0; i < lists.length; i += 1) lists[i].setAttribute('class', cls);
      menu.setAttribute('data-layout', view);
      var links = menu.querySelectorAll('a.lib-view');
      for (var j = 0; j < links.length; j += 1) {
        if (links[j] === link) links[j].setAttribute('aria-current', 'true');
        else links[j].removeAttribute('aria-current');
      }
      var icon = link.querySelector('svg.ic'), shown = button && button.querySelector('svg.ic');
      if (icon && shown) button.replaceChild(icon.cloneNode(true), shown);
      var words = link.querySelector('.lib-view-t'), label = button && button.querySelector('.lib-layout-t');
      if (words && label) label.textContent = words.textContent;
      window.history.replaceState(window.history.state, '', link.getAttribute('href'));
      var keep = document.querySelectorAll('nav.chips a.chip, a.k-warn-act');
      for (var k = 0; k < keep.length; k += 1) keep[k].setAttribute('href', withView(keep[k].getAttribute('href'), view));
      close(true);
      if (before) glide(before);
    });
    document.addEventListener('click', function (event) {
      if (menu.hasAttribute('open') && !menu.contains(event.target)) close(false);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && menu.hasAttribute('open')) close(true);
    });
  }

  lens();
  bfcache();
  worker();
  flight();
  interrupt();
  arrive();
  press();
  sheet();
  chrome();
  layout();
})();
