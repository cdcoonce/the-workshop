# Pack: UX patterns & usability heuristics

> Researched: 2026-07-18 · Staleness threshold: 18 months
> Load me when: reviewing dashboards, data apps, or admin tables built by a data engineer whose instincts are pipeline-first, UI-second; critiquing a portfolio site or consumer mobile app for form, navigation, and empty-state quality; you need named heuristics to make a critique legible and debatable; someone justifies a design decision with folk-science ("7 items max") and you need the receipts to push back.

## Entries

### Cite heuristics by name, argue by consequence
- **Claim:** Use Nielsen's 10 heuristics as shared vocabulary when flagging an issue ("this fails Visibility of System Status"), but treat them as argument-starters, not a compliance standard — every "violation" must be paired with a concrete user-task consequence or it doesn't ship in the review. Nielsen's own framing: they are "broad rules of thumb and not specific usability guidelines."
- **Applies when:** Any expert review of a UI artifact conducted without user data; whenever a critique needs a name so it can be debated rather than felt.
- **Fails when:** Wielded as validated science. The heuristics have never been empirically validated; they were condensed from 1,000+ guidelines into a generic set that misses domain-specific issues and modern modalities. A heuristic citation with no task consequence is a false positive waiting to happen.
- **Source:** NN/g, "10 Usability Heuristics for User Interface Design" — https://www.nngroup.com/articles/ten-usability-heuristics/ (1994, updated 2024-01-30)
- **Contested:** UXPA Magazine, "Nielsen's Heuristic Evaluation: Limitations in Principles and Practice" — http://uxpamagazine.org/nielsens-heuristic-evaluation/ (2017-09) — cites David Travis and Bob Bailey: the principles "have never been validated," lack depth, and don't scale to conversational/wearable/multimodal UIs.

### Never present single-evaluator findings as fact
- **Claim:** Nielsen's method calls for 3–5 independent evaluators because each individual, however expert, misses problems. A solo reviewer's severity ratings are subjective; an AI-persona review is definitionally a single evaluator — caveat the output accordingly, and validate high-severity findings against real user behavior before anyone acts on them.
- **Applies when:** Formal heuristic evaluations, reviews delivered as prioritized findings lists, any AI-generated design critique.
- **Fails when:** Budget and speed realities: one expert pass beats no review, and aggregating evaluators imports its own noise — the evaluator effect cuts both ways, surfacing more real problems and more phantom ones that need a debrief to prune.
- **Source:** UXPA Magazine (above, 2017-09); method baseline: Moran & Gordon, NN/g, "How to Conduct a Heuristic Evaluation" — https://www.nngroup.com/articles/how-to-conduct-a-heuristic-evaluation/ (2023-06-25)

### Surface system status and data freshness — always answer "as of when?"
- **Claim:** In a data app, every long-running query, refresh, or export must show progress, and every dashboard needs a visible last-updated timestamp. A dashboard with no staleness indicator fails Visibility of System Status in its most consequential form: users deciding on data they wrongly believe is current.
- **Applies when:** Async query execution, cached or scheduled-refresh sources, CSV/report exports — anywhere render time and data time diverge.
- **Fails when:** Status becomes chatter — spinners and toasts on sub-second operations add noise, not trust. Status without recourse (a progress bar with no cancel) trades heuristic #1 for a #3 violation (User Control and Freedom).
- **Source:** NN/g, "10 Usability Heuristics" (#1, #3) — https://www.nngroup.com/articles/ten-usability-heuristics/ (updated 2024-01-30)

### Label in the audience's vocabulary, not the warehouse's
- **Claim:** `revenue_net_usd` or `dim_customer_cnt` on an exec-facing surface fails Match Between System and the Real World. The data engineer's fluency in internal naming is precisely the blind spot to review for — translate at the display layer, every time.
- **Applies when:** Exec dashboards, consumer mobile apps, portfolio pieces — any surface where the viewer did not build the pipeline.
- **Fails when:** Analyst-facing tools, where canonical field names preserve traceability to the semantic layer and renaming breaks the UI-to-query mental mapping. Mixed audiences: translate on the surface, keep the canonical name discoverable (tooltip, data-dictionary link).
- **Source:** NN/g, "10 Usability Heuristics" (#2) — https://www.nngroup.com/articles/ten-usability-heuristics/ (updated 2024-01-30)

### Hold the monitoring layer to a single screen
- **Claim:** Few's definition: information "consolidated and arranged on a single screen so the information can be monitored at a glance." Simultaneity of vision is the dashboard's whole value — cross-metric comparison dies when the viewer must scroll or flip between fragments hidden behind radio buttons. If it scrolls, review it as a report and hold it to report standards.
- **Applies when:** Operational and executive monitoring views where anomaly-spotting and cross-metric comparison are the job; when slices are fragmented so they can never be seen together (Few's Pitfall #1).
- **Fails when:** Written in 2006, pre-mobile and pre-drill-down. Layering depth behind the single screen via progressive disclosure is now legitimate norm; exploratory analyst workbenches are not dashboards in Few's sense — applying the rule there is a category error. On mobile, scroll is the medium.
- **Source:** Stephen Few, "Common Pitfalls in Dashboard Design" — https://www.perceptualedge.com/articles/Whitepapers/Common_Pitfalls.pdf (2006-02; contents verified in full)
- **Contested:** UXPin, "Dashboard Design Principles: The Definitive Guide" — https://www.uxpin.com/studio/blog/dashboard-design-principles/ (2026-06-05) — treats layered overview-to-drilldown as the norm, not a fixed single screen.

### Never show a naked number — display the difference the viewer needs
- **Claim:** A lone "$736,502" answers nothing: "Compared to what? Is this good or bad? Are we on track?" Every KPI needs a target, prior period, trend, or encoded state — and for actual-vs-budget, plot variance around a zero line rather than two lines the viewer must mentally subtract (Few's Pitfall #4). If the viewer needs the difference, show the difference. Twin failure: excessive precision — $3,848,305.93 where $3.8M serves slows monitoring without informing it.
- **Applies when:** KPI tiles, scorecards, hero metrics; any target/plan/prior-period comparison chart, especially multi-entity ones where percentages normalize wildly different scales.
- **Fails when:** Context on every tile can double visual density and re-create the clutter it cures — for well-known operational metrics, an on-track/off-track state can stand in. And when absolute magnitude is the decision variable, percentage-only displays lie: a 10% miss on $1M and on $10K are not the same event. Show both or anchor the variance chart with absolutes.
- **Source:** Stephen Few, "Common Pitfalls in Dashboard Design," Pitfalls #2–#4 — https://www.perceptualedge.com/articles/Whitepapers/Common_Pitfalls.pdf (2006-02)

### Practice visual economy: repeat chart forms, ration color
- **Claim:** "Meaningless variety" (Few's Pitfall #6) forces a new perceptual strategy per panel; a dashboard that is all bar charts is not boring, it is efficient. Reserve saturated color and visual weight for the one or two things needing attention now; keep the rest subdued; demote logos and chrome from prime top-left real estate. Never encode state in red/yellow/green alone — it excludes the ~10% of males (and 1% of females) with color-vision deficiency; pair color with position, shape, or text.
- **Applies when:** Multi-panel dashboards where several metrics share the same data relationship; layout reviews; any traffic-light status encoding; anything that smells like gauges-next-to-pies-next-to-radars.
- **Fails when:** Genuinely different data relationships demand different forms — forcing sameness onto a time series, a part-to-whole, and a distribution is Pitfall #5 from the other direction. Brand-mandated palettes and expressive portfolio pieces shift the standard (a portfolio sells craft; an ops dashboard sells signal). Uniform subduedness with no highlight at all is its own failure: the eye needs somewhere to land.
- **Source:** Stephen Few, "Common Pitfalls in Dashboard Design," Pitfalls #5, #6, #9–#12 — https://www.perceptualedge.com/articles/Whitepapers/Common_Pitfalls.pdf (2006-02)

### Layer mixed audiences with two-level progressive disclosure
- **Claim:** For exec-plus-analyst surfaces, default to summary first, detail on demand — but cap at two levels ("designs that go beyond 2 disclosure levels typically have low usability because users often get lost") and derive the split from frequency-of-use evidence, not the org chart. Make the disclosure mechanic obvious and label what's behind it accurately.
- **Applies when:** Dashboards serving execs (status at a glance) and analysts (drivers on demand) simultaneously; complex settings panels; long staged forms.
- **Fails when:** The split is wrong — too much upfront loses focus, too little doubles interaction cost. Staged (linear) disclosure fails when steps are interdependent and users must revise earlier choices. Hiding functions experts use hourly violates Flexibility and Efficiency of Use — disclosure is for the infrequent, not the merely advanced.
- **Source:** Jakob Nielsen, NN/g, "Progressive Disclosure" — https://www.nngroup.com/articles/progressive-disclosure/ (2006-12-03)

### Make every click smell like its destination
- **Claim:** Links, tabs, drill affordances, and filter labels must telegraph what's behind them in the user's own words — information scent, per Pirolli & Card's information-foraging work at PARC. Generic labels ("More", "Details", "Insights", "Explore") kill scent, and modern users are informavores: when the scent goes cold they leave rather than dig.
- **Applies when:** Navigation menus, dashboard drill paths, portfolio site sections, empty-state CTAs — any point where a user must predict the value of a click before spending it.
- **Fails when:** Scent-maximizing labels bloat into sentence-length links; on small screens brevity wins and icons-plus-placement carry the scent. Inside a daily-use internal tool, users navigate by rote — weak labels tax onboarding, not steady-state use.
- **Source:** Jakob Nielsen, NN/g, "Information Foraging: Why Google Makes People Leave Your Site Faster" — https://www.nngroup.com/articles/information-foraging-leave-site/ (2003-06-29)

### Retire Miller's 7±2 as a design justification
- **Claim:** Never accept "maximum 7 items" for menus, nav, or KPI tiles on Miller's authority — 7±2 is a working-memory recall limit, and a visible menu is a recognition task. Miller himself protested the misreading: the limit concerned unidimensional stimuli and immediate recall, "neither of which has anything to do with" scanning visible options. Flag any rationale that counts to seven.
- **Applies when:** Reviewing navigation breadth, tile counts, filter lists — anywhere a numeric cap is asserted as science. Broad-and-shallow with good grouping routinely beats hierarchies built deep to honor the "rule."
- **Fails when:** Capacity limits are real even though the number is fake: 40 ungrouped, unranked options genuinely overload — the fix is chunking, grouping, and hierarchy, not truncating to seven. Items held in memory across screens (wizard steps, comparison sets) do hit real working-memory limits.
- **Source:** UX Myths, "Myth #23: Choices should always be limited to seven" — https://uxmyths.com/post/931925744/myth-23-choices-should-always-be-limited-to-seven (2010); Stéphanie Walter, "Your navigation menu doesn't need Miller's 7±2 rule" — https://stephaniewalter.design/blog/your-menu-doesnt-need-millers-7-plus-minus-2-rule/ (2026-03-07)

### Inline validation: reward early, punish late
- **Claim:** Require inline validation, but the timing is the load-bearing part: never flag an error while the user is still typing a first entry (validate on blur or plausible completion), clear the error keystroke-by-keystroke once they're fixing it, confirm success positively. Baymard's benchmark: 31% of e-commerce sites lack inline validation entirely and 4% implement it so badly it backfires. Wroblewski's original study: the well-timed variant cut errors 22% and completion time 42%.
- **Applies when:** Signup, settings, and data-entry forms — especially mobile, where re-submission round-trips cost most; long checkout-style flows where a surprise error at submit drives abandonment.
- **Fails when:** Server-side-only checks (uniqueness, credit) can't be honestly inline-validated — faking certainty is worse than deferring. Instant per-keystroke error-flagging measurably increases errors and hunt-for-problems behavior; and Wroblewski found validation feedback on trivial fields (name, address) confused users — reserve it for fields users doubt.
- **Source:** Baymard Institute, "Usability Testing of Inline Form Validation: 31% Don't Have It, 4% Get It Wrong" — https://baymard.com/blog/inline-form-validation (2024-01-09); Luke Wroblewski, "Inline Validation in Web Forms," A List Apart — https://alistapart.com/article/inline-validation-in-web-forms/ (2009-09-01)

### Data tables: align by data type, freeze what identifies
- **Claim:** Right-align quantitative numbers in tabular/monospace figures (so $999.99 doesn't read smaller than $1,111.11), left-align text and qualitative numbers (dates, IDs, postal codes), keep headers sticky and the identifying left column frozen on horizontal scroll, offer adjustable row density (~40/48/56px), and reveal bulk actions only after selection so the resting state stays clean. Skip zebra striping — it collides with hover/selected/disabled states into multiple-grey chaos; use light line divisions.
- **Applies when:** Enterprise-style tables — many columns, horizontal scroll, scanning and comparison as primary tasks; any table where users act on rows.
- **Fails when:** Small static tables don't earn the machinery — density toggles and frozen columns add settings burden for nothing. The authors' own gate: classify the table as action-oriented or info-oriented first, then apply patterns; the two types want different affordances.
- **Source:** Pencil & Paper, "Data Table Design UX Patterns & Best Practices" — https://www.pencilandpaper.io/articles/ux-pattern-analysis-enterprise-data-tables (2026-02-23)

### Prefer pagination for reference-and-compare tables
- **Claim:** Position matters when users return to a row, compare across pages, or trust that an export matches what they saw — pagination gives structure, spatial orientation, and predictability; infinite scroll strips them. Default to 10–25 rows with a 10/25/50 selector, and treat filter-then-paginate as one system: filtering 500 rows to 40 and paging those is the workflow to optimize, not either mechanism alone.
- **Applies when:** Tables backing analytical or operational work; anything with an export button (infinite scroll breaks the what-you-see-is-what-you-export contract); tables users cite by position.
- **Fails when:** Feed-like consumption lists (activity streams, media) where nobody revisits positions — there infinite scroll or load-more wins. On very large warehouse-backed tables, exact server-side counts can make accurate pagination expensive; honestly-labeled approximate counts beat slow exact ones.
- **Source:** Muhd Fitri, ALF Design Group, "Why Pagination Matters in Table Design" — https://www.alfdesigngroup.com/post/why-pagination-is-important-for-table-design (updated 2026-07-10)

### Design zero-data and error states deliberately
- **Claim:** First-run, filtered-to-nothing, and error-empty are three different states needing three different messages — each must say what is empty, why ("You haven't added any items yet," not "No data"), and offer one action. A bare axis grid with no message reads as a bug; "Something went wrong" with no retry is a dead end. Hold error copy to Nielsen #9 — plain language, precise diagnosis, constructive next step — and never surface raw stack traces or SQL to end users.
- **Applies when:** Dashboards where filters can legitimately return nothing (users must distinguish no-match from query-failed from not-loaded-yet); first-run in a mobile app; export and query failure paths.
- **Fails when:** Illustration-heavy, personality-forward empty states become noise in high-frequency workflows — charm is for first-run, economy is for daily use. Stacked CTAs dilute; one idea per state. Security contexts legitimately cap error specificity (login failures should not disclose which credential was wrong).
- **Source:** Eleken, "Empty state UX: Real-world examples and design rules" — https://www.eleken.co/blog-posts/empty-state-ux (updated 2026-02-24); error-message standard: NN/g heuristic #9 — https://www.nngroup.com/articles/ten-usability-heuristics/ (updated 2024-01-30)
