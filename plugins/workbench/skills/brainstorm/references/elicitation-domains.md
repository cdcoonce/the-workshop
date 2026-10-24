# Elicitation Domains

The areas a brainstorm interview covers before any option appears. Order
them to the idea: start where the user's energy is, and work outward.
Skip a domain the codebase or the conversation already answered.

Each domain lists starter questions. Use them as prompts for your own
specific question, never as a list to paste. Ask one, listen, follow up,
then move on.

---

## Domain 1: Trigger

Why this, why now?

- What happened that made you want to work on this now?
- Walk me through the last time this came up. What were you doing?
- What happens if nobody does anything about it for six months?

**Listen for:** the real problem behind the stated one, and urgency.

## Domain 2: People

Who feels this, and who has a say?

- Who runs into this most? Is it you?
- Who else would notice if it changed, for better or worse?
- Whose approval or buy-in does a fix need?

**Multiple choice works:** "Who hits this most?" with the known roles as
options.

## Domain 3: Current State

How does it work today, warts and all?

- How do you handle it today? Walk me through the steps.
- What's the workaround, and what does it cost you each time?
- Where does the current way break down?

**Listen for:** workarounds. A workaround is a solution the user already
believes in.

## Domain 4: Desired Outcome

What does better look like?

- If this were solved, what would you notice first?
- How would you know it worked, a month after it shipped?
- What would make a fix a failure, even if it technically works?

**Listen for:** a success signal you could check, not a feeling.

## Domain 5: Constraints and Appetite

What bounds the answer?

- How much time is this problem worth to you: an afternoon, a week, a
  month?
- What can't change: tools, data, people, budget?
- Is there anything you've already ruled out, and why?

**Multiple choice works:** appetite as options (an afternoon, a week, a
month, open-ended).

## Domain 6: Their Ideas

What does the user already think? Always ask this domain, and always
open-ended.

- What have you already tried or considered, even half-way?
- What's your gut telling you to do?
- If you had to ship something by Friday, what would you build?
- What's an idea you'd never pitch because it sounds too big or too
  dumb?

**Listen for:** ideas mentioned in passing in earlier answers. Read them
back here so they count.

---

## Follow-up Techniques

- **Ladder up:** "Why does that matter?" Repeat until you reach the goal
  under the request.
- **Ladder down:** "Can you give me an example?" Repeat until you reach a
  concrete instance.
- **Name the vague word:** "When you say 'messy', what does messy look
  like here?"
- **Quantify:** "How often? How long does it take? How many people?"
- **Contrast:** "What's different about the times it works fine?"

## Anti-patterns

| Don't                                                 | Instead                                                     |
| ----------------------------------------------------- | ----------------------------------------------------------- |
| "Tell me everything you're thinking about this."      | One specific question from the domain with the most energy. |
| "Anything else?"                                      | Name the gap: "You haven't said who maintains it."          |
| "Wouldn't a cache fix this?" (leading)                | "What have you tried for the slowness?"                     |
| "Who uses it and how often and what breaks?" (double) | Three questions, three messages.                            |
| Options that are solutions during elicitation         | Options that describe the problem space.                    |
