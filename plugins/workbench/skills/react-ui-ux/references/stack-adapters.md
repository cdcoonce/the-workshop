# Stack Adapters (non-Tailwind projects)

Same three dials, same anti-genericness rules — translated to whatever styling approach the project already uses. Detect via `package.json` + an existing component before picking one of these.

## MUI

- `DESIGN_VARIANCE` → override `theme.components` slot styles per-component rather than accepting default `Card`/`Paper` elevation; use `Grid2` with asymmetric `size` props instead of centered `Stack`
- `MOTION_INTENSITY` → MUI's `Grow`/`Slide`/`Fade` transition components; `Collapse` for staggered lists
- `VISUAL_DENSITY` → theme `components.MuiTableCell.styleOverrides` / the built-in `size="small"` density prop, not manual padding overrides
- Anti-genericness: override the default MUI blue (`#1976d2`) and default `borderRadius: 4`; define a real `typography` scale in the theme instead of relying on default `variant` sizes

## styled-components / Emotion (CSS-in-JS, no component library)

- `DESIGN_VARIANCE` → asymmetric CSS Grid (`grid-template-columns: 1.4fr 1fr`) instead of `display: flex; justify-content: center` everywhere
- `MOTION_INTENSITY` → `keyframes` + `transition` for low/mid; pull in Framer Motion only if already a dependency, otherwise stay in pure CSS
- `VISUAL_DENSITY` → a shared spacing scale (`const space = [0, 4, 8, 12, 16, 24, 32, 48]`) referenced by index, not ad-hoc px values
- Anti-genericness: define an actual color palette object and type scale as constants, imported everywhere — no inline hex/px one-offs

## CSS Modules / vanilla CSS

- `DESIGN_VARIANCE` → CSS Grid with named areas for asymmetric layouts; avoid the reflexive `.container { display:flex; flex-direction:column; align-items:center }`
- `MOTION_INTENSITY` → CSS `transition`/`@keyframes` in the module file; `prefers-reduced-motion` media query respected at every level (already required by ux-reviewer)
- `VISUAL_DENSITY` → CSS custom properties for spacing (`--space-sm`, `--space-md`, `--space-lg`) referenced consistently, not per-component magic numbers
- Anti-genericness: a real `:root` type-scale + color-token set in a shared stylesheet, not per-module inline values

## General rule when no dedicated component library exists

Still build the anti-genericness rules in as constants/tokens (spacing scale, type scale, palette) even if there's no `theme` object to hang them on — the goal is consistency and intentionality, not a specific API.
