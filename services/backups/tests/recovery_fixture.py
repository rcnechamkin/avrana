"""A disposable host for test_recovery_proof.py: the real scripts, a fixture tree, fake tools, a real SMTP conversation.

Nothing here touches production, Docker, rclone or the network beyond loopback. avrana-backup.sh is copied with its
absolute paths rewritten to the fixture (`install`), so what runs is the production script's logic, not a model of it.
`docker` is fake_docker.py, which also stands in for the rclone container. `zstd` is the real one when present; otherwise
a pass-through shim, and backup-recovery-proof.yml sets AVRANA_REQUIRE_REAL_TOOLS=1 so CI cannot fall back to that.
"""
import json
import os
import pathlib
import shutil
import smtplib  # noqa: F401  (documents the client side the sink speaks to)
import socket
import sqlite3
import ssl
import stat
import subprocess
import sys
import threading

TESTS = pathlib.Path(__file__).resolve().parent
BACKUPS = TESTS.parent
ROOT = BACKUPS.parents[1]
SMTP_PASSWORD = "fixture-smtp-password-per-run"
BINDINGS = {"format": "avrana-identity-bindings", "version": 2, "initialized": "2026-10-29T00:00:00Z",
            "bindings": {"member-a": "a" * 64, "member-b": "b" * 64}, "released": {}}
MEMBER_KEYS = {"a@fixture.test": "0123456789abcdef0123456789abcdef", "b@fixture.test": "fedcba9876543210fedcba9876543210"}
KEY_IDS = {"a@fixture.test": "0ABC", "b@fixture.test": "0DEF"}
REWRITES = (
    ('REPO="/home/cody/avrana"', 'REPO="{repo}"'),
    ('/home/cody/docker', '{docker}'),
    ('/mnt/avrana_media/calibre-library', '{array}/calibre-library'),
    ('/etc/systemd/system', '{etc}/systemd/system'),
    ('/etc/fstab', '{etc}/fstab'),
    ('/etc/docker/daemon.json', '{etc}/docker/daemon.json'),
)
SERVICE_FILES = """
services/audiobookshelf/metadata/items/one/metadata.json
services/audiobookshelf/metadata/authors/one.json
services/bookstack/.env
services/bookstack/config/www/uploads/a
services/bookstack/config/www/images/a
services/bookstack/config/www/files/a
services/shelfarr/data/.encryption_keys
services/shelfarr/data/.secret_key_base
services/omnibus/.env
services/komga/config/application.yml
services/beszel/data/data.db
services/beszel/agent-data/a
services/beszel/secrets/agent-key
services/beszel/secrets/agent-token
services/calibre-web-automated/config/.key
services/libation/config/libation-master.key
services/libation/config/AccountsSettings.json
services/libation/config/Settings.json
services/shelfmark/config/settings.json
services/shelfmark/config/.flask_secret
services/mylar3/config.ini
filing_cabinet/a.yaml
kern_sync/a.yaml
kern_secrets/a
services/recyclarr/config/state/a
""".split()
DATABASES = """
services/audiobookshelf/config/absdatabase.sqlite
services/avrana-audible-connector/data/connector.db
services/shelfarr/data/production.sqlite3
services/omnibus/config/omnibus.db
services/komga/config/database.sqlite
services/calibre-web-automated/config/app.db
services/calibre-web-automated/config/cwa.db
services/libation/config/LibationContext.db
services/shelfmark/config/users.db
services/mylar3/mylar.db
""".split()


def have_real_tools():
    return bool(shutil.which("zstd"))


def write(path, text="x\n", mode=None):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    if mode is not None:
        os.chmod(path, mode)
    return path


def database(path):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE fixture (id INTEGER)")
    connection.execute("INSERT INTO fixture VALUES (1)")
    connection.commit()
    connection.close()


class Host:
    """One disposable host under `root`. Attributes name its trees."""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        for name in ("repo", "docker", "home", "etc", "array", "bin", "state", "deploy", "remote", "ha"):
            setattr(self, name, self.root / name)
            getattr(self, name).mkdir()
        self.backups = self.array / ".backups/avrana"
        self.offhost_state = self.array / ".backups/OFFHOST_LAST_RUN.json"
        self.backups.mkdir(parents=True)
        self.alert_env = self.repo / "services/backups/.env.alert"
        self.tools()
        self.sources()
        self.install()

    def tool(self, name, body):
        write(self.bin / name, "#!/usr/bin/env bash\n" + body + "\n", 0o755)

    def tools(self):
        self.tool("docker", f'exec "{sys.executable}" "{TESTS / "fake_docker.py"}" "$@"')
        self.tool("mountpoint", '[[ ! -e "$FIXTURE_ROOT/array-unmounted" ]]')
        self.tool("systemctl", '''case "$*" in
  *list-unit-files*) echo "avrana-backup.timer enabled" ;;
  *is-active*) grep -qx "$3" "$FIXTURE_ROOT/dead-timers" 2>/dev/null && { echo inactive; exit 3; }; echo active ;;
  *is-enabled*) grep -qx "$3" "$FIXTURE_ROOT/dead-timers" 2>/dev/null && { echo disabled; exit 1; }; echo enabled ;;
esac''')
        self.tool("python3", f'exec "{sys.executable}" "$@"')
        if not have_real_tools():
            self.tool("zstd", '''case "$1" in
  -dc) cat "$2" ;;
  *) out=""; while (( $# )); do [[ "$1" == -o ]] && { out="$2"; shift; }; shift; done; cat > "$out" ;;
esac''')

    def sources(self):
        lines = (BACKUPS / "required-artifacts.txt").read_text(encoding="utf-8").splitlines()
        for rel in SERVICE_FILES:
            write(self.repo / rel)
        for rel in DATABASES:
            database(self.repo / rel)
        for line in lines:                                 # everything stack-config must hold, from the real list
            parts = line.strip().split("|")
            if len(parts) == 4 and parts[1] in ("member", "nonempty") and parts[2].startswith("stack-config/"):
                if not (self.repo / parts[3]).exists():
                    write(self.repo / parts[3])
            elif len(parts) == 3 and parts[1] == "file" and parts[2].startswith("systemd/system/"):
                write(self.etc / "systemd/system" / parts[2][len("systemd/system/"):])
            elif len(parts) == 3 and parts[1] == "file" and parts[2].startswith("systemd/user/"):
                write(self.home / ".config/systemd/user" / parts[2][len("systemd/user/"):])
        state = self.repo / "services/avrana-home/state"
        write(state / "identity_bindings.json", json.dumps(BINDINGS), 0o600)
        write(state / "identity_bindings.json.lock", "", 0o600)
        write(state / "komga_member_keys", json.dumps(MEMBER_KEYS), 0o600)
        write(state / "komga_member_keys.ids", json.dumps(KEY_IDS), 0o600)
        write(state / "komga_member_keys.lock", "", 0o600)
        for service in ("radarr", "sonarr", "prowlarr"):
            database(self.docker / service / f"{service}.db")
            write(self.docker / service / "config.xml")
        database(self.docker / "seerr/config/db/db.sqlite3")
        write(self.docker / "seerr/config/settings.json")
        database(self.docker / "jellyfin/config/data/jellyfin.db")
        for rel in ("config/system.xml", "config/network.xml", "config/encoding.xml", "metadata/a"):
            write(self.docker / "jellyfin/config" / rel)
        database(self.array / "calibre-library/metadata.db")
        for name in ("config.yml", "1f77ba21-71ca-4360-8861-28b0a5a30f6f.json", "cert.pem"):
            write(self.home / ".cloudflared" / name)
        write(self.home / ".sabnzbd/sabnzbd.ini")
        database(self.home / ".sabnzbd/admin/history1.db")
        write(self.etc / "fstab")
        for rel in ("configuration.yaml", "secrets.yaml", ".storage/auth", ".storage/auth_provider.homeassistant",
                    ".storage/core.config", ".storage/core.config_entries", ".storage/core.device_registry",
                    ".storage/core.entity_registry", ".storage/esphome.encryption_keys"):
            write(self.ha / "config" / rel)
        database(self.root / "ha-recorder.db")

    def install(self, script=None):
        """The real scripts, with only their absolute paths moved, and a hash list that matches them."""
        for rel in ("services/backups", "scripts"):
            (self.repo / rel).mkdir(parents=True, exist_ok=True)
        for name in ("offhost-backup.py", "verify-required.py", "restore-test.py", "restore-home-state.py",
                     "backup-guard.py", "restore-map.txt", "restore-test.sh", "offhost-setup.sh",
                     "offhost-verify-secrets.sh", "README.md"):
            if (BACKUPS / name).exists():
                shutil.copy(BACKUPS / name, self.repo / "services/backups" / name)
        shutil.copy(ROOT / "scripts/avrana-alert.py", self.repo / "scripts/avrana-alert.py")
        text = (BACKUPS / "avrana-backup.sh").read_text(encoding="utf-8")
        for old, new in REWRITES:
            assert old in text, old
            text = text.replace(old, new.format(repo=self.repo, docker=self.docker, array=self.array, etc=self.etc))
        write(self.repo / "services/backups/avrana-backup.sh", text, 0o755)
        # Thresholds meant for the real library, reduced to fit a fixture. Nothing else in the list changes.
        required = []
        for line in (BACKUPS / "required-artifacts.txt").read_text(encoding="utf-8").splitlines():
            parts = line.split("|")
            required.append("|".join(parts[:4] + ["1"]) if len(parts) == 5 and parts[1] == "mincount" else line)
        write(self.repo / "services/backups/required-artifacts.txt", "\n".join(required) + "\n")
        self.rehash()

    def rehash(self):
        guard = self.repo / "services/backups/backup-guard.py"
        if not guard.exists():
            return
        names = [f for f in ("scripts/avrana-alert.py", *(f"services/backups/{n}" for n in (
            "avrana-backup.sh", "backup-guard.py", "offhost-backup.py", "offhost-setup.sh", "offhost-verify-secrets.sh",
            "required-artifacts.txt", "restore-home-state.py", "restore-map.txt", "restore-test.py", "restore-test.sh",
            "verify-required.py"))) if (self.repo / f).exists()]
        import hashlib
        write(self.repo / "services/backups/INSTALLED-FILES.sha256", "".join(
            f"{hashlib.sha256((self.repo / n).read_bytes()).hexdigest()}  {n}\n" for n in names))

    def env(self, **extra):
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "HOME": str(self.home),
               "FIXTURE_ROOT": str(self.root), "AVRANA_REPO": str(self.repo),
               "AVRANA_BACKUP_ROOT": str(self.backups), "AVRANA_ARRAY_ROOT": str(self.array),
               "AVRANA_BACKUP_GUARD": "1", "AVRANA_BACKUP_MIN_FREE_GB": "0", "AVRANA_STATE_DIR": str(self.state),
               "AVRANA_DEPLOY_ROOT": str(self.deploy), "AVRANA_ALERT_ENV": str(self.alert_env),
               "AVRANA_OFFHOST_STATE": str(self.offhost_state), "AVRANA_RCLONE_CONF": str(self.root / "rclone.conf"),
               "AVRANA_OFFHOST_DAILY": "daily:", "AVRANA_OFFHOST_PINNED": "pinned:",
               "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}
        if "SSL_CERT_FILE" in os.environ:
            env["SSL_CERT_FILE"] = os.environ["SSL_CERT_FILE"]
        env.update(extra)
        return env

    def backup(self, timeout=120, **extra):
        return subprocess.run(["bash", str(self.repo / "services/backups/avrana-backup.sh")], env=self.env(**extra),
                              capture_output=True, text=True, timeout=timeout)

    def script(self, *arguments, stdin=None, **extra):
        return subprocess.run([sys.executable, *map(str, arguments)], env=self.env(**extra), input=stdin,
                              capture_output=True, text=True, timeout=120)

    def configure_alerts(self, sink, password=SMTP_PASSWORD):
        write(self.alert_env, f"ALERT_SMTP_HOST=localhost\nALERT_SMTP_PORT={sink.port}\nALERT_SMTP_USER=avrana-mail\n"
                              f"ALERT_SMTP_PASSWORD={password}\nALERT_FROM=alerts@fixture.test\nALERT_TO=owner@fixture.test\n",
              stat.S_IRUSR | stat.S_IWUSR)

    def last_run(self):
        return json.loads((self.backups / "LAST_RUN.json").read_text(encoding="utf-8"))

    def transport(self):
        return json.loads((self.state / "alert-transport.json").read_text(encoding="utf-8"))

    def runs(self):
        return sorted(p.name for p in self.backups.iterdir() if p.is_dir())


class SmtpSink:
    """A real SMTP conversation on loopback: EHLO, STARTTLS with a throwaway certificate, AUTH PLAIN or LOGIN, DATA.

    Standard library only, so production code runs unchanged (TLS verification stays on; the certificate is trusted
    through SSL_CERT_FILE). Wrong password: 535, which is what a rotated SMTP2GO password looks like.
    """

    def __init__(self, directory, password=SMTP_PASSWORD):
        self.password, self.messages, self.logins = password, [], []
        self.certificate = pathlib.Path(directory) / "sink.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1", "-keyout", str(self.certificate),
                        "-out", str(self.certificate)], check=True, capture_output=True)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(self.certificate)
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def close(self):
        self.listener.close()

    def serve(self):
        while True:
            try:
                connection, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self.session, args=(connection,), daemon=True).start()

    def session(self, connection):
        try:
            self.converse(connection)
        except (OSError, ssl.SSLError, ValueError):
            pass
        finally:
            connection.close()

    def converse(self, connection):
        stream = connection.makefile("rb")

        def say(text):
            connection.sendall((text + "\r\n").encode())

        say("220 fixture ESMTP")
        secure = authed = False
        while True:
            line = stream.readline().decode("utf-8", "replace").strip()
            if not line:
                return
            verb = line.split()[0].upper()
            if verb == "EHLO":
                say("250-fixture")
                say("250 AUTH PLAIN LOGIN" if secure else "250 STARTTLS")
            elif verb == "STARTTLS":
                say("220 go ahead")
                connection = self.context.wrap_socket(connection, server_side=True)
                stream = connection.makefile("rb")
                secure = True
            elif verb == "AUTH":
                import base64
                parts = line.split()
                if parts[1].upper() == "PLAIN":
                    secret = base64.b64decode(parts[2]).split(b"\0")[-1].decode()
                else:                                      # LOGIN
                    say("334 VXNlcm5hbWU6")
                    stream.readline()
                    say("334 UGFzc3dvcmQ6")
                    secret = base64.b64decode(stream.readline().strip()).decode()
                authed = secret == self.password
                self.logins.append(authed)
                say("235 ok" if authed else "535 authentication failed")
            elif verb == "MAIL" or verb == "RCPT":
                say("250 ok" if authed else "530 authentication required")
            elif verb == "DATA":
                say("354 go")
                body = b""
                while True:
                    chunk = stream.readline()
                    if chunk in (b".\r\n", b""):
                        break
                    body += chunk
                self.messages.append(body.decode("utf-8", "replace"))
                say("250 queued")
            elif verb == "QUIT":
                say("221 bye")
                return
            else:
                say("250 ok")
