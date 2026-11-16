# North star

The owner's goal, rewritten as the brief every contributor (human or agent) works from.

## The product

**FORM is the best open-source AI-to-CAD app.** You open it, describe a physical part, and an AI agent designs it with a
real CAD kernel while you watch. It checks the part, slices it with your real slicer, and tells you honestly what is known.
It should feel like a first-class native creative tool (the calm of Linear, the craft of Things, the viewport of a pro
CAD package), not like a developer demo.

## Non-negotiables

1. **One app, zero terminal.** Everything FORM needs is found, offered and installed from inside the app on first start:
   the CAD kernel, parts libraries, a slicer, the agent CLI, agent sign-in status. The user never opens a terminal, never
   edits a config file, and never has to go to another app to finish setup. Each install is shown before it runs and needs
   one click of consent.
2. **A clean slate.** No example projects are created. The first screen is an invitation to make something.
3. **Conversations like a real assistant app.** Many conversations, each tied to a project or free-standing; a history you
   can search, rename, pin and delete; a model picker; attachments (photos, drawings, STEP files); stop and retry; cost per
   conversation; streaming text. It should feel like Claude, but living inside your designs.
4. **Headless parity.** Every capability that makes sense without a window works from the CLI and over MCP with the same
   engine: no feature exists only in the UI.
5. **Honesty is the brand.** Nothing is faked: no invented CAD runs, slicer output, strength numbers, benchmarks or print
   results. Every number says how it is known (measured, specified, assumed, photo, computed, simulated, modelled,
   heuristic, physical). A missing dependency is named, with the way to get it. Never start a print, upload a design or
   buy anything. Only a human approves a release.
6. **It works with the tools people already have** (slicers, CAD apps, Blender, agents) instead of replacing them.
7. **Cross-platform:** macOS, Windows, Linux. UTF-8 everywhere. No POSIX-only code without a Windows path.
8. **Everything lands on GitHub.** Every finished piece of work is committed, pushed and reflected in the README,
   changelog, docs and the project website. Nothing lives only on one machine.

## The bar

- **Design:** graphite plate, one pale-mint datum colour, clay parts, evidence-coloured tags. One focal point per view.
  Hierarchy from weight and space, not lines. No decoration that does not carry meaning.
- **Motion:** purposeful and fast. Geometry changes are shown, not swapped: parts rebuild, cameras glide, panels answer
  the pointer. 120–320 ms, ease-out; nothing used all day animates; reduced-motion is respected.
- **Wow moments** are real capabilities shown beautifully: watching a part get designed, a print simulated layer by layer,
  a wall-thickness map on the model, an assembly exploding, a photoreal render, a goal-seek optimising a hook.
- **Quality:** every screen is looked at (screenshots) before it ships; every feature has tests; the suite stays green on
  all three platforms; the packaged app is rebuilt and opened.

## How we work

Decide, build, look at it, criticise it, fix it, repeat until there is nothing left that we would be embarrassed to show.
When something is not verified, say so in the product and in the docs.
