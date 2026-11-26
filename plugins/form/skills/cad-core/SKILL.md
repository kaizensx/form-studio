---
name: cad-core
description: Write a Form Studio design as code (build123d on OpenCascade) that builds, is editable through named Params and passes the checks, and change it with edit_design ops instead of resending the file. Use when calling create_design, edit_design or update_design for anything the built-in recipes do not cover, or when a build fails and you need the contract, the rules or a worked example.
---

# CAD core: the design contract

FORM tools: `design_guide()`, `design_brief()`, `create_design()`, `edit_design()`, `add_feature()`,
`update_design()`, `build_candidates()`, `render()`, `get_project()`, `get_design_source()`, `refine_design()`.

A Form Studio design is one Python file with one design class. The kernel builds it, names every face after the
feature that made it, and derives STEP, STL, checks and pictures from it. The source is the only authority.

1. Read `references/contract.md` before the first `create_design()`: the contract, the rules, hardware (`form.parts`),
   assemblies, text and patterns, and what to do when a build fails. `design_guide(topic="core")` returns the same
   text; for a design whose purpose is print it swaps rules 5 and 6 for bed orientation, overhang and wall rules.
2. Skeleton first, one validated feature at a time: `create_design()` with the skeleton feature only, look at
   `render(view="sheet")`, then one `add_feature()` per feature. A feature that fails twice is deferred and listed;
   it never blocks the design.
3. Change a design by naming what changes: `get_design_source()` once (it returns one method per feature and the
   feature ids), then `edit_design()` with ops (replace, insert, delete, set_param). One call is one build and one
   revision; only the changed feature and the ones after it are built. Never send the whole file back for a change.
4. Say what must be true and let the kernel check it: `design_brief()` returns the contract (kernel-checkable
   assertions) and an audit of missing, conflicting or impossible numbers to settle before coding;
   `@feature(..., expects=[contract.bolt_circle(4, 5.2, 60)])` makes a feature fail where it misses, with measured
   against wanted; `get_project()` returns the proof sheet. Claim only its PASS rows.
5. The source is checked before the kernel runs (preflight) and every problem comes back at once: violated
   constraints, unknown names and keywords, undeclared parameters, a clockwise Polygon extruded upward, a thread
   pair that does not engage. Fix them all in one call.
6. A risky step with two or three plausible constructions: `build_candidates()` builds them in parallel and keeps
   the best.
7. Worked examples that build: `references/example-recipe.md` (a two-part box written as a Recipe) and
   `references/example-features.md` (a FeatureDesign with one method per feature).
8. After every build Form Studio refines the design automatically (fillet tiers, edge breaks, parting lines, grip,
   materials) as one more revision, kept only when the checks still pass and the interface features are unchanged.
   Give fit, access, mechanism and interface features those roles so they stay exact. `refine_design()` reports the
   status, takes one change out (`action="undo"`) or turns refinement off. A game asset is not refined unless it is
   turned on (`action="on"`).

Complex designs (a mechanism, an organic or styled form, a texture, several parts) are staged: see the staged-design
skill. Meshes to make editable: see remodel-from-mesh.

Units are mm, degrees and grams. A dimension is `specified` only with a named source, `measured` only when the person
measured it and told you, otherwise `assumed`. The design source runs in Form Studio's kernel worker: write geometry,
never file, network or process access.
