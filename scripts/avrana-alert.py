#!/usr/bin/env python3
"""Send one alert e-mail through the stack's SMTP relay. The message body is read from stdin.

Added in remediation Batch 1 (2026-10-03): until now every check on this host could detect a
failure and nobody was told. services-health.sh, boot-verify.sh and avrana-backup.sh call this.

Settings come from services/backups/.env.alert (override: AVRANA_ALERT_ENV), which must be owned
by the calling user and mode 0600. The file is PARSED as KEY=VALUE lines. It is never sourced or
executed, and the password is never printed or logged.

  ALERT_SMTP_HOST   ALERT_SMTP_PORT (587, STARTTLS)   ALERT_SMTP_USER   ALERT_SMTP_PASSWORD
  ALERT_FROM        ALERT_TO (comma-separated)

Usage:
  avrana-alert.py --subject "text" < body      send
  avrana-alert.py --check                      validate the file and the SMTP login, send nothing

Exit: 0 ok · 3 not configured (file absent) · 4 file unsafe or incomplete · 5 SMTP failure
"""
import argparse
import email.message
import email.utils
import os
import pathlib
import smtplib
import socket
import ssl
import sys

DEFAULT_ENV = pathlib.Path(__file__).resolve().parent.parent / "services" / "backups" / ".env.alert"
REQUIRED = ("ALERT_SMTP_HOST", "ALERT_SMTP_USER", "ALERT_SMTP_PASSWORD", "ALERT_FROM", "ALERT_TO")


def load(path):
    st = path.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise PermissionError("settings file must be owned by the caller and mode 0600")
    conf = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        conf[key.strip()] = value
    missing = [k for k in REQUIRED if not conf.get(k)]
    if missing:
        raise KeyError("missing settings: " + ", ".join(missing))
    return conf


def connect(conf):
    port = int(conf.get("ALERT_SMTP_PORT", "587"))
    smtp = smtplib.SMTP(conf["ALERT_SMTP_HOST"], port, timeout=20)
    smtp.ehlo()
    smtp.starttls(context=ssl.create_default_context())
    smtp.ehlo()
    smtp.login(conf["ALERT_SMTP_USER"], conf["ALERT_SMTP_PASSWORD"])
    return smtp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check and not args.subject:
        parser.error("--subject is required unless --check is given")

    path = pathlib.Path(os.environ.get("AVRANA_ALERT_ENV", str(DEFAULT_ENV)))
    if not path.exists():
        print(f"alert: not configured ({path} absent)", file=sys.stderr)
        return 3
    try:
        conf = load(path)
    except (PermissionError, KeyError, OSError, ValueError) as exc:
        print(f"alert: settings rejected: {exc}", file=sys.stderr)
        return 4

    try:
        smtp = connect(conf)
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        # str(exc) for SMTP errors is the server's reply; it does not contain the password.
        print(f"alert: SMTP failure: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        return 5

    try:
        if args.check:
            print("alert: settings valid, SMTP login accepted")
            return 0
        host = socket.gethostname()
        msg = email.message.EmailMessage()
        msg["From"] = conf["ALERT_FROM"]
        msg["To"] = conf["ALERT_TO"]
        msg["Subject"] = f"[{host}] {args.subject}"[:200]
        msg["Date"] = email.utils.formatdate(localtime=True)
        msg["Message-ID"] = email.utils.make_msgid(domain=host)
        body = sys.stdin.read() if not sys.stdin.isatty() else ""
        msg.set_content(body[:20000] or "(no detail)")
        smtp.send_message(msg)
        print("alert: sent")
        return 0
    except (smtplib.SMTPException, OSError) as exc:
        print(f"alert: SMTP failure: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        return 5
    finally:
        try:
            smtp.quit()
        except (smtplib.SMTPException, OSError):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
