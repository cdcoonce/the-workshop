# Dial Patterns (Tailwind + shadcn/Radix + Framer Motion)

Concrete code per dial level. Ranges are guidance, not hard boundaries — interpolate between them.

## DESIGN_VARIANCE

**1-3 (symmetric/centered)**
```tsx
<div className="mx-auto max-w-2xl flex flex-col items-center gap-6 text-center">
  <h1>{title}</h1>
  <p>{description}</p>
</div>
```

**4-7 (asymmetric, weighted grid)**
```tsx
<div className="grid grid-cols-12 gap-8 items-start">
  <div className="col-span-7">
    <h1 className="text-left">{title}</h1>
    <p className="text-left">{description}</p>
  </div>
  <div className="col-span-5 -mt-8">{/* offset visual element */}</div>
</div>
```

**8-10 (overlapping, off-center focal point)**
```tsx
<div className="relative">
  <div className="absolute -top-6 -left-4 rotate-[-2deg] z-10">{badge}</div>
  <div className="grid grid-cols-[1.4fr_1fr] gap-4">
    <h1 className="text-left leading-[0.95]">{title}</h1>
    <div className="translate-y-8">{visual}</div>
  </div>
</div>
```

## MOTION_INTENSITY

**1-3 (none/minimal)**
```tsx
<button className="transition-colors hover:bg-accent">{label}</button>
```

**4-7 (hover + entrance)**
```tsx
<motion.div
  initial={{ opacity: 0, y: 8 }}
  animate={{ opacity: 1, y: 0 }}
  transition={{ duration: 0.3 }}
  className="hover:-translate-y-0.5 transition-transform"
>
  {content}
</motion.div>
```

**8-10 (staggered, scroll-linked, spring)**
```tsx
const container = {
  animate: { transition: { staggerChildren: 0.08 } },
}
const item = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 300, damping: 24 } },
}

<motion.ul variants={container} initial="initial" animate="animate">
  {items.map((it) => (
    <motion.li key={it.id} variants={item}>{it.label}</motion.li>
  ))}
</motion.ul>
```
Use `useScroll` + `useTransform` for scroll-linked reveals when DENSITY is also high (dashboards, long feeds).

## VISUAL_DENSITY

**1-3 (spacious)**
```tsx
<div className="space-y-12 p-12">
  <Card className="p-8">{content}</Card>
</div>
```

**4-7 (balanced)**
```tsx
<div className="space-y-6 p-6">
  <Card className="p-5">{content}</Card>
</div>
```

**8-10 (dense/data-forward)**
```tsx
<div className="space-y-2 p-3 text-sm">
  <Card className="p-2.5 [&_td]:py-1 [&_td]:px-2">{content}</Card>
</div>
```
At high density, drop to `text-sm`/`text-xs` for secondary content and tighten table cell padding — don't just shrink margins.

## Type Scale (all variance/density levels)

Define once, reuse — never let headings be an ad-hoc font-weight bump:
```ts
const type = {
  display: "text-4xl font-semibold tracking-tight",
  h1: "text-2xl font-semibold tracking-tight",
  h2: "text-lg font-medium",
  body: "text-sm text-muted-foreground",
  caption: "text-xs text-muted-foreground",
}
```
