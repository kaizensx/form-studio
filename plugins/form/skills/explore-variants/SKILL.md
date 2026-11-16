---
name: explore-variants
description: Compare design candidates or search parameter ranges in FORM with explicit objectives and constraints. Use when the user asks "which is best", wants the lightest/stiffest/cheapest version, or a trade-off between two or more variants.
---

# Explore variants

FORM tools: `explore_alternatives()`, `optimize()`, `preview_change()`, `render()`, `compare_revisions()`, `commit_change()`.

1. State hard constraints before ranking: measured interfaces stay fixed, the envelope fits the printer, the fit
   window holds. Only vary `form` and `process` parameters unless the user asks otherwise.
2. Small grid (1–2 parameters, up to 5 values each): `explore_alternatives(axes=[...], weights=...)`.
   Goal seek over 1–4 parameters: `optimize(vary=[...], objective={"minimize": "solid_mass_g"},
   constraints=["statics.safety_factor >= 3", "fit_yield >= 0.9"])`. Every candidate is built by the kernel.
3. Look at the best two or three: `render(values=..., view="sheet")` with the same views for each.
4. Recommend one with concrete trade-offs, then `preview_change()` and, with the user's agreement, `commit_change()`.

Honesty
- Name the objectives that were actually evaluated and the finite set searched: "best of 40 builds", not "optimal".
- Mass and volume are computed from the solid; print time and filament come only from a real slice (simulated).
  Never substitute solid volume for filament use or invent a print estimate.
- `statics.*` metrics are simple models, not FEA and not a strength qualification of a layered part.
- Aesthetic judgement and physical tests stay separate from the ranking. Ask the user only when the remaining
  preference materially changes the design.
