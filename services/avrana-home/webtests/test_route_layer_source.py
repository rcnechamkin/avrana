"""Tier A: a source-level guard on the route layer.

No module of the application may read an identity, a user id, a username or a group from the
query string, path parameters, a body, a form, a cookie or any header, except `identity.py`,
which reads exactly the four trusted headers from the raw ASGI scope and hands them to the
principal parser. The one other request input the route layer uses is the path text itself
(`scope["raw_path"]`), only to choose a page; `routing.decide` takes the path and the viewer's
groups and nothing else.
"""
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "avrana_home" / "app"

FORBIDDEN = [r"query_params", r"query_string", r"\.cookies", r"path_params",
             r"\.form\(", r"\.json\(", r"\.body\(", r"\.stream\(",
             r"from fastapi import[^\n]*\b(Path|Query|Cookie|Header|Form|Body|File|UploadFile)\b",
             r"request\.headers", r"\.headers\.get", r"\.headers\[", r"scope\[.headers.\]",
             r"scope\.get\(.headers.", r"\.url\b", r"\.base_url"]
IDENTITY_ONLY = {"identity.py"}


def sources():
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(APP.glob("*.py"))}


def code(text):
    """Executable source only: docstrings and comments removed."""
    text = re.sub(r'""".*?"""', "", text, flags=re.S)
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


class RouteLayerTests(unittest.TestCase):
    def test_only_identity_py_reads_request_input(self):
        for name, text in sources().items():
            if name in IDENTITY_ONLY:
                continue
            body = code(text)
            for pattern in FORBIDDEN:
                with self.subTest(module=name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, body), f"{name} reads request input: {pattern}")

    def test_the_only_scope_reads_outside_identity_are_the_path_and_our_own_labels(self):
        allowed = {"raw_path", "path", "avrana_route", "avrana_shell", "type", "method", "headers_unused"}
        for name, text in sources().items():
            if name in IDENTITY_ONLY:
                continue
            for key in re.findall(r"scope(?:\.get|\.setdefault)?[\[(]\s*[\"']([a-z_]+)[\"']", code(text)):
                with self.subTest(module=name, key=key):
                    self.assertIn(key, allowed)

    def test_identity_py_reads_only_trusted_headers_through_the_one_parser(self):
        text = sources()["identity.py"]
        self.assertEqual(1, len(re.findall(r"principal_from_raw_headers\(", code(text))))
        body = code(text)
        self.assertNotIn("query", body.lower().replace("query_string", ""))
        self.assertNotIn("cookie", body.lower())

    def test_principals_are_minted_in_one_place_only(self):
        for name, text in sources().items():
            body = code(text)
            self.assertNotIn("_mint_principal", body, name)
            self.assertNotIn("object.__new__", body, name)
            if name != "identity.py":
                self.assertNotIn("principal_from_headers", body, name)
                self.assertNotIn("principal_or_none", body, name)
                self.assertNotIn("principal_from_raw_headers", body, name)

    def test_routes_never_call_an_adapter_directly(self):
        """Mapping goes through the adapters' own resolve_user, reached only via aggregate.gather."""
        for name, text in sources().items():
            body = code(text)
            for call in (".continue_items(", ".recent_items(", ".resolve_user(", ".fetch_artwork(",
                         ".search(", "._resolve_user("):
                if call == ".fetch_artwork(" and name == "artwork.py":
                    continue                      # the one member-scoped artwork gateway
                self.assertNotIn(call, body, f"{name}: {call}")

    def test_fetch_artwork_is_called_in_one_module_with_the_verified_principal_and_a_checked_ref(self):
        body = code(sources()["artwork.py"])
        self.assertEqual(1, body.count(".fetch_artwork("))
        self.assertIn("adapter.fetch_artwork(principal, ref)", body)
        self.assertIn("REF.fullmatch(ref)", body)

    def test_no_redirect_is_built_from_request_input(self):
        main = code(sources()["main.py"])
        self.assertNotIn("RedirectResponse", main)
        self.assertEqual(1, len(re.findall(r'"Location"', main)))
        self.assertIn("decision.location", main)

    def test_no_import_time_side_effects_in_the_package(self):
        for name, text in sources().items():
            if name in ("asgi.py", "serve.py"):          # server entry points, never imported by tests
                continue
            body = code(text)
            for risky in ("os.environ", "os.getenv", "basicConfig(", "uvicorn.run(", "socket.socket("):
                if name == "settings.py" and risky == "os.environ":
                    continue                          # only inside Settings.from_env, called by entry points
                self.assertNotIn(risky, body, f"{name}: {risky}")
            self.assertNotRegex(body, r"(?m)^app\s*=", name)


if __name__ == "__main__":
    unittest.main()
