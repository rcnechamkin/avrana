"""RC1 finding S1: the enrollment username policy, checked inside a REAL throwaway Authentik.

Run by tests/authentik_enrollment_live.sh (CI workflow enrollment-policy.yml), never against production:

  stub           stand-ins at 10.0.0.218: Jellyfin on 8096 and Komga on 25600. Each takes only the run's key, and they
                 count what they were asked to create (GET :8096/__seen, counts only)
  checks         apply avrana-enrollment.yaml, then ask Authentik's own policy engine and flow executor
  provision      AVR-791: an enrollment through the login stage, so jellyfin-create and komga-create run for real
  refused        a key file is absent or holds a key Komga refuses: sign-up must refuse on the prompt, nobody written
  gap            the race the prompt cannot stop (file gone after the prompt): loud, no account made, no key shown
  jellyfin-down  the same policy with the stub stopped: sign-up must refuse, not pass

Standard library only. Synthetic names; every credential is generated per run by the shell script.
"""
import http.cookiejar
import http.server
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

POLICY = "avrana-enrollment-username-available"
MINT_POLICY = "avrana-komga-key-mint"
FLOW = "avrana-invite"
BLUEPRINT_PATH = "avrana/avrana-enrollment.yaml"
GROUPS = ["avrana-users", "avrana-audiobooks", "avrana-comics", "avrana-books", "avrana-videos", "avrana-requests"]
TAKEN = "That username is taken"
UNAVAILABLE = "briefly unavailable"


def stub():
    jellyfin_key, komga_key = os.environ["JF_KEY"], os.environ["KOMGA_KEY"]
    users = [u for u in os.environ["JF_USERS"].split(",") if u]
    seen = {"jellyfin_new": 0, "komga_new": 0, "wrong_key": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def reply(self, status, body=None):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if body is not None:
                self.wfile.write(json.dumps(body).encode())

        def authorised(self):
            komga = self.server.server_address[1] == 25600
            ok = (self.headers.get("X-API-Key") == komga_key if komga
                  else self.headers.get("X-MediaBrowser-Token") == jellyfin_key)
            if not ok:
                seen["wrong_key"] += 1
                self.reply(401)
            return ok

        def do_GET(self):
            if self.path == "/__seen":
                self.reply(200, seen)
            elif self.path not in ("/Users", "/api/v2/users"):
                self.reply(404)
            elif self.authorised():
                self.reply(200, [{"Name": n, "Id": f"{i:032x}"} for i, n in enumerate(users)]
                           if self.path == "/Users" else [])

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path not in ("/Users/New", "/api/v2/users"):
                self.reply(404)
            elif self.authorised():
                seen["jellyfin_new" if self.path == "/Users/New" else "komga_new"] += 1
                self.reply(200, {"Id": "0" * 32, "Policy": {}})

        def log_message(self, *args):
            pass
    komga = http.server.ThreadingHTTPServer(("0.0.0.0", 25600), Handler)
    threading.Thread(target=komga.serve_forever, daemon=True).start()
    http.server.ThreadingHTTPServer(("0.0.0.0", 8096), Handler).serve_forever()


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


def sentinels():
    values = [v for v in os.environ["SENTINELS"].split(",") if v]
    assert len(values) == 2
    return values


def no_sentinel_in_any_expression(api):
    """The admin API returns the stored text of every expression policy: neither generated key may be in it."""
    rows, page = [], 1
    while page:
        body = api.get(f"/api/v3/policies/expression/?page_size=100&page={page}")
        rows += body["results"]
        page = body["pagination"]["next"]
    carrying = sorted(r["name"] for r in rows if any(v in r["expression"] for v in sentinels()))
    return expect(f"no generated key in the text of any of {len(rows)} expression policies", not carrying,
                  f"carrying a key: {carrying}")


def seen():
    with urllib.request.urlopen("http://10.0.0.218:8096/__seen", timeout=10) as r:
        return json.loads(r.read())


def sign_up(api, flow, username, **invitation):
    """A fresh visitor, through a fresh invitation, up to the answer to the prompt. Returns that answer."""
    visitor = Api()
    status, invite = api.call("POST", "/api/v3/stages/invitation/invitations/",
                              dict({"name": "ci-" + username, "single_use": True, "flow": flow["pk"]}, **invitation))
    assert status == 201, (status, invite)
    executor = "/api/v3/flows/executor/" + FLOW + "/?query=" + urllib.parse.quote("itoken=" + invite["pk"])
    status, challenge = visitor.call("GET", executor, auth=False, opener=visitor.anon)
    assert challenge.get("component") == "ak-stage-prompt", (status, challenge.get("component"))
    form = {"component": "ak-stage-prompt", "username": username, "name": "Synthetic Person",
            "email": username + "@example.test", "password": "ci-Synthetic-Passw0rd-xyz",
            "password_repeat": "ci-Synthetic-Passw0rd-xyz"}
    return visitor.call("POST", executor, form, auth=False, opener=visitor.anon)[1]


LIBRARIES = {"fixed_data": {"avrana_groups": "avrana-users,avrana-videos,avrana-comics"}}


def provision():
    """The email stage cannot finish on a network with no mail host, and the provisioning policies sit after it. This
    throwaway copy of the flow loses that one binding, so the login stage's policies run as they do after an email link.
    The user stays inactive, so the login itself is refused: what counts is what reached the stand-ins, with which key."""
    api = Api()
    flow = api.one("/api/v3/flows/instances/?slug=" + FLOW)
    binding = api.one(f"/api/v3/flows/bindings/?target={flow['pk']}&order=30")
    status, body = api.call("DELETE", f"/api/v3/flows/bindings/{binding['pk']}/")
    assert status == 204, (status, body)
    before = seen()
    sign_up(api, flow, "provisioned-member", **LIBRARIES)
    after = seen()
    results = [
        expect("jellyfin-create reached Jellyfin with the key from the file",
               after["jellyfin_new"] == before["jellyfin_new"] + 1, f"{before} -> {after}"),
        expect("komga-create reached Komga with the key from the file",
               after["komga_new"] == before["komga_new"] + 1, f"{before} -> {after}"),
        expect("no stand-in saw a wrong key", after["wrong_key"] == 0, after),
        no_sentinel_in_any_expression(api)]
    if not all(results):
        raise SystemExit("provisioning did not use the key files")


def refused():
    api = Api()
    flow = api.one("/api/v3/flows/instances/?slug=" + FLOW)
    policy = api.one("/api/v3/policies/expression/?name=" + POLICY)
    me = api.get("/api/v3/core/users/me/")["user"]["pk"]
    label, name = sys.argv[2], "refused-" + sys.argv[2]
    before = seen()
    passing, messages = policy_test(api, me, policy["pk"], name)
    reply = sign_up(api, flow, name, **LIBRARIES)
    after = seen()
    results = [
        expect(f"{label}: the policy refuses and says try again", passing is False and UNAVAILABLE in messages,
               f"passing={passing} {messages}"),
        expect(f"{label}: the flow stays on the prompt with the same message",
               reply.get("component") == "ak-stage-prompt" and UNAVAILABLE in json.dumps(reply),
               json.dumps(reply)[:300]),
        expect(f"{label}: nobody was written", not api.get("/api/v3/core/users/?username=" + name)["results"]),
        expect(f"{label}: no account was asked for", (after["jellyfin_new"], after["komga_new"])
               == (before["jellyfin_new"], before["komga_new"]), f"{before} -> {after}"),
        expect(f"{label}: nothing about the path reaches the member",
               "/run/" not in json.dumps(reply) and "/run/" not in messages)]
    if not all(results):
        raise SystemExit(f"{label}: sign-up was not refused cleanly")


def gap():
    api = Api()
    flow = api.one("/api/v3/flows/instances/?slug=" + FLOW)
    stage = api.one("/api/v3/stages/prompt/stages/?name=avrana-enrollment-prompt")
    status, body = api.call("PATCH", f"/api/v3/stages/prompt/stages/{stage['pk']}/", {"validation_policies": []})
    assert status == 200, (status, body)
    before = seen()
    sign_up(api, flow, "gap-member", **LIBRARIES)
    after = seen()
    events = api.get("/api/v3/events/events/?action=policy_exception&page_size=50")["results"]
    results = [expect("file gone after the prompt: no account was asked for",
                      (after["jellyfin_new"], after["komga_new"]) == (before["jellyfin_new"], before["komga_new"]),
                      f"{before} -> {after}")]
    for name in ("avrana-jellyfin-create", "avrana-komga-create"):
        pk = str(api.one("/api/v3/policies/expression/?name=" + name)["pk"]).replace("-", "")
        mine = [e for e in events if str(e["context"].get("policy_uuid", "")).replace("-", "") == pk]
        results.append(expect(f"{name}: a policy_exception event says so", len(mine) >= 1, len(events)))
        results.append(expect(f"{name}: and it holds no key", not any(v in json.dumps(mine) for v in sentinels())))
    if not all(results):
        raise SystemExit("the gap was silent")


def checks():
    api = Api()
    apply_blueprint(api)
    results = [no_sentinel_in_any_expression(api)]
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
    # S-01: the Komga key mint policy is applied, bound to the login stage after komga-create, and passes (never
    # fails enrollment) when it has nothing to do: here no flow plan and no AVRANA_HOME_KEY_INTAKE_TOKEN.
    mint = api.one("/api/v3/policies/expression/?name=" + MINT_POLICY)
    login = api.one(f"/api/v3/flows/bindings/?target={flow['pk']}&order=40")
    bound = api.get("/api/v3/policies/bindings/?policy=" + str(mint["pk"]))["results"]
    results.append(expect("the Komga key mint policy is bound to the login stage at order 2",
                          [(str(b.get("target")), b.get("order")) for b in bound] == [(str(login["pk"]), 2)], bound))
    status, body = api.call("POST", f"/api/v3/policies/all/{mint['pk']}/test/", {"user": me, "context": {}})
    results.append(expect("the Komga key mint policy passes when it has nothing to do",
                          status == 200 and body.get("passing") is True, f"HTTP {status} {body}"))
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
    {"stub": stub, "checks": checks, "provision": provision, "refused": refused, "gap": gap,
     "jellyfin-down": jellyfin_down}[sys.argv[1]]()
