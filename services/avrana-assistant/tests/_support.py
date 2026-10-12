"""Shared test helpers. Synthetic principals only; no real member data."""
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE))

from avrana_assistant.budget import BudgetConfig, BudgetGuard  # noqa: E402
from avrana_assistant.pipeline import AnswerPipeline  # noqa: E402
from avrana_assistant.provider import FakeProvider  # noqa: E402
from avrana_assistant.retrieval import Corpus  # noqa: E402
from avrana_assistant.datatypes import Principal  # noqa: E402

MANIFEST = SERVICE / "corpus" / "manifest.json"

# Synthetic price table: arbitrary integers, not any provider's prices.
TEST_BUDGET = {
    "prices": {"default": {"input_per_1k_micro": 100, "output_per_1k_micro": 300}},
    "per_request_max_tokens": 4000, "per_request_max_cost_micro": 5000,
    "member_daily_tokens": 40000, "member_daily_cost_micro": 50000, "member_daily_requests": 100,
    "global_daily_tokens": 400000, "global_daily_cost_micro": 500000,
}

ALL_GROUPS = frozenset({"avrana-videos", "avrana-audiobooks", "avrana-comics", "avrana-books",
                        "avrana-requests", "library-contributors"})


def principal(groups=("avrana-videos",), subject="synthetic-member-a"):
    return Principal(subject=subject, groups=frozenset(groups))


def make_pipeline(provider=None, budget=None, corpus=None, **kw):
    corpus = corpus or Corpus.load(MANIFEST)
    provider = provider or FakeProvider("rules")
    budget = budget or BudgetGuard(BudgetConfig.from_mapping(TEST_BUDGET))
    return AnswerPipeline(corpus, provider, budget, **kw)
