"""Synthetic member identities for offline suites. Data only: no behaviour, no real people.

Every name, username and address below is invented; addresses use the reserved example.test
domain. `groups` is the list Authentik would send, joined with "|" in X-authentik-groups. A value
of None means the header is absent altogether (distinct from an empty header, which is "").

Group names mirror the live Authentik groups the portal gates on. They are written out here on
purpose, not imported from the portal, so a change to the portal's tables cannot silently move
the expectation that tests compare it against.
"""

VIDEOS = "avrana-videos"
AUDIOBOOKS = "avrana-audiobooks"
COMICS = "avrana-comics"
BOOKS = "avrana-books"
CONTRIBUTORS = "library-contributors"
ADMIN = "authentik Admins"
BASELINE = "avrana-users"
LEGACY_REQUESTS = "avrana-requests"  # retained in Authentik, gates no service

MEMBER_GROUPS = [VIDEOS, AUDIOBOOKS, COMICS, BOOKS, CONTRIBUTORS]

# name -> groups (list, or None for "header absent")
IDENTITIES = {
    "no_header":      None,
    "empty_header":   [],
    "baseline_only":  [BASELINE],
    "videos":         [BASELINE, VIDEOS],
    "audiobooks":     [BASELINE, AUDIOBOOKS],
    "comics":         [BASELINE, COMICS],
    "books":          [BASELINE, BOOKS],
    "contributors":   [BASELINE, CONTRIBUTORS],
    "legacy_requests": [BASELINE, LEGACY_REQUESTS],
    "all_members":    [BASELINE] + MEMBER_GROUPS,
    "admin_only":     [ADMIN],
    "admin_and_all":  [ADMIN, BASELINE] + MEMBER_GROUPS,
}

# Two distinct fake members for cross-request isolation tests.
MEMBER_A = {"name": "Member A", "username": "member-a", "email": "a@example.test",
            "groups": [BASELINE, VIDEOS]}
MEMBER_B = {"name": "Member B", "username": "member-b", "email": "b@example.test",
            "groups": [BASELINE, BOOKS, COMICS]}
