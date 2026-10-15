"""Accessibility, copy and the manual-refresh fix for every Audible connector page (AVR-359, S1-4).

Uses the existing fixtures only (`conftest.py`): an in-process app with a temporary SQLite file, a fake
companion and header identities. Nothing touches Audible, Amazon, Libation or the network.

Not run by tests/run_offline.py (needs fastapi, jinja2, httpx, itsdangerous, python-multipart, pytest). Run:

    python -m pytest tests/test_a11y.py -q          # from services/avrana-audible-connector/connector
"""
import re

import pytest

from fastapi.testclient import TestClient

import a11y_helpers as A
from app.config import Settings
from app.main import create_app
from conftest import FakeCompanion
from helpers import connect, csrf, hdr

PROGRESS = "/contribute/audible/progress"
GET_PAGES = {"/contribute/audible", "/contribute/audible/library", "/contribute/audible/mode", PROGRESS}


def _select_and_start(client, app, sub, mode="ask", asins=("B000000AA1", "B000000AA2")):
    for a in asins:
        client.post("/contribute/audible/select", data={"asin": a, "csrf_token": csrf(app, sub)},
                    headers=hdr(sub), follow_redirects=False)
    return client.post("/contribute/audible/mode", data={"mode": mode, "csrf_token": csrf(app, sub)},
                       headers=hdr(sub), follow_redirects=False)


def _get(client, sub, path):
    r = client.get(path, headers=hdr(sub), follow_redirects=False)
    assert r.status_code == 200, (path, r.status_code)
    return r


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """One app for the module (the page states are expensive to build): the same construction as
    conftest.py, with a temporary SQLite file, the in-memory fake companion and header identities.
    The scheduler never starts (no `with TestClient`), and nothing leaves the process."""
    settings = Settings(
        companion_base_url="http://companion", companion_token="t", companion_timeout_seconds=5,
        required_group="library-contributors", auth_mode="header",
        oidc_issuer="", oidc_client_id="", oidc_client_secret="", public_base_url="",
        hdr_sub="x-authentik-uid", hdr_username="x-authentik-username",
        hdr_email="x-authentik-email", hdr_groups="x-authentik-groups",
        dev_identity="", db_path=str(tmp_path_factory.mktemp("audible-a11y") / "t.db"),
        secret_key="test-secret-key-000", cookie_secure=False, session_ttl_seconds=1800,
        rate_limit_window_seconds=300, rate_limit_max=10000, scan_interval_hours=24, brand_name="Avrana")
    fake = FakeCompanion()
    app = create_app(settings)
    app.state.companion = fake
    assert app.state.settings.db_path.startswith(str(tmp_path_factory.getbasetemp()))
    return TestClient(app), app, fake


@pytest.fixture(scope="module")
def pages(site):
    """Every page state the connector renders, as responses keyed by state name -> (sub, response)."""
    client, app, fake = site
    out = {}

    def keep(name, sub, resp):
        assert resp.status_code == 200, (name, resp.status_code)
        out[name] = (sub, resp)

    keep("connect, empty", "u1", _get(client, "u1", "/contribute/audible"))

    # sign-in: paste page, then a failed handshake (error banner on the connect form)
    r = client.post("/contribute/audible/start",
                    data={"email": "e1@audible.example", "marketplace": "us", "csrf_token": csrf(app, "e1")},
                    headers=hdr("e1"), follow_redirects=False)
    keep("paste", "e1", r)
    sid = re.search(r'name="session_id" value="([^"]+)"', r.text).group(1)
    fake.fail_complete = True
    r = client.post("/contribute/audible/complete",
                    data={"session_id": sid, "response_url": "https://amazon.example/x", "csrf_token": csrf(app, "e1")},
                    headers=hdr("e1"), follow_redirects=False)
    keep("error", "e1", r)
    fake.fail_complete = False

    # library with books, then an empty library
    connect(client, app, "lib")
    keep("library", "lib", _get(client, "lib", "/contribute/audible/library"))
    connect(client, app, "emp")
    from app.db import connect as dbc
    db = dbc(app.state.settings.db_path)
    db.execute("DELETE FROM book WHERE connection_id=(SELECT id FROM connection WHERE authentik_sub='emp')")
    db.close()
    keep("library, empty", "emp", _get(client, "emp", "/contribute/audible/library"))

    # mode chooser
    connect(client, app, "mod")
    client.post("/contribute/audible/select", data={"asin": "B000000AA1", "csrf_token": csrf(app, "mod")},
                headers=hdr("mod"), follow_redirects=False)
    keep("mode", "mod", _get(client, "mod", "/contribute/audible/mode"))

    # progress: running (companion keeps saying running), failed, succeeded, nothing queued
    connect(client, app, "run")
    _select_and_start(client, app, "run")
    for j in fake.jobs.values():
        if "asin" in j:
            j["status"] = "running"
    keep("progress, running", "run", _get(client, "run", PROGRESS))

    fake.fail_backup_all = True
    connect(client, app, "bad")
    _select_and_start(client, app, "bad")
    fake.fail_backup_all = False
    keep("progress, failed", "bad", _get(client, "bad", PROGRESS))

    connect(client, app, "ok")
    _select_and_start(client, app, "ok")
    keep("progress, succeeded", "ok", _get(client, "ok", PROGRESS))

    connect(client, app, "non")
    # In the default one-time mode, opening the progress page with nothing selected would finish the
    # import and disconnect (existing behaviour, left alone), so this user chooses "ask" first.
    client.post("/contribute/audible/mode", data={"mode": "ask", "csrf_token": csrf(app, "non")},
                headers=hdr("non"), follow_redirects=False)
    keep("progress, nothing queued", "non", _get(client, "non", PROGRESS))

    # one-time import finished: the "disconnected, nothing kept" notice, then the disconnect page
    connect(client, app, "once")
    _select_and_start(client, app, "once", mode="once")
    keep("progress, finished once", "once", _get(client, "once", PROGRESS))

    connect(client, app, "bye")
    r = client.post("/contribute/audible/disconnect", data={"csrf_token": csrf(app, "bye")},
                    headers=hdr("bye"), follow_redirects=False)
    keep("disconnected", "bye", r)
    return out


@pytest.fixture(scope="module")
def docs(pages):
    return {n: A.Doc(r.text) for n, (_s, r) in pages.items()}


@pytest.fixture(scope="module")
def sheet(site, docs):
    client = site[0]
    hrefs = {l.attrs["href"] for dd in docs.values() for l in dd.find("link") if l.attrs.get("rel") == "stylesheet"}
    assert len(hrefs) == 1, "all pages must share one stylesheet"
    r = client.get(hrefs.pop())
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    for dd in docs.values():
        assert dd.css == "", "no inline <style>: one stylesheet only"
    return A.Sheet(r.text), r.text


def each(docs):
    return list(docs.items())


# ---------------------------------------------------------------- the refresh fix
def test_no_page_reloads_itself(pages, docs):
    for name, (_sub, resp) in pages.items():
        A.check_no_auto_navigation(docs[name], resp)
    assert "http-equiv" not in "".join(r.text for _s, r in pages.values()).lower()


@pytest.mark.parametrize("state", ["progress, running", "progress, failed", "progress, succeeded",
                                   "progress, nothing queued"])
def test_progress_has_a_status_region_and_a_manual_refresh_control(state, pages, docs):
    d = docs[state]
    main = d.find("main")[0]
    status = [e for e in main.all_descendants() if e.attrs.get("role") == "status" and "alert" not in e.classes]
    assert status, "no role=status region with the current import status"
    assert status[0].all_text, "status region is empty"
    refresh = [a for a in main.all_descendants() if a.tag == "a" and a.all_text.strip() == "Refresh"]
    assert len(refresh) == 1
    assert refresh[0].attrs["href"] == PROGRESS, "Refresh must be a GET to the same page"
    assert "target" not in refresh[0].attrs and "download" not in refresh[0].attrs
    # not a form, not a button: a plain link (no JavaScript, no POST)
    assert not any(f for f in d.find("form") if f.attrs.get("action") == PROGRESS)
    assert "refresh" not in (refresh[0].attrs.get("onclick") or "")


def test_status_region_says_how_many_are_done_and_failed(pages, docs):
    def status(name):
        return [e for e in docs[name].all if e.attrs.get("role") == "status" and e.attrs.get("id") == "import-status"][0].all_text
    assert status("progress, running") == "0 of 2 imported, 2 still in progress."
    assert status("progress, failed") == "0 of 2 imported, 2 failed."
    assert status("progress, succeeded") == "2 of 2 imported."
    assert status("progress, nothing queued") == "Nothing is queued."


def test_status_words_travel_with_the_rows(pages, docs):
    words = lambda n: sorted(e.own_text for e in docs[n].all if "ps" in e.classes)
    assert words("progress, running") == ["Importing", "Importing"] or words("progress, running") == ["Queued", "Queued"]
    assert words("progress, failed") == ["Failed", "Failed"]
    assert words("progress, succeeded") == ["Imported", "Imported"]


def _snapshot(app):
    """Everything the progress page could change: connection, book and job rows, and the audit count."""
    from app.db import connect as dbc
    db = dbc(app.state.settings.db_path)
    try:
        tables = {t: [tuple(r) for r in db.execute(f"SELECT * FROM {t} ORDER BY 1,2")]
                  for t in ("connection", "book", "job")}
        return tables, db.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
    finally:
        db.close()


@pytest.mark.parametrize("state", ["progress, running", "progress, failed", "progress, succeeded",
                                   "progress, nothing queued"])
def test_following_refresh_twice_changes_nothing_and_starts_no_work(state, site, pages, docs):
    client, app, fake = site
    sub = pages[state][0]
    href = [a for a in docs[state].find("a") if a.all_text.strip() == "Refresh"][0].attrs["href"]
    started = []
    real_backup = fake.backup

    async def counting_backup(profile_id, asin):
        started.append(asin)
        return await real_backup(profile_id, asin)
    fake.backup = counting_backup

    before = _snapshot(app)
    first = client.get(href, headers=hdr(sub), follow_redirects=False)
    second = client.get(href, headers=hdr(sub), follow_redirects=False)
    after = _snapshot(app)
    assert first.status_code == second.status_code == 200
    assert after == before, "following Refresh changed stored state"
    assert started == [], "following Refresh started a download"
    A.check_no_auto_navigation(A.Doc(second.text), second)
    # same page, same rows
    rows = lambda t: [e.own_text for e in A.Doc(t).all if "pt" in e.classes]
    assert rows(first.text) == rows(second.text) == rows(pages[state][1].text)


def test_finished_one_time_import_has_a_status_but_no_refresh_to_nowhere(site, pages, docs):
    """Once the last book is in, one-time mode disconnects and the next GET of the page redirects to the
    connect page (existing behaviour). So that page announces the result and offers no Refresh."""
    client, app, fake = site
    d = docs["progress, finished once"]
    assert [a for a in d.find("a") if a.all_text.strip() == "Refresh"] == []
    assert any("disconnected" in e.all_text for e in d.all if "alert" in e.classes)
    assert any(e.attrs.get("role") == "status" for e in d.all)
    r = client.get(PROGRESS, headers=hdr(pages["progress, finished once"][0]), follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (302, "/contribute/audible")


def test_progress_route_is_still_get_only_and_authenticated(site, pages):
    client, app, fake = site
    sub = pages["progress, running"][0]
    assert client.post(PROGRESS, data={"csrf_token": csrf(app, sub)}, headers=hdr(sub)).status_code == 405
    assert client.get(PROGRESS, headers={"accept": "application/json"}).status_code == 401
    assert client.get(PROGRESS, headers=hdr("outsider", groups="some-other-group")).status_code == 403


# ---------------------------------------------------------------- csrf and forms unchanged
def test_every_form_is_a_post_with_a_verifying_csrf_token(site, pages, docs):
    app = site[1]
    forms = 0
    for name, (sub, _r) in pages.items():
        d = docs[name]
        A.check_csrf_forms(d, lambda tok, sub=sub: app.state.csrf.verify(tok, sub))
        forms += len(d.find("form"))
    assert forms >= 15


def test_state_changing_actions_are_still_the_same_posts(docs):
    actions = {n: sorted(f.attrs["action"] for f in d.find("form")) for n, d in docs.items()}
    assert actions["connect, empty"] == ["/contribute/audible/start"]
    assert actions["paste"] == ["/contribute/audible/complete"]
    assert actions["library"] == ["/contribute/audible/scan", "/contribute/audible/select"]
    assert actions["mode"] == ["/contribute/audible/disconnect", "/contribute/audible/mode"]
    assert actions["progress, failed"] == ["/contribute/audible/disconnect", "/contribute/audible/retry",
                                           "/contribute/audible/retry"]
    assert actions["progress, running"] == ["/contribute/audible/disconnect"]
    assert actions["disconnected"] == []


def test_links_never_point_at_a_state_changing_route(docs):
    post_only = {"/contribute/audible/start", "/contribute/audible/complete", "/contribute/audible/scan",
                 "/contribute/audible/select", "/contribute/audible/retry", "/contribute/audible/disconnect"}
    for name, d in docs.items():
        for a in d.find("a"):
            href = a.attrs.get("href", "")
            assert href not in post_only, f"{name}: link to {href}"
            assert href in GET_PAGES or href.startswith("https://amazon.example/"), (name, href)


@pytest.mark.parametrize("path,data", [
    ("/contribute/audible/retry", {"asin": "B000000AA1"}), ("/contribute/audible/disconnect", {}),
    ("/contribute/audible/scan", {}), ("/contribute/audible/select", {"asin": "B000000AA1"}),
    ("/contribute/audible/mode", {"mode": "ask"}), ("/contribute/audible/start", {"email": "a@b.co", "marketplace": "us"}),
    ("/contribute/audible/complete", {"session_id": "x", "response_url": "https://a.example/x"})])
def test_posts_without_a_token_are_still_rejected(path, data, client, app):
    connect(client, app, "tok")
    assert client.post(path, data=data, headers=hdr("tok"), follow_redirects=False).status_code == 403
    bad = dict(data, csrf_token=csrf(app, "someone-else"))
    assert client.post(path, data=bad, headers=hdr("tok"), follow_redirects=False).status_code == 403


# ---------------------------------------------------------------- structure, labels, roles, copy
def test_document_structure_on_every_state(docs):
    for name, d in each(docs):
        try:
            A.check_document(d)
        except AssertionError as e:
            raise AssertionError(f"{name}: {e}") from None


def test_every_control_has_a_label_and_ids_resolve(docs):
    for name, d in each(docs):
        try:
            A.check_labels(d)
        except AssertionError as e:
            raise AssertionError(f"{name}: {e}") from None


def test_alerts_use_alert_for_errors_and_status_for_notices(docs):
    A.check_alerts(docs["error"])
    assert [b.attrs["role"] for b in docs["error"].all if "alert" in b.classes] == ["alert"]
    assert [b.attrs["role"] for b in docs["progress, finished once"].all if "alert" in b.classes] == ["status"]
    for d in docs.values():
        A.check_alerts(d)


def test_field_hints_are_wired(docs):
    paste = docs["paste"]
    ta = paste.find("textarea")[0]
    ids = {e.attrs["id"]: e for e in paste.all if "id" in e.attrs}
    assert "never stored" in ids[ta.attrs["aria-describedby"]].all_text
    email = docs["connect, empty"].find("input")
    email = [i for i in email if i.attrs.get("type") == "email"][0]
    assert (email.attrs.get("autocomplete"), email.attrs.get("inputmode")) == ("email", "email")
    assert email.attrs.get("autocapitalize") == "none" and email.attrs.get("spellcheck") == "false"


def test_the_mode_choices_are_a_named_group(docs):
    fs = docs["mode"].find("fieldset")[0]
    ids = {e.attrs["id"]: e for e in docs["mode"].all if "id" in e.attrs}
    assert ids[fs.attrs["aria-labelledby"]].tag == "h1"


def test_no_em_or_en_dashes_or_first_person_in_member_visible_copy(docs):
    for name, d in each(docs):
        try:
            A.check_copy(d)
        except AssertionError as e:
            raise AssertionError(f"{name}: {e}") from None


def test_templates_and_stylesheet_hold_no_dash_characters():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    for p in list(root.glob("templates/*.html")) + [root / "static" / "style.css"]:
        assert not re.search("[‒–—―]", p.read_text(encoding="utf-8")), p.name


# ---------------------------------------------------------------- the stylesheet, computed
def test_style_contrast_focus_targets_and_tokens_on_every_state(docs, sheet):
    s, css = sheet
    for name, d in each(docs):
        try:
            A.check_style(d, s)
        except AssertionError as e:
            raise AssertionError(f"{name}: {e}") from None
    A.check_reduced_motion(css)


def test_dividers_keep_quiet_rule_and_controls_use_control_rule(sheet, docs):
    s, _css = sheet
    d = docs["library"]
    assert s.vars["--rule-quiet"] == "#474747" and s.vars["--rule-control"] == "#6e6e6e"
    email = A.Doc('<input type="email">').find("input")[0]
    assert s.declared(email, "border-color") == "#6e6e6e"
    ghost = [b for b in d.find("button") if "ghost" in b.classes][0]
    assert s.declared(ghost, "border-color") == "#6e6e6e"
    book = [li for li in d.find("li") if "book" in li.classes][0]
    assert s.declared(book, "border-bottom") == "1px solid #474747"


def test_one_stylesheet_only(client):
    r = client.get("/static/style.css")
    assert r.status_code == 200
    import pathlib
    static = pathlib.Path(__file__).resolve().parents[1] / "app" / "static"
    assert sorted(p.name for p in static.iterdir()) == ["style.css"]


def test_library_rows_and_checkbox_are_usable_at_390px(docs, sheet):
    s, _ = sheet
    d = docs["library"]
    boxes = [i for i in d.find("input") if i.attrs.get("type") == "checkbox"]
    assert boxes
    for b in boxes:
        lab = [a for a in b.chain()[1:] if a.tag == "label"][0]
        assert "pick" in lab.classes
        assert b.attrs["aria-label"].startswith("Select ")
    book = [li for li in d.find("li") if "book" in li.classes][0]
    assert s.declared(book, "grid-template-columns", mobile=True) == "48px 1fr auto"
    meta = [e for e in d.all if "meta" in e.classes][0]
    assert s.declared(meta, "min-width") == "0" and s.declared(meta, "overflow-wrap") == "anywhere"


# ---------------------------------------------------------------- review follow-ups
def test_one_status_region_per_page(docs):
    for name, d in docs.items():
        regions = [e for e in d.all if e.attrs.get("role") == "status"]
        assert len(regions) <= 1, f"{name}: {len(regions)} role=status regions at load"
        if name.startswith("progress"):
            assert len(regions) == 1, name


def test_nothing_queued_is_said_once_and_there_is_no_empty_list(docs):
    d = docs["progress, nothing queued"]
    assert d.visible_text.count("Nothing") == 1
    assert d.find("ul") == []
    assert [e for e in d.all if "progress" in e.classes] == []


def test_links_that_open_a_new_tab_are_safe_and_described(docs):
    seen = 0
    for name, d in docs.items():
        ids = {e.attrs["id"]: e for e in d.all if "id" in e.attrs}
        for a in d.find("a"):
            if a.attrs.get("target") == "_blank":
                seen += 1
                assert {"noopener", "noreferrer"} <= set(a.attrs.get("rel", "").split()), (name, a.attrs.get("rel"))
                ref = a.attrs.get("aria-describedby", "")
                assert ref in ids and "new tab" in ids[ref].all_text, f"{name}: new-tab link not described"
    assert seen == 1


def test_alert_roles_are_exact_for_error_and_notice(site):
    env = site[1].state.templates.env
    html = env.get_template("connect.html").render(csrf_token="t", marketplaces=[("us", "United States")],
                                                    error="Something failed.", notice="Heads up.")
    d = A.Doc(html)
    roles = {tuple(sorted(e.classes)): e.attrs.get("role") for e in d.all if "alert" in e.classes}
    assert roles == {("alert", "error"): "alert", ("alert", "notice"): "status"}


def test_the_not_updating_hint_goes_with_the_refresh_link(docs):
    for name, d in docs.items():
        if not name.startswith("progress"):
            continue
        has_link = any(a.all_text.strip() == "Refresh" for a in d.find("a"))
        hint = [e for e in d.all if "hint" in e.classes and "does not update by itself" in e.all_text]
        assert bool(hint) == has_link, f"{name}: Refresh link and its explanation must appear together"
        if hint:
            assert "Refresh" in hint[0].all_text


def test_base_text_is_in_rem_and_the_topbar_wraps_at_320px(docs, sheet):
    s, _css = sheet
    d = docs["connect, empty"]
    body = d.find("body")[0]
    assert re.match(r"^1\.0625rem/1\.55 ", s.declared(body, "font") or ""), s.declared(body, "font")
    assert "px" not in (s.declared(body, "font") or "").split(" ")[0]
    top = [e for e in d.all if "topbar" in e.classes][0]
    assert s.declared(top, "display") == "flex" and s.declared(top, "flex-wrap") == "wrap"
