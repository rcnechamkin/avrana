"""Tier B: the optional home sections, the JSON view, degradation and cross-member isolation,
all through the HTTP layer against the mock Jellyfin (real UrllibTransport over loopback)."""
import concurrent.futures
import json
import re
import time
import unittest

from dev.mock_jellyfin import MockJellyfin

from .support import (GROUPS, USER, StubAdapter, make_client, make_settings, require_framework)

require_framework()

A = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos")]
B = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos|avrana-books|avrana-comics")]
C = [(USER, "member-c"), (GROUPS, "avrana-users|avrana-videos")]          # disabled Jellyfin account
D = [(USER, "member-d"), (GROUPS, "avrana-users|avrana-videos")]          # no Jellyfin account
NOLIB = [(USER, "member-nolib"), (GROUPS, "avrana-users|avrana-comics")]  # no video permission
ADMIN = [(USER, "synthetic-admin"), (GROUPS, "authentik Admins")]

A_ONLY = ["Synthetic Film One", "Synthetic Pilot", "Synthetic Series Alpha", "Synthetic Film Three",
          "aaaa0000000000000000000000000001", "aaaa0000000000000000000000000010"]
B_ONLY = ["Synthetic Film Two", "Synthetic Documentary B", "Synthetic Film Four",
          "bbbb0000000000000000000000000001", "bbbb0000000000000000000000000002",
          "bbbb0000000000000000000000000010", "1 hour 21 minutes left", "6 minutes left"]


def region(text):
    """The part of the page that holds the sections (the one <main>)."""
    return re.split(r"<main(?:\s[^>]*)?>", text)[1].split("</main>")[0]


def cards(text):
    """(class, href) of every card on the page."""
    return re.findall(r'<li class="(w-[a-z]+)"><a class="card" href="([^"]*)">', text)


class Fixture(unittest.TestCase):
    timeout = 0.6

    @classmethod
    def setUpClass(cls):
        cls.mock = MockJellyfin(slow_seconds=3.0).start()
        cls.on = make_client(make_settings(home_sections=True, jellyfin_base_url=cls.mock.url,
                                           timeout=cls.timeout))
        cls.off = make_client(make_settings(home_sections=False))
        cls.on.__enter__()
        cls.off.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.on.__exit__(None, None, None)
        cls.off.__exit__(None, None, None)
        cls.mock.stop()

    def fresh(self, **kw):
        """A new app (cold cache, closed circuit) against the shared mock."""
        client = make_client(make_settings(home_sections=True, jellyfin_base_url=self.mock.url,
                                           timeout=kw.pop("timeout", self.timeout), **kw))
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def setUp(self):
        self.mock.set_mode("ok")
        self.mock.reset()


class SectionRenderingTests(Fixture):
    def test_flag_off_has_no_sections_and_no_json_view(self):
        r = self.off.get("/", headers=A)
        self.assertNotIn("<h2", r.text)
        self.assertEqual(404, self.off.get("/home.json", headers=A).status_code)
        self.assertEqual([], self.mock.paths())

    def test_flag_on_renders_the_home_design_and_flag_off_stays_the_portal_page(self):
        flag_off = self.off.get("/", headers=A).text
        self.assertIn('<nav class="tiles" aria-label="Your Avrana services">', flag_off)
        self.assertNotIn('class="mast"', flag_off)
        r = self.on.get("/", headers=A)
        self.assertEqual(200, r.status_code)
        self.assertEqual(1, r.text.count('<nav class="places" aria-label="Avrana">'))
        self.assertNotIn('class="tiles"', r.text)
        above = region(r.text)
        for token in ("Synthetic Film One", "Synthetic Pilot", "Synthetic Film Three"):
            self.assertIn(token, above)
        self.assertIn('href="https://watch.avrana.net/web/#/details?id=aaaa0000000000000000000000000001"', above)
        self.assertIn("1 hour 10 minutes left", above)
        places = re.search(r'<nav class="places".*?</nav>', r.text, flags=re.S).group(0)
        for place in ("/watch", "/request", "/help"):
            self.assertIn(f'<a href="{place}">', places)

    def test_home_markup_follows_the_design(self):
        text = self.on.get("/", headers=A).text
        above = region(text)
        self.assertEqual(1, len(re.findall(r"<main(?:\s[^>]*)?>", text)))
        self.assertEqual(1, text.count("<h1>"))
        self.assertNotRegex(above, r"style=|<svg|<picture|<script|<canvas|on\w+=")
        self.assertEqual(2, above.count("<h2"))
        # Continue is bounded (at most four); artwork is decoration (alt="") from the artwork route only
        self.assertLessEqual(len(re.findall(r'class="card"', above.split('id="h-new"')[0])), 4)
        for tag in re.findall(r"<img[^>]*>", above):
            self.assertRegex(tag, r'^<img class="art" src="/art/[A-Za-z0-9_/-]+" alt="" width="160" height="240" loading="lazy">$')
        self.assertRegex(text, r'<details class="account">\s*<summary>')
        self.assertEqual(1, text.count('class="idlink" href="/search"'))   # Search is in the masthead

    def test_navigation_stays_reachable_for_every_state(self):
        for headers in (A, B, C, D, NOLIB, ADMIN):
            places = re.findall(r'<nav class="places".*?</nav>', self.on.get("/", headers=headers).text, flags=re.S)
            self.assertEqual(1, len(places))
            self.assertIn('href="/help"', places[0])

    def test_a_member_with_no_library_sees_nothing_to_show_and_no_upstream_call(self):
        self.mock.reset()
        page = self.on.get("/", headers=ADMIN).text
        self.assertIn("No library yet", page)
        self.assertNotIn('class="rail', page)
        self.assertNotIn("Movies and TV", page)
        self.assertEqual([], self.mock.paths(), "NOT_PERMITTED must make no upstream call")

    def test_a_library_the_member_cannot_use_leaves_no_trace(self):
        self.mock.reset()
        page = self.on.get("/", headers=NOLIB).text
        for needle in ("Movies and TV", "/watch", "Synthetic Film", "Watch"):
            self.assertNotIn(needle, page)
        self.assertEqual([], self.mock.paths())

    def test_not_linked_member_gets_a_neutral_sentence_naming_only_their_library(self):
        for headers in (C, D):
            r = self.on.get("/", headers=headers)
            above = region(r.text)
            # Not a dead end (#3): a section with its own heading, the sentence once, and the next step.
            self.assertIn('<h2 id="h-setup">Not set up yet</h2>', above)
            self.assertEqual(1, above.count("Movies and TV are not set up for your account yet."))
            self.assertIn('<a class="link" href="/help/trouble#not-set-up">What to do next</a>', above)
            self.assertNotIn('class="banner"', above)
            self.assertEqual([], cards(above))
            self.assertNotIn("error", above.lower())
            self.assertEqual(200, r.status_code)

    def test_empty_state_says_so_in_a_sentence(self):
        empty = StubAdapter({"member-a": []})
        client = make_client(make_settings(home_sections=True), adapters=[empty])
        r = client.get("/", headers=A)
        self.assertEqual(200, r.status_code)
        self.assertEqual([], cards(r.text))
        self.assertIn("Nothing in progress.", r.text)
        self.assertIn("Nothing new this week.", r.text)

    def test_hostile_titles_are_escaped_and_bidi_controls_removed(self):
        hostile = ['<script>alert(1)</script>', '"><img src=x onerror=alert(1)>', "' onmouseover='x",
                   "Normal" + chr(0x202e) + "evil", "a&b <b>bold</b>", "javascript:alert(1)"]
        data = {"member-a": [(f"{i:032x}", t, 0.5) for i, t in enumerate(hostile, start=1)]}
        client = make_client(make_settings(home_sections=True), adapters=[StubAdapter(data)])
        for path in ("/", "/home.json"):
            r = client.get(path, headers=A)
            self.assertEqual(200, r.status_code)
        page = client.get("/", headers=A).text
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        self.assertNotIn("<b>bold</b>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn(chr(0x202e), page)
        self.assertNotRegex(page, r"""<[^>]*\sonerror=""")
        self.assertNotRegex(page, r"""<[^>]*\sonmouseover=""")
        # card hrefs are only ever the contract's fixed https hand-off hostnames
        found = cards(region(page))
        self.assertTrue(found)
        for _cls, href in found:
            self.assertTrue(href.startswith("https://watch.avrana.net/web/#/details?id="), href)

    def test_account_page_escapes_identity_fields(self):
        hostile = [(USER, "m<script>alert(1)</script>"), (GROUPS, "avrana-users"),
                   ("X-authentik-name", '"><img src=x onerror=1>'), ("X-authentik-email", "a&b'c@example.test")]
        r = self.on.get("/account", headers=hostile)
        self.assertNotIn("<script>alert", r.text)
        self.assertNotIn("<img src=x", r.text)
        self.assertIn("m&lt;script&gt;alert(1)&lt;/script&gt;", r.text)
        self.assertIn("a&amp;b&#39;c@example.test", r.text)


class NavigationAndCallPatternTests(Fixture):
    NAV = '<nav class="tiles" aria-label="Your Avrana services">'
    PLACES = '<nav class="places" aria-label="Avrana">'

    def test_places_and_footer_are_present_once_in_every_state(self):
        """Watch/Request/Help/Account stay reachable whatever the sections do."""
        scenarios = [("ok", self.on, A), ("not_linked", self.on, D),
                     ("no library", self.on, ADMIN), ("no principal", self.on, [])]
        failing = self.fresh()
        self.mock.set_mode("500")
        scenarios.append(("unavailable", failing, A))
        for label, client, headers in scenarios:
            with self.subTest(state=label):
                text = client.get("/", headers=headers).text
                if label == "no principal":
                    self.assertEqual(1, text.count(self.NAV))      # not a member: the portal page
                    continue
                self.assertEqual(1, text.count(self.PLACES))
                self.assertEqual(1, text.count("<footer>"))
                self.assertEqual(1, len(re.findall(r"<main(?:\s[^>]*)?>", text)))
                self.assertIn('href="/help"', text.split("</header>")[0])   # Help in the masthead's places bar (#56)
                self.assertIn('href="/account"', text.split("<footer>")[0])   # the masthead's account menu
        self.mock.set_mode("ok")

    def test_one_cold_page_makes_one_mapping_call(self):
        client = self.fresh()
        self.mock.reset()
        client.get("/", headers=A)
        paths = self.mock.paths()
        self.assertEqual(1, paths.count("/Users"), paths)
        self.assertEqual(1, paths.count("/UserItems/Resume"))
        self.assertEqual(1, paths.count("/Items/Latest"))
        self.mock.reset()
        client.get("/", headers=A)
        self.assertEqual([], self.mock.paths())            # warm: no upstream call at all

    def test_concurrent_cold_requests_from_one_member_all_get_a_page(self):
        self.mock.set_mode("slow")
        client = self.fresh(timeout=0.4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            replies = list(pool.map(lambda _i: client.get("/", headers=A), range(6)))
        self.assertEqual({200}, {r.status_code for r in replies})
        for r in replies:
            self.assertEqual(1, r.text.count(self.PLACES))
            self.assertIn("unavailable right now", r.text)
        self.mock.set_mode("ok")

    def test_cache_is_one_per_process_in_memory_and_closed_on_shutdown(self):
        client = make_client(make_settings(home_sections=True, jellyfin_base_url=self.mock.url))
        app = client.fastapi_app
        self.assertIs(app.state.cache, app.state.adapters[0].cache)
        with client:
            client.get("/", headers=A)
        self.assertTrue(app.state.cache._closed)


class JsonViewTests(Fixture):
    def test_json_is_exactly_the_member_view_contract(self):
        r = self.on.get("/home.json", headers=A)
        self.assertEqual(200, r.status_code)
        self.assertTrue(r.headers["content-type"].startswith("application/json"))
        self.assertEqual("no-store", r.headers["cache-control"])
        self.assertEqual("nosniff", r.headers["x-content-type-options"])
        doc = r.json()
        self.assertEqual({"sections"}, set(doc))
        self.assertEqual([("jellyfin", "continue", "ok"), ("jellyfin", "recent", "ok")],
                         [(s["service"], s["section"], s["state"]) for s in doc["sections"]])
        for s in doc["sections"]:
            self.assertEqual({"service", "section", "state", "items"}, set(s))
            for it in s["items"]:
                self.assertEqual({"id", "service", "kind", "title", "subtitle", "series", "progress",
                                  "artwork", "creator", "year", "summary", "handoff_url"}, set(it))
                self.assertIsNone(it["summary"])       # a synopsis only on the title page (R2-C)
        self.assertNotIn("reason", r.text)

    def test_not_permitted_is_omitted_entirely(self):
        self.assertEqual({"sections": []}, self.on.get("/home.json", headers=NOLIB).json())

    def test_other_states_serialise_with_empty_items(self):
        self.assertEqual(["not_linked", "not_linked"],
                         [s["state"] for s in self.on.get("/home.json", headers=D).json()["sections"]])
        self.mock.set_mode("500")
        fresh = self.fresh()
        doc = fresh.get("/home.json", headers=A).json()
        self.assertEqual(["unavailable", "unavailable"], [s["state"] for s in doc["sections"]])
        self.assertTrue(all(s["items"] == [] for s in doc["sections"]))

    def test_json_requires_a_principal_and_takes_no_identity_from_the_request(self):
        r = self.on.get("/home.json")
        self.assertEqual(404, r.status_code)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertEqual(self.on.get("/home.json", headers=A).json(),
                         self.on.get("/home.json?userId=bbbbbbbbbbbb4bbb8bbbbbbbbbbbbbbb&user=member-b",
                                     headers=A).json())

    def test_json_and_html_agree(self):
        doc = self.on.get("/home.json", headers=A).json()
        page = self.on.get("/", headers=A).text
        urls = {it["handoff_url"] for s in doc["sections"] for it in s["items"]}
        shown = [href for _cls, href in cards(page)]
        self.assertTrue(shown)
        self.assertTrue(set(shown) <= urls)           # the page is a bounded subset of the JSON, never more


class DegradationTests(Fixture):
    def assert_degraded_page(self, r, started):
        self.assertEqual(200, r.status_code)
        # The member's only library is down: the calm block, with one combined line naming it (#13).
        self.assertIn('<p class="said" role="status">Movies and TV are unavailable right now. This usually passes', r.text)
        self.assertNotIn('class="banner"', r.text)
        self.assertIn('<s>Watch</s><span class="sr">, unavailable: what to do</span>', r.text)    # struck, kept in place
        for tile in ("/request", "/help"):
            self.assertIn(f'href="{tile}"', r.text)
        self.assertEqual([], cards(region(r.text)))
        self.assertNotIn("error", region(r.text).lower())
        self.assertLess(time.monotonic() - started, 2.5)

    def test_each_failure_mode_costs_only_the_section(self):
        for mode in ("500", "malformed", "down"):
            with self.subTest(mode=mode):
                self.mock.set_mode(mode)
                client = self.fresh()
                started = time.monotonic()
                r = client.get("/", headers=A)
                self.assert_degraded_page(r, started)

    def test_wrong_user_data_degrades_only_the_section_it_poisoned(self):
        """The mock answers the resume list with the other member's items (naming them); the
        adapter's scope tripwire discards it. The recently-added list is a different call and
        still renders."""
        self.mock.set_mode("wrong-user")
        r = self.fresh().get("/", headers=A)
        above = region(r.text)
        # One section unavailable: the library counts as down (#6), so Watch is struck and the notice says the
        # list still shown may be out of date.
        self.assertIn('<p class="banner" role="status">Movies and TV are unavailable right now. Anything shown from '
                      'them may be out of date.</p>', above)
        self.assertIn('<s>Watch</s>', r.text)
        self.assertIn("Synthetic Film Three", above)
        self.assertNotIn("Synthetic Film Two", r.text)

    def test_slow_beyond_the_timeout(self):
        self.mock.set_mode("slow")
        client = self.fresh(timeout=0.3)
        started = time.monotonic()
        r = client.get("/", headers=A)
        self.assert_degraded_page(r, started)

    def test_upstream_stopped_entirely(self):
        mock = MockJellyfin().start()
        client = make_client(make_settings(home_sections=True, jellyfin_base_url=mock.url, timeout=0.5))
        mock.stop()
        started = time.monotonic()
        self.assert_degraded_page(client.get("/", headers=A), started)

    def test_other_pages_and_other_members_are_unaffected(self):
        self.mock.set_mode("500")
        client = self.fresh()
        self.assertEqual(200, client.get("/help", headers=A).status_code)
        self.assertEqual(200, client.get("/account", headers=A).status_code)
        self.assertEqual(200, client.get("/watch", headers=A).status_code)
        nolib = client.get("/", headers=NOLIB)
        self.assertNotIn("unavailable", nolib.text)            # never names a library they cannot use

    def test_recovery_after_the_cool_off_needs_no_restart(self):
        self.mock.set_mode("500")
        client = self.fresh()
        for _ in range(3):
            client.get("/", headers=A)
        adapter = client.fastapi_app.state.adapters[0]
        self.assertEqual("cooling_off", adapter.health().state)
        self.mock.set_mode("ok")
        adapter.breaker._open_until = 0.0           # the 60 s cool-off elapsing (no sleeping in tests)
        # Half-open admits exactly ONE trial (resilience.CircuitBreaker). Continue and Recently added are fetched
        # concurrently and race for it; the loser is refused as cooling off. When Recently added wins, this first
        # page has no Continue, and "Synthetic Film One" is a Continue item only (AVR-733: the old single-page
        # assertion failed whenever that thread won). The trial's success must close the circuit, with no restart.
        client.get("/", headers=A)
        self.assertEqual("ok", adapter.health().state)
        r = client.get("/", headers=A)
        self.assertIn("Synthetic Film One", r.text)
        self.assertEqual("ok", adapter.health().state)

    def test_half_open_trial_goes_to_one_section_and_its_sibling_is_refused(self):
        """AVR-733, made deterministic: Recently added takes the trial and holds it until Continue has asked."""
        import threading
        self.mock.set_mode("500")
        client = self.fresh()
        for _ in range(3):
            client.get("/", headers=A)
        adapter = client.fastapi_app.state.adapters[0]
        self.mock.set_mode("ok")
        adapter.breaker._open_until = 0.0
        real_acquire, real_recent, real_continue = adapter.breaker.acquire, adapter.recent_items, adapter.continue_items
        holder = threading.local()
        held, asked = threading.Event(), threading.Event()

        def acquire(trial=True):
            token = real_acquire(trial)
            if getattr(holder, "first", False):
                held.set()                       # the trial call is in flight ...
                asked.wait(5)                    # ... until Continue has been answered
            return token

        def recent(*a, **k):
            holder.first = True
            try:
                return real_recent(*a, **k)
            finally:
                holder.first = False

        def continue_(*a, **k):
            held.wait(5)                         # asks only while Recently added holds the trial
            try:
                return real_continue(*a, **k)
            finally:
                asked.set()

        adapter.breaker.acquire, adapter.recent_items, adapter.continue_items = acquire, recent, continue_
        try:
            first = client.get("/", headers=A).text
        finally:
            adapter.breaker.acquire, adapter.recent_items, adapter.continue_items = (real_acquire, real_recent,
                                                                                     real_continue)
        self.assertNotIn("Synthetic Film One", first)   # Continue was refused: no upstream call, no stale data
        self.assertEqual("ok", adapter.health().state)  # the trial closed the circuit
        self.assertIn("Synthetic Film One", client.get("/", headers=A).text)

    def test_wrong_user_data_never_reaches_the_page_or_json(self):
        self.mock.set_mode("wrong-user")
        for headers, other in ((A, B_ONLY), (B, A_ONLY)):
            client = self.fresh()
            for path in ("/", "/home.json"):
                text = client.get(path, headers=headers).text
                for token in other:
                    self.assertNotIn(token, text, (path, token))


class IsolationTests(Fixture):
    def test_members_never_see_each_others_titles_ids_or_progress_even_concurrently_with_a_warm_cache(self):
        client = self.on
        for headers in (A, B):                       # warm the cache
            client.get("/", headers=headers)
        self.mock.reset()

        def fetch(i):
            headers, other = (A, B_ONLY) if i % 2 == 0 else (B, A_ONLY)
            out = []
            for path in ("/", "/home.json"):
                out.append((client.get(path, headers=headers).text, other, path))
            return out

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = [item for batch in pool.map(fetch, range(48)) for item in batch]
        for text, other, path in results:
            for token in other:
                self.assertNotIn(token, text, (path, token))
        self.assertEqual([], self.mock.paths(), "a warm cache should answer without upstream calls")

    def test_cold_concurrent_start_does_not_cross_members(self):
        client = self.fresh()

        def fetch(i):
            headers, other = (A, B_ONLY) if i % 2 == 0 else (B, A_ONLY)
            return client.get("/home.json", headers=headers).text, other

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for text, other in pool.map(fetch, range(32)):
                for token in other:
                    self.assertNotIn(token, text)

    def test_removing_a_group_takes_effect_immediately_with_a_warm_cache(self):
        self.assertIn("Synthetic Film One", self.on.get("/home.json", headers=A).text)
        no_video = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-books")]
        self.assertEqual({"sections": []}, self.on.get("/home.json", headers=no_video).json())

    def test_case_variants_of_a_username_do_not_share_or_borrow_data(self):
        shout = [(USER, "MEMBER-A"), (GROUPS, "avrana-users|avrana-videos")]
        doc = self.on.get("/home.json", headers=shout).json()
        self.assertEqual(["not_linked", "not_linked"], [s["state"] for s in doc["sections"]])
        self.assertNotIn("Synthetic Film One", json.dumps(doc))


if __name__ == "__main__":
    unittest.main()
