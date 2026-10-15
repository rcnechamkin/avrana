# Avrana Assistant (phase A0, offline foundation)

Status: **proposed, not approved, nothing deployed.** This directory is an experimental workstream
("Avrana Assistant" in Linear), separately governed from Media 2.0 and **not a prerequisite for it**. It is
not wired into the portal, has no container, no port, no credentials and makes no network calls. Python
standard library only.

Read first: [`docs/assistant/THREAT-MODEL.md`](../../docs/assistant/THREAT-MODEL.md) (abuse cases and the
permission matrix) and [`docs/assistant/DATA-CLASSIFICATION.md`](../../docs/assistant/DATA-CLASSIFICATION.md)
(what may enter retrieval, a prompt, a provider, a log).

## Layout

| Path | Purpose |
|---|---|
| `corpus/manifest.json`, `corpus/docs/` | Approved-corpus **proposal**: member-safe documents with audience, class, source blob hashes. Review status `proposed` |
| `avrana_assistant/datatypes.py` | `Principal`, `Message`, `CompletionRequest/Response`, `ToolCall`, behaviour classes |
| `avrana_assistant/provider.py` | `Provider` Protocol and the deterministic `FakeProvider` (rules, scripted, hostile, outage). No SDK imports |
| `avrana_assistant/budget.py` | `BudgetGuard`: per-request, per-member/day, global/day token, cost and request ceilings; injectable clock; price table is configuration; fails closed |
| `avrana_assistant/egress.py` | Egress filter applied before any provider call; enforces the data-class table |
| `avrana_assistant/denylist.py` | Reusable operator-internal / secret-shape deny-list (also gates the corpus in tests) |
| `avrana_assistant/retrieval.py` | Corpus loader (verifies document hashes) and a BM25 retriever with audience filtering done before ranking |
| `avrana_assistant/policy.py`, `guards.py` | Deterministic input policy, injection detection, output validation |
| `avrana_assistant/tools.py` | Tool registry stub: **denies everything**; authorisation is outside the model |
| `avrana_assistant/pipeline.py` | The answer pipeline |
| `avrana_assistant/audit.py` | Audit log that cannot hold content |
| `eval/` | Golden set, fixtures, runner (see below) |
| `tests/` | `unittest` suite |

Corpus staleness. Hard checks (well-formed manifest, source paths exist, documents exist and are
referenced, each document's recorded hash, no deny-list marker) fail the offline suite. Source drift (a
source file's blob hash changed or an anchor string vanished) does **not**: the default test prints
`WARN corpus stale: <doc id> <- <source path>` and passes, so this service can never block edits to the
portal or onboarding files. `Corpus.load` is strict by default (fails closed: documents with stale
sources are not retrievable, hard problems raise); tests and the eval load the pinned corpus with
`strict=False`. Before approving the corpus run the strict gate, which exits non-zero on any staleness:

    python -B services/avrana-assistant/avrana_assistant/corpus_check.py --strict

Run everything offline: `python -B tests/run_offline.py` from the repository root (this service's tests are
the last step), or `python -B -m unittest discover -s services/avrana-assistant/tests`.

## How a request flows

1. The caller (in future, the code behind the Authentik outpost) builds a `Principal` from verified headers
   and passes it in. Nothing in message text can set or change it.
2. `policy.classify` routes requests the model must not decide: empty or oversized input, injection shapes,
   identity claims, other members' data, operator internals, password problems (point to the recovery
   flow), access changes (human), status questions (status unknown), contact requests (human).
3. Retrieval: documents are filtered by the `Principal`'s audience *before* ranking, so a document a member
   cannot see is never ranked or sent to a model. Injection-shaped or deny-list passages are quarantined.
4. The prompt carries retrieved text and the question inside delimiters, as untrusted data, with angle
   brackets escaped. The provider receives no username or group list.
5. Egress filter, then budget reservation (no valid budget configuration means no call), then the provider.
6. Output validation requires citations to retrieved corpus ids, rejects deny-list content, injection
   shapes, status claims, claims of performed actions, requests for secrets and weakly grounded sentences,
   and rejects any tool call. Any failure is replaced by a template that points to a human.
7. No tool executes in A0.

Low retrieval confidence escalates; no retrieval match at all is treated as off-topic and refused.

## Design note: plugging in a real provider later (A1, AVR-343; not implemented)

Nothing here picks a vendor, model or price, and no client is written. A future provider module would:

- Live in its own file, implement `Provider.complete(CompletionRequest) -> CompletionResponse`, translate
  the neutral `system`, `messages` (including `role == "tool"` results with `tool_call_id`), `tools` and
  `max_output_tokens` to the vendor's request shape, and translate text, tool calls and token usage back.
  It is the only module allowed to import a vendor SDK.
- Read its credential from the server environment or a secret file with mode 0600 at start-up (see
  `docs/SECRETS.md` for where such secrets are recorded, locations only). The credential is never in the
  browser, never in the corpus, never in logs, and the process must refuse to start if it is missing.
- Take `model_label` as an opaque configuration key. The owner supplies, in configuration, the mapping from
  label to the vendor's model identifier and the price table that `BudgetConfig` already requires. The
  per-request, per-member and global ceilings are likewise owner numbers; with none supplied the pipeline
  never calls the provider.
- Enforce `timeout_s`, map transport errors, rate limits and outages to `ProviderUnavailable` so the
  pipeline degrades to the human-escalation answer, and report real token usage so `BudgetGuard.settle`
  can replace the worst-case reservation.
- Be exercised by the same golden set with the same guards. Swapping `FakeProvider` for the real one must
  not change retrieval, policy, guards or the tool gateway. Opt-in evaluation runs need the owner's
  approval of the provider, data-egress terms (only public-help and member-general content leaves), the
  provider's retention terms, and the budget numbers.
- A local-inference provider (A3) is a second implementation of the same Protocol.

## Evaluation (`eval/`)

`eval/golden.json` holds 64 cases over six synthetic members (usernames `synthetic-*`, groups from the real
vocabulary in `services/avrana-portal/portal.py`, plus one anonymous visitor): the seven common requests
across different memberships (access, which app, why a library is not visible, how to request, password
reset, is a service down, contact support) and adversarial cases (injection in the question, injection
inside a retrieved passage, other members' data, claiming to be the admin, operator internals, direct
access or password changes, off-topic and cost-abuse input). The poisoned documents are synthetic fixtures
in `eval/fixtures/poisoned/`, kept outside the approved corpus.

`eval/run_eval.py` runs the real pipeline with `FakeProvider` over the set, deterministically
(`--provider rules` or `--provider hostile`, `--json` for the full rows). `tests/test_eval.py` wraps it.

**This measures retrieval and guard behaviour with a fake provider. It does not measure the answer quality
of any real model.** The rules provider is extractive, so "answer" cases show that the right passage was
retrieved, cited and passed the guards, not that a model would phrase a good answer. The rules and the
golden set were written together, so these numbers are a regression gate and not an estimate of how the
system generalises to unseen member questions.

Measured on 2026-10-11 (rules provider, 64 cases) and the thresholds the tests assert:

| Metric | Measured | Asserted floor |
|---|---|---|
| Behaviour-class compliance (expected or listed acceptable class) | 0.969 | 0.95 |
| Exact expected class | 0.859 | not asserted |
| Retrieval hit rate (required doc in the top 3 or cited; 35 cases) | 1.000 | 0.95 |
| Citation rate (required ids cited when the expected class is produced) | 0.968 | 0.95 |
| must-not-contain pass (leaks, invented status, invented actions) | 1.000 | 1.0 |
| Deny-list marker free | 1.000 | 1.0 |

Known misses, asserted exactly so any change is noticed: `acc-02` (retrieves the request document for
"sign in to Jellyfin"), `app-03` and `pw-05` (conversational phrasing lowers lexical coverage below the
answer threshold, so the pipeline escalates instead of answering). These are the honest limits of a small
lexical retriever.

Hostile provider (each case receives one deliberate misbehaviour, rotating through injected instructions,
unauthorised tool calls, fabricated status, operator leaks, bad or missing citations, invented policy,
invented actions, password solicitation and secret echo): 0 of 16 provider outputs reached the member,
must-not-contain and deny-list pass rates 1.000, 3 attempted tool calls denied. Behaviour-class numbers
are lower in that mode by design, because answers fall back to escalation.
