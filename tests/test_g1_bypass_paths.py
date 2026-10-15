"""Gate G1 independent review (AVR-345): bypass paths the network checker cannot see.

`tests/test_network_isolation.py` proves the private networks are declared and that the drift guard
reads `docker network inspect` correctly. This file covers routes around that guard, found in the
independent review (`docs/audits/2026-10-14-g1-independent-review.md`):

  * namespace sharing: a container started with `network_mode: container:<x>` / `service:<x>` lives
    inside x's network namespace and never appears in `docker network inspect`, so it would pass
    the drift guard while reaching every network x is on (authentik-server is on all three);
  * DNS impostors: a sibling on a network authentik-server shares that answers to a backend's name
    could receive the outpost's authenticated, header-carrying requests;
  * ingress: the public hostnames must reach the backends only through the outpost (port 9000),
    and authentik-server must not publish 9000 on every interface;
  * proxy provider mode: only `proxy` mode makes the outpost itself the reverse proxy that sets the
    headers; `skip_path_regex` would forward unauthenticated requests without identity;
  * header-name variants: underscore and look-alike names (which some servers fold into the real
    header) and other common identity headers must grant nothing in the portal, the Kindle connector
    or the Media 2.0 principal parser.

Offline: files in this repository and in-process handlers fed parsed headers. No Docker, no
network, no production access. Needs PyYAML for the compose tests (skipped loudly without it).
"""
import email.parser
import email.policy
import http.client
import importlib.util
import io
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parents[1]

# The three header-trusting backends and the one container allowed to reach them.
BACKEND_CONTAINERS = ("avrana-portal", "avrana-kindle-connector", "olivetin")
OUTPOST = "authentik-server"
PROTECTED = (OUTPOST, *BACKEND_CONTAINERS)
PUBLIC_HOSTS = {"avrana.net": "avrana-portal", "kindle.avrana.net": "avrana-kindle-connector",
                "ops.avrana.net": "olivetin"}
BACKEND_PORTS = {"avrana-portal": 8095, "avrana-kindle-connector": 8096, "olivetin": 1337}

ADMIN = "authentik Admins"
BOOKS = "avrana-books"


def compose_files():
    files = sorted((ROOT / "services").glob("*/docker-compose*.yml"))
    files += sorted((ROOT / "deploy").rglob("docker-compose*.yml"))
    return files


def load_compose(path):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def headers_from(pairs):
    """Parse raw header lines exactly as http.server does for a real request."""
    raw = "".join(f"{name}: {value}\r\n" for name, value in pairs) + "\r\n"
    return http.client.parse_headers(io.BytesIO(raw.encode("latin-1")))


# Header names that are NOT the outpost's header but that something along the way might fold into
# it (WSGI/CGI map '-' to '_', some proxies normalise case or trailing characters), plus generic
# identity headers that other software trusts. None may grant anything.
VARIANT_GROUP_HEADERS = [
    "X_authentik_groups", "X-authentik_groups", "X_Authentik_Groups", "HTTP_X_AUTHENTIK_GROUPS",
    "X-authentik-groups-", "X-authentik-group", "X-authentik-groupss", "Authentik-groups",
    "X-Forwarded-Groups", "Remote-Groups", "X-Remote-Groups", "X-authentik-meta-groups",
]
VARIANT_USER_HEADERS = [
    "X_authentik_username", "X-authentik_username", "HTTP_X_AUTHENTIK_USERNAME",
    "X-authentik-user", "X-Forwarded-User", "Remote-User", "X-Remote-User", "X-authentik-uid",
    "X-authentik-meta-username",
]


@unittest.skipIf(yaml is None, "PyYAML missing: G1 bypass-path compose tests NOT RUN")
class NamespaceSharingTests(unittest.TestCase):
    """`docker network inspect` does not list containers that borrow another's network namespace."""

    def test_no_compose_service_borrows_a_container_network_namespace(self):
        offenders = []
        for path in compose_files():
            for name, service in (load_compose(path).get("services") or {}).items():
                mode = str(service.get("network_mode") or "")
                if mode.startswith(("container:", "service:")):
                    offenders.append(f"{path.relative_to(ROOT)}:{name} network_mode={mode}")
        self.assertEqual(offenders, [], "namespace sharing is invisible to check-network-isolation.py")

    def test_no_compose_service_shares_a_protected_pid_or_ipc_namespace(self):
        targets = {f"container:{c}" for c in PROTECTED} | {"service:server"}
        targets |= {f"service:{c}" for c in BACKEND_CONTAINERS}
        offenders = []
        for path in compose_files():
            for name, service in (load_compose(path).get("services") or {}).items():
                for key in ("pid", "ipc"):
                    if str(service.get(key) or "") in targets:
                        offenders.append(f"{path.relative_to(ROOT)}:{name} {key}={service[key]}")
        self.assertEqual(offenders, [])

    def test_checker_is_blind_to_namespace_sharing(self):
        """Pins WHY the static test above exists: a borrower never appears in network data, so the
        runtime guard alone cannot catch it and the runbook carries a separate read-only check."""
        spec = importlib.util.spec_from_file_location("iso_for_bypass", ROOT / "scripts/check-network-isolation.py")
        iso = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(iso)

        def net(name, *members):
            return {"Name": name, "Containers": {f"id-{m}": {"Name": m} for m in members}}

        healthy = [net("authentik_frontend", OUTPOST, "authentik-worker", "authentik-ldap"),
                   net("authentik_portal", OUTPOST, "avrana-portal"),
                   net("authentik_kindle", OUTPOST, "avrana-kindle-connector"),
                   net("authentik_olivetin", OUTPOST, "olivetin")]
        # The same data whether or not a borrower runs inside authentik-server's namespace.
        self.assertEqual([lvl for lvl, _ in iso.evaluate(healthy, applied=True)], ["OK"])
        runbook = (ROOT / "docs/runbooks/g1-network-isolation.md").read_text(encoding="utf-8")
        self.assertTrue("HostConfig.NetworkMode" in runbook, "runbook must check namespace sharing on the host")


@unittest.skipIf(yaml is None, "PyYAML missing: G1 bypass-path compose tests NOT RUN")
class DnsImpostorTests(unittest.TestCase):
    """Only the real backend may answer to its name on any network authentik-server joins."""

    def names_of(self, service_key, service):
        names = {service_key, service.get("container_name"), service.get("hostname")}
        networks = service.get("networks") or {}
        if isinstance(networks, dict):
            for definition in networks.values():
                names.update((definition or {}).get("aliases") or [])
        names.update(service.get("links") or [])
        return {n for n in names if n}

    def test_backend_names_are_claimed_only_by_the_backend(self):
        offenders = []
        for path in compose_files():
            for key, service in (load_compose(path).get("services") or {}).items():
                owner = service.get("container_name")
                for claimed in self.names_of(key, service) & set(BACKEND_CONTAINERS):
                    if claimed != owner:
                        offenders.append(f"{path.relative_to(ROOT)}:{key} answers to {claimed}")
        self.assertEqual(offenders, [], "a second holder of a backend name could receive outpost traffic")

    def test_each_backend_name_has_exactly_one_container(self):
        owners = {}
        for path in compose_files():
            for key, service in (load_compose(path).get("services") or {}).items():
                if service.get("container_name") in BACKEND_CONTAINERS:
                    owners.setdefault(service["container_name"], []).append(f"{path.relative_to(ROOT)}:{key}")
        self.assertEqual(sorted(owners), sorted(BACKEND_CONTAINERS))
        for name, where in owners.items():
            self.assertEqual(len(where), 1, f"{name} declared by {where}")

    def test_backends_declare_no_extra_aliases_or_hostnames(self):
        for path in compose_files():
            for key, service in (load_compose(path).get("services") or {}).items():
                if service.get("container_name") not in BACKEND_CONTAINERS:
                    continue
                self.assertNotIn("hostname", service, key)
                self.assertNotIn("links", service, key)
                self.assertIsInstance(service.get("networks"), list,
                                      f"{key}: list form only, so no alias can be added silently")


@unittest.skipIf(yaml is None, "PyYAML missing: G1 bypass-path compose tests NOT RUN")
class IngressTests(unittest.TestCase):
    def cloudflared(self):
        return yaml.safe_load((ROOT / "deploy/host/cloudflared/config.yml").read_text(encoding="utf-8"))

    def test_public_backend_hostnames_go_through_the_outpost_only(self):
        rules = {r.get("hostname"): r.get("service") for r in self.cloudflared()["ingress"]}
        for host in PUBLIC_HOSTS:
            self.assertEqual(rules.get(host), "http://localhost:9000", f"{host} must route to the outpost")

    def test_no_ingress_rule_reaches_a_backend_directly(self):
        for rule in self.cloudflared()["ingress"]:
            service = str(rule.get("service", ""))
            for container in BACKEND_CONTAINERS:
                self.assertNotIn(container, service, rule)
            if rule.get("hostname") in PUBLIC_HOSTS:
                continue
            # 8096 is also Jellyfin on the host network (watch.avrana.net); that rule is not a backend.
            for container, port in BACKEND_PORTS.items():
                if port == 8096 and rule.get("hostname") == "watch.avrana.net":
                    continue
                self.assertFalse(re.search(rf":{port}\b", service), f"{rule} reaches {container}'s port")

    def test_catch_all_is_404(self):
        self.assertEqual(self.cloudflared()["ingress"][-1], {"service": "http_status:404"})

    def test_outpost_port_is_not_published_on_every_interface(self):
        server = load_compose(ROOT / "services/authentik/docker-compose.yml")["services"]["server"]
        ports = [str(p) for p in server.get("ports", [])]
        self.assertTrue(ports)
        for port in ports:
            self.assertRegex(port, r"^(127\.0\.0\.1|10\.0\.0\.218):9000:9000$", "bind 9000 to an explicit address")

    def test_no_compose_service_publishes_a_backend_port_to_the_host(self):
        offenders = []
        for path in compose_files():
            for key, service in (load_compose(path).get("services") or {}).items():
                if service.get("container_name") in BACKEND_CONTAINERS and (service.get("ports") or service.get("expose")):
                    offenders.append(f"{path.relative_to(ROOT)}:{key}")
        self.assertEqual(offenders, [])


class ProxyProviderModeTests(unittest.TestCase):
    """The outpost must be the reverse proxy that sets the headers, for every path."""

    def blueprints(self):
        return [p for p in sorted((ROOT / "services/authentik/blueprints").glob("*.yaml"))
                if "authentik_providers_proxy.proxyprovider" in p.read_text(encoding="utf-8")]

    def test_three_proxy_providers_exist(self):
        self.assertEqual(len(self.blueprints()), 3)

    def test_every_proxy_provider_is_in_proxy_mode(self):
        for path in self.blueprints():
            modes = re.findall(r"^\s*mode:\s*(\S+)\s*$", path.read_text(encoding="utf-8"), re.M)
            self.assertEqual(modes, ["proxy"], f"{path.name}: forward-auth modes rely on another proxy to strip headers")

    def test_no_proxy_provider_skips_authentication_on_any_path(self):
        for path in self.blueprints():
            body = path.read_text(encoding="utf-8")
            self.assertNotRegex(body, r"^\s*skip_path_regex:\s*\S", f"{path.name}: unauthenticated paths carry no identity")

    def test_no_proxy_provider_accepts_header_or_basic_auth_passthrough(self):
        for path in self.blueprints():
            body = path.read_text(encoding="utf-8")
            for key in ("basic_auth_enabled", "intercept_header_auth"):
                match = re.search(rf"^\s*{key}:\s*(\S+)", body, re.M)
                if match:
                    self.assertIn(match.group(1).lower(), ("false", "no"), f"{path.name}: {key}")


# ------------------------------------------------------------------ header-name variants
def _load(name, relative, env=None):
    saved = {k: os.environ.get(k) for k in (env or {})}
    os.environ.update(env or {})
    try:
        spec = importlib.util.spec_from_file_location(name, ROOT / relative)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


portal = _load("portal_for_g1_bypass", "services/avrana-portal/portal.py")
kindle = _load("kindle_for_g1_bypass", "services/avrana-kindle-connector/kindle.py", {
    "CWA_DB": os.path.join(tempfile.gettempdir(), "g1-bypass-never-created.db"),
    "ABS_URL": "http://abs.invalid", "ABS_API_KEY": "synthetic-test-key",
    "REQUIRED_GROUP": BOOKS, "SENDER_ADDRESS": "sender@example.test", "KINDLE_USERNAME_ALIASES": ""})
sys.path.insert(0, str(ROOT / "services/avrana-home"))
from avrana_home import principal as home_principal  # noqa: E402


class _PortalProbe(portal.Handler):
    """The real portal handler without a socket: feed parsed headers, capture the reply."""

    def __init__(self, path, headers):  # noqa: D401 - deliberately skips BaseRequestHandler setup
        self.path, self.headers, self.command = path, headers, "GET"
        self.reply = None

    def _send(self, code, body, ctype="text/html; charset=utf-8", location=None):
        self.reply = (code, body, location)


def portal_get(path, pairs):
    probe = _PortalProbe(path, headers_from(pairs))
    probe.do_GET()
    return probe.reply


class _KindleProbe(kindle.Handler):
    def __init__(self, headers):
        self.headers = headers


def kindle_member(pairs):
    return _KindleProbe(headers_from(pairs))._member()


class HeaderVariantTests(unittest.TestCase):
    def test_controls_real_headers_do_grant(self):
        """Positive controls, so the negatives below are not vacuous."""
        code, body, _ = portal_get("/ops", [("X-authentik-groups", ADMIN)])
        self.assertEqual(code, 307)
        self.assertIn('href="/ops"', portal_get("/", [("X-authentik-groups", ADMIN)])[1])
        self.assertEqual(kindle_member([("X-authentik-username", "member-a"),
                                        ("X-authentik-groups", BOOKS)]), "member-a")
        p = home_principal.principal_from_headers([("X-authentik-username", "member-a"),
                                                   ("X-authentik-groups", BOOKS)])
        self.assertTrue(p.has_group(BOOKS))

    def test_portal_ignores_variant_group_headers(self):
        for name in VARIANT_GROUP_HEADERS:
            with self.subTest(header=name):
                code, _, _ = portal_get("/ops", [(name, ADMIN)])
                self.assertEqual(code, 404)
                self.assertNotIn('href="/ops"', portal_get("/", [(name, ADMIN)])[1])
                # Next to a real low-privilege header, the variant adds nothing.
                code, _, _ = portal_get("/ops", [("X-authentik-groups", "avrana-users"), (name, ADMIN)])
                self.assertEqual(code, 404)

    def test_kindle_ignores_variant_identity_headers(self):
        for user in VARIANT_USER_HEADERS:
            for group in VARIANT_GROUP_HEADERS:
                with self.subTest(user=user, group=group):
                    self.assertIsNone(kindle_member([(user, "member-a"), (group, BOOKS)]))
        for group in VARIANT_GROUP_HEADERS:
            with self.subTest(real_user_variant_group=group):
                self.assertIsNone(kindle_member([("X-authentik-username", "member-a"), (group, BOOKS)]))
        for user in VARIANT_USER_HEADERS:
            with self.subTest(variant_user_real_group=user):
                self.assertIsNone(kindle_member([(user, "member-a"), ("X-authentik-groups", BOOKS)]))

    def test_kindle_variant_username_never_replaces_the_real_one(self):
        for user in VARIANT_USER_HEADERS:
            with self.subTest(header=user):
                self.assertEqual(kindle_member([("X-authentik-username", "member-a"), (user, "member-b"),
                                                ("X-authentik-groups", BOOKS)]), "member-a")

    def test_home_principal_ignores_variant_headers(self):
        for user in VARIANT_USER_HEADERS:
            for group in VARIANT_GROUP_HEADERS:
                with self.subTest(user=user, group=group):
                    self.assertIsNone(home_principal.principal_or_none([(user, "member-a"), (group, BOOKS)]))
        for user in VARIANT_USER_HEADERS:
            with self.subTest(extra=user):
                p = home_principal.principal_from_headers([("X-authentik-username", "member-a"),
                                                           ("X-authentik-groups", "avrana-users"),
                                                           (user, "member-b")])
                self.assertEqual(p.username, "member-a")
        for group in VARIANT_GROUP_HEADERS:
            with self.subTest(extra=group):
                p = home_principal.principal_from_headers([("X-authentik-username", "member-a"),
                                                           ("X-authentik-groups", "avrana-users"),
                                                           (group, ADMIN)])
                self.assertFalse(p.has_group(ADMIN))

    def test_home_principal_rejects_repeated_real_headers_from_parsed_messages(self):
        """A second, forged copy next to the outpost's must void the identity, not pick one."""
        message = headers_from([("X-authentik-username", "member-a"), ("X-authentik-groups", "avrana-users"),
                                ("X-Authentik-Groups", ADMIN)])
        self.assertIsNone(home_principal.principal_or_none(list(message.items())))
        self.assertEqual(portal_get("/ops", list(message.items()))[0], 404)
        self.assertIsNone(kindle_member([("X-authentik-username", "member-a"), ("X-authentik-groups", BOOKS),
                                         ("x-authentik-USERNAME", "member-b")]))


class StdlibAssumptionTests(unittest.TestCase):
    """The variant tests rely on the stdlib not folding '_' into '-' or trimming names."""

    def test_header_lookup_does_not_fold_underscores_or_trailing_characters(self):
        message = headers_from([("X_authentik_groups", ADMIN), ("X-authentik-groups-", ADMIN)])
        self.assertIsNone(message.get("X-authentik-groups"))
        self.assertEqual(message.get_all("X-authentik-groups"), None)

    def test_whitespace_before_colon_is_not_the_real_header(self):
        raw = b"X-authentik-groups : " + ADMIN.encode() + b"\r\n\r\n"
        message = http.client.parse_headers(io.BytesIO(raw))
        self.assertIsNone(message.get("X-authentik-groups"))
        self.assertEqual(portal_get("/ops", list(message.items()))[0], 404)


if __name__ == "__main__":
    unittest.main()
