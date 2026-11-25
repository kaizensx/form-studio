"""Refinement styles: how much each operator is wanted, with which parameters, and which deficits weigh more.

    styles.detect("a rugged field tool with knurled grips")        # "rugged_tool"
    styles.weight("rugged_tool", "knurl_zone")                     # 1.6
    styles.params("rugged_tool", op)                               # op.params with the style's overrides

A style is chosen from the brief's words, then from the product class (form/product_classes.detect), and falls back
to clean consumer. Weights multiply an operator's priority (1.0 when a style does not name it; 0 turns it off).
Operator names are the ones the operator modules use (form/refine/ops_cad.py, ops_cage.py, ops_material.py); a name
no module defines is simply never ranked.
"""
from __future__ import annotations

import re

DEFAULT = "clean_consumer"

STYLES = {
    "clean_consumer": {
        "label": "Clean consumer",
        "keywords": ["consumer", "clean", "minimal", "sleek", "modern", "appliance", "gadget", "device", "remote",
                     "speaker", "earbud", "case", "phone", "desk", "home", "kitchen", "product"],
        "weights": {"fillet_hierarchy": 1.5, "parting_line": 1.4, "edge_break": 1.2, "button_pads": 1.3,
                    "recessed_panel": 1.1, "knurl_zone": 0.5, "rib_lightening": 0.6, "material_zones": 1.3,
                    "contrast_pair": 1.0, "edge_wear": 0.0, "silhouette_breaker": 0.6, "kit_place": 0.4,
                    "support_loops": 1.2, "panel_line": 0.8, "trim_strip": 0.7, "inset": 1.0},
        "params": {"fillet_hierarchy": {"tiers": [0.4, 1.5, 5.0]}, "parting_line": {"width": 0.5, "depth": 0.4},
                   "edge_break": {"r": 0.3}, "contrast_pair": {"min_contrast": 0.15},
                   "knurl_zone": {"pitch": 1.2}},          # a fine knurl reads as a consumer finish, a coarse one as a tool
        "deficits": {"edge_hierarchy": 1.4, "surface_breaks": 1.1, "wear": 0.0},
    },
    "rugged_tool": {
        "label": "Rugged tool",
        "keywords": ["rugged", "tool", "field", "outdoor", "industrial", "work", "heavy duty", "heavy-duty", "grip",
                     "knurl", "knurled", "tactical", "jobsite", "drill", "wrench", "clamp", "bracket"],
        "weights": {"fillet_hierarchy": 1.2, "parting_line": 1.0, "edge_break": 1.3, "knurl_zone": 1.6,
                    "rib_lightening": 1.4, "button_pads": 1.0, "recessed_panel": 0.9, "material_zones": 1.2,
                    "contrast_pair": 1.2, "edge_wear": 1.2, "silhouette_breaker": 1.0, "kit_place": 1.0,
                    "support_loops": 1.0, "panel_line": 1.0, "trim_strip": 1.2, "inset": 0.9},
        "params": {"fillet_hierarchy": {"tiers": [0.6, 2.0, 6.0]}, "knurl_zone": {"pitch": 1.2, "depth": 0.5},
                   "edge_break": {"r": 0.5}, "edge_wear": {"amount": 0.5}},
        "deficits": {"touch_points": 1.4, "detail_scales": 1.2},
    },
    "scifi_hard_surface": {
        "label": "Sci-fi hard surface",
        "keywords": ["sci-fi", "scifi", "sci fi", "futuristic", "hard surface", "hard-surface", "mech", "robot",
                     "spaceship", "space", "cyber", "drone", "blaster", "armor", "armour", "panel"],
        "weights": {"panel_line": 1.8, "inset": 1.5, "kit_place": 1.6, "trim_strip": 1.3, "silhouette_breaker": 1.5,
                    "support_loops": 1.3, "recessed_panel": 1.5, "parting_line": 1.4, "fillet_hierarchy": 1.0,
                    "edge_break": 0.8, "knurl_zone": 0.6, "button_pads": 1.0, "material_zones": 1.4,
                    "contrast_pair": 1.3, "edge_wear": 0.8, "rib_lightening": 1.0, "crisp_regions": 1.6},
        "params": {"kit_place": {"ratios": [1.0, 0.38, 0.15], "pitch": "constant"}, "panel_line": {"width": 0.6},
                   "edge_wear": {"amount": 0.3}},
        "deficits": {"silhouette": 1.4, "interior_read": 1.3, "surface_breaks": 1.3},
    },
    "stylised_fantasy": {
        "label": "Stylised fantasy",
        "keywords": ["fantasy", "stylised", "stylized", "medieval", "magic", "wizard", "dragon", "sword", "shield",
                     "chest", "treasure", "castle", "potion", "rune", "elven", "dwarven", "cartoon", "hand-painted"],
        "weights": {"silhouette_breaker": 1.7, "trim_strip": 1.4, "inset": 1.1, "support_loops": 1.2,
                    "kit_place": 1.1, "panel_line": 0.8, "edge_wear": 1.6, "material_zones": 1.5,
                    "contrast_pair": 1.5, "fillet_hierarchy": 1.0, "edge_break": 0.8, "knurl_zone": 0.4,
                    "parting_line": 0.4, "recessed_panel": 0.8, "button_pads": 0.4, "rib_lightening": 0.4},
        "params": {"edge_wear": {"amount": 0.6}, "silhouette_breaker": {"exaggeration": 1.3}},
        "deficits": {"silhouette": 1.5, "material_contrast": 1.3, "wear": 1.3},
    },
    "organic": {
        "label": "Organic",
        "keywords": ["organic", "natural", "flowing", "soft", "ergonomic", "sculpted", "biomorphic", "creature",
                     "plant", "vase", "pebble", "shell", "wave", "curved", "smooth"],
        "weights": {"fillet_hierarchy": 1.6, "edge_break": 1.2, "parting_line": 0.0, "recessed_panel": 0.5,
                    "button_pads": 0.6, "knurl_zone": 0.5, "rib_lightening": 0.4, "panel_line": 0.4,
                    "kit_place": 0.2, "trim_strip": 0.4, "inset": 0.6, "silhouette_breaker": 1.0,
                    "support_loops": 1.4, "material_zones": 1.1, "contrast_pair": 0.9, "edge_wear": 0.6},
        "params": {"fillet_hierarchy": {"tiers": [1.0, 3.0, 9.0]}, "edge_break": {"r": 0.6}},
        "deficits": {"edge_hierarchy": 1.2, "surface_breaks": 0.6, "proportion": 1.2},
    },
}

# product classes (form/product_classes.CLASSES) that settle a style when the brief's words do not
CLASS_STYLE = {"mouse": "clean_consumer", "bottle": "clean_consumer", "helmet_fullface": "scifi_hard_surface",
               "helmet_open": "rugged_tool"}


def _words(text: str) -> str:
    return " " + " ".join(re.sub(r"[^a-z0-9\- ]+", " ", (text or "").lower()).split()) + " "


def detect(brief: str = "", product_class: str | None = None) -> str:
    """The style a brief asks for: the most keyword hits (longer keywords count more; ties go to the order of
    STYLES), then the product class's style, then clean consumer."""
    low = _words(brief)
    best, score = None, 0.0
    for sid, s in STYLES.items():
        sc = sum(len(k) for k in s["keywords"] if f" {k} " in low)
        if sc > score:
            best, score = sid, sc
    if best:
        return best
    if product_class is None and brief:
        try:
            from ..product_classes import detect as detect_class
            product_class = detect_class(brief)
        except Exception:                                       # noqa: BLE001 - classes are a hint, never required
            product_class = None
    return CLASS_STYLE.get(product_class or "", DEFAULT)


def get(style: str | None) -> dict:
    return STYLES.get(style or "", STYLES[DEFAULT])


def weight(style: str | None, op_name: str) -> float:
    return float(get(style)["weights"].get(op_name, 1.0))


def params(style: str | None, op) -> dict:
    """The operator's default params with the style's overrides."""
    return {**(getattr(op, "params", None) or {}), **(get(style)["params"].get(op.name) or {})}


def deficit_weights(style: str | None) -> dict:
    """Per-deficit weight multipliers of the style, applied over form/refine/analyze.WEIGHTS."""
    from .analyze import WEIGHTS
    mult = get(style).get("deficits") or {}
    return {k: round(w * float(mult.get(k, 1.0)), 4) for k, w in WEIGHTS.items()}
