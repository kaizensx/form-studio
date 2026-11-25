---
name: staged-design
description: Stage a complex Form Studio design (a mechanism, an organic or styled form, a texture, several parts) through brief, guide topics, exemplars, plan, skeleton, one feature at a time, critique and refinement. Use when a request is more than a simple prismatic part, or when create_design refuses a design as complex until it has a brief and a plan.
---

# Staged design

FORM tools: `design_brief()`, `design_guide()`, `design_examples()`, `plan_design()`, `create_design()`,
`add_feature()`, `build_candidates()`, `render()`, `render_photo()`, `critique()`, `refine_design()`, `ask_user()`,
`ask_measurement()`.

Form Studio enforces this for complex designs: `create_design()` refuses one without a plan and gives the reasons
(a heuristic).

1. **Brief.** `design_brief()`: goal, requirements, key dimensions with their source (measured, specified or
   assumed), constraints, style and the unknowns. Never guess a dimension that changes fit, load or safety: ask with
   `ask_user()` or `ask_measurement()`, one question at a time, at most three per task. The brief returns the guide
   topics and exemplars to read.
2. **Read.** `design_guide()` for each topic the brief names (the cad-core, surfacing-organic, texture,
   assemblies-and-mechanisms and industrial-design skills carry the same texts), and `design_examples()` for the
   closest exemplar. Read its source.
3. **Plan.** `plan_design()`: every feature with how it is built (which form.craft helper, which sections), the parts,
   key dimensions, mechanisms with their clearances, textures with their tier, and a route per feature. Unknown
   helper names are refused; each step comes back with its risk and fallback.
4. **Skeleton.** `create_design()` with `plan=<brief id>` and only the skeleton feature. Look at the six-view sheet
   and the section it returns before adding anything.
5. **One feature at a time.** `add_feature()` per plan step. A failure comes back diagnosed: apply the first fix,
   retry at most twice, then defer it and list it. A risky step with several constructions: `build_candidates()`.
6. **Critique.** `critique()` with close-ups, metrics and a checklist; for a design that must look good, score the
   aesthetic items from `render_photo()` pictures. Fix the lowest item and critique again. A briefed design cannot be
   released until its head revision has a critique pass.
7. **Refinement.** The refinement engine runs after each build and lands one "Refined" revision, kept only when the
   checks pass and interface faces are unchanged. `refine_design()` reports it, undoes one change or turns it off.

One request makes one design. A second design in the same conversation states its relation (replaces, part_of,
alternative, new).
