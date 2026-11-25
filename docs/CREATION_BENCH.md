# Creation bench: refinement on and off

The 22 creation briefs (tests/design_bench/creation_briefs.json) run twice through the MCP server by the scripted agent (tests/fixtures/scripted_agent.py, deterministic, no model): once with design refinement on (the default: it runs in the background after every build and the bench waits for the last one), once with FORM_REFINE=off. On: 2026-11-25 09:48:57, off: 2026-11-25 09:43:19, 2 kernel workers. Every number is measured in these runs; the critic score is the design bench's heuristic (tests/design_bench/bench.py), not a person's judgement.

## Gates

- Function checks identical on and off: **pass**
- Mean critic gain >= 0.5: **pass** (mean 1.91)
- No brief lower: **pass**
- First visible within 5 % of off: **pass** (median 0.044 s on, 0.043 s off)

## Per brief

| Brief | Critic off | Critic on | Gain | Checks same | First visible off / on (s) | Refinement | Changes kept |
|---|---|---|---|---|---|---|---|
| shaft_coupler | 80 | 80 | +0.0 | yes | 0.164 / 0.217 | done 2.86 s (no step gains 2 %) | Material zones |
| pillow_block | 93 | 93 | +0.0 | yes | 0.035 / 0.037 | done 5.62 s (no step gains 2 %) | Material zones, Fillet hierarchy |
| cam_clamp | 93 | 93 | +0.0 | yes | 0.074 / 0.038 | done 2.43 s (no step gains 2 %) | Material zones |
| planetary | 93 | 100 | +7.0 | yes | 0.044 / 0.047 | done 5.55 s (no step gains 2 %) | Material zones, Fillet hierarchy |
| din_clip | 93 | 93 | +0.0 | yes | 0.035 / 0.038 | done 3.06 s (no step gains 2 %) | Material zones |
| drag_chain | 93 | 93 | +0.0 | yes | 0.039 / 0.04 | done 3.9 s (no step gains 2 %) | Material zones |
| spiral_vase | 93 | 93 | +0.0 | yes | 0.038 / 0.038 | done 16.82 s (time budget spent) | Material zones |
| twisted_shade | 93 | 93 | +0.0 | yes | 0.053 / 0.055 | done 16.19 s (time budget spent) | Material zones |
| knurled_knob | 93 | 93 | +0.0 | yes | 0.036 / 0.037 | done 13.28 s (time budget spent) | Material zones |
| hex_planter | 93 | 93 | +0.0 | yes | 0.04 / 0.042 | done 18.77 s (time budget spent) | Material zones |
| earbud_case | 93 | 100 | +7.0 | yes | 0.071 / 0.071 | done 17.95 s (time budget spent) | Fillet hierarchy, Material zones |
| hero_helmet | 89 | 89 | +0.0 | yes | 0.12 / 0.122 | done 21.05 s (time budget spent) | Material zones |
| scooter_helmet | 93 | 93 | +0.0 | yes | 0.116 / 0.116 | done 18.99 s (time budget spent) | Material zones |
| mouse_shell | 60 | 60 | +0.0 | yes | 0.108 / 0.108 | done 10.5 s (no step gains 2 %) | Material zones |
| screwdriver_handle | 93 | 93 | +0.0 | yes | 0.037 / 0.04 | done 11.82 s (time budget spent) | Fillet hierarchy, Material zones |
| creature_horn | 93 | 93 | +0.0 | yes | 0.059 / 0.06 | done 11.78 s (no step gains 2 %) | Material zones |
| screwed_enclosure | 93 | 100 | +7.0 | yes | 0.043 / 0.043 | done 13.57 s (no step gains 2 %) | Fillet hierarchy, Material zones |
| aa_box | 80 | 87 | +7.0 | yes | 0.036 / 0.038 | done 15.04 s (time budget spent) | Fillet hierarchy, Edge break, Material zones |
| magnet_organizer | 93 | 93 | +0.0 | yes | 0.039 / 0.041 | done 15.69 s (time budget spent) | Material zones |
| ratchet | 93 | 100 | +7.0 | yes | 0.043 / 0.045 | done 16.86 s (time budget spent) | Material zones, Fillet hierarchy |
| pod_parts | 93 | 93 | +0.0 | yes | 0.084 / 0.08 | done 13.53 s (no step gains 2 %) | none |
| hang_injected | 93 | 100 | +7.0 | yes | 0.043 / 0.045 | done 18.82 s (time budget spent) | Fillet hierarchy, Material zones |

## Totals

- Final build ok: 100.0 % off, 100.0 % on.
- Critic mean: 90.1 off, 92.0 on.
- Refinement: {"refined": 21, "of": 22, "changes": 30, "states": {"done": 22}, "seconds_median": 13.55, "seconds_max": 21.05, "within_budget": 21}.
- Total seconds: 278.3 off, 469.1 on.

## Reading it

- The critic is the design bench's score out of 100 (staging, builds, features, craft, form, integrity, and a product class's silhouette). Refinement can move only some of it: craft (rounds present, sharp-edge share under 0.6), integrity (it must not fold a skin or thin a wall) and the class silhouette. Material zones change the deficit vector the engine searches on but no critic item, so most briefs keep their score.
- First visible is the time from the brief's first call to the first stage the kernel reports: the skeleton, built before any refinement starts. The difference on and off is a few milliseconds.
- Refinement time: 21 of 22 jobs within their budget (20 s for CAD, the final exported-mesh check included); the median and the longest are in the Refinement line above.
- Earlier runs of this pass, not used above: before the checkpoint-pruning fix (form/featureprog.py prunes in a background thread now) the gate failed again, median 0.048 s on and 0.0435 s off; with pruning moved off the build path a second pair was discarded unread because another benchmark process (the game bench's rescoring) ran on the same machine during it. The pair above ran alone.
