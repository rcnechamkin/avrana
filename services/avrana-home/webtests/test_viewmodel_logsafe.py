"""Tier A: the section view-model, progress in words, and the log-redaction helpers."""
import io
import json
import logging
import unittest

from avrana_home.app import logsafe
from avrana_home.app.viewmodel import build_sections, progress_words


def item(**kw):
    base = {"id": "jellyfin:x", "service": "jellyfin", "kind": "movie", "title": "Synthetic Film One",
            "subtitle": None, "series": None, "progress": None, "artwork": None,
            "handoff_url": "https://watch.avrana.net/web/#/details?id=aaaa"}
    base.update(kw)
    return base


def section(state, items=(), section="continue", service="jellyfin"):
    return {"service": service, "section": section, "state": state, "items": list(items)}


class ProgressWordsTests(unittest.TestCase):
    def test_words_not_bare_numbers(self):
        cases = [
            ({"position_seconds": 3024, "duration_seconds": 7200, "percent": 42}, "movie", "1 hour 10 minutes left"),
            ({"position_seconds": 6750, "duration_seconds": 8820, "percent": 76}, "movie", "35 minutes left"),
            ({"position_seconds": 7140, "duration_seconds": 7200}, "movie", "1 minute left"),
            ({"position_seconds": 7190, "duration_seconds": 7200}, "movie", "less than a minute left"),
            ({"position_seconds": 7200, "duration_seconds": 7200}, "movie", "finished"),
            ({"position_seconds": 0, "duration_seconds": 7200}, "movie", "2 hours left"),
            ({"position_seconds": None, "duration_seconds": None, "percent": 42}, "movie", "42 percent watched"),
            ({"position_seconds": None, "duration_seconds": None, "percent": 7}, "audiobook", "7 percent listened"),
            ({"percent": 7}, "ebook", "7 percent read"),
            ({"position_seconds": 3600, "duration_seconds": None, "percent": None}, "movie", "1 hour in"),
            ({"position_seconds": 30, "duration_seconds": None, "percent": None}, "movie", "just started"),
            ({}, "movie", None),
            (None, "movie", None),
        ]
        for progress, kind, want in cases:
            with self.subTest(progress=progress, kind=kind):
                self.assertEqual(want, progress_words(kind, progress))

    def test_hostile_progress_values_are_ignored(self):
        for progress in ({"position_seconds": "9", "duration_seconds": "10"}, {"percent": 500},
                         {"percent": True}, {"position_seconds": -5, "duration_seconds": 100}, "42%", []):
            with self.subTest(progress=progress):
                self.assertIsNone(progress_words("movie", progress))


class SectionStateTests(unittest.TestCase):
    def test_ok_renders_the_list_with_handoff_links(self):
        out = build_sections({"sections": [section("ok", [item(
            progress={"fraction": 0.42, "percent": 42, "position_seconds": 3024, "duration_seconds": 7200},
            subtitle="S1 E3", series="Synthetic Series Alpha", kind="episode")])]})
        self.assertEqual(1, len(out))
        self.assertEqual("Continue watching", out[0].heading)
        it = out[0].items[0]
        self.assertEqual("https://watch.avrana.net/web/#/details?id=aaaa", it.href)
        self.assertEqual("S1 E3 · Synthetic Series Alpha", it.detail)    # episode marker first (Home 2.0)
        self.assertEqual("1 hour 10 minutes left", it.progress)

    def test_empty_is_nothing_and_not_permitted_is_absent(self):
        self.assertEqual((), build_sections({"sections": [section("empty")]}))
        self.assertEqual((), build_sections({"sections": [section("not_permitted")]}))
        self.assertEqual((), build_sections({"sections": []}))
        self.assertEqual((), build_sections({}))

    def test_unavailable_and_not_linked_are_neutral_sentences(self):
        out = build_sections({"sections": [section("unavailable"), section("not_linked", section="recent")]})
        self.assertEqual("Movies and TV are unavailable right now.", out[0].message)
        self.assertEqual("Movies and TV are not set up for your account yet.", out[1].message)
        self.assertEqual((), out[0].items)

    def test_unknown_service_or_state_is_dropped(self):
        self.assertEqual((), build_sections({"sections": [section("ok", [item()], service="mystery")]}))
        self.assertEqual((), build_sections({"sections": [section("weird")]}))

    def test_items_without_a_safe_handoff_are_dropped(self):
        bad = [item(handoff_url="javascript:alert(1)"), item(handoff_url="//evil.example"),
               item(handoff_url=None), item(handoff_url="http://watch.avrana.net/x")]
        self.assertEqual((), build_sections({"sections": [section("ok", bad)]}))

    def test_titles_stay_text_at_this_layer(self):
        out = build_sections({"sections": [section("ok", [item(title="<script>alert(1)</script>")])]})
        self.assertEqual("<script>alert(1)</script>", out[0].items[0].title)     # escaped by the template


class LogSafeTests(unittest.TestCase):
    def capture(self):
        stream = io.StringIO()
        logger = logging.getLogger("avrana_home.test_capture")
        logger.handlers = [h for h in logger.handlers if not getattr(h, "_t", False)]
        handler = logging.StreamHandler(stream)
        handler._t = True
        handler.setFormatter(logsafe.JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        self.addCleanup(logger.removeHandler, handler)
        return logger, stream

    def test_only_allowed_fields(self):
        logger, _ = self.capture()
        with self.assertRaises(ValueError):
            logsafe.log_event(logger, logging.INFO, "x", username="member-a")
        with self.assertRaises(ValueError):
            logsafe.log_event(logger, logging.INFO, "x", title="Synthetic Film One")

    def test_values_that_are_not_identifiers_are_replaced(self):
        logger, stream = self.capture()
        logsafe.log_event(logger, logging.INFO, "request", route="/help/{slug}", method="GET", status=200,
                          duration_ms=1.5, service="jellyfin", error_class="UpstreamTimeout")
        logsafe.log_event(logger, logging.INFO, "request", route="/watch?token=abc def", service="Synthetic Film One",
                          error_class="boom: member-a@example.test", method="get x")
        first, second = [json.loads(l) for l in stream.getvalue().splitlines()]
        self.assertEqual("/help/{slug}", first["route"])
        self.assertEqual(200, first["status"])
        for key in ("route", "service", "error_class", "method"):
            self.assertEqual("invalid", second[key], key)
        self.assertNotIn("member-a", stream.getvalue())
        self.assertNotIn("Synthetic Film", stream.getvalue())

    def test_exceptions_log_the_class_only(self):
        logger, stream = self.capture()
        try:
            raise ValueError("member-a@example.test watched Synthetic Film One")
        except ValueError:
            logger.exception("adapter failed")
        doc = json.loads(stream.getvalue().splitlines()[0])
        self.assertEqual("ValueError", doc["error_class"])
        self.assertNotIn("member-a", stream.getvalue())
        self.assertNotIn("Traceback", stream.getvalue())

    def test_foreign_loggers_message_is_not_passed_through(self):
        rec = logging.LogRecord("some.library", logging.INFO, "f", 1, "GET /watch?user=member-a", None, None)
        self.assertNotIn("member-a", logsafe.JsonFormatter().format(rec))

    def test_uvicorn_access_log_is_silenced(self):
        lg = logging.getLogger("uvicorn.access")
        lg.disabled = False
        logsafe.silence_uvicorn_access()
        self.assertTrue(lg.disabled)
        self.assertFalse(lg.propagate)
        self.assertEqual([], lg.handlers)

    def test_forbidden_values_scanner_reads_args_extra_and_exc_info(self):
        scan = logsafe.ForbiddenValues(["member-a", "Synthetic Film One"])
        try:
            raise RuntimeError("Synthetic Film One")
        except RuntimeError:
            import sys
            exc = sys.exc_info()
        for rec in (logging.LogRecord("x", 20, "f", 1, "m %s", ("member-a",), None),
                    logging.LogRecord("x", 20, "f", 1, "m", None, exc)):
            self.assertTrue(scan.scan(rec))
        rec = logging.LogRecord("x", 20, "f", 1, "m", None, None)
        rec.avrana_fields = {"title": "Synthetic Film One"}
        self.assertEqual(["Synthetic Film One"], scan.scan(rec))
        self.assertEqual([], scan.scan(logging.LogRecord("x", 20, "f", 1, "clean", None, None)))


if __name__ == "__main__":
    unittest.main()
