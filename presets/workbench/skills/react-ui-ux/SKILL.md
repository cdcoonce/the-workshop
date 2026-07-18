---
name: react-ui-ux
description: Applies deliberate design taste to React UI generation — adjustable dials (variance, motion, density) and explicit anti-genericness rules to stop AI-generated components from defaulting to the generic shadcn/Tailwind look. Use when building or editing React components, pages, or layouts (.tsx/.jsx), especially new UI generation in Tailwind/shadcn/Framer-Motion projects.
---

# React UI/UX Taste

Frontend-builder handles correctness (a11y, state, testing). This skill handles taste: stopping generated UI from reading as generic AI output.

## 1. Detect the Stack

Before writing anything, check `package.json` and skim 1-2 existing components:

- Tailwind + shadcn/Radix present → use dial patterns directly (see `references/dial-patterns.md`)
- Anything else (CSS Modules, styled-components, MUI, vanilla CSS) → translate the same principles using that project's actual approach (see `references/stack-adapters.md`)
- Framer Motion present → use it for `MOTION_INTENSITY` guidance; otherwise fall back to CSS transitions

Never silently no-op on a non-Tailwind project — always apply the underlying principles in whatever the project already uses.

## 2. Set the Three Dials

Each dial is 1-10. Infer values from context (app type, existing density/motion in the codebase, explicit user asks) and **state them before generating**:

> "Using VARIANCE=6, MOTION=5, DENSITY=5 — dashboard-style app, moderate polish."

The user can override mid-session ("more density", "less motion") — don't ask upfront, don't require a config file.

- **DESIGN_VARIANCE** — layout experimentation. Low = centered/symmetric. High = asymmetric grids, overlapping elements, off-center focal points.
- **MOTION_INTENSITY** — animation depth. Low = no transitions. High = staggered entrances, scroll-linked reveals, spring physics.
- **VISUAL_DENSITY** — information density. Low = spacious, generous whitespace. High = compact, information-dense layouts.

Concrete code per level: `references/dial-patterns.md`.

## 3. Anti-Genericness Rules

Regardless of dial settings, actively avoid the default "AI look":

- Centered flex-column as the only layout shape
- `bg-gray-50` / `bg-gray-100` as the default background
- `rounded-lg` on every single element with no variation
- `indigo-600` / `blue-600` as the reflexive primary color
- No deliberate type scale — every heading is just a bigger font-weight bump
- Default shadcn component usage with zero customization (spacing, radius, color tokens all left at defaults)

Pick specific alternatives (a real type scale, an intentional accent color, varied corner radii by element role) — vague "make it nicer" is not a rule, it's not a pattern.

## 4. Editing Existing Components

If the component already exists and has an established design language — even a generic one — **match it first**. Apply the dials only to genuinely new elements being added in the same change. Don't introduce a jarring one-off aesthetic mid-app; flag broader inconsistency for a separate follow-up instead of unilaterally fixing it inline.

## 5. Advanced

- `references/dial-patterns.md` — concrete Tailwind/shadcn/Framer Motion code per dial level
- `references/stack-adapters.md` — translating the dials/rules to MUI, styled-components, CSS Modules
