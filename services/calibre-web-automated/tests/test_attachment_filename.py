"""Avrana CWA patch tests — the MIME attachment filename (which Kindle turns into the personal
document's title) is a clean "{title}.epub", decoupled from the physical on-disk filename.

Run INSIDE the patched image (it needs the full cps package):

    docker run --rm --entrypoint python3 \
      -v "$PWD/tests:/avrana-tests:ro" \
      avrana-calibre-web-automated:v4.0.8-kindlefilename \
      -m pytest -q /avrana-tests

Covers: normal EPUB delivery, converted (non-epub) delivery, punctuation/Unicode, and missing
metadata (blank title falls back to the physical name so the book still delivers).
"""
import sys

sys.path.insert(0, "/app/calibre-web-automated")

from cps.tasks.mail import TaskEmail  # noqa: E402
from cps import config, helper  # noqa: E402

# Preserve Unicode in sanitized names (matches the deployed setting).
config.config_unicode_filename = 0


def _mime_filename(attachment, attachment_name):
    """Build the MIME message the way TaskEmail does, with the physical read stubbed out, and
    return the filename Kindle would see."""
    t = TaskEmail("Send to eReader", "Author/Book (1)", attachment,
                  {"mail_from": "Avrana <books@example.invalid>", "mail_server_type": 0},
                  "reader@kindle.com", "msg", "body text", id=1,
                  attachment_name=attachment_name)
    t._get_attachment = lambda book_path, filename: b"%PDF-not-really-epub-bytes"
    msg = t.prepare_message()
    part = next(p for p in msg.iter_attachments())
    return part.get_filename()


# --- the core decoupling -------------------------------------------------------------------

def test_mime_name_is_the_clean_display_name_not_the_physical_file():
    # Physical file carries Calibre's "Title - Author" style; the MIME name must be the clean one.
    got = _mime_filename("Cibola Burn - James S. A. Corey.epub", "Cibola Burn.epub")
    assert got == "Cibola Burn.epub"


def test_falls_back_to_attachment_when_no_display_name_given():
    # Unpatched callers (test email etc.) omit attachment_name -> behaviour unchanged.
    got = _mime_filename("Whatever - Author.epub", None)
    assert got == "Whatever - Author.epub"


def test_converted_file_keeps_clean_name_with_converted_extension():
    got = _mime_filename("Cibola Burn - James S. A. Corey.azw3", "Cibola Burn.azw3")
    assert got == "Cibola Burn.azw3"


# --- the name builder: get_valid_filename(title) + ext -------------------------------------

def _built(title, ext=".epub"):
    return helper.get_valid_filename(title) + ext


def test_normal_title():
    assert _built("Cibola Burn") == "Cibola Burn.epub"


def test_punctuation_is_sanitized_but_spaces_kept():
    # Colon is filesystem/AZW-unsafe; it must be replaced, spaces preserved.
    out = _built("A Court of Thorns and Roses: Book 1")
    assert ":" not in out
    assert out.startswith("A Court of Thorns and Roses")
    assert out.endswith("Book 1.epub")


def test_unicode_is_preserved():
    out = _built("Café Society — Émigré Über")
    assert "Café" in out and "Émigré" in out and "Über" in out


def test_missing_title_raises_so_callers_can_fall_back():
    # send_mail/convert wrap this in try/except and fall back to the physical name.
    import pytest
    with pytest.raises(Exception):
        helper.get_valid_filename("")
