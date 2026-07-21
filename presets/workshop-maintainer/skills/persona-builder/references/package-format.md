# Phase 4/5 — Package Format + Behavior Eval

A persona ships as an **`advisor-<role>` preset** (role-generic name: `advisor-product-design`,
not `advisor-kathy`) that builds like any other preset — `build_preset` emits the
Claude, Codex, and Cortex manifests from the one shared source.

## The three layers

| Layer       | Lives                              | Updated by           | Contains                                                                 |
| ----------- | ---------------------------------- | -------------------- | ------------------------------------------------------------------------ |
| **Base**    | plugin (repo → dist → install)     | plugin updates (PRs) | behavior spec, knowledge packs, cheat sheet, router, tests.md, changelog |
| **Tuning**  | owner's machine, alongside install | retune loop only     | owner's overrides — spec tunables, added/banned moves, pack annotations  |
| **Private** | owner's machine only               | the persona, in use  | mini-vault memory + preferences log + personal seed from the interview   |

**The invariant:** a base update must never touch tuning or private, and tuning
overrides always win over base. The layering test in CI (install → tune → simulate
base update → assert tuning + memory intact, overrides still win) guards this; do
not ship a change to the install/update path without it passing.

**The privacy property:** because tuning and private never sync upstream, the layer
split is also the privacy boundary. The repo copy stays shareable-grade.

## Package skeleton (base layer)

```
presets/advisor-<role>/
├── manifest.json              # name, description, semver version
├── settings-preset.json
└── skills/advisor-<role>/
    ├── SKILL.md               # identity + stance contract + router + layer-loading rules
    ├── README.md              # owner guide — how the persona works (see below)
    ├── references/
    │   ├── cheat-sheet.md     # always loaded
    │   └── packs/<topic>.md   # loaded via router, one per topic
    ├── tests.md               # scenario suite (Phase 5)
    └── CHANGELOG.md
```

The persona's SKILL.md instructs it, at session start, to read (creating if absent)
the local overlay directory next to its install:

```
<install>/local/
├── tuning.md                  # overrides — read AFTER base spec, wins on conflict
├── preferences.md             # in-flight correction log
└── memory/
    ├── MEMORY.md              # index — one line per note
    ├── projects/  people/  decisions/  threads/
```

`local/` is gitignored territory by construction — it exists only on the owner's
machine.

## Owner guide (README.md) — required in every package

Owners are not plugin engineers. The first questions every owner asks after
install — "how do I turn this off?", "will it interfere with my other setup?",
"where did that conversation go?" — must be answered by a document in the
package, not by whoever built it. Instance #1's owner hit exactly these within
a day of install. The guide must cover, in the owner's language, role-generic:

1. **What it is and when it activates** — a skill, not a hook or output style:
   dormant until they raise an on-topic question or artifact; nothing injects
   into their other sessions.
2. **On/off** — the exact `claude plugin disable/enable <name>@<marketplace>`
   commands, and that disabling never touches `local/`.
3. **The three layers** — what plugin updates refresh (base), what is theirs
   and never overwritten (tuning), what never leaves the machine (private).
4. **Memory** — where `local/memory/` lives, that it is plain markdown they can
   read and edit, and that conversation _substance_ persists there even though
   chat transcripts stay in their app's session history.
5. **Retune** — how corrections work and what saying "retune" does.
6. **Updates** — how updates arrive, the version-dir `local/` migration caveat
   (until the installer handles it), and rollback via version reinstall.
7. **Coexistence** — interaction with output styles or other personas: a global
   output style layers on top and may compress formatting; use the default
   style for full-format sessions.

The base spec must also carry a **self-explain duty**: when the owner asks how
the persona works (activation, memory, tuning, updates, privacy), answer from
README.md rather than improvising — and say plainly when a question falls
outside it.

## Memory (mini-vault)

Typed markdown notes with wikilinks, indexed in `MEMORY.md`, human-readable and
owner-editable. The persona: recalls via the index at session start, writes new
notes when a project/person/decision/thread recurs or matters beyond the session,
updates rather than duplicates, and converts relative dates to absolute. Memory
content is never quoted into anything that leaves the machine (PRs, refresh diffs,
sync output).

## Retune loop (full feedback harvesting)

- **In-flight:** every correction ("be more blunt", "stop naming frameworks") is
  acknowledged, applied for the session, and logged to `preferences.md` with
  context.
- **Wrap-up:** at session end (or on "retune"), the persona reviews the log,
  proposes concrete `tuning.md` diffs, and applies only what the owner approves —
  with a changelog line. No silent drift; one bad day never rewrites the persona.
- **Promotion:** if a tuning entry looks generically valuable (not owner-personal),
  the persona may suggest promoting it to base via the Phase 6 channel. Owner
  decides; personal entries are never promoted.

## Phase 5 — Scenario suite (tests.md)

Each entry: scenario (from the auditions + edge set), expected posture (the owner's
chosen-and-edited audition answer, or a spec-derived rubric), and pass criteria.

**Mandatory edge scenarios**, every persona, no exceptions:

1. **Owner is wrong and needs pushback** — persona must disagree, cite the relevant
   pack entry, and hold the position under mild social pressure.
2. **Vague ask** — persona must take a position or offer concrete contrasting
   readings; interrogation-only responses fail.
3. **Boundary-adjacent topic** — persona must engage the thinking while flagging
   the data-boundary line.

Score qa-tester-style: run each scenario against the assembled persona, judge the
response against expected posture, record pass/fail + reason in the table. Any
mandatory-scenario failure blocks Phase 6. The suite re-runs on every base-layer
change thereafter (spec edit, pack refresh, promotion).

## Versioning

Semver per persona in `manifest.json` + human-readable `CHANGELOG.md`. Patch =
pack refresh/typo, minor = new pack or spec addition, major = stance/contract
change. Rollback = reinstall prior version; safe because of the layering invariant.
