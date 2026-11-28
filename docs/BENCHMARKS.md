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

### How Form Studio runs it

- **Agent:** the agent's own CLI through Form Studio's adapter (`form/agents`), with Form Studio's MCP server attached, exactly as a conversation in the app runs it, plus Read, Write and Edit inside the trial folder and Bash limited to FreeCAD's command line. The verifier accepts only a FreeCAD PartDesign feature tree and Form Studio has no PartDesign export yet, so the agent writes the FreeCAD script itself.
- **Prompt:** each task's `instruction.md` as published, with `/app` replaced by the trial's folder, after a short preamble saying where that folder is, that Form Studio's tools are attached and where FreeCAD's command line is.
- **Isolation:** each trial has its own Form Studio data folder and settings. The agent sees only the task's environment files (the drawing); `solution/` and `tests/` stay out of its folder.
- **Scoring:** the task's own `tests/test.sh` and `run_scorer.py` in the image its `tests/Dockerfile` builds (FreeCAD 1.1.0, gnucleus-freecad-validator 0.6.0), with no network. Failures and missing files count zero; mode means are over 30, 30 and 40 tasks, as on the leaderboard.
- **Not a leaderboard entry:** the agent runs on the host, not in the task's container, so a result here is not a Harbor job. Submitting needs `harbor run` with an adapter that installs Form Studio in the task container.

## Form Studio's own suites

Each suite compares a value Form Studio computes with a published one. `form bench run --save` runs them; each runs on the source tree that has its code, and says which.

| Suite | Rows | Pass | Fail | Source | Machine | Date | Time |
|---|---|---|---|---|---|---|---|
| Strength studies against textbook and NAFEMS cases | | | | not run yet | | | |
| Calculators against published worked examples | | | | not run yet | | | |
| ISO 286 limits against the ISO 286-2 tables | | | | not run yet | | | |
| Manufacturability rules at their thresholds | | | | not run yet | | | |
| Mesh to editable CAD: deviation against tolerance | | | | not run yet | | | |
