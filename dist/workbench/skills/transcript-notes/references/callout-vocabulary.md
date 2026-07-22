# Callout Vocabulary

The reconstruction pass (SKILL.md Step 3) maps the transcript's logical blocks
onto Obsidian callouts. Obsidian renders unknown callout types with a default
style, so custom types are safe and self-documenting. Use the same machinery for
every content kind; only the labels flex.

## Block callouts

Tag each block of the transcript with one callout. Put the block's type in the
callout title so the eye can navigate:

```markdown
> [!definition] Attention
> Attention maps a query and a set of key-value pairs to an output...

> [!derivation] Scaling the dot product
> We divide by the square root of the key dimension because...

> [!claim] Softmax saturates on large logits
> ...

> [!example] Two-token sequence
> ...
```

**Lecture vocabulary (default):** `setup`, `definition`, `derivation`, `claim`,
`example`, `aside`.

**Flex for non-lectures — keep the callout machinery, change the labels:**

| Content       | Suggested block labels                          |
| ------------- | ----------------------------------------------- |
| Lecture/talk  | setup, definition, derivation, claim, example   |
| Interview     | question, answer, point, aside                  |
| Panel         | question, point, disagreement, aside            |
| Demo/tutorial | step, result, gotcha, aside                     |

Render `aside` quietly — it is a kept tangent, not part of the spine. Drop pure
filler (verbal tics, dead air, admin chatter that carries nothing) silently
rather than making it an aside.

## Structural callouts

Two callouts are not block types but reading aids:

```markdown
> [!ask] What problem is this section solving?
> One line at the START of each section, phrased for that section. Bakes active
> reading into the page.

> [!gap] Missing visual (~12:30)
> The speaker referenced a plot here — most likely a loss curve over training
> steps. Jump to the source to see it.
```

Every "as you can see here" / "this plot" / "on the board" reference in the
cleaned text becomes a `[!gap]`, with an approximate timestamp when inferable.
State the likely type and role only — never fabricate a detailed description.

## Equations

Display math uses `$$…$$` with a one-line italic gloss immediately beneath:

```markdown
$$\text{Attention}(Q,K,V) = \text{softmax}\!\left(\frac{QK^\top}{\sqrt{d_k}}\right)V$$
*Divide by $\sqrt{d_k}$ so large dot products don't saturate the softmax.*
```

When the spoken math is too mangled to reconstruct with confidence, render the
best guess and mark it explicitly rather than presenting a guess as certain:

```markdown
$$\nabla_\theta \mathcal{L} = \dots$$
*Reconstruction uncertain — the audio here was garbled; verify against the source.*
```

Never silently invent math. Use the field's standard notation even when the ASR
text differs.
