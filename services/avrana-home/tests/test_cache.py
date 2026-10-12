"""The disposable SQLite cache, exercised against ':memory:' and against a temporary file database."""
import os as _os
import sys as _sys

_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from tests import _netguard  # noqa: E402,F401  (installs the network guard, also when run directly)
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest

from avrana_home.cache import (KNOWN_CLASSES, SCHEMA_VERSION, DisposableCache, MemberCache,
                               SharedCache)
from avrana_home.contract import (ArtworkRef, ArtworkResult, Kind, MediaItem, SectionResult,
                                  SectionState, Service, UpstreamUser)
from avrana_home.resilience import FakeClock
from tests.helpers import make_principal


class Cases:
    """Every cache attack case, run once per backend. Subclasses set `use_file`."""
    use_file = False

    def setUp(self):
        self.clock = FakeClock()
        self.tmp = tempfile.mkdtemp(prefix="avrana-cache-test-")
        self.path = os.path.join(self.tmp, "cache.sqlite") if self.use_file else None
        self.made = []
        self.cache = self.make()

    def tearDown(self):
        for c in self.made:
            c.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, **kw):
        kw.setdefault("path", self.path)
        c = MemberCache(self.clock, **kw)
        self.made.append(c)
        return c

    # ---- isolation, TTL, bounds (the earlier attack cases) ----
    def test_members_never_share_entries(self):
        a, b = make_principal("member-a"), make_principal("member-b")
        self.cache.for_member(a).set("jellyfin", "continue", "A-DATA", ttl=30)
        self.assertEqual(self.cache.for_member(a).get("jellyfin", "continue"), "A-DATA")
        self.assertIsNone(self.cache.for_member(b).get("jellyfin", "continue"))

    def test_username_variants_are_different_members(self):
        self.cache.for_member(make_principal("member-a")).set("jellyfin", "continue", "A-DATA", 30)
        for variant in ("Member-A", "member-ax", "member_a", "member a"):
            self.assertIsNone(self.cache.for_member(make_principal(variant)).get("jellyfin", "continue"))

    def test_key_parts_cannot_collide(self):
        s = self.cache.for_member(make_principal("member-a"))
        s.set("jellyfin", "x:y", "one", 30)
        s.set("jellyfin:x", "y", "two", 30)
        self.assertEqual(s.get("jellyfin", "x:y"), "one")
        self.assertEqual(s.get("jellyfin:x", "y"), "two")
        m = self.cache.for_member(make_principal("member-a:jellyfin"))
        self.assertIsNone(m.get("x", "y"))

    def test_raw_string_and_impostors_rejected(self):
        with self.assertRaises(TypeError):
            self.cache.for_member("member-a")
        with self.assertRaises(TypeError):
            self.cache.for_member(object.__new__(type(make_principal())))

    def test_ttl_boundary_exact(self):
        s = self.cache.for_member(make_principal("member-a"))
        s.set("jellyfin", "continue", "v", ttl=30)
        self.clock.advance(29.9)
        self.assertEqual(s.get("jellyfin", "continue"), "v")
        self.clock.advance(0.1)                       # now == expiry: expired
        self.assertIsNone(s.get("jellyfin", "continue"))
        self.assertEqual(len(self.cache), 0)

    def test_zero_and_negative_ttl_not_stored(self):
        s = self.cache.for_member(make_principal("member-a"))
        s.set("jellyfin", "x", "v", ttl=0)
        s.set("jellyfin", "y", "v", ttl=-5)
        self.assertEqual(len(self.cache), 0)

    def test_entry_bound(self):
        small = self.make(max_entries=3) if not self.use_file else self.make(max_entries=3, path=self.path + "2")
        s = small.for_member(make_principal("member-a"))
        for i in range(10):
            s.set("jellyfin", f"k{i}", i, ttl=10 + i)
        self.assertLessEqual(len(small), 3)

    def test_global_byte_bound(self):
        small = self.make(max_bytes=1000, member_max_bytes=1000, member_max_entries=100,
                          path=(self.path + "g") if self.use_file else None)
        for name in ("member-a", "member-b", "member-c"):
            s = small.for_member(make_principal(name))
            for i in range(3):
                s.set("jellyfin", f"k{i}", i, ttl=100, size=300)
        self.assertLessEqual(small.total_bytes(), 1000)
        self.assertLessEqual(len(small), 3)

    def test_per_member_byte_quota_leaves_others_alone(self):
        c = self.make(max_bytes=10_000, member_max_bytes=1000, member_max_entries=100,
                      path=(self.path + "q") if self.use_file else None)
        b = c.for_member(make_principal("member-b"))
        b.set("jellyfin", "mine", "B", ttl=100, size=300)
        a = c.for_member(make_principal("member-a"))
        for i in range(20):
            a.set("jellyfin", f"k{i}", i, ttl=100, size=300)
        self.assertEqual(b.get("jellyfin", "mine"), "B")
        self.assertLessEqual(sum(1 for i in range(20) if a.get("jellyfin", f"k{i}") is not None), 3)

    def test_oversize_entry_boundary(self):
        c = self.make(member_max_bytes=1000, path=(self.path + "o") if self.use_file else None)
        s = c.for_member(make_principal("member-a"))
        s.set("jellyfin", "exact", "v", ttl=100, size=1000)
        s.set("jellyfin", "over", "v", ttl=100, size=1001)
        self.assertEqual(s.get("jellyfin", "exact"), "v")
        self.assertIsNone(s.get("jellyfin", "over"))

    def test_one_member_cannot_evict_everyone_else(self):
        cache = self.make(max_entries=40, member_max_entries=10, path=(self.path + "f") if self.use_file else None)
        a, b = cache.for_member(make_principal("member-a")), cache.for_member(make_principal("member-b"))
        for i in range(5):
            b.set("jellyfin", f"k{i}", i, ttl=100)
        for i in range(500):
            a.set("jellyfin", f"flood{i}", i, ttl=100)
        self.assertEqual([b.get("jellyfin", f"k{i}") for i in range(5)], [0, 1, 2, 3, 4])
        self.assertLessEqual(sum(1 for i in range(500) if a.get("jellyfin", f"flood{i}") is not None), 10)

    def test_global_pressure_evicts_the_heaviest_member_first(self):
        cache = self.make(max_entries=12, member_max_entries=10, path=(self.path + "h") if self.use_file else None)
        a, b = cache.for_member(make_principal("member-a")), cache.for_member(make_principal("member-b"))
        for i in range(3):
            b.set("jellyfin", f"k{i}", i, ttl=100)
        for i in range(10):
            a.set("jellyfin", f"f{i}", i, ttl=100)
        c = cache.for_member(make_principal("member-c"))
        for i in range(3):
            c.set("jellyfin", f"k{i}", i, ttl=100)
        self.assertEqual([b.get("jellyfin", f"k{i}") for i in range(3)], [0, 1, 2])
        self.assertEqual([c.get("jellyfin", f"k{i}") for i in range(3)], [0, 1, 2])
        self.assertLessEqual(len(cache), 12)

    def test_group_loss_is_not_the_cache_job_but_delete_and_purge_are_member_scoped(self):
        a, b = (self.cache.for_member(make_principal(n)) for n in ("member-a", "member-b"))
        a.set("jellyfin", "mapping", 1, 60, data_class="member_mapping")
        b.set("jellyfin", "mapping", 2, 60, data_class="member_mapping")
        a.set("jellyfin", "x", 3, 60)
        a.delete("jellyfin", "mapping")
        self.assertIsNone(a.get("jellyfin", "mapping"))
        self.assertEqual(b.get("jellyfin", "mapping"), 2)
        self.assertEqual(self.cache.purge_member(make_principal("member-a")), 1)
        self.assertIsNone(a.get("jellyfin", "x"))
        self.assertEqual(b.get("jellyfin", "mapping"), 2)
        self.assertEqual(self.cache.purge_member(make_principal("member-a")), 0)

    def test_clear_is_only_a_speed_cost(self):
        s = self.cache.for_member(make_principal("member-a"))
        s.set("jellyfin", "x", "v", 30)
        self.cache.clear()
        self.assertIsNone(s.get("jellyfin", "x"))
        s.set("jellyfin", "x", "w", 30)
        self.assertEqual(s.get("jellyfin", "x"), "w")

    def test_shared_cache_is_a_separate_namespace(self):
        shared = SharedCache(self.clock, path=(self.path + "s") if self.use_file else None)
        self.made.append(shared)
        shared.set("public", "k", "v", 10)
        self.assertEqual(shared.get("public", "k"), "v")
        self.cache.for_member(make_principal("shared")).set("public", "k", "member", 10)
        self.assertEqual(shared.get("public", "k"), "v")
        self.assertIsNone(shared.get("public", "other"))

    # ---- value codec ----
    def test_domain_objects_round_trip_and_unknown_types_are_not_stored(self):
        item = MediaItem(id="jellyfin:x", service=Service.JELLYFIN, kind=Kind.MOVIE, title="Synthetic Film One",
                         handoff_url="https://watch.avrana.net/web/#/details?id=" + "a" * 32,
                         progress_fraction=0.42, position_seconds=3024, duration_seconds=7200,
                         artwork=ArtworkRef("jellyfin/primary/" + "a" * 32, "Poster for Synthetic Film One"))
        s = self.cache.for_member(make_principal("member-a"))
        section = SectionResult.of(Service.JELLYFIN, "continue", (item,))
        s.set("jellyfin", "continue", section, 30)
        self.assertEqual(s.get("jellyfin", "continue"), section)
        art = ArtworkResult(SectionState.OK, "image/png", b"\x89PNG\r\n\x1a\n\x00\xff")
        s.set("jellyfin", "art", art, 30, data_class="artwork")
        self.assertEqual(s.get("jellyfin", "art"), art)
        s.set("jellyfin", "map", ("user", UpstreamUser(Service.JELLYFIN, "a" * 32)), 30, data_class="member_mapping")
        self.assertEqual(s.get("jellyfin", "map"), ("user", UpstreamUser(Service.JELLYFIN, "a" * 32)))
        s.set("jellyfin", "map2", ("ambiguous", None), 30, data_class="member_mapping")
        self.assertEqual(s.get("jellyfin", "map2"), ("ambiguous", None))
        s.set("jellyfin", "weird", object(), 30)             # not cacheable: silently not stored
        self.assertIsNone(s.get("jellyfin", "weird"))

    def test_class_rules(self):
        s = self.cache.for_member(make_principal("member-a"))
        for bad in ("catalogue", "nonsense", None):
            with self.assertRaises(ValueError):
                s.set("jellyfin", "x", 1, 30, data_class=bad)
        shared = SharedCache(self.clock, path=(self.path + "c") if self.use_file else None)
        self.made.append(shared)
        with self.assertRaises(ValueError):
            shared.set("n", "k", 1, 30, data_class="member_progress")
        self.assertEqual(set(KNOWN_CLASSES), {"member_progress", "member_mapping", "catalogue", "artwork"})

    # ---- keys on disk or in memory are not recoverable names ----
    def test_member_keys_are_hmacs_not_usernames_or_item_ids(self):
        s = self.cache.for_member(make_principal("member-secretname"))
        s.set("jellyfin", "item:" + "a" * 32, "Synthetic Title Plain", 30)
        rows = self.cache._conn.execute("SELECT k, owner FROM all_entries").fetchall()
        self.assertEqual(len(rows), 1)
        for col in rows[0]:
            self.assertNotIn("secretname", col)
            self.assertNotIn("a" * 32, col)
            self.assertRegex(col, r"^[0-9a-f]{64}$")

    def test_key_material_differs_between_processes_and_caches(self):
        other = self.make(path=(self.path + "k") if self.use_file else None)
        for c in (self.cache, other):
            c.for_member(make_principal("member-a")).set("jellyfin", "x", 1, 30)
        ka = self.cache._conn.execute("SELECT k, owner FROM all_entries").fetchone()
        kb = other._conn.execute("SELECT k, owner FROM all_entries").fetchone()
        self.assertNotEqual(ka, kb)

    # ---- concurrency and failure ----
    def test_concurrent_members_never_see_each_other_and_never_raise(self):
        errors, seen = [], {}

        def work(n):
            try:
                s = self.cache.for_member(make_principal(f"member-{n}"))
                for i in range(60):
                    s.set("jellyfin", f"k{i % 7}", f"v-{n}-{i % 7}", 100)
                    got = s.get("jellyfin", f"k{i % 7}")
                    if got is not None and not got.startswith(f"v-{n}-"):
                        errors.append((n, got))
                seen[n] = True
            except Exception as exc:                       # pragma: no cover
                errors.append(repr(exc))
        threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(20)
        self.assertEqual(errors, [])
        self.assertEqual(len(seen), 8)

    def test_a_sqlite_error_is_a_miss_and_the_cache_rebuilds(self):
        s = self.cache.for_member(make_principal("member-a"))
        s.set("jellyfin", "x", "v", 100)
        original = self.cache._exec
        state = {"n": 0}

        def flaky(*a, **k):
            if state["n"] < 1:
                state["n"] += 1
                raise sqlite3.DatabaseError("database disk image is malformed")
            return original(*a, **k)
        self.cache._exec = flaky
        self.assertIsNone(s.get("jellyfin", "x"))              # a miss, not an exception
        self.cache._exec = original
        s.set("jellyfin", "y", "w", 100)                       # rebuilt and usable
        self.assertEqual(s.get("jellyfin", "y"), "w")
        self.assertIsNone(s.get("jellyfin", "x"))              # the old content is gone

    def test_set_and_delete_survive_errors_too(self):
        s = self.cache.for_member(make_principal("member-a"))

        def always(*a, **k):
            raise sqlite3.OperationalError("disk I/O error")
        original = self.cache._exec
        self.cache._exec = always
        s.set("jellyfin", "x", "v", 100)
        s.delete("jellyfin", "x")
        self.assertEqual(self.cache.purge_member(make_principal("member-a")), 0)
        self.assertEqual(len(self.cache), 0)
        self.assertEqual(self.cache.total_bytes(), 0)
        self.cache.clear()
        self.cache._exec = original

    def test_closed_cache_is_all_misses(self):
        s = self.cache.for_member(make_principal("member-a"))
        s.set("jellyfin", "x", "v", 100)
        self.cache.close()
        self.assertIsNone(s.get("jellyfin", "x"))
        s.set("jellyfin", "x", "v", 100)
        self.assertEqual(len(self.cache), 0)


class MemoryCacheTests(Cases, unittest.TestCase):
    use_file = False

    def test_default_is_memory_only(self):
        self.assertIsNone(self.cache.path)
        self.assertEqual(self.cache._conn.execute("PRAGMA database_list").fetchall()[0][2], "")


class FileCacheTests(Cases, unittest.TestCase):
    use_file = True

    def ro(self, path=None):
        uri = "file:" + (path or self.path).replace("\\", "/") + "?mode=ro"
        return sqlite3.connect(uri, uri=True)

    def test_member_classes_never_reach_the_file_by_default(self):
        s = self.cache.for_member(make_principal("member-a"))
        s.set("jellyfin", "continue", "WATCH-STATE", 100, data_class="member_progress")
        s.set("jellyfin", "mapping", ("absent", "unmapped"), 100, data_class="member_mapping")
        s.set("jellyfin", "art", ArtworkResult(SectionState.OK, "image/png", b"\x89PNG\r\n\x1a\nxx"), 100,
              data_class="artwork")
        self.assertEqual(len(self.cache), 3)                    # they are in the cache ...
        con = self.ro()
        try:
            self.assertEqual(con.execute("SELECT count(*) FROM entries").fetchone()[0], 0)   # ... not on disk
        finally:
            con.close()
        with open(self.path, "rb") as fh:
            blob = fh.read()
        for needle in (b"WATCH-STATE", b"member-a", b"unmapped"):
            self.assertNotIn(needle, blob)

    def test_catalogue_class_does_reach_the_file(self):
        shared = SharedCache(self.clock, path=self.path + "cat")
        self.made.append(shared)
        shared.set("public", "k", "CATALOGUE-VALUE", 100)
        con = self.ro(self.path + "cat")
        try:
            self.assertEqual(con.execute("SELECT count(*) FROM entries").fetchone()[0], 1)
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        finally:
            con.close()

    def test_owner_can_widen_persist_classes_keys_stay_hashed_values_are_plaintext(self):
        wide = self.make(path=self.path + "wide", persist_classes=frozenset({"catalogue", "artwork"}))
        s = wide.for_member(make_principal("member-secretname"))
        s.set("jellyfin", "art:" + "b" * 32, ArtworkResult(SectionState.OK, "image/png", b"\x89PNG\r\n\x1a\nxx"),
              100, data_class="artwork")
        s.set("jellyfin", "continue", "MEMBER-TITLE-PLAIN", 100)           # still not persisted
        con = self.ro(self.path + "wide")
        try:
            rows = con.execute("SELECT k, owner, value FROM entries").fetchall()
        finally:
            con.close()
        self.assertEqual(len(rows), 1)
        with open(self.path + "wide", "rb") as fh:
            blob = fh.read()
        self.assertNotIn(b"secretname", blob)               # no username as key material
        self.assertNotIn(b"b" * 32, blob.replace(b"synthetic", b""))   # no item id as key material
        self.assertNotIn(b"MEMBER-TITLE-PLAIN", blob)
        self.assertIn(b"image/png", blob)                    # VALUES are plaintext: stated, not hidden

    def test_file_is_deleted_and_recreated_at_start(self):
        shared = SharedCache(self.clock, path=self.path + "re")
        shared.set("public", "k", "OLD", 100)
        shared.close()
        again = SharedCache(self.clock, path=self.path + "re")
        self.made.append(again)
        self.assertIsNone(again.get("public", "k"))
        with open(self.path + "re", "rb") as fh:
            self.assertNotIn(b"OLD", fh.read())

    def test_corrupt_or_foreign_file_is_replaced_at_start(self):
        with open(self.path + "bad", "wb") as fh:
            fh.write(b"this is not a sqlite database" * 100)
        c = SharedCache(self.clock, path=self.path + "bad")
        self.made.append(c)
        c.set("public", "k", "v", 100)
        self.assertEqual(c.get("public", "k"), "v")
        con = self.ro(self.path + "bad")
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
        finally:
            con.close()

    def test_secure_delete_and_no_sidecar_files(self):
        self.assertEqual(self.cache._conn.execute("PRAGMA secure_delete").fetchone()[0], 1)
        shared = SharedCache(self.clock, path=self.path + "sd")
        self.made.append(shared)
        shared.set("public", "k", "SECRET-CATALOGUE-TEXT" * 20, 100)
        shared.clear()
        with open(self.path + "sd", "rb") as fh:
            self.assertNotIn(b"SECRET-CATALOGUE-TEXT", fh.read())      # deleted pages are zeroed
        self.assertEqual([f for f in os.listdir(self.tmp) if f.endswith(("-wal", "-shm", "-journal"))], [])

    def test_file_permissions_are_0600_where_supported(self):
        if os.name == "nt":
            msg = "SKIPPED: POSIX file modes are not enforced on Windows; this check runs on Linux/CI"
            print(msg)
            self.skipTest(msg)
        mode = os.stat(self.path).st_mode & 0o777
        print(f"permissions check ran on {os.name}: mode={oct(mode)}")
        self.assertEqual(mode, 0o600)

    def test_unusable_path_degrades_to_memory_not_an_exception(self):
        c = SharedCache(self.clock, path=os.path.join(self.tmp, "no-such-dir", "x.sqlite"))
        self.made.append(c)
        c.set("public", "k", "v", 100)
        self.assertEqual(c.get("public", "k"), "v")


class Facades(unittest.TestCase):
    def test_one_engine_class(self):
        self.assertTrue(issubclass(MemberCache, DisposableCache))
        self.assertTrue(issubclass(SharedCache, DisposableCache))
        import avrana_home.cache as mod
        self.assertFalse(hasattr(mod, "_TTLStore"))           # the old dict implementation is gone


if __name__ == "__main__":
    unittest.main()
