---
name: industrial-design
description: Develop the form and appearance of a FORM part — concepts, proportion, radius families, seams, grip, finger access. Use when the user cares how it looks or feels, or asks for something "nicer", before or while modelling. For critiquing a finished revision use design-review.
---

# Industrial design that can be evaluated

FORM tools: `render()`, `render_photo()`, `critique()`, `set_appearance()`, `preview_change()`, `explore_alternatives()`,
`commit_change()`, `update_design()`, `refine_design()`.

Adjectives such as "premium" are not acceptance criteria. Translate intent into observable geometry.

1. Establish use, visible faces, material and two or three real references. Say what transfers from each: silhouette,
   mass distribution, edge transitions, reveal depth, hardware treatment. Do not copy logos.
2. Default direction: quiet objects, clean silhouette, restrained transitions, purposeful negative space, concealed or
   aligned fixings, tactile finger access, a logical seam. The manufacturing process should explain the details.
3. For a design-sensitive part, compare three genuinely different constructions (for a holder: monolithic cradle,
   split clamshell, minimal rail with separate retention). Three corner radii on one box are not three concepts.
   Build candidates for real: `preview_change()` + `render(values=..., view="sheet")`, or `explore_alternatives()`
   for a parameter sweep. Write one line of rationale each and pick one. Skip this for a fully dimensioned simple part.
4. Details: a small radius hierarchy instead of unrelated fillets; entry chamfers; finger relief; drainage where water
   can stand; seam and support scars away from the main visible face; text and logos optional, off by default.
5. Judge the real filament surface, not a metallic render. Avoid grooves or text below a printable scale. Prefer a
   chamfer to a bottom fillet that would print unsupported.

The method, step by step (design language, proportion system, continuity, radius hierarchy, surface breaks and
shadow gaps, detail rhythm, material and colour, then look, score, fix): `references/aesthetics.md`, the same text as
`design_guide(topic="aesthetics")`. For a "make it beautiful" request, score the photos with `critique()` and fix the
lowest item, at least two passes.

The refinement engine runs after every build (fillet tiers, an edge break, a parting line, grip, materials and
contrast) and keeps each change only when the checks pass and interface faces are unchanged. Read what it did with
`refine_design()` and take out a change that fights the design language. Game assets are refined only when turned
on (`refine_design(action="on")`).

Never improve looks by shrinking a required clearance or thinning a load-bearing root. Stop when the requirements are
met and no visible or manufacturing defect remains; do not iterate on cosmetics forever. Ask the user for a photo of
the first real print under ordinary light and revise from it.
