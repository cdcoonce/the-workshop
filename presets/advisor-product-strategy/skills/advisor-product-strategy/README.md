# Owner Guide — advisor-product-strategy

How your coach works, in five minutes. This is the document the coach itself
answers from when you ask "how do you work?".

## What it is, and when it wakes up

Your coach is a **skill** — not a hook, not an output style. It is dormant
until you raise something in its territory: a product decision you're torn on,
a stakeholder situation, a prioritization call, a design artifact to judge, or
naming it directly. In your ordinary sessions it does nothing, injects
nothing, and costs nothing.

## Turning it off and on

```
claude plugin disable advisor-product-strategy@the-workshop
claude plugin enable  advisor-product-strategy@the-workshop
```

Disabling removes it from your sessions entirely. It never touches your
`local/` folder — tuning and memory survive any number of off/on cycles, and
uninstalling the plugin also leaves `local/` on disk until you delete it.

## The three layers — what's whose

| Layer       | Where                                                     | Who writes it                       | What updates do to it                        |
| ----------- | --------------------------------------------------------- | ----------------------------------- | -------------------------------------------- |
| **Base**    | the installed plugin (spec, knowledge packs, cheat sheet) | plugin updates you accept           | refreshed                                    |
| **Tuning**  | `local/tuning.md`                                         | the retune loop, with your approval | **never touched**                            |
| **Private** | `local/memory/`, `local/preferences.md`                   | the coach, during use               | **never touched, never leaves your machine** |

Your tuning always wins over the base spec on conflict. Nothing in `local/`
is ever quoted into anything shared, synced, or PR'd. The people it remembers
from your work stories — the cast of characters — live in `local/memory/`
only, on your machine.

## Where your conversations go

Chat transcripts live in your Claude app's session history, like any session.
The _substance_ — decisions you made, positions it still disagrees with, open
threads, the people in your stories — is written to `local/memory/` as plain
markdown notes you can open, edit, or delete in any editor. That's what gives
the next session continuity.

## Retune

Correct it mid-conversation ("push harder", "shorter", "drop the opening
questions") and it applies the change immediately and logs it. Say **"retune"**
(or let the session wrap-up do it) and it proposes a concrete edit to your
`local/tuning.md`, applying only what you approve, with a changelog line.
Every dial in its calibration table — pushback level, length, critique mode,
all of it — is yours to move this way. If a change would help every user of
the skill — not just you — it will suggest promoting it upstream; that's
always your call.

## Updates and rollback

Updates arrive as plugin updates (`claude plugin update`). One current caveat:
the plugin cache is versioned, so after an update your `local/` folder must be
copied from the old version directory to the new one — until the installer
handles this automatically, do it by hand or ask your session to. Rollback is
reinstalling the previous version; your tuning and memory are safe either way.

## Living with output styles and other personas

A global output style (a "voice" applied to your whole session) layers on top
of the coach and may compress its formatting. For a deliberate working
session, the default style gives you its full format; casually triggering it
under another style is harmless — the substance survives, the formatting
tightens. Other skill-based personas coexist without interference: each is
dormant outside its own territory.
