"""Close the unclosed <meta charset="..."> that CWA's Kindle EPUB fixer wrote into XHTML pages
(upstream crocodilestick/Calibre-Web-Automated#1473).

usage: python3 epub_charset_fix.py ROOT [--apply] [--backup DIR]

Dry run by default. With --apply, each affected EPUB is copied to --backup (same relative path)
before it is rewritten. Only page entries containing the exact unclosed tag change; every other
zip entry is copied byte for byte, `mimetype` stays first and stored. The new file replaces the
old one atomically and keeps its owner, mode and mtime. Every rewritten page must then parse as XML.
"""
import glob, os, re, shutil, sys, tempfile, zipfile
import xml.dom.minidom as md

TAG = re.compile(rb'<meta charset="([A-Za-z0-9_-]+)">')
PAGE = (".html", ".xhtml", ".htm")


def fix_bytes(data):
    return TAG.sub(rb'<meta charset="\1"/>', data)


def needs(path):
    with zipfile.ZipFile(path) as z:
        return any(n.lower().endswith(PAGE) and TAG.search(z.read(n)) for n in z.namelist())


def rewrite(path):
    st = os.stat(path)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    os.close(fd)
    changed = 0
    try:
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w") as dst:
            for info in src.infolist():
                data = src.read(info)
                if info.filename.lower().endswith(PAGE) and TAG.search(data):
                    data = fix_bytes(data)
                    md.parseString(data)          # raises if the page is still not XML
                    changed += 1
                dst.writestr(info, data, compress_type=info.compress_type)
        os.chown(tmp, st.st_uid, st.st_gid)
        os.chmod(tmp, st.st_mode & 0o7777)
        os.utime(tmp, (st.st_atime, st.st_mtime))
        os.replace(tmp, path)
    except Exception:
        os.unlink(tmp)
        raise
    return changed


def main():
    root = sys.argv[1]
    apply = "--apply" in sys.argv
    backup = sys.argv[sys.argv.index("--backup") + 1] if "--backup" in sys.argv else None
    if apply and not backup:
        sys.exit("--apply needs --backup DIR")
    books = sorted(p for p in glob.glob(os.path.join(root, "*", "*", "*.epub")) if needs(p))
    print(f"{len(books)} books need the fix")
    if not apply:
        return
    for p in books:
        rel = os.path.relpath(p, root)
        dest = os.path.join(backup, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(p, dest)
    print(f"backed up {len(books)} to {backup}")
    pages = sum(rewrite(p) for p in books)
    left = sum(needs(p) for p in books)
    print(f"fixed {pages} pages in {len(books)} books; still unfixed: {left}")


if __name__ == "__main__":
    main()
