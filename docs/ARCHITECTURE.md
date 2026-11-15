# Architecture

```
agent (Codex / Claude Code / Gemini / Cursor)      person
        | MCP stdio (form-mcp) or JSON CLI (form)    | browser: the bench
        +-----------------------+--------------------+
                                |
                     Studio (form/studio.py)  -- one project state, cross-process locks
                     |            |             |
      kernel worker (OCCT)   slicer adapter   renderer (numpy, headless PNG)
      form/worker.py         form/adapters/   form/render.py
```

**FORM is a layer, not an app.** Agents supply the intelligence; existing software supplies CAD and slicing. FORM owns what neither does: parameters with provenance, hashed staleness, computed impact, checks, the fit model, calibration and the release record.

**Agents propose, a person releases.** Every engine action is an MCP tool except approval, which exists only on the bench. `commit_change` takes `expect_head`; a stale head is refused with the current head, so an agent never overwrites a newer human edit. Revisions record their origin (`agent:<client name>`, `cli`, `user`).

**Agents can see.** `render` rasterises the kernel's tessellation in-process (z-buffer, flat shading, visible edges, colour by feature, scale bar) and returns a PNG. No GPU, browser or OCCT in the server process.

**Concurrency.** The bench, one or more MCP servers and the CLI may share a data folder. `Studio.lock(pid)` is an in-process RLock plus an `flock` on `<data>/.locks/<pid>.lock`; every mutation reloads the project under the lock. The bench polls a cheap `/stamp` and follows agent edits.

## Decisions

**build123d is the only geometry authority.** A recipe builds a BREP solid in OCCT as an ordered list of feature stages. STEP is the exchange format for any other CAD tool; STL is derived for slicing. Other CAD tools receive STEP through `open_in`; none of them is a second editable source.

**Staleness is derived, never flagged.** `Studio.keys()` hashes each artifact's inputs:

| Artifact | Key covers |
|---|---|
| Solid | recipe source hash, kernel version, parameter values |
| STEP + STL | solid key, print orientation, mesh tolerance |
| Checks | export key, build envelope, nozzle, checks version, fit window, calibration fingerprint, provenance of the mating dimension |
| Slice | export key, content hash of each flattened preset, slicer version |

An artifact is current if a file exists under the expected key. So a clearance change stales all four; an orientation change keeps the solid; a new coupon measurement stales only the checks; selecting another process in Bambu Studio stales only the slice. Reverting an input makes the old artifact current again with no rebuild.

**Feature attribution is geometric.** After each stage the kernel keeps the solid's skin. A final face belongs to the last stage that created the surface under it. This is what makes click-to-select and “features touched” real rather than declared.

**OCCT is isolated.** The server talks to one worker process over a pipe. A timeout or crash kills the worker; the next call starts a new one; project state is untouched.

**Evidence classes.** computed (kernel), heuristic (rule of thumb on computed values), model (statistics or statics with stated assumptions), simulated (slicer), physical (entered by the user from a real print). Coupon measurements calibrate the printer profile; only a result from the part itself counts as physical evidence for a revision.

**Optional in-app model call.** Off by default (`[models].cli = ""`). “Read” parses simple intents locally. If enabled, “Ask”/“Consult” make one tool-less `claude -p` call with a JSON schema and a replaced system prompt; the reply is range-checked, rebuilt by the kernel, shown with its computed impact, and applied only if you load and commit it. Model, cost and summary go to the decision log.

## Fit model

Total gap = (nominal cavity + printer bias) − device width, errors independent and normal. Device σ comes from its provenance; printer bias and σ from pooled coupon/part measurements for the profile (printer · filament), or an assumed ±0.15 mm prior labelled as assumed. Yield is the probability the gap lands in your acceptance window.

## Slicer

`form/slicer.py` dispatches to the adapter named by `[slicer].kind`. The Bambu adapter (`form/adapters/bambu.py`) reads the presets selected in Bambu Studio (or pinned in `studio.toml`), flattens their inheritance chain into self-contained JSON, and runs the Bambu Studio CLI on the oriented STL. Time, filament and supports come from the produced 3MF and G-code; the G-code is parsed into per-layer paths by feature type for inspection.
