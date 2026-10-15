import json
import unittest

from avrana_home.aggregate import gather, health_summary
from avrana_home.contract import SectionState, Service
from avrana_home.resilience import CircuitBreaker, FakeClock
from tests.helpers import FakeAdapter, make_principal

ALL_GROUPS = ("avrana-videos", "avrana-audiobooks", "avrana-comics", "avrana-books")
SERVICES = (Service.JELLYFIN, Service.AUDIOBOOKSHELF, Service.KOMGA, Service.CALIBRE_WEB)


class AggregateTests(unittest.TestCase):
    def build(self, modes=None):
        clock = FakeClock()
        modes = modes or {}
        return [FakeAdapter(s, {"member-a": "1", "member-b": "2"}, clock, mode=modes.get(s, "ok"),
                            breaker=CircuitBreaker(clock, threshold=1))
                for s in SERVICES]

    def states(self, result):
        return {(s.service, s.section): s.state for s in result.sections}

    def test_all_ok(self):
        res = gather(make_principal("member-a", ALL_GROUPS), self.build())
        self.assertEqual(len(res.sections), 8)
        self.assertTrue(all(s.state is SectionState.OK for s in res.sections))

    def test_each_adapter_failing_in_turn_leaves_the_rest(self):
        for mode in ("timeout", "boom"):
            for broken in SERVICES:
                res = gather(make_principal("member-a", ALL_GROUPS), self.build({broken: mode}))
                for (svc, _), state in self.states(res).items():
                    expected = SectionState.UNAVAILABLE if svc is broken else SectionState.OK
                    self.assertIs(state, expected, (mode, broken, svc))

    def test_hung_adapter_is_capped_and_others_return(self):
        adapters = self.build({Service.KOMGA: "block"})
        try:
            res = gather(make_principal("member-a", ALL_GROUPS), adapters, hard_cap=0.05)
            st = self.states(res)
            self.assertIs(st[(Service.KOMGA, "continue")], SectionState.UNAVAILABLE)
            self.assertIs(st[(Service.JELLYFIN, "continue")], SectionState.OK)
            self.assertIs(st[(Service.CALIBRE_WEB, "recent")], SectionState.OK)
            self.assertEqual(adapters[2].health().state, "cooling_off")
        finally:
            adapters[2].release.set()

    def test_member_without_group_gets_absence_not_a_hint(self):
        adapters = self.build()
        res = gather(make_principal("member-a", ("avrana-videos",)), adapters)
        view = res.member_view()
        self.assertEqual({s["service"] for s in view["sections"]}, {"jellyfin"})
        self.assertNotIn("not_permitted", json.dumps(view))
        self.assertEqual([a.calls for a in adapters][1:], [0, 0, 0])

    def test_member_view_json_serialisable_with_unavailable(self):
        res = gather(make_principal("member-a", ALL_GROUPS), self.build({Service.JELLYFIN: "timeout"}))
        view = json.loads(json.dumps(res.member_view()))
        states = {(s["service"], s["section"]): s["state"] for s in view["sections"]}
        self.assertEqual(states[("jellyfin", "continue")], "unavailable")
        self.assertEqual(states[("komga", "continue")], "ok")

    def test_members_get_their_own_data(self):
        adapters = self.build()
        a = gather(make_principal("member-a", ALL_GROUPS), adapters)
        b = gather(make_principal("member-b", ALL_GROUPS), adapters)
        titles_a = {i.title for s in a.sections for i in s.items}
        titles_b = {i.title for s in b.sections for i in s.items}
        self.assertEqual(titles_a, {"Synthetic Title 1"})
        self.assertEqual(titles_b, {"Synthetic Title 2"})

    def test_raw_string_rejected(self):
        with self.assertRaises(TypeError):
            gather("member-a", self.build())

    def test_health_summary(self):
        adapters = self.build({Service.KOMGA: "timeout"})
        h = health_summary(adapters)
        self.assertEqual(h["libraries"], "ok")
        gather(make_principal("member-a", ALL_GROUPS), adapters)
        h = health_summary(adapters)
        self.assertEqual(h["home"], "ok")
        self.assertEqual(h["libraries"], "degraded")
        rows = {r["service"]: r["state"] for r in h["adapters"]}
        self.assertEqual(rows["komga"], "cooling_off")
        self.assertEqual(rows["jellyfin"], "ok")
        self.assertNotIn("member", json.dumps(h))


if __name__ == "__main__":
    unittest.main()
