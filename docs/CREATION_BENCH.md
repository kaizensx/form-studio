# Creation bench: refinement on and off

The 22 creation briefs (tests/design_bench/creation_briefs.json) run twice through the MCP server by the scripted agent (tests/fixtures/scripted_agent.py, deterministic, no model): once with design refinement on (the default: it runs in the background after every build and the bench waits for the last one), once with FORM_REFINE=off. On: 2026-11-25 00:18:27, off: 2026-11-25 00:12:51, 2 kernel workers. Every number is measured in these runs; the critic score is the design bench's heuristic (tests/design_bench/bench.py), not a person's judgement.

## Gates

- Function checks identical on and off: **pass**
- Mean critic gain >= 0.5: **pass** (mean 1.27)
- No brief lower: **pass**
- First visible within 5 % of off: **pass** (median 0.0445 s on, 0.0425 s off)

## Per brief

| Brief | Critic off | Critic on | Gain | Checks same | First visible off / on (s) | Refinement | Changes kept |
|---|---|---|---|---|---|---|---|
| shaft_coupler | 80 | 80 | +0.0 | yes | 0.164 / 0.214 | done 2.9 s (no step gains 2 %) | Material zones |
| pillow_block | 93 | 93 | +0.0 | yes | 0.035 / 0.036 | done 3.12 s (no step gains 2 %) | Material zones |
| cam_clamp | 93 | 93 | +0.0 | yes | 0.038 / 0.038 | done 2.43 s (no step gains 2 %) | Material zones |
| planetary | 93 | 100 | +7.0 | yes | 0.044 / 0.044 | done 6.68 s (no step gains 2 %) | Fillet hierarchy, Material zones |
| din_clip | 93 | 93 | +0.0 | yes | 0.036 / 0.036 | done 3.05 s (no step gains 2 %) | Material zones |
| drag_chain | 93 | 93 | +0.0 | yes | 0.038 / 0.04 | done 2.82 s (no step gains 2 %) | Material zones |
| spiral_vase | 93 | 93 | +0.0 | yes | 0.035 / 0.037 | done 16.75 s (time budget spent) | Material zones |
| twisted_shade | 93 | 93 | +0.0 | yes | 0.053 / 0.056 | done 6.9 s (no step gains 2 %) | Material zones |
| knurled_knob | 93 | 93 | +0.0 | yes | 0.034 / 0.037 | done 15.81 s (time budget spent) | Material zones |
| hex_planter | 93 | 93 | +0.0 | yes | 0.04 / 0.044 | done 18.67 s (time budget spent) | Material zones |
| earbud_case | 93 | 93 | +0.0 | yes | 0.071 / 0.073 | done 13.35 s (no step gains 2 %) | Material zones |
| hero_helmet | 89 | 89 | +0.0 | yes | 0.121 / 0.127 | done 20.02 s (time budget spent) | Material zones |
| scooter_helmet | 93 | 93 | +0.0 | yes | 0.118 / 0.12 | done 17.08 s (time budget spent) | Material zones |
| mouse_shell | 60 | 60 | +0.0 | yes | 0.108 / 0.11 | done 8.88 s (no step gains 2 %) | Material zones |
| screwdriver_handle | 93 | 93 | +0.0 | yes | 0.037 / 0.041 | done 9.23 s (no step gains 2 %) | Fillet hierarchy, Material zones |
| creature_horn | 93 | 93 | +0.0 | yes | 0.057 / 0.061 | done 12.34 s (no step gains 2 %) | Material zones |
| screwed_enclosure | 93 | 100 | +7.0 | yes | 0.042 / 0.045 | done 14.5 s (no step gains 2 %) | Fillet hierarchy, Material zones |
| aa_box | 80 | 87 | +7.0 | yes | 0.035 / 0.036 | done 14.82 s (time budget spent) | Fillet hierarchy, Material zones |
| magnet_organizer | 93 | 93 | +0.0 | yes | 0.039 / 0.042 | done 15.6 s (time budget spent) | Material zones |
| ratchet | 93 | 100 | +7.0 | yes | 0.043 / 0.048 | done 13.03 s (time budget spent) | Fillet hierarchy |
| pod_parts | 93 | 93 | +0.0 | yes | 0.083 / 0.082 | done 13.35 s (no step gains 2 %) | none |
| hang_injected | 93 | 93 | +0.0 | yes | 0.043 / 0.045 | done 11.14 s (time budget spent) | none |

## Totals

- Final build ok: 100.0 % off, 100.0 % on.
- Critic mean: 90.1 off, 91.4 on.
- Refinement: {"refined": 20, "of": 22, "changes": 24, "states": {"done": 22}, "seconds_median": 12.68, "seconds_max": 20.02, "within_budget": 21}.
- Total seconds: 277.3 off, 801.9 on.

## Reading it

- The critic is the design bench's score out of 100 (staging, builds, features, craft, form, integrity, and a product class's silhouette). Refinement can move only some of it: craft (rounds present, sharp-edge share under 0.6), integrity (it must not fold a skin or thin a wall) and the class silhouette. Material zones change the deficit vector the engine searches on but no critic item, so most briefs keep their score.
- First visible is the time from the brief's first call to the first stage the kernel reports: the skeleton, built before any refinement starts. The difference on and off is a few milliseconds.
- Refinement time: 21 of 22 jobs within their budget (20 s for CAD, the final exported-mesh check included); the median and the longest are in the Refinement line above.
