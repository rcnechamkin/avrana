"""The page hook for account creation (main._gather + provision.py). Synthetic adapters, no network."""
import unittest

from .support import StubAdapter, make_settings, require_framework


def setUpModule():
    require_framework()


class ProvisionHookTests(unittest.TestCase):
    def _client(self, users, created_ok=True):
        from fastapi.testclient import TestClient
        from avrana_home.app.main import create_app
        from avrana_home.contract import Service
        from avrana_home.provision import ProvisionFailed, Provisioner

        adapter = StubAdapter(users)
        self.creates = []

        class Creator:
            def create(self_inner, username, email):
                self.creates.append(username)
                if not created_ok:
                    raise ProvisionFailed("http_500")
                users[username] = [("a" * 32, "Synthetic Title", 0.5)]    # the upstream now has the account

        self.logs = []
        prov = Provisioner({Service.JELLYFIN: Creator()}, log=lambda **f: self.logs.append(f))
        app = create_app(make_settings(home_sections=True), adapters=[adapter], provisioner=prov)
        adapter.cache = app.state.cache
        return TestClient(app, base_url="http://portal.test")

    @staticmethod
    def _home(client, name="member-a"):
        r = client.get("/home.json", headers={"X-authentik-username": name, "X-authentik-groups": "avrana-videos"})
        return {(s["service"], s["section"]): s["state"] for s in r.json()["sections"]}

    def test_first_visit_creates_the_account_and_shows_the_library(self):
        client = self._client({})
        self.assertEqual(self._home(client), {("jellyfin", "continue"): "ok", ("jellyfin", "recent"): "ok"})
        self.assertEqual(self.creates, ["member-a"])
        self.assertEqual(self.logs, [{"service": "jellyfin", "state": "provisioned", "reason": ""}])
        self._home(client)
        self.assertEqual(self.creates, ["member-a"])          # never again once it exists

    def test_a_failed_create_keeps_not_set_up_yet(self):
        client = self._client({}, created_ok=False)
        self.assertEqual(set(self._home(client).values()), {"not_linked"})
        self._home(client)
        self.assertEqual(self.creates, ["member-a"])          # once per hour, not once per page

    def test_an_existing_account_is_never_touched(self):
        client = self._client({"member-a": [("b" * 32, "Synthetic Title", 0.5)]})
        self.assertEqual(set(self._home(client).values()), {"ok"})
        self.assertEqual(self.creates, [])


if __name__ == "__main__":
    unittest.main()
