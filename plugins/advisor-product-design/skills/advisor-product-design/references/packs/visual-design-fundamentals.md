# Pack: Visual design fundamentals

> Researched: 2026-07-18 · Staleness threshold: 24 months
> Load me when: Reviewing visual artifacts from an engineer-turned-designer — portfolio pages, dashboards, mobile app screens, chart-heavy UIs.
> Use these entries to name *why* something looks off (spacing, hierarchy, grouping, contrast) instead of saying "it feels unpolished."
> Strongest on typography scales, spacing systems, Gestalt grouping, and the WCAG 2 vs APCA contrast situation as of mid-2026.
> Not a brand/aesthetics pack — no logo, illustration, or motion guidance here.

## Entries

### Derive type sizes from a modular scale
- **Claim:** Pick one base size and one ratio (1.25 Major Third, 1.333 Perfect Fourth) and derive every text size from it; snap off-looking sizes to the nearest step instead of nudging 1–2px ad hoc. 16px at 1.25 gives 16/20/25/31/39 — distinct heading levels with zero arbitrary values.
- **Applies when:** Setting type tokens for a portfolio, marketing page, or app needing ~4–7 sizes; reviewing UIs where heading levels look inconsistent or barely distinguishable.
- **Fails when:** Dense data UIs — ratio-derived jumps are too coarse for captions, axis labels, and table cells, so practitioners insert off-scale utility sizes there. Large ratios (1.618) blow up unusably fast on desktop. Even systems advocates concede type ultimately gets tuned by eye.
- **Source:** Kalamuna, "Modular Type Scaling for Frontend Developers", https://www.kalamuna.com/blog/modular-type-scaling-frontend-developers (n.d., confirmed 2026-07); canonical print source Bringhurst, *The Elements of Typographic Style* (1992/2004).

### Build hierarchy with weight and color before adding sizes
- **Claim:** A UI needs 2–3 weights and colors doing the hierarchy work, not a pile of font sizes. Size is the crudest emphasis lever; weight and value contrast are what make the primary content read first — and de-emphasizing secondary content beats emphasizing primary content.
- **Applies when:** Dashboards or app screens where everything shouts or nothing does; stat tiles and KPI rows where the number should dominate and the label recede.
- **Fails when:** Light weights (≤300) at small sizes die on low-DPI screens and fail contrast; grey de-emphasis collides with WCAG 4.5:1 for anything still functioning as body text. Glanceable contexts (mobile at arm's length, TV) favor size differences, which survive distance and blur better than weight.
- **Source:** Refactoring UI (Wathan & Schoger, 2018), "Hierarchy is Everything"; summary confirmed at https://www.sglavoie.com/posts/2023/09/09/book-summary-refactoring-ui/ (2023-09).

### Never grey text on a colored background
- **Claim:** Grey-on-color reads as washed out and broken. De-emphasize by hand-picking a color with the background's hue, then dropping saturation and raising lightness until it recedes. Moving text color *toward the background* creates hierarchy; literal grey does not.
- **Applies when:** Colored hero sections, alert banners, primary buttons with secondary text, dark brand cards.
- **Fails when:** The harmonious same-hue color frequently lands below 4.5:1 on saturated brand backgrounds — re-check every pick against a contrast tool, and accessibility wins the conflict. Also note published discussion of this rule is nearly all reinforcement, not critique: treat it as craft consensus, not tested finding.
- **Source:** Refactoring UI (Wathan & Schoger, 2018), "Working with Color"; summary confirmed at https://www.sglavoie.com/posts/2023/09/09/book-summary-refactoring-ui/ (2023-09).

### Put a rem term in every fluid type expression
- **Claim:** Never ship viewport-unit type without a rem term in clamp()'s preferred value, and keep max ≤ 2.5× min. Browsers don't scale viewport units on zoom, so pure-vw type silently fails WCAG SC 1.4.4's 200% resize; Barvian's derivation shows max ≤ 2.5× min always passes in modern browsers (given max breakpoint < 5× min breakpoint).
- **Applies when:** Any clamp()-based fluid scale — hero headings, Utopia-style systems, Tailwind arbitrary values; any CSS review where font-size contains vw/vi/vmin.
- **Fails when:** Dramatic display scales (18px → 72px is 4×) exceed the ratio and need breakpoint stepping or a compressed fluid range instead. Utopia's generator now warns per-step when a scale fails SC 1.4.4.
- **Source:** Maxwell Barvian, "Addressing Accessibility Concerns With Using Fluid Type", Smashing Magazine, https://www.smashingmagazine.com/2023/11/addressing-accessibility-concerns-fluid-type/ (2023-11-07).
- **Contested:** w3c/wcag#1671 (https://github.com/w3c/wcag/issues/1671, closed) debated exempting already-huge display headings from strict 200% scaling; community consensus there leaned toward "should not fail," but the SC text grants no exemption — so treat the rule as binding for audits, arguable for lawyering.

### Name your spacing, don't number it
- **Claim:** Replace raw pixel spacing with a small token scale applied through named patterns — Curtis's inset, squish-inset, stretch-inset, stack, inline, grid. Fine-grained linear scales invite "24 or 28? I dunno"; few geometric-ish options force intentional choices. Curtis argues base-16 over base-8: it's the default font size, factors into 320/768/1024, and gives memorable multiples (32, 64) and factors (8, 4, 2).
- **Applies when:** Standing up spacing tokens; design-dev handoff where devs can't tell which spacing a mock intends; auditing codebases full of one-off margins.
- **Fails when:** Curtis concedes line-height interactions create unpredictable spacing collisions needing CSS workarounds, and generic escape-hatch spacing variables remain necessary. Optical adjustments (icon centering, cap-height alignment) legitimately go off-scale.
- **Source:** Nathan Curtis, "Space in Design Systems", EightShapes, https://eightshapes.com/articles/space-in-design-systems/ (2016-09-25).

### Use an 8pt base as scaffold, not law
- **Claim:** Default spacing and sizing to multiples of 8, dropping to 4 for dense contexts. The point is having *a* base unit — 4pt, 6pt, and 8pt systems all deliver the benefit. Flag sibling gaps of 13, 17, and 22px; don't flag a deliberate 4pt half-step.
- **Applies when:** Cross-platform work (8-multiples survive 1x/1.5x/2x device scaling cleanly); teams with no spacing vocabulary; mock reviews with arbitrary adjacent values.
- **Fails when:** Typography rarely lands on 8 — line-heights break the grid, which is why print-style baseline grids mostly failed on the web (text is placed by line-height, not baseline). Odd bases (5pt) produce blurry split pixels when centering in odd-height containers. Religious 8pt enforcement over optical judgment (visually centering an icon) is a known failure mode.
- **Source:** "Spacing, grids, and layouts", designsystems.com, https://www.designsystems.com/space-grids-and-layouts/ (n.d., confirmed 2026-07).

### Keep internal spacing ≤ external spacing
- **Claim:** Padding inside a group must be smaller than or equal to the gap between groups, or proximity grouping misfires and users parse the wrong elements as related. This is the most common single cause of "something looks off" in card grids and forms.
- **Applies when:** Card layouts; label/field pairs (label sits closer to its own field than to the previous field); dashboard tile grids; list items with metadata.
- **Fails when:** Dense tables and toolbars where spacing is uniform by necessity — borders, zebra striping, or containers must carry grouping there. Also moot as a heuristic when an explicit container already establishes the boundary.
- **Source:** Cieden, "Spacing best practices", https://cieden.com/book/sub-atomic/spacing/spacing-best-practices (n.d., confirmed 2026-07).

### Group with whitespace before boxes
- **Claim:** Vary whitespace to unite or separate elements before reaching for borders and boxes. Proximity is strong enough to overpower competing cues like color or shape similarity; added borders in low-density UIs read as chrome, not structure.
- **Applies when:** Content pages, settings screens, portfolios — low-to-medium-density layouts.
- **Fails when:** High-density UIs where the whitespace budget can't disambiguate — there, common region (cards) is the stronger cue. Also fails when the within-group vs between-group difference is too subtle to perceive, which just manufactures ambiguity.
- **Source:** Aurora Harley, "Proximity Principle in Visual Design", Nielsen Norman Group, https://www.nngroup.com/articles/gestalt-proximity/ (2020-08-02).

### In dense dashboards, contain each unit
- **Claim:** Group each title + chart + metadata unit in an explicit container. Items inside a visible boundary are perceived as a functional group, and common region overrides proximity and similarity — exactly what you need when tile spacing is necessarily uniform and small.
- **Applies when:** Multi-chart dashboards, stat-tile rows, card feeds — anywhere whitespace can't carry the grouping.
- **Fails when:** Container overuse: a border on everything makes chrome compete with data and flattens hierarchy; NN/g itself warns containers create false stopping points that suppress scrolling. Nested cards-in-cards are a smell. Low density → go back to whitespace.
- **Source:** Aurora Harley, "The Principle of Common Region: Containers Create Groupings", Nielsen Norman Group, https://www.nngroup.com/articles/common-region/ (2020-07-12).

### Hold WCAG 2 AA as the shipping floor
- **Claim:** 4.5:1 body, 3:1 large text and UI components — ship to that, even knowing the math is perceptually flawed. WCAG 2 is the normative, legally-cited standard; WCAG 3 is "perhaps 2030 at the soonest" and its contrast algorithm is officially yet to be determined. Roselli's advice: pass both WCAG 2 and APCA, or document every WCAG 2 miss with a response plan.
- **Applies when:** Anything shipping to real users; any compliance-sensitive or procurement context.
- **Fails when:** Near the threshold and near black, the ratio is bureaucratic truth, not perceptual truth: #777 on white fails at 4.48:1 while indistinguishable #767676 passes at 4.54:1, and dark-mode pairs can pass AAA (e.g. #B0B0B0 on #1E1E1E at 7.69:1) while reading poorly. Don't defend a boundary pass as "readable" — defend it as "compliant."
- **Source:** Adrian Roselli, "WCAG3 Contrast as of April 2026", https://adrianroselli.com/2026/04/wcag3-contrast-as-of-april-2026.html (2026-04); threshold examples from 66colorful, https://66colorful.com/blog/apca-contrast/ (2026).
- **Contested:** Andrew Somers/Myndex ("Why APCA", https://git.apcacontrast.com/documentation/WhyAPCA.html) argues WCAG 2 contrast is perceptually invalid and should be superseded; Roselli's counter is that draft guidance carries no legal weight today.

### Use APCA as a design-time check, never a compliance claim
- **Claim:** APCA's Lc values are font-size- and weight-aware (Lc 60 from 24px/400 or 16px/700), which catches exactly what WCAG 2 misses: thin fonts and dark-mode pairs. Run it when designing dark themes, secondary/placeholder text, and weight-varied type — but never ship APCA-only colors without documenting the WCAG 2 deviations.
- **Applies when:** Dark palettes, light-weight type systems, any pair WCAG 2 blesses that still looks muddy.
- **Fails when:** Compliance contexts — APCA was pulled from the WCAG 3 working draft in July 2023 and remains a candidate method, so relying on it alone creates legal exposure; versions embedded in old drafts are obsolete, so tool results vary.
- **Source:** 66colorful, "APCA Contrast vs WCAG 2: The 2026 Guide", https://66colorful.com/blog/apca-contrast/ (2026); status per Roselli, https://adrianroselli.com/2026/04/wcag3-contrast-as-of-april-2026.html (2026-04).
- **Contested:** Eric Eggert ("WCAG 3 is not ready yet", https://yatil.net/blog/wcag-3-is-not-ready-yet, 2021-12) warned designers off early APCA adoption; the APCA team published a point-by-point rebuttal claiming factual errors. Live, two-sided dispute — cite the removal date, not either camp's rhetoric.

### Set 45–75 characters per line — as comfort, not science
- **Claim:** Keep reading text around 45–75cpl (66 classic), but wield it as a preference rule, not a performance law. Dyson's review of the screen-reading research shows longer lines are read as fast or faster (Duchnicky & Kolers 1983 found faster reading at full width; her own 1998 work agrees), while readers consistently *judge* long lines least easy to read.
- **Applies when:** Blog/portfolio body text, docs, long-form surfaces; text columns stretching edge-to-edge on wide monitors.
- **Fails when:** Doesn't apply to UI labels, table cells, or scannable dashboard text. Readers with dyslexia may genuinely need shorter lines (Schneps et al. 2013). And citing 45–75 as "proven optimal for reading speed" is factually wrong — the honest framing is comfort and trust, not speed. Dyson herself won't recommend long lines despite the speed data.
- **Source:** Mary Dyson, "Line length revisited: following the research", Design Regression, https://designregression.com/article/line-length-revisited-following-the-research (2021-09-08); discussed at https://css-tricks.com/line-length-revisited-following-the-research/ (2021-11).
- **Contested:** The Bringhurst-derived 45–75/66cpl consensus (e.g., Baymard, https://baymard.com/blog/line-length-readability) presents the range as evidence-based optimum; Dyson — a University of Reading typography researcher — shows the speed evidence points the other way.

### Give every overlay unambiguous figure/ground
- **Claim:** Modals, sticky headers, drawers, and chart tooltips need clear figure/ground separation — scrim, elevation shadow, blur — because users treat whatever visually separates from the background as the thing to focus on and interact with. Weak separation makes overlays read as page content and page content read as tappable.
- **Applies when:** Mobile overlay reviews; tooltips/popovers over dense charts; any modal that "floats" without a dimmed backdrop.
- **Fails when:** When everything is elevated, nothing is — shadow-on-every-card flattens the hierarchy. Heavy scrims fail when the user must compare overlay content against the data beneath (filter panel over a chart). Flat-minimal styles that strip these cues are trading discoverability for aesthetics — name the trade.
- **Source:** Samhita Tankala, "Figure/Ground: Gestalt Principle for User Interface Design", Nielsen Norman Group, https://www.nngroup.com/videos/figure-ground-gestalt/ (n.d., confirmed 2026-07).

### Pull grid gutters from the spacing scale
- **Claim:** Layout-grid gutters and page margins must be members of the spacing token scale, not a parallel system — Curtis's sixth spacing concept is "grid" for exactly this reason. Gutters that don't align with component spacing produce the subtle misalignment that reads as "off" without anyone being able to say why.
- **Applies when:** Page-level layout for portfolios and web apps; responsive column systems; reviews where card padding, inter-card gap, and page margin are three unrelated numbers.
- **Fails when:** Widget-grid dashboards where user-resizable tiles drive layout instead of an editorial 12-column grid. Deliberate grid-breaking (full-bleed images, pull-outs) is a technique, not a defect — flag only unintentional violations.
- **Source:** Nathan Curtis, "Space in Design Systems", EightShapes, https://eightshapes.com/articles/space-in-design-systems/ (2016-09-25); supporting: https://www.designsystems.com/space-grids-and-layouts/.

### Re-audit grouping at every breakpoint
- **Claim:** Reflow silently breaks proximity relationships — never sign off a responsive layout without re-checking what *reads as grouped* at each width, not just whether content fits. NN/g's documented failures: Transport for London's emission-zone links read as a pair on desktop but stacking distanced them on mobile so users missed the second; Kayak's skip link sat so far from the sign-in options it modified that users thought sign-in was mandatory; Wellington City Council had to reposition mobile search to avoid mis-grouping with navigation.
- **Applies when:** Any breakpoint review of a responsive dashboard, web companion, or portfolio site.
- **Fails when:** Container-carried groupings (common region) survive reflow far better than whitespace-only ones — concentrate audit effort on whitespace-grouped layouts. Moot for single-column mobile-first layouts that never reflow horizontally.
- **Source:** Aurora Harley, "Proximity Principle in Visual Design", Nielsen Norman Group, https://www.nngroup.com/articles/gestalt-proximity/ (2020-08-02).
