# Knowledge Pack: Prioritization on Thin Evidence

**Topic:** Startup-speed prioritization — cheap validation, sequencing, kill criteria, opportunity cost of half-shipped work, sales/pitch-driven development (build-to-close economics, demo-ware vs prod code, revealed preference vs meeting agreement), pre-PMF roadmap posture.
**Researched on:** 2026-07-19
**Staleness:** 12 months (entries marked ⏳ fast-moving: 6 months)

**Load me when…**
The conversation is about deciding what to build next without real data. That means: roadmap/backlog prioritization debates (RICE/ICE/WSJF pushback, cost-of-delay sequencing, backlog hygiene); pre-PMF planning posture (roadmap-or-not, cadence, who owns prioritization, what to promise externally); build-to-close pressure from sales (custom features, demo-ware, design partners, "this one deal is special"); choosing validation instruments (paid pilots vs LOIs, fake doors vs thin real builds, prototypes vs PRDs); or kill-or-continue calls on in-flight bets and half-shipped work.

---

## 1. Scores are for arguing, not for ranking — Contested

**Claim:** Prefer treating a RICE/ICE score as a debate-structuring input — with Confidence tied to an explicit evidence ladder (opinions < assessments < data < live test results) — over a ranked execution order. A 1.7-vs-1.3 delta is false precision, not signal, and gut-assigned 1-10 confidence just launders conviction into arithmetic.

**When it applies:** Any time a scored backlog is about to be executed top-down in sorted order; any prioritization meeting where within-noise score deltas are being treated as decisions; whenever someone's Confidence number is an opinion with a decimal point. The honest uses: force the team to argue about the same three or four variables in the open, sanity-check the ranking by hand, and raise Confidence only by running the next-cheapest test — not by arguing louder. Gilad's Confidence Meter operationalizes it: a 0.01–10 multiplier that climbs the ladder from subjective conviction through opinions/estimates to data and live test results.

**When it fails / contested:** Khan goes further than this claim: scoring is "prioritization theatre" — subjective high/medium/low ratings aren't ratio-scale numbers, so the formula is mathematically invalid, and four factors at ±20% each compound to roughly ±80% margin of error, swamping most score differences ("You cannot turn approximates into absolutes just by ignoring the uncertainty"; split teams scoring the same backlog produce divergent rankings). His prescription is top-down narrowing via vision/strategy instead. The counter-camp (Gilad; Intercom's original RICE post) says that attacks a strawman — scoring was never a standalone oracle, and rough transparent quantification beats the real-world alternative: "a tangled mess of gut feeling" and HiPPO backlogs. Even the originator agrees scores "shouldn't be used as a hard and fast rule" (dependencies and table stakes are legitimate overrides). Both camps agree on the load-bearing point: nobody defensible executes the raw sorted list.

**Source:** Avion, [How To Use RICE Prioritization](https://www.avion.io/blog/rice-prioritization/); Intercom (McBride), [RICE: Simple prioritization](https://www.intercom.com/blog/rice-simple-prioritization-for-product-managers/) — independent, originator; Saeed Khan, [Why You Should Avoid Prioritization Frameworks](https://swkhan.medium.com/why-you-should-avoid-prioritization-frameworks-779a61c0087); Itamar Gilad, [ICE Scores](https://itamargilad.com/ice-scores/) — note the ladder specifics live on his Confidence Meter page, not the ICE page.

**Date:** Intercom 2016; Khan 2022-01-08; Gilad evergreen. Researched 2026-07-19.

---

## 2. Sequence by cost of delay in rough dollars — never WSJF — Contested

**Claim:** Prefer asking "what does a month of delay cost us?" — answered as a rough $/month, or plain CD3 — over "what is this worth?", and over SAFe-style WSJF entirely. Summing relative Fibonacci proxies (business value + time criticality + risk reduction) then dividing by relative size destroys the economic trade-off power that made CoD useful, and self-scored inputs get gamed at the source.

**When it applies:** Sequencing a portfolio where items compete for the same team; when a high-ROI-but-delay-insensitive project is crowding out a low-ROI-but-urgent one (ROI alone missequences); whenever someone proposes WSJF because "we can't estimate dollars." Reinertsen's kicker: unquantified CoD intuitions vary person-to-person by up to 50:1, so even a hand-waved shared number beats a room of confident divergent gut calls — "If you only quantify one thing, quantify the cost of delay." Yip's trade-off test: a relative CoD of "9" can't be weighed against a $100k decision; a dollar figure can.

**When it fails / contested:** Two-front pushback. (a) Quantified CoD inherits the false-precision disease: the 50:1 spread relocates into the forecast rather than disappearing — with speculative revenue (pre-launch, new markets) dollar CoD is "confident-looking numbers encoding collective delusion," and real CoD distributions are power-law (RoadmapOne; Khan on ignored error bars; Gilad notes CD3 implementations ignore evidence strength entirely — one person's guess scores like thorough research). (b) Richards' steelman of SAFe: relative ratios are a pragmatic on-ramp for orgs with no revenue model — flawed on time sensitivity, but better than analysis paralysis. Keep the question-frame; hold the number loosely. Citation nit: the 50:1 figure and the quantify-one-thing quote are Reinertsen's (Principles of Product Development Flow), not on the Black Swan Farming page.

**Source:** Reinertsen via [Wikipedia: Cost of delay](https://en.wikipedia.org/wiki/Cost_of_delay); Black Swan Farming (Arnold), [Cost of Delay](https://blackswanfarming.com/cost-of-delay/); Jason Yip, [Problems I have with SAFe-style WSJF](https://jchyip.medium.com/problems-i-have-with-safe-style-wsjf-772df2beaf02). Counters: Mark Richards, [Improving SAFe Cost of Delay](http://www.agilenotanarchy.com/2016/09/improving-safe-cost-of-delay-response.html); [RoadmapOne on $-CoD false precision](https://roadmap.one/blog/posts/blog8-13-cost-of-delay-prioritisation/); Gilad, [Prioritization Techniques Compared](https://itamargilad.com/prioritization-techniques-1/).

**Date:** Reinertsen 2009; Yip 2024-03-10; Richards 2016-09. Researched 2026-07-19.

---

## 3. Pre-PMF, frameworks starve — make 10 customers very happy — Contested

**Claim:** Prefer depth-with-a-handful-of-customers ("make 10 customers very happy") plus a fast shipping cadence over any scoring framework pre-PMF. RICE's Reach term is meaningless at n=30 users, and every scoring model silently assumes data volume you don't have — statistical significance on a 10% conversion lift needs >5,000 users.

**When it applies:** Seed-stage, small user base, weekly-pivot dynamics; whenever someone imports big-company scoring ritual into a 30-user product. The asymmetry that justifies it: pre-PMF the startup is a fragile flame — intensity of satisfaction among few beats breadth of appeal, because fatal mistakes and recoverable mistakes aren't symmetric.

**When it fails / contested:** The named failure mode is overfitting: depth with five boutique customers gets you product-_customer_ fit, not product-_market_ fit — the bespoke/consultancy trap where you found fit with five idiosyncratic workflows, not a market. Mitigations from the counter-literature: hold a product thesis independent of any one customer, and check that features reuse across customers. Separately, ProductLift's startup-prioritization guide argues lightweight ICE/impact-effort still earns its keep pre-PMF even where Reach is dead. The counter attacks execution risk, not the statistical point — that stands unrefuted.

**Source:** Lenny Rachitsky, [Prioritizing at startups](https://www.lennysnewsletter.com/p/prioritizing-startup); Growth Unhinged, [The pre-PMF guide to product management](https://www.growthunhinged.com/p/the-pre-pmf-guide-to-product-management); June.so (independent outlets). Counters: Gomes, [How to avoid over-fitting your product to early customers](https://myromes.medium.com/how-to-avoid-over-fitting-your-product-to-early-customers-e8a650d1f3f2); Priestley, [The 'Bespoke' Trap](https://medium.com/@alyx.priestley/the-bespoke-trap-why-customization-kills-scale-65cc2e95ae96); [ProductLift](https://www.productlift.dev/blog/product-prioritization-framework-for-startups).

**Date:** Lenny 2022-01-04; Growth Unhinged 2023-11-15. Researched 2026-07-19.

---

## 4. Problem list, not roadmap — and the shortest cadence you can physically run — Contested

**Claim:** Pre-PMF, prefer a short prioritized problem list on a rolling ≤3-month horizon — 6-week planning cycles, 1-week sprints, weekly public changelog — over a feature roadmap. The roadmap artifact itself is the liability, not just its contents: Avigo threw away 10 roadmaps in his first three months at June. The operating question is "what's the highest-impact work this week?" against the problem list; user stories and epics are abstraction that slows you down.

**When it applies:** Before repeatable growth, when the product changes faster than any quarterly artifact can track; teams filtering customer signal through the plan instead of letting signal rewrite the plan. Avigo's paired dissent on MVPs: ship close to the eventual form — "don't rush through your first version" — because "ship it, you'll learn faster" only works if jank isn't drowning the signal.

**When it fails / contested:** Contested at the sprint level only. Shape Up rejects short-sprint churn outright: six-week cycles because that's "long enough to build something meaningful start-to-finish," and "we don't rethink our roadmap every two weeks" — frequent replanning is overhead, not agility; Serious Scrum adds that one-week sprints inflate the ceremony-to-build ratio and feel frantic. Note the camps actually agree on the ~6-week planning horizon; the fight is sprint length. Two honesty notes: "the changelog deadline is the forcing function" is an interpretive gloss — Avigo presents the never-missed weekly changelog as shipping-discipline evidence, not explicitly as mechanism; and problem-based Now/Next/Later boards are still "roadmaps" by name — a naming quibble, compatible with the substance. Both sources concede roadmaps become appropriate as the company matures.

**Source:** Growth Unhinged (Avigo x Poyar), [The pre-PMF guide to product management](https://www.growthunhinged.com/p/the-pre-pmf-guide-to-product-management) — verified verbatim; Product Trench (Kawsarani), [Why your startup doesn't need a product roadmap yet](https://www.producttrench.com/p/why-your-startup-doesnt-need-a-product) — independent. Counters: Basecamp, [Shape Up ch. 1](https://basecamp.com/shapeup/0.3-chapter-01); Carleson, [A shorter Sprint doesn't mean you are more Agile](https://medium.com/serious-scrum/a-shorter-sprint-doesnt-mean-you-are-more-agile-4f916e00afdc).

**Date:** Growth Unhinged 2023-11-15; Product Trench 2024-08-01; Shape Up 2019. Researched 2026-07-19.

---

## 5. Founder owns the roadmap; sell vision, not dates

**Claim:** Pre-PMF, prefer keeping the founder (or the senior-most product person actually doing sales calls) as de facto roadmap owner over installing a PM layer — "a layer between the founder and the customer signal is dangerous regardless of what fills that layer"; "proximity to customers is the entire job, not part of it." And externally, prefer selling vision plus the next milestone over a committed, dated roadmap — dated commitments turn the plan into a prison, stop critical re-litigation once features are "on the roadmap," and torch credibility the first time you miss.

**When it applies:** Before a repeatable buyer exists; first-PM-hire timing debates; prospect or board asking for a committed roadmap. For a design+PM hybrid the practical read: your leverage is being _in_ the customer conversations, not synthesizing them secondhand.

**When it fails / contested:** The graduation condition is real and both sources encode it — when growth is repeatable and customers need predictability more than you need optionality, structured planning and a PM layer earn their keep. Carrying caveats: Ellenox is a small product-studio blog (one practitioner's articulation of a widely-held position, not an authority citation), and the Olusola piece leans on the contested "70% of features rarely used" stat, which this claim doesn't need.

**Source:** Ellenox (Bagchi), [Pre-PMF vs Post-PMF](https://www.ellenox.com/post/pre-pmf-vs-post-pmf); Product Trench (Kawsarani), [Why your startup doesn't need a product roadmap yet](https://www.producttrench.com/p/why-your-startup-doesnt-need-a-product); Olusola, [Why Your Product Roadmap Is Killing Your Startup](https://aboyejiemmanuel.medium.com/why-your-product-roadmap-is-killing-your-startup-2991e6d65a08) — independent.

**Date:** Ellenox 2026-06-05; Product Trench 2024-08-01; Olusola 2025-09-14. Researched 2026-07-19.

---

## 6. Delete the backlog

**Claim:** Prefer deleting the backlog over grooming it: keep an item only if you can attach documented proof-of-desire (a customer email, chat screenshot, tweet) or name it as groundwork for something that has proof, and archive everything you can't justify in one sentence. Kahl cut Podscan's backlog ~120 → 15 with exactly this gate.

**When it applies:** Any two-pizza pre-PMF team whose backlog makes last quarter's guesses compete with this week's live signal; grooming sessions that are pure opportunity cost; quarterly hygiene. Kill unclear items, cute ideas, duplicates, and high-effort/low-impact work on sight.

**When it fails / contested:** The institutional-memory objection is absorbed by _archiving_ rather than hard-deleting (Watson's own hedge is export-first), and truly important items resurface on their own. No published refutation of evidence-gated pruning surfaced in verification.

**Source:** Arvid Kahl, [Deleting Your Backlog](https://thebootstrappedfounder.com/deleting-your-backlog-a-founders-guide-to-feature-pruning/); Product Driven (Watson), [Delete Your Product Backlog](https://newsletter.productdriven.com/p/delete-your-backlog-product-planning) — independent.

**Date:** Kahl 2025-01-31; Watson 2024-05-07. Researched 2026-07-19.

---

## 7. Build-to-close: three gates and a standing budget — Contested

**Claim:** Prefer refusing build-to-close unless the deal clears three gates at once — the customer pays real contract money for it (1yr+ term, not a paid pilot), it was already on your next-24-months roadmap, and a second big customer will use the same feature — over case-by-case "this one deal is special" reasoning. And pre-agree the capacity before any deal lands: Lemkin's numbers are ~10% of story points, 1-2 big-deal builds in flight, 1-2 per year total. Sales will bring 10-12; the budget lets you say yes twice and no ten times without a war each time. The payment gate isn't about the money — it's the only honest signal the ask is real.

**When it applies:** Post-PMF SaaS with real pipeline pressure; orgs where every hot deal currently triggers a sprint-blowup fight. A true one-off gets pushed back on or priced at a premium painful enough that everyone internalizes the cost. No true exclusivity, ever.

**When it fails / contested:** Stage-dependent — pre-PMF the dominant VC advice inverts it: design-partner programs (a16z, Bessemer) deliberately build with individual customers at discounted or free terms, failing the money gate on purpose, because custom work _is_ the discovery mechanism (Paul Graham's do-things-that-don't-scale). Lemkin's rule is post-PMF hygiene; applied earlier it can block the fastest route to fit. Attribution honesty: the 10% / 1-2-in-flight / 1-2-per-year numbers rest on Lemkin alone — Yoskovitz, often cited as the second leg, actually runs a per-deal 7-question evaluation (payment in advance, roadmap fit, value to other clients), i.e., disciplined case-by-case is a respected alternative; his nod to reserved sprint capacity is secondhand. Also "name a second big customer" is marginally stronger than Lemkin's own "there almost certainly will be another" — that gate carries via Yoskovitz's validate-with-similar-customers question.

**Source:** Lemkin, [One Simple Rule on When to Build a Custom Feature](https://www.saastr.com/one-simple-rule-on-when-to-build-a-custom-feature/) + [Dear SaaStr on custom features](https://www.saastr.com/dear-saastr-our-biggest-potential-customers-are-all-asking-for-custom-features-when-do-we-say-yes/); Yoskovitz, [How Do You Decide to Build a Feature to Close a Deal?](https://www.focusedchaos.co/p/build-feature-close-deal). Counters: [a16z design-partner framework](https://a16z.com/a-framework-for-finding-a-design-partner/); [Bessemer on design partners](https://www.bvp.com/atlas/design-partners-the-pre-launch-edge-most-ai-founders-ignore); Graham, [Do Things that Don't Scale](https://www.paulgraham.com/ds.html).

**Date:** Lemkin ~2017 (SaaStr Classic); Yoskovitz 2023-09-05; Graham 2013-07. Researched 2026-07-19.

---

## 8. Price build-to-close at fully-loaded cost

**Claim:** Prefer pricing build-to-close against fully-loaded cost — maintenance drag on every future release, support/training/docs, UX bloat (Cutler's hotel-sprawl metaphor), opportunity cost, and the parallel-work tax (conservatively ~50% team effectiveness; parallel tracks take ~3x) — over the naive "deal revenue > build cost" math. Cutler's worked scenario: a $50k build closing a $100k deal lands as a net loss once the invisible ledger is counted.

**When it applies:** Every build-to-close conversation after the gates in entry 7 pass — the visible ledger (eng-weeks vs contract value) is the smallest line item; the code lives in your codebase forever. And post-launch: instrument the sales-driven feature and check actual adoption — the only reality check on "this closes deals," and it builds the internal dataset for the next fight.

**When it fails / contested:** No published rebuttal of the accounting argument. Honesty notes: the 50%/3x figures are Cutler's asserted conservative rules of thumb, not measured data, and "routinely a net loss" generalizes his single illustrative scenario — use it as a pricing posture, not a proof. The design-partner camp's "custom work can be strategically correct early" doesn't contradict this: fully-loaded pricing is compatible with saying yes.

**Source:** John Cutler, [Hidden Costs of the Sales-Driven Roadmap](https://medium.com/@johnpcutler/hidden-costs-of-the-sales-driven-roadmap-81b847da3452) — attributed, fully verified against the primary.

**Date:** Cutler 2016-01-16 (cost-accounting logic, not stale). Researched 2026-07-19.

---

## 9. The buyer at the door: ship the 80%, apply the buy-and-wait test — Contested

**Claim:** When a live buyer has a specific problem and a specific date, prefer shipping the 80% that works today over the 100% still on the plan — the roadmap is a hypothesis, the buyer is evidence, and "when hypothesis meets evidence, evidence wins." But bound the detour with the buy-and-wait test: "when the need is large enough, people will buy your product and wait for you to build the rest" (Amin/Clay) — an ask that only closes if you build it first is revealed evidence the wedge isn't there, and feature-matching a hesitant buyer is masking a weak signal, not serving a customer.

**When it applies:** Pre-PMF collisions between plan and a live deal where the 80% already exists; reading whether a deal-driven detour sits on your wedge. Pairs with Webflow's Bryant Chou running 5-whys on requests to build the root cause (their CMS) instead of the surface ask. Note the test self-limits to wedge asks — procurement table-stakes (SSO, compliance) sit outside it.

**When it fails / contested:** Mironov's sales-led critique is the standing counter: one buyer with a date is n=1 evidence about a _deal_, not a market, and "evidence wins every collision" is precisely the reasoning that erodes roadmap capacity and accumulates customization debt — years of hidden maintenance that starves core product work until a product business drifts into an unscalable services business. The claim is strongest pre-PMF when the 80% already exists; weakest at an established company where honoring the buyer means deal-specific custom work. Treat "every collision" as disputed; the buy-and-wait gate is what keeps this from being the slippery slope.

**Source:** First Round Review, [20 Lessons From 20 Different Paths to Product-Market Fit](https://review.firstround.com/20-lessons-from-20-different-paths-to-product-market-fit-advice-for-founders-from-founders/) — Amin quote verified verbatim; Tonse, [Your roadmap feels like progress. Your customer at the door is proof.](https://sridharpaitonse.substack.com/p/your-roadmap-feels-like-progress). Counters: Mironov, [The Slippery Slope of Sales-Led Development](https://www.mironov.com/sales-led/) + [Customization Debt](https://www.mironov.com/customization-debt/).

**Date:** Tonse 2026-05-23; Mironov 2018-11-02 / 2024-10-18. Researched 2026-07-19.

---

## 10. Validation has a price tag — Contested

**Claim:** Prefer counting only validation that costs the prospect something — cash (deposit, paid pilot with money up-front), calendar (trial participation, wireframe reviews), or reputation (intro to their boss, public reference) — over meeting enthusiasm; and within instruments, prefer money-at-risk over a stack of unpaid LOIs. "We'd definitely buy that" is politeness data, not demand data; a feature ask in a sales meeting is a compliment until it arrives with budget, a named economic buyer, and a next step. Ken Morse: LOIs "can't be taken to the bank" — if the value is real, asking for payment surfaces the truth sooner; if they won't pay anything, you've learned what an LOI would have hidden for two quarters.

**When it applies:** Reading sales-meeting feature asks before they touch the roadmap; deciding whether a build-ahead-of-product bet is validated; pre-PMF instrument choice ("when the solution is free, the problem seems less significant" — LeanB2B).

**When it fails / contested:** Two sharp edges. (a) Paid pilots are their own documented false-validation channel: enterprises fund pilots from innovation budgets with no path to production, and a pilot without executable pass/fail criteria "can neither succeed nor fail, only continue to consume budget" — MIT NANDA 2025 puts enterprise gen-AI pilots with no measurable P&L impact at ~95%. Money only validates when tied to production-intent acceptance criteria, not an innovation-budget line item. (b) "Interviews are theater" overreaches: Mom-Test-style interviews extract valid signal precisely via commitment and advancement — the defensible dichotomy is commitment-with-cost vs cheap enthusiasm, not selling vs interviews. Nuances: Fitzpatrick himself counts an LOI among money-currency commitments — treat LOIs as weak-tier signal, not zero — and don't confuse investor-signaling with demand validation; the "3-5 LOIs moves seed investors" folk wisdom is unsourced in this pack's verified literature.

**Source:** Fitzpatrick's commitment-currency frame ([The Mom Test](https://www.momtestbook.com/), via [mtlynch book report](https://mtlynch.io/book-reports/the-mom-test/)); [LeanB2B on selling first products](https://leanb2bbook.com/blog/the-3-approaches-to-selling-your-first-product/) — independent; [Dealmayker pre-selling tactics](https://dealmayker.com/blog/founder-playbooks/pre-selling-tactics-validate-b2b-saas-before-building); Peaka ("the Pre-PMF stage is purely sales-led… When you nail demand, you don't sell. People buy."). Counters: [QueryNow enterprise-pilot paradox](https://www.querynow.com/resources/whitepapers/enterprise-ai-pilot-paradox); [Argano on the AI pilot trap / MIT NANDA](https://argano.com/insights/articles/overcoming-the-ai-pilot-trap.html).

**Date:** Mom Test 2013; pilot-trap literature 2025-2026. Researched 2026-07-19.

---

## 11. Build the thin real thing, not the painted door — Contested ⏳ fast-moving (stale after 6 months)

**Claim:** Prefer building the thin real thing over running a painted-door test when an AI-assisted PoC is a weekend of work — real usage data beats click-intent proxies, and you skip the "coming soon" trust tax on an early product with few users to burn. Reserve fake doors for genuinely expensive builds (deep integrations, infra, multi-platform) and for recruiting a qualified beta cohort. When you _do_ run a B2B painted door: small qualified cohorts (300-1,000 sessions per audience), a pricing anchor ("design partner slots from $1,500/month"), founder follow-up calls, 7-14 days max, segment existing-customer in-app clicks (8-13% CTR is normal there) from cold traffic (sub-1%), and pre-register the pass/fail number before launch — pick the bar after seeing the data and you'll rationalize whatever came back.

**When it applies:** Surface-level features where vibe-coding flipped the build-cost economics that justified fake doors; B2B with small samples and tight communities where clicks without a price select for tire-kickers.

**When it fails / contested:** Three fronts. (a) The prototype-trap literature: a weekend build shipped to real users carries hidden security/maintenance cost the economics ignore — 2026 reporting cites ~25% of AI-generated code with confirmed vulnerabilities and the Moltbook exposure (Feb 2026, 1.5M auth tokens) as the named failure; the counter argues for _hardening the thin real thing_, not for fake doors, but "weekend of work" understates total cost. (b) Painted-door skeptics (Chameleon, Amplitude): trust damage amplifies in high-touch B2B — one burned champion can cost more than the learning — and CTR measures curiosity, not commitment, even with a price anchor; sometimes the founder call _is_ the better instrument. (c) The specific benchmark numbers are DoWhatMatter single-source — Userpilot's bars differ (~5% CTR for targeted power users; 2-3% cold counts as meaningful) — treat them as one shop's calibration, not consensus.

**Source:** Userpilot, [Is Fake Door Testing Still Worth Doing in The Vibe-Coding Era?](https://userpilot.com/blog/fake-door-testing/); Figma, [Prototypes Are the New PRDs](https://www.figma.com/blog/prototypes-are-the-new-prds/); DoWhatMatter, [Fake door test for B2B SaaS](https://dowhatmatter.com/guides/fake-door-test). Counters: CKEditor, [Vibe Coding and the Prototype Trap](https://ckeditor.com/blog/vibe-coding-prototype-trap/); martinfowler.com, [The VibeSec Reckoning](https://martinfowler.com/articles/vibesec-reckoning.html); [Chameleon](https://www.chameleon.io/blog/fake-door-testing); [Amplitude](https://amplitude.com/explore/experiment/fake-door-testing).

**Date:** Userpilot 2026-06-25; DoWhatMatter 2026-03-27; CKEditor 2026-07-07; Fowler 2026-05-27. Researched 2026-07-19.

---

## 12. Demos persuade, prototypes align — neither is the spec, neither ships — Contested ⏳ fast-moving (stale after 6 months)

**Claim:** Prefer treating demo-ware as sales collateral with a planned funeral — hand off the learning, not the code — over letting the demo that closed the deal become the production foundation. And prefer a working AI-built prototype over a written PRD/deck as the alignment-and-validation artifact — show intent, don't describe it — but treat it as a conversation piece, not a spec: handoff still needs human interpretation and grounding in the real design system. Kaplan-Moss's taxonomy is the clean cut: a demo is a persuasive artifact, a prototype is a learning artifact, an MVP is a product — the classic failure is category-blending, where the stakeholder loves the demo and the shortcuts become permanent liabilities. AI codegen made this sharper, not obsolete: demos are now nearly free, which makes promote-the-throwaway the dominant failure mode — the demo skips error handling, security, and the real data model, and proves neither feasibility nor economics.

**When it applies:** Post-signature "just productionize the demo" pressure; kickoff alignment where prototype + Loom is displacing the spec doc; any artifact doing double duty across Kaplan-Moss categories. For a design-fluent operator, the prototype collapses validate-then-spec into one artifact — the same one that works in a sales room.

**When it fails / contested:** Two counters. (a) The selective-salvage school (GetDevDone, 2026): the prototype-to-production full-rewrite pipeline is outdated — "the fastest path to production is selective salvage" — triage component-by-component: keep client-approved UI shells and flows, refactor business logic, rebuild only auth/payments; a blanket planned-funeral rewrite doubles the timeline for no quality gain on salvageable parts. Whitespectre's counter-datapoint: only ~30% of AI prototype code was salvageable in their audits — so triage, don't assume either way. (b) Prototype-replaces-PRD teams drifted from the problem and reintroduced a written framing doc: "a prototype without a PRD can drift away from the problem the team intends to solve" — the durable workflow is prototype + written framing _pairing_, not substitution. Also: Figma is vendor-interested on the prototype claim; discount accordingly.

**Source:** Kaplan-Moss, [Demos, Prototypes, and MVPs](https://jacobian.org/2020/jan/16/demos-prototypes-mvps/); Whitespectre, [Working Demo, So What?](https://www.whitespectre.com/ideas/ai-powered-prototype-to-production-process/); Product Map, [Ship the prototype instead of the spec](https://www.productmap.io/blog/ship-the-prototype-instead-of-the-spec) ("hand off the learning, not the code"); Figma (Webster), [Prototypes Are the New PRDs](https://www.figma.com/blog/prototypes-are-the-new-prds/). Counters: GetDevDone, [AI prototype to production without rework](https://getdevdone.com/blog/ai-prototype-to-production-for-agencies.html); Mason, [Prototypes are the new PRDs — practitioner response](https://medium.com/@danmas0n/prototypes-are-the-new-prds-8222b8470e64); [LogRocket: How we replaced PRDs with AI prototypes](https://stories.logrocket.com/p/thought-leadership-how-we-replaced-prds-ai-prototypes).

**Date:** Kaplan-Moss 2020-01-16; Whitespectre 2025-04; Figma 2025-12-15; GetDevDone 2026-05-28. Researched 2026-07-19.

---

## 13. Half-shipped work is pure carrying cost: kill criteria first, monkey first, WIP 1-2 — Contested (one stat)

**Claim:** Three moves against the same disease. (a) Write kill criteria in the brief before work starts — pre-mortem-derived, as state+date pairs ("the best quitting criteria combine two things: a state and a date" — Duke) — because the mid-flight version of you is compromised by sunk cost, identity, and ownership effects; the tie-breaker is Duke's "would you start this today knowing what you know now?" (b) Attack the riskiest unknown first: "there is no point building the pedestal if you can't train the monkey," and "low hanging fruit is, by definition, pedestal building, offering the illusion of progress" — pre-PMF, most half-shipped fragments are pedestals that existed because they were buildable, not because they were the test; sequence so the first thing you ship is the thing that could kill the idea. (c) Cap concurrent workstreams at 1-2 per person — WIP is inventory, inventory doesn't compound, and high WIP delays every item simultaneously while degrading quality and fragmenting knowledge. Stop starting, start finishing.

**When it applies:** Any pre-PMF bet at kickoff (criteria + sequencing go in the brief); boards full of initiated-not-finished work; teams celebrating initiation in standup instead of completion. Criteria trigger _reassessment_, not automatic killing — that's the version that survives the grit-vs-quit objection.

**When it fails / contested:** Only the WIP stat is contested — and it's refuted as commonly cited: the "~23-minute re-immersion tax per context switch" has no primary academic source; it's Gloria Mark's informal 2006 Gallup-interview estimate of elapsed time before _returning_ to an interrupted task (typically after ~2 intervening tasks). Her actual paper found interrupted work completed in _less_ total time (20.3-20.6 vs 22.8 min) at significantly higher stress. Cite "interruptions raise stress, not task time," or skip the number. Scrum.org's PSK line adds: optimize WIP per context rather than rigidly capping at a fixed per-person number. The kill-criteria and monkey-first halves survived refutation clean; the nearest counter (small-wins momentum) addresses motivation, not information value. Citation correction from verification: monkeys/pedestals is NOT in the Lenny's Duke interview — cite Duke's own newsletter and the Behavioral Scientist Quit excerpt, both crediting Astro Teller.

**Source:** Duke, [Monkeys and Pedestals newsletter](https://www.annieduke.com/newsletter-monkeys-and-pedestals-find-the-bottleneck-and-solve-for-that-first/) + [Behavioral Scientist excerpt from Quit](https://behavioralscientist.org/annie-duke-quit-mental-models-to-help-you-cut-your-losses/); Duke on [Lenny's Podcast](https://www.lennysnewsletter.com/p/making-better-decisions-annie-duke) (kill-criteria mechanism); Dutta, [Kill Criteria](https://medium.com/@rajeshdutta/kill-criteria-the-uncomfortable-pill-to-swallow-for-product-managers-5f130b3a28a5) — independent practitioner, no Duke citation. WIP: [Leading Trails](https://leadingtrails.substack.com/p/the-silent-killer-why-high-wip-crushes); [Uplevel](https://uplevelteam.com/blog/wip-limits). Corrections/counters: [oberien's 23-min source investigation](https://blog.oberien.de/2023/11/05/23-minutes-15-seconds.html); [Scrum.org PSK on optimizing WIP](https://www.scrum.org/resources/blog/professional-scrum-kanban-psk-dont-just-limit-wip-optimize-it-post-1-3).

**Date:** Duke excerpt 2022-11-07; Lenny's 2024-05-02; Dutta 2025-11-17; oberien 2023-11-05. Researched 2026-07-19.

---

## 14. Sell-first vs build-first is a business-model call, not a philosophy — Contested ⏳ fast-moving (stale after 6 months)

**Claim:** Prefer choosing sell-first vs build-first off your GTM motion, not your temperament: sales-led/enterprise or bootstrapped → sell first; PLG/devtools → build first — and know each side's paired failure mode. Sell-first fails into the consulting trap (bespoke wins that don't generalize; "basically, a consultancy"); build-first fails into the beautiful thing nobody wanted — Pike's own iPad app: 5.0 stars, ~100 customers, "something wonderful that nobody was looking for." The emotional trap on the build side (resisting feedback because the work is your vision) is as expensive as the technical-debt trap on the sell side.

**When it applies:** Sequencing a new product or wedge; refereeing the religious war between "get a check first" and "build the vision" — the meta-heuristic (motion decides sequencing; each side has a named trap) is the durable part.

**When it fails / contested:** Pike himself calls the dichotomy "partly false" — Slack, Mailchimp, and Shopify succeeded as hybrids — so the crisp two-bucket mapping over-sharpens even its own source. And the devtools/PLG→build-first half is a 2024 market-norm snapshot past its sell-by: AI-era devtools widely run sales-led and product-led-sales motions from day one. Treat the mapping as dated; keep the failure-mode pairing.

**Source:** Allen Pike, [Sell First, or Build First?](https://allenpike.com/2024/sell-or-build-first/) — attributed, verified including the hybrid concession that bounds it.

**Date:** Pike 2024-04-30. Researched 2026-07-19.
