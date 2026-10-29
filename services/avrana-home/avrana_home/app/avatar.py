"""The member's photo (Me → My profile; owner, 2026-10-28: "Users should be able to edit their pictures").

Upload → Home's own small square WebP, nothing else kept. The decoder (Pillow) is attack surface, so:

  * only JPEG, PNG and WebP, detected from the bytes (Pillow's own format sniffing, limited to those three), never from
    the file name or the declared type;
  * at most MAX_UPLOAD bytes in, and MAX_PIXELS before decoding (decompression bombs are refused, not decoded); a JPEG
    is decoded at a reduced scale (draft mode), so a 48-megapixel phone photo costs a fraction of its full size;
  * EXIF orientation is applied, then every piece of metadata (location included) is dropped by re-encoding the pixels;
  * centre-cropped to a square (the page's cropper usually sends a square already) and re-encoded at SIZE×SIZE WebP;
  * nothing is logged but a fixed outcome code.

`multipart_file` reads the one file field from a multipart/form-data body with the standard library's email parser,
so no multipart dependency is added; forms.py stays the only module that reads a request body (it passes the bytes).
"""
from __future__ import annotations

import io
from email.parser import BytesParser
from email.policy import HTTP
from typing import Dict, Optional, Tuple

MAX_UPLOAD = 10 * 1024 * 1024          # a phone photo straight from the camera, when the page's cropper can't run
MAX_PIXELS = 50_000_000                # 48 MP phone sensors fit; anything bigger is refused before decoding
SIZE = 256
QUALITY = 82
FORMATS = ("JPEG", "PNG", "WEBP")
CONTENT_TYPE = "image/webp"

# process() outcomes, each a fixed id the page turns into words.
TOO_BIG, NOT_IMAGE, TOO_MANY_PIXELS = "too_big", "not_image", "too_many_pixels"


def profile_result_headers(outcome: str, allowed) -> Dict[str, str]:
    """The 303 back to My profile after a post (post/redirect/get). `outcome` is a fixed id from `allowed`."""
    if outcome not in allowed:
        raise ValueError("not an outcome")
    return {"Location": f"/me/profile?r={outcome}"}


class AvatarError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def process(data: bytes) -> bytes:
    """Upload bytes -> SIZE×SIZE WebP bytes with no metadata. Raises AvatarError(reason)."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not isinstance(data, (bytes, bytearray)) or not data:
        raise AvatarError(NOT_IMAGE)
    if len(data) > MAX_UPLOAD:
        raise AvatarError(TOO_BIG)
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(bytes(data)), formats=FORMATS) as im:
            if im.width * im.height > MAX_PIXELS:
                raise AvatarError(TOO_MANY_PIXELS)
            if im.format == "JPEG":
                im.draft("RGB", (SIZE * 4, SIZE * 4))
            im = ImageOps.exif_transpose(im)
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
            if im.mode == "RGBA":
                ground = Image.new("RGB", im.size, (0x12, 0x12, 0x14))     # Spire Ink behind any transparency
                ground.paste(im, mask=im.getchannel("A"))
                im = ground
            side = min(im.width, im.height)
            left, top = (im.width - side) // 2, (im.height - side) // 2
            im = im.crop((left, top, left + side, top + side)).resize((SIZE, SIZE), Image.LANCZOS)
            out = io.BytesIO()
            im.save(out, format="WEBP", quality=QUALITY, method=4)       # no exif/icc passed: none is written
            return out.getvalue()
    except AvatarError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise AvatarError(TOO_MANY_PIXELS) from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError, MemoryError):
        raise AvatarError(NOT_IMAGE) from None


def multipart_file(content_type: str, body: bytes, file_field: str,
                   text_fields: Tuple[str, ...]) -> Optional[Tuple[Optional[bytes], Dict[str, str]]]:
    """(file bytes or None, {text field: value}) from a multipart/form-data body, or None when it is malformed, has an
    unexpected or repeated field, or more than one file. Text values are at most 256 characters."""
    if not content_type.lower().startswith("multipart/form-data") or "boundary=" not in content_type:
        return None
    try:
        msg = BytesParser(policy=HTTP).parsebytes(b"Content-Type: " + content_type.encode("latin-1") + b"\r\n\r\n" + body)
    except (ValueError, UnicodeError):
        return None
    if not msg.is_multipart():
        return None
    data: Optional[bytes] = None
    texts: Dict[str, str] = {}
    seen = set()
    for part in msg.iter_parts():
        if part.get_content_disposition() != "form-data":
            return None
        name = part.get_param("name", header="content-disposition")
        if not isinstance(name, str) or name in seen or (name != file_field and name not in text_fields):
            return None
        seen.add(name)
        payload = part.get_payload(decode=True) or b""
        if name == file_field:
            data = payload or None              # an empty file input sends a part with no bytes
        else:
            try:
                value = payload.decode("utf-8")
            except UnicodeDecodeError:
                return None
            if len(value) > 256:
                return None
            texts[name] = value
    return data, texts
