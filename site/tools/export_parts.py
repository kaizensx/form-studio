"""Export real FORM builds for the website's hero viewer.

Every step of every sweep is one build by the CAD kernel (build123d / OpenCascade) through the same
Studio call the app uses for a draft. Nothing is interpolated here; the page swaps between these builds.

Run from the repository root, with a data folder that holds the sample projects:

    FORM_DATA=.dev/data FORM_CONFIG=/nonexistent PYTHONPATH=. python site/tools/export_parts.py

Writes site/assets/parts/<id>.bin and site/assets/parts/parts.json.

Binary layout per step (little endian, offsets in parts.json):
    positions  uint16 x 3 per vertex, quantised over the sweep's bounding box
    indices    uint16 (or uint32 when a step has more than 65535 vertices) x 3 per triangle
    edges      uint16 x 6 per segment (the kernel's own B-rep edges), same quantisation
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import numpy as np

from form import config
from form.studio import H, Studio

OUT = Path(__file__).resolve().parents[1] / "assets" / "parts"

SWEEPS = [
    {"id": "dock", "project": "hallway-phone-dock", "name": "Phone dock", "key": "device_width",
     "values": [60, 65, 70, 75, 80, 85, 90, 95, 100, 105, 110, 115, 120], "start": 70, "tol": 0.08,
     "note": "From a small phone to a small tablet. The pocket, walls and thumb relief follow."},
    {"id": "enclosure", "project": "sensor-enclosure", "name": "Sensor enclosure", "key": "inner_h",
     "values": [26, 29, 32, 35, 38, 41, 44, 47, 50, 53, 56], "start": 29, "tol": 0.12,
     "note": "Base and lid as they print, side by side. Bosses, vents and ports are rebuilt each time."},
    {"id": "gears", "project": "gear-pair", "name": "Gear pair", "key": "teeth_b",
     "values": [18, 21, 24, 27, 30, 33, 36, 39, 42], "start": 30, "tol": 0.2,
     "note": "Involute teeth from the kernel. The peg spacing follows the centre distance."},
    {"id": "box", "project": "hinged-box", "name": "Hinged box", "key": "inner_w",
     "values": [40, 45, 50, 55, 60, 65, 70, 75], "start": 60, "tol": 0.08,
     "note": "Box and lid as they print. The hinge knuckles are re-divided along the new width."},
]


def _f32(b64: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(b64), dtype=np.float32)


def _u32(b64: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(b64), dtype=np.uint32)


def build(s: Studio, p: dict, key: str, value: float, tol: float) -> dict:
    vals = {**s.rev(p)["values"], key: float(value)}
    k = "site-" + H(s.rid(p), vals, tol)
    return s._k("view", key=k, recipe_id=s.rid(p), values=vals, tol=tol, p=p)


def merged(view: dict):
    P, T, off = [], [], 0
    for m in view["mesh"]:
        pos = _f32(m["positions"]).reshape(-1, 3)
        idx = _u32(m["indices"]).reshape(-1, 3)
        P.append(pos)
        T.append(idx + off)
        off += len(pos)
    E = _f32(view["edges"]).reshape(-1, 3)
    return np.concatenate(P), np.concatenate(T), E


def main() -> int:
    s = Studio(config.load())
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"kernel": None, "parts": []}
    try:
        for sw in SWEEPS:
            p = s.load(sw["project"])
            spec = s.recipe(p).spec(sw["key"])
            built = []
            for v in sw["values"]:
                view = build(s, p, sw["key"], v, sw["tol"])
                built.append((v, view, *merged(view)))
                manifest["kernel"] = view["kernel"]
            lo = np.min([b[2].min(axis=0) for b in built], axis=0)
            hi = np.max([b[2].max(axis=0) for b in built], axis=0)
            span = np.maximum(hi - lo, 1e-6)
            q = lambda a: np.round((a - lo) / span * 65535).astype("<u2")
            blob, steps = bytearray(), []
            for v, view, P, T, E in built:
                wide = len(P) > 65535
                st = {"value": v, "v": [len(blob), len(P)]}
                blob += q(P).tobytes()
                st["i"] = [len(blob), int(T.size), 4 if wide else 2]
                blob += T.astype("<u4" if wide else "<u2").tobytes()
                if len(blob) % 2:
                    blob += b"\0"
                st["e"] = [len(blob), len(E) // 2]
                blob += q(E).tobytes()
                bb = view["bbox"]
                st["size"] = [round(bb[1][i] - bb[0][i], 2) for i in range(3)]
                st["bbox"] = [[round(x, 3) for x in bb[0]], [round(x, 3) for x in bb[1]]]
                st["volume_cm3"] = round(view["volume_mm3"] / 1000, 2)
                st["faces"] = view["faces"]
                st["build_ms"] = round(view["timing"]["build_s"] * 1000)
                steps.append(st)
                print(f"{sw['id']:10s} {sw['key']}={v:<6} {st['size']} {st['volume_cm3']} cm3  {len(P)} v  {st['build_ms']} ms")
            (OUT / f"{sw['id']}.bin").write_bytes(bytes(blob))
            manifest["parts"].append({
                "id": sw["id"], "name": sw["name"], "recipe": s.rid(p), "note": sw["note"],
                "param": {"key": sw["key"], "label": spec.label, "unit": spec.unit},
                "start": sw["values"].index(sw["start"]),
                "lo": [round(float(x), 4) for x in lo], "hi": [round(float(x), 4) for x in hi],
                "bin": f"{sw['id']}.bin", "bytes": len(blob), "steps": steps,
            })
    finally:
        s.kernel.stop()
    (OUT / "parts.json").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
