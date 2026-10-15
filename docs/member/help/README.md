# Device help topics (draft, AVR-364 groundwork)

Status: **DRAFT, unverified.** Not wired into the Avrana home shell, not shown to any member. Every
device step ends with `[UNVERIFIED on a real device]`. Nobody has followed these steps on a phone or
computer. Remove a marker only after a person has done that step on that device and the owner has said so.

## Format (maps 1:1 onto the shell's help data)

The shell takes help from `HELP` in `services/avrana-portal/portal.py` (loaded by
`avrana_home/app/catalogue.py`, rendered by `help_topic.html`):

    (group, label, host, [ (platform, [ (client, store, url, [step, ...]) ]) ])

plus `HELP_SLUGS[label] = slug`. Each file here is one topic in that shape:

| In the file | In the shell |
|---|---|
| `# Title` | `label` |
| `slug:` | `HELP_SLUGS[label]` |
| `group:` | `group` (one Authentik group; `avrana-users` means every member) |
| `host:` | `host` (the "Open ..." link at the foot) |
| `## Heading` | `platform` |
| `### Heading` | `client` |
| `store:` and `url:` | `store` and `url`, or `none` for both |
| `1. text` lines | `steps` |

The shell shows the first client of a platform as "Recommended" when a platform has more than one.
Step text is rendered as trusted markup by the shell, so steps here use plain text only: no `<`, no `&`.
The marker text in steps is for reviewers and must be removed (by the wiring change) before members see it.

Open decisions that these topics wait on: D-1 support contact, D-12 television app, D-13 password
recovery, D-15 unavailable wording (all in `docs/member/DECISIONS-NEEDED.md` on the AVR-361 branch).
Install prompts also depend on the web app manifest in AVR-364, which is not built. Until it is, a home
screen icon is only a shortcut.
