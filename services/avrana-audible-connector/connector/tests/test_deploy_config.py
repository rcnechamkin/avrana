"""Static checks on the deployment: the companion must be private (no published port) and
on an internal-only network; the connector must never mount the Docker socket."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]  # services/avrana-audible-connector/


def _compose():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def test_companion_has_no_published_ports():
    c = _compose()["services"]["companion"]
    assert "ports" not in c or not c["ports"], "companion must not publish a host port"


def _env(service: str) -> dict:
    raw = _compose()["services"][service].get("environment", [])
    return dict(e.split("=", 1) for e in raw if "=" in e)


def test_companion_login_ttl_is_at_least_the_connector_session_ttl():
    """The companion must not reap a login-external process before the connector expires the
    matching session. When it did (10m vs 30m), a slow first-time sign-in failed completion
    while the connector still thought the session was live — the 'session not found' dead end.
    Connector SESSION_TTL defaults to 1800s (30m) and is not overridden in compose."""
    connector_ttl = int(_env("connector").get("SESSION_TTL", "1800"))
    companion_minutes = int(_env("companion")["AUTH_SESSION_TIMEOUT_MINUTES"])
    assert companion_minutes * 60 >= connector_ttl, (
        f"companion login TTL {companion_minutes}m < connector session TTL {connector_ttl}s"
    )


def test_internal_network_is_internal():
    nets = _compose()["networks"]
    assert nets["internal"].get("internal") is True


def test_companion_reaches_connector_and_audible_but_nothing_reaches_it():
    """The companion needs exactly two things: the connector can call it, and it can call
    Audible. Neither implies anyone can reach IN to it — that is what having no published
    ports guarantees, and it is the invariant worth pinning.

    This replaces an earlier `networks == ["internal"]` assertion. That was too strict and
    encoded a real outage: `internal: true` also blocks OUTBOUND traffic, so LibationCli
    could never reach Amazon and `/v1/auth/start` failed 502 on the first live attempt.
    """
    compose = _compose()
    c = compose["services"]["companion"]
    assert "internal" in c["networks"], "connector must still reach the companion privately"
    assert "ports" not in c, "companion must never publish a port"

    egress = [n for n in c["networks"] if n != "internal"]
    assert len(egress) == 1, f"companion should have exactly one egress network, got {egress}"
    assert compose["networks"][egress[0]].get("internal") is not True, (
        "the egress network must not be internal:true, or LibationCli cannot reach Audible"
    )
    # Sole member: an egress bridge nobody else joins is outbound-only in practice.
    others = [n for n, svc in compose["services"].items()
              if n != "companion" and egress[0] in svc.get("networks", [])]
    assert not others, f"{egress[0]} must have no members besides the companion, found {others}"


def test_no_docker_socket_mounted():
    services = _compose()["services"]
    for name, svc in services.items():
        for vol in svc.get("volumes", []):
            assert "docker.sock" not in str(vol), f"{name} must not mount the docker socket"


def test_companion_token_mounted_readonly():
    c = _compose()["services"]["companion"]
    tok = [v for v in c["volumes"] if "/control/token" in v]
    assert tok and tok[0].endswith(":ro")


def test_secrets_come_from_files_not_env():
    conn = _compose()["services"]["connector"]["environment"]
    joined = "\n".join(conn)
    # The token/secret/oidc secret must be referenced as *_FILE, never inlined.
    assert "COMPANION_TOKEN_FILE=" in joined
    assert "SECRET_KEY_FILE=" in joined
    assert "OIDC_CLIENT_SECRET_FILE=" in joined
    assert "COMPANION_TOKEN=" not in joined
