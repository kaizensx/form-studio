# Benchmarks

Every number here comes from a run you can repeat, with the commit, the machine and the date it ran on. Failures are printed with the rest. This page is written by `form bench publish` from `docs/benchmarks/suites.json` and `docs/benchmarks/cadbench.json`; never edit it by hand.

## Parametric CAD Bench v3

[Parametric CAD Bench v3](https://arxiv.org/abs/2611.02659) (Chen, Xia and Mao, 2026) gives an agent 100 FreeCAD tasks: 30 text to CAD, 30 create then edit, 40 engineering drawing to CAD. A separate verifier scores the saved model's geometry and its consistency with a held-back specification, between 0 and 1. The tasks ([`gnucleus-ai/cad-bench@v3`](https://hub.harborframework.com/datasets/gnucleus-ai/cad-bench/v3), content digest `sha256:8a786725d3648a76282fc5868df06da3d5e00d603f283573a53430803465d78a`), their reference models and the [submission tools](https://github.com/gNucleus-AI/cad-bench-submission) are Apache-2.0; the [scorer](https://github.com/gNucleus-AI/freecad-validator) is Apache-2.0 too. FreeCAD and Open CASCADE are LGPL-2.1.

**Score: pending a run with a real model.** The harness, the scoring and the plumbing are proven below; the score itself needs an agent and model run with their owner's account. To run it:

```
form bench cadbench --download ~/cadbench-v3
form bench cadbench --tasks ~/cadbench-v3 --agent claude-code --model <model id> --effort <effort>
```

That writes the results into `docs/benchmarks/cadbench.json` and this page. A full run is 100 tasks with up to 9000 s each; the spending cap per task is `--budget-usd` (default 10).

### Stand-in agent (deterministic, no model): proves the plumbing, is not a score

6 of 100 tasks (a subset: not comparable with the leaderboard). Mean reward **0**; scored 6, errors 0, perfect 0. Form Studio 1.2.0-dev, commit `b44f4d692c`, arm64, Darwin 27.3.0, 18 cores, FreeCAD on the host: FreeCAD 1.1.4 Revision: 20260928 (Git shallow), 2026-11-28.

| Mode | Tasks | Mean reward |
|---|---|---|
| Create | 2 | 0 |
| Create and edit | 2 | 0 |
| Image to CAD | 2 | 0 |

| Task | Mode | Reward | Geometry | Spec | Files | Form Studio tools | Seconds | Why |
|---|---|---|---|---|---|---|---|---|
| `freecad-0280cda4fc` | create_edit | 0 | 0 | 0 | answer.py, answer_base.FCStd, answer_edit.FCStd | create_design, form_overview | 5.8 | face count differs by 90% (candidate=6, reference=61; threshold 50%) — candidate likely represents a structurally different part; gated geometry to 0.0 |
| `freecad-03561c2ec4` | create | 0 | 0 | 0 | answer.py, answer.FCStd | create_design, form_overview | 6.1 | face count differs by 93% (candidate=6, reference=83; threshold 50%) — candidate likely represents a structurally different part; gated geometry to 0.0 |
| `freecad-066c381c7c` | image_to_cad | 0 | 0 | 0 | answer.py, answer.FCStd | create_design, form_overview | 6 | face count differs by 74% (candidate=6, reference=23; threshold 50%) — candidate likely represents a structurally different part; gated geometry to 0.0 |
| `freecad-06a5c206229` | create | 0 | 0 | 0 | answer.py, answer.FCStd | create_design, form_overview | 5.7 | vertex count differs by 62% (candidate=8, reference=21; threshold 50%) — gated geometry to 0.0 |
| `freecad-06d3f63e25` | create_edit | 0 | 0 | 0 | answer.py, answer_base.FCStd, answer_edit.FCStd | create_design, form_overview | 5.6 | face count differs by 86% (candidate=6, reference=42; threshold 50%) — candidate likely represents a structurally different part; gated geometry to 0.0 |
| `freecad-1338adbf8b` | image_to_cad | 0 | 0 | 0 | answer.py, answer.FCStd | create_design, form_overview | 5.3 | face count differs by 98% (candidate=6, reference=261; threshold 50%) — candidate likely represents a structurally different part; gated geometry to 0.0 |

### Scorer parity

each task's held-back reference scored as the answer, through the harness's scoring (the task's own verifier image and test.sh). Every row must be 1.0. Measured 2026-11-28 on arm64, Darwin 27.3.0, 18 cores, commit `b44f4d692c`.

| Task | Mode | Reward |
|---|---|---|
| `freecad-0280cda4fc` | create_edit | 1 |
| `freecad-03561c2ec4` | create | 1 |
| `freecad-066c381c7c` | image_to_cad | 1 |
| `freecad-06a5c206229` | create | 1 |
| `freecad-06d3f63e25` | create_edit | 1 |
| `freecad-1338adbf8b` | image_to_cad | 1 |

### How Form Studio runs it

- **Agent:** the agent's own CLI through Form Studio's adapter (`form/agents`), with Form Studio's MCP server attached, exactly as a conversation in the app runs it, plus Read, Write and Edit inside the trial folder and Bash limited to FreeCAD's command line. The verifier accepts only a FreeCAD PartDesign feature tree: the agent builds with Form Studio's tools and writes the answer with `freecad_partdesign`, Form Studio's PartDesign export (recomputed and checked in FreeCAD); writing the FreeCAD script itself stays the fallback.
- **Prompt:** each task's `instruction.md` as published, with `/app` replaced by the trial's folder, after a short preamble saying where that folder is, that Form Studio's tools are attached, that `freecad_partdesign` writes the answer files, and where FreeCAD's command line is.
- **Isolation:** each trial has its own Form Studio data folder and settings. The agent sees only the task's environment files (the drawing); `solution/` and `tests/` stay out of its folder.
- **Scoring:** the task's own `tests/test.sh` and `run_scorer.py` in the image its `tests/Dockerfile` builds (FreeCAD 1.1.0, gnucleus-freecad-validator 0.6.0), with no network. Failures and missing files count zero; mode means are over 30, 30 and 40 tasks, as on the leaderboard.
- **Not a leaderboard entry:** the agent runs on the host, not in the task's container, so a result here is not a Harbor job. Submitting needs `harbor run` with an adapter that installs Form Studio in the task container.

## Form Studio's own suites

Each suite compares a value Form Studio computes with a published one. `form bench run --save` runs them; each runs on the source tree that has its code, and says which.

| Suite | Rows | Pass | Fail | Source | Machine | Date | Time |
|---|---|---|---|---|---|---|---|
| [Strength studies against textbook and NAFEMS cases](#strength) | 30 | 30 | 0 | `3fd02397f8 (wave-d-strength)` | arm64, Darwin 27.3.0, 18 cores | 2026-11-28 | 24.93 s |
| [Calculators against published worked examples](#calculators) | 96 | 96 | 0 | `a981a6b7de (wave-x-calculators)` | arm64, Darwin 27.3.0, 18 cores | 2026-11-28 | 9.43 s |
| [ISO 286 limits against the ISO 286-2 tables](#iso286) | 219 | 219 | 0 | `4ceb6a71c0 (wave-f-drawings)` | arm64, Darwin 27.3.0, 18 cores | 2026-11-28 | 0.05 s |
| [Manufacturability rules at their thresholds](#dfm) | 130 | 130 | 0 | `5f7e8c09fe (wave-e-dfm)` | arm64, Darwin 27.3.0, 18 cores | 2026-11-28 | 0.04 s |
| [Mesh to editable CAD: deviation against tolerance](#recon) | 10 | 10 | 0 | `8c7f09ad7d (wave-v-bench)` | arm64, Darwin 27.3.0, 18 cores | 2026-11-28 | 836.6 s |

<a id="strength"></a>
### Strength studies against textbook and NAFEMS cases

Wave D. 30 rows, 30 pass, 0 fail. Commit `3fd02397f8 (wave-d-strength)`, arm64, Darwin 27.3.0, 18 cores, Python 3.12.15, 2026-11-28. Versions: scikit-fem 12.0.2, scipy 1.18.1, numpy 2.5.5, pyamg 5.4.1, netgen-mesher 6.2.2608.

| Group | Quantity | Expected | Computed | Unit | Error | Accepted | Result | Source |
|---|---|---|---|---|---|---|---|---|
| Cantilever beam, end load | tip deflection | 0.191619 | 0.191605 | mm | 0.00713 % | 1 % | pass | Timoshenko beam: F L^3/(3 E I) + F L/(kappa G A) |
| Cantilever beam, end load | tip deflection (Euler-Bernoulli, no shear) | 0.190476 | 0.191605 | mm | 0.593 % | 1.5 % | pass | F L^3/(3 E I) |
| Cantilever beam, end load | bending stress near mid-span, top fibre | 29.9263 | 29.9238 | MPa | 0.00834 % | 2 % | pass | M c / I at that node |
| Cantilever beam, end load | hand estimate: stress at the fixed end | 60 | 60 | MPa | 2.72e-13 % | 0.5 % | pass | M c / I; the estimate measures the section on the mesh |
| Cantilever beam, end load | hand estimate: deflection at the load | 0.190476 | 0.190476 | mm | 1.89e-13 % | 0.5 % | pass | F L^3/(3 E I); the estimate measures the section on the mesh |
| Plate with a hole in tension | peak stress at the hole / applied stress (Kt, gross) | 3.1488 | 3.15559 |  | 0.216 % | 3 % | pass | Howland/Heywood in Peterson, chart 4.1 (d/W = 0.2); Kirsch gives 3 for an infinite plate |
| Thick cylinder under internal pressure | peak von Mises stress (at the bore) | 231.325 | 231.526 | MPa | 0.0872 % | 2 % | pass | Lame, plane strain |
| Thick cylinder under internal pressure | radial displacement of the bore | 0.0181587 | 0.0181584 | mm | 0.00188 % | 1 % | pass | Lame, plane strain |
| Cantilever under its own weight | tip deflection under gravity | 0.0351919 | 0.0352031 | mm | 0.0321 % | 1 % | pass | w L^4/(8 E I) |
| Two bonded solids in series | elongation of two bonded solids | 0.00857143 | 0.00857143 | mm | 7.08e-13 % | 0.5 % | pass | F L1/(E1 A) + F L2/(E2 A) |
| Two bonded solids in series | safety factor (the weaker solid governs) | 24 | 24 |  | 1.52e-11 % | 1 % | pass | yield / (F / A) |
| Block under a bolt preload | shortening under a bolt preload | 0.00297619 | 0.00297619 | mm | 2.89e-11 % | 0.5 % | pass | N L/(E A) |
| Block under a bolt preload | stress under a bolt preload | 12.5 | 12.5 | MPa | 2.45e-08 % | 1 % | pass | N / A |
| NAFEMS LE1: elliptic membrane | stress yy at D (2, 0) | 92.7 | 92.5181 | MPa | 0.196 % | 2 % | pass | NAFEMS, The Standard NAFEMS Benchmarks (1990), test LE1: 92.7 MPa (plane stress) |
| NAFEMS LE10: thick plate under pressure | stress yy at D (2, 0, top) | -5.38 | -5.27145 | MPa | 2.02 % | 3 % | pass | NAFEMS, The Standard NAFEMS Benchmarks (1990), test LE10: -5.38 MPa |
| Natural frequencies of a cantilever | mode 1: first bending, thin direction | 104.439 | 104.881 | Hz | 0.423 % | 2 % | pass | Euler-Bernoulli, beta L = 1.8751 |
| Natural frequencies of a cantilever | mode 2: first bending, stiff direction | 208.878 | 209.044 | Hz | 0.0795 % | 2 % | pass | Euler-Bernoulli, beta L = 1.8751 |
| Natural frequencies of a cantilever | mode 3: second bending, thin direction | 654.514 | 655.571 | Hz | 0.161 % | 2 % | pass | Euler-Bernoulli, beta L = 4.6941 |
| Natural frequencies of a free beam | free-free mode 1: bending, thin direction | 664.564 | 663.276 | Hz | 0.194 % | 2 % | pass | Euler-Bernoulli, beta L = 4.7300 |
| Natural frequencies of a free beam | free-free mode 2: bending, stiff direction | 1329.13 | 1317.49 | Hz | 0.876 % | 2 % | pass | Euler-Bernoulli, beta L = 4.7300 |
| Euler buckling of a column | buckling load factor | 10.7949 | 10.8148 |  | 0.184 % | 2 % | pass | Euler: pi^2 E I/(4 L^2) / P |
| Heat through a wall with convection | heat through the wall | 38.4 | 38.4 | W | 1.11e-13 % | 0.5 % | pass | q = (T1 - Ta) / (L / k + 1 / h), times the area |
| Heat through a wall with convection | temperature of the convective face | 68 | 68 | C | 1.25e-13 % | 0.5 % | pass | Ta + q / h |
| Heat through a pipe wall | heat through the wall (a quarter) | 169.964 | 169.964 | W | 0.000421 % | 0.5 % | pass | 2 pi k L (Ti - To) / ln(ro / ri) |
| Heat through a pipe wall | temperature at mid-wall (span minus the worst node error) | 150 | 149.989 | K | 0.00725 % | 0.5 % | pass | T(r) = Ti - (Ti - To) ln(r / ri) / ln(ro / ri) |
| Thermal stress in a bar that cannot expand | stress in a bar that cannot expand | 201.6 | 201.6 | MPa | 2.26e-12 % | 0.5 % | pass | E alpha dT |
| Thermal stress in a bar that cannot expand | sideways growth of the free faces | 0.01248 | 0.01248 | mm | 3.35e-12 % | 0.5 % | pass | (1 + nu) alpha dT a |
| Thermal stress in a thick cylinder | hoop stress at the bore (hot side, compression) | -330.472 | -329.972 | MPa | 0.152 % | 2 % | pass | Timoshenko and Goodier, Theory of Elasticity, art. 151: long cylinder, steady radial heat flow |
| Thermal stress in a thick cylinder | hoop stress at the outside (cold side, tension) | 209.528 | 209.169 | MPa | 0.171 % | 2 % | pass | the same solution at r = ro |
| Sharp inside corner (singularity) | the sharp inside corner is named and its stress left out | yes | yes |  | 0 % | 0 % | pass | Williams (1952): the stress at a re-entrant corner is unbounded |

<a id="calculators"></a>
### Calculators against published worked examples

Wave X. 96 rows, 96 pass, 0 fail. Commit `a981a6b7de (wave-x-calculators)`, arm64, Darwin 27.3.0, 18 cores, Python 3.12.15, 2026-11-28.

| Group | Quantity | Expected | Computed | Unit | Error | Accepted | Result | Source |
|---|---|---|---|---|---|---|---|---|
| snapfit: Calculation example I: PC hook, l 19, b 9.5, y 2.4 mm, half of 4 % strain, thickness tapering to one-half | thickness h | 3.28 | 3.27908 | mm | 0.028 % | 0.2 % | pass | Bayer, Snap-Fit Joints for Plastics |
| snapfit: Calculation example I: PC hook, l 19, b 9.5, y 2.4 mm, half of 4 % strain, thickness tapering to one-half | deflection force P | 32.5 | 32.526 | N | 0.0799 % | 0.2 % | pass | Bayer, Snap-Fit Joints for Plastics; E_s = 1815 MPa from the guide's Fig. 16 |
| snapfit: Calculation example I: PC hook, l 19, b 9.5, y 2.4 mm, half of 4 % strain, thickness tapering to one-half | mating force W | 58.5 | 58.591 | N | 0.156 % | 0.3 % | pass | Bayer, Snap-Fit Joints for Plastics; the guide reads the friction term as 1.8 off its chart; it is 1.801 |
| snapfit: Annular example: PC lamp cover, d 200, t 2.5, undercut 2 × 1 mm, both parts equally stiff | hoop strain | 0.005 | 0.005 |  | 0 % | 0.0001 % | pass | Bayer, Snap-Fit Joints for Plastics |
| snapfit: Annular example: PC lamp cover, d 200, t 2.5, undercut 2 × 1 mm, both parts equally stiff | geometric factor X_N | 0.0017 | 0.00168613 |  | 0.816 % | 1 % | pass | Bayer, Snap-Fit Joints for Plastics; read off the guide's Fig. 27; its formula gives 0.001686 |
| snapfit: Annular example: PC lamp cover, d 200, t 2.5, undercut 2 × 1 mm, both parts equally stiff | transverse force P | 748 | 741.898 | N | 0.816 % | 1 % | pass | Bayer, Snap-Fit Joints for Plastics; the guide multiplies by the rounded 0.0017 |
| snapfit: Annular example: PC lamp cover, d 200, t 2.5, undercut 2 × 1 mm, both parts equally stiff | mating force W | 1346 | 1336.42 | N | 0.711 % | 1 % | pass | Bayer, Snap-Fit Joints for Plastics; same rounding |
| spring: Example 10-1: music wire d 0.037 in, OD 7/16 in, 12.5 total turns, squared ends | tensile strength S_ut | 324 | 323.578 | kpsi | 0.13 % | 0.3 % | pass | Shigley's Mechanical Engineering Design, 10th ed.; Table 10-4, A / d^m |
| spring: Example 10-1: music wire d 0.037 in, OD 7/16 in, 12.5 total turns, squared ends | correction factor K_B | 1.124 | 1.12408 |  | 0.00694 % | 0.1 % | pass | Shigley's Mechanical Engineering Design, 10th ed. |
| spring: Example 10-1: music wire d 0.037 in, OD 7/16 in, 12.5 total turns, squared ends | rate k | 4.13 | 4.11565 | lbf/in | 0.347 % | 0.5 % | pass | Shigley's Mechanical Engineering Design, 10th ed.; the book rounds intermediates; exact arithmetic gives 4.116 |
| spring: Example 10-1: music wire d 0.037 in, OD 7/16 in, 12.5 total turns, squared ends | solid length L_s | 0.5 | 0.4995 | in | 0.1 % | 0.2 % | pass | Shigley's Mechanical Engineering Design, 10th ed. |
| spring: Example 10-1: music wire d 0.037 in, OD 7/16 in, 12.5 total turns, squared ends | load at torsional yield | 6.46 | 6.43366 | lbf | 0.408 % | 0.5 % | pass | Shigley's Mechanical Engineering Design, 10th ed.; from the sheet's k and R_m |
| spring: Example 10-1: music wire d 0.037 in, OD 7/16 in, 12.5 total turns, squared ends | deflection at that load | 1.56 | 1.56322 | in | 0.206 % | 0.5 % | pass | Shigley's Mechanical Engineering Design, 10th ed. |
| spring: Example 10-1: music wire d 0.037 in, OD 7/16 in, 12.5 total turns, squared ends | longest free length that cannot buckle | 2.11 | 2.10663 | in | 0.16 % | 0.3 % | pass | Shigley's Mechanical Engineering Design, 10th ed.; EN 13906-1's buckling relation changes from no root to a root at 2.63 D / α |
| spring: d 2, D 20, n 8, steel | natural frequency, the standard's 3560 d/(n D²) √(G/ρ) | 226.712 | 226.636 | Hz | 0.0334 % | 0.1 % | pass | EN 13906-1; the SI form used here against the standard's unit form (3560 is 10³·√500/2π = 3558.8, rounded) |
| fastener: M6 class 8.8, μ = 0.1 | permissible preload F_M | 10.4 | 10.4473 | kN | 0.455 % | 0.6 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |
| fastener: M6 class 8.8, μ = 0.1 | tightening torque M_A | 9 | 8.95675 | N·m | 0.481 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener: M6 class 8.8, μ = 0.12 | permissible preload F_M | 10.2 | 10.1819 | kN | 0.177 % | 0.6 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |
| fastener: M6 class 8.8, μ = 0.12 | tightening torque M_A | 10.1 | 10.1493 | N·m | 0.488 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener: M6 class 8.8, μ = 0.14 | permissible preload F_M | 9.9 | 9.90656 | kN | 0.0663 % | 0.6 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |
| fastener: M6 class 8.8, μ = 0.14 | tightening torque M_A | 11.3 | 11.2564 | N·m | 0.386 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener: M8 class 8.8, μ = 0.1 | permissible preload F_M | 19.1 | 19.1032 | kN | 0.0169 % | 0.6 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |
| fastener: M8 class 8.8, μ = 0.1 | tightening torque M_A | 21.6 | 21.6375 | N·m | 0.173 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener: M8 class 8.8, μ = 0.12 | permissible preload F_M | 18.8 | 18.6273 | kN | 0.919 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); the table prints 18.8 between 19.1 and 18.1; the guideline's formula gives 18.6 |
| fastener: M8 class 8.8, μ = 0.12 | tightening torque M_A | 24.6 | 24.573 | N·m | 0.11 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener: M8 class 8.8, μ = 0.14 | permissible preload F_M | 18.1 | 18.1315 | kN | 0.174 % | 0.6 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |
| fastener: M8 class 8.8, μ = 0.14 | tightening torque M_A | 27.3 | 27.3011 | N·m | 0.00393 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener: M10 class 8.8, μ = 0.1 | permissible preload F_M | 30.3 | 30.3504 | kN | 0.166 % | 0.6 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |
| fastener: M10 class 8.8, μ = 0.1 | tightening torque M_A | 43 | 42.6193 | N·m | 0.885 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener: M10 class 8.8, μ = 0.12 | permissible preload F_M | 29.6 | 29.6032 | kN | 0.0108 % | 0.6 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |
| fastener: M10 class 8.8, μ = 0.12 | tightening torque M_A | 48 | 48.4631 | N·m | 0.965 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener: M10 class 8.8, μ = 0.14 | permissible preload F_M | 28.8 | 28.8229 | kN | 0.0795 % | 0.6 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |
| fastener: M10 class 8.8, μ = 0.14 | tightening torque M_A | 54 | 53.8971 | N·m | 0.191 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener: M12 class 8.8, μ = 0.1 | permissible preload F_M | 44.1 | 44.1888 | kN | 0.201 % | 0.6 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |
| fastener: M12 class 8.8, μ = 0.1 | tightening torque M_A | 73 | 73.5003 | N·m | 0.685 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener: M12 class 8.8, μ = 0.12 | permissible preload F_M | 43 | 43.1095 | kN | 0.255 % | 0.6 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |
| fastener: M12 class 8.8, μ = 0.12 | tightening torque M_A | 84 | 83.632 | N·m | 0.438 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| fastener: M12 class 8.8, μ = 0.14 | permissible preload F_M | 41.9 | 41.9807 | kN | 0.193 % | 0.6 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8) |
| fastener: M12 class 8.8, μ = 0.14 | tightening torque M_A | 93 | 93.0566 | N·m | 0.0609 % | 1.2 % | pass | Pfeiffer Vacuum, Table 3.10 (values to VDI 2230, 90 % of R_p0.2, class 8.8); hexagon head ISO 4017, hole ISO 273 medium; the table rounds to whole N·m from M10 |
| gear: Profile-shifted spur pair example: m 3, z 12/24, x 0.6/0.36 | working pressure angle | 26.0886 | 26.0886 | deg | 0.000153 % | 0.001 % | pass | KHK Gear Technical Reference |
| gear: Profile-shifted spur pair example: m 3, z 12/24, x 0.6/0.36 | centre distance | 56.4999 | 56.4999 | mm | 5.31e-05 % | 0.001 % | pass | KHK Gear Technical Reference |
| gear: Profile-shifted spur pair example: m 3, z 12/24, x 0.6/0.36 | centre distance modification y | 0.8333 | 0.83329 |  | 0.00121 % | 0.01 % | pass | KHK Gear Technical Reference |
| gear: Profile-shifted spur pair example: m 3, z 12/24, x 0.6/0.36 | pinion tip diameter | 44.84 | 44.8397 | mm | 0.00058 % | 0.01 % | pass | KHK Gear Technical Reference |
| gear: Profile-shifted spur pair example: m 3, z 12/24, x 0.6/0.36 | gear tip diameter | 79.4 | 79.3997 | mm | 0.000327 % | 0.01 % | pass | KHK Gear Technical Reference |
| gear: Profile-shifted spur pair example: m 3, z 12/24, x 0.6/0.36 | pinion root diameter | 32.1 | 32.1 | mm | 0 % | 0.01 % | pass | KHK Gear Technical Reference |
| gear: Profile-shifted spur pair example: m 3, z 12/24, x 0.6/0.36 | gear root diameter | 66.66 | 66.66 | mm | 0 % | 0.01 % | pass | KHK Gear Technical Reference |
| gear: Profile-shifted spur pair example: m 3, z 12/24, x 0.6/0.36 | tooth depth | 6.37 | 6.36987 | mm | 0.00204 % | 0.01 % | pass | KHK Gear Technical Reference |
| gear: Helical pair example, normal system: m_n 3, β 30°, z 12/60, x_n1 0.09809 | transverse pressure angle | 22.7959 | 22.7959 | deg | 0 % | 0.0001 % | pass | KHK Gear Technical Reference |
| gear: Helical pair example, normal system: m_n 3, β 30°, z 12/60, x_n1 0.09809 | working pressure angle | 23.1126 | 23.1126 | deg | 0.00013 % | 0.001 % | pass | KHK Gear Technical Reference |
| gear: Helical pair example, normal system: m_n 3, β 30°, z 12/60, x_n1 0.09809 | centre distance | 125 | 125 | mm | 0 % | 0.001 % | pass | KHK Gear Technical Reference |
| gear: Helical pair example, normal system: m_n 3, β 30°, z 12/60, x_n1 0.09809 | pinion reference diameter | 41.569 | 41.5692 | mm | 0.000529 % | 0.001 % | pass | KHK Gear Technical Reference |
| gear: Helical pair example, normal system: m_n 3, β 30°, z 12/60, x_n1 0.09809 | gear reference diameter | 207.846 | 207.846 | mm | 4.81e-05 % | 0.001 % | pass | KHK Gear Technical Reference |
| gear: Helical pair example, normal system: m_n 3, β 30°, z 12/60, x_n1 0.09809 | pinion base diameter | 38.322 | 38.3223 | mm | 0.000757 % | 0.001 % | pass | KHK Gear Technical Reference |
| gear: Helical pair example, normal system: m_n 3, β 30°, z 12/60, x_n1 0.09809 | gear base diameter | 191.611 | 191.612 | mm | 0.000261 % | 0.001 % | pass | KHK Gear Technical Reference |
| gear: Helical pair example, normal system: m_n 3, β 30°, z 12/60, x_n1 0.09809 | pinion tip diameter | 48.153 | 48.1539 | mm | 0.00189 % | 0.01 % | pass | KHK Gear Technical Reference |
| gear: Helical pair example, normal system: m_n 3, β 30°, z 12/60, x_n1 0.09809 | gear tip diameter | 213.842 | 213.842 | mm | 9.35e-05 % | 0.01 % | pass | KHK Gear Technical Reference |
| gear: Example 13-1: P 2 teeth/in, 16/40 teeth, 20°, mounted 1/4 in too far apart | pinion base radius | 3.76 | 3.75877 | in | 0.0327 % | 0.2 % | pass | Shigley's Mechanical Engineering Design, 10th ed. |
| gear: Example 13-1: P 2 teeth/in, 16/40 teeth, 20°, mounted 1/4 in too far apart | gear base radius | 9.4 | 9.39693 | in | 0.0327 % | 0.2 % | pass | Shigley's Mechanical Engineering Design, 10th ed. |
| gear: Example 13-1: P 2 teeth/in, 16/40 teeth, 20°, mounted 1/4 in too far apart | pressure angle as mounted | 22.59 | 22.6005 | deg | 0.0465 % | 0.1 % | pass | Shigley's Mechanical Engineering Design, 10th ed.; the book rounds the base radius first; exact arithmetic gives 22.60 |
| gear: Example 14-1: P 8, 16 teeth, face 1.5 in, 1200 rev/min, W_t 365 lbf | velocity factor K_v | 1.52 | 1.52326 |  | 0.214 % | 0.3 % | pass | Shigley's Mechanical Engineering Design, 10th ed. |
| gear: Example 14-1: P 8, 16 teeth, face 1.5 in, 1200 rev/min, W_t 365 lbf | Lewis form factor Y | 0.296 | 0.296 |  | 0 % | 1e-07 % | pass | Shigley's Mechanical Engineering Design, 10th ed. |
| gear: Example 14-1: P 8, 16 teeth, face 1.5 in, 1200 rev/min, W_t 365 lbf | bending stress | 10 | 10.0178 | kpsi | 0.178 % | 0.3 % | pass | Shigley's Mechanical Engineering Design, 10th ed.; the book's allowable stress, which its W_t = 365 lbf was sized to |
| gear: involute function | inverse of inv α at α = 26.0886° | 26.0886 | 26.0886 | deg | 1.36e-14 % | 1e-07 % | pass | ISO 21771 |
| cam: cycloidal rise | peak velocity factor C_v (v = C_v h/β) | 2 | 2 |  | 3.58e-05 % | 0.1 % | pass | Norton, Design of Machinery, ch. 8 |
| cam: cycloidal rise | peak acceleration factor C_a (a = C_a h/β²) | 6.283 | 6.28319 |  | 0.00295 % | 0.1 % | pass | Norton, Design of Machinery, ch. 8 |
| cam: harmonic rise | peak velocity factor C_v (v = C_v h/β) | 1.571 | 1.5708 |  | 0.013 % | 0.1 % | pass | Norton, Design of Machinery, ch. 8 |
| cam: harmonic rise | peak acceleration factor C_a (a = C_a h/β²) | 4.935 | 4.9348 |  | 0.00401 % | 0.1 % | pass | Norton, Design of Machinery, ch. 8 |
| cam: poly345 rise | peak velocity factor C_v (v = C_v h/β) | 1.875 | 1.875 |  | 6.13e-06 % | 0.1 % | pass | Norton, Design of Machinery, ch. 8 |
| cam: poly345 rise | peak acceleration factor C_a (a = C_a h/β²) | 5.777 | 5.7735 |  | 0.0606 % | 0.1 % | pass | Norton, Design of Machinery, ch. 8; the handbook prints 5.777 for the 3-4-5 polynomial; the exact maximum is 5.7735 |
| fit: H7/g6 at Ø25: hole 0/+21 µm, shaft −7/−20 µm | smallest clearance at 20 °C | 0.007 | 0.007 | mm | 0 % | 1e-07 % | pass | ISO 286-2 tables |
| fit: H7/g6 at Ø25: hole 0/+21 µm, shaft −7/−20 µm | largest clearance at 20 °C | 0.041 | 0.041 | mm | 0 % | 1e-07 % | pass | ISO 286-2 tables |
| fit: H7/g6 at Ø25: hole 0/+21 µm, shaft −7/−20 µm; aluminium on steel, +100 K | growth of the clearance, d (α_h − α_s) ΔT = 25 × 11.9e-6 × 100 | 0.02975 | 0.0298 | mm | 0.168 % | 0.2 % | pass | hand calculation; the limits scale too, hence the 0.1 % difference |
| solid: snap hook | root thickness plus undercut (extent in X) | 3.83177 | 3.83177 | mm | 4.42e-08 | 0.0001 | pass | the calculator's own sheet |
| solid: snap hook | width (extent in Y) | 6 | 6 | mm | 0 | 0.0001 | pass | the calculator's own sheet |
| solid: snap hook | valid solid | 1 | 1 |  | 0 | 0 | pass | the calculator's own sheet |
| solid: compression spring | free length (between the ground faces) | 24.7264 | 24.7264 | mm | 3.68e-07 | 0.02 | pass | the calculator's own sheet |
| solid: compression spring | outside diameter D + d | 15.6 | 15.6001 | mm | 5.93e-05 | 0.02 | pass | the calculator's own sheet |
| solid: compression spring | wire volume against π d²/4 · π D n_t (less what is ground off) | 1 | 0.975915 | ratio | 0.0241 | 0.08 | pass | the calculator's own sheet |
| solid: compression spring | valid solid | 1 | 1 |  | 0 | 0 | pass | the calculator's own sheet |
| solid: spur gear, x = 0.3 | tip diameter d_a1 (bounding box) | 33.1461 | 33.1461 | mm | 4.2e-06 | 0.002 | pass | the calculator's own sheet |
| solid: spur gear, x = 0.3 | tooth thickness against the exact involute at four radii, largest difference | 0 | 0.000677423 | mm | 0.000677 | 0.002 | pass | the calculator's own sheet |
| solid: spur gear, unshifted | tip diameter d_a1 (bounding box) | 52 | 52 | mm | 2e-07 | 0.002 | pass | the calculator's own sheet |
| solid: spur gear, unshifted | tooth thickness against the exact involute at four radii, largest difference | 0 | 0.00127748 | mm | 0.00128 | 0.002 | pass | the calculator's own sheet |
| solid: helical gear, β = 20° | tip diameter d_a1 (bounding box) | 35.9253 | 35.9253 | mm | 3.37e-06 | 0.002 | pass | the calculator's own sheet |
| solid: helical gear, β = 20° | tooth thickness against the exact involute at four radii, largest difference | 0 | 0.0014946 | mm | 0.00149 | 0.002 | pass | the calculator's own sheet |
| solid: spur pair, x = 0.3 | centre distance at which the library meshes the two gears | 44.573 | 44.573 | mm | 2.17e-06 | 0.002 | pass | the calculator's own sheet |
| solid: spur pair, x = 0.3, backlash 0.1 | volume the meshed pinion and gear share | 0 | 0 | mm³ | 0 | 0.001 | pass | the calculator's own sheet |
| solid: helical pair, β = 20°, backlash 0.1 | volume the meshed pinion and gear share | 0 | 0 | mm³ | 0 | 0.001 | pass | the calculator's own sheet |
| solid: internal pair, backlash 0.1 | volume the pinion and the internal gear share | 0 | 0 | mm³ | 0 | 0.001 | pass | the calculator's own sheet |
| solid: rack | length = teeth × π m | 62.8319 | 62.8319 | mm | 0 | 0.0001 | pass | the calculator's own sheet |
| solid: rack and pinion, backlash 0.1 | volume the pinion and the rack share | 0 | 0 | mm³ | 0 | 0.001 | pass | the calculator's own sheet |
| solid: cam | largest radius = base circle + lift (extent toward the dwell) | 28 | 28 | mm | 1e-07 | 0.02 | pass | the calculator's own sheet |
| solid: cam | valid solid | 1 | 1 |  | 0 | 0 | pass | the calculator's own sheet |
| solid: fit pair | pin diameter = middle of g6 at Ø25 | 24.9865 | 24.9865 | mm | 0 | 0.0001 | pass | the calculator's own sheet |
| solid: insert boss | boss diameter = hole + 2 × least wall (CNC Kitchen M3: 4.0 + 2 × 1.6) | 7.2 | 7.2 | mm | 0 | 0.0001 | pass | the calculator's own sheet |
| solid: insert boss | pocket depth below the boss top = insert length + 1 | 6.7 | 6.7 | mm | 0 | 0.001 | pass | the calculator's own sheet |

<a id="iso286"></a>
### ISO 286 limits against the ISO 286-2 tables

Wave F. 219 rows, 219 pass, 0 fail. Commit `4ceb6a71c0 (wave-f-drawings)`, arm64, Darwin 27.3.0, 18 cores, Python 3.12.15, 2026-11-28.

| Group | Quantity | Expected | Computed | Unit | Error | Accepted | Result | Source |
|---|---|---|---|---|---|---|---|---|
| IT5 | over 0 to 3 mm | 4 | 4 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT5 | over 3 to 6 mm | 5 | 5 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT5 | over 6 to 10 mm | 6 | 6 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT5 | over 10 to 18 mm | 8 | 8 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT5 | over 18 to 30 mm | 9 | 9 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT5 | over 30 to 50 mm | 11 | 11 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT5 | over 50 to 80 mm | 13 | 13 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT5 | over 80 to 120 mm | 15 | 15 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT5 | over 120 to 180 mm | 18 | 18 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT5 | over 180 to 250 mm | 20 | 20 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT5 | over 250 to 315 mm | 23 | 23 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT5 | over 315 to 400 mm | 25 | 25 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT5 | over 400 to 500 mm | 27 | 27 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT6 | over 0 to 3 mm | 6 | 6 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT6 | over 3 to 6 mm | 8 | 8 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT6 | over 6 to 10 mm | 9 | 9 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT6 | over 10 to 18 mm | 11 | 11 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT6 | over 18 to 30 mm | 13 | 13 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT6 | over 30 to 50 mm | 16 | 16 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT6 | over 50 to 80 mm | 19 | 19 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT6 | over 80 to 120 mm | 22 | 22 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT6 | over 120 to 180 mm | 25 | 25 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT6 | over 180 to 250 mm | 29 | 29 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT6 | over 250 to 315 mm | 32 | 32 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT6 | over 315 to 400 mm | 36 | 36 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT6 | over 400 to 500 mm | 40 | 40 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT7 | over 0 to 3 mm | 10 | 10 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT7 | over 3 to 6 mm | 12 | 12 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT7 | over 6 to 10 mm | 15 | 15 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT7 | over 10 to 18 mm | 18 | 18 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT7 | over 18 to 30 mm | 21 | 21 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT7 | over 30 to 50 mm | 25 | 25 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT7 | over 50 to 80 mm | 30 | 30 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT7 | over 80 to 120 mm | 35 | 35 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT7 | over 120 to 180 mm | 40 | 40 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT7 | over 180 to 250 mm | 46 | 46 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT7 | over 250 to 315 mm | 52 | 52 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT7 | over 315 to 400 mm | 57 | 57 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT7 | over 400 to 500 mm | 63 | 63 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT8 | over 0 to 3 mm | 14 | 14 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT8 | over 3 to 6 mm | 18 | 18 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT8 | over 6 to 10 mm | 22 | 22 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT8 | over 10 to 18 mm | 27 | 27 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT8 | over 18 to 30 mm | 33 | 33 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT8 | over 30 to 50 mm | 39 | 39 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT8 | over 50 to 80 mm | 46 | 46 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT8 | over 80 to 120 mm | 54 | 54 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT8 | over 120 to 180 mm | 63 | 63 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT8 | over 180 to 250 mm | 72 | 72 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT8 | over 250 to 315 mm | 81 | 81 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT8 | over 315 to 400 mm | 89 | 89 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT8 | over 400 to 500 mm | 97 | 97 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT9 | over 0 to 3 mm | 25 | 25 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT9 | over 3 to 6 mm | 30 | 30 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT9 | over 6 to 10 mm | 36 | 36 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT9 | over 10 to 18 mm | 43 | 43 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT9 | over 18 to 30 mm | 52 | 52 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT9 | over 30 to 50 mm | 62 | 62 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT9 | over 50 to 80 mm | 74 | 74 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT9 | over 80 to 120 mm | 87 | 87 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT9 | over 120 to 180 mm | 100 | 100 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT9 | over 180 to 250 mm | 115 | 115 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT9 | over 250 to 315 mm | 130 | 130 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT9 | over 315 to 400 mm | 140 | 140 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT9 | over 400 to 500 mm | 155 | 155 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT10 | over 0 to 3 mm | 40 | 40 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT10 | over 3 to 6 mm | 48 | 48 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT10 | over 6 to 10 mm | 58 | 58 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT10 | over 10 to 18 mm | 70 | 70 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT10 | over 18 to 30 mm | 84 | 84 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT10 | over 30 to 50 mm | 100 | 100 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT10 | over 50 to 80 mm | 120 | 120 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT10 | over 80 to 120 mm | 140 | 140 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT10 | over 120 to 180 mm | 160 | 160 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT10 | over 180 to 250 mm | 185 | 185 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT10 | over 250 to 315 mm | 210 | 210 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT10 | over 315 to 400 mm | 230 | 230 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT10 | over 400 to 500 mm | 250 | 250 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT11 | over 0 to 3 mm | 60 | 60 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT11 | over 3 to 6 mm | 75 | 75 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT11 | over 6 to 10 mm | 90 | 90 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT11 | over 10 to 18 mm | 110 | 110 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT11 | over 18 to 30 mm | 130 | 130 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT11 | over 30 to 50 mm | 160 | 160 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT11 | over 50 to 80 mm | 190 | 190 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT11 | over 80 to 120 mm | 220 | 220 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT11 | over 120 to 180 mm | 250 | 250 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT11 | over 180 to 250 mm | 290 | 290 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT11 | over 250 to 315 mm | 320 | 320 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by formula |
| IT11 | over 315 to 400 mm | 360 | 360 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| IT11 | over 400 to 500 mm | 400 | 400 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py; computed by table |
| shaft e: upper deviation es | over 0 to 3 mm | -14 | -14 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft e: upper deviation es | over 3 to 6 mm | -20 | -20 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft e: upper deviation es | over 6 to 10 mm | -25 | -25 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft e: upper deviation es | over 10 to 18 mm | -32 | -32 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft e: upper deviation es | over 18 to 30 mm | -40 | -40 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft e: upper deviation es | over 30 to 50 mm | -50 | -50 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft e: upper deviation es | over 50 to 80 mm | -60 | -60 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft e: upper deviation es | over 80 to 120 mm | -72 | -72 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft e: upper deviation es | over 120 to 180 mm | -85 | -85 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft e: upper deviation es | over 180 to 250 mm | -100 | -100 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft e: upper deviation es | over 250 to 315 mm | -110 | -110 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft e: upper deviation es | over 315 to 400 mm | -125 | -125 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft e: upper deviation es | over 400 to 500 mm | -135 | -135 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 0 to 3 mm | -6 | -6 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 3 to 6 mm | -10 | -10 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 6 to 10 mm | -13 | -13 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 10 to 18 mm | -16 | -16 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 18 to 30 mm | -20 | -20 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 30 to 50 mm | -25 | -25 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 50 to 80 mm | -30 | -30 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 80 to 120 mm | -36 | -36 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 120 to 180 mm | -43 | -43 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 180 to 250 mm | -50 | -50 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 250 to 315 mm | -56 | -56 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 315 to 400 mm | -62 | -62 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft f: upper deviation es | over 400 to 500 mm | -68 | -68 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 0 to 3 mm | -2 | -2 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 3 to 6 mm | -4 | -4 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 6 to 10 mm | -5 | -5 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 10 to 18 mm | -6 | -6 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 18 to 30 mm | -7 | -7 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 30 to 50 mm | -9 | -9 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 50 to 80 mm | -10 | -10 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 80 to 120 mm | -12 | -12 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 120 to 180 mm | -14 | -14 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 180 to 250 mm | -15 | -15 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 250 to 315 mm | -17 | -17 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 315 to 400 mm | -18 | -18 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft g: upper deviation es | over 400 to 500 mm | -20 | -20 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 0 to 3 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 3 to 6 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 6 to 10 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 10 to 18 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 18 to 30 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 30 to 50 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 50 to 80 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 80 to 120 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 120 to 180 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 180 to 250 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 250 to 315 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 315 to 400 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft h: upper deviation es | over 400 to 500 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 0 to 3 mm | 0 | 0 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 3 to 6 mm | 1 | 1 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 6 to 10 mm | 1 | 1 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 10 to 18 mm | 1 | 1 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 18 to 30 mm | 2 | 2 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 30 to 50 mm | 2 | 2 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 50 to 80 mm | 2 | 2 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 80 to 120 mm | 3 | 3 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 120 to 180 mm | 3 | 3 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 180 to 250 mm | 4 | 4 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 250 to 315 mm | 4 | 4 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 315 to 400 mm | 4 | 4 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft k6: lower deviation ei | over 400 to 500 mm | 5 | 5 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 0 to 3 mm | 2 | 2 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 3 to 6 mm | 4 | 4 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 6 to 10 mm | 6 | 6 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 10 to 18 mm | 7 | 7 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 18 to 30 mm | 8 | 8 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 30 to 50 mm | 9 | 9 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 50 to 80 mm | 11 | 11 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 80 to 120 mm | 13 | 13 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 120 to 180 mm | 15 | 15 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 180 to 250 mm | 17 | 17 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 250 to 315 mm | 20 | 20 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 315 to 400 mm | 21 | 21 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft m6: lower deviation ei | over 400 to 500 mm | 23 | 23 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 0 to 3 mm | 4 | 4 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 3 to 6 mm | 8 | 8 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 6 to 10 mm | 10 | 10 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 10 to 18 mm | 12 | 12 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 18 to 30 mm | 15 | 15 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 30 to 50 mm | 17 | 17 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 50 to 80 mm | 20 | 20 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 80 to 120 mm | 23 | 23 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 120 to 180 mm | 27 | 27 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 180 to 250 mm | 31 | 31 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 250 to 315 mm | 34 | 34 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 315 to 400 mm | 37 | 37 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft n6: lower deviation ei | over 400 to 500 mm | 40 | 40 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 0 to 3 mm | 6 | 6 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 3 to 6 mm | 12 | 12 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 6 to 10 mm | 15 | 15 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 10 to 18 mm | 18 | 18 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 18 to 30 mm | 22 | 22 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 30 to 50 mm | 26 | 26 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 50 to 80 mm | 32 | 32 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 80 to 120 mm | 37 | 37 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 120 to 180 mm | 43 | 43 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 180 to 250 mm | 50 | 50 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 250 to 315 mm | 56 | 56 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 315 to 400 mm | 62 | 62 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft p6: lower deviation ei | over 400 to 500 mm | 68 | 68 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft s6: lower deviation ei | over 0 to 3 mm | 14 | 14 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft s6: lower deviation ei | over 3 to 6 mm | 19 | 19 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft s6: lower deviation ei | over 6 to 10 mm | 23 | 23 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft s6: lower deviation ei | over 10 to 18 mm | 28 | 28 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft s6: lower deviation ei | over 18 to 30 mm | 35 | 35 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| shaft s6: lower deviation ei | over 30 to 50 mm | 43 | 43 | µm |  | 0 | pass | ISO 286-2:2010 table value, as transcribed in form/craft/fits.py |
| fit H7/g6 | Ø8 kind and clearance | clearance (0.005, 0.029) | clearance (0.005, 0.029) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H7/g6 | Ø25 kind and clearance | clearance (0.007, 0.041) | clearance (0.007, 0.041) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H7/g6 | Ø100 kind and clearance | clearance (0.012, 0.069) | clearance (0.012, 0.069) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H7/h6 | Ø8 kind and clearance | clearance (0.0, 0.024) | clearance (0.0, 0.024) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H7/h6 | Ø25 kind and clearance | clearance (0.0, 0.034) | clearance (0.0, 0.034) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H7/h6 | Ø100 kind and clearance | clearance (0.0, 0.057) | clearance (0.0, 0.057) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H7/k6 | Ø8 kind and clearance | transition (-0.01, 0.014) | transition (-0.01, 0.014) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H7/k6 | Ø25 kind and clearance | transition (-0.015, 0.019) | transition (-0.015, 0.019) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H7/k6 | Ø100 kind and clearance | transition (-0.025, 0.032) | transition (-0.025, 0.032) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H7/p6 | Ø8 kind and clearance | interference (-0.024, 0.0) | interference (-0.024, 0.0) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H7/p6 | Ø25 kind and clearance | interference (-0.035, -0.001) | interference (-0.035, -0.001) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H7/p6 | Ø100 kind and clearance | interference (-0.059, -0.002) | interference (-0.059, -0.002) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H8/f7 | Ø8 kind and clearance | clearance (0.013, 0.05) | clearance (0.013, 0.05) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H8/f7 | Ø25 kind and clearance | clearance (0.02, 0.074) | clearance (0.02, 0.074) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H8/f7 | Ø100 kind and clearance | clearance (0.036, 0.125) | clearance (0.036, 0.125) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H9/e9 | Ø8 kind and clearance | clearance (0.025, 0.097) | clearance (0.025, 0.097) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H9/e9 | Ø25 kind and clearance | clearance (0.04, 0.144) | clearance (0.04, 0.144) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |
| fit H9/e9 | Ø100 kind and clearance | clearance (0.072, 0.246) | clearance (0.072, 0.246) | mm |  | 0 | pass | form/craft/fits.py (the tabulated values) |

<a id="dfm"></a>
### Manufacturability rules at their thresholds

Wave E. 130 rows, 130 pass, 0 fail. Commit `5f7e8c09fe (wave-e-dfm)`, arm64, Darwin 27.3.0, 18 cores, Python 3.12.15, 2026-11-28.

| Group | Quantity | Expected | Computed | Unit | Error | Accepted | Result | Source |
|---|---|---|---|---|---|---|---|---|
| cnc cnc.access | <= at the fail limit (0 mm²) | pass | pass |  |  |  | pass | computed (B-rep) |
| cnc cnc.access | <= just past the fail limit (1e-06 mm²) | fail | fail |  |  |  | pass | computed (B-rep) |
| cnc cnc.corner_tool | >= at the fail limit (3 mm) | pass | pass |  |  |  | pass | computed (B-rep) |
| cnc cnc.corner_tool | >= just past the fail limit (3 mm) | fail | fail |  |  |  | pass | computed (B-rep) |
| cnc cnc.corner_depth | >= at the warn limit (0.3333 × depth) | pass | pass |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.corner_depth | >= just past the warn limit (0.333299 × depth) | warn | warn |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.reach | <= at the fail limit (30 × tool diameter) | warn | warn |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.reach | <= just past the fail limit (30 × tool diameter) | fail | fail |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.reach | <= at the warn limit (4 × tool diameter) | pass | pass |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.reach | <= just past the warn limit (4 × tool diameter) | warn | warn |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.wall (material = metal) | >= at the fail limit (0.5 mm) | warn | warn |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.wall (material = metal) | >= just past the fail limit (0.499999 mm) | fail | fail |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.wall (material = metal) | >= at the warn limit (0.8 mm) | pass | pass |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.wall (material = metal) | >= just past the warn limit (0.799999 mm) | warn | warn |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.wall (material = plastic) | >= at the fail limit (1 mm) | warn | warn |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.wall (material = plastic) | >= just past the fail limit (0.999999 mm) | fail | fail |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.wall (material = plastic) | >= at the warn limit (1.5 mm) | pass | pass |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.wall (material = plastic) | >= just past the warn limit (1.5 mm) | warn | warn |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.hole_depth | <= at the fail limit (40 × diameter) | warn | warn |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.hole_depth | <= just past the fail limit (40 × diameter) | fail | fail |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.hole_depth | <= at the warn limit (4 × diameter) | pass | pass |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.hole_depth | <= just past the warn limit (4 × diameter) | warn | warn |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.hole_min | >= at the fail limit (1 mm) | warn | warn |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.hole_min | >= just past the fail limit (0.999999 mm) | fail | fail |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.hole_min | >= at the warn limit (2.5 mm) | pass | pass |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.hole_min | >= just past the warn limit (2.5 mm) | warn | warn |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.hole_drill | <= at the warn limit (0.01 mm off the nearest size) | pass | pass |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| cnc cnc.hole_drill | <= just past the warn limit (0.010001 mm off the nearest size) | warn | warn |  |  |  | pass | rule (How to design parts for CNC machining, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| injection injection.undercut | <= at the fail limit (0 mm²) | pass | pass |  |  |  | pass | computed (B-rep) |
| injection injection.undercut | <= just past the fail limit (1e-06 mm²) | fail | fail |  |  |  | pass | computed (B-rep) |
| injection injection.draft | >= at the fail limit (0.5 °) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.draft | >= just past the fail limit (0.499999 °) | fail | fail |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.draft | >= at the warn limit (2 °) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.draft | >= just past the warn limit (2 °) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.draft_textured | >= at the fail limit (3 °) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.draft_textured | >= just past the fail limit (3 °) | fail | fail |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = abs) | >= at the warn limit (1.143 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = abs) | >= just past the warn limit (1.143 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = acetal) | >= at the warn limit (0.762 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = acetal) | >= just past the warn limit (0.761999 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = acrylic) | >= at the warn limit (0.635 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = acrylic) | >= just past the warn limit (0.634999 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = lcp) | >= at the warn limit (0.762 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = lcp) | >= just past the warn limit (0.761999 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = lfrp) | >= at the warn limit (1.905 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = lfrp) | >= just past the warn limit (1.905 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = nylon) | >= at the warn limit (0.762 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = nylon) | >= just past the warn limit (0.761999 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = pc) | >= at the warn limit (1.016 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = pc) | >= just past the warn limit (1.016 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = pe) | >= at the warn limit (0.762 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = pe) | >= just past the warn limit (0.761999 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = polyester) | >= at the warn limit (0.635 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = polyester) | >= just past the warn limit (0.634999 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = pp) | >= at the warn limit (0.889 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = pp) | >= just past the warn limit (0.888999 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = pps) | >= at the warn limit (0.508 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = pps) | >= just past the warn limit (0.507999 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = ps) | >= at the warn limit (0.889 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = ps) | >= just past the warn limit (0.888999 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = pu) | >= at the warn limit (2.032 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_min (resin = pu) | >= just past the warn limit (2.032 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = abs) | <= at the warn limit (3.556 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = abs) | <= just past the warn limit (3.556 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = acetal) | <= at the warn limit (3.048 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = acetal) | <= just past the warn limit (3.048 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = acrylic) | <= at the warn limit (12.7 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = acrylic) | <= just past the warn limit (12.7 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = lcp) | <= at the warn limit (3.048 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = lcp) | <= just past the warn limit (3.048 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = lfrp) | <= at the warn limit (25.4 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = lfrp) | <= just past the warn limit (25.4 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = nylon) | <= at the warn limit (2.921 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = nylon) | <= just past the warn limit (2.921 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = pc) | <= at the warn limit (3.81 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = pc) | <= just past the warn limit (3.81 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = pe) | <= at the warn limit (5.08 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = pe) | <= just past the warn limit (5.08001 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = polyester) | <= at the warn limit (3.175 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = polyester) | <= just past the warn limit (3.175 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = pp) | <= at the warn limit (3.81 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = pp) | <= just past the warn limit (3.81 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = pps) | <= at the warn limit (4.572 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = pps) | <= just past the warn limit (4.572 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = ps) | <= at the warn limit (3.81 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = ps) | <= just past the warn limit (3.81 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = pu) | <= at the warn limit (19.05 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.wall_max (resin = pu) | <= just past the warn limit (19.05 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.projected_area | <= at the warn limit (175 in²) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.projected_area | <= just past the warn limit (175 in²) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.depth | <= at the warn limit (101 mm) | pass | pass |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| injection injection.depth | <= just past the warn limit (101 mm) | warn | warn |  |  |  | pass | rule (Plastic Injection Molding Design Guidelines, Protolabs, read 2026-11-28) |
| fdm fdm.wall | >= at the fail limit (0.8 mm) | pass | pass |  |  |  | pass | rule (What are the key design elements for 3D printing?, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| fdm fdm.wall | >= just past the fail limit (0.799999 mm) | fail | fail |  |  |  | pass | rule (What are the key design elements for 3D printing?, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| fdm fdm.overhang | >= at the warn limit (45 ° from level) | pass | pass |  |  |  | pass | rule (What are the key design elements for 3D printing?, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| fdm fdm.overhang | >= just past the warn limit (45 ° from level) | warn | warn |  |  |  | pass | rule (What are the key design elements for 3D printing?, Protolabs Network (formerly Hubs), knowledge base, read 2026-11-28) |
| sla sla.wall | >= at the fail limit (0.2 mm) | pass | pass |  |  |  | pass | rule (Design specifications for 3D models (Form 4L generation), Formlabs, support article, read 2026-11-28) |
| sla sla.wall | >= just past the fail limit (0.199999 mm) | fail | fail |  |  |  | pass | rule (Design specifications for 3D models (Form 4L generation), Formlabs, support article, read 2026-11-28) |
| sla sla.overhang | >= at the warn limit (10 ° from level) | pass | pass |  |  |  | pass | rule (Design specifications for 3D models (Form 4L generation), Formlabs, support article, read 2026-11-28) |
| sla sla.overhang | >= just past the warn limit (9.99999 ° from level) | warn | warn |  |  |  | pass | rule (Design specifications for 3D models (Form 4L generation), Formlabs, support article, read 2026-11-28) |
| sla sla.hole | >= at the fail limit (0.5 mm) | pass | pass |  |  |  | pass | rule (Design specifications for 3D models (Form 4L generation), Formlabs, support article, read 2026-11-28) |
| sla sla.hole | >= just past the fail limit (0.499999 mm) | fail | fail |  |  |  | pass | rule (Design specifications for 3D models (Form 4L generation), Formlabs, support article, read 2026-11-28) |
| sla sla.trapped | <= at the fail limit (0 voids) | pass | pass |  |  |  | pass | computed (B-rep) |
| sla sla.trapped | <= just past the fail limit (1e-06 voids) | fail | fail |  |  |  | pass | computed (B-rep) |
| sls sls.wall | >= at the fail limit (0.6 mm) | pass | pass |  |  |  | pass | rule (Fuse Series SLS Design Guide, Formlabs, white paper, read 2026-11-28) |
| sls sls.wall | >= just past the fail limit (0.599999 mm) | fail | fail |  |  |  | pass | rule (Fuse Series SLS Design Guide, Formlabs, white paper, read 2026-11-28) |
| sls sls.hole | >= at the fail limit (1 mm) | pass | pass |  |  |  | pass | rule (Fuse Series SLS Design Guide, Formlabs, white paper, read 2026-11-28) |
| sls sls.hole | >= just past the fail limit (0.999999 mm) | fail | fail |  |  |  | pass | rule (Fuse Series SLS Design Guide, Formlabs, white paper, read 2026-11-28) |
| sls sls.trapped | <= at the fail limit (0 voids) | pass | pass |  |  |  | pass | computed (B-rep) |
| sls sls.trapped | <= just past the fail limit (1e-06 voids) | fail | fail |  |  |  | pass | computed (B-rep) |
| mjf mjf.wall | >= at the fail limit (1 mm) | pass | pass |  |  |  | pass | rule (Design Guidelines for PA 12 (MJF), Materialise Academy, read 2026-11-28) |
| mjf mjf.wall | >= just past the fail limit (0.999999 mm) | fail | fail |  |  |  | pass | rule (Design Guidelines for PA 12 (MJF), Materialise Academy, read 2026-11-28) |
| mjf mjf.hole | >= at the fail limit (1 mm) | warn | warn |  |  |  | pass | rule (Design Guidelines for PA 12 (MJF), Materialise Academy, read 2026-11-28) |
| mjf mjf.hole | >= just past the fail limit (0.999999 mm) | fail | fail |  |  |  | pass | rule (Design Guidelines for PA 12 (MJF), Materialise Academy, read 2026-11-28) |
| mjf mjf.hole | >= at the warn limit (2 mm) | pass | pass |  |  |  | pass | rule (Design Guidelines for PA 12 (MJF), Materialise Academy, read 2026-11-28) |
| mjf mjf.hole | >= just past the warn limit (2 mm) | warn | warn |  |  |  | pass | rule (Design Guidelines for PA 12 (MJF), Materialise Academy, read 2026-11-28) |
| mjf mjf.trapped | <= at the fail limit (0 voids) | pass | pass |  |  |  | pass | computed (B-rep) |
| mjf mjf.trapped | <= just past the fail limit (1e-06 voids) | fail | fail |  |  |  | pass | computed (B-rep) |
| lpbf lpbf.wall | >= at the fail limit (0.381 mm) | warn | warn |  |  |  | pass | rule (Designing for Metal 3D Printing (DMLS design guide), Protolabs, read 2026-11-28) |
| lpbf lpbf.wall | >= just past the fail limit (0.380999 mm) | fail | fail |  |  |  | pass | rule (Designing for Metal 3D Printing (DMLS design guide), Protolabs, read 2026-11-28) |
| lpbf lpbf.wall | >= at the warn limit (1 mm) | pass | pass |  |  |  | pass | rule (Designing for Metal 3D Printing (DMLS design guide), Protolabs, read 2026-11-28) |
| lpbf lpbf.wall | >= just past the warn limit (0.999999 mm) | warn | warn |  |  |  | pass | rule (Designing for Metal 3D Printing (DMLS design guide), Protolabs, read 2026-11-28) |
| lpbf lpbf.overhang (alloy = 316l) | >= at the fail limit (55 ° from the build plate) | pass | pass |  |  |  | pass | rule (Designing for Metal 3D Printing (DMLS design guide), Protolabs, read 2026-11-28) |
| lpbf lpbf.overhang (alloy = 316l) | >= just past the fail limit (54.9999 ° from the build plate) | fail | fail |  |  |  | pass | rule (Designing for Metal 3D Printing (DMLS design guide), Protolabs, read 2026-11-28) |
| lpbf lpbf.overhang (alloy = cunisicr) | >= at the fail limit (55 ° from the build plate) | pass | pass |  |  |  | pass | rule (Designing for Metal 3D Printing (DMLS design guide), Protolabs, read 2026-11-28) |
| lpbf lpbf.overhang (alloy = cunisicr) | >= just past the fail limit (54.9999 ° from the build plate) | fail | fail |  |  |  | pass | rule (Designing for Metal 3D Printing (DMLS design guide), Protolabs, read 2026-11-28) |
| lpbf lpbf.overhang (alloy = default) | >= at the fail limit (45 ° from the build plate) | pass | pass |  |  |  | pass | rule (Designing for Metal 3D Printing (DMLS design guide), Protolabs, read 2026-11-28) |
| lpbf lpbf.overhang (alloy = default) | >= just past the fail limit (45 ° from the build plate) | fail | fail |  |  |  | pass | rule (Designing for Metal 3D Printing (DMLS design guide), Protolabs, read 2026-11-28) |
| lpbf lpbf.trapped | <= at the fail limit (0 voids) | pass | pass |  |  |  | pass | computed (B-rep) |
| lpbf lpbf.trapped | <= just past the fail limit (1e-06 voids) | fail | fail |  |  |  | pass | computed (B-rep) |

<a id="recon"></a>
### Mesh to editable CAD: deviation against tolerance

Wave recon. 10 rows, 10 pass, 0 fail. Commit `8c7f09ad7d (wave-v-bench)`, arm64, Darwin 27.3.0, 18 cores, Python 3.12.15, 2026-11-28.

| Group | Quantity | Expected | Computed | Unit | Error | Accepted | Result | Source |
|---|---|---|---|---|---|---|---|---|
| bracket: filleted_bracket | Hausdorff deviation | <= 0.02 | 0.00119 | mm |  | 0.02 | pass | the input mesh; B-rep 100.0 %, editable 100.0 %, gates pass, 62.1 s |
| bracket: stepped_bracket | Hausdorff deviation | <= 0.02 | 0.001711 | mm |  | 0.02 | pass | the input mesh; B-rep 100.0 %, editable 100.0 %, gates pass, 91.9 s |
| flange: bolt_flange | Hausdorff deviation | <= 0.02 | 0.012433 | mm |  | 0.02 | pass | the input mesh; B-rep 100.0 %, editable 100.0 %, gates pass, 18.8 s |
| turned shaft: turned_shaft | Hausdorff deviation | <= 0.02 | 0.008252 | mm |  | 0.02 | pass | the input mesh; B-rep 100.0 %, editable 100.0 %, gates pass, 39.2 s |
| turned shaft: flanged_shaft | Hausdorff deviation | <= 0.02 | 0.009965 | mm |  | 0.02 | pass | the input mesh; B-rep 100.0 %, editable 100.0 %, gates pass, 217.3 s |
| enclosure with holes: enclosure_with_holes | Hausdorff deviation | <= 0.02 | 5.7e-05 | mm |  | 0.02 | pass | the input mesh; B-rep 94.33 %, editable 100.0 %, gates pass, 182.9 s |
| filleted block: filleted_block | Hausdorff deviation | <= 0.02 | 0.001446 | mm |  | 0.02 | pass | the input mesh; B-rep 66.4 %, editable 100.0 %, gates pass, 134.4 s |
| scan artifacts: bolt_flange+noise | Hausdorff deviation | <= 0.05 | 0.041872 | mm |  | 0.05 | pass | the input mesh; B-rep 100.0 %, editable 100.0 %, gates pass, 39.9 s |
| scan artifacts: bolt_flange+quantised | Hausdorff deviation | <= 0.05 | 0.016958 | mm |  | 0.05 | pass | the input mesh; B-rep 100.0 %, editable 100.0 %, gates pass, 17.4 s |
| scan artifacts: bolt_flange+dropout | Hausdorff deviation | <= 0.05 | 0.012433 | mm |  | 0.05 | pass | the input mesh; B-rep 100.0 %, editable 100.0 %, gates pass, 17.9 s |
