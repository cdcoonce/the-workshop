# Pack: Design-tool ecosystem

> Researched: 2026-07-18 · Staleness threshold: 3 months
> Load me when: Reviewing AI-generated UI (v0/Lovable/Bolt/Figma Make output) or any screen built by an engineer without a design counterpart; auditing design-system, token, or component-library decisions in a React/Tailwind codebase; judging whether a mock, prototype, or coded spike was the right fidelity for the question asked; evaluating agent-driven design-to-code workflows (Figma MCP, CLAUDE.md-style design context); deciding where Figma belongs in a code-first solo workflow.

## Entries

### Treat first-pass AI UI as distribution-shaped, not designed
- **Claim:** Prompt-to-UI output with no injected constraints is the statistical mean of the training data. A vague prompt ("clean modern dashboard") guarantees the consensus artifact. Flag on sight: purple-to-cyan gradients, glassmorphism with neon glow, six identical icon+heading+blurb cards in a row, missing focus states, WCAG contrast failures. The fix is constraints — tokens, type scale, real product context — not abandoning the tool.
- **Applies when:** Reviewing any v0/Lovable/Bolt/Figma Make first draft, or any UI where the prompt lacked an explicit design system; dashboards, landing pages, portfolios especially.
- **Fails when:** The consensus pattern is genuinely correct — data-dense dashboards and admin tools often SHOULD follow convention, and "avoid the generic look" pushed too hard produces novelty for its own sake. Also fails for throwaway internal demos where time-to-artifact beats differentiation.
- **Source:** Eduardo Calvo, "AI Design Slop," SmoothUI — https://smoothui.dev/blog/ai-design-slop — 2026-06-24 (verified 2026-07-18)

### Demand a closed critique loop, not a better prompt
- **Claim:** One-shot generation has no taste and no loop. A reviewer's leverage is forcing iteration against named criteria: build with guardrails → critique against an explicit written acceptance bar → fix the highest-impact issue → re-evaluate until it passes. Feed each caught error back into the project brief so it can't recur.
- **Applies when:** Any AI-assisted UI that will ship; writing the brief or CLAUDE.md-style design constraints for a coding agent; setting up review workflows for generated artifacts.
- **Fails when:** The acceptance criteria are themselves generic ("looks clean, modern") — then the loop converges on the same slop with extra steps. Also fails on disposable one-off mocks: infinite refinement there is fidelity spent on a question nobody asked.
- **Source:** Eduardo Calvo, SmoothUI — https://smoothui.dev/blog/ai-design-slop — 2026-06-24

### Assume generated UI is inaccessible until audited
- **Claim:** Never ship AI-generated UI without a dedicated accessibility pass. CHI 2025 research (arxiv.org/abs/2502.10884) found AI assistants systematically generate inaccessible markup; missing focus states and contrast failures are named slop tells; CodeRabbit's Dec 2025 analysis of 470 real PRs found AI-generated code carried 1.7× more issues and 2.74× more security vulnerabilities.
- **Applies when:** Any generated component headed to production — especially interactive custom UI (modals, menus, form controls) and dark-theme dashboards where contrast failures hide.
- **Fails when:** Per-tool variation is real: tools scaffolding on accessible primitives (v0 on shadcn/Radix) inherit correct semantics for standard components, so blanket suspicion wastes review time on solved patterns — risk concentrates in custom, non-primitive UI. Single-user internal tools may legitimately deprioritize full WCAG conformance.
- **Source:** Eduardo Calvo, SmoothUI (citing CHI 2025 + CodeRabbit 470-PR analysis) — https://smoothui.dev/blog/ai-design-slop — 2026-06-24
- **Contested:** Marc Andrews' 2026 v0 review (https://marcandrews.com/v0-by-vercel-review-2026-ai-powered-react-ui-generator/) reports v0 emits accessible, TypeScript-typed components by default that he ships to clients with minimal edits — the dispute is scoped to primitive-based tools, not custom UI.

### Start the design system in the repo, not in Figma
- **Claim:** Solo or pre-PMF: shadcn/ui + Tailwind, real components rendering in the real app, back-fill Figma only if a stakeholder needs it. "Pre-PMF UI keeps changing. A system you maintain is pure overhead" — shadcn's copy-into-repo model eliminates version management; building on MUI or from scratch are both anti-patterns at this scale.
- **Applies when:** Solo engineer-designer starting a dashboard, data app, or side project; pre-PMF; React/Next stack; no design counterpart.
- **Fails when:** Multi-brand platforms (atomic tokens + headless Radix/React Aria instead); enterprise scale — shadcn lacks governance (version pinning, deprecation, RFC process) and is explicitly warned against as a 100+ engineer foundation; marketing-only sites (brand kit, no component library); and when non-coding stakeholders must align before build — then Figma is the alignment surface.
- **Source:** Kiryl Zhukouski, "Which design system to build on," DesignSystems.one — https://www.designsystems.one/design-systems/which-one — 2026 (verified 2026-07-18)

### Own a semantic token layer above whatever you adopt
- **Claim:** Semantic names (`--color-action-primary`, `--color-surface-secondary`), not literal ones (`--color-blue-500`). In Tailwind v4, define tokens CSS-first via `@theme` / CSS variables, not a JS config. Three layers — primitive → semantic → component — so a rebrand or theme flip is a one-variable edit.
- **Applies when:** Any project living past a month; anything needing dark mode; any codebase an agent will extend — semantic tokens are the constraint vocabulary you feed the agent.
- **Fails when:** Full three-layer ceremony on a single-page portfolio is overhead — start base+semantic, add the component layer when variants multiply. And the layer is documentation theater if raw hex keeps leaking into components with nobody enforcing it.
- **Source:** Mavik Labs, "Design Tokens That Scale in 2026 (Tailwind v4 + CSS Variables)" — https://www.maviklabs.com/blog/design-tokens-tailwind-v4-2026/ — 2026-01-20 (updated 2026-01-27)

### Match artifact fidelity to the learning goal
- **Claim:** Before choosing mock vs prototype vs code, ask five questions: what question are we answering? where in the lifecycle? what resources? who gives feedback? what's the mis-feedback risk? Low-fi for concept/flow questions with internal audiences; high-fi for usability detail, investors, non-technical clients. Validate structure before spending on polish — a polished artifact makes stakeholders "think the product is ready to ship because it looks real."
- **Applies when:** Deciding whether a feature needs a Figma mock, clickable prototype, or coded spike; reviewing whether someone burned a week polishing an unvalidated flow.
- **Fails when:** "Lo-fi first" fails when the audience can't read wireframes — polish IS the question for consumer-app first impressions. And for a solo builder whose component system covers most of the surface, the intermediate rungs may add no information (that escape hatch is my extrapolation, not Dhanwani's — he argues the gradual ladder).
- **Source:** Robin Dhanwani, "Low Fidelity vs. High Fidelity Prototypes," Parallel — https://www.parallelhq.com/blog/low-fidelity-vs-high-fidelity-prototypes — 2026-05-15

### Default to designing in code when you own the system
- **Claim:** An engineer-designer with a working component system should design directly in code and skip static mocks — converting between two representations of the same idea "is never lossless," and you iterate on the real thing instead of a picture of it. The prerequisite is written design clarity (CLAUDE.md-style system docs): "The barrier was never code. It was always clarity."
- **Applies when:** Solo work where you are designer and implementer; token/component system covers most of the surface; flows and states matter more than novel visual direction (dashboards, CRUD, settings).
- **Fails when:** Genuinely new visual territory — code commits you to structure early, and ten cheap canvas variations beat one coded direction; when stakeholders must align before build; and for motion/visual-polish exploration where canvas iteration is faster.
- **Source:** Dheepak Narayan, "Can Designers Skip Figma and Work Directly in Code?," Medium — https://dheepaknarayan.medium.com/can-designers-skip-figma-and-work-directly-in-code-5b16e90b12fa — 2026-03-17
- **Contested:** Robin Dhanwani (Parallel, 2026-05) argues the direct counter-position — gradual low→high fidelity so structure is validated before refinement, because polished artifacts invite the wrong feedback too early.

### Pick prompt-to-UI tools by job, plan the graduation path up front
- **Claim:** v0 for individual components (opinionated React/Tailwind/shadcn; GitHub export is one-way); Lovable as default full-stack workshop (bi-directional GitHub sync is the differentiator); Bolt/Replit when you need framework flexibility (Angular, Vue, React Native); Magic Patterns for side-by-side variation exploration; graduate to Cursor/Claude Code the moment complexity exceeds the platform ceiling.
- **Applies when:** Starting a prototype and choosing where; diagnosing someone stuck fighting a low-code platform past its ceiling; React-ecosystem work.
- **Fails when:** Arteeva's own meta-principle undercuts rigid matching — "once you master one of them, you become proficient in any other… just pick the option that smiles at you." Tool-hopping has real switching costs solo, and off the React stack most of the matrix collapses. Source is ~8 months old in a fast-moving category — re-verify specific tool capabilities before citing them.
- **Source:** Anna Arteeva, "Choosing your AI prototyping stack," Medium — https://annaarteeva.medium.com/choosing-your-ai-prototyping-stack-lovable-v0-bolt-replit-cursor-magic-patterns-compared-9a5194f163e9 — 2025-11-22

### Scope v0 to the component/page level
- **Claim:** v0 is a specialized text-to-UI converter, not a general coding assistant. The classic misuse is expecting backend wiring, databases, auth, or app-state logic — it doesn't do them. Scope it to React component/page generation and hand the rest to a real coding agent.
- **Applies when:** Evaluating v0 output that includes data fetching, auth, or multi-screen state; deciding whether a v0 artifact is a starting point or a deliverable.
- **Fails when:** The "prototype-only" framing overcorrects: v0 emits typed components on shadcn primitives that reviewers ship to clients with minimal edits — dismissing the output as throwaway means pointlessly rewriting decent code. The quality boundary is the component level; even the favorable review concedes complex state logic and API integration "needs substantial reworking."
- **Source:** Trickle, "Vercel v0 Review 2025: What Most Developers Get Wrong About It" — https://trickle.so/blog/vercel-v0-review — 2025-08-17
- **Contested:** Marc Andrews, "V0 By Vercel Review 2026" — output is not throwaway, best-in-class for React UI generation (https://marcandrews.com/v0-by-vercel-review-2026-ai-powered-react-ui-generator/).

### Only run Figma MCP against structured files
- **Claim:** Design-to-code via the Figma MCP server pays off only on structured files — auto layout, real components, variables, Code Connect mappings to your codebase. It hands the agent the node tree and token definitions instead of a flat screenshot; without design-system foundations the agent misuses components and creatively generates one-off styles anyway.
- **Applies when:** You maintain both a Figma file and a codebase and want agents implementing designs; workflows where the Figma file is genuinely the source of truth.
- **Fails when:** Requires a paid Dev Mode plan and real setup burden — for a solo dev with a loose file, pasting a screenshot into a coding agent is better ROI. Hard limit: the agent has no visibility into its own rendered output, so MCP context never replaces human visual QA in the browser.
- **Source:** Alice Moore, "Design to Code with the Figma MCP Server," Builder.io — https://www.builder.io/blog/figma-mcp-server — 2025-07-03, updated 2025-11-18

### Give agents design context as repo files, not longer prompts
- **Claim:** A markdown design-reference doc the agent reads on every conversion, component READMEs with usage examples ("2–3 examples can anchor the model"), explicit file locations, and annotations for behavior the node tree can't express. Anchoring in the repo beats re-explaining in chat.
- **Applies when:** Any AI-assisted UI implementation, with or without Figma; diagnosing why an agent keeps inventing off-system styles.
- **Fails when:** Stale docs are worse than none — a README that no longer matches the component API actively misleads the agent, so this carries a maintenance obligation. For one-off throwaway projects the documentation overhead exceeds the payoff.
- **Source:** Alice Moore, Builder.io — https://www.builder.io/blog/figma-mcp-server — 2025-07-03, updated 2025-11-18

### Make the design system AI-readable
- **Claim:** Agents are now first-class consumers of the system: plain TSX components (not heavily abstracted wrappers), MDX documentation, tokens in the W3C .tokens.json format — "formats that Cursor, Claude Code, and v0 can actually consume." Buy components; build product-specific patterns — differentiation lives in your patterns, not re-implemented buttons.
- **Applies when:** Building or refactoring a component library in 2025–26; choosing between headless kit and styled framework; preparing a codebase for heavy agent-driven UI work.
- **Fails when:** W3C tokens tooling is still maturing — an export pipeline nobody consumes is ceremony. And the same author caps it: pre-PMF, maintaining any system is overhead, so "AI-readable system" is a scale-up move, not a day-one one.
- **Source:** Kiryl Zhukouski, DesignSystems.one — https://www.designsystems.one/design-systems/which-one — 2026

### Don't write Figma off — but treat code as the artifact
- **Claim:** Figma's 2026 bet is canvas/code convergence and its remaining moat is the multiplayer alignment surface. Config 2026 (June 24) shipped Code Layers (any layer ↔ interactive code), Figma Motion (timeline animation exporting CSS/JSON/React), and agent Skills/Connectors; Figma Make's May 2026 beta connects to live Git repos and opens real PRs. Use Figma where shared visual thinking happens; land production work in the repo.
- **Applies when:** Deciding whether Figma stays in a 2026 workflow; motion design, stakeholder walkthroughs, team-visible exploration; evaluating "Figma is dead" rhetoric against your context.
- **Fails when:** Solo work with no stakeholders — the alignment value evaporates and code-first is simpler. Make's generated code was "awkward to reuse outside Figma" as of late 2025; the May 2026 Git/PR beta targets exactly that weakness, so re-test rather than cite the old verdict. Trust caveat: a proposed class action filed 2025-11-21 (N.D. Cal.) alleges Figma silently enrolled users in AI training on proprietary designs — Figma denies it, but it's relevant when client work is confidential.
- **Source:** Figma, "Config 2026 Recap" — https://www.figma.com/blog/config-2026-recap/ — 2026-06-24; Make Git beta: VentureBeat — https://venturebeat.com/technology/are-designers-the-new-swes-figma-makes-new-two-way-github-integration-turns-designs-into-live-production-code-with-built-in-governance — 2026-05; lawsuit: Bloomberg Law — https://news.bloomberglaw.com/litigation/figma-trained-ai-on-user-data-without-consent-class-action-says — 2025-11
- **Contested:** The skip-Figma camp (Narayan, 2026-03) — translation between representations is never lossless, so iterate on the real product instead; the moat argument only holds where multiplayer alignment actually happens.

### Never sign off without empty, error, and loading states
- **Claim:** "Undesigned empty and error states" is a named AI-slop tell — generated screens reliably show only the happy path. For data products this is doubly binding: empty, loading, and error are common real states, not edge cases, on any API-backed view.
- **Applies when:** Reviewing any dashboard, data app, or mobile screen before ship; auditing AI-generated screens; views where latency and failure are routine.
- **Fails when:** Disposable concept demos where only the happy path is under discussion — full state coverage there is fidelity spent on the wrong question. Prioritize by realistic frequency: a rarely-empty admin table doesn't need first-run-mobile-screen investment.
- **Source:** Eduardo Calvo, SmoothUI — https://smoothui.dev/blog/ai-design-slop — 2026-06-24
