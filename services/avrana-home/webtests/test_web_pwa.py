"""Tier B, MK-3 (AVR-717; owner decision O1, DECISIONS.md 2026-10-26): the one first-party page script, the service
worker, the offline page and the sign-out hop. Synthetic data only (StubAdapter), no upstream.

What these pin, and why (the security review's checklist is the threat model in the PR description):
  * script and worker exist only where the shell exists; the script tag appears exactly when the CSP allows it;
  * the worker is served only at /sw.js, with no Service-Worker-Allowed header and `connect-src 'self'` on that
    response alone; the offline page adds `font-src 'self'` and nothing else;
  * the worker's allow-list is built from code, holds no member route and is identical for every viewer;
  * the offline page and the worker carry nothing about any member;
  * /signout clears cache and storage (never cookies) and ends at the outpost's own sign-out;
  * every other page, error page and non-shell page has no script and an unchanged CSP.
"""
import re
import unittest

from avrana_home.app import brand, install, pwa
from avrana_home.app.middleware import CSP
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

# Font and brand paths come from brand.py, never typed here, so this file does not care which font the brand ships.
FONTS = [r for r in brand.ROUTES if r.endswith(".woff2")]
FONT = FONTS[0]
NAME = "X-authentik-name"
FILM_A = "aaaa0000000000000000000000000001"
FILM_B = "bbbb0000000000000000000000000002"
A = [(USER, "member-a"), (NAME, "Alice Aardvark"), (GROUPS, "avrana-users|avrana-videos")]
B = [(USER, "member-b"), (NAME, "Bertram Bobcat"), (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks|avrana-books")]
NO_GROUPS = [(USER, "member-a")]
BASE = CSP.decode()
SHELL = BASE + "; manifest-src 'self'; font-src 'self'; script-src 'self'; worker-src 'self'"
SIGNOUT = "/outpost.goauthentik.io/sign_out"
SCRIPT = '<script src="%s" defer></script>'
JS_FORBIDDEN = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|\beval\b|new Function|document\.write|setTimeout\(\s*['\"]"
                          r"|localStorage|sessionStorage|indexedDB|document\.cookie|importScripts|XMLHttpRequest|WebSocket")


def data():
    return StubAdapter({"member-a": [(FILM_A, "Synthetic Film", 0.5)], "member-b": [(FILM_B, "Other Film", 0.2)]})


class Base(unittest.TestCase):
    def client(self, sections=True, **settings):
        c = make_client(make_settings(home_sections=sections, **settings), adapters=[data()] if sections else None)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c


class PageScript(Base):
    def test_served_at_its_versioned_path_with_the_script_type(self):
        c = self.client()
        r = c.get(pwa.script_path(), headers=A)
        self.assertEqual(200, r.status_code)
        self.assertEqual("text/javascript; charset=utf-8", r.headers["content-type"])
        self.assertEqual("nosniff", r.headers["x-content-type-options"])
        self.assertEqual("no-store", r.headers["cache-control"])                   # D11: no relaxation
        self.assertEqual(BASE, r.headers["content-security-policy"])
        self.assertRegex(pwa.script_path(), r"^/static/home\.[0-9a-f]{12}\.js$")

    def test_the_hash_in_the_path_is_the_hash_of_the_bytes(self):
        import hashlib
        body = self.client().get(pwa.script_path()).content
        self.assertTrue(pwa.script_path().endswith(hashlib.sha256(body).hexdigest()[:12] + ".js"))

    def test_the_same_bytes_for_everyone(self):
        c = self.client()
        want = c.get(pwa.script_path()).content
        for headers in (A, B, NO_GROUPS, []):
            self.assertEqual(want, c.get(pwa.script_path(), headers=headers).content)

    def test_any_other_script_path_is_the_standard_404(self):
        c = self.client()
        nf = c.get("/nope", headers=A).text
        for path in ("/static/home.js", "/static/home.000000000000.js", "/static/", "/static", "/home.js"):
            r = c.get(path, headers=A)
            self.assertEqual((404, nf), (r.status_code, r.text), path)

    def test_the_script_source_has_no_dangerous_api_and_reads_no_member_data(self):
        """Threat 1 and 12: no HTML from text, no eval, no storage, no cookies, no network of its own."""
        source = pwa.script_bytes().decode("utf-8")
        self.assertIsNone(JS_FORBIDDEN.search(source), JS_FORBIDDEN.search(source))
        self.assertNotIn("fetch(", source)                                         # D13: no heartbeat, no requests
        self.assertNotIn("/home.json", source)
        self.assertNotIn("http://", source.replace("http://www.w3.org", ""))
        self.assertNotIn("https://", source)

    def test_the_script_keeps_the_lens_contract_and_never_prevents_navigation(self):
        source = pwa.script_bytes().decode("utf-8")
        for needle in ("nav.tabbar", "a.tab", "data-at", "aria-current", "prefers-reduced-motion"):
            self.assertIn(needle, source)
        self.assertNotIn("preventDefault", source)                                 # the browser always navigates
        self.assertIn("pageshow", source)
        self.assertIn("event.persisted", source)
        self.assertIn("location.reload", source)
        self.assertRegex(source, r"scope:[ \t]*'/'[ \t]*,[ \t]*updateViaCache:[ \t]*'none'")   # whatever the spacing
        self.assertIn("pagehide", source)
        self.assertIn("'/sw.js'", source)
        self.assertIn("data-sw", source)

    def test_the_banner_is_a_live_region_that_is_announced_and_text_is_never_html(self):
        """Review LOW: the status element goes into the page empty and gets its words after it is in the document."""
        source = pwa.script_bytes().decode("utf-8")
        for needle in ("'update-banner'", "'update-banner-text'", "'update-banner-button'", "setAttribute('role', 'status')"):
            self.assertIn(needle, source)
        self.assertLess(source.index("document.body.appendChild(box)"), source.index("text.textContent ="))
        self.assertEqual(1, source.count("text.textContent ="))
        self.assertEqual(1, source.count("setTimeout("))

    def test_only_the_script_and_the_worker_answer_with_a_script_type(self):
        """Threat 1, 7 and 8: nosniff everywhere, and no other route can be executed as script or as a worker."""
        c = self.client()
        paths = ["/", "/account", "/help", "/help/movies", "/help/trouble", "/search", "/search?q=x", "/watch", "/read",
                 "/request", "/nope", "/healthz", "/home.json", "/manifest.webmanifest", "/offline", "/signout",
                 "/art/jellyfin/primary/" + FILM_A, "/title/jellyfin/" + FILM_A, FONT,
                 brand.LOCKUP, brand.FAVICON] + list(install.ICON_PATHS)
        for path in paths:
            for headers in (A, B, []):
                r = c.get(path, headers=headers)
                self.assertNotIn("javascript", r.headers.get("content-type", ""), path)
                self.assertNotIn("service-worker-allowed", r.headers, path)
                self.assertEqual("nosniff", r.headers["x-content-type-options"], path)
        for path, headers in ((pwa.script_path(), A), ("/sw.js", A)):
            r = c.get(path, headers=headers)
            self.assertEqual("text/javascript; charset=utf-8", r.headers["content-type"])


class ScriptTagAndCsp(Base):
    ROUTES = ("/", "/account", "/help", "/help/movies", "/help/trouble", "/search", "/search?q=Film", "/watch", "/request",
              "/title/jellyfin/" + FILM_A)

    def test_the_script_tag_is_present_exactly_when_the_csp_allows_script(self):
        c = self.client()
        for path in self.ROUTES + ("/read", "/nope", "/healthz", "/offline", "/signout", "/manifest.webmanifest",
                                   "/outpost.goauthentik.io/sign_out", "/help/comics"):
            for headers in (A, B, NO_GROUPS, []):
                r = c.get(path, headers=headers)
                html = "html" in r.headers.get("content-type", "")
                tag = html and (SCRIPT % pwa.script_path()) in r.text
                allowed = "script-src 'self'" in r.headers["content-security-policy"]
                self.assertEqual(tag, allowed, (path, bool(headers)))
                if html:
                    self.assertEqual(allowed, "worker-src 'self'" in r.headers["content-security-policy"], path)
                    self.assertLessEqual(len(re.findall(r"(?i)<script", r.text)), 1, path)

    def test_the_script_is_in_the_head_never_before_the_skip_link(self):
        text = self.client().get("/", headers=A).text
        self.assertLess(text.index("<script"), text.index("</head>"))
        self.assertLess(text.index("</head>"), text.index('class="skip-link"'))

    def test_a_member_sees_the_script_only_on_shell_pages(self):
        """No principal, no shell: sign-in-less and unknown pages stay script-free with an unchanged CSP."""
        c = self.client()
        for path in ("/", "/account", "/help", "/nope", "/read"):
            r = c.get(path, headers=NO_GROUPS)
            self.assertNotIn("<script", r.text.lower(), path)
            self.assertEqual(BASE, r.headers["content-security-policy"], path)

    def test_error_and_method_pages_have_no_script(self):
        c = self.client()
        for method in ("POST", "PUT", "DELETE", "OPTIONS"):
            r = c.request(method, "/", headers=A)
            self.assertEqual(501, r.status_code)
            self.assertNotIn("<script", r.text.lower())
            self.assertEqual(BASE, r.headers["content-security-policy"])
        r = c.get("/nope", headers=A)
        self.assertEqual((404, BASE), (r.status_code, r.headers["content-security-policy"]))
        self.assertNotIn("<script", r.text.lower())
        bad = c.get("/title/jellyfin/" + "z" * 64, headers=A)
        self.assertNotIn("<script", bad.text.lower())

    def test_a_500_from_a_shell_route_gets_the_base_csp_and_no_script(self):
        """N-1: a render failure after the route marked itself a shell page (or /search) must not leave script-src,
        worker-src, manifest-src, font-src or form-action 'self' on the generic 500 page, which has no script."""
        from unittest import mock
        c = self.client()
        env = c.fastapi_app.state.env
        real = env.get_template

        for path, template, before in (("/account", "account.html", SHELL), ("/", "home.html", SHELL),
                                       ("/search", "search.html", SHELL.replace("form-action 'none'", "form-action 'self'"))):
            def boom(name, *args, **kwargs):
                if name == template:
                    raise RuntimeError("synthetic render failure")
                return real(name, *args, **kwargs)

            with self.subTest(path=path):
                self.assertEqual(before, c.get(path, headers=A).headers["content-security-policy"])
                with mock.patch.object(env, "get_template", boom):
                    r = c.get(path, headers=A)
                self.assertEqual(500, r.status_code)
                self.assertEqual(BASE, r.headers["content-security-policy"])
                self.assertNotIn("<script", r.text.lower())
                self.assertNotIn("Synthetic Film", r.text)
                self.assertEqual("no-store", r.headers["cache-control"])

    def test_csp_never_allows_inline_script_eval_or_another_host(self):
        c = self.client()
        for path in self.ROUTES:
            csp = c.get(path, headers=A).headers["content-security-policy"]
            self.assertEqual(1, csp.count("unsafe-inline"))
            self.assertIn("style-src 'unsafe-inline'", csp)
            self.assertNotIn("unsafe-eval", csp)
            self.assertNotIn("strict-dynamic", csp)
            self.assertNotIn("data:", csp)
            self.assertNotIn("http", csp)
            self.assertNotIn("*", csp)
            script = re.search(r"script-src ([^;]*)", csp).group(1)
            self.assertEqual("'self'", script)

    def test_shell_csp_equals_the_documented_string(self):
        c = self.client()
        for path in ("/", "/account", "/help", "/help/movies", "/watch"):
            self.assertEqual(SHELL, c.get(path, headers=A).headers["content-security-policy"], path)
        self.assertEqual(SHELL.replace("form-action 'none'", "form-action 'self'"),
                         c.get("/search", headers=A).headers["content-security-policy"])


class Worker(Base):
    def test_headers_and_csp(self):
        r = self.client().get("/sw.js", headers=A)
        self.assertEqual(200, r.status_code)
        self.assertEqual("text/javascript; charset=utf-8", r.headers["content-type"])
        self.assertEqual("no-store", r.headers["cache-control"])
        self.assertEqual("nosniff", r.headers["x-content-type-options"])
        self.assertEqual(BASE + "; connect-src 'self'", r.headers["content-security-policy"])
        self.assertNotIn("service-worker-allowed", r.headers)                       # scope "/" comes from the path alone
        self.assertEqual("no-referrer", r.headers["referrer-policy"])

    def test_connect_src_is_on_the_worker_response_alone(self):
        c = self.client()
        for path in ("/", "/account", "/help", "/search", "/watch", "/nope", "/healthz", "/offline", "/signout",
                     "/manifest.webmanifest", pwa.script_path(), FONT, "/icons/avrana-192.png"):
            self.assertNotIn("connect-src", c.get(path, headers=A).headers["content-security-policy"], path)
        self.assertIn("connect-src 'self'", c.get("/sw.js", headers=A).headers["content-security-policy"])

    def test_the_same_bytes_for_every_viewer(self):
        c = self.client()
        want = c.get("/sw.js", headers=A).content
        for headers in (B, NO_GROUPS, []):
            self.assertEqual(want, c.get("/sw.js", headers=headers).content)
        for name in ("Alice", "Aardvark", "Bertram", "Bobcat", "member-a", "member-b", "Synthetic Film"):
            self.assertNotIn(name, want.decode())

    def test_the_allow_list_comes_from_code_and_holds_only_static_shell_files(self):
        c = self.client()
        paths = set(pwa.precache_paths())
        self.assertEqual({pwa.script_path(), pwa.OFFLINE_PATH} | set(brand.ROUTES) | set(install.ICON_PATHS), paths)
        text = c.get("/sw.js").text
        for path in paths:
            self.assertIn('"%s"' % path, text)
        for member_route in ("/", "/search", "/account", "/help", "/watch", "/read", "/request", "/home.json",
                             "/manifest.webmanifest", "/signout", "/sw.js", "/healthz", "/readyz"):
            self.assertNotIn(member_route, paths)
        self.assertFalse([p for p in paths if p.startswith(("/art", "/title"))])
        types = pwa.precache_types()
        for path in paths - {pwa.OFFLINE_PATH}:
            r = c.get(path)                                                         # every one is a plain 200 without identity
            self.assertEqual(200, r.status_code, path)
            self.assertEqual(types[path], r.headers["content-type"].split(";")[0], path)

    def test_the_policy_in_the_worker_source(self):
        """Threats 2 to 4 and 8, as source assertions (the behaviour itself is run in a browser, see the PR)."""
        src = self.client().get("/sw.js").text
        for needle in ("response.type !== 'basic'", "response.redirected", "response.status !== 200",
                       "redirect: 'error'", "cache: 'reload'", "MAX_BYTES", "ALLOW[path]", "'vary'",
                       "error instanceof TypeError", "request.mode === 'navigate'", "fetch(request)",
                       "event.waitUntil", "caches.delete"):
            self.assertIn(needle, src)
        self.assertIsNone(JS_FORBIDDEN.search(src), JS_FORBIDDEN.search(src))
        for bad in ("clients.claim", "Authorization", "authorization", "cookie", "new Request(request", "request.clone"):
            self.assertNotIn(bad, src)
        self.assertEqual(1, src.count("skipWaiting()"))                             # only in the message handler
        self.assertLess(src.index("addEventListener('message'"), src.index("skipWaiting()"))
        self.assertLess(src.index("skipWaiting()"), src.index("async function offlinePage"))
        # SF-1: a navigation to the sign-out hop or the outpost is left to the browser (no respondWith, no fetch here)
        branch = src[src.index("request.mode === 'navigate'"):src.index("event.respondWith(fetch(request)")]
        self.assertIn("sessionPath(new URL(request.url).pathname)) return;", branch)
        self.assertIn("=== '/signout'", src)
        self.assertIn("indexOf('/outpost.goauthentik.io/') === 0", src)
        self.assertNotIn("__BUILD__", src)
        self.assertNotIn("__ALLOW__", src)
        self.assertNotIn("__OFFLINE__", src)

    def test_a_changed_file_means_a_new_cache_name(self):
        a = pwa.worker_bytes(b"<p>one</p>").decode()
        b = pwa.worker_bytes(b"<p>two</p>").decode()
        name = lambda s: re.search(r"const BUILD = '([0-9a-f]{12})'", s).group(1)
        self.assertNotEqual(name(a), name(b))
        self.assertEqual(name(a), name(pwa.worker_bytes(b"<p>one</p>").decode()))

    def test_sections_off_the_worker_does_not_exist(self):
        c = self.client(sections=False)
        nf = c.get("/nope", headers=A).text
        for path in ("/sw.js", "/offline", "/signout", pwa.script_path()):
            r = c.get(path, headers=A)
            self.assertEqual((404, nf), (r.status_code, r.text), path)

    def test_kill_switch_serves_a_worker_that_removes_itself_and_the_script_skips_registration(self):
        c = self.client(pwa_sw=False)
        r = c.get("/sw.js", headers=A)
        self.assertEqual(200, r.status_code)
        self.assertEqual(pwa.SELF_DESTRUCT, r.content)
        body = r.text
        for needle in ("skipWaiting", "caches.delete", "registration.unregister()"):
            self.assertIn(needle, body)
        self.assertNotIn("addEventListener('fetch'", body)                          # it intercepts nothing
        self.assertEqual(BASE + "; connect-src 'self'", r.headers["content-security-policy"])
        tag = '<script src="%s" defer data-sw="off"></script>' % pwa.script_path()
        self.assertIn(tag, c.get("/", headers=A).text)
        on = self.client().get("/", headers=A).text
        self.assertNotIn("data-sw", on)
        self.assertIn(SCRIPT % pwa.script_path(), on)


class OfflinePage(Base):
    def test_headers_and_csp(self):
        r = self.client().get("/offline", headers=A)
        self.assertEqual((200, "text/html; charset=utf-8"), (r.status_code, r.headers["content-type"]))
        self.assertEqual(BASE + "; font-src 'self'", r.headers["content-security-policy"])
        self.assertEqual("no-store", r.headers["cache-control"])

    def test_the_same_page_for_member_a_member_b_and_nobody(self):
        """Threat 2: nothing per member. Two different members with different names, groups and libraries."""
        c = self.client()
        a, b, none = (c.get("/offline", headers=h) for h in (A, B, []))
        self.assertEqual(a.content, b.content)
        self.assertEqual(a.content, none.content)
        text = a.text.split("<body>", 1)[1]                                     # the page, not the inlined stylesheet
        for secret in ("Alice", "Aardvark", "Bertram", "Bobcat", "member-a", "member-b", "Synthetic Film", "Other Film",
                       "Continue", "Listen", "Watch", "Movies", "Account", "Signed in", "aria-current", "@"):
            self.assertNotIn(secret, text, secret)
        self.assertNotIn('<nav class="places"', text)
        self.assertNotIn("<details", text)

    def test_the_words_the_owner_approved_and_a_way_back(self):
        text = self.client().get("/offline").text
        self.assertIn("This phone has no connection. Avrana Media needs one to show your libraries.", text)
        self.assertRegex(text, r'<a class="link" href="/">Try again</a>')
        self.assertIn("<title>No connection · Avrana Media</title>", text)
        self.assertEqual(1, len(re.findall(r"<h1", text)))
        self.assertIn('<main id="main"', text)

    def test_no_script_and_no_manifest_and_the_shell_look(self):
        text = self.client().get("/offline").text
        self.assertNotIn("<script", text.lower())
        self.assertNotIn('rel="manifest"', text)
        self.assertIn("@font-face", text)                                           # home.css is inlined: shell-styled
        for font in FONTS:
            self.assertIn('url("%s")' % font, text)                                 # the brand font, a file the worker stores
        self.assertIn('src="%s"' % brand.LOCKUP, text)                              # a file the worker stores


class Signout(Base):
    def test_clears_cache_and_storage_then_redirects_to_the_outpost(self):
        c = self.client()
        for headers in (A, B, NO_GROUPS, []):
            r = c.get("/signout", headers=headers)
            self.assertEqual(303, r.status_code)
            self.assertEqual(SIGNOUT, r.headers["location"])
            self.assertEqual('"cache", "storage"', r.headers["clear-site-data"])
            self.assertNotIn("cookies", r.headers["clear-site-data"])                # D10: never "cookies"
            self.assertEqual("no-store", r.headers["cache-control"])
            self.assertEqual(BASE, r.headers["content-security-policy"])
            self.assertEqual(b"", r.content)

    def test_the_target_is_the_catalogues_fixed_signout_url_whatever_the_request_says(self):
        c = self.client()
        want = c.fastapi_app.state.catalogue.signout_url
        self.assertEqual(SIGNOUT, want)
        for extra in ([], [("X-Forwarded-Host", "evil.example")], [("Host", "evil.example")],
                      [("Referer", "https://evil.example/")], [("Origin", "https://evil.example")]):
            r = c.get("/signout?next=https://evil.example", headers=A + extra)
            self.assertEqual(want, r.headers["location"])

    def test_head_matches_and_other_methods_are_501(self):
        c = self.client()
        h = c.head("/signout", headers=A)
        self.assertEqual((303, SIGNOUT, '"cache", "storage"'),
                         (h.status_code, h.headers["location"], h.headers["clear-site-data"]))
        self.assertEqual(501, c.post("/signout", headers=A).status_code)

    def test_no_other_response_sends_clear_site_data(self):
        c = self.client()
        for path in ("/", "/account", "/help", "/search", "/nope", "/sw.js", "/offline", "/healthz"):
            self.assertNotIn("clear-site-data", c.get(path, headers=A).headers, path)

    def test_account_points_at_the_hop_on_shell_pages_and_at_the_outpost_without_the_shell(self):
        shell = self.client().get("/account", headers=A).text
        self.assertIn('<a class="account" href="/signout">Sign out</a>', shell)
        self.assertNotIn('href="%s"' % SIGNOUT, shell)
        plain = self.client(sections=False).get("/account", headers=A).text      # byte-identical to the portal (parity)
        self.assertIn('<a class="account" href="%s">Sign out</a>' % SIGNOUT, plain)
        self.assertNotIn("/signout", plain)

    def test_the_copy_does_not_claim_the_sign_in_service_session_ended(self):
        text = re.sub(r"<[^>]+>", " ", self.client().get("/account", headers=A).text)
        section = text.split("Signing out", 1)[1].split("Getting help", 1)[0]
        self.assertIn("signs you out of Avrana Media on this device", section)
        self.assertNotRegex(section, r"(?i)authentik|single sign|everywhere|as well|all (?:your )?(?:sessions|devices)")
        self.assertNotRegex(text, r"(?i)sign out from the account page")


if __name__ == "__main__":
    unittest.main()
