"""Replace a broken part: one guided flow from a photo to a replacement design.

    from form import replace
    msg = replace.brief("Shelf clip", reference="card", broke="the hook snapped at its root")

The pieces already exist: the agent reads the scale off a reference object in the photo (Form Studio's photo rule: a
bank card, a coin's official diameter, a ruler), asks for the fit-critical sizes with ask_measurement (where, tolerance,
a diagram; the answer is committed with how it was measured) and designs the part with create_design. This module
writes the message that asks for exactly that, in that order, and names the steps the app shows while it happens.
It runs nothing itself: the agent does the work through the app's normal chat (or `form chat` on the command line).
"""
from __future__ import annotations

FIRST_LINE = "Replace a broken part"

REFERENCES = {
    "card": "a bank card (85.60 × 53.98 mm, ISO/IEC 7810 ID-1)",
    "coin": "a coin (use its official diameter; say which coin you assume)",
    "ruler": "a ruler or tape measure in the photo",
    "none": "",
}

STEPS = [
    {"id": "photo", "label": "Photo", "text": "A photo of the broken part"},
    {"id": "estimate", "label": "Estimate", "text": "Sizes estimated from the photo's scale"},
    {"id": "measure", "label": "Measure", "text": "You measure the sizes that decide the fit"},
    {"id": "design", "label": "Design", "text": "The replacement, built in the kernel"},
]


def brief(name: str = "", what: str = "", reference: str = "card", coin: str = "", broke: str = "",
          purpose: str = "print") -> str:
    """The message the agent receives with the photo attached."""
    from .studio import StudioError
    if reference not in REFERENCES:
        raise StudioError(f"Unknown reference “{reference}”.", "Use card, coin, ruler or none.")
    name = (name or "").strip()[:80] or "the part in the photo"
    ref = REFERENCES[reference]
    if reference == "coin" and coin.strip():
        ref = f"a coin: {coin.strip()[:60]} (use its official diameter)"
    lines = [f"{FIRST_LINE}: {name}.", ""]
    if what.strip():
        lines += [f"What it does: {what.strip()[:600]}", ""]
    if broke.strip():
        lines += [f"Where and how it broke: {broke.strip()[:600]}", ""]
    lines += ["Work in these steps, and say which step you are on:", ""]
    if ref:
        lines.append(f"1. Estimate from the photo. The photo shows {ref} next to the part. Find the scale from it and "
                     "estimate the part's overall sizes. Say each one is “estimated from the photo (scale from "
                     f"{reference if reference != 'none' else 'the reference'})”; they stay assumed until measured.")
    else:
        lines.append("1. Estimate from the photo. There is no reference object in it, so there is no scale: estimate "
                     "proportions only, and get one overall size from me with ask_measurement before any other number.")
    lines += [
        "2. Measure. Ask me for the sizes that decide whether the replacement fits (holes, pins, shafts, slots, clips, "
        "mounting distances, the thickness of what it grips) with ask_measurement: where to measure, the tolerance, a "
        "diagram. One question at a time, at most three. Use what I measure; never invent a number I did not give.",
        "3. Design. Design the replacement with create_design (a recipe only if it is truly the same part), with the "
        "measured sizes, and reinforce it where the original broke (a fillet, a thicker section, the layers along "
        "the load). Render it and look at it, then run the pipeline and tell me which checks pass.",
    ]
    if purpose == "model":
        lines += ["", "Purpose: just a 3D model, not for 3D printing."]
    else:
        lines += ["", "Purpose: for 3D printing."]
    return "\n".join(lines)


def guide() -> dict:
    """What the flow is, for an agent outside Form Studio (MCP replace_part_guide)."""
    return {"steps": STEPS, "references": {k: v for k, v in REFERENCES.items() if v},
            "how": ["Look at the person's photo. Find the scale from a reference object in it and estimate the overall "
                    "sizes; they are estimates, provenance assumed.",
                    "ask_measurement for each size that decides the fit, one at a time, at most three.",
                    "create_design with the measured values; strengthen where it broke; render, run_pipeline, report the checks."],
            "note": "Photo estimates are never fit-critical. Only what the person measures is marked measured."}
