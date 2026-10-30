"""Route-level degraded-state matrix (coverage review T-01, T-03). SYNTHETIC adapters through the REAL app.

2026-10-29: Listen and Read answered HTTP 500 on the live beta when their library had nothing added lately. #146 fixed a
shadowed local in the view model and #148 pinned the template, but nothing requested a ROUTE. This module does: four
libraries, each section in one of ok / empty / unavailable / not_linked, across every Home, Continue, Library and Search
route, for a member who holds all four libraries and for a comics-only member. Every response must be a calm 200.

Jinja runs with StrictUndefined (the app builds its environment in `make_environment`, kept on `app.state.env`; the test
swaps `env.undefined` on its own app, application code is untouched), so a template that reads a name the view model
does not give fails loudly instead of rendering as empty.
"""
import itertools
import json
import random
import re
import time
import unittest

from avrana_home.aggregate import derive_hard_cap

from .plan_adapters import (ALL_GROUPS, COMICS_GROUPS, OFFERED, SERVICES, STATES, adapters_for)
from .support import GROUPS, USER, make_client, make_settings, require_framework

require_framework()

from avrana_home.contract import Service  # noqa: E402
from jinja2 import StrictUndefined  # noqa: E402

LABEL = {"jellyfin": "Movies and TV", "audiobookshelf": "Audiobooks", "komga": "Comics", "calibre-web": "Books"}
MEMBERS = {"all": [(USER, "member-a"), (GROUPS, ALL_GROUPS)], "comics": [(USER, "comics-a"), (GROUPS, COMICS_GROUPS)]}
FOCI = ("watch", "listen", "read", "comics", "books")
VIEWS = ("shelves", "grid", "compact", "list", "large", "small", "details")
RELS = ("watch", "listen", "comics", "books", "bogus")
BAD_WORDS = ("Traceback", "UndefinedError", "Something went wrong")
# DEFECT (reported; pinned by BareHeadingsUnderABanner below): when a library is unavailable or not set up, Home can keep a
# section heading ("Continue", "New to Avrana") with no card and no line under it; the page banner explains the library,
# but the heading is still empty. The sweep tolerates that ONLY beside a banner or warning; anywhere else it fails.
SEED = 20261029
RANDOM_CASES = 8     # keeps the module well inside its time budget; the 81 uniform combinations are always run


def routes(n):
    """Home, Listen, Read and the library are asked in every scenario (the 500 class); the families with many spellings
    rotate with the scenario number `n`, so the whole run covers each spelling and a scenario always asks the same."""
    svc = [s.value for s in SERVICES]
    slot1 = [f"/?for={FOCI[n % 5]}", f"/continue?for={FOCI[n % 5]}", f"/?for={FOCI[(n + 1) % 5]}", "/continue"]
    slot2 = [f"/?rel={RELS[n % 5]}", f"/?new={svc[n % 4]}", f"/?rel={RELS[(n + 1) % 5]}&for={FOCI[n % 5]}",
             f"/?new={svc[(n + 1) % 4]}&for={FOCI[(n + 3) % 5]}", "/?rel=books,comics"]
    slot3 = [f"/library?lib={svc[n % 4]}&view={VIEWS[n % 7]}", f"/library?view={VIEWS[n % 7]}",
             f"/library?lib={svc[(n + 1) % 4]}&view={VIEWS[(n + 3) % 7]}"]
    slot4 = ["/search?q=a", "/home.json", "/?more=released", "/?more=new", "/?more=bogus"]
    rotating = [slot1[n % 4], slot2[n % 5], slot3[n % 3], slot4[n % 5]]
    return ["/", "/?for=listen", "/?for=read", "/library", rotating[n % 4], rotating[(n + 1 + n // 4) % 4]]


def plans_uniform(combo):
    return {s: {sec: st for sec in OFFERED[s]} for s, st in zip(SERVICES, combo)}


def scenarios():
    for combo in itertools.product(("ok", "empty", "unavailable"), repeat=4):
        yield "uniform:" + "/".join(combo), plans_uniform(combo)
    for st in ("not_linked",):
        yield f"uniform:{st}", plans_uniform((st,) * 4)
    rnd = random.Random(SEED)
    for k in range(RANDOM_CASES):
        plans = {s: {sec: rnd.choice(STATES) for sec in OFFERED[s]} for s in SERVICES}
        yield f"random#{k}:" + json.dumps({s.value: "".join(p[x][0] for x in OFFERED[s]) for s, p in plans.items()}), plans


def strict_client(adapters):
    client = make_client(make_settings(home_sections=True), adapters=adapters)
    client.fastapi_app.state.env.undefined = StrictUndefined
    return client


def main_of(text):
    parts = re.split(r"<main(?:\s[^>]*)?>", text, maxsplit=1)
    return parts[1].split("</main>")[0] if len(parts) == 2 else ""


def hard_bare(main):
    """Empty-rail headings on a page that does NOT say a library is degraded (nothing excuses them)."""
    return [] if ('class="banner"' in main or 'class="k-warn' in main) else empty_headings(main)


def empty_headings(main):
    """Headings of sections that hold neither a card, a line of text nor a notice (an empty rail with a title)."""
    bad = []
    for chunk in main.split("<section")[1:]:
        body = chunk.split("</section>")[0]
        if 'class="hero ' in body.split(">", 1)[0]:
            continue
        for h in re.findall(r"<h2[^>]*>([^<]*)</h2>", body):
            if not re.search(r"<li\b|class=\"said\"|<p\b|<nav\b|class=\"k-", body):
                bad.append(h)
    return bad


def tile_problems(text):
    """A place tile or chip is a link, or struck through and then says why (screen-reader text)."""
    bad = []
    for nav in re.findall(r'<nav class="(?:places|chips)[^"]*".*?</nav>', text, flags=re.S):
        for child in re.findall(r"<(a|span|s|div|button)\b", nav):
            if child == "div" or child == "button":
                bad.append("tile is not a link: " + child)
        for anchor in re.findall(r"<a\b[^>]*>.*?</a>", nav, flags=re.S):
            if " href=" not in anchor:
                bad.append("anchor without href")
            if "<s>" in anchor and not re.search(r'class="sr">[^<]*(unavailable|not set up)', anchor):
                bad.append("struck tile without a reason")
    return bad


def problems(client, headers, url, cap):
    t0 = time.monotonic()
    r = client.get(url, headers=headers)
    took = time.monotonic() - t0
    out = []
    if r.status_code != 200:
        return [f"{url}: status {r.status_code}"]
    if took > cap:
        out.append(f"{url}: {took:.1f}s is over the {cap:.1f}s hard cap")
    text = r.text
    if url == "/home.json":
        try:
            json.loads(text)
        except ValueError:
            out.append(f"{url}: not JSON")
        return out
    for word in BAD_WORDS:
        if word in text:
            out.append(f"{url}: page contains {word!r}")
    if len(re.findall(r"<main[\s>]", text)) != 1:
        out.append(f"{url}: {len(re.findall(r'<main[\\s>]', text))} <main> elements")
    for h in hard_bare(main_of(text)):
        out.append(f"{url}: heading {h!r} over an empty rail")
    out += [f"{url}: {p}" for p in tile_problems(text)]
    return out


class DegradedMatrix(unittest.TestCase):
    def sweep(self, member, only=None):
        failures, count = [], 0
        for n, (label, plans) in enumerate(scenarios()):
            if only is not None and n % only[0] != only[1]:
                continue
            adapters = adapters_for(plans)
            cap = derive_hard_cap(adapters)
            with strict_client(adapters) as client:
                for url in routes(n):
                    count += 1
                    failures += [f"[{label}] {p}" for p in problems(client, MEMBERS[member], url, cap)]
        self.assertGreater(count, 100)
        self.assertEqual([], failures[:15], f"{len(failures)} problems in {count} requests")

    def test_a_member_with_every_library(self):
        self.sweep("all")

    def test_a_comics_only_member(self):
        self.sweep("comics", only=(4, 0))      # a quarter of the scenarios: this member has one place, so fewer branches


def get(adapters_plans, url, member="all", **kw):
    client = strict_client(adapters_for(adapters_plans, **kw))
    with client:
        r = client.get(url, headers=MEMBERS[member])
    return r


def sections(**per_service):
    """{service: {section: state}} from `komga={"recent": "ok"}`; absent libraries are fully ok."""
    return {Service(k.replace("_", "-")): v for k, v in per_service.items()}


class AdjacentStates(unittest.TestCase):
    """T-03: neighbouring states the uniform sweep does not isolate, with the exact wording asserted."""

    def only_once(self, text, service, how):
        said = {"unavailable": f"{LABEL[service]} are unavailable right now.",
                "not_linked": f"{LABEL[service]} are not set up for your account yet."}[how]
        self.assertEqual(1, text.count(said), said)

    def test_read_with_komga_ok_and_calibre_unavailable_and_the_reverse(self):
        for down, up in (("calibre-web", "komga"), ("komga", "calibre-web")):
            plan = sections(**{down.replace("-", "_"): {s: "unavailable" for s in OFFERED[Service(down)]}})
            for url in ("/?for=read", "/?for=comics", "/?for=books", "/"):
                with self.subTest(down=down, url=url):
                    r = get(plan, url)
                    self.assertEqual(200, r.status_code)
                    self.only_once(r.text, down, "unavailable")
                    self.assertNotIn(f"{LABEL[up]} are unavailable", r.text)
                    self.assertEqual([], hard_bare(main_of(r.text)))

    def test_recent_ok_but_released_unavailable(self):
        plan = sections(**{s.value.replace("-", "_"): {"released": "unavailable"} for s in SERVICES})
        for url in ("/", "/?for=listen", "/?for=read", "/?for=comics", "/?for=books", "/?rel=books", "/?more=released",
                    "/library?lib=audiobookshelf"):
            with self.subTest(url=url):
                r = get(plan, url)
                self.assertEqual(200, r.status_code)
                self.assertEqual([], hard_bare(main_of(r.text)))
                self.assertIn('id="h-new"', main_of(r.text)) if url == "/" else None

    def test_chips_for_a_library_the_member_does_not_hold(self):
        for url in ("/?rel=books", "/?rel=watch", "/?new=calibre-web", "/?new=jellyfin", "/?for=listen"):
            with self.subTest(url=url):
                r = get({}, url, member="comics")
                self.assertEqual(200, r.status_code)
                text = r.text
                for label in ("Movies and TV", "Audiobooks"):
                    self.assertNotIn(label, text, label)
                self.assertNotIn("Show on Home", text)           # one place: no filter row
                self.assertEqual([], hard_bare(main_of(text)))

    def test_chips_for_a_library_that_is_down(self):
        plan = sections(komga={s: "unavailable" for s in OFFERED[Service.KOMGA]})
        for url in ("/?rel=comics", "/?new=komga", "/?for=comics", "/?for=read"):
            with self.subTest(url=url):
                r = get(plan, url)
                self.assertEqual(200, r.status_code)
                self.only_once(r.text, "komga", "unavailable")
                self.assertEqual([], hard_bare(main_of(r.text)))

    def test_a_library_that_is_not_linked_is_named_once(self):
        from .plan_adapters import PlanAdapter
        adapters = [PlanAdapter(s, linked=(s is not Service.CALIBRE_WEB)) for s in SERVICES]
        with strict_client(adapters) as c:
            for url in ("/", "/?for=books", "/library?lib=calibre-web"):
                with self.subTest(url=url):
                    r = c.get(url, headers=MEMBERS["all"])
                    self.assertEqual(200, r.status_code)
                    self.assertEqual([], hard_bare(main_of(r.text)))
                    self.assertLessEqual(r.text.count(f"{LABEL['calibre-web']} are not set up"), 1)

    def test_more_released_with_nothing_released(self):
        plan = sections(**{s.value.replace("-", "_"): {"released": "empty", "week": "empty"} for s in SERVICES})
        for url in ("/?more=released", "/?more=new", "/?more=released&for=listen", "/?rel=books&more=released"):
            with self.subTest(url=url):
                r = get(plan, url)
                self.assertEqual(200, r.status_code)
                self.assertEqual([], hard_bare(main_of(r.text)))
                self.assertNotIn("Show more", main_of(r.text).split('id="h-released"', 1)[-1].split("</section>")[0]
                                 if 'id="h-released"' in r.text else "")


class BareHeadingsUnderABanner(unittest.TestCase):
    """Two real defects the matrix found (reported, not fixed here: this task changes no application code). A library that
    is unavailable or not set up leaves its section heading standing over nothing, even though the banner explains."""

    @unittest.expectedFailure
    def test_continue_has_a_line_when_komga_has_nothing_in_progress_and_books_are_down(self):
        # DEFECT: viewmodel build_home sets continue_said = None whenever any Continue section is degraded, and the
        # template then prints "Continue" with no card and no line.
        plan = sections(komga={"continue": "empty"}, calibre_web={"continue": "unavailable", "recent": "unavailable"},
                        jellyfin={"continue": "empty"}, audiobookshelf={"continue": "empty"})
        main = main_of(get(plan, "/?for=read").text)
        self.assertEqual([], empty_headings(main))

    @unittest.expectedFailure
    def test_new_to_avrana_has_a_line_when_audiobooks_are_not_set_up(self):
        # DEFECT: Listen with Audiobooks recent/shelves not_linked prints "New to Avrana" with no card and no line.
        plan = sections(audiobookshelf={"continue": "empty", "recent": "not_linked", "shelves": "not_linked"})
        main = main_of(get(plan, "/?for=listen").text)
        self.assertEqual([], empty_headings(main))


if __name__ == "__main__":
    unittest.main()
