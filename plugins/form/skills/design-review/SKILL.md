---
name: design-review
description: Review a FORM revision from designer, engineer and print-technician perspectives with the silhouette / relationships / details rubric. Use when asked for a design review or critique, or before request_release on a part people will see or handle.
---

# Design review

FORM tools: `get_project()`, `render()`, `get_design_source()`, `compare_revisions()`, `preview_change()`.

Review the actual current revision, not a memory of it. `get_project()` for head, checks and slice; then
`render(view="sheet")`, `render(view="bottom")` and `render(view="iso_back")`. Use the same views between revisions;
`compare_revisions()` for what changed.

Three scales
1. **Silhouette** (front, left, top): is the mass balanced, the useful volume clear, does it look stable and intentional?
2. **Relationships**: spacing, wall thickness, corner families, repeated features, contact points. A small radius
   hierarchy beats unrelated fillets everywhere.
3. **Details**: seam location, entry chamfers, finger relief, drainage, support scars, tool access, the underside and
   the assembled state. Look at the print orientation as well as the use orientation.

Three passes
- Designer: proportion, interaction, finish.
- Engineer: interfaces, load path, assembly, tolerances (read the checks and fit model).
- Print technician: orientation, layer direction at loaded roots, overhangs, supports, seams (read the simulated slice).

Score each 0–5 and explain the two weakest with evidence from the renders or checks:
function and fit · proportion · geometric coherence · manufacturing integration · assembly and use · visual restraint.

Then list concrete defects, each with the parameter or feature to change and the expected effect. Offer to try the
top one with `preview_change()`; do not commit without the user. Reject for any critical functional defect regardless
of the average. Scores organise critique; they are subjective, not a certification, and not physical validation.
