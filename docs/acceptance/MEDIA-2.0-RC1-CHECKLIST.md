# Media 2.0 RC1 member acceptance checklist (AVR-387)

Status: **not run.** A checklist and results template for the owner device pass (O5 in
[../release/MEDIA-2.0-RC1.md](../release/MEDIA-2.0-RC1.md)) and then 3 to 5 consenting members. Scenario detail,
synthetic members and failure copy live in [MEDIA-2.0-MEMBER-SCENARIOS.md](MEDIA-2.0-MEMBER-SCENARIOS.md); this
page is what to run and how to score it.

**Opening a link does not prove playback.** A handoff passes only when the media actually starts (video plays,
audio plays, a page renders in the reader) in the right app, at the right item, with the member's own progress.

## Who runs what

| Layer | Who | What it can prove |
|---|---|---|
| Automated | CI / agent | Code behaviour on fixtures (RC1 section 4). Nothing about real devices. |
| Browser simulation | agent | Layout, keyboard, axe at phone width on synthetic data. Not Safari, not the PWA, not real sign-in. |
| Owner physical-device tests | owner, with a **non-admin** tester account | Journeys A to F on real hardware and the live beta |
| Independent member acceptance | 3 to 5 consenting members, unaided | That someone other than the builder can use it |

Before members: O1 (e-mail), O2 (admin MFA), O3 (username/e-mail change off), O4 (restore drill) are done.

## Severity

- **S0 blocker**: someone sees another member's data; cannot sign in or recover; a library they are entitled to is
  unreachable with no explanation. Stops the beta.
- **S1 major**: a journey fails but a documented fallback works; wrong item opens; progress wrong.
- **S2 minor**: confusing copy, slow (over 3 s to a usable Home on phone 4G/Wi-Fi), cosmetic.

## Journeys

Each row: do the steps, record **Pass / Fail / Blocked**, the evidence, and a severity for any failure.

| ID | Journey | Steps | Pass when | Evidence |
|---|---|---|---|---|
| A | First-time member | Invite e-mail → set password → sign in → Home → a library they are entitled to → pick an item → Open | Invite arrives in under 10 min; Home shows only their libraries; the upstream app opens on that item **and it plays/renders** | time of e-mail; screenshot of Home; short screen recording of playback start |
| B | Returning member | Sign in → Continue → first card → Resume | The card is the thing they last used; it resumes within about 1 min of where they stopped, in the right app | before/after position |
| C | Search and discovery | Search one each: movie, show, book, audiobook, comic → open | Results only from entitled libraries; an unentitled library is never named; the chosen item opens and plays/renders | screenshots; note any "no results" that should have matched |
| D | Account recovery | Let a session expire (or sign out) → sign back in; then "Forgot password" → reset e-mail → new password → Home | Each path returns to a usable Home with no dead end; reset e-mail arrives | timestamps; any error text verbatim |
| E | Failure recovery | (owner only) with one library stopped or unreachable; a missing app on the phone; airplane mode | Home still loads the other libraries and says plainly which is unavailable; missing app → web fallback; offline → the offline page, not a browser error | screenshots |
| F | Devices | iPhone Safari; installed PWA (Add to Home Screen); keyboard only on desktop; VoiceOver on iPhone; one TV/native client actually used in the household (Quick Connect "Sign in on a TV") | Each completes A-B-C; focus is always visible; VoiceOver reads cards with titles; the TV signs in and plays | device + OS version per row |

## Two-member isolation (owner, before members; S0 if it fails)

With two non-admin testers whose libraries differ (one without comics, say):

1. Each sees only their own libraries on Home, Library and Search.
2. Tester 1 watches 2 minutes of something; tester 2's Continue does not show it.
3. Remove tester 2 from a library group in Authentik; within 2 minutes tester 2 no longer sees that library or its
   covers (reload).
4. Tester 1 makes a request; tester 2's My requests does not list it.

## Results template

Copy per tester (use a pseudonym, never the member's name or titles they watched):

```
Tester: T1   Device: iPhone 15 / iOS 26.1 / PWA   Date: 2026-__-__   Build: <sha from the deploy record>
A  Pass/Fail/Blocked  sev:   evidence:          note:
B  ...
C  ...
D  ...
E  (owner only)
F  ...
Isolation 1-4: ...
Unaided? yes/no (did they need help; where)
One thing that confused you:
Would you use this instead of the apps directly? yes/no/sometimes
```

## Scorecard (release rule)

- Member beta can start: owner pass has **no S0 and no S1** on A, B, C, D, F and the isolation check passes.
- Cutover can be proposed (AVR-389): at least 3 members completed A to D **unaided**, no open S0, every S1 has a fix
  or an accepted workaround, and the owner signs off in writing.
