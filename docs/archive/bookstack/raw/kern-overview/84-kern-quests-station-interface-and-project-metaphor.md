---
bookstack_page_id: 84
title: "Kern Quests: Station Interface and Project Metaphor"
shelf: "Kern"
book: "Kern: Overview"
chapter: ""
created: 2026-09-09 03:16:58
updated: 2026-09-09 03:37:28
last_editor: "Cody"
revisions: 2
tags: []
source_format: markdown
classification: ARCHIVE
destination: ""
---

> **Archived BookStack page. Not authoritative.** Last edited 2026-09-09; exported 2026-10-04. Classified ARCHIVE. Kern project design.

# Kern Quests: Station Interface and Project Metaphor
# Kern Quests: Station Interface and Project Metaphor

**Status: concept. Nothing built, and several load-bearing decisions are deliberately open.**
This page captures the design concept for Kern's presentation layer and its first practical
application, in enough detail to be used as design context when implementation starts. It is
product and interface design, not architecture. The orchestration constraints on
*Kern: Design Principles* still apply and are not restated here.

Read alongside [Project Overview and Naming](http://10.0.0.218:6875/books/kern-overview/page/project-overview-and-naming)
and [Architecture and Boundaries](http://10.0.0.218:6875/books/kern-overview/page/architecture-and-boundaries).
Section 15 records where this concept currently contradicts those pages. Those contradictions are
listed, not silently resolved.

## 1. Overview

Kern Quests is the first practical Kern application: management of projects and ideas, presented
through a fictional interface rather than a conventional productivity dashboard.

The framing is that the user is the captain of a mobile deep space expedition station. Real work
is presented through that fiction: projects are expeditions, ideas are unresolved signals,
finished work leaves permanent marks on an explored universe.

The fiction is part of the MVP. It is not a skin to be applied after a generic task manager
works. Section 12 states that boundary precisely, because it is the easiest thing about this
concept to get wrong.

## 2. Design philosophy: diegetic, not gamified wallpaper

The distinction that governs every other decision on this page.

Kern Quests is explicitly **not**:

```text
task manager + XP + achievements + spaceship background
```

That pattern bolts a reward system onto an unchanged productivity tool. The points are invented,
they measure nothing real, and the theme is decoration that could be removed without changing
what the interface communicates.

The ambition here is the opposite. Ordinary productivity concepts are communicated **through** the
fictional system, so that the fiction is doing the information design work:

| Real state | Diegetic presentation |
|---|---|
| Neglected project | Expedition losing contact |
| New idea captured | Signal detected |
| Completed initiative | System charted, outpost established |
| Blocked project | Mission awaiting external transmission or resource |
| Shelved project | Stasis |
| Important stale project | Bridge alert |
| Periodic backlog review | Command Review |

**Test for whether a proposed element belongs:** does it tell the captain something true about the
state of real work? An expedition losing contact communicates neglect, and communicates it more
legibly than a "last updated 17 days ago" field. An XP bar communicates nothing that was not
already known.

**Counterweight, equally important.** The metaphor serves the information architecture and must
not obscure it. A captain who cannot tell what is actually going on, or who has to translate
fiction back into real project state before acting, is looking at a worse tool than a plain list.
Legibility wins over immersion wherever the two conflict.

## 3. Grounding in real project management practice

**Status: stated design intent and an open research workstream. No methodology has been chosen.**

The mechanics on this page must be rooted in established project management theory rather than
invented because they feel good. The intent has two parts, and they are separable:

**Apply real project management practice across the whole stack.** Not only to Kern Quests as an
application, but to how work across the ecosystem is actually planned, sequenced, reviewed and
closed out. The Avrana roadmap, the audit remediation batches, and the Kern build order are all
project management artifacts already, produced ad hoc. Bringing them under a consistent, researched
approach is part of the goal.

**Root the design in genuine project management education.** Research established bodies of
practice first, decide which theories and approaches to adopt deliberately, and let the fiction
express those rather than inventing parallel mechanics that happen to look similar. A mechanic that
maps onto a real practice inherits decades of evidence about whether it works. A mechanic invented
to fill a screen does not.

**Why this belongs next to section 2.** The diegetic principle says the fiction should communicate
true state. This section adds the other half: the underlying model being communicated should itself
be sound. Fiction over a well-grounded model is an interface. Fiction over invented mechanics is
still wallpaper, however diegetic it looks.

**The recall mechanic in section 7 is the first worked example.** Requiring a written account of
what was learned before crew can be recovered is the retrospective, or lessons-learned review, which
is long-established practice. The fiction supplies the motivation to actually do it, which is the
part real teams routinely skip. That is the pattern to repeat: find the practice first, then find
the diegetic expression of it.

Bodies of practice worth researching are deliberately **not** listed here as recommendations, because
choosing among them is an open decision (section 14) and the research has not been done. Recording a
shortlist now would prejudge it.

## 4. World and metaphor

The mapping, as currently understood:

| Fiction | Reality |
|---|---|
| The station, or flagship | The user's broader life infrastructure and operating environment |
| The captain | The user |
| Expeditions, expedition vessels | Projects and campaigns dispatched toward objectives |
| Unidentified signals, anomalies, discoveries | Ideas that have been detected but not investigated |
| Smaller missions, sorties, probes, auxiliary craft | Side quests and smaller tasks |
| Outposts, charted systems, completed expedition records | Completed major projects, as permanent marks |
| Crew | Effort, tools, automation, software agents, and other resources assigned to work |

The station is the persistent home context. Expeditions leave it and go somewhere. That directional
quality is the useful part of the metaphor: work has a destination, a distance still to travel, and
a state of contact with the station.

## 5. Projects as expeditions

Four levels of work, from largest to smallest.

**Campaigns.** Large initiatives containing multiple quests or related objectives. A campaign is
the strategic unit: it expresses where effort is heading over a long horizon.

**Quests.** Concrete projects, or meaningful self-contained pieces of work. This is the primary
unit of the system and the thing most screens are about.

**Side quests.** Smaller, optional, experimental, or lower priority work. They exist so that minor
work does not have to be dressed up as a project to be tracked, and so that it does not compete
for attention with campaign-level commitments.

**Signals.** Captured ideas that have not become work yet. Covered in section 6.

**Next action.** Every active project should make the next meaningful thing the captain can
actually do obvious. This is a requirement on the data model and on every view that shows an
active quest, not a UI nicety. A project whose next action is unknown is itself a finding, and
Command Review is where that surfaces.

## 6. Signals and idea capture

Ideas enter through something resembling a scanner, sensor array, or signal feed.

The purpose is a deliberate asymmetry:

- **Capture must be extremely low friction.** A thought that is annoying to record is lost.
- **Capture must not create obligation.** A newly captured thought does not become a project,
  does not appear on the active list, and does not start aging as though it were work in flight.

A signal is an unresolved detection. It sits in the feed until the captain decides whether it
deserves an expedition. Promotion from signal to active quest is an explicit decision, made during
Command Review or ad hoc, and it is the moment an idea acquires a next action and a staleness
profile.

This is what prevents every passing thought from bloating the active project list, which is the
common failure of low-friction capture systems.

**Historical note: the Tavern concept.** An earlier iteration framed the discovery and selection of
side quests as visiting a tavern and picking up work from a board. That idea is preserved here as
conceptual inspiration because the underlying insight is sound: browsing available work and
choosing to accept it is a different activity from being handed a task list, and it deserves its
own place in the interface. The tavern framing itself does not fit a deep space station, so current
terminology favours the scanner, the signal feed, and the mission board. The mechanic is retained;
the fantasy dressing is not.

## 7. Project states

Six states are currently in the concept. Each has a practical meaning and a fictional presentation.

| State | Practical meaning | Fictional presentation |
|---|---|---|
| **Idea** | Captured, not committed to. No next action required. | An unresolved signal or anomaly on the sensor feed |
| **Active** | Committed to and being worked. Should have a next action. | An expedition under way, in contact with the station |
| **Waiting** | Blocked on something outside the captain's control: another person, a delivery, an external event. Not neglect. | A mission awaiting an external transmission or resource |
| **Stasis** | Deliberately shelved. A decision was made to stop, and it can be resumed. | A vessel powered down and held in stasis |
| **Complete** | Finished. Leaves a permanent mark on the universe. | A charted system, an established outpost, a filed expedition record |
| **Abandoned** | Deliberately stopped and not intended for resumption. Offers a choice between abandoning in place and recalling crew, covered below. | A written-off expedition, or a recovered one that filed its record |

**The distinction that matters most is Waiting versus Stasis versus neglect.** All three look like
"nothing is happening" in a naive system, and they are completely different situations. Waiting is
healthy and externally caused. Stasis is a deliberate decision. Neglect is an active project that
has quietly stopped receiving attention, and it is the only one of the three that should become
conspicuous. Staleness handling depends entirely on getting this separation right.


### Abandonment: two paths

Abandoning an expedition offers the captain a choice, and the choice carries different costs.

**Abandon in place.** The mission is written off where it stands. Equipment and crew are left
behind with it. This is the low friction path: no account of the decision is required, and it can be
taken at any time.

**Recall.** Crew and equipment are retrieved from the expedition and returned to the station for
reassignment. This path is available **only if the captain files a short record of what was learned
and why the mission was abandoned.** The record is the price of recovering the investment.

**Escalation when abandonment goes unexamined.** If too many expeditions are abandoned in place
without recall, attempting to launch a new expedition raises a prompt, and continues to do so until
substantial progress has been made on something already active. The intent is to make a pattern of
unexamined abandonment visible at the moment it is about to repeat, rather than reporting it in a
statistic nobody reads.

**Why this mechanic is worth keeping.** It is the clearest example on this page of section 2 and
section 3 working together. The real practice underneath is the retrospective: the discipline of
recording why something was stopped and what it taught, which teams routinely skip because nothing
forces it and the project is over anyway. Here the fiction supplies the motivation directly, and the
reward is concrete rather than moral. The captain is not being told to reflect because reflection is
virtuous. The captain wants the crew back.

It also produces something genuinely valuable over time: a body of honest records about why work
was stopped, which is exactly the history that is normally lost.

**What this commits the data model to.** Recorded here because these follow from the mechanic rather
than being separate decisions:

- The abandonment record is a first class content type, not a comment field. It is the thing the
  Archive is most likely to be read for later.
- Crew and equipment must be modelled as an assignable resource with a finite pool, or recall
  recovers nothing and the choice is empty.
- The abandonment pattern must be tracked over time, not just per project, since the escalation
  depends on a ratio and a recent history.
- "Substantial progress" is the same undefined quantity as meaningful activity in section 8. Both
  depend on one definition, and the escalation gate cannot be built before it exists.

Several parameters of this mechanic are deliberately unresolved. See section 14.

## 8. Dynamic staleness

Projects and ideas age differently, and staleness is presented diegetically rather than as a
timestamp field.

**The principle.** Time since last activity means different things in different states. An
undeveloped idea can lie dormant indefinitely without being a problem, because dormancy is the
normal condition of an idea. An active expedition that suddenly stops reporting is a problem, and
should become increasingly conspicuous the longer it continues. A project in Waiting should not
accrue neglect at all while the thing it waits on has not arrived, and a project in Stasis should
not accrue it either.

Staleness is therefore a function of state, not a single global timer.

**Meaningful activity.** Kern should distinguish real progress from record touching. Editing a
title, adjusting a tag, or opening a project does not constitute progress, and should not reset an
inactivity clock if nothing meaningful happened. What qualifies as meaningful is an open question
(section 14) and needs a written definition before implementation, because the entire staleness
model rests on it.

This connects directly to an existing Kern rule. *State, Events and Reliability* requires naming
one authority per fact and treating everything else as a supporting signal. "Did meaningful
progress occur" is exactly such a fact, and it needs a named authority rather than an accumulation
of heuristics.

**Presentation.** Staleness should manifest as diegetic signals rather than a numeric field.
Candidates raised so far include deteriorating mission status, lost telemetry, drifting vessels,
overdue transmissions, and neglected systems. **The visual implementation is deliberately not
specified here.** The principle is what is being recorded: degradation should be visible, should
scale with severity, and should read as something happening to a mission rather than as an
administrative warning.

## 9. Command Review

A periodic mechanism where the captain is shown missions that require a decision, rather than an
undifferentiated task list.

The problem it solves is that backlogs decay silently. Items do not announce that they have gone
stale, that they are blocked on something that already arrived, or that they no longer matter.
Command Review is the scheduled moment when the system raises those cases and asks for a ruling.

Decisions available at review currently include:

- Continue the mission.
- Change its priority.
- Put it into stasis.
- Abandon it.
- Define a next action.
- Promote a signal into an active expedition.

**What distinguishes this from a task list is curation.** Command Review should surface the
missions that need a decision, which is a much smaller set than everything open. An active quest
with a clear next action and recent progress does not need the captain's attention and should not
consume it.

The set of decisions above maps onto Kern's existing action classes on
*Orchestration and API Principles*: most are additive or administrative, and abandonment is
destructive in the sense that page uses. Review cadence and trigger conditions are open
(section 14).

## 10. Station modules

The station provides distinct functional areas rather than one generic dashboard. Each module is a
place with a purpose, which is what makes the layout navigable without a menu of abstract nouns.

**These names are the current design language, not a finalised navigation architecture.**

| Module | Purpose |
|---|---|
| **Bridge** | Command overview: current objectives, alerts, priority missions, decisions requiring captain attention |
| **Engineering** | Infrastructure, maintenance, technical systems, and possibly operational projects |
| **Science** | Investigation, research, experiments, unidentified signals, and ideas |
| **Navigation** | Longer term destinations, planning, campaigns, roadmap, and where effort is heading |
| **Archive** | Completed, abandoned, historical, and reference material |
| **Fabrication** | Things actively being built or created |
| **Comms** | Messages, external information, notifications, integrations |
| **Medical** | Reserved for future captain telemetry and wellness concepts. Explicitly **not** part of the project management MVP |

Two observations worth keeping. Several modules overlap in ways that are not yet resolved:
Science holds ideas while Navigation holds campaigns, and a research-heavy campaign has a plausible
claim on both. Engineering and Fabrication are also adjacent. Whether these are distinct modules,
distinct views over one dataset, or a filter applied to a single work list is open (section 14).

## 11. Persistent universe and completed work

The concept element to preserve most carefully.

Completed work should make the fictional universe feel increasingly inhabited. A finished project
does not vanish into a list called Archive. It leaves something behind: a charted planet, a colony,
a station, an outpost, an explored system, a filed expedition record, a discovery, or another
persistent landmark.

Over time the universe becomes a visual history of what the captain has actually accomplished.

**Why this matters, and why it is not a points system.** The landmarks are generated by real
completed work, so the map is a true record. Its density and shape are consequences of history
rather than of a scoring rule someone invented. This is the same principle as section 2 applied to
reward: the satisfaction comes from the accumulated evidence of real accomplishment, and it cannot
be farmed by touching records, because only genuine completion creates a landmark.

An XP counter can be gamed and means nothing outside the app. A charted system corresponds to a
project that actually finished.

## 12. MVP scope: Kern Quests v1

**In scope.** The fiction is included deliberately and is not deferred:

- Campaigns
- Projects and quests
- Side quests
- Idea and signal capture
- Project states
- Next actions
- Meaningful activity tracking
- Dynamic staleness
- Command Review
- Bridge and dashboard concept
- Archive and history
- The science fiction presentation layer itself

**The reason the fiction is in the MVP.** Building a generic task manager first and theming it
later produces exactly the outcome section 2 rejects, because the data model will have been shaped
by a conventional tool and the theme will have nowhere to attach. Staleness presentation, the
persistent universe, and the signal-versus-project distinction are all data model commitments as
much as visual ones.

## 13. Longer term Kern vision

Out of scope for the MVP. Recorded so the boundary is explicit and so these are not treated as
natural extensions to add during v1:

- Health tracking
- Wearable integrations
- Journaling
- CBT modules
- Media library integration
- Large AI agent systems
- Broad third party integrations
- Captain biometrics and telemetry
- Other personal operating system functions

These can eventually make Kern a much larger personal operating environment. None of them may
derail the project management MVP. The Medical module in section 10 is the placeholder where several
of them would eventually land.

## 14. Open design questions

Genuinely undecided. Per the convention on *Project Overview and Naming*, **do not resolve any of
these by writing an implementation.**

**Model and data**

- What exactly constitutes meaningful activity? The whole staleness model depends on this
  definition, and it does not exist yet.
- Does Kern Quests own its own datastore, or use a Kern datastore? This intersects the existing
  open question on *Open Decisions and Future Research* about whether Kern owns a datastore from
  day one.
- Do campaigns nest? Can a quest belong to more than one campaign?
- Are side quests a distinct entity type, or a quest with a flag or priority band?
- Is staleness computed per state with a configurable profile, or fixed per state?
- Does the system ingest work from elsewhere, for example the Avrana roadmap page or Git activity,
  or is every quest entered by hand?

**Behaviour**

- Command Review cadence: scheduled, triggered by conditions, or both? What triggers it?
- What does abandonment leave in the universe? **Partly answered by the recall mechanic in
  section 7**, which settles what happens to crew and equipment. What remains open is the visible
  mark: does an expedition abandoned in place leave a derelict or a distress beacon on the map, and
  does a recalled one leave a different mark, or none? Leaving nothing loses real history; leaving a
  derelict may read as either honest or discouraging.
- Is the persistent universe spatially meaningful, with coordinates and distance carrying
  information, or is it symbolic arrangement?
- Is there a plain mode that presents the same state without the fiction, for moments when the
  metaphor is in the way? Section 2 requires legibility to win over immersion, but the mechanism
  is unspecified.
- Is Kern Quests single captain? Avrana has real users; whether this system ever has more than one
  is undecided.

**The recall and escalation mechanic (section 7)**

- How many abandonments in place is "too many", and over what window? A fixed count, a ratio
  against completions, or a decaying score?
- What counts as "substantial progress" for clearing the escalation? This is the meaningful
  activity definition again and cannot be answered separately.
- Is the escalation a hard block on launching, or a dismissible prompt? A hard block makes the
  system something to fight; a prompt that is always dismissed does nothing. Undecided, and it is
  the difference between the mechanic helping and being resented.
- Does the recovered crew and equipment pool actually constrain anything in v1, or is it symbolic?
  If capacity is never scarce, recall costs nothing and the choice is not a real one.
- Is the mechanic itself MVP or later? Project states are in scope for v1 (section 12), but the
  crew and equipment pool, the abandonment history and the escalation gate are a larger system than
  a state field. Not stated either way.
- Is there a minimum bar for the abandonment record, or is any text accepted? A required field that
  accepts "n/a" teaches the captain to write "n/a".
- Can an abandoned expedition be revived later, and if so does its record travel with it?

**Project management grounding (section 3)**

- Which bodies of project management practice are adopted? The research has not been done and no
  methodology has been selected.
- Does "education around project management" mean the design is informed by real practice, or that
  Kern Quests itself teaches project management to the captain? Both readings are live and they
  imply very different products.
- How much formal process survives contact with a single-operator personal system? Most established
  practice assumes teams, stakeholders and schedules that do not exist here.
- Which existing artifacts get brought under the approach, and in what order: the Avrana roadmap,
  the audit remediation batches, the Kern build order?

**Interface and naming**

- Are the eight station modules distinct areas, distinct views over one dataset, or filters on a
  single work list? Section 10 notes the Science and Navigation overlap and the Engineering and
  Fabrication adjacency.
- Does Medical exist in the MVP as a visible but empty area, or not at all?
- Final terminology for the capture mechanism: scanner, sensor array, signal feed, or another term.
- How much visual weight does staleness degradation carry before it becomes noise?

## 15. Reconciliation with existing Kern documentation

Recorded rather than resolved. Each of these is a real conflict with a page on this shelf.

**1. Kern's stated purpose does not currently include this.** *Project Overview and Naming* defines
Kern as an orchestration and control plane over subsystems, existing so that interfaces target one
deterministic layer instead of individual services. Personal project and idea management is neither
media nor smart home, and it is not orchestration of a subsystem. That page also states that
anything not media and not smart home is a future subsystem until it is named. Kern Quests is
either that named subsystem, or a broadening of what Kern is for. **Undecided, and it should be
decided early**, because it determines whether Kern Quests sits above Kern, beside Avrana, or is
Kern's own first application.

**2. It is not in the agreed build order.** *Roadmap and Order of Operations* sequences Kern as
stabilise Avrana, define boundaries, define contracts, prove one deterministic workflow, build
state and event plumbing, then add a model gateway. Every step concerns orchestration over existing
subsystems. A project management application is not a step in that sequence. Two readings are
available and neither has been chosen: Kern Quests becomes the step 4 deterministic workflow, or it
is a parallel track with its own sequence. Note that Kern Quests satisfies step 4's stated
requirement of involving no LLM.

**3. The design language conflicts.** *Kern Tablet: SM-T510 desk companion* fixes the design
language as Avrana's monochrome retro-futurist aesthetic: black and white, Times New Roman, square
rules, no shadows, sparse rather than information dense, minimal animation, subtle orbital and
radar motifs, inherited from the portal and the Authentik login rather than reinvented. A
persistent inhabited universe with drifting vessels and accumulating landmarks pulls toward
information density and motion. The orbital and radar motifs are compatible; sparseness and minimal
animation may not be. Unresolved.

**4. Two competing navigation models exist.** The Kern Tablet page proposes five pages: Home,
Media, Kern HQ, Avrana, Infrastructure. Section 10 proposes eight station modules. If the tablet is
a Kern Quests client, one of these has to give, or they are describing different surfaces.

**5. "Interface" is now overloaded.** *Orchestration and API Principles* states that Kern owns its
own interface, meaning Kern-owned API contracts that never leak an upstream service's shape. This
page uses "interface" to mean the presentation layer. Both usages are legitimate and they are not
the same thing. Prose that mixes them will confuse a future session.

**6. The layering question follows from item 1.** *Architecture and Boundaries* requires that
interfaces never reach subsystems directly, and that Home Assistant occupies two distinct roles as
interface and subsystem. If the station is an interface and the quest data lives in Kern, then Kern
is both the control plane and the subsystem being controlled. That may be acceptable, and it may
be the same dual role Home Assistant already has, but it has not been examined.

**Where the concept fits existing principles without conflict**, and should reuse them rather than
invent parallel mechanisms:

- *State, Events and Reliability* treats availability as a lifecycle with stall states rather than
  a boolean, and expects items to stall in middle states rather than fail loudly. Project states
  and staleness are the same shape of problem and should reuse that thinking.
- The same page's rule of one named authority per fact applies directly to meaningful activity.
- *Orchestration and API Principles* action classes already cover the Command Review decisions,
  including treating abandonment as destructive and requiring confirmation.
- The canonical identifier rule applies: quests, campaigns and signals need stable internal IDs,
  and titles are display strings only.
