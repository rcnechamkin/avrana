#!/usr/bin/env python3
"""Avrana build-time patch for Calibre-Web-Automated — decouple the outgoing MIME attachment
filename from the physical library filename so Kindle personal-document titles are clean.

WHY: Amazon derives a personal document's displayed title from the *attachment filename* of
the email it receives. Calibre-Web sends the book using its on-disk name — Calibre's
"<title> - <author>.epub" — so the Kindle entry ends up titled "Cibola Burn - James S. A.
Corey". This patch makes the sender pass a separate clean "<title>.epub" as the MIME
attachment name (no author), while the physical file that is READ from disk and the canonical
library file are untouched. The book's embedded metadata (title/author/cover) is unchanged.

HOW: applied at image build time (see ../Dockerfile) by exact string replacement against the
pinned CWA version. Each replacement asserts it matched exactly once, so if a future CWA
upgrade changes these code fragments the build FAILS LOUDLY — that is the signal to review the
upstream diff and refresh the fragments here (see README.md → Upgrade procedure).

Scope of change (4 files, additive):
  cps/tasks/mail.py       TaskEmail gains an `attachment_name` param; the MIME filename +
                          mimetype guess use it, while `attachment` still names the file to READ.
  cps/helper.py           send_mail() (manual + convert-dispatch) computes
                          get_valid_filename(title)+ext and passes it as attachment_name.
  cps/tasks/convert.py    TaskConvert's post-conversion send does the same for the converted file.
  cps/usermanagement.py   verify_password() (OPDS/API HTTP Basic auth) — in LDAP login mode,
                          fall back to the LOCAL password for existing local accounts. Upstream
                          only tries an LDAP bind for existing users, so local service accounts
                          (the read-only Homepage dashboard user, break-glass admin) that aren't
                          in the directory get a 401 on OPDS/API. This restores them without
                          letting LDAP-managed users (no usable local hash) bypass LDAP.
  scripts/kindle_epub_fixer.py  write a self-closing <meta charset="..."/> so fixed XHTML pages stay
                          valid XML (upstream #1473).
"""
from __future__ import annotations

import sys

CWA_ROOT = "/app/calibre-web-automated"

# (relative path, [(old, new), ...]) — every `old` must appear exactly once.
EDITS = {
    "cps/tasks/mail.py": [
        (
            "    def __init__(self, subject, filepath, attachment, settings, recipient, task_message, text, id=0, internal=False):",
            "    def __init__(self, subject, filepath, attachment, settings, recipient, task_message, text, id=0, internal=False, attachment_name=None):",
        ),
        (
            "        self.subject = subject\n        self.attachment = attachment\n        self.settings = settings",
            "        self.subject = subject\n"
            "        self.attachment = attachment\n"
            "        # MIME attachment display name, decoupled from the physical source filename.\n"
            "        # Amazon derives a personal document's title from this outgoing filename, so\n"
            "        # senders pass a clean \"{title}.epub\" here while `attachment` stays the on-disk\n"
            "        # name used to READ the file. Falls back to `attachment` when omitted.\n"
            "        self.attachment_name = attachment_name or attachment\n"
            "        self.settings = settings",
        ),
        (
            "content_type, encoding = mimetypes.guess_type(self.attachment)",
            "content_type, encoding = mimetypes.guess_type(self.attachment_name)",
        ),
        (
            "message.add_attachment(data, maintype=main_type, subtype=sub_type, filename=self.attachment)",
            "message.add_attachment(data, maintype=main_type, subtype=sub_type, filename=self.attachment_name)",
        ),
    ],
    "cps/helper.py": [
        (
            "            converted_file_name = entry.name + '.' + book_format.lower()\n"
            "            link = '<a href=\"/book/{}\">{}</a>'.format(book_id, escape(book.title))",
            "            converted_file_name = entry.name + '.' + book_format.lower()\n"
            "            # Kindle derives a personal document's title from the MIME attachment\n"
            "            # filename, so send \"{title}.epub\" (no author); converted_file_name stays\n"
            "            # the physical on-disk name used to read the file. Fall back to it if the\n"
            "            # title is missing/blank so a metadata-poor book still delivers.\n"
            "            try:\n"
            "                _clean_title = get_valid_filename(book.title)\n"
            "            except Exception:\n"
            "                _clean_title = ''\n"
            "            attachment_name = (_clean_title + '.' + book_format.lower()) if _clean_title else converted_file_name\n"
            "            link = '<a href=\"/book/{}\">{}</a>'.format(book_id, escape(book.title))",
        ),
        (
            "email_text, _('This Email has been sent via Calibre-Web Automated.'), book.id))",
            "email_text, _('This Email has been sent via Calibre-Web Automated.'), book.id,\n"
            "                                                    attachment_name=attachment_name))",
        ),
    ],
    "cps/usermanagement.py": [
        (
            "            if login_result:\n"
            "                [limiter.limiter.storage.clear(k.key) for k in limiter.current_limits]\n"
            "                return user\n"
            "            if error is not None:\n"
            "                log.error(error)\n"
            "        else:",
            "            if login_result:\n"
            "                [limiter.limiter.storage.clear(k.key) for k in limiter.current_limits]\n"
            "                return user\n"
            "            if error is not None:\n"
            "                log.error(error)\n"
            "            # Avrana: fall back to the LOCAL password for existing local accounts (the\n"
            "            # read-only Homepage dashboard user, break-glass admin). In LDAP mode CWA\n"
            "            # otherwise gives local service accounts no way to pass OPDS/API Basic auth\n"
            "            # (they aren't in the directory). LDAP-managed users have no usable local\n"
            "            # password hash, so this never lets them bypass LDAP.\n"
            "            if user.password and check_password_hash(str(user.password), password):\n"
            "                [limiter.limiter.storage.clear(k.key) for k in limiter.current_limits]\n"
            "                return user\n"
            "        else:",
        ),
    ],
    # Upstream bug, not an Avrana preference: cps/editbooks.py deletes a book, then calls
    # CWA_DB().invalidate_duplicate_cache() followed by cwa_db.close() -- but CWA_DB never
    # defines close(). Every deletion therefore raised
    #   'CWA_DB' object has no attribute 'close'
    # which was swallowed by the surrounding try/except and logged as an error. The cache
    # invalidation itself had already run, so the visible symptom was only log noise, but the
    # sqlite connection CWA_DB opens in __init__ (self.con) was left open each time.
    "scripts/cwa_db.py": [
        (
            "    def invalidate_duplicate_cache(self):",
            "    def execute_write(self, query, params=()):\n"
            "        \"\"\"Run a write statement and commit.\n"
            "\n"
            "        cps/tasks/auto_hardcover_id.py::_save_stats() calls this to record each\n"
            "        auto-fetch run, but upstream never defined it, so the INSERT always raised\n"
            "        AttributeError. The surrounding try/except downgraded it to a warning, so the\n"
            "        task reported success while hardcover_auto_fetch_stats stayed empty.\n"
            "\n"
            "        Mirrors the connect/commit style used by the other write helpers here.\n"
            "        \"\"\"\n"
            "        self.cur.execute(query, params)\n"
            "        self.con.commit()\n"
            "        return self.cur.rowcount\n"
            "\n"
            "    def close(self):\n"
            "        \"\"\"Close the sqlite connection opened in __init__.\n"
            "\n"
            "        Callers (cps/editbooks.py) already expect this to exist. Idempotent and\n"
            "        non-throwing: closing twice, or on a half-built instance, must never break a\n"
            "        book deletion.\n"
            "        \"\"\"\n"
            "        try:\n"
            "            con = getattr(self, \"con\", None)\n"
            "            if con is not None:\n"
            "                con.close()\n"
            "        except Exception:\n"
            "            pass\n"
            "        finally:\n"
            "            self.con = None\n"
            "            self.cur = None\n"
            "\n"
            "    def invalidate_duplicate_cache(self):",
        ),
    ],
    "cps/tasks/convert.py": [
        (
            "                    EmailText = N_(u\"%(book)s send to E-Reader\", book=escape(self.title))",
            "                    EmailText = N_(u\"%(book)s send to E-Reader\", book=escape(self.title))\n"
            "                    # MIME attachment name = clean \"{title}.<ext>\" (no author) so Kindle\n"
            "                    # shows the right title; `filename` stays the physical converted file.\n"
            "                    # Fall back to it if the title is missing/blank.\n"
            "                    try:\n"
            "                        _clean_title = helper.get_valid_filename(self.title)\n"
            "                    except Exception:\n"
            "                        _clean_title = ''\n"
            "                    attachment_name = (_clean_title + os.path.splitext(filename)[1]) if _clean_title else filename",
        ),
        (
            "                                                               id=self.book_id,\n"
            "                                                               internal=True)",
            "                                                               id=self.book_id,\n"
            "                                                               internal=True,\n"
            "                                                               attachment_name=attachment_name)",
        ),
    ],
    # Upstream bug crocodilestick/Calibre-Web-Automated#1473 (open, still in v4.0.8): the Kindle EPUB
    # fixer writes an UNCLOSED <meta charset="..."> into XHTML pages. One unclosed tag makes the page
    # invalid XML, so strict renderers (browsers, Komga's EPUB reader, Apple Books) show nothing.
    # A self-closing tag is valid in both XHTML and HTML, so Kindles are unaffected.
    "scripts/kindle_epub_fixer.py": [
        (
            "return meta_charset_pattern.sub(f'<meta charset=\"{charset}\">', content, count=1)",
            "return meta_charset_pattern.sub(f'<meta charset=\"{charset}\"/>', content, count=1)",
        ),
        (
            "content[:insert_at] + f\"\\n    <meta charset=\\\"{charset}\\\">\" + content[insert_at:]",
            "content[:insert_at] + f\"\\n    <meta charset=\\\"{charset}\\\"/>\" + content[insert_at:]",
        ),
        (
            "return f\"<meta charset=\\\"{charset}\\\">\\n\" + content",
            "return f\"<meta charset=\\\"{charset}\\\"/>\\n\" + content",
        ),
    ],
}


def main() -> int:
    for rel, subs in EDITS.items():
        path = f"{CWA_ROOT}/{rel}"
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for i, (old, new) in enumerate(subs):
            if new in text and old not in text:
                print(f"  {rel} edit#{i}: already applied, skipping")
                continue
            count = text.count(old)
            if count != 1:
                sys.stderr.write(
                    f"ERROR {rel} edit#{i}: expected exactly 1 match, found {count}. "
                    f"CWA source changed — refresh avrana-patch (see README.md).\n"
                )
                return 2
            text = text.replace(old, new)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"  patched {rel} ({len(subs)} edits)")
    print("avrana CWA patches applied OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
