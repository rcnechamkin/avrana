"""Redaction, secret non-persistence, path/identifier validation, session expiry."""
import datetime

from helpers import connect, csrf, hdr

from app.security import redact, safe_component, valid_asin, valid_id


def test_redaction_scrubs_urls_and_tokens():
    s = "failed at https://www.amazon.com/ap/maplanding?openid.oa2.authorization_code=SECRET123 now"
    out = redact(s)
    assert "SECRET123" not in out and "[REDACTED]" in out
    assert "Bearer abc.def.ghi" not in redact("Authorization: Bearer abc.def.ghi")
    assert redact('responseUrl="https://x/y?code=zzz"').count("zzz") == 0


def test_response_url_never_persisted(client, app):
    secret_url = "https://amazon.example/maplanding?code=TOPSECRETVALUE999"
    connect(client, app, "alice", response_url=secret_url)
    from app.db import connect as dbc
    conn = dbc(app.state.settings.db_path)
    # Scan the entire DB dump for the secret token — it must appear nowhere.
    dump = "\n".join(row[0] for row in conn.iterdump())
    conn.close()
    assert "TOPSECRETVALUE999" not in dump


def test_asin_and_id_validation():
    assert valid_asin("B000000AA1")
    assert not valid_asin("../../etc/passwd")
    assert not valid_asin("b000000aa1")  # must be upper/num, 10 chars
    assert valid_id("abc-123_XYZ")
    assert not valid_id("../evil")
    assert not valid_id("a/b")


def test_safe_component_neutralizes_paths():
    out = safe_component("../../etc/passwd")
    assert "/" not in out and ".." not in out


def test_invalid_asin_rejected_by_retry(client, app):
    connect(client, app, "alice")
    r = client.post("/contribute/audible/retry",
                    data={"asin": "../secret", "csrf_token": csrf(app, "alice")},
                    headers=hdr("alice"), follow_redirects=False)
    assert r.status_code == 400


def test_expired_auth_session_rejected(client, app):
    import re
    r = client.post("/contribute/audible/start",
                    data={"email": "a@b.co", "marketplace": "us", "csrf_token": csrf(app, "alice")},
                    headers=hdr("alice"), follow_redirects=False)
    sid = re.search(r'name="session_id" value="([^"]+)"', r.text).group(1)
    # Force expiry in the DB.
    from app.db import connect as dbc
    conn = dbc(app.state.settings.db_path)
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
    conn.execute("UPDATE auth_session SET expires_at=? WHERE id=?", (past, sid))
    conn.close()
    r2 = client.post("/contribute/audible/complete",
                     data={"session_id": sid, "response_url": "https://amazon.example/x",
                           "csrf_token": csrf(app, "alice")},
                     headers=hdr("alice"), follow_redirects=False)
    assert r2.status_code == 400
