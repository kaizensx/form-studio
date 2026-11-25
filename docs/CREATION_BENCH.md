# Creation bench: refinement on and off

The 22 creation briefs (tests/design_bench/creation_briefs.json) run twice through the MCP server by the scripted agent (tests/fixtures/scripted_agent.py, deterministic, no model): once with design refinement on (the default: it runs in the background after every build and the bench waits for the last one), once with FORM_REFINE=off. On: 2026-11-25 07:27:54, off: 2026-11-25 07:21:56, 2 kernel workers. Every number is measured in these runs; the critic score is the design bench's heuristic (tests/design_bench/bench.py), not a person's judgement.

## Gates

- Function checks identical on and off: **pass**
- Mean critic gain >= 0.5: **pass** (mean 2.23)
- No brief lower: **pass**
- First visible within 5 % of off: **FAIL** (median 0.046 s on, 0.0425 s off)

## Per brief

| Brief | Critic off | Critic on | Gain | Checks same | First visible off / on (s) | Refinement | Changes kept |
|---|---|---|---|---|---|---|---|
| shaft_coupler | 80 | 87 | +7.0 | yes | 0.175 / 0.215 | done 4.92 s (no step gains 2 %) | Material zones, Fillet hierarchy |
| pillow_block | 93 | 93 | +0.0 | yes | 0.035 / 0.037 | done 2.78 s (no step gains 2 %) | Material zones |
| cam_clamp | 93 | 93 | +0.0 | yes | 0.038 / 0.038 | done 2.44 s (no step gains 2 %) | Material zones |
| planetary | 93 | 100 | +7.0 | yes | 0.045 / 0.045 | done 5.7 s (no step gains 2 %) | Fillet hierarchy, Material zones |
| din_clip | 93 | 93 | +0.0 | yes | 0.035 / 0.037 | done 2.98 s (no step gains 2 %) | Material zones |
| drag_chain | 93 | 93 | +0.0 | yes | 0.039 / 0.039 | done 3.34 s (no step gains 2 %) | Material zones |
| spiral_vase | 93 | 93 | +0.0 | yes | 0.037 / 0.037 | done 16.88 s (time budget spent) | Material zones |
| twisted_shade | 93 | 93 | +0.0 | yes | 0.057 / 0.056 | done 25.77 s (time budget spent) | none |
| knurled_knob | 93 | 93 | +0.0 | yes | 0.035 / 0.04 | done 10.44 s (no step gains 2 %) | Material zones |
| hex_planter | 93 | 93 | +0.0 | yes | 0.041 / 0.043 | done 18.74 s (time budget spent) | Material zones |
| earbud_case | 93 | 93 | +0.0 | yes | 0.108 / 0.072 | done 12.93 s (no step gains 2 %) | Material zones |
| hero_helmet | 89 | 89 | +0.0 | yes | 0.124 / 0.121 | done 22.29 s (time budget spent) | Material zones |
| scooter_helmet | 93 | 93 | +0.0 | yes | 0.156 / 0.118 | done 18.54 s (time budget spent) | Material zones |
| mouse_shell | 60 | 60 | +0.0 | yes | 0.113 / 0.111 | done 10.64 s (no step gains 2 %) | Material zones |
| screwdriver_handle | 93 | 93 | +0.0 | yes | 0.039 / 0.041 | done 9.75 s (no step gains 2 %) | Fillet hierarchy, Material zones |
| creature_horn | 93 | 93 | +0.0 | yes | 0.06 / 0.062 | done 12.22 s (no step gains 2 %) | Material zones |
| screwed_enclosure | 93 | 100 | +7.0 | yes | 0.041 / 0.047 | done 11.14 s (time budget spent) | Fillet hierarchy, Material zones |
| aa_box | 80 | 87 | +7.0 | yes | 0.035 / 0.041 | done 14.56 s (no step gains 2 %) | Material zones, Fillet hierarchy |
| magnet_organizer | 93 | 100 | +7.0 | yes | 0.039 / 0.044 | done 17.58 s (time budget spent) | Fillet hierarchy |
| ratchet | 93 | 100 | +7.0 | yes | 0.044 / 0.049 | done 13.82 s (time budget spent) | Fillet hierarchy |
| pod_parts | 93 | 93 | +0.0 | yes | 0.091 / 0.08 | done 14.41 s (no step gains 2 %) | none |
| hang_injected | 93 | 100 | +7.0 | yes | 0.044 / 0.051 | done 11.82 s (time budget spent) | Fillet hierarchy |

## Totals

- Final build ok: 100.0 % off, 100.0 % on.
- Critic mean: 90.1 off, 92.4 on.
- Refinement: {"refined": 20, "of": 22, "changes": 25, "states": {"done": 22}, "seconds_median": 12.02, "seconds_max": 25.77, "within_budget": 20}.
- Total seconds: 296.4 off, 493.9 on.

## Reading it

- The critic is the design bench's score out of 100 (staging, builds, features, craft, form, integrity, and a product class's silhouette). Refinement can move only some of it: craft (rounds present, sharp-edge share under 0.6), integrity (it must not fold a skin or thin a wall) and the class silhouette. Material zones change the deficit vector the engine searches on but no critic item, so most briefs keep their score.
- First visible is the time from the brief's first call to the first stage the kernel reports: the skeleton, built before any refinement starts. The difference on and off is a few milliseconds.
- Refinement time: 20 of 22 jobs within their budget (20 s for CAD, the final exported-mesh check included); the median and the longest are in the Refinement line above.
