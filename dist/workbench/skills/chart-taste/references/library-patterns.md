# Library Patterns (Recharts + Nivo)

Concrete code per dial level. Ranges are guidance — interpolate between them.

## ANNOTATION_DENSITY

**1-3 (axis labels only)**
```tsx
// Recharts
<LineChart data={data}>
  <XAxis dataKey="date" />
  <YAxis tickFormatter={(v) => `$${v}`} />
  <Line dataKey="value" stroke="var(--chart-1)" dot={false} />
</LineChart>
```

**4-7 (reference line / single callout)**
```tsx
// Recharts — mark one inflection point
<LineChart data={data}>
  <XAxis dataKey="date" />
  <YAxis tickFormatter={(v) => `$${v}`} />
  <Line dataKey="value" stroke="var(--chart-1)" dot={false} />
  <ReferenceLine x={launchDate} stroke="var(--muted-foreground)" strokeDasharray="3 3"
    label={{ value: "Launch", position: "top" }} />
</LineChart>
```

**8-10 (narrative annotation anchored to data)**
```tsx
// Recharts — custom label with the actual insight, not just a marker
<ReferenceDot x={inflectionDate} y={inflectionValue} r={4} fill="var(--chart-1)">
  <Label value={`+${pctChange}% after launch`} position="top" offset={12} />
</ReferenceDot>
```

## CHART_COMPLEXITY

**1-3 (single series)**
```tsx
<LineChart data={data}>
  <Line dataKey="value" stroke="var(--chart-1)" />
</LineChart>
```

**4-7 (multi-series, one chart)**
```tsx
<LineChart data={data}>
  <Line dataKey="regionA" stroke="var(--chart-1)" />
  <Line dataKey="regionB" stroke="var(--chart-2)" />
  <Line dataKey="regionC" stroke="var(--chart-3)" />
  <Legend />
</LineChart>
```

**8-10 (small multiples / faceted)**
```tsx
// One mini chart per series instead of 5+ overlapping lines
<div className="grid grid-cols-3 gap-4">
  {series.map((s) => (
    <div key={s.key}>
      <p className="text-xs text-muted-foreground">{s.label}</p>
      <LineChart width={200} height={80} data={s.data}>
        <Line dataKey="value" stroke="var(--chart-1)" dot={false} />
      </LineChart>
    </div>
  ))}
</div>
```

## COLOR_RESTRAINT

**1-3 (full categorical palette)**
```tsx
const COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"]
{series.map((s, i) => <Line key={s.key} dataKey={s.key} stroke={COLORS[i % COLORS.length]} />)}
```

**4-7 (limited palette + gray non-focal)**
```tsx
{series.map((s) => (
  <Line
    key={s.key}
    dataKey={s.key}
    stroke={s.key === focalSeries ? "var(--chart-1)" : "var(--muted-foreground)"}
    strokeOpacity={s.key === focalSeries ? 1 : 0.4}
  />
))}
```

**8-10 (monochrome + single accent)**
```tsx
{series.map((s) => (
  <Bar
    key={s.key}
    dataKey={s.key}
    fill={s.key === highlightKey ? "var(--chart-1)" : "var(--muted)"}
  />
))}
```

## Nivo Equivalents

- `ANNOTATION_DENSITY` → Nivo's `markers` prop on `ResponsiveLine` (`{ axis: 'x', value: launchDate, legend: 'Launch', lineStyle: { stroke: 'var(--muted-foreground)', strokeDasharray: '3,3' } }`)
- `CHART_COMPLEXITY` → `ResponsiveLine` with multiple `series` entries for mid-complexity; drop to a manual grid of individual `ResponsiveLine` instances (one series each) for small-multiples at high complexity — Nivo has no built-in facet grid
- `COLOR_RESTRAINT` → `colors` prop: a full `nivo` categorical scheme at low restraint, a custom 2-color function (`(d) => d.id === focalSeries ? accentColor : mutedColor`) at mid/high restraint

## Declutter Defaults (both libraries)

```tsx
// Recharts: no legend for single series, faded secondary gridlines
<CartesianGrid strokeDasharray="3 3" vertical={false} />
{series.length > 1 && <Legend />}

// Nivo: equivalent via theme
theme={{ grid: { line: { stroke: "var(--border)", strokeWidth: 1 } } }}
enableGridX={false}
```
