# Pack: AI-product & agentic UX

> Researched: 2026-07-18 · Staleness threshold: 3 months
> Load me when: reviewing AI-infused product surfaces — dashboards or data apps with generated insights, forecasts, or auto-categorization; agent workflows with human approval gates; embedded chat/assistant features; RAG answers with citations; AI microcopy, loading, and error states.
> Also load for: autonomy-level decisions (how much the AI does vs. the user), confidence/uncertainty display, and shipping model or prompt changes to an existing user base.
> Audience: a reviewer citing these against artifacts built by a senior data engineer — expect strong pipelines, weak trust-calibration UX.

## Entries

### State what it can do and how well, at first contact
- **Claim:** Never ship an AI feature without a first-contact surface covering both capability (G1) and quality (G2). Hedging copy like "we think you'll like…" is a legitimate G2 calibration mechanism, not weakness — the paper uses it as a positive example.
- **Applies when:** Any AI feature a user meets cold — insights panels, auto-forecasts, in-app helpers — especially where it can be silently wrong.
- **Fails when:** Front-loading everything into an onboarding modal; users skip walls of caveats, so expectation-setting must be progressive and in-context. Weak for expert internal tools where users already know the failure profile.
- **Source:** Amershi et al., "Guidelines for Human-AI Interaction," CHI 2019 — https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf (verified: G1/G2 and the hedging example are in the paper), 2019

### Prefer structured controls over a blank chat box
- **Claim:** Where intent has known structure, scoped controls (date pickers, sliders, presets, editable parameters) beat a free-text box — "a date picker expresses temporal intent more precisely than any sentence," and a blank input offers no affordances, no constraint slots, no in-scope feedback.
- **Applies when:** Adding AI to dashboards, filters, report builders, or any workflow where valid requests are enumerable.
- **Fails when:** Genuinely open-ended, long-tail intent (exploratory Q&A, brainstorming) — chat legitimately wins there. And the market counter-evidence is real: chat's zero learning curve drove adoption, and the labs retrofitted GUI around chat rather than replacing it.
- **Source:** Amelia Wattenberger, "Why Chatbots Are Not the Future" — https://wattenberger.com/thoughts/boo-chatbots, 2023; corroborated by Adi Leviim via Roger Wong — https://rogerwong.me/2026/04/chat-box-wrong-ui-paradigm, 2026-04
- **Contested:** Leviim/Wong concede the pragmatic counter-position: chat shipped fastest and required no training; three years of retrofits (Canvas, Artifacts, Projects) show augmentation of chat, not abandonment.

### Show numeric confidence only if calibrated
- **Claim:** Don't render "87% confident" unless you can produce a reliability diagram for it. Miscalibrated confidence impairs appropriate reliance, users can't detect the miscalibration, and even disclosing the calibration level tanks trust into under-reliance without restoring decision quality.
- **Applies when:** Any urge to decorate predictions or recommendations with a percentage. If uncalibrated, prefer qualitative hedging ("low confidence — verify").
- **Fails when:** Genuinely calibrated, monitored systems in expert workflows — there, numeric confidence demonstrably helps (calibrated scores improved decision accuracy ~+20% vs ~+2% for miscalibrated in related 2025 reliance studies). Also fails in regulated/audit contexts that mandate exposing scores.
- **Source:** Lu (Li) et al., "Understanding the Effects of Miscalibrated AI Confidence on User Trust, Reliance, and Decision Efficacy" — https://arxiv.org/abs/2402.07632, 2024 (v4 2025)
- **Contested:** Enterprise HITL guidance (Aufait UX, https://www.aufaitux.com/blog/human-in-the-loop-ux/) still recommends confidence scores as first-class transparency and the routing signal for escalation; the live dispute is whether the score helps the user or merely transfers liability.

### Deep-link citations to the exact passage
- **Claim:** Citations must point to the exact passage/timestamp behind a specific claim, with hover previews, and must flag unavailable sources outright. A favicon row at the bottom of an answer is provenance theater.
- **Applies when:** Any AI output making factual or data-derived claims — RAG answers, dashboard insight text, portfolio-agent answers. Verification cost must approach zero because users won't pay more.
- **Fails when:** Discovery queries where collection-level links are more honest than false precision; creative output where citation is meaningless. And the pattern backfires when the summary misrepresents its own source — the citation then lends credibility to a hallucination (Shape of AI's own listed failure mode).
- **Source:** Emily Campbell, The Shape of AI, Citations pattern — https://www.shapeof.ai/patterns/citations, 2025
- **Contested:** NN/g (Chan, "Explainable AI in Chat Interfaces," 2025-12 — https://www.nngroup.com/articles/explainable-ai/) found users rarely click citations at all; their mere presence raises perceived trust without verification, so citations can act as trust inflation, not a verification aid.

### Treat narrated reasoning as rationalization, not audit log
- **Claim:** "Here's how I got this" walkthroughs from LLMs are frequently post-hoc rationalizations, unfaithful to the actual computation — never present them as an audit trail or let them drive sign-off.
- **Applies when:** Reviewing any show-your-work UI: chain-of-thought panels, "thinking…" expandables, explanation tooltips — anywhere the display feeds a trust or approval decision.
- **Fails when:** Agentic systems where the displayed steps ARE the actions taken — tool calls, queries executed, files edited. That log is genuine provenance and should be shown. The critique targets narration, not action telemetry.
- **Source:** Megan Chan, "Explainable AI in Chat Interfaces," Nielsen Norman Group — https://www.nngroup.com/articles/explainable-ai/, 2025-12

### Gate approvals on blast radius, and make every gate context-rich
- **Claim:** Confirmation checkpoints belong at irreversibility and external side effects, not at "the AI did it" — per-step approval breeds rubber-stamping, which defeats the checkpoint. And each surviving gate must carry reason, impact, and urgency; a bare "Allow? [Y/N]" is a liability transfer, not a control. Pair with visible undo so approval isn't the only safety net.
- **Applies when:** Agent workflows, automation in data apps (schema changes, sent reports), HITL review queues. Route by risk: low-risk proceeds, uncertain or high-impact escalates.
- **Fails when:** Pre-trust-calibration (early product life) more gates are warranted; compliance can mandate per-action sign-off regardless of fatigue; and if the risk classification is itself model-made and wrong, the gate is fiction — make the routing deterministic where possible. High-frequency operator consoles do better with batch review, diffs-before-apply, and post-hoc audit than verbose per-action dialogs.
- **Source:** Aufait UX, "Human in the Loop UX for Enterprise Systems" (Confidence-Based Escalation; Context-Rich Alerts) — https://www.aufaitux.com/blog/human-in-the-loop-ux/, 2026

### Label AI output provisional until a human accepts it
- **Claim:** Mark machine output "draft" / "suggested" / "pending review" until accepted — the label declares that human judgment completes the work and visually separates guesses from committed facts.
- **Applies when:** AI content entering a system of record: auto-categorized transactions, generated SQL, drafted messages, auto-filled fields — especially sitting at equal visual weight beside real data.
- **Fails when:** High-volume low-stakes suggestions, where a universal "draft" badge trains users to ignore it; and fully-automated pipelines no human will ever review — a permanent draft badge there is dishonest.
- **Source:** Aufait UX, "Human in the Loop UX" (Provisional AI States) — https://www.aufaitux.com/blog/human-in-the-loop-ux/, 2026

### Stream real work; optimize time-to-first-token
- **Claim:** Past a couple of seconds, stream — tokens, tool calls, and intermediate steps rendered progressively. Users judge perceived latency, and TTFT is the dominant perceived-performance signal (~200–500ms streamed vs. 5–30s spinner). For multi-minute agent runs, prefer async + notify over any live-wait UI.
- **Applies when:** Chat agents, long generation, agent runs in data apps.
- **Fails when:** Sub-second operations (streaming adds jitter for nothing); outputs a user might act on half-rendered — a partially streamed number reads as final; and outputs needing validation before display (executable code, rendered charts) should buffer then show. Streaming raw "reasoning" inherits the faithfulness problem — stream actions, not narration.
- **Source:** AWS Well-Architected, Agentic AI Lens AGENTPERF02-BP04 — https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentperf02-bp04.html, 2026; NiteAgent, "Streaming Agent Responses in Production" — https://niteagent.com/blog/2026-07-09-streaming-agent-responses-production-guide/, 2026-07

### Design failure paths by perceived error type — and always hand back control
- **Claim:** Sort failures by how the user perceives them — context errors (system worked, user expected otherwise), failstates (true capability limits), background errors (silent malfunction) — and give every visible failure a path forward, usually returning manual control. Failure should feel "safe, boring, and a natural part" of the product. A refusal that dead-ends converts one failed request into feature abandonment: state the limit, offer the manual path or narrower query.
- **Applies when:** Reviewing any AI feature's error handling — timeout, garbage output, confident wrongness, outage. Refusal copy is an expectation-setting surface: it teaches scope.
- **Fails when:** Background errors can't be UX'd — they need monitoring and QA; polishing the visible path does nothing for them. The taxonomy predates generative AI: hallucination is a success-shaped failure that fits none of the three buckets — don't force it. And safety refusals shouldn't over-explain the boundary (it's a probing vector).
- **Source:** Google PAIR, People + AI Guidebook, "Errors + Graceful Failure" — https://pair.withgoogle.com/chapter/errors-failing/, 2019 (maintained since)

### Make dismissal one gesture, correction inline
- **Claim:** If ignoring or fixing a suggestion costs more than the suggestion saves, the feature is net-negative and will get turned off. Every suggestion needs an obvious "not this" (G8) and an editable "almost — fix here" (G9), no retyping from scratch.
- **Applies when:** Auto-complete, auto-categorization, suggested filters/insights, generated text anywhere. Test: can the user dismiss without breaking flow and correct without starting over?
- **Fails when:** Dense UIs where correction chrome becomes clutter; high-accuracy background features don't warrant it — scale the affordance investment with error rate × error cost.
- **Source:** Amershi et al., CHI 2019, G8–G9 — https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf, 2019

### Scale explanation depth to stakes — and to surprise
- **Claim:** "Why did it do that" (G11) is essential in consequential domains but demonstrably less important for low-cost scenarios like search ranking and recommendations (the paper's own Bunt et al. discussion) — don't pay the screen-space tax where a wrong answer costs nothing. A budgeting app's flagged transaction deserves G11; a "you might also like" shelf doesn't.
- **Applies when:** Deciding whether a dashboard insight, forecast, or recommendation needs an explanation panel.
- **Fails when:** Surprise, not stakes alone, triggers the need — even low-stakes features need explanation the moment behavior contradicts user expectation (context errors). Regulated domains mandate explanation regardless of this cost-benefit logic.
- **Source:** Amershi et al., CHI 2019, G11 + Bunt et al. discussion — https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf, 2019

### Cut anthropomorphic capability-inflation from microcopy
- **Claim:** First-person personas and "I'm thinking about your question…" inflate perceived intelligence and trust beyond what the system warrants. Prefer neutral, factual language about what the system is doing.
- **Applies when:** Loading states, refusals, explanations, empty states — especially where users make decisions on the output (data apps), not chat-for-entertainment.
- **Fails when:** Consumer products where persona IS the product; and mild hedging ("we think you'll like…") is endorsed by Amershi G2 as calibrating despite being grammatically anthropomorphic — the line is capability-inflation, not pronoun use.
- **Source:** Megan Chan, "Explainable AI in Chat Interfaces," Nielsen Norman Group — https://www.nngroup.com/articles/explainable-ai/, 2025-12
- **Contested:** The persona-led design school treats warmth and first-person voice as a deliberate trust-and-retention feature; NN/g's own hedging examples show some humanized language aids calibration.

### Avoid the automation no-man's-land — give levers on the artifact
- **Claim:** Between roughly 50% and 100% automation the human loses control while keeping responsibility — a "machine operator" babysitting output they can't shape. Prefer AI that supports direct manipulation of the artifact (targeted suggestions, editable output) over AI that replaces the making. A regenerate button is not a lever.
- **Applies when:** Setting an AI feature's autonomy level: code/SQL generation, report drafting, agent pipelines. If the user signs their name to the output, they need handles on the output itself.
- **Fails when:** Truly delegable, cheap-to-verify tasks (formatting, transcription, bulk classification with spot-checks) — full automation plus audit sampling beats keeping a human in the crafting loop. The argument is weakest where correctness is verifiable by inspection.
- **Source:** Amelia Wattenberger, "Why Chatbots Are Not the Future" — https://wattenberger.com/thoughts/boo-chatbots, 2023

### Don't let model swaps silently change behavior
- **Claim:** Update and adapt cautiously (G14), notify users about changes (G18): a model or prompt upgrade must not silently reshape an AI feature users have habituated to. Limit disruptive changes, keep stable UI anchors, announce capability shifts.
- **Applies when:** Shipping model swaps or prompt changes into a product with an existing user base — auto-categorization rules, ranking, suggestions users have built muscle memory around.
- **Fails when:** Security and correctness fixes ship immediately regardless of disruption; and pre-PMF products that freeze behavior for stability lock in a bad baseline — the guideline assumes a habituated audience.
- **Source:** Amershi et al., CHI 2019, G14 + G18 — https://www.microsoft.com/en-us/research/wp-content/uploads/2019/01/Guidelines-for-Human-AI-Interaction-camera-ready.pdf, 2019
