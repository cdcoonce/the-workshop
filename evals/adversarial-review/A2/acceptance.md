# A2 acceptance (private: scorer and maintainers only)

Never sent to a lens agent, to the no-skill reviewer, or to anyone dispatched. The
dispatch-safety guard refuses a prompt that carries any of it.

## What the case is

The merged diff of PR #896 with five injected defects, copied unchanged from the
terse-lens-contract A/B. Ground truth is `fixture/defects.json`; the saved replies
from that experiment sit in `ab_raws/`. Run inline: the conductor plays the skill's
conductor, dispatches three lens agents (domain, test veracity, spec conformance),
gives each the case prompt plus that lens from the skill's own PR-review reference,
and pools their findings for scoring. The case supplies no lens wording of its own,
and the domain lens is written by the conductor from the PR's ledger, never from
this file.

## Items

| Item | Defect | Kind | Location | Regex needs |
| --- | --- | --- | --- | --- |
| A2-D1 | the pushed-prefix helper returns one too many | gate candidate | script, lines 105-125 | the helper's name, or an off-by-one phrase near "prefix" |
| A2-D2 | ancestor test called with its two arguments swapped | gate candidate | script, lines 197-217 | the ancestry helper near a swap or inversion word, or the pushed flags near an inversion word |
| A2-D3 | collapse test asserts only a lower bound | trend, never gated | test file, lines 139-160 | a weak-assertion phrase |
| A2-D4 | edit to the other skill's command reference, which the spec says is untouched | gate candidate | file level (suffix only) | the other skill's name |
| A2-D5 | the specced guard for changes sitting in the index is absent | gate candidate | file level (suffix only) | a negator, a guard word and one of the three index words in one clause |

Every matcher is conjunctive: location and regex must both hit. There is no fallback
where one alone credits. The experiment's `score_arm.py` line 65 credited on either,
which is why it over-counted D3 (a D1 consequence landing inside D3's window) and D5
(a spec guard list that merely names the index words).

## Passing mentions of the index words

D5 is not credited by a finding that lists the spec's guards, names the guard's test,
or says the index is clean. Only a finding that says the guard is missing counts.

## No-skill arm

One plain reviewer, one pass over the whole diff, no lens split, given the case
prompt with any skill reference removed plus the do-not-invoke-skills line. Nothing
from the skill's own files may reach it, or the baseline stops being a baseline.

## Raws

The saved replies are for matcher development and the cross-match audit. They are
never calibration data. Admission of any gated item happens only when the hand-run
calibration issue executes this case itself.
