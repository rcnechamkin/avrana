"""AVR-790: the LDAP bind flow, checked inside a REAL throwaway Authentik with the REAL LDAP outpost.

Run by tests/authentik_ldap_bind_live.sh (CI workflow ldap-bind-flow.yml), never against production. Each phase is one
argument; the shell script orders them and restarts the outpost between two of them.

  setup                  blueprints, groups, synthetic members, providers, applications, outpost
  control                the EXISTING flow: proves the failure, and what the new flow changes
  cutover-*              the owner's step rehearsed: pointer swap, then outpost restart
  matrix                 the access matrix on a direct and a cached provider
  browser                the browser flow keeps the passkey; a browser cannot run the bind flow
  reputation             a failed bind counts the same on the new flow as on the old one
  revocation             measures cached-bind lag, in seconds, for each way of revoking a member

Runs on the server image's own Python: ldap3 is one of Authentik's dependencies. Synthetic names; every credential is
generated per run and stays in the run's temporary directory. "MEASURE" lines are the numbers the runbook reports.
"""
import http.cookiejar
import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request

import ldap3
from ldap3.core.exceptions import LDAPException

from authentik_enrollment_live import Api, expect, wait

BIND_FLOW = "avrana-ldap-bind"
BROWSER_FLOW = "default-authentication-flow"
INVALIDATION_FLOW = "default-provider-invalidation-flow"
BLUEPRINTS = ("avrana/avrana-ldap-bind.yaml", "avrana/avrana-session-tuning.yaml", "avrana/calibre-web-ldap.yaml")
GROUPS = ["avrana-books", "avrana-videos", "ldap-service"]
MEMBERS = {
    "holder": ["avrana-books", "avrana-videos"],
    "holder-two": ["avrana-books", "avrana-videos"],
    "plain": ["avrana-books", "avrana-videos"],
    "session-probe": ["avrana-books", "avrana-videos"],
    "outsider": [],
    "disabled": ["avrana-books", "avrana-videos"],
    "administrator": ["authentik Admins", "avrana-books", "avrana-videos"],
    "mfa-member": ["avrana-mfa-required", "avrana-books", "avrana-videos"],
    "rep-old": ["avrana-books", "avrana-videos"],
    "rep-new": ["avrana-books", "avrana-videos"],
    "lag-disabled": ["avrana-books", "avrana-videos"],
    "lag-deleted": ["avrana-books", "avrana-videos"],
    "lag-password": ["avrana-books", "avrana-videos"],
    "lag-group": ["avrana-books", "avrana-videos"],
}
# Production's two shapes: jellyfin-ldap direct (E1, 2026-10-30, it exists only live, so CI builds it) and calibre-ldap
# cached (the repository's blueprint, applied as it stands). The rest keep the existing flow, as the control.
JELLYFIN = "DC=jellyfin,DC=avrana,DC=lan"
CALIBRE = "DC=avrana,DC=net"
CONTROL = "DC=control,DC=ci,DC=test"
CONTROL_CACHED = "DC=cached,DC=ci,DC=test"
CUTOVER = "DC=cutover,DC=ci,DC=test"
EXTRA_PROVIDERS = (
    ("jellyfin-ldap", "jellyfin", JELLYFIN, "direct", BIND_FLOW),
    ("ci-control", "ci-control", CONTROL, "direct", BROWSER_FLOW),
    ("ci-control-cached", "ci-control-cached", CONTROL_CACHED, "cached", BROWSER_FLOW),
    ("ci-cutover", "ci-cutover", CUTOVER, "cached", BROWSER_FLOW),
)


class Run:
    def __init__(self):
        self.api = Api()
        self.results = []
        self.path = os.path.join(os.environ["WORK"], "state.json")
        self.state = {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                self.state = json.load(f)
        self.server = ldap3.Server(os.environ["LDAP_HOST"], port=3389, get_info=ldap3.NONE, connect_timeout=10)

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.state, f)

    def check(self, label, ok, detail=""):
        self.results.append(expect(label, ok, detail))

    def finish(self):
        if not all(self.results):
            raise SystemExit(f"{self.results.count(False)} of {len(self.results)} checks failed")
        print(f"all {len(self.results)} checks passed", flush=True)

    def connect(self, dn_base, name, password):
        conn = ldap3.Connection(self.server, user=f"cn={name},ou=users,{dn_base}", password=password, receive_timeout=30)
        return conn, conn.bind()

    def bind(self, dn_base, name, password=None):
        conn, ok = self.connect(dn_base, name, password or self.state["passwords"][name])
        description = conn.result.get("description")
        conn.unbind()
        return ok, description

    def serving(self, dn_base):
        try:
            return self.bind(dn_base, "plain")[0]
        except LDAPException:
            return False

    def flow_pk(self, slug):
        return self.api.one("/api/v3/flows/instances/?slug=" + slug)["pk"]

    def group_pk(self, name):
        return self.api.one("/api/v3/core/groups/?name=" + urllib.parse.quote(name))["pk"]

    def user(self, name):
        return self.api.one("/api/v3/core/users/?username=" + urllib.parse.quote(name))

    def session_seconds(self, name):
        """Seconds left on the newest session of `name`: what a cached bind's cookie carries."""
        found = self.api.get("/api/v3/core/authenticated_sessions/?user__username=" + urllib.parse.quote(name))["results"]
        expires = [s["expires"] for s in found if s.get("expires")]
        if not expires:
            return None
        newest = max(expires).replace("Z", "+00:00")
        return time.mktime(time.strptime(newest[:19], "%Y-%m-%dT%H:%M:%S")) - time.mktime(time.gmtime())


def apply(api, path):
    def discovered():
        return any(b.get("path") == path for b in api.get("/api/v3/managed/blueprints/available/"))
    wait(f"{path} discovered", discovered)
    found = api.get("/api/v3/managed/blueprints/?path=" + urllib.parse.quote(path))["results"]
    if found:
        instance = found[0]
    else:
        status, instance = api.call("POST", "/api/v3/managed/blueprints/",
                                    {"name": path, "path": path, "enabled": True, "context": {}})
        assert status == 201, (status, instance)

    def applied():
        status, _ = api.call("POST", f"/api/v3/managed/blueprints/{instance['pk']}/apply/")
        state = api.get(f"/api/v3/managed/blueprints/{instance['pk']}/")["status"]
        print(f"{path} apply -> HTTP {status}, status {state}", flush=True)
        return state == "successful"
    wait(f"{path} applied", applied, seconds=300)


def post(api, path, body, want=201):
    status, reply = api.call("POST", path, body)
    assert status == want, (path, status, reply)
    return reply


def app_password(api, identifier, user_pk):
    post(api, "/api/v3/core/tokens/", {"identifier": identifier, "intent": "app_password", "user": user_pk,
                                       "expiring": False})
    return api.get(f"/api/v3/core/tokens/{identifier}/view_key/")["key"]


def setup():
    run = Run()
    api = run.api
    wait("api and bootstrap token", lambda: api.call("GET", "/api/v3/core/users/me/")[0] == 200)
    wait("default authentication flow", lambda: api.get("/api/v3/flows/instances/?slug=" + BROWSER_FLOW)["results"])
    wait("default invalidation flow", lambda: api.get("/api/v3/flows/instances/?slug=" + INVALIDATION_FLOW)["results"])
    wait("default mfa validation stage", lambda: api.get(
        "/api/v3/stages/authenticator/validate/?name=default-authentication-mfa-validation")["results"])
    print("authentik version", api.get("/api/v3/admin/version/").get("version_current"), flush=True)
    for name in GROUPS:
        post(api, "/api/v3/core/groups/", {"name": name})
    for path in BLUEPRINTS:
        apply(api, path)

    passwords = {}
    for name, groups in MEMBERS.items():
        made = post(api, "/api/v3/core/users/", {"username": name, "name": f"Synthetic {name}", "path": "ci",
                                                 "groups": [run.group_pk(g) for g in groups]})
        passwords[name] = secrets.token_urlsafe(24)
        post(api, f"/api/v3/core/users/{made['pk']}/set_password/", {"password": passwords[name]}, want=204)
    status, body = api.call("PATCH", f"/api/v3/core/users/{run.user('disabled')['pk']}/", {"is_active": False})
    assert status == 200, (status, body)

    # Service accounts bind with app passwords, as ldap-cwa and ldap-jellyfin do. ldap-cwa comes from the blueprint.
    jelly = post(api, "/api/v3/core/users/", {"username": "ldap-jellyfin", "name": "Jellyfin LDAP bind",
                                              "type": "service_account", "path": "goauthentik.io/outposts/ldap"})
    cwa = run.user("ldap-cwa")
    for member in (jelly, cwa):
        post(api, f"/api/v3/core/groups/{run.group_pk('ldap-service')}/add_user/", {"pk": member["pk"]}, want=204)
    passwords["ldap-cwa"] = app_password(api, "ci-ldap-cwa", cwa["pk"])
    passwords["ldap-jellyfin"] = app_password(api, "ci-ldap-jellyfin", jelly["pk"])
    # A service account passes the same application access check as a member.
    for member in (jelly, cwa):
        for group in ("avrana-videos", "avrana-books"):
            post(api, f"/api/v3/core/groups/{run.group_pk(group)}/add_user/", {"pk": member["pk"]}, want=204)

    invalidation = run.flow_pk(INVALIDATION_FLOW)
    providers = [api.one("/api/v3/providers/ldap/?name=calibre-ldap")["pk"]]
    video = run.group_pk("avrana-videos")
    for name, slug, dn_base, mode, flow in EXTRA_PROVIDERS:
        pk = run.flow_pk(flow)
        made = post(api, "/api/v3/providers/ldap/", {
            "name": name, "base_dn": dn_base, "bind_mode": mode, "search_mode": mode, "mfa_support": False,
            "authentication_flow": pk, "authorization_flow": pk, "invalidation_flow": invalidation})
        app = post(api, "/api/v3/core/applications/", {"name": slug, "slug": slug, "backchannel_providers": [made["pk"]]})
        post(api, "/api/v3/policies/bindings/", {"target": app["pk"], "group": video, "order": 0, "enabled": True})
        providers.append(made["pk"])
    outpost = post(api, "/api/v3/outposts/instances/", {
        "name": "avrana-ldap", "type": "ldap", "providers": providers,
        "config": {"authentik_host": "http://10.0.0.11:9000", "authentik_host_insecure": True}})
    run.state = {"passwords": passwords}
    run.save()

    def token_key():
        status, body = api.call("GET", f"/api/v3/core/tokens/{outpost['token_identifier']}/view_key/")
        if status != 200:
            return None
        with open(os.path.join(os.environ["WORK"], "outpost-token"), "w", encoding="utf-8") as f:
            f.write(body["key"])
        return True
    wait("outpost token", token_key)


def control():
    run = Run()
    wait("the outpost serves every provider", lambda: run.serving(CONTROL) and run.serving(JELLYFIN), seconds=180)
    ok, why = run.bind(CONTROL, "holder")
    run.check("control: on the existing flow a passkey holder's correct password is refused", ok is False, why)
    ok, why = run.bind(CONTROL, "plain")
    run.check("control: on the existing flow a member with no passkey binds", ok is True, why)
    ok, why = run.bind(CONTROL, "administrator")
    run.check("control: on the existing flow an administrator with no passkey binds (the new flow must not)",
              ok is True, why)

    # The lifetime a cached bind gets today. The connection stays open so no unbind ends the session first.
    conn, ok = run.connect(CONTROL_CACHED, "session-probe", run.state["passwords"]["session-probe"])
    seconds = run.session_seconds("session-probe")
    conn.unbind()
    print(f"MEASURE existing-flow-session-seconds={seconds} (days={None if seconds is None else round(seconds / 86400, 1)})",
          flush=True)
    run.check("control: the existing flow gives a bind about 180 days",
              ok is True and seconds is not None and seconds > 170 * 86400, f"{ok} {seconds}")
    run.finish()


def cutover_before_restart():
    """The owner's pointer change, on a cached provider that already refused a passkey holder."""
    run = Run()
    api = run.api
    ok, why = run.bind(CUTOVER, "holder")
    run.check("cutover: before the change a holder is refused on the cached provider", ok is False, why)
    provider = api.one("/api/v3/providers/ldap/?name=ci-cutover")
    pk = run.flow_pk(BIND_FLOW)
    status, body = api.call("PATCH", f"/api/v3/providers/ldap/{provider['pk']}/",
                            {"authentication_flow": pk, "authorization_flow": pk})
    assert status == 200, (status, body)

    def on_new_flow():
        # A fresh password each try: a refusal from the old flow is cached against the DN and password it was given for.
        password = secrets.token_urlsafe(24)
        post(api, f"/api/v3/core/users/{run.user('holder-two')['pk']}/set_password/", {"password": password}, want=204)
        return run.bind(CUTOVER, "holder-two", password)[0] is True
    wait("the outpost picked up the new pointer", on_new_flow, seconds=240)
    ok, why = run.bind(CUTOVER, "holder")
    print(f"MEASURE cutover-holder-before-restart bind={ok} ({why})", flush=True)
    run.check("cutover: without a restart the cached refusal survives the pointer change", ok is False, why)
    run.finish()


def cutover_after_restart():
    run = Run()
    wait("the restarted outpost serves", lambda: run.serving(JELLYFIN), seconds=180)
    ok, why = run.bind(CUTOVER, "holder")
    run.check("cutover: after the outpost restart the same holder binds", ok is True, why)
    run.finish()


def search_count(run, dn_base, account, name):
    conn, ok = run.connect(dn_base, account, run.state["passwords"][account])
    found = None
    if ok:
        conn.search(f"ou=users,{dn_base}", f"(cn={name})", attributes=["cn"])
        found = len(conn.entries)
    description = conn.result.get("description")
    conn.unbind()
    return ok, found, description


def matrix():
    run = Run()
    for label, dn_base, account in (("direct", JELLYFIN, "ldap-jellyfin"), ("cached", CALIBRE, "ldap-cwa")):
        ok, why = run.bind(dn_base, "holder")
        run.check(f"{label}: a passkey holder binds with the password", ok is True, why)
        ok, why = run.bind(dn_base, "plain")
        run.check(f"{label}: a member with no MFA still binds", ok is True, why)
        ok, why = run.bind(dn_base, "plain", "wrong-" + secrets.token_urlsafe(12))
        run.check(f"{label}: a bad password is refused", ok is False, why)
        ok, why = run.bind(dn_base, "nobody-" + secrets.token_hex(4), "wrong-" + secrets.token_urlsafe(12))
        run.check(f"{label}: an unknown name is refused", ok is False, why)
        ok, why = run.bind(dn_base, "disabled")
        run.check(f"{label}: a disabled member is refused", ok is False, why)
        ok, why = run.bind(dn_base, "outsider")
        run.check(f"{label}: a member outside the application's group is refused",
                  ok is False and why == "insufficientAccessRights", why)
        ok, why = run.bind(dn_base, "administrator")
        run.check(f"{label}: an administrator is refused, with the right password", ok is False, why)
        ok, why = run.bind(dn_base, "mfa-member")
        run.check(f"{label}: a member of avrana-mfa-required is refused", ok is False, why)
        for attempt in (1, 2):
            ok, found, why = search_count(run, dn_base, account, "plain")
            print(f"MEASURE {label}-service-search-{attempt} bind={ok} entries={found} ({why})", flush=True)
            run.check(f"{label}: service account search bind works (connection {attempt})",
                      ok is True and found == 1, f"{ok} {found} {why}")
    finished = time.time()
    run.bind(JELLYFIN, "plain")
    direct_ms = int((time.time() - finished) * 1000)
    finished = time.time()
    run.bind(CALIBRE, "plain")
    print(f"MEASURE bind-ms direct={direct_ms} cached={int((time.time() - finished) * 1000)}", flush=True)

    # The fail-closed path: a policy that raises must refuse, not wave the bind through.
    api = run.api
    policy = api.one("/api/v3/policies/expression/?name=avrana-ldap-bind-privileged")
    status, body = api.call("PATCH", f"/api/v3/policies/expression/{policy['pk']}/", {"expression": 'raise ValueError("ci")'})
    assert status == 200, (status, body)
    ok, why = run.bind(JELLYFIN, "plain")
    run.check("fail closed: a policy error refuses the bind", ok is False, why)
    status, body = api.call("PATCH", f"/api/v3/policies/expression/{policy['pk']}/", {"expression": policy["expression"]})
    assert status == 200, (status, body)
    ok, why = run.bind(JELLYFIN, "plain")
    run.check("fail closed: the restored policy lets a member bind again", ok is True, why)
    run.finish()


class Browser:
    """A stranger's browser at the flow executor: anonymous, its own cookie jar, no outpost anything."""

    def __init__(self, run, flow, headers=None):
        self.run, self.url = run, f"/api/v3/flows/executor/{flow}/?query="
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        for name, value in (headers or {}).items():
            self.opener.addheaders.append((name, value))

    def start(self):
        status, reply = self.run.api.call("GET", self.url, auth=False, opener=self.opener)
        return status, reply if isinstance(reply, dict) else {}

    def send(self, body):
        status, reply = self.run.api.call("POST", self.url, body, auth=False, opener=self.opener)
        return status, reply if isinstance(reply, dict) else {}

    def signed_in(self):
        return self.run.api.call("GET", "/api/v3/core/users/me/", auth=False, opener=self.opener)[0] == 200

    def identify_and_password(self, name):
        reply = self.start()[1]
        if reply.get("component") != "ak-stage-identification":
            return reply
        reply = self.send({"component": "ak-stage-identification", "uid_field": name})[1]
        if reply.get("component") != "ak-stage-password":
            return reply
        return self.send({"component": "ak-stage-password", "password": self.run.state["passwords"][name]})[1]


def browser():
    run = Run()
    api = run.api
    reply = Browser(run, BROWSER_FLOW)
    answer = reply.identify_and_password("holder")
    classes = [d.get("device_class") for d in answer.get("device_challenges") or []]
    run.check("browser flow: after the password a holder still faces the passkey",
              answer.get("component") == "ak-stage-authenticator-validate" and "webauthn" in classes,
              f"{answer.get('component')} {classes}")
    run.check("browser flow: a holder is not signed in by the password alone", reply.signed_in() is False)

    plain = Browser(run, BROWSER_FLOW)
    answer = plain.identify_and_password("plain")
    if answer.get("component") == "ak-stage-user-login":
        plain.send({"component": "ak-stage-user-login", "remember_me": False})
    run.check("browser flow: a member with no passkey still signs in", plain.signed_in() is True, answer.get("component"))

    answer = Browser(run, BIND_FLOW).start()[1]
    run.check("bind flow: a browser is refused", answer.get("component") == "ak-stage-access-denied", answer)
    forged = {"X-authentik-outpost-token": secrets.token_hex(32), "X-authentik-remote-ip": "198.51.100.7"}
    answer = Browser(run, BIND_FLOW, forged).start()[1]
    run.check("bind flow: an invented outpost token is refused", answer.get("component") == "ak-stage-access-denied", answer)
    stolen = {"X-authentik-outpost-token": os.environ["AK_TOKEN"], "X-authentik-remote-ip": "198.51.100.7"}
    answer = Browser(run, BIND_FLOW, stolen).start()[1]
    run.check("bind flow: an API token that is not an outpost's is refused",
              answer.get("component") == "ak-stage-access-denied", answer)

    # The negative control. With the guard off this flow IS a passkey bypass, which is what require_outpost is for. This
    # is the throwaway Authentik, and the guard goes back before anything else runs.
    status, body = api.call("PATCH", f"/api/v3/flows/instances/{BIND_FLOW}/", {"authentication": "none"})
    assert status == 200, (status, body)
    bypass = Browser(run, BIND_FLOW)
    try:
        bypass.identify_and_password("holder")
        signed_in = bypass.signed_in()
    finally:
        status, body = api.call("PATCH", f"/api/v3/flows/instances/{BIND_FLOW}/", {"authentication": "require_outpost"})
        assert status == 200, (status, body)
    run.check("negative control: without require_outpost a browser skips the passkey", signed_in is True)
    answer = Browser(run, BIND_FLOW).start()[1]
    run.check("bind flow: refused again with the guard restored", answer.get("component") == "ak-stage-access-denied", answer)

    bind = api.one("/api/v3/flows/instances/?slug=" + BIND_FLOW)
    run.check("bind flow: designation, authentication, denied action",
              (bind["designation"], bind["authentication"], bind["denied_action"])
              == ("authentication", "require_outpost", "message"), bind)
    stages = api.get(f"/api/v3/flows/bindings/?target={bind['pk']}&ordering=order")["results"]
    names = [s["stage_obj"]["component"] for s in stages]
    run.check("bind flow: no authenticator stage is bound",
              names == ["ak-stage-identification-form", "ak-stage-password-form", "ak-stage-deny-form",
                        "ak-stage-user-login-form"], names)
    original = api.one("/api/v3/flows/instances/?slug=" + BROWSER_FLOW)
    stages = api.get(f"/api/v3/flows/bindings/?target={original['pk']}&ordering=order")["results"]
    names = [s["stage_obj"]["name"] for s in stages]
    run.check("browser flow: its stages are unchanged and it keeps the MFA stage",
              names == ["default-authentication-identification", "default-authentication-password",
                        "default-authentication-mfa-validation", "default-authentication-login"], names)
    calibre = api.one("/api/v3/providers/ldap/?name=calibre-ldap")
    run.check("calibre-ldap: both pointers name the bind flow",
              str(calibre["authentication_flow"]) == str(bind["pk"]) and str(calibre["authorization_flow"]) == str(bind["pk"]),
              calibre)
    brand = api.get("/api/v3/core/brands/")["results"]
    run.check("no brand uses the bind flow", all(str(b.get("flow_authentication")) != str(bind["pk"]) for b in brand))
    run.finish()


def reputation_score(run, name):
    return sum(r["score"] for r in run.api.get("/api/v3/policies/reputation/scores/?identifier=" + name)["results"])


def reputation():
    """Authentik has no bind lockout on either flow: a bind is one new flow plan, so the password stage's cancel count never
    builds up. What must hold is that the new flow feeds the same reputation score, the signal a policy would act on."""
    run = Run()
    for attempt in range(3):
        run.bind(CONTROL, "rep-old", f"wrong-{attempt}-" + secrets.token_urlsafe(12))
        run.bind(JELLYFIN, "rep-new", f"wrong-{attempt}-" + secrets.token_urlsafe(12))
    time.sleep(20)
    old, new = reputation_score(run, "rep-old"), reputation_score(run, "rep-new")
    print(f"MEASURE reputation-after-3-bad-binds existing={old} bind-flow={new}", flush=True)
    run.check("failed binds lower the score the same on both flows", old == new and new < 0, f"{old} {new}")
    wrong = "wrong-" + secrets.token_urlsafe(12)
    before = reputation_score(run, "rep-new")
    for _ in range(3):
        run.bind(CALIBRE, "rep-new", wrong)
    time.sleep(20)
    print(f"MEASURE reputation-same-bad-password-3x-cached delta={reputation_score(run, 'rep-new') - before}", flush=True)
    ok, why = run.bind(JELLYFIN, "rep-new")
    print(f"MEASURE bind-after-failures bind={ok} ({why})", flush=True)
    run.check("failures do not lock a member out on the new flow (as on the old one)", ok is True, why)
    run.finish()


def revocation():
    """Each member binds on both providers, then is revoked. The direct provider must refuse at once. The cached provider is
    polled until it refuses: that is the revocation lag."""
    run = Run()
    api = run.api
    passwords = run.state["passwords"]
    new_password = secrets.token_urlsafe(24)

    def disable():
        status, body = api.call("PATCH", f"/api/v3/core/users/{run.user('lag-disabled')['pk']}/", {"is_active": False})
        assert status == 200, (status, body)

    def delete():
        status, body = api.call("DELETE", f"/api/v3/core/users/{run.user('lag-deleted')['pk']}/")
        assert status == 204, (status, body)

    def change_password():
        post(api, f"/api/v3/core/users/{run.user('lag-password')['pk']}/set_password/", {"password": new_password}, want=204)

    def remove_groups():
        pk = run.user("lag-group")["pk"]
        for group in ("avrana-videos", "avrana-books"):
            post(api, f"/api/v3/core/groups/{run.group_pk(group)}/remove_user/", {"pk": pk}, want=204)

    cases = {"lag-disabled": ("disabled", disable), "lag-deleted": ("deleted", delete),
             "lag-password": ("password-changed", change_password), "lag-group": ("group-removed", remove_groups)}
    for name in cases:
        for dn_base in (JELLYFIN, CALIBRE):
            ok, why = run.bind(dn_base, name)
            run.check(f"revocation: {name} binds before the change", ok is True, why)
    revoked = {}
    for name, (label, change) in cases.items():
        change()
        revoked[name] = time.time()
        ok, why = run.bind(JELLYFIN, name)
        run.check(f"revocation: {label} takes effect at once on the direct provider", ok is False, why)
    ok, why = run.bind(JELLYFIN, "lag-password", new_password)
    run.check("revocation: the new password works at once on the direct provider", ok is True, why)
    ok, why = run.bind(CALIBRE, "lag-password", new_password)
    run.check("revocation: the new password works at once on the cached provider", ok is True, why)

    lag = {}
    pending = set(cases)
    deadline = time.time() + 420
    first = True
    while pending and time.time() < deadline:
        for name in sorted(pending):
            ok, _ = run.bind(CALIBRE, name)
            if first:
                print(f"MEASURE cached-immediately-after-{cases[name][0]} bind={ok}", flush=True)
            if not ok:
                lag[name] = time.time() - revoked[name]
                pending.discard(name)
        first = False
        if pending:
            time.sleep(10)
    for name, (label, _) in cases.items():
        print(f"MEASURE cached-revocation-lag-seconds {label}={int(lag[name]) if name in lag else 'not-refused-in-420s'}",
              flush=True)
        run.check(f"revocation: {label} ends on the cached provider within the 5 minute session plus a poll",
                  name in lag and lag[name] <= 330, lag.get(name))

    # And back: does a cached refusal outlive the reason for it? Reported as measured; the runbook states the result.
    status, body = api.call("PATCH", f"/api/v3/core/users/{run.user('lag-disabled')['pk']}/", {"is_active": True})
    assert status == 200, (status, body)
    pk = run.user("lag-group")["pk"]
    for group in ("avrana-videos", "avrana-books"):
        post(api, f"/api/v3/core/groups/{run.group_pk(group)}/add_user/", {"pk": pk}, want=204)
    for name, label in (("lag-disabled", "re-enabled"), ("lag-group", "re-added")):
        ok, why = run.bind(JELLYFIN, name)
        run.check(f"restore: {label} member binds on the direct provider", ok is True, why)
        ok, why = run.bind(CALIBRE, name)
        print(f"MEASURE cached-after-{label} bind={ok} ({why})", flush=True)
    run.finish()


if __name__ == "__main__":
    {"setup": setup, "control": control, "cutover-before-restart": cutover_before_restart,
     "cutover-after-restart": cutover_after_restart, "matrix": matrix, "browser": browser, "reputation": reputation,
     "revocation": revocation}[sys.argv[1]]()
