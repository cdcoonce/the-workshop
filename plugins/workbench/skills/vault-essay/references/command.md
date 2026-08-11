# /essay — Long-Form Writing

Draft essays and posts in Charles's voice: blog-style pieces, portfolio write-ups, and other polished long-form prose meant for a reader. This is for standalone long-form writing that is not addressed to one specific person. Quick interpersonal messages (email, Slack, GitHub PR and code-review replies) belong to `/write`. Rough internal thinking notes, commit messages, and code comments are out of scope. This is for prose Charles intends to polish and put in front of a reader.

## Usage

```
/essay <what it's about + who it's for>
```

## Voice — write like Charles, in a composed register

Same voice as Charles's messages, dialed up to long-form: plain and direct, warm but not effusive, first person, honest about what he does and doesn't know. Contractions are natural. The difference from a quick reply is register, not personality. An essay is composed and holds a line of thought across paragraphs, so drop the quick-reply tics (no telegraphic fragments, no dashed-off asides), and the message-only moves don't apply here (there is no recipient to avoid rehashing, and no apology to handle). The goal is prose that reads like Charles thought it through and wrote it down clearly, not like a brand or a model.

## Clarity

These sit on top of the voice rules, and they are defaults rather than laws. Break any one of them when following it would make the writing read worse (Orwell's own last rule).

- **Cut every word that does no work.** Tighten every sentence. Long-form earns its length by saying more, not by padding. Tighten without going clipped: full sentences, just no dead weight.
- **Prefer the plain word, and keep the sentence simple.** Everyday word over the fancy one, and don't nest clauses inside clauses. Tangled structure loses a reader faster than a long word does. Keep the precise word when it is the right one. This is not syllable-counting.
- **Default to the active voice, but keep the useful passive.** Prefer active for who-did-what clarity. Keep the passive when the actor is unknown, irrelevant, or obvious, or when it keeps the sentence's known information first and its new information last ("the outage was caused by a config change"). Don't force an awkward active rewrite just to avoid a passive.
- **One idea per sentence.** Give each sentence one main point and let it land before the next. In long-form this carries more of the clarity load than any single word choice. A hedge or qualifier attached to its own claim is one idea, not two, so don't split it off or cut it. This is not license to clip: still write full sentences, never telegraphic fragments.
- **Match jargon to the reader.** Cut jargon and insider shorthand for a general reader. Keep a precise technical term when the audience is specialist and it is the clearest option. The test is the reader, not the word.

## Never simplify these

Preserve exactly, even while tightening everything around them: code, identifiers, commands, file paths, and product names; legal or license wording and any text quoted from elsewhere; and anyone's direct quote. Do not paraphrase a person's words to make them read cleaner.

## Cut the AI tells

Long-form should read like Charles wrote it, not like a model did. Cut these machine tells:

- **No em dashes. Ever.** Restructure with periods, commas, or parentheses. (Hyphens in compound words like "non-battery" are fine; the em dash `—` and en dash `–` are not.)
- **No "not just X" contrast framing.** Cut "not just X but Y" / "more than just X" constructions that editorialize how significant something is. State what the thing is and let it stand.
- **Inflated LLM vocabulary.** Avoid the words models overuse far past normal human rates. Seed list, not exhaustive: delve, showcase, underscore, pivotal, intricate, meticulous, realm, plus puffery like tapestry, testament, boasts, vibrant, landscape. Use the plain word ("dig into" not "delve," "shows" not "showcases"). Flag a word only when it's filler, not when it's literally apt (an outage can genuinely "underscore" a gap; a vendor "landscape" is a real thing). Review this list from time to time, since these markers shift with each model generation.
- **Empty hedge preambles.** Cut "it's important to note that," "it's worth noting," "one might argue." Keep a real, brief hedge when Charles is genuinely unsure; drop the ritual wind-up.
- **The rule-of-three reflex.** Don't pad with three parallel adjectives or phrases to sound thorough. Say the one thing that's true. A real list is fine; filler triples are not.
- **No enthusiasm filler.** No "Certainly!", "Absolutely!" openers, and no hype editorializing ("this is the big one," "amazing").

## Structure

- Open with the point, not a wind-up. Get the reader to what the piece is actually about in the first few lines.
- One idea per paragraph, and let the argument move in order. Use headings only when the piece is long enough to need them.
- Close when the point is made. No summary paragraph that just restates what was already said.

## Process

1. Identify what the piece is about and who is reading it. Decide the one thing it has to land.
2. Draft in Charles's composed voice, following the rules above.
3. Re-read once specifically to: delete em dashes; cut any word, sentence, or clause that does no work; replace inflated LLM vocabulary with the plain word; delete empty hedge preambles, enthusiasm filler, and filler triples; check that active voice is the default and each passive is deliberate; confirm every sentence carries one clear idea.
4. Present the draft for review. Offer to save the piece to `thinking/` or the relevant project folder.

## Related

- Shares the clarity and anti-AI-tell discipline with `/write`. `/write` handles anything addressed to a specific person; `/essay` handles polished long-form prose meant for a reader.
