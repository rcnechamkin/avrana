import datetime as dt
import unittest

import _support  # noqa: F401  (sets sys.path)
from avrana_assistant import egress
from avrana_assistant.budget import BudgetConfig, BudgetDenied, BudgetGuard, ConfigError
from avrana_assistant.datatypes import CompletionRequest, Message
from avrana_assistant.provider import FakeProvider
from _support import TEST_BUDGET, make_pipeline, principal


def cfg(**over):
    d = dict(TEST_BUDGET)
    d.update(over)
    return BudgetConfig.from_mapping(d)


class Clock:
    def __init__(self):
        self.now = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc)

    def __call__(self):
        return self.now


class BudgetTests(unittest.TestCase):
    def test_budget_fail_closed_missing_config(self):
        with self.assertRaises(BudgetDenied) as cm:
            BudgetGuard(None).reserve("m", "default", 10, 10)
        self.assertEqual(cm.exception.reason, "budget_not_configured")

    def test_budget_config_must_be_complete(self):
        for key in list(TEST_BUDGET):
            d = dict(TEST_BUDGET)
            del d[key]
            with self.assertRaises(ConfigError, msg=key):
                BudgetConfig.from_mapping(d)
        with self.assertRaises(ConfigError):
            BudgetConfig.from_mapping({**TEST_BUDGET, "member_daily_tokens": 0})
        with self.assertRaises(ConfigError):
            BudgetConfig.from_mapping({**TEST_BUDGET, "prices": {}})

    def test_budget_unknown_model_label_denied(self):
        with self.assertRaises(BudgetDenied) as cm:
            BudgetGuard(cfg()).reserve("m", "unpriced", 10, 10)
        self.assertEqual(cm.exception.reason, "no_price_for_model_label")

    def test_budget_per_request_ceilings(self):
        g = BudgetGuard(cfg(per_request_max_tokens=100))
        with self.assertRaises(BudgetDenied) as cm:
            g.reserve("m", "default", 90, 20)
        self.assertEqual(cm.exception.reason, "per_request_tokens")
        g = BudgetGuard(cfg(per_request_max_cost_micro=10))
        with self.assertRaises(BudgetDenied) as cm:
            g.reserve("m", "default", 1000, 1000)
        self.assertEqual(cm.exception.reason, "per_request_cost")

    def test_budget_member_daily_and_isolation(self):
        g = BudgetGuard(cfg(member_daily_tokens=300), Clock())
        g.reserve("a", "default", 100, 100)
        with self.assertRaises(BudgetDenied) as cm:
            g.reserve("a", "default", 100, 100)
        self.assertEqual(cm.exception.reason, "member_daily_tokens")
        g.reserve("b", "default", 100, 100)  # another member is unaffected

    def test_budget_global_daily(self):
        g = BudgetGuard(cfg(global_daily_tokens=300), Clock())
        g.reserve("a", "default", 100, 100)
        with self.assertRaises(BudgetDenied) as cm:
            g.reserve("b", "default", 100, 100)
        self.assertEqual(cm.exception.reason, "global_daily_tokens")

    def test_budget_request_count_and_day_rollover(self):
        clock = Clock()
        g = BudgetGuard(cfg(member_daily_requests=2), clock)
        g.reserve("a", "default", 1, 1)
        g.reserve("a", "default", 1, 1)
        with self.assertRaises(BudgetDenied):
            g.reserve("a", "default", 1, 1)
        clock.now += dt.timedelta(days=1)
        g.reserve("a", "default", 1, 1)

    def test_budget_settle_returns_unused_reservation(self):
        g = BudgetGuard(cfg(), Clock())
        r = g.reserve("a", "default", 100, 400)
        g.settle(r, 100, 10)
        self.assertEqual(g.usage("a")["member"]["tokens"], 110)
        r2 = g.reserve("a", "default", 50, 50)
        g.release(r2)
        self.assertEqual(g.usage("a")["member"]["tokens"], 110)
        self.assertEqual(g.usage("a")["member"]["requests"], 1)

    def test_pipeline_without_budget_never_calls_provider(self):
        prov = FakeProvider("rules")
        pl = make_pipeline(provider=prov, budget=BudgetGuard(None))
        r = pl.answer(principal(), "How do I watch movies on my Roku?")
        self.assertEqual(r.behavior, "escalate-to-human")
        self.assertFalse(r.provider_called)
        self.assertEqual(prov.calls, [])
        self.assertIn("budget:budget_not_configured", r.reasons)


class EgressTests(unittest.TestCase):
    def req(self, *messages, system="You are a help assistant."):
        return CompletionRequest(system, tuple(messages), 100)

    def test_allows_public_help_and_member_general(self):
        r = self.req(Message("user", "<passage id=\"a\">Hello</passage>", origin="retrieved", data_class="public-help"),
                     Message("user", "<passage id=\"b\">Hello</passage>", origin="retrieved", data_class="member-general"))
        out, report = egress.prepare(r)
        self.assertEqual(len(out.messages), 2)

    def test_egress_blocks_member_personal_class(self):
        r = self.req(Message("user", "groups: avrana-comics", origin="retrieved", data_class="member-personal"))
        with self.assertRaises(egress.EgressBlocked):
            egress.prepare(r)

    def test_blocks_operator_and_secret_classes(self):
        for cls in ("operator-internal", "secret", "unknown-class"):
            with self.assertRaises(egress.EgressBlocked, msg=cls):
                egress.prepare(self.req(Message("tool", "x", origin="tool", data_class=cls)))

    def test_blocks_operator_marker_in_retrieved_text(self):
        r = self.req(Message("user", "see /" + "home/x/app", origin="retrieved", data_class="member-general"))
        with self.assertRaises(egress.EgressBlocked):
            egress.prepare(r)

    def test_blocks_operator_marker_in_system_text(self):
        with self.assertRaises(egress.EgressBlocked):
            egress.prepare(self.req(system="run docker " + "compose up"))

    def test_egress_blocks_secret_shape(self):
        secret = "sk-" + "ab" * 15
        r = self.req(Message("user", f"my key is {secret} and mail me@example.org", origin="user"))
        out, report = egress.prepare(r)
        self.assertNotIn(secret, out.messages[0].content)
        self.assertNotIn("me@example.org", out.messages[0].content)
        self.assertIn("provider_key_shape", report.redactions)

    def test_provider_not_called_on_block(self):
        prov = FakeProvider("rules")
        pl = make_pipeline(provider=prov)
        # A passage that carries an operator marker must never reach the provider.
        from avrana_assistant.retrieval import Corpus, Doc
        bad = Doc("bad-doc", "Roku help", "Roku " + "setup: open /" + "mnt/media/roku to configure Roku.",
                  {"kind": "public"}, "public-help", "synthetic-fixture")
        pl2 = make_pipeline(provider=prov, corpus=Corpus([bad]))
        r = pl2.answer(principal(), "How do I set up Roku?")
        self.assertFalse(r.provider_called)
        self.assertEqual(prov.calls, [])
        self.assertIn("bad-doc", r.quarantined_ids)
        del pl


if __name__ == "__main__":
    unittest.main()
