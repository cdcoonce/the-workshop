All key sources verified. Findings applied: the 5-7 KPI figure appears in neither cited source (dropped, replaced with verified guidance), the HBS article says bagels/doughnuts not bananas (corrected), the Cortesi "one solution, multiple opportunities" friction is not in her article (replaced with her verified findings), and the Kozyrkov entry is re-anchored on the verified podcast content. Ulwick/Strategyn dispute confirmed live, so milkshake-JTBD stays contested. The two-schools JTBD point is folded into the milkshake entry's contested note. Final pack:

# Pack: Product discovery & user outcomes

> Researched: 2026-07-18 · Staleness threshold: 18 months
> Load me when: Reviewing dashboards, data apps, internal data platforms, or portfolio/side projects for whether they serve a real user need — not just whether they're well-built.
> Also load for: roadmap/spec/backlog critique (outputs dressed as outcomes), adoption post-mortems (built it, nobody came), MVP scope reviews, and any artifact whose success criterion is "ship it."
> The audience artifact-maker is a senior data engineer: expect technically excellent things with undefined users, undefined decisions, and undefined behavior change. These entries are the counter-pressure.

## Entries

### Ask what job the artifact is hired for
- **Claim:** Review every artifact by asking what job the user "hires" it for — and define its competition by the job, not the category. Christensen's milkshake study found the commuter milkshake competing with bagels and doughnuts against a boring commute, not with other milkshakes; a dashboard's real competitor is often a Slack DM to the analyst, not another dashboard.
- **Applies when:** Deciding whether a dashboard, data app, or portfolio page should exist at all; diagnosing flat adoption despite feature improvements; asking what users do instead.
- **Fails when:** Job narratives applied loosely are unfalsifiable — if the hypothesized job fails to predict behavior, the analyst just re-narrates the job. A job statement with no specified disconfirming observation is storytelling. Also weak where usage is mandated (users can't "fire" the tool).
- **Source:** "Clay Christensen's Milkshake Marketing," HBS Working Knowledge, https://www.library.hbs.edu/working-knowledge/clay-christensens-milkshake-marketing, 2011-02
- **Contested:** Ulwick/Strategyn calls milkshake marketing methodologically flawed ("Market Segmentation is Soured by Milkshake Marketing," https://strategyn.com/market-segmentation-is-soured-by-milkshake-marketing/) and fought Klement over it directly ("Alan Klement's War On Jobs-To-Be-Done," https://jobs-to-be-done.com/alan-klements-war-on-jobs-to-be-done-dad8eaed567c, 2017). There are two rival JTBD schools — Ulwick's jobs-as-activities vs Christensen/Moesta's jobs-as-progress (Klement, "Know the Two — Very — Different Interpretations of Jobs to be Done," https://jtbd.info/know-the-two-very-different-interpretations-of-jobs-to-be-done-5a18b748bd89, ~2016) — so never cite "JTBD" without saying which one you mean.

### Define success as a behavior change, not a delivery
- **Claim:** Seiden's definition: an outcome is "a change in human behavior that drives business results." A shipped dashboard is an output; "the ops lead stops exporting to Excel and makes the staffing call in the tool" is an outcome. Force the question: whose behavior, from what, to what, observable how?
- **Applies when:** Reviewing roadmaps, README goals, launch criteria; any success statement phrased as "ship X by Q3."
- **Fails when:** Low-uncertainty, high-prescription work (compliance rendering, deterministic migration, contractual deliverable) where the output IS the commitment; and orgs that mandate outcome-OKRs without strategic coherence, where they degrade into process theater nobody re-checks.
- **Source:** Josh Seiden, Outcomes Over Output (2019); overview at https://www.shortform.com/blog/outcomes-over-output/
- **Contested:** John Cutler, "Beyond Outcomes Over Outputs" (https://medium.com/hackernoon/beyond-outcomes-over-outputs-6b2677044214, 2018-05): the mantra oversimplifies — the real problems are strategy coherence, trust, and connecting work across time horizons.

### Match the mandate to the uncertainty
- **Claim:** Place each piece of work on Cutler's mission spectrum — from "build exactly this" through "solve this customer problem" up to "generate this long-term business outcome" — instead of reflexively demanding outcome-framing for everything. A portfolio site can honestly be "build exactly this"; a metrics dashboard should be "optimize this metric" with the metric named.
- **Applies when:** Portfolio triage and scoping reviews; deciding how hard to push outcome-framing on a given artifact.
- **Fails when:** Used as a permission slip to stay at "build exactly this" forever — Cutler's own failure modes still bite: context blindness (work unlinked to any larger bet) and the measurement gap ("Does anyone ever go back and check whether hitting the OKRs made any difference?").
- **Source:** John Cutler, "Beyond Outcomes Over Outputs," https://medium.com/hackernoon/beyond-outcomes-over-outputs-6b2677044214, 2018-05

### Treat shipping-volume praise as a smell
- **Claim:** Cutler's feature factory: teams rewarded for outputs shipped rather than for moving a named metric or retiring a problem. In review, ask which shipped artifact changed which number — if the answer is a list of features, the process is the defect, not the UI.
- **Applies when:** Reviewing a body of work (a quarter of dashboard releases, an app changelog, a project portfolio); changelog reads as pure feature enumeration with no observed effect.
- **Fails when:** Early greenfield where instrumentation doesn't exist yet and output-counting is honest scaffolding; small-n internal tools where metric movement is statistically meaningless and a user's changed workflow is the right receipt. Cutler himself allows a deliberate feature factory "while explaining the bet and hypothesis."
- **Source:** John Cutler, "Why Outcomes Over Outputs?", Amplitude, https://amplitude.com/blog/why-outcomes-over-outputs, 2019-01 (feature factory coined by Cutler, 2016)

### Root discovery in a product outcome the team can move
- **Claim:** Anchor discovery on one product outcome at the root of an opportunity solution tree — a metric directly within the team's control (e.g., "weekly active decision-makers in the tool"), not a lagging business outcome like revenue. Everything must trace: outcome → opportunity → solution → assumption test. A feature that can't be placed on the tree is a pet feature.
- **Applies when:** Structuring discovery for anything with real users; auditing whether a proposed feature connects to any stated outcome.
- **Fails when:** The tree is starved of evidence — an OST fed quarterly is decoration, not discovery. Practitioner data (Cortesi) adds: big trees induce FOMO-driven abandonment of opportunities before solutions ship, and quarterly OKR cycles fight solutions needing 6-month behavioral change horizons.
- **Source:** Teresa Torres, "Opportunity Solution Trees: Visualize Your Discovery," https://www.producttalk.org/opportunity-solution-trees/, 2016 (updated 2023); counterweight: Francesca Cortesi, https://www.francescacortesi.com/blog/the-importance-of-discovering-solutions-beyond-opportunities-our-learnings-with-the-opportunity-solution-tree

### Reject opportunities that admit only one solution
- **Claim:** Torres's litmus test, verbatim: "Is there more than one way to address this opportunity?" If not, it's a solution in an opportunity costume. "Users need a dark mode toggle" is a solution; "users work in low-light ops rooms at night" is an opportunity.
- **Applies when:** Reviewing requirement docs, issue titles, backlog items; any "user need" that names a UI control or a technology.
- **Fails when:** Genuinely constrained work — compliance mandate, contractual spec, platform deprecation — where the solution is fixed by decree; opportunity ceremony there is pure overhead. Also fails when opportunities are invented at the whiteboard: Torres requires they emerge from story-based interviews, not brainstorms.
- **Source:** Teresa Torres, Product Talk OST guide, https://www.producttalk.org/opportunity-solution-trees/, 2016 (updated 2023)

### Compare at least three solutions before building one
- **Claim:** Evaluate multiple candidate solutions against one target opportunity before building any — Torres: "when we compare and contrast our options, we make better decisions." The reviewer's question for any built thing: "what two alternatives did you reject, and why?"
- **Applies when:** Any non-trivial build decision — chart type for a key view, information architecture for a data app, navigation model for a mobile app.
- **Fails when:** Cheap, reversible changes where generating alternatives costs more than shipping wrong and correcting; and when it becomes ideation theater — Cortesi's teams only converged on shipped value after spending at least double the time on the solution side of the tree.
- **Source:** Teresa Torres, https://www.producttalk.org/opportunity-solution-trees/; Francesca Cortesi, https://www.francescacortesi.com/blog/the-importance-of-discovering-solutions-beyond-opportunities-our-learnings-with-the-opportunity-solution-tree

### Ground opportunities in story-based interviews, not opinions
- **Claim:** Torres's prerequisite is three to four "excavate the story" interviews (what happened first? then what?) before mapping the opportunity space — and her named failure mode is reshuffling priorities around the most recent complaint, sales call, or support ticket.
- **Applies when:** Any artifact with reachable users; a redesign justified by "someone complained about X last week" — ask whether that's one data point or a pattern.
- **Fails when:** Internal tools with five total users — weekly interview cadence exhausts the pool in a month; substitute direct observation (watch the Monday standup where the dashboard is read), telemetry, and periodic check-ins. Continuous-interview dogma on tiny populations produces fatigue, not insight.
- **Source:** Teresa Torres, https://www.producttalk.org/opportunity-solution-trees/ (habits detailed in Continuous Discovery Habits, 2021)

### Treat internal data consumers as customers
- **Claim:** "A data warehouse is really just a codebase... serving internal customers like other analysts, data scientists, and product managers." Full apparatus: named stakeholders partnered early, scoping docs written like specs, SLAs, and health metrics for the data product itself (incidents, time-to-detection, time-to-resolution). Someone must own the reliability contract.
- **Applies when:** Reviewing a data platform, pipeline-backed dashboard, or internal data app built for colleagues; checking whether consumers were consulted before build.
- **Fails when:** One-person data teams where full product ceremony outweighs delivered value — right-size to a lightweight scoping doc plus one health check. And "self-service" framing quietly shifts the interpretation burden onto non-technical users, who then misread data with confidence.
- **Source:** Monte Carlo, "How To Treat Your Data As A Product" (practitioners at Convoy, Uber, Retool, Ironclad, SeatGeek, Toast), https://montecarlo.ai/blog-how-to-treat-your-data-as-a-product/, updated 2024-07

### Start every dashboard with the decision, not the data
- **Claim:** Kozyrkov's line: data-driven means decision criteria are set before looking at the data; otherwise you're merely data-inspired, ratifying a choice already made. Decisions under uncertainty ("no do-overs") and data-mining for inspiration are different activities needing different artifacts. Opening review question: name a decision someone made differently last month because of this view. A dashboard with no nameable downstream decision is a poster.
- **Applies when:** Reviewing any KPI dashboard, metrics page, or recurring report.
- **Fails when:** Genuinely exploratory surfaces whose stated job IS inspiration and anomaly-hunting — judging drill-down tools by decision-per-view is a category error; and monitoring dashboards where the decision is exception-triggered and correctly dormant most days.
- **Source:** Cassie Kozyrkov, "Decision Intelligence," Google Cloud Platform Podcast ep. 128, https://www.gcppodcast.com/post/episode-128-decision-intelligence-with-cassie-kozyrkov/, 2018-05

### Ask who opens this page, when, and why — before any pixel critique
- **Claim:** Audience role determines dashboard genre — operational (shift managers, SREs), analytical (analysts), strategic (executives), tactical (squad leads) — which dictates density, refresh cadence, and depth. Working limits: the core view fits one laptop screen, and it must answer the team's top two questions in ten seconds. The "for everyone" dashboard is the canonical failure — one artifact serving three audiences serves none.
- **Applies when:** First-pass review of any dashboard or data-app screen.
- **Fails when:** The screen/ten-second heuristics are calibration, not law — dense operational walls for expert monitoring teams legitimately break them; and genre labels fail for hybrid tools where one user shifts modes (monitor → investigate) and needs a designed path between modes, not two separate dashboards.
- **Source:** UXPin, "Dashboard Design Principles: The Definitive Guide," https://www.uxpin.com/studio/blog/dashboard-design-principles/, 2026-06; DataCamp, https://www.datacamp.com/tutorial/dashboard-design-tutorial

### Diagnose non-adoption with the four forces
- **Claim:** Push of the current problem plus pull of the new solution, versus anxiety of change plus habit of the present. A technically superior data app loses to a spreadsheet whenever push+pull fail to exceed anxiety+habit — so hunt for anxiety-reducers (import their existing data, mirror their current column names) as seriously as feature value.
- **Applies when:** A built tool exists but users cling to Excel exports, a legacy report, or manual Slack asks; reviewing onboarding and first-run experience.
- **Fails when:** Adoption is mandated top-down — the model then predicts resentment and workarounds rather than non-use, and the fix is workflow fit, not persuasion. Inherits the Christensen-school falsifiability critique: forces are easy to narrate post hoc, hard to measure ex ante.
- **Source:** Christensen/Moesta four forces (Competing Against Luck), explained in GoPractice, https://gopractice.io/product/jobs-to-be-done-the-theory-and-the-frameworks/, framework 1999-2016; article accessed 2026-07

### Prototype the riskiest assumption, not the whole product
- **Claim:** Torres's warning: cramming in every mentioned feature until the product is bloated "tests" nothing. Identify the assumption most likely to kill the idea, build the smallest artifact that could disconfirm it, then decide. Any spec whose test plan is "launch it and see" fails this.
- **Applies when:** Reviewing MVPs, v1 scopes, and side projects — a consumer app's first release, a new data-app concept.
- **Fails when:** Assumption-testing degenerates into never shipping — for low-risk, well-understood builds (a portfolio site, an internal CRUD screen) the fastest test IS shipping the real thing; the discipline pays only where a genuinely killer assumption exists.
- **Source:** Teresa Torres via Aakash Gupta, "Teresa Torres's Step-by-Step Guide to AI Product Discovery," https://www.news.aakashg.com/p/teresa-torres-podcast, 2025-08

### Use AI to augment discovery, never to replace user contact
- **Claim:** Torres: AI summaries can miss 20-40% of important detail — keep humans reviewing raw traces and transcripts and tagging error classes; let AI handle volume (logging, clustering, first-pass synthesis). For AI-powered features, "does the model behave acceptably" is itself a discovery question with its own loop: log traces → human tagging → error classes → automated evals → fixes.
- **Applies when:** Teams substituting AI interview-synthesis for interviews; reviewing any AI-assisted feature in a data app.
- **Fails when:** High-volume, low-stakes feedback triage where reviewing everything by hand is impossible — sampled human validation over AI clustering is the honest best available. The 20-40% figure is Torres's practitioner estimate, not a measured constant.
- **Source:** Teresa Torres via Aakash Gupta, "Teresa Torres's Step-by-Step Guide to AI Product Discovery," https://www.news.aakashg.com/p/teresa-torres-podcast, 2025-08
- **Contested:** AI-research tooling vendors and some practitioners argue AI-moderated synthesis is now good enough to replace much manual work; Torres's augment-don't-replace line is one side of a live disagreement.
