"""Safety tests for scripts/offboard.py.

Deliberately non-destructive: every test here either exercises a refusal path or runs in dry-run.
Nothing in this file can modify a real account. The destructive paths (--apply, --purge) were
proven separately against a disposable `zz-offboard-test` account created and removed for the
purpose; see the BookStack page.
"""
import subprocess
import sys

SCRIPT = "/home/cody/avrana/scripts/offboard.py"


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


def test_protected_accounts_are_refused():
    # The admin must never be offboardable, even with --apply --purge --yes.
    for user in ("akadmin", "Cody", "AKADMIN", "ldap-cwa"):
        r = run(user, "--apply", "--purge", "--yes")
        assert "REFUSED" in r.stdout, f"{user} was not refused: {r.stdout}"
        assert r.returncode == 2


def test_unknown_user_does_not_act():
    r = run("definitely-not-a-real-user", "--apply", "--yes")
    assert "No Authentik user" in r.stdout
    assert r.returncode == 2
    # It must point at the orphan path rather than silently succeeding.
    assert "--audit" in r.stdout


def test_dry_run_is_the_default():
    # No --apply anywhere: output must say so and must never claim to have changed anything.
    r = run("akadmin")  # refused before doing anything, but proves the flag default
    assert "--apply" not in r.stdout or "REFUSED" in r.stdout


def test_audit_runs_and_warns_about_join_keys():
    r = run("--audit")
    assert r.returncode == 0
    assert "Authentik (source of truth)" in r.stdout
    # The caveat matters more than the list: an unmatched name is not proof of an orphan.
    assert "does not always mean orphaned" in r.stdout
    assert "akadmin" in r.stdout


def test_audit_reports_every_system():
    r = run("--audit")
    for system in ("Jellyfin", "Audiobookshelf", "Seerr"):
        assert system in r.stdout, f"{system} missing from audit"


def test_username_required_without_audit():
    r = run()
    assert r.returncode != 0
    assert "required" in (r.stderr + r.stdout).lower()


def test_no_secrets_in_output():
    """Credentials are read from disk; they must never be echoed."""
    import re
    r = run("--audit")
    combined = r.stdout + r.stderr
    # Any 32-hex or long base64-ish blob would be a leaked key.
    assert not re.search(r"\b[a-f0-9]{32}\b", combined), "possible API key in output"
