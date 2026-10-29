"""Tier B: Customize (Media 2.0 HOME-01/02) and the device-setup card (ME-02). SYNTHETIC data.

What this slice adds and must never weaken:
  * One Home per account: the place it starts on, the places shown and the order of its sections, saved once and the
    same on every device (two clients sharing one store stand in for two devices). No device override exists.
  * Effective = saved ∩ allowed now: hiding is presentation only, a lost place drops out quietly, at least one place
    stays, and the start counts only while it is the member's and shown. An explicit `?for=` wins and saves nothing.
  * Every save goes through the locks (same origin, the allow-listed fields, this member's token, the version the page
    was drawn from) and replaces the whole record or nothing; an unreadable store renders defaults and writes nothing.
  * Hiding the setup suggestion changes how Me looks and nothing else: no upstream call, setup stays one row away.
"""
import re
import tempfile
import unittest
from pathlib import Path

from avrana_home.app import customize
from avrana_home.app.catalogue import Trusted
from avrana_home.app.viewmodel import build_continue_page, build_home, home_start
from avrana_home.memberstore import HOME_DEFAULT, HomePrefs, MemberStore
from .support import GROUPS, USER, StubAdapter, make_client, make_settings, require_framework

require_framework()

TILES = [("watch", Trusted("Watch"), Trusted("Movies &amp; TV")), ("listen", Trusted("Listen"), Trusted("Audiobooks")),
         ("read", Trusted("Read"), Trusted("Comics")), ("request", Trusted("Request"), Trusted("Ask")),
         ("help", Trusted("Help"), Trusted("Guides"))]


def item(i, title, kind="movie", service="x", progress=None):
    return {"id": f"x:{i}", "service": service, "kind": kind, "title": title, "series": None, "subtitle": None,
            "handoff_url": f"https://watch.avrana.net/web/#/details?id={i}", "progress": progress, "artwork": None}


def sec(service, section, state, items=()):
    return {"service": service, "section": section, "state": state, "items": list(items), "reason": None}


VIEW = {"sections": [sec("jellyfin", "continue", "ok", [item(1, "A Film", progress={"fraction": 0.5})]),
                     sec("jellyfin", "recent", "empty"),
                     sec("audiobookshelf", "continue", "ok", [item(2, "A Book", "audiobook", progress={"fraction": 0.2})]),
                     sec("audiobookshelf", "recent", "empty")]}


class Effective(unittest.TestCase):
    def test_defaults_are_homes_own(self):
        for prefs in (None, HOME_DEFAULT):
            home = build_home(VIEW, TILES, prefs=prefs)
            self.assertEqual((None, ("continue", "released", "new")), (home.focus, home.order))
            self.assertEqual(["/", "/?for=watch", "/?for=listen", "/?for=read"], [f.href for f in home.filters])

    def test_start_applies_only_without_an_explicit_choice(self):
        prefs = HomePrefs(1, "listen", (), ("new", "continue", "released"))
        home = build_home(VIEW, TILES, prefs=prefs)
        self.assertEqual("listen", home.focus)
        self.assertEqual(["A Book"], [c.title for c in home.continue_items])
        self.assertEqual("/?for=all", home.filters[0].href)            # All stays All while a start is saved
        self.assertEqual(("new", "continue", "released"), home.order)
        self.assertEqual("watch", build_home(VIEW, TILES, prefs=prefs, focus="watch").focus)
        everything = build_home(VIEW, TILES, prefs=prefs, focus="all")
        self.assertIsNone(everything.focus)
        self.assertTrue(everything.filters[0].current)
        self.assertEqual(["/?for=all#h-new"], list(everything.new_hrefs)[:1])
        self.assertEqual("listen", home_start(prefs, TILES))
        # the Continue page reached from that All goes back to All, not to the start
        self.assertEqual("/?for=all", build_continue_page(VIEW, TILES, focus="all").back_href)

    def test_hidden_places_leave_the_filters_and_all(self):
        home = build_home(VIEW, TILES, prefs=HomePrefs(1, "all", ("listen",)))
        self.assertEqual(["/", "/?for=watch", "/?for=read"], [f.href for f in home.filters])
        self.assertEqual(["A Film"], [c.title for c in home.continue_items])
        self.assertNotIn("/listen", [p.href for p in home.places])

    def test_saved_meets_allowed_now(self):
        # every place hidden: ignored, at least one stays
        self.assertEqual(4, len(build_home(VIEW, TILES, prefs=HomePrefs(1, "all", ("watch", "listen", "read"))).filters))
        # a start the member lost (no Comics place here) or one that is hidden: All
        for prefs in (HomePrefs(1, "comics"), HomePrefs(1, "listen", ("listen",))):
            self.assertIsNone(build_home(VIEW, TILES, prefs=prefs).focus, prefs)
            self.assertIsNone(home_start(prefs, TILES))
        # a place gained later appears (only "hidden" is stored)
        two = TILES[:2] + TILES[3:]
        self.assertEqual(3, len(build_home(VIEW, two, prefs=HomePrefs(1, "all", ("read",))).filters))


class Parse(unittest.TestCase):
    KEYS = ["watch", "listen", "read"]
    ORDER = {"o1": "new", "o2": "continue", "o3": "released"}

    def form(self, **kw):
        return dict(self.ORDER, start="all", show_watch="on", show_listen="on", show_read="on", **kw)

    def test_good_forms(self):
        self.assertEqual((None, "listen", ("read",), ("new", "continue", "released")),
                         customize.parse(dict(self.ORDER, start="listen", show_watch="on", show_listen="on"),
                                         self.KEYS))
        # one place: nothing to choose, only the order
        self.assertEqual((None, "all", (), ("new", "continue", "released")),
                         customize.parse(dict(self.ORDER, start="watch"), ["watch"]))

    def test_refusals(self):
        bad = [(dict(self.form(), show_comics="on"), "invalid"),       # a place that isn't theirs
               (dict(self.form(), show_watch="yes"), "invalid"),
               (dict(self.form(), o3="continue"), "invalid"),
               (dict(self.form(), start="comics"), "invalid"),
               (dict(self.ORDER, start="all"), "none_shown"),
               (dict(self.ORDER, start="watch", show_listen="on"), "start_hidden")]
        for form, why in bad:
            self.assertEqual(why, customize.parse(form, self.KEYS)[0], form)


ALL = [(USER, "member-a"), (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks|avrana-comics|avrana-books")]
B = [(USER, "member-b"), (GROUPS, "avrana-users|avrana-videos|avrana-audiobooks|avrana-comics|avrana-books")]
NOLIB = [(USER, "member-n"), (GROUPS, "avrana-users")]
DATA = {"member-a": [("a" * 32, "Synthetic Film", 0.5)], "member-b": [], "member-n": []}


def filters(text):
    nav = re.search(r'<nav class="places filters"[^>]*>(.*?)</nav>', text, re.S)
    return re.findall(r'<a href="([^"]*)"', nav.group(1)) if nav else []


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MemberStore(Path(self.tmp.name) / "members.sqlite3")
        self.stub = StubAdapter(DATA)
        self.client = self.open()

    def open(self):
        c = make_client(make_settings(home_sections=True), adapters=[self.stub], member_store=self.store)
        c.__enter__()
        self.addCleanup(c.__exit__, None, None, None)
        return c

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def fields(self, client=None, headers=ALL, query=""):
        r = (client or self.client).get("/me/home" + query, headers=headers)
        self.assertEqual(200, r.status_code)
        return (re.search(r'name="t" value="([^"]+)"', r.text).group(1),
                re.search(r'name="v" value="([^"]+)"', r.text).group(1), r.text)

    def post(self, body, client=None, headers=ALL, site="same-origin", path="/me/home"):
        h = dict(headers, **{"Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": site})
        return (client or self.client).post(path, content=body, headers=h)


class Editor(Base):
    def test_the_form_starts_from_the_record_and_names_every_device(self):
        t, v, text = self.fields(query="?from=home")
        main = text.split("<main", 1)[1]
        self.assertIn("These settings apply to your account on every device.", main)
        self.assertIn('<input type="hidden" name="from" value="home">', main)
        self.assertIn('<a class="kbtn kbtn-quiet" href="/">Cancel</a>', main)
        self.assertEqual(["watch", "listen", "read"], re.findall(r'name="show_([a-z]+)"', main))
        self.assertEqual(["continue", "released", "new"], re.findall(r'name="o\d" value="([a-z]+)"', main))
        self.assertIn('class="cz-moves" hidden', main)                    # the Move buttons need JavaScript
        self.assertNotIn("Authentik", text)
        _t, _v, plain = self.fields()
        self.assertIn('<a class="kbtn kbtn-quiet" href="/me">Cancel</a>', plain)

    def test_save_on_one_device_shows_on_another(self):
        t, v, _ = self.fields(query="?from=home")
        r = self.post(f"t={t}&v={v}&from=home&start=listen&show_watch=on&show_listen=on&o1=new&o2=continue&o3=released")
        self.assertEqual((303, "/"), (r.status_code, r.headers["location"]))
        other = self.open()                                  # a second device: same store, its own app
        home = other.get("/", headers=ALL).text
        self.assertEqual(["/?for=all", "/?for=watch", "/?for=listen"], filters(home))
        self.assertIn('aria-current="true"', re.search(r'<a href="/\?for=listen"[^>]*>', home).group(0))
        self.assertIn('<a class="custbtn glass" href="/me/home?from=home">', home)
        _t, _v, form = self.fields(other)
        self.assertIn('value="listen" checked', form)
        self.assertNotIn('name="show_read" value="on" checked', form)
        # an explicit choice wins and saves nothing
        self.assertEqual(["/?for=all", "/?for=watch", "/?for=listen"], filters(other.get("/?for=watch", headers=ALL).text))
        self.assertEqual("listen", self.store.home("member-a").start)

    def test_accounts_are_isolated(self):
        t, v, _ = self.fields()
        self.post(f"t={t}&v={v}&start=listen&show_watch=on&show_listen=on&o1=continue&o2=released&o3=new")
        self.assertEqual(["/", "/?for=watch", "/?for=listen", "/?for=read"], filters(self.client.get("/", headers=B).text))
        self.assertEqual(0, self.store.home("member-b").version)


class Locks(Base):
    GOOD = "start=all&show_watch=on&o1=continue&o2=released&o3=new"

    def test_stale_version_is_a_conflict_and_bad_forms_change_nothing(self):
        t, v, _ = self.fields()
        self.assertEqual("/me/home?r=saved", self.post(f"t={t}&v={v}&{self.GOOD}").headers["location"])
        self.assertEqual("/me/home?r=conflict", self.post(f"t={t}&v={v}&start=listen&show_listen=on&o1=continue&o2=released&o3=new")
                         .headers["location"])
        t, v, _ = self.fields()
        for body, why in ((f"t={t}&v={v}&start=watch&show_listen=on&o1=continue&o2=released&o3=new", "start_hidden"),
                          (f"t={t}&v={v}&start=all&o1=continue&o2=released&o3=new", "none_shown"),
                          (f"t={t}&v={v}&start=all&show_comics=on&o1=continue&o2=released&o3=new", "invalid")):
            self.assertEqual(f"/me/home?r={why}", self.post(body).headers["location"], why)
        saved = self.store.home("member-a")
        self.assertEqual((1, "all", ("listen", "read")), (saved.version, saved.start, saved.hidden))

    def test_token_site_and_field_locks(self):
        t, v, _ = self.fields()
        self.assertEqual("/me/home?r=expired", self.post(f"t={t}&v={v}&{self.GOOD}", headers=B).headers["location"])
        self.assertEqual(403, self.post(f"t={t}&v={v}&{self.GOOD}", site="cross-site").status_code)
        self.assertEqual(400, self.post(f"t={t}&v={v}&{self.GOOD}&admin=1").status_code)
        self.assertEqual(400, self.post(f"t={t}&v={v}&{self.GOOD}&start=all").status_code)       # repeated
        self.assertEqual(0, self.store.home("member-a").version)

    def test_unreadable_store_renders_defaults_and_writes_nothing(self):
        class Broken(MemberStore):
            def home(self, member):
                return None
        broken = Broken(Path(self.tmp.name) / "b.sqlite3")
        self.addCleanup(broken.close)
        with make_client(make_settings(home_sections=True), adapters=[self.stub], member_store=broken) as c:
            self.assertEqual(["/", "/?for=watch", "/?for=listen", "/?for=read"], filters(c.get("/", headers=ALL).text))
            text = c.get("/me/home", headers=ALL).text
            self.assertIn("couldn't be loaded just now", text)
            self.assertNotIn("<form", text.split("<main", 1)[1])

    def test_store_off(self):
        with make_client(make_settings(home_sections=True), adapters=[self.stub]) as c:
            self.assertNotIn('class="custbtn', c.get("/", headers=ALL).text)
            self.assertIn("isn't switched on yet", c.get("/me/home", headers=ALL).text)
            self.assertNotIn("/me/home", c.get("/me", headers=ALL).text)
            h = dict(ALL, **{"Content-Type": "application/x-www-form-urlencoded"})
            self.assertEqual(501, c.post("/me/home", content=self.GOOD, headers=h).status_code)
            self.assertEqual(501, c.post("/me/setup", content="do=hide", headers=h).status_code)

    def test_gating(self):
        nope = self.client.get("/nope", headers=[])
        r = self.client.get("/me/home", headers=[])
        self.assertEqual((404, nope.text), (r.status_code, r.text))


class SetupCard(Base):
    def me(self, headers=ALL, query=""):
        return self.client.get("/me" + query, headers=headers).text.split("<main", 1)[1]

    def test_me_and_the_editor_may_post_forms_only_to_this_site(self):
        for path in ("/me", "/me/home"):
            self.assertIn("form-action 'self'", self.client.get(path, headers=ALL).headers["content-security-policy"])
        with make_client(make_settings(home_sections=True), adapters=[self.stub]) as c:
            self.assertIn("form-action 'none'", c.get("/me", headers=ALL).headers["content-security-policy"])

    def test_hide_and_show_again_touch_nothing_upstream(self):
        me = self.me()
        self.assertIn("Watch and listen on your devices", me)
        self.assertIn('<a class="kbtn kbtn-go" href="/help">Set up a device</a>', me)
        self.assertIn(">Hide setup suggestion</button>", me)
        token = re.search(r'action="/me/setup".*?name="t" value="([^"]+)"', me, re.S).group(1)
        calls = self.stub.calls
        r = self.post(f"t={token}&do=hide", path="/me/setup")
        self.assertEqual((303, "/me?r=setup_hidden"), (r.status_code, r.headers["location"]))
        self.assertEqual(calls, self.stub.calls)
        me = self.me(query="?r=setup_hidden")
        self.assertNotIn("Watch and listen on your devices", me)
        self.assertIn("Suggestion hidden. Set up a device is still under Devices.", me)
        self.assertIn('<a class="krow-a" href="/help">', me)              # setup stays one row away
        self.assertIn("Show the setup suggestion again", me)
        self.assertNotIn("Connected", me)
        token = re.search(r'action="/me/setup".*?name="t" value="([^"]+)"', me, re.S).group(1)
        self.assertEqual("/me?r=setup_shown", self.post(f"t={token}&do=show", path="/me/setup").headers["location"])
        self.assertIn("Watch and listen on your devices", self.me())
        # another member's view is their own
        self.post(f"t={token}&do=hide", path="/me/setup")
        self.assertIn("Watch and listen on your devices", self.me(B))

    def test_locks_and_members_without_a_library(self):
        token = re.search(r'action="/me/setup".*?name="t" value="([^"]+)"', self.me(), re.S).group(1)
        self.assertEqual("/me?r=expired", self.post(f"t={token}&do=hide", headers=B, path="/me/setup").headers["location"])
        self.assertEqual(400, self.post(f"t={token}&do=revoke", path="/me/setup").status_code)
        self.assertEqual(403, self.post(f"t={token}&do=hide", site="cross-site", path="/me/setup").status_code)
        self.assertEqual(0, self.store.setup_hidden("member-a"))
        nolib = self.me(NOLIB)
        for absent in ("setup-card", "me-devices", "/me/home"):
            self.assertNotIn(absent, nolib, absent)

    def test_store_off_shows_the_card_without_a_hide_button(self):
        with make_client(make_settings(home_sections=True), adapters=[self.stub]) as c:
            me = c.get("/me", headers=ALL).text
            self.assertIn("Watch and listen on your devices", me)
            self.assertNotIn("Hide setup suggestion", me)

    def test_purge_removes_home_and_setup_state(self):
        self.store.save_home("member-a", "listen", (), ("continue", "released", "new"), 0)
        self.store.set_setup_hidden("member-a", customize.SETUP_CARD)
        self.assertTrue(self.store.purge("member-a"))
        self.assertEqual((0, 0), (self.store.home("member-a").version, self.store.setup_hidden("member-a")))


if __name__ == "__main__":
    unittest.main()
