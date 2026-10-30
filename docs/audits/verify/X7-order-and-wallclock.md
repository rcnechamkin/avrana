# X7 verification: test order dependence (S-12/T-20) and wall-clock N6 (T-22)

Change: branch `test/rc2-order-and-wallclock`, commit 8d81dc0 on 2cb228f
(`services/avrana-home/tests/test_hung.py` +12, `services/avrana-home/tests/test_phase1.py` +30/-4).
Verifier: an independent agent. No files in either checkout were edited, and nothing was committed or pushed.
Interpreter: `.venv-media` Python, `-B`, Windows. Scratch runners are in
`C:\Users\cnech\AppData\Local\Temp\claude\C--Users-cnech-Projects\aa646cb8-53b8-47f2-ae01-c8adcaf3826c\scratchpad\verify-x7\`.

## Verdict: ACCEPT

Both defects are fixed. The bounds are unchanged (4 and 8, and 16 statements in place of the timer).
Under injected regressions, the new tests are strictly stronger than the baseline tests.

## 1. S-12/T-20 test_hung order dependence

| Run | Result |
|---|---|
| Baseline 2cb228f, test_hung alone | FAILED 2/4: `12 not <= 4`, `32 not <= 8` (reproduced) |
| Baseline, test_hung then test_aggregate (one process) | 13 run, 2 fail |
| Worktree, test_hung alone, twice | 4/0, 4/0 |
| Worktree, test_aggregate then test_hung (one process, `order.py`) | 13/0 |
| Worktree, test_hung then test_aggregate (one process) | 13/0 |

**Is the test still meaningful? Yes.** `setUpClass` sends `POOL_WORKERS` (48) no-op tasks
through the real `aggregate._shared_pool()` and waits for each one. That brings the pool to its fixed
bound, and the pool never grows past it (`_DaemonPool.submit`, aggregate.py:47-56). After that, any
rise in `threading.active_count()` is a thread outside the pool. The bounds 4 and 8 are unchanged
from baseline.

Leak injection (`leak.py`, which monkeypatches the worktree code in a separate process):
- `bare`: every pooled request also starts a bare hanging `threading.Thread`. Both thread tests fail
  (`12 not <= 4`, `60 not <= 8`).
- `freshpool`: `_shared_pool` returns a new `_DaemonPool` for each gather, a pool-per-call regression.
  Both tests fail (`12 not <= 4`, `60 not <= 8`).
- `none` (no injection): 4/0.

Residual (also present in baseline): raising `POOL_WORKERS` is invisible to the test, because the
pre-fill reads the same constant. That is the pool's own documented bound, not a leak.

## 2. T-22 N6 wall clock replaced by a statement count

**Choke point.** `self._conn.execute` is called only inside `_exec` (cache.py:400-401) and in
`_create` (connection-setup PRAGMAs, schema and view, outside the set/evict path). The module has no
`executemany`, `executescript` or cursor use. Every eviction statement (`_delete_key`, `_purge_expired`,
`_usage`, `_candidates`, `_delete_many`, `_evict_global` GROUP BY, INSERT, BEGIN/COMMIT) goes through
`self._exec`, so the instance-attribute wrapper sees all of them. Caveat: a future edit that calls
`self._conn.execute` directly would undercount silently.

**Measured counts.** These are deterministic, because FakeClock does not move during the tests:
- Test 1: 13 statements on every one of the 300 evicting sets (min = max = 13), 3900 in total (the bound is 4800).
  Each set issues BEGIN, 2 key deletes, owner usage, 2 purges, 2 usages, GROUP BY, 1 candidates query,
  1 chunked DELETE, INSERT and COMMIT.
- Test 2: 12 statements in total for the set that evicts about 300 entries.
- Margin: with the clock advanced 31 s before each set, so the periodic sweep fires, the peak is 15,
  still within 16. The worst structural case is about 22: sweep, plus owner eviction, plus global
  eviction, plus deletes in both schemas. The tests' setups cannot reach it, so the margin is not
  brittle for these tests. A new statement added to every `set` (for example a PRAGMA) would fail them
  and need a deliberate bound change. That is the intended behaviour.

**Quadratic mutations** (`n6.py` / `n6b.py`; the same mutation applied to the new and the baseline tests):

| Mutation | New test (8d81dc0) | Baseline wall-clock test |
|---|---|---|
| none | pass (4.2 s) | pass (6.1 s) |
| `_CHUNK = 1` (one DELETE per victim) | **FAIL** `310 not <= 16` | pass |
| DELETE per victim (rewritten `_delete_many`) | **FAIL** `310 not <= 16` | pass |
| owner eviction re-queries candidates per victim | **FAIL** `310 not <= 16` | pass |
| global eviction re-aggregates and rescans per victim | pass | pass |

The baseline timer caught none of these regressions. The new count catches the three that involve
victims. One gap remains, and baseline shares it: test 1 evicts one entry per set, so a per-victim
rescan inside `_evict_global` adds no statements, and test 2 never takes the global path (owner
eviction frees enough). A test of global eviction with many victims would close this gap. That is a
follow-up and does not block acceptance.

Pure-Python quadratic work (no SQL) is no longer bounded by any timer. Victim counts are about 300,
so such work would not have broken the old 5 s bound either.

**Runs in the worktree:** test_phase1 48/0 three times (12.2 s, 11.0 s, 7.8 s, on a loaded machine),
test_cache 56/0 with 1 skip (1.9 s).

Cosmetic: the method name `test_a_set_near_quota_into_a_full_cache_is_bounded_in_time` still says
"in_time". `import time` is still used elsewhere in the file.

## 3. Content review

`review_git_content.py` supports only `--staged`, which reads the index. Instead of touching this
worktree's index, the script's own `review_blob()` was imported and run on the commit's blobs
(`git ls-tree 8d81dc0` plus `git cat-file`, `blobs.py`):
- `test_hung.py` 100644 955cbc1e70: clean
- `test_phase1.py` 100644 3ff61b067e: clean

`git diff 2cb228f..8d81dc0 | grep -i -E "token|secret|password|key="` found no matches. The diff
contains no CR characters. The worktree status is clean.
