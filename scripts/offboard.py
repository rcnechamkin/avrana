#!/usr/bin/env python3
"""Offboard an Avrana member across every system that holds an account for them.

WHY THIS EXISTS
    Deleting the Authentik user does NOT offboard anyone. Jellyfin holds a *replicated
    password* created at enrollment, so the account keeps working after Authentik is gone;
    Seerr rides on that Jellyfin account; ABS, Komga and Calibre-Web each auto-provisioned a
    local account on first SSO login. Offboarding by hand means six systems in the right order,
    which is easy to half-complete - and it gets done under time pressure, which is exactly when
    steps get skipped.

THE HARD PART: THERE IS NO SINGLE JOIN KEY
    Verified against the live stack:
      - Jellyfin stores NO email for any user. Its only key is the username.
      - Audiobookshelf stores email, and those emails match Authentik.
      - The admin's Authentik username is `akadmin` but his Jellyfin/ABS/Seerr account is `Cody`.
    So matching cannot be automatic. This tool resolves candidates per system using the key that
    system actually has, then SHOWS YOU EXACTLY WHAT IT MATCHED and refuses to act without
    confirmation. A fuzzy match is never acted on silently.

SAFETY
    - Dry run by default. Nothing changes without --apply.
    - Disable by default (reversible, keeps watch history). --purge deletes instead.
    - Refuses to touch protected accounts (akadmin / the ABS root user) outright.
    - Authentik is handled LAST, because identity resolution depends on it.
    - Verifies afterwards that the account can no longer authenticate.
"""
from __future__ import annotations

import argparse
import shlex
import json
import subprocess
import sys
import urllib.error
import urllib.request

SECRETS = "/home/cody/avrana/services/homepage/widget-secrets.env"
OLIVETIN_ENV = "/home/cody/avrana/services/olivetin/.env"
SEERR_SETTINGS = "/home/cody/docker/seerr/config/settings.json"

JELLYFIN = "http://10.0.0.218:8096"
ABS = "http://10.0.0.218:13378"
SEERR = "http://10.0.0.218:5055"
KOMGA = "http://10.0.0.218:25600"

# Never offboardable by this tool, at any flag combination.
PROTECTED = {"akadmin", "cody", "ldap-cwa", "root"}


def load_env(path: str) -> dict:
    out = {}
    try:
        for line in open(path):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                out[k] = v
    except OSError:
        pass
    return out


SEC = load_env(SECRETS)
OT = load_env(OLIVETIN_ENV)


def api(url, headers, method="GET", body=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def jf_headers():
    key = OT.get("JELLYFIN_API_KEY") or SEC.get("HOMEPAGE_VAR_JELLYFIN_KEY", "")
    return {"X-MediaBrowser-Token": key, "Content-Type": "application/json"}


def abs_headers():
    return {"Authorization": f"Bearer {SEC.get('HOMEPAGE_VAR_ABS_KEY','')}",
            "Content-Type": "application/json"}


def seerr_headers():
    try:
        key = json.load(open(SEERR_SETTINGS))["main"]["apiKey"]
    except Exception:
        key = ""
    return {"X-Api-Key": key, "Content-Type": "application/json"}


# ---------------------------------------------------------------- identity resolution
def authentik_user(username: str) -> dict | None:
    row = sh(
        "docker exec authentik-postgresql psql -U authentik -d authentik -t -A -F'|' -c "
        f"\"SELECT username,email,name,is_active FROM authentik_core_user WHERE lower(username)=lower('{username}');\""
    )
    if not row or "|" not in row:
        return None
    u, e, n, active = (row.split("|") + ["", "", "", ""])[:4]
    return {"username": u, "email": e, "name": n, "active": active == "t"}


def find_matches(ident: dict) -> dict:
    """Resolve this person's account in each system, using the key that system actually has."""
    uname = ident["username"].lower()
    email = (ident.get("email") or "").lower()
    m = {"jellyfin": [], "abs": [], "seerr": [], "komga": [], "notes": []}

    # Jellyfin: username only - it stores no email.
    try:
        for u in api(f"{JELLYFIN}/Users", jf_headers()):
            if u["Name"].lower() == uname:
                m["jellyfin"].append({"id": u["Id"], "name": u["Name"],
                                      "disabled": u.get("Policy", {}).get("IsDisabled", False)})
    except Exception as e:
        m["notes"].append(f"jellyfin unreachable: {type(e).__name__}")

    # ABS: email is reliable here; fall back to username.
    try:
        for u in api(f"{ABS}/api/users", abs_headers()).get("users", []):
            if (email and (u.get("email") or "").lower() == email) or u["username"].lower() == uname:
                m["abs"].append({"id": u["id"], "name": u["username"], "type": u.get("type"),
                                 "disabled": not u.get("isActive", True)})
    except Exception as e:
        m["notes"].append(f"abs unreachable: {type(e).__name__}")

    # Seerr: rides on the Jellyfin account, so match its display/user name.
    try:
        for u in api(f"{SEERR}/api/v1/user?take=200", seerr_headers()).get("results", []):
            nm = (u.get("displayName") or u.get("username") or "").lower()
            if nm == uname or (email and (u.get("email") or "").lower() == email):
                m["seerr"].append({"id": u["id"], "name": u.get("displayName") or u.get("username")})
    except Exception as e:
        m["notes"].append(f"seerr unreachable: {type(e).__name__}")

    # Komga: the available API key is rejected (403/401 verified), so this tool cannot act there.
    m["notes"].append("komga: no working admin credential on this host - handle manually "
                      "(Komga UI -> Users). See BookStack.")
    # Calibre-Web: no user-delete API; users live in its local app.db.
    m["notes"].append("calibre-web: no user API - LDAP users lose access when Authentik is "
                      "disabled, but the local row remains. Handle manually if you want it gone.")
    return m


# ---------------------------------------------------------------- actions
def act_jellyfin(entry, purge, apply_):
    """The real revocation: Jellyfin holds its own password copy."""
    if not apply_:
        return f"would {'DELETE' if purge else 'DISABLE'} jellyfin/{entry['name']}"
    if purge:
        api(f"{JELLYFIN}/Users/{entry['id']}", jf_headers(), method="DELETE")
        return f"deleted jellyfin/{entry['name']}"
    pol = api(f"{JELLYFIN}/Users/{entry['id']}", jf_headers()).get("Policy", {})
    pol["IsDisabled"] = True
    api(f"{JELLYFIN}/Users/{entry['id']}/Policy", jf_headers(), method="POST", body=pol)
    return f"disabled jellyfin/{entry['name']}"


def act_abs(entry, purge, apply_):
    if entry.get("type") == "root":
        return f"REFUSED abs/{entry['name']} (root user)"
    if not apply_:
        return f"would {'DELETE' if purge else 'DISABLE'} abs/{entry['name']}"
    if purge:
        api(f"{ABS}/api/users/{entry['id']}", abs_headers(), method="DELETE")
        return f"deleted abs/{entry['name']}"
    api(f"{ABS}/api/users/{entry['id']}", abs_headers(), method="PATCH", body={"isActive": False})
    return f"disabled abs/{entry['name']}"


def act_seerr(entry, purge, apply_):
    if not apply_:
        return f"would {'DELETE' if purge else 'leave (Seerr has no disable)'} seerr/{entry['name']}"
    if purge:
        api(f"{SEERR}/api/v1/user/{entry['id']}", seerr_headers(), method="DELETE")
        return f"deleted seerr/{entry['name']}"
    return f"left seerr/{entry['name']} (no disable concept; it follows Jellyfin)"


def act_authentik(ident, purge, apply_):
    u = ident["username"]
    if not apply_:
        return f"would {'DELETE' if purge else 'DEACTIVATE'} authentik/{u}"
    if purge:
        # A plain DELETE fails: authentik_core_user_groups (and several other tables) hold FK
        # references, so postgres refuses. Django's ORM knows the cascade order, so delete through
        # it rather than hand-rolling a list of child tables that changes between versions.
        script = RETIRE_NAME_FIRST % {"name": repr(u)} + (      # RC1 S1: see RETIRE_NAME_FIRST
            "from authentik.core.models import User\n"
            f"qs = User.objects.filter(username__iexact={u!r})\n"
            "print('DELETED' if qs.exists() and qs.delete() else 'NOTFOUND')\n"
        )
        out = sh(f"docker exec -i authentik-server ak shell -c {shlex.quote(script)}")
        if "RETIRED" not in out or "DELETED" not in out:
            return f"FAILED to retire or delete authentik/{u} - check by hand"
        return f"retired the name and deleted authentik/{u}"
    sh("docker exec authentik-postgresql psql -U authentik -d authentik -c "
       f"\"UPDATE authentik_core_user SET is_active=false WHERE lower(username)=lower('{u}');\"")
    return f"deactivated authentik/{u}"


# ---------------------------------------------------------------- verification
def verify(ident, matches) -> list[str]:
    out = []
    for e in matches["jellyfin"]:
        try:
            u = api(f"{JELLYFIN}/Users/{e['id']}", jf_headers())
            dis = u.get("Policy", {}).get("IsDisabled")
            out.append(("PASS" if dis else "FAIL") + f"  jellyfin/{e['name']} IsDisabled={dis}")
        except urllib.error.HTTPError as ex:
            out.append(("PASS" if ex.code in (404, 400) else "FAIL") + f"  jellyfin/{e['name']} gone (HTTP {ex.code})")
    ak = authentik_user(ident["username"])
    if ak is None:
        out.append(f"PASS  authentik/{ident['username']} no longer exists")
    else:
        out.append(("PASS" if not ak["active"] else "FAIL") + f"  authentik/{ident['username']} active={ak['active']}")
    return out


def main():
    p = argparse.ArgumentParser(description="Offboard an Avrana member across all systems.")
    p.add_argument("username", nargs="?", help="Authentik username to offboard")
    p.add_argument("--apply", action="store_true", help="actually make changes (default: dry run)")
    p.add_argument("--purge", action="store_true", help="delete instead of disable")
    p.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    p.add_argument("--audit", action="store_true", help="report accounts across all systems and exit")
    a = p.parse_args()

    if a.audit:
        return audit()
    if not a.username:
        p.error("a username is required (or use --audit)")

    if a.username.lower() in PROTECTED:
        print(f"REFUSED: '{a.username}' is a protected account.")
        return 2

    ident = authentik_user(a.username)
    if ident is None:
        print(f"No Authentik user '{a.username}'. If they were already deleted there, their "
              f"Jellyfin/ABS/Seerr accounts may still exist - run --audit to find orphans.")
        return 2

    matches = find_matches(ident)
    print(f"=== offboarding {ident['username']} ({ident.get('name') or 'no name'}) ===")
    print(f"    mode: {'PURGE (delete)' if a.purge else 'DISABLE (reversible)'}"
          f"   {'APPLY' if a.apply else 'DRY RUN'}")
    print("\n    matched accounts:")
    total = 0
    for sysname in ("jellyfin", "abs", "seerr"):
        for e in matches[sysname]:
            print(f"      {sysname:<10} {e['name']}")
            total += 1
    print(f"      {'authentik':<10} {ident['username']}")
    total += 1
    for n in matches["notes"]:
        print(f"    note: {n}")

    if total == 1:
        print("\n    Only the Authentik account matched. Check --audit before assuming that is right.")

    if a.apply and not a.yes:
        print(f"\n    This will {'DELETE' if a.purge else 'DISABLE'} {total} account(s).")
        if input("    Type the username to confirm: ").strip() != ident["username"]:
            print("    aborted.")
            return 1

    print("\n    actions:")
    # Jellyfin FIRST - it is the account that actually still works after Authentik is gone.
    for e in matches["jellyfin"]:
        print("      " + act_jellyfin(e, a.purge, a.apply))
    for e in matches["seerr"]:
        print("      " + act_seerr(e, a.purge, a.apply))
    for e in matches["abs"]:
        print("      " + act_abs(e, a.purge, a.apply))
    print("      " + act_komga_key(ident.get("email") or "", a.apply))     # S-01: Home's copy of their Komga key
    # Authentik LAST: identity resolution above depends on it.
    print("      " + act_authentik(ident, a.purge, a.apply))

    if a.apply:
        print("\n    verification:")
        for line in verify(ident, matches):
            print("      " + line)
    else:
        print("\n    (dry run - nothing was changed. re-run with --apply)")
    return 0


def audit():
    """Cross-system account report. Username is NOT a reliable join key, so this reports rather
    than concludes: it shows which accounts have no obvious Authentik counterpart."""
    ak_rows = sh("docker exec authentik-postgresql psql -U authentik -d authentik -t -A -F'|' -c "
                 "\"SELECT username,email,is_active FROM authentik_core_user "
                 "WHERE username NOT LIKE 'ak-outpost-%' AND username<>'AnonymousUser';\"")
    ak = {}
    for row in ak_rows.split("\n"):
        if "|" in row:
            u, e, act = (row.split("|") + ["", "", ""])[:3]
            ak[u.lower()] = {"email": e.lower(), "active": act == "t"}
    ak_emails = {v["email"] for v in ak.values() if v["email"]}

    print("=== Authentik (source of truth) ===")
    for u, v in sorted(ak.items()):
        print(f"    {u:<18} active={v['active']}")

    def report(label, names, emails=None):
        print(f"\n=== {label} ===")
        for i, n in enumerate(names):
            e = (emails[i] if emails else "") or ""
            by_name = n.lower() in ak
            by_mail = e.lower() in ak_emails if e else False
            tag = "" if (by_name or by_mail) else "   <-- no Authentik counterpart"
            print(f"    {n:<18} {'email-match' if by_mail else ('name-match' if by_name else 'UNMATCHED')}{tag}")

    try:
        jf = api(f"{JELLYFIN}/Users", jf_headers())
        report("Jellyfin (holds a replicated password - the real access)", [u["Name"] for u in jf])
    except Exception as e:
        print(f"\n=== Jellyfin === unreachable: {type(e).__name__}")
    try:
        au = api(f"{ABS}/api/users", abs_headers()).get("users", [])
        report("Audiobookshelf", [u["username"] for u in au], [u.get("email") for u in au])
    except Exception as e:
        print(f"\n=== ABS === unreachable: {type(e).__name__}")
    try:
        se = api(f"{SEERR}/api/v1/user?take=200", seerr_headers()).get("results", [])
        report("Seerr", [u.get("displayName") or u.get("username") for u in se],
               [u.get("email") for u in se])
    except Exception as e:
        print(f"\n=== Seerr === unreachable: {type(e).__name__}")

    print("\nNOTE: UNMATCHED does not always mean orphaned. Jellyfin stores no email, and the "
          "admin is 'akadmin' in Authentik but 'Cody' elsewhere. Confirm before acting.")
    return 0


# RC1 finding S1: --purge never frees the name for someone else. Before the user is deleted, in the same ak shell
# script (so a failure here deletes nothing), the name is added to the `usernames` attribute of the Authentik group
# avrana-retired-usernames, which the enrollment policy refuses (services/authentik/blueprints/avrana-enrollment.yaml).
# A retired name may still have rows in apps that match by username on a direct sign-in (Calibre-Web over LDAP,
# Shelfarr linking existing users) and in Media Home, which keeps it bound to the former member. Shelfarr, Omnibus,
# Calibre-Web and Komga accounts are deleted by hand; releasing a name: docs/runbooks/identity-bindings.md.
RETIRE_NAME_FIRST = (
    "from authentik.core.models import Group\n"
    "g, _ = Group.objects.get_or_create(name='avrana-retired-usernames')\n"
    "names = list((g.attributes or {}).get('usernames') or [])\n"
    "if %(name)s.casefold() not in {str(n).casefold() for n in names}:\n"
    "    names.append(%(name)s)\n"
    "g.attributes = dict(g.attributes or {}, usernames=names)\n"
    "g.save()\n"
    "print('RETIRED')\n"
)


# ---------------------------------------------------------------- Home's copy of the member's own Komga key
# Appended below everything else so the line citations in docs/runbooks/offboarding.md keep holding.
# Home's file of members' own Komga keys (services/avrana-home/docker-compose.beta-live.yml mounts ./state).
KOMGA_KEYS_FILE = "/home/cody/avrana/services/avrana-home/state/komga_member_keys"


def act_komga_key(email, apply_, keys_file=KOMGA_KEYS_FILE, client=None, home_dir=None):
    """S-01 (docs/runbooks/komga-key-lifecycle.md): revoke the member's own Komga key that Home holds, in Komga AS the
    member with the key itself (no admin credential), then drop it from Home's keys file. Never prints the key."""
    import os
    sys.path.insert(0, home_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                "services", "avrana-home"))
    from avrana_home.komga_keys import KomgaKeyClient
    from avrana_home.member_keys import KeysFileError, MemberKeyStore, member_key_id, read_keys
    if member_key_id(email) is None:
        return "komga key: no usable email for this member, nothing to do"
    if not os.path.isfile(keys_file):
        return f"komga key: no keys file at {keys_file}, nothing to do"
    try:
        store = MemberKeyStore(keys_file, writable=True, initial=read_keys(keys_file))
        held = store.get(email) is not None
        if not apply_:
            return ("would REVOKE the Komga key Home holds for this member and drop it from Home's keys file"
                    if held else "komga key: Home holds none for this member")
        filed = store.remove(email)
    except (KeysFileError, OSError) as e:
        return f"FAILED komga key: Home's keys file could not be used ({type(e).__name__}) - check by hand"
    if filed is None:
        return "komga key: Home holds none for this member"
    try:
        outcome = (client or KomgaKeyClient(KOMGA, timeout=15.0)).revoke(*filed)
    except Exception as e:
        return (f"dropped the Komga key from Home's file; Komga unreachable ({type(e).__name__}): delete the member's "
                "avrana-home key in Komga (Users) by hand")
    return ("revoked the member's Komga key and dropped it from Home's file" if outcome == "revoked"
            else "dropped the Komga key from Home's file (Komga no longer accepted it)")


if __name__ == "__main__":
    sys.exit(main())
