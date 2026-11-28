---
name: strength-studies
description: Answer "will it hold?" on a FORM design with a strength study — supports and loads on picked faces, a sourced material, a result read with its convergence and its singularities. Use when asked about strength, stiffness, safety factor, deflection, natural frequency, buckling, temperature or thermal stress, or before calling a load-bearing part ready.
---

# Strength studies

FORM tools: `analyze_selection()`, `strength_study()`, `get_strength_study()`, `set_appearance()`, `optimize()`,
`make_lighter()`, `inverse_design()`, `get_inverse_design()`, `topology_optimise()`, `get_topology()`,
`apply_topology()`, `edit_design()`.

A study is a simulation with a stated error. Report it as one: quote the evidence class it returns
(`simulated (FEA, linear static, converged to 1.8 %)`), never "it will hold" on its own. Full method, limits and the
verification table: `references/strength.md`.

1. **Ask what the part must carry** when the person has not said: how big the load is, where it acts, where the part
   is held. A load you invent makes every number after it meaningless. Mark an assumed load as assumed.
2. **Pick faces as points.** A support or a load sits on a face, given as a point on it, `[x, y, z]` in design
   millimetres on the part as printed. Check each point with `analyze_selection(items=[{"kind": "face", "at": [...]}])`
   first: it names the face, its type and its area. A hole's wall is a cylinder; pick a point on the wall, not on the
   axis. Never load a point or an edge.
3. **Hold it the way it is held.** `fixed` for a face that is clamped or glued, `pin` for a hole on a shaft or a bolt
   that may turn, `roller` for a face resting on a surface or a symmetry plane, `hold` for single directions. The
   supports together must stop the part moving and turning as a whole, or the study is refused.
4. **Give the material.** `material="AL-6061"` reads Young's modulus, Poisson's ratio, yield and density with their
   sources. When a value is missing the study says which; give it with where it is from
   (`{"key": "PLA", "poisson": 0.35, "source": "..."}`), and say that it is assumed when you have no source. Without a
   yield strength there is no safety factor: do not make one up from a typical number.
5. **Run and wait.** `strength_study(...)` starts it in the background; `get_strength_study(project, study,
   wait_s=60)` returns it. A typical bracket takes 10 to 30 s.
6. **Read the result in this order:**
   - `converged`. If false, say so with `not_converged_because`; there is no safety factor to quote. Refine the
     question (a smaller part of the load case, `mesh.budget_s`), do not round the number up.
   - `safety_factor.low`, the value with the stated error applied, and `safety_factor.against` (yield, or for a
     printed filament the ultimate strength across the layers).
   - `singularities`. Each is a place whose stress was left out because it has no finite value: a sharp inside
     corner, the edge of a rigid support. **Never quote the stress there as the part's stress**, and never use
     `max_von_mises_MPa_anywhere` of a level as a result. For a sharp inside corner the fix is a fillet: propose it
     with `edit_design()`, run the study again, and the corner then has a real number.
   - `hand_estimate`. Where the part reads as a bar fixed at one end, the beam-theory value is beside the result. A
     simulated peak far above it means a stress concentration; far below it, check the loads.
   - `equilibrium`, `material_notes` and `assumptions`: linear elastic, small displacement, bonded parts, a printed
     part solved solid and isotropic.
7. **After any change to the design the study is stale.** `get_strength_study` says which revision the stored result
   describes. Run it again before repeating its numbers.

Other kinds: `modal` (natural frequencies; no supports means a free body), `buckling` (the factor on the loads at
which a slender part buckles; a real part buckles earlier), `thermal` (steady temperatures and heat flow from
`thermal=[...]` conditions) and `thermal_stress` (the stress that temperature field causes).

Making it lighter or stronger: `optimize(..., constraints=["fea.safety_factor >= 2"])` and
`make_lighter(require=["fea.safety_factor >= 2"])` solve the study on real candidates, a bounded number of them. Only
candidates listed under `strength.solved` with `ok` were checked; say how many were.

A requirement instead of a guess ("hold 250 N with a safety factor of 3, as light as possible"): define the study,
then `inverse_design(minimize=["mass_g"], require=["fea.safety_factor >= 3"])`. It searches the design's parameters
and returns a Pareto front in which every variant was built and solved; quote the budget it used and say the front
is approximate. Removing the material that carries no load: `topology_optimise(volfrac=0.5)` finds the layout on the
study's mesh and rebuilds it as lightening pockets (features with `topo_inset`, `topo_fillet`, `topo_web`), then
studies the rebuilt part. Report the rebuilt part's studied safety factor, never the density field's; when the
outcome is "mesh body", say that it is a mesh and not editable CAD. Nothing changes until `apply_topology`.

What a study does not tell you: fatigue, impact, creep, yielding, layer adhesion of a print, a bolted joint opening,
sliding contact. Say so when the question touches one of them. A study is evidence, not a certificate, and not a
test of the made part.
