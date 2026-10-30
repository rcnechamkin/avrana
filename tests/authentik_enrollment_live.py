"""RC1 finding S1: the enrollment username policy, checked inside a REAL throwaway Authentik.

Run by tests/authentik_enrollment_live.sh (CI workflow enrollment-policy.yml), never against production:

  stub           a stand-in Jellyfin at 10.0.0.218:8096 (GET /Users with the run's key; names from JF_USERS)
  checks         apply avrana-enrollment.yaml, then ask Authentik's own policy engine and flow executor
  jellyfin-down  the same policy with the stub stopped: sign-up must refuse, not pass

Standard library only. Synthetic names; every credential is generated per run by the shell script.
"""
import http.cookiejar
import http.server
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

POLICY = "avrana-enrollment-username-available"
FLOW = "avrana-invite"
BLUEPRINT_PATH = "avrana/avrana-enrollment.yaml"
GROUPS = ["avrana-users", "avrana-audiobooks", "avrana-comics", "avrana-books", "avrana-videos", "avrana-requests",
          "library-contributors", "Avrana Home (Beta)"]
# The blueprint's first entry sets the groups of production's admin, so that user has to exist as it does live.
ADMIN = "Cody"
TAKEN = "That username is taken"
UNAVAILABLE = "briefly unavailable"


def stub():
    key, users = os.environ["JF_KEY"], [u for u in os.environ["JF_USERS"].split(",") if u]

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/Users" or self.headers.get("X-MediaBrowser-Token") != key:
                self.send_response(401)
                self.end_headers()
                return
            body = json.dumps([{"Name": n, "Id": f"{i:032x}"} for i, n in enumerate(users)]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    http.server.HTTPServer(("0.0.0.0", 8096), Handler).serve_forever()


class Api:
    def __init__(self):
        self.base, self.token = os.environ["AK_URL"].rstrip("/"), os.environ["AK_TOKEN"]
        self.jar = http.cookiejar.CookieJar()
        self.anon = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None, auth=True, opener=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        if auth:
            req.add_header("Authorization", f"Bearer {self.token}")
        open_ = opener.open if opener is not None else urllib.request.urlopen
        try:
            with open_(req, timeout=60) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except ValueError:
                return e.code, raw[:200]

    def get(self, path):
        status, body = self.call("GET", path)
        assert status == 200, (path, status, body)
        return body

    def one(self, path):
        results = self.get(path)["results"]
        assert len(results) == 1, (path, len(results))
        return results[0]


def wait(what, probe, seconds=600):
    deadline = time.time() + seconds
    while True:
        try:
            if probe():
                print(f"ready: {what}", flush=True)
                return
        except (OSError, AssertionError, ValueError, KeyError):
            pass
        if time.time() > deadline:
            raise SystemExit(f"timed out waiting for {what}")
        time.sleep(3)


def apply_blueprint(api):
    wait("api and bootstrap token", lambda: api.call("GET", "/api/v3/core/users/me/")[0] == 200)
    wait("default webauthn setup flow",
         lambda: api.get("/api/v3/flows/instances/?slug=default-authenticator-webauthn-setup")["results"])
    for name in GROUPS:
        if not api.get("/api/v3/core/groups/?name=" + urllib.parse.quote(name))["results"]:
            status, body = api.call("POST", "/api/v3/core/groups/", {"name": name})
            assert status == 201, (name, status, body)
    if not api.get("/api/v3/core/users/?username=" + urllib.parse.quote(ADMIN))["results"]:
        status, body = api.call("POST", "/api/v3/core/users/", {"username": ADMIN, "name": ADMIN})
        assert status == 201, (ADMIN, status, body)
    wait("blueprint discovered",
         lambda: any(b.get("path") == BLUEPRINT_PATH for b in api.get("/api/v3/managed/blueprints/available/")))
    found = api.get("/api/v3/managed/blueprints/?path=" + urllib.parse.quote(BLUEPRINT_PATH))["results"]
    if found:
        instance = found[0]
    else:
        status, instance = api.call("POST", "/api/v3/managed/blueprints/",
                                    {"name": "ci-enrollment", "path": BLUEPRINT_PATH, "enabled": True, "context": {}})
        assert status == 201, (status, instance)

    def applied():
        status, _ = api.call("POST", f"/api/v3/managed/blueprints/{instance['pk']}/apply/")
        state = api.get(f"/api/v3/managed/blueprints/{instance['pk']}/")["status"]
        print(f"blueprint apply -> HTTP {status}, status {state}", flush=True)
        return state == "successful"
    wait("blueprint applied successfully", applied, seconds=300)


def policy_test(api, user_pk, policy_pk, username):
    status, body = api.call("POST", f"/api/v3/policies/all/{policy_pk}/test/",
                            {"user": user_pk, "context": {"prompt_data": {"username": username}}})
    assert status == 200, (status, body)
    return body["passing"], " ".join(str(m) for m in body.get("messages") or [])


def expect(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (f"  ({detail})" if detail and not ok else ""), flush=True)
    return ok


def checks():
    api = Api()
    apply_blueprint(api)
    results = []
    policy = api.one("/api/v3/policies/expression/?name=" + POLICY)
    stage = api.one("/api/v3/stages/prompt/stages/?name=avrana-enrollment-prompt")
    results.append(expect("the prompt stage runs the username policy",
                          policy["pk"] in [str(p) for p in stage.get("validation_policies") or []], stage))
    me = api.get("/api/v3/core/users/me/")["user"]["pk"]
    status, body = api.call("POST", "/api/v3/core/users/", {"username": "existing-user", "name": "Existing"})
    assert status == 201, (status, body)
    retired = api.one("/api/v3/core/groups/?name=avrana-retired-usernames")
    results.append(expect("the retired-usernames group exists and starts empty",
                          (retired.get("attributes") or {}).get("usernames") == [], retired.get("attributes")))
    status, body = api.call("PATCH", f"/api/v3/core/groups/{retired['pk']}/",
                            {"attributes": {"usernames": ["former"]}})
    assert status == 200, (status, body)

    for name, want_pass, want_text in (
            ("new-member", True, ""),
            ("member-a", False, TAKEN), ("MEMBER-A", False, TAKEN), ("orphan", False, TAKEN),
            ("former", False, TAKEN), ("Former", False, TAKEN),
            ("Existing-User", False, TAKEN), ("", False, "")):
        passing, messages = policy_test(api, me, policy["pk"], name)
        results.append(expect(f"policy engine: {name!r} -> {'pass' if want_pass else 'refuse'}",
                              passing is want_pass and want_text in messages, f"passing={passing} {messages}"))

    flow = api.one("/api/v3/flows/instances/?slug=" + FLOW)
    status, invite = api.call("POST", "/api/v3/stages/invitation/invitations/",
                              {"name": "ci-invite", "single_use": True, "flow": flow["pk"]})
    assert status == 201, (status, invite)
    executor = "/api/v3/flows/executor/" + FLOW + "/?query=" + urllib.parse.quote("itoken=" + invite["pk"])
    status, challenge = api.call("GET", executor, auth=False, opener=api.anon)
    results.append(expect("the invitation opens the prompt", challenge.get("component") == "ak-stage-prompt",
                          f"HTTP {status} {challenge.get('component')}"))
    form = {"component": "ak-stage-prompt", "name": "Synthetic Person", "email": "person@example.test",
            "password": "ci-Synthetic-Passw0rd-xyz", "password_repeat": "ci-Synthetic-Passw0rd-xyz"}
    for taken in ("member-a", "former", "Existing-User"):
        status, reply = api.call("POST", executor, dict(form, username=taken), auth=False, opener=api.anon)
        results.append(expect(f"flow executor: sign-up as {taken!r} is refused on the prompt",
                              reply.get("component") == "ak-stage-prompt" and TAKEN in json.dumps(reply),
                              f"HTTP {status} {json.dumps(reply)[:300]}"))
    results.append(expect("no user was written for a refused name",
                          not api.get("/api/v3/core/users/?username=member-a")["results"]))
    status, reply = api.call("POST", executor, dict(form, username="new-member"), auth=False, opener=api.anon)
    made = api.get("/api/v3/core/users/?username=new-member")["results"]
    results.append(expect("flow executor: a free name moves past the prompt and writes an INACTIVE user",
                          reply.get("component") != "ak-stage-prompt" and len(made) == 1
                          and made[0]["is_active"] is False, f"HTTP {status} {reply.get('component')} {made}"))
    if not all(results):
        raise SystemExit(f"{results.count(False)} of {len(results)} checks failed")
    print(f"all {len(results)} checks passed", flush=True)


def jellyfin_down():
    api = Api()
    policy = api.one("/api/v3/policies/expression/?name=" + POLICY)
    me = api.get("/api/v3/core/users/me/")["user"]["pk"]
    passing, messages = policy_test(api, me, policy["pk"], "another-new-member")
    if not expect("Jellyfin unreachable: sign-up refuses", passing is False and UNAVAILABLE in messages,
                  f"passing={passing} {messages}"):
        raise SystemExit("the policy passed with Jellyfin down")


if __name__ == "__main__":
    {"stub": stub, "checks": checks, "jellyfin-down": jellyfin_down}[sys.argv[1]]()
