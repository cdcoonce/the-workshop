---
name: chart-taste
description: Applies chart-design taste to React data visualization — a chart-type decision tree and adjustable dials (annotation density, complexity, color restraint) to stop charts from being technically-rendered-but-uninformative. Use when building charts or data visualizations with Recharts, Nivo, or similar React charting libraries.
---

# Chart Taste

A chart can be accessible, on-brand, and technically correct and still fail its job: not answering the question it was built to answer. This skill governs a single chart's own design — type, annotation, decluttering, color. Container chrome (padding, corner radius, entrance motion) is `react-ui-ux`'s job when both skills are active; this skill only governs what's drawn inside the chart canvas.

## 1. Check Whether a Chart Is Even the Right Call

1-2 data points, or a single aggregate value → recommend a big-number/stat callout with a trend arrow or sparkline instead of a full axis-and-legend chart. Don't build a chart just because one was asked for if the data can't support it.

## 2. Pick the Chart Type

Use the decision tree in `references/chart-type-decision-tree.md` (data shape → chart type, with named exceptions for ambiguous cases).

If the user explicitly requests a type the tree disagrees with (e.g. a pie chart for 12 categories): **build what was asked, but state the trade-off and name the better alternative in one line.** Never silently substitute a different chart type than requested.

## 3. Set the Three Dials

Each dial is 1-10. Infer from context and **state values before generating**, same pattern as `react-ui-ux`:

> "Using ANNOTATION_DENSITY=4, CHART_COMPLEXITY=5, COLOR_RESTRAINT=7 — single KPI trend, one thing to highlight."

The user can override mid-session ("more annotation", "simplify this").

- **ANNOTATION_DENSITY** — low: axis labels only. Mid: a reference line or callout on the key data point. High: full narrative annotations (e.g. "+18% after launch" text anchored to the inflection point).
- **CHART_COMPLEXITY** — low: single clean series. Mid: multi-series on one chart. High: small multiples / faceted views when series would otherwise overlap unreadably.
- **COLOR_RESTRAINT** — low: full categorical palette, one hue per series. Mid: limited palette (3-4 hues) + gray out non-focal series. High: monochrome + single accent color on the one series that matters.

Concrete Recharts/Nivo code per dial level: `references/library-patterns.md`.

## 4. Declutter Defaults

Regardless of dial settings, avoid the default library look:

- No legend when there's only one series (redundant with the axis/title)
- No gridlines on both axes at full opacity — keep one axis's gridlines, fade or drop the other
- Axis labels present and unit-labeled (`$`, `%`, `k`) — never a bare unlabeled number scale
- Tooltip shows the value with its unit and label, not just a raw number

## 5. Advanced

- `references/chart-type-decision-tree.md` — data shape → chart type table with exceptions
- `references/library-patterns.md` — Recharts/Nivo code per dial level
