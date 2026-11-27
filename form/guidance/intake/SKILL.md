---
name: intake
description: Start a new printable part in FORM. Use when the user asks for a new part, or a brief is vague, and you must decide what to ask, what to look up (datasheets, drawings, photos) and which template or recipe to start from. Not for changing an existing design.
---

# Intake: ask only what changes the result

FORM tools: `form_overview()`, `triage()`, `brief_presets()`, `describe_recipe()`, `read_document()`, `get_project()`.

1. `form_overview()` first: printer, slicer, recipes, existing projects. Do not start a duplicate project.
   Anything the person attached or linked, and their words when nothing is attached: `triage(source)`. It says what
   the input is and the route (which calls, in order), what will be prepared, what the route cannot give, and `ask`:
   one question, present only when the answer changes the result. Take the route; do not ask the person to pick it.
2. If the part matches a template, `brief_presets(preset="...")` gives the questions worth asking, environment
   defaults, a starting material and the checks to plan for. Its defaults are **assumed** until the user confirms them.
   A project made from the app's "Start from a brief" already carries `brief.answers`; read them with `get_project()`.
3. Look up before asking, from documents the user gave you or the maker's own drawing. Official dimensions of boards, devices and hardware come from the maker's drawing:
   `read_document(source=url_or_path, pages="1-2")`. Record the document and page in the parameter's doc and mark it
   **specified**.
4. Classify every unknown as blocking (fit, attachment, load, temperature, safety) or reversible (proportions, colour,
   file names, camera angles). Decide the reversible ones yourself and say what you assumed.
5. Ask at most three questions per task, only for blocking unknowns. For each, say why it matters and offer two or three
   choices with a recommendation. Example: "Adhesive pad or screws? I recommend a pad if you want no holes; it needs a
   flat rear face." Use `ask_user(question, choices, why=...)`: in Form Studio's chat it shows the question as a card and
   returns the answer; one question per call. Before an action the user should agree to (replacing or deleting their
   design), use `ask_user(..., kind="confirm")`. If it returns `no_user` (you are outside Form Studio's chat), ask in
   your own interface instead; if nobody answered, continue with safe values marked assumed and say which answer
   would change the design.
6. For a measurement, say what to measure, from which datum, and with what (calipers for anything that must fit).
   A number is **measured** only when the user measured it and told you how.

Photos and scans: a photo with a marked scale gives a rough form dimension (the app's photo measuring treats it as
±0.6 mm or worse). Never derive a fit-critical or hidden dimension from a photo or an unaligned scan; ask for a
measurement instead. To make an existing STL, OBJ, 3MF or STEP editable: `reconstruct(path)` (the remodel-from-mesh
skill has the routes).

Never invent a fit-critical value, and never treat silence as consent or as a measurement.
