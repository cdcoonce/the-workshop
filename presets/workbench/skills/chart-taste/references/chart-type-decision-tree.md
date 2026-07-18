# Chart Type Decision Tree

Match the data shape to a default chart type. Deviate only for the named exceptions below — don't pick a type because it's visually interesting.

## By Data Shape

| Data shape | Default chart type | Why |
|---|---|---|
| Trend over time, 1 series | Line chart | Continuity of the x-axis is the point; bars imply discrete unrelated buckets |
| Trend over time, 2-4 series | Multi-line chart | Direct comparison of trajectories; more than ~4 lines gets unreadable — switch to small multiples |
| Trend over time, 5+ series | Small multiples (one mini line chart per series) | A single chart with 5+ overlapping lines is unreadable regardless of color |
| Part-to-whole, ≤5 categories | Stacked bar or donut | Few enough slices/segments to compare by eye |
| Part-to-whole, 6+ categories | Horizontal bar (sorted, not pie) | Pie/donut with 6+ slices makes angle comparison impossible; a sorted bar makes ranking immediate |
| Comparison across many categories (not part-to-whole) | Horizontal bar, sorted by value | Vertical bars with long category labels force rotated/truncated text; horizontal + sorted reads top-to-bottom as a ranking |
| Comparison across few categories (≤5), no time dimension | Vertical bar | Short labels fit under vertical bars; matches reading order for a small set |
| Distribution of a single variable | Histogram or box plot | Shows spread/shape, which a bar or line chart of raw values cannot |
| Correlation between two variables | Scatter plot | Only chart type that shows the relationship between two continuous variables directly |
| Single aggregate value or 1-2 data points | Stat/KPI callout, not a chart | See SKILL.md §1 — a chart implies structure that doesn't exist yet at this data size |

## Named Exceptions

- **Time series with an obvious inflection point** (launch, incident, policy change): even at 1 series, prefer a line chart with an annotation on the inflection point over a bare line — this is what `ANNOTATION_DENSITY` governs, not the type choice itself.
- **Part-to-whole where one category dominates (>60% of total)**: a single stat ("Category X is 64% of total") beside a simplified bar often communicates faster than any part-to-whole chart, especially at ≤5 categories.
- **Comparison across categories AND over time simultaneously**: don't force this into one chart. Prefer small multiples (one per category, sharing a time x-axis) or, if the user needs a single view, a heatmap — not a bar chart with too many grouped/stacked series.
- **Ranked leaderboard with a "your position" callout** (e.g. "you rank 12th of 50"): horizontal bar, sorted, with the relevant entry highlighted via `COLOR_RESTRAINT`'s highlight-one-series mode — not a full unhighlighted table.
