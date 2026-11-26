# North star

The project's goals: the brief every contributor works from.

## The product

**Form Studio is the open-source AI CAD studio: describe anything, and an engineer-grade agent builds it as real,
editable CAD.** A part, a product shell, a mechanism or an organic form: you describe it, add a photo, a sketch, a
drawing or a mesh, and the agent designs it with a parametric CAD kernel while you watch. Every design stays editable:
named parameters, features you can select and change, a revision history and checks that say honestly what is known.

Making it is the last step, and printing is one way among several: STEP for another CAD program, renders, CNC, laser
cutting, moulding, or 3D printing with your own slicer. 3D printing is optional and opt-in; nothing about printers or
slicers appears until you turn it on.

Setup is a launcher. It asks what you want to make, which agent designs with you, and then downloads only that. Every
choice can be changed later in Settings.

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

- **Design:** near-black plate, one periwinkle datum colour, clay parts, evidence-coloured tags. One focal point per view.
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
