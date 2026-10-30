# Media 2.0 closed-beta acceptance packet (owner-executed)

Status: **not run. Written 2026-10-29 for the pre-closed-beta quality sprint; supersedes the RC1 checklist on
draft PR #165 (same journeys A–F, now with the two-member privacy test, the support/recovery tests, expected
behaviours per step and a results template).** Build under test: the revision printed by
`scripts/deploy-home-beta.sh` (today `2cb228f`, container label `working_dir=home-2cb228f`). Scenario detail and
synthetic members: [MEDIA-2.0-MEMBER-SCENARIOS.md](MEDIA-2.0-MEMBER-SCENARIOS.md).

The agent prepared this and can prepare evidence-capture commands, but **cannot observe a physical device**. Nothing
below is passed until the owner writes the result in the template.

## 0. Before you start (dependency order)

| Step | Needs | Done when |
|---|---|---|
| 0.1 Pick two **non-admin** tester accounts, T1 and T2, with different library groups (T2 without `avrana-comics`, say). Add both to `avrana-beta` and to `HOME_ALLOWED_USERS` (restart Home for the env change: a routine deploy). | owner | both names appear in `docker exec avrana-home-beta python3 -m avrana_home.identity_bindings count` output as bound (or bind on first sign-in) |
| 0.2 E-mail works (O1, AVR-346): one invitation, one reset mail, one alert arrived | owner, `docs/runbooks/m0-smtp2go-email.md` | three timestamps in `docs/findings/` |
| 0.3 akadmin MFA on (O2, AVR-347) | owner | MFA prompt seen; recovery code tested |
| 0.4 A restore drill done this week (O3, AVR-350) | owner | one restored file opened |
| 0.5 Rollback material at hand: `docker tag avrana-home-live:pre-<sha> avrana-home-live:local` then `docker compose up -d --no-build` in the previous export folder | from the deploy record | the two commands copied into your notes |

## 1. Severity (used in every result row)

- **S0 blocker**: someone sees another member's title, cover, progress or request; cannot sign in or recover; a library
  they are entitled to is unreachable with no explanation. Stops the beta until fixed and re-tested.
- **S1 major**: a journey fails but a documented fallback works; the wrong item opens; progress is wrong by more than
  about a minute / a page; a request is lost or duplicated.
- **S2 minor**: confusing copy, slow (over 3 s to a usable Home on phone Wi-Fi), a layout fault, a focus fault with a
  workaround.

"Opening a link does not prove playback": a handoff passes only when the media starts in the right app at the right
item with the member's own progress.

## 2. Journeys (run as T1 unless stated; phone first, then TV)

### A. First-time member
| Step | Do | Expect |
|---|---|---|
| A1 | Send T1 an invitation from Authentik | mail arrives in under 10 min; the link opens the enrollment flow |
| A2 | Set a password; sign in | lands on Home (not a blank Authentik page, not a 404); the Home shows the member's first name or username on Me |
| A3 | Look at Home without touching anything | the hero and rails show only libraries T1 has; no library T1 lacks is named anywhere (check Home, Library chips, Search placeholder, Help) |
| A4 | Open Library → one library → one item → the single action button | the upstream app (or its web page) opens on **that** item and plays/renders |
| A5 | Come back to Avrana (back gesture / switch app) | Home is where you left it (scroll position, same tab); nothing re-signs-in |

### B. Returning member, Continue and progress
| Step | Do | Expect |
|---|---|---|
| B1 | In Jellyfin, watch 2 min of something and stop; in Audiobookshelf, listen 2 min; in Komga, read 3 pages | — |
| B2 | Reload Home | Continue shows those three, most recent activity first; the progress words match (minutes left / page / percent) |
| B3 | Tap Resume on each | resumes within ~1 min / 1 page of where you stopped, in the right app |
| B4 | Finish one item in the upstream app; reload Home | it leaves Continue; Up next (TV) / On Deck (comics) offers the next one, if there is one |

### C. Cross-media search
| Step | Do | Expect |
|---|---|---|
| C1 | Search one word that matches a film, a show, a book, an audiobook and a comic | results from every library T1 has, grouped; none from a library T1 lacks |
| C2 | Search nonsense | "no results" with the request routes T1 is allowed to use, nothing else |
| C3 | Open a result → action | the right item opens (compare the title and year/author) |
| C4 | Search while one library is stopped (owner: `docker stop komga` for 3 min, then start it) | results from the others; the stopped library is named as unavailable, not silently empty |

### D. Account, recovery, session
| Step | Do | Expect |
|---|---|---|
| D1 | Me → Sign out | you are signed out of Avrana (back button does not show member pages) |
| D2 | Sign in again | Home |
| D3 | "Forgot password" from the sign-in page | reset mail arrives; the link sets a new password; you land on Home |
| D4 | Leave the phone locked for longer than the session lifetime (owner: note the Authentik session length), then open the installed app | a sign-in page, then back to Home — no blank page, no error page, no dead end |
| D5 | Me → Account | shows how to change password / where to get help; no admin-only wording for a non-admin |

### E. Failure and offline (owner only)
| Step | Do | Expect |
|---|---|---|
| E1 | Stop Audiobookshelf; reload Home as T1 | the other rails load; Listen is marked unavailable with a plain sentence and "Try again"; nothing else breaks; Continue still shows video/comics |
| E2 | Start it again; reload | Listen returns within 2 min |
| E3 | Uninstall (or never install) the Jellyfin app on the phone; tap Watch | the web player opens, not a Safari "cannot open" alert with no way on |
| E4 | Airplane mode; open the installed app | the Avrana offline page (lockup + one sentence + Try again), not a browser error |
| E5 | Submit a book request, then immediately submit the same one again | one request; the second says it is already asked / no duplicate in My requests |

### F. Devices
| Row | Device | Do | Expect |
|---|---|---|---|
| F1 | iPhone Safari (not installed) | A2–A5, B2–B3 | focus/scroll fine; no horizontal scroll at 390 px |
| F2 | iPhone, Add to Home Screen | A2–A5, D4, E4 | runs standalone; handoffs open the apps; coming back lands in the installed app |
| F3 | iPhone text size at the largest accessibility step | Home, Library, Search | every focused card and every button is reachable and fully visible; nothing clipped |
| F4 | iPhone VoiceOver | Home → first Continue card → action | cards read "<title>, <glance line>, link"; the tab bar reads four tabs with the current one announced |
| F5 | Desktop keyboard only | Home → Library → a card → action → back | Tab order follows reading order; the focus ring is always visible; Escape/back restores focus to the card you left |
| F6 | TV / native client actually used at home | Me → "Sign in on a TV" (Quick Connect) | the code pairs; the TV signs in as T1; playback starts |

## 3. Two-member privacy test (S0 if any row fails)

Run with T1 and T2 signed in on two devices (or two browsers).

| Step | Do | Expect |
|---|---|---|
| I1 | Each opens Home, Library, Search | each sees only their own libraries; T2 never sees Comics named, counted or "unavailable" |
| I2 | T1 watches/listens/reads 2 min | T2's Continue (reload) does not show it; T2's `/home.json` has no T1 item |
| I3 | Owner removes T2 from a library group in Authentik; T2 reloads within 2 min | that library and its covers are gone for T2 (also open a previously loaded cover URL in T2's browser: it must not load) |
| I4 | T1 makes a request (book or watch) | T2's My requests does not list it; T1's does, with status |
| I5 | T1 opens a title page, copies its URL; T2 pastes it | T2 gets the standard not-found page if T2 lacks the library, never T1's item |
| I6 | `docker exec avrana-home-beta python3 -m avrana_home.identity_bindings count`; `docker logs avrana-home-beta --since 24h | grep -c bindings_unavailable` | bound/reserved counts as expected; 0 |

## 4. Support and recovery tests (owner)

| Step | Do | Expect |
|---|---|---|
| R1 | From Me → Help → "If something doesn't open", follow the steps for a missing app as a member would | every step is doable on the phone; no step names a service the member lacks |
| R2 | Read the welcome and house-rules text as T1 | names the support contact decided in AVR-458; says what is collected (bindings, progress read from the apps, request history) |
| R3 | Offboard a throwaway test account with `scripts/offboard.py` per `docs/runbooks/offboarding.md` (dry run first) | the name is retired; a new sign-up under that name is refused; Home refuses the old `sub` |
| R4 | Roll Home back to `pre-<sha>` and forward again (`docs/runbooks/home-rollback-rehearsal.md`) | both under 5 min; members' Continue unchanged afterwards |

## 5. Results template

Copy per tester (pseudonyms only; never member names or the titles they actually watched):

```
Tester: T1   Device: <model / OS / Safari or PWA>   Date: 2026-__-__   Build: <sha>   Session length: <min>
A1..A5  Pass/Fail/Blocked  sev:  evidence (screenshot/recording file, timestamp):  note:
B1..B4
C1..C4
D1..D5
E1..E5  (owner only)
F1..F6  (one row per device)
I1..I6  (both testers)
R1..R4  (owner)
Unaided? yes/no — where did they need help?
One thing that confused you:
Would you use this instead of the apps directly? yes/no/sometimes
```

## 6. Release rule

- **Member beta may start** when: 0.1–0.5 done; the owner pass has **no S0 and no S1** on A, B, C, D, F; I1–I6 all pass;
  R1–R3 pass. S2 findings go to the triage list, not the gate.
- **Cutover may be proposed** (AVR-389) when at least 3 members completed A–D unaided, no open S0, every S1 has a fix or
  an accepted workaround, O6–O8 done, and the owner signs off in writing.
