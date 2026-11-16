---
name: intake
description: Start a new printable part in FORM. Use when the user asks for a new part, or a brief is vague, and you must decide what to ask, what to look up (datasheets, drawings, photos) and which template or recipe to start from. Not for changing an existing design.
---

# Intake: ask only what changes the result

FORM tools: `form_overview()`, `brief_presets()`, `describe_recipe()`, `read_document()`, `get_project()`.

1. `form_overview()` first: printer, slicer, recipes, existing projects. Do not start a duplicate project.
2. If the part matches a template, `brief_presets(preset="...")` gives the questions worth asking, environment
   defaults, a starting material and the checks to plan for. Its defaults are **assumed** until the user confirms them.
   A project made from the app's "Start from a brief" already carries `brief.answers`; read them with `get_project()`.
3. Look up before asking. Official dimensions of boards, devices and hardware come from the maker's drawing:
   `read_document(source=url_or_path, pages="1-2")`. Record the document and page in the parameter's doc and mark it
   **specified**.
4. Classify every unknown as blocking (fit, attachment, load, temperature, safety) or reversible (proportions, colour,
   file names, camera angles). Decide the reversible ones yourself and say what you assumed.
5. Ask at most three related questions in one batch. For each, say why it matters and offer two or three choices with
   a recommendation. Example: "Adhesive pad or screws? I recommend a pad if you want no holes; it needs a flat rear face."
   Keep working on independent parts of the design while you wait.
6. For a measurement, say what to measure, from which datum, and with what (calipers for anything that must fit).
   A number is **measured** only when the user measured it and told you how.

Photos and scans: a photo with a marked scale gives a rough form dimension (the app's photo measuring treats it as
±0.6 mm or worse). Never derive a fit-critical or hidden dimension from a photo or an unaligned scan; ask for a
measurement instead. FORM does not reconstruct geometry from scans.

Never invent a fit-critical value, and never treat silence as consent or as a measurement.
