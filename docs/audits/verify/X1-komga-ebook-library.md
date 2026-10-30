# X1: independent verification of F-01 (Komga e-book filed under Books for a member with no Books)

- Fix under review: branch `fix/rc2-komga-ebook-library`, commit `c77847a` on `2cb228f`
  (worktree `avrana.wt-rc2-f01`, clean)
- Baseline: `avrana` at `2cb228f` (read-only)
- Verifier: independent agent, 2026-10-29. No files edited, no commit, no ssh, no Docker, no real services.
- **Verdict: REJECT**

## Why it is rejected (blocking)

**B1. `books_held(tiles)` is true for every Comics member, so the fix does nothing in a real deployment.**
`books_held` returns true for a `books` **or `read`** tile. In the real catalogue (`services/avrana-portal/portal.py`),
`/comics` and `/books` are not Home tiles. They are members of the **Read chooser**, and a viewer gets the `read` tile
when they can open any one of its members. `decide("/", groups, cat).context["tiles"]` (what `tiles_for(viewer)`
returns) gives:

| groups | tiles | `books_held` |
|---|---|---|
| avrana-users, avrana-comics | `read, request, help` | **True** |
| avrana-users, avrana-books | `read, request, help` | True |
| avrana-users, avrana-comics, avrana-books | `read, request, help` | True |
| avrana-users, avrana-audiobooks | `listen, request, help` | False |

So a Comics-only member counts as holding Books. The new tests and the original probe build their own tile list
`[("comics", ...), ("request", ...)]`, which the catalogue never produces. That is why they pass while the rendered app
still shows the defect.

**B2. Rendered, the defect is still there and Search and Details got worse for a Comics-only member.**
I ran the dev stack from a scratch copy of the worktree at `c77847a` on 8496/18496-18499. The stock mock Komga has
no EPUB, so the only change to the copy was one synthetic reflowable EPUB ("Synthetic Lantern Novel",
`BOOKNOVL0099`) added to its `tests/fixtures/komga` files. For comparison I ran the baseline with the same fixture on
8596/18596-18599. Identity `comics-a` (avrana-comics only):

| page | baseline 2cb228f | fix c77847a |
|---|---|---|
| `/` | `?rel=books` chip "Books", `?new=calibre-web` tab "Books" | **same** (still there) |
| `/library` | chip `?lib=calibre-web` "Books", shelf heading "Books" | **same** (still there) |
| `/library?lib=calibre-web` | 200 with a Books shelf | **same** (still there) |
| `/search?q=lantern` | the e-book under "Comics" (no "Books") | **now under a "Books" group** (regression) |
| `/title/komga/BOOKNOVL0099` | "Comics" (no "Books") | **`<title>… · Books`, kicker "Books", "Read … in Books", "Opens in Books"** (regression) |
| `/continue`, `/home.json` | no "Books" | no "Books" |

`member-b` (holds both libraries) now agrees on "Books" across Home, Library, Search and Details, which is the
intended half. The comics-only half is not fixed, and a Comics-only member now sees "Books" in two more places than
before.

## Required follow-ups

1. Decide "holds Books" from the member's **groups or libraries**, not from Home tiles. Two ways:
   - `REQUIRED_GROUP[Service.CALIBRE_WEB] in viewer.groups`, or `"books"` in
     `cat.chooser_members(read_chooser, groups)`, passed down from `main.py`; or
   - inside the view: does `view` hold a `calibre-web` section whose state is not `not_permitted`? This needs care,
     because Search and Title get no Home view.

   Apply the same signal to `build_home`'s `has_books` (it uses `BOOK_PLACES`, which includes `/read`, so it has the
   same flaw: the Books release chip is always offered to a Comics member).
2. Rewrite the tests around **catalogue-produced tiles** (or real groups through `decide`), plus at least one
   route-level test through `create_app` with a Comics-only identity. As written, the 10 new tests cannot catch B1.
3. Search: when the member's `calibre-web` group is `empty` or `unavailable` and Komga matched an e-book, the merge
   step appends a **second "Books" group**. Probe output for `member-with-both`:
   `('Books','empty',[],'No matches in Books.')` and then `('Books','ok',['Synth ebook 2'])`. The unavailable case
   reads "The Books library could not be searched right now" next to a Books group with results. Merge into the
   existing group whatever its state (an `ok` group with the items), or drop the empty one.
4. Minor (P3): a member with Watch and Comics but no Books (once B1 is fixed) sees the e-book on New Releases All
   labelled "Comics". The Comics chip filters by kind `("comic",)`, so the e-book disappears when that chip is
   chosen. Add `"ebook"` to the Comics chip's kinds when the member has no Books.
5. Minor wording: for a member with Books, the title page now says "Opens in Books", but the link goes to Komga
   (`read.avrana.net`). Home cards already said "Read … in Books" on baseline, so this is consistent, but "Opens in"
   names a destination. The owner may want the app (or "Comics") there.

## What checked out

- **Probe** (`scratchpad\verify-x1\probe_komga_epub_comics_only.py`, repointed by `AVR_HOME`): baseline FAILED (2/2),
  worktree OK (2/2). This uses the hand-built tile list, so it does not represent production (see B1).
- **New tests against the baseline** (copy of `services/avrana-home` at 2cb228f, plus the new module): the import
  fails as written (`books_held` is missing). With a shim that supplies `books_held` and ignores `books=`, 5/10 fail
  on baseline:
  - new tabs
  - e-book under Comics
  - Library chips
  - Search grouped under Books
  - Title "Books"

  The other 5 pass on baseline. They are regression guards and the helper test. So the tests do detect the
  view-model behaviour, but only with tiles the catalogue never produces.
- **Callers:** every caller of `_sections_by_service` passes the flag (`build_places` :660, `build_home` :999,
  `build_continue_page` :1258, `build_library` :1368). `main.py` passes `books=` to `build_search` (:424) and
  `build_title` (:581).
- **`ItemVM.library`** honours the `_home` mark, so cards, the hero's "in" label and New Releases detail say Comics
  when the flag is false (view-model probe).
- **Unchanged:** `/home.json` returns the raw member view (raw services, no label). The request "Already in" hints use
  the catalogue-id index (Calibre-Web only), so no change. Adapters, security, caching and templates are unchanged
  (the diff touches only `main.py`, `viewmodel.py` and the new test).
- **Search ordering for a member with both:** Calibre results first, then the moved Komga e-books appended. No
  duplicate item within one group. An item that is in both Komga and Calibre-Web (different ids) shows twice, as on
  baseline.
- **Single-library rule:** `tabs = [All] + libs if len(libs) != 1 else libs` already exists ("A member with exactly
  one library has no use for All"). The implementer's caveat is correct.

## Test runs (worktree, one module at a time, `python -B`)

All green on the first run, no flakes seen:

| module | tests | result |
|---|---|---|
| `test_web_komga_comics_only` | 10 | OK |
| `test_web_komga_books` | 5 | OK |
| `test_web_library_k` | 42 | OK |
| `test_web_home` | 21 | OK |
| `test_web_search` | 19 | OK |
| `test_web_title` | 21 | OK |
| `test_web_sections` | 31 | OK |
| `test_web_new_rows` | 9 | OK |
| `test_web_komga` | 14 | OK |
| `test_web_continue` | 5 | OK |
| `test_web_home_shelves` | 27 | OK |
| `test_web_new_for_you` | 11 | OK |
| `test_web_pages_k` | 25 | OK |
| `tests/test_summary` | 12 | OK |
| `tests.test_home_static_export` | 8 | OK |

Green suites do not offset B1. None of them uses catalogue-produced tiles for a Comics-only member with an EPUB.

## Artefacts (scratch, not committed)

All under `C:\Users\cnech\AppData\Local\Temp\claude\C--Users-cnech-Projects\aa646cb8-53b8-47f2-ae01-c8adcaf3826c\scratchpad\verify-x1\`:

- `probe_komga_epub_comics_only.py`
- `probe_edges.py`: search merge, Library `?lib=`, Continue, Title
- `probe_rel.py`: New Releases chips
- `inject_epub.py`: the synthetic EPUB fixture
- `render\out\*.html`: fetched pages, by port, identity and route
- `base\avrana-home`: the baseline copy with the shimmed new tests

Both dev stacks were stopped after use (ports confirmed free).

## Re-verification: commit 2dc2599 (on c77847a), 2026-10-29

**Verdict: ACCEPT.** B1, B2 and follow-ups 1-4 are resolved. Two small notes remain; they are not blocking.

**What changed.** `holds_books(viewer)` in `main.py` is `REQUIRED_GROUP[Service.CALIBRE_WEB] in viewer.groups`.
That is the same predicate the adapters use. `Viewer.groups` is `principal.groups`, and
`MediaAdapter.section/item/search` returns `not_permitted` when `not principal.has_group(self.required_group)`, with
`required_group = REQUIRED_GROUP[self.service]` (`contract.py:551`, `:609` onward). The flag reaches every call site
that works on a real view:

- `build_home` (:739)
- `build_library` (:547)
- `build_continue_page` (:562)
- `build_search` (:424)
- `build_title` (:581)

`build_places` gets it through those callers. Its two other callers (`my_places` and `build_me`) pass an empty view,
so the flag cannot matter there. `books_held` is gone.

**Rendered result.** I ran a scratch copy of the code at 2dc2599 (worktree clean), with the same single synthetic
EPUB added, on 8496/18496-18499. The stack was stopped afterwards and the ports confirmed free.

- `comics-a`: none of these pages contains the word "Books" or the string "calibre-web":
  - `/`, `/?new=komga`, `/?new=calibre-web`, `/?rel=books`
  - `/library`, `/library?lib=calibre-web`, `/library?lib=komga`
  - `/continue`, `/search?q=lantern`
  - `/title/komga/BOOKNOVL0099`, `/home.json`

  `/library?lib=calibre-web` returns **200, not 404**. That is the existing rule: an unknown `?lib=` falls back to
  All, which for this one-library member is a single "Comics" shelf. Nothing names Books, so I accept it. The
  coordinator expected a 404, but that would be a behaviour change outside F-01. Search shows one "Comics" group
  holding the e-book. The title page shows `<title>… · Comics`, kicker "Book · Comics", "Read … in Comics" and
  "Opens in Comics".
- `member-b`: the e-book is under "Books" on Home tabs and chips, Library, and Search (group 4 "Books"). The title
  page shows `<title>… · Books`, kicker "Books", "Read … in Books" and the hint "Opens in Comics" (`TitleVM.opens` is
  the app's library name). `/home.json` is the raw view, unchanged.

**View-model probe** (`scratchpad\verify-x1\probe_v2.py`):

- Search for a member with both libraries:

  | Books group state | result |
  |---|---|
  | `ok` | one Books group (Calibre items, then the moved e-book) |
  | `empty` | one Books group, now `ok`, holding the e-book (the duplicate group is gone) |
  | `unavailable` / `not_linked` | the notice stands and the e-book stays under Comics |
  | no Books group | a Books group is added |

- Search for a Comics-only member: one Comics group.
- New Releases for Watch plus Read without Books: chips are `all, watch, comics`, and the Comics chip holds the
  e-book (follow-up 4 fixed). There is no Books chip.

**Tests.** The rewritten `test_web_komga_comics_only.py` (15 tests) passes. The view-model tests take tiles from
`decide()` on the real catalogue. A mutant copy with `holds_books` forced to `True` fails
`OverHttp.test_a_comics_only_member_never_sees_books_named` (1 of 15), so the HTTP test does catch B1.

Module reruns, one at a time:

| module | tests | result |
|---|---|---|
| `test_web_komga_books` | 5 | OK |
| `test_web_library_k` | 42 | OK after one rerun (see below) |
| `test_web_home` | 21 | OK |
| `test_web_search` | 19 | OK |
| `test_web_title` | 21 | OK |
| `test_web_sections` | 31 | OK |
| `test_web_new_rows` | 9 | OK |
| `test_web_komga` | 14 | OK |
| `test_web_continue` | 5 | OK |
| `test_web_home_shelves` | 27 | OK |
| `test_web_new_for_you` | 11 | OK |
| `test_web_pages_k` | 25 | OK |
| `tests/test_summary` | 12 | OK |
| `tests.test_home_static_export` | 8 | OK |

`test_web_library_k` failed once on the first run:
`HomeFilters.test_listen_has_no_up_next_and_asks_no_one_for_it`. The Listen shelves "Short listens" and "Epic
listens" were missing. It passed when rerun on its own, and it passes on baseline. The shelves are a separate
late-loading section, so this looks like the known timing flake. The failure does not touch Books/Comics code.

**Notes (not blocking)**

- N1. A member in avrana-books whose Calibre-Web account is **not linked** still gets the Books tab and chip, holding
  the Komga e-books (Home and Library), but Search keeps those e-books under Comics next to the "not set up" notice.
  This matches the owner's rule (they do hold the Books group) and is a rare, temporary state. The small
  Home/Search mismatch is acceptable; record it in the ledger.
- N2. For a member with both libraries, the title page says "Read … in Books" and "Opens in Comics" on the same
  page. That is accurate (filed under Books, opens in the Comics app), but it is an owner wording call.
