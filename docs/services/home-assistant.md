# Kern HQ: Home Assistant

> Promoted from the BookStack wiki on 2026-10-04 (page 62, "Kern HQ: Home Assistant", last edited 2026-08-21) when BookStack was retired. This file is now the maintained copy.
> The text was written before the 2026-09-20 recovery and has not been re-verified line by line; where it disagrees with the compose files or `BOOTSTRAP.md`, they win. Correct it here.
> Note: Home Assistant runs in production under the name Kern HQ.
> Original: [archive](../../docs/archive/bookstack/raw/kern-hq-home-assistant/62-kern-hq-home-assistant.md).

**Status: DEPLOYED 2026-08-18.** Home Assistant Container 2026.8.2 runs on the avrana host at
`services/home-assistant/`, LAN-only, with a fully local voice pipeline and the Voice PE puck
adopted. The design principles below are unchanged; the "planned" language has been updated to
reflect what is actually running.

## Scope

Kern HQ is the **smart-home portion of Kern**:

- Home Assistant itself and its device integrations,
- household automation,
- voice interfaces, including **Home Assistant Voice Preview Edition**,
- local speech processing (wake word, STT, TTS).

It is *not* the media stack. Media is Avrana.

## Two roles, kept separate

Home Assistant occupies two distinct positions, and conflating them is the main architectural
risk in this area:

| Role | Meaning |
|---|---|
| **Interface** | A person speaks to a voice device; that utterance becomes a request to Kern. |
| **Subsystem** | Kern instructs Home Assistant to act on devices. |

The same software, two directions of travel. Kern sits between them.

## Kern HQ must not become the orchestrator

It will be tempting to implement cross-subsystem logic as Home Assistant automations: the
automation engine is already there, already triggered by voice, and already talks to devices.
Doing so is a mistake.

- HA automations are hard to version, test and review compared to a service with a contract.
- Media logic would end up living in the smart-home system, where nobody thinks to look.
- Two orchestrators competing for authority produces exactly the state disagreements described
  in *State, Events & Reliability*.

**Rule:** Kern HQ handles home devices and captures intent. Anything crossing subsystems goes to
Kern.

**Enforced in code:** `services/home-assistant/docker-compose.yml` carries a boundary comment
stating that no automation in this instance may call Sonarr, Radarr, Seerr, Jellyfin,
Audiobookshelf or Komga. Once voice works, wiring "play the next episode" straight to Jellyfin is
the tempting next step and is exactly what this rule forbids. That waits for Kern, roadmap step 7.

## Voice pipeline: as built

```text
wake word (on-device, puck) → STT → intent match → action → spoken result
```

Concretely, pipeline **`Kern HQ Local`**:

| Stage | Component | Notes |
|---|---|---|
| Wake word | on-device microWakeWord | currently **"Hey Jarvis"**; Okay Nabu / Hey Mycroft also available |
| STT | `stt.speech_to_phrase` :10300 | Wyoming container, Kaldi, local |
| Intent | `conversation.home_assistant` | deterministic, **no LLM** |
| TTS | `tts.piper` :10200 | Wyoming container, `en_US-lessac-medium`, local |

**No cloud in the voice path.** This satisfies the invariant that the architecture keeps
functioning if every external provider disappears. Deployment shape was decided as **HA Container
on the existing host** (not HAOS, not an appliance), per *Hardware / Infrastructure Strategy* :
which means no Supervisor and no add-on store, so voice components run as separate Wyoming
containers.

**Operational rule:** Speech-to-Phrase builds its vocabulary from entities **exposed to Assist**.
An unexposed or newly renamed device is unrecognisable, and the transcript returns as an **empty
string with no error**: that empty transcript is the signature of "not exposed / not retrained",
not of broken audio. After adding or renaming a device:
`docker compose restart speech-to-phrase` (~5s).

The identity question applies most sharply here: a shared voice device does not establish who is
speaking. See *Identity, Permissions & Security* before letting voice reach anything sensitive.

## Local speech workloads

Fast local speech (Speech-to-Phrase, Piper) was expected to run acceptably on existing hardware,
and does. Measured idle: HA ~490 MB, Piper ~166 MB, Speech-to-Phrase ~155 MB, all ~0% CPU.
Training completes in about 5 seconds. See *Hardware / Infrastructure Strategy*: this remains
**not** a reason to buy anything.

## Amazon Smart Plug bridge: HA side DONE, 2 manual routines outstanding

**Problem.** The Amazon Smart Plug (bookshelf lights) had no local control path. The original
bridge was a UI template switch, `switch.bookshelf_lights_on_off`, whose turn_on/turn_off actions
called `alexa_devices.send_text_command` against the **Study Echo**, literally sending the text
"turn on bookshelf lights". The Echo processes that as a spoken command, so **every switch
produced an acknowledgement chime**.

**Final flow:**

```text
HA Voice → input_boolean.bookshelf_lights → automation → button.<alexa routine> → Amazon Smart Plug
```

### Why this needs no HA→Alexa exposure

This was the key finding, and it overturned the initial design. `alexa_devices` is usually
described as one-way (Amazon → HA), and its only services are `send_text_command`, `send_sound`
and `send_info_skill`: none of which publish HA entities to Alexa. That suggests you need a paid
Nabu Casa bridge to let an Alexa routine watch HA state.

You don't. The integration also surfaces **every ENABLED Alexa routine as an HA button**
(`AmazonRoutineButton`), and pressing it calls `aioamazondevices.call_routine()` →
`AmazonSequenceType.Routines`, which invokes the routine's action sequence **directly through
Amazon's sequence API**. That is not an utterance handed to the NLU, which is exactly what
`send_text_command` does and precisely why the old path chimed.

So the direction of travel inverts: **HA pushes to Alexa; Alexa never watches HA.**

Routines are matched **by name**, filtered only on `status == "ENABLED"`. The **trigger type is
irrelevant**: give them whatever trigger the Alexa app will accept.

> **Rejected earlier draft:** a template `binary_sensor` with `device_class: door` mirroring the
> helper, so an Alexa routine could trigger *on* HA state. Alexa routine triggers do only accept
> contact/motion sensors, so the trick itself is sound: but it points the wrong way, and it still
> requires a paid HA→Alexa bridge. It was built, then removed. `emulated_hue` was also ruled out:
> it needs host port 80, already occupied on avrana, and cannot present a contact sensor anyway.

### Built and verified on the HA side

| Entity | Role |
|---|---|
| `input_boolean.bookshelf_lights` | canonical state; the **only** voice-exposed target. Aliases: Bookshelf Lights, Bookshelf, Shelf Lights |
| `automation.kern_hq_bookshelf_lights_legacy_text_command_bridge` | **TEMPORARY** legacy path; mirrors the helper to `send_text_command`. This is what still causes the chime |
| `switch.bookshelf_lights_on_off` | legacy UI template switch, superseded, to be deleted |

Verified end to end: spoken phrase → Speech-to-Phrase transcript → intent → helper flips →
automation fires → `send_text_command` succeeds with no errors. Only reloads were needed; HA was
not restarted.

### Manual dependency: two Alexa routines

There is no supported API for **creating** Alexa routines, and undocumented endpoints and browser
automation were explicitly excluded. These two must be made by hand in the Alexa app:

| | Routine 1 | Routine 2 |
|---|---|---|
| Name | **Bookshelf Lights ON** | **Bookshelf Lights OFF** |
| When | any trigger Alexa accepts: e.g. "When you say" → *bookshelf on* | e.g. "When you say" → *bookshelf off* |
| Action | Smart Home → *Amazon Smart Plug* → Power **On** | Smart Home → *Amazon Smart Plug* → Power **Off** |
| Speech | add none: a routine with no speech action is silent | add none |
| Status | must be **enabled** | must be **enabled** |

Names matter: they become the entity ids
`button.cnechamkin_gmail_com_bookshelf_lights_on` / `..._off`.

### Remaining steps once the routines exist

1. Reload the `alexa_devices` config entry so the two new buttons appear.
2. Repoint the automation from `alexa_devices.send_text_command` to `button.press` on those
   entities.
3. Confirm by voice that the plug switches **with no chime**.
4. Delete the legacy automation and `switch.bookshelf_lights_on_off`.

## Voice PE button: desk light group toggle

Double-pressing the centre dial toggles three lights as one group:
`input_boolean.bookshelf_lights` (Amazon plug), `light.office_office_closet_light` (Govee) and
`light.library_lamp` (TP-Link KL125). Automation:
`automation.kern_hq_voice_pe_double_press_toggles_desk_light_group`.

**Single press is not available.** The Voice PE firmware consumes a single centre-button press to
start/stop the voice assistant and never emits it to Home Assistant. The event entity
`event.home_assistant_voice_0992d5_button_press` offers only:

```text
double_press · triple_press · long_press · easter_egg_press
```

Double press is therefore the closest gesture to "push the button". `triple_press` and
`long_press` remain free for future use.

**Group semantics:** if ANY of the three is on, a press turns ALL of them off; only when all three
are already off does a press turn them all on. This keeps one button authoritative over the set
rather than letting three independent toggles drift out of sync.

**Two implementation details worth keeping:**

1. The trigger fires on **any** state change of the event entity, with the gesture checked in a
   template condition. The direct form: `attribute: event_type` with `to: double_press`: would
   silently **miss a second identical press**, because the attribute value does not change between
   two double-presses; only the entity's timestamp state does.
2. `govee_light_local` drives the lamp over **fire-and-forget UDP with no acknowledgement**. One
   dropped command was observed during testing (1 of 7 cycles; a later 6-cycle run was clean). The
   automation therefore waits 2s and re-asserts the Govee only if it did not take. This adds no
   user-visible latency: both lights are commanded before the delay begins.

**Known caveat:** because the group includes `input_boolean.bookshelf_lights`, every press still
fires the legacy text-command bridge and the Study Echo still chimes. That disappears with the
Alexa routines above, not with anything on the button side.

## Sequencing

Kern HQ connects to Kern as a **client**, at step 7 of the roadmap: after deterministic
orchestration is proven. Deploying Home Assistant earlier for its own sake was fine, and is what
has been done; wiring it as an orchestrator is still not.

## Open decisions

- ~~Deployment shape~~: **closed 2026-08-18: HA Container on the existing host.**
- ~~Which wake-word and STT components to use~~: **closed: on-device wake word +
  Speech-to-Phrase + Piper, fully local.**
- How the Amazon Smart Plug gets a chime-free control path: see the four options above.
- How many voice devices, and in which rooms: which drives the shared-identity problem.
- Whether HA keeps any autonomous automations, or defers everything cross-subsystem to Kern.
