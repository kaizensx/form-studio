"""Cage data: the plain arrays a modelled mesh is kept as, and the preview meshes streamed while it is modelled.

A cage is points V (n, 3, millimetres), polygons F (lists of point indices, quads where the modelling kept quads),
creases ([a, b, sharpness 0..1] per creased edge) and named regions ({name: [face indices]}). It is data, never a
file Blender owns: a design keeps it in its source (literal() writes it as Python) and a FeatureDesign feature turns
it into geometry with form/craft/subd.py:

    from form import meshsource
    from form.craft import subd
    CAGE = meshsource.cage(V=[...], F=[...], creases=[...], regions={...})
    ...
    @feature("Body")
    def body(self, v):
        return subd.Cage(CAGE.V, CAGE.F).solid(label="body")

The interface is deliberately plain arrays, creases and region labels, so it does not depend on how subd.Cage grows
(creases and regions are passed on when subd.Cage accepts them; see to_subd()).

Plain numpy, no OCCT and no Blender: the engine, the MCP server and tests import it freely.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

HASH_DECIMALS = 5            # a cage hash rounds points to 1e-5 mm: replays that agree to that are the same cage
STAGE_MAGIC = b"FMS1"
REGION_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")


@dataclass
class CageData:
    V: np.ndarray
    F: list
    creases: list = field(default_factory=list)       # [[a, b, sharpness], ...]
    regions: dict = field(default_factory=dict)       # {name: [face index, ...]}
    # optional: the bake source when ops were tagged high_only (model_mesh): the whole high-poly cage (this cage plus
    # the detail that goes only into the baked maps, never into the LODs). None for every cage without such ops.
    high: "CageData | None" = None

    def __post_init__(self):
        # points are kept to 1e-6 mm, so a cage saved, written into source and read back hashes the same
        self.V = np.round(np.asarray(self.V, dtype=np.float64).reshape(-1, 3), 6) + 0.0
        self.F = [[int(i) for i in f] for f in self.F]
        self.creases = [[int(a), int(b), float(s)] for a, b, s in self.creases]
        self.regions = {str(k): sorted(int(i) for i in v) for k, v in (self.regions or {}).items()}
        if isinstance(self.high, dict):
            self.high = CageData.from_dict(self.high)

    # ---- identity ----
    def hash(self) -> str:
        """sha256 of the rounded points and the faces: two replays of one op list must give the same value."""
        return cage_hash(self.V, self.F)

    def full_hash(self) -> str:
        """hash() plus creases, regions and the high-poly cage (when there is one)."""
        h = hashlib.sha256(self.hash().encode())
        h.update(json.dumps([sorted(map(tuple, ((min(a, b), max(a, b), round(s, 6)) for a, b, s in self.creases))),
                             self.regions], sort_keys=True).encode())
        if self.high is not None:
            h.update(b"high" + self.high.full_hash().encode())
        return h.hexdigest()

    # ---- checks ----
    def is_quads(self) -> bool:
        return all(len(f) == 4 for f in self.F)

    def open_edges(self) -> int:
        """Edges with other than two faces (0 for a closed, manifold cage)."""
        count: dict = {}
        for f in self.F:
            for k in range(len(f)):
                a, b = f[k], f[(k + 1) % len(f)]
                e = (a, b) if a < b else (b, a)
                count[e] = count.get(e, 0) + 1
        return sum(1 for c in count.values() if c != 2)

    def summary(self) -> dict:
        lo, hi = (self.V.min(0), self.V.max(0)) if len(self.V) else (np.zeros(3), np.zeros(3))
        out = {"points": len(self.V), "faces": len(self.F), "quads": sum(len(f) == 4 for f in self.F),
               "open_edges": self.open_edges(), "creases": len(self.creases),
               "regions": {k: len(v) for k, v in self.regions.items()},
               "bbox_mm": [np.round(lo, 4).tolist(), np.round(hi, 4).tolist()], "hash": self.hash()}
        if self.high is not None:
            out["high"] = self.high.summary()
        return out

    # ---- conversion ----
    def to_dict(self) -> dict:
        d = {"V": self.V.tolist(), "F": self.F, "creases": self.creases, "regions": self.regions}
        if self.high is not None:
            d["high"] = self.high.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CageData":
        return cls(d["V"], d["F"], d.get("creases") or [], d.get("regions") or {}, d.get("high"))

    def save(self, path) -> Path:
        path = Path(path)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict()), encoding="utf-8")
        tmp.replace(path)
        return path

    @classmethod
    def load(cls, path) -> "CageData":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def literal(self, name: str = "CAGE") -> str:
        """Python source that rebuilds this cage, for a design's source (the design stays the geometry authority)."""
        d = self.to_dict()
        high = f",\n    high={json.dumps(d['high'])}" if "high" in d else ""
        return (f"{name} = meshsource.cage(\n    V={json.dumps(d['V'])},\n    F={json.dumps(d['F'])},\n"
                f"    creases={json.dumps(d['creases'])},\n    regions={json.dumps(d['regions'])}{high})\n")

    def to_subd(self, levels: int = 0):
        """A form.craft.subd.Cage of this cage (closed cages; non-quads get one Catmull-Clark step there). Creases and
        regions are passed when the installed subd.Cage takes them, and kept on the object as .creases/.regions."""
        import inspect

        from .craft import subd
        kw = {}
        sig = inspect.signature(subd.Cage.__init__).parameters
        if "creases" in sig:
            kw["creases"] = subd_creases(self.creases)
        if "regions" in sig:
            kw["regions"] = self.regions
        c = subd.Cage(self.V, self.F, levels=levels, **kw)
        if not kw:
            c.creases, c.regions = self.creases, self.regions
        elif not hasattr(c, "regions"):              # subd.Cage keeps them as region_names / face_region
            c.regions = self.regions
        return c


def subd_creases(creases) -> dict:
    """Blender's crease weights (0..1, per edge) as form.craft.subd sharpness: weight 1 is infinitely sharp (a C0
    border between exact patches); a weight w < 1 is the semi-sharp sharpness 10 w² that Blender's own OpenSubdiv
    evaluation uses, so the CAD limit surface follows the cage as Blender shows it. 0 is smooth (left out)."""
    out: dict = {}
    for a, b, w in creases or []:
        w = float(w)
        if w <= 0:
            continue
        k = (min(int(a), int(b)), max(int(a), int(b)))
        out[k] = max(out.get(k, 0.0), float("inf") if w >= 1.0 else 10.0 * w * w)
    return out


PACK_PREFIX = "zb64:"


def pack(obj) -> str:
    """Data as a compact, deterministic string literal: JSON (sorted keys, no spaces), zlib level 9, base64. The same
    data always packs to the same text, so a design source that holds it hashes the same way every time."""
    import base64
    import zlib
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    return PACK_PREFIX + base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def unpack(text):
    """pack()'s inverse; anything that is not a packed string comes back as it is."""
    if not (isinstance(text, str) and text.startswith(PACK_PREFIX)):
        return text
    import base64
    import zlib
    return json.loads(zlib.decompress(base64.b64decode(text[len(PACK_PREFIX):])).decode())


def cage_fields(kw: dict) -> dict:
    """A meshsource.cage(...) call's keyword values with packed ones unpacked: packed= (a dict of the fields) and any
    single field given as a packed string (V, F, creases, regions, high)."""
    out = dict(kw)
    pk = out.pop("packed", None)
    if pk is not None:
        d = unpack(pk)
        if not isinstance(d, dict):
            raise ValueError("packed= must hold a dict of cage fields")
        for k, v in d.items():
            if out.get(k) is None:
                out[k] = v
    return {k: unpack(v) for k, v in out.items()}


def cage(V=None, F=None, creases=None, regions=None, high=None, packed=None) -> CageData:
    """The cage a design's source holds (see literal()). high: the bake source ({V, F, creases, regions}) when the
    cage was modelled with high_only ops. Any field may be a pack() string, and packed= a pack() of a dict of fields:
    large cages stay under the design source limit and the call stays a literal (read with ast, never run)."""
    f = cage_fields({"V": V, "F": F, "creases": creases, "regions": regions, "high": high, "packed": packed})
    if f.get("V") is None or f.get("F") is None:
        raise ValueError("a cage needs V and F")
    return CageData(f["V"], f["F"], f.get("creases") or [], f.get("regions") or {}, f.get("high"))


def cage_hash(V, F, decimals: int = HASH_DECIMALS) -> str:
    v = np.round(np.asarray(V, dtype=np.float64), decimals) + 0.0      # + 0.0: -0.0 and 0.0 hash alike
    h = hashlib.sha256(np.ascontiguousarray(v).tobytes())
    h.update(json.dumps([[int(i) for i in f] for f in F]).encode())
    return h.hexdigest()


# ---- preview meshes (the FORM_STAGE files the Blender runner writes) ------------------------------------------------

def read_stage(path) -> tuple[int, np.ndarray, np.ndarray]:
    """(op index, positions (n, 3) float32, triangles (t, 3) uint32) from a stage file (format: blender_ops.py)."""
    data = Path(path).read_bytes()
    if data[:4] != STAGE_MAGIC or len(data) < 16:
        raise ValueError(f"{Path(path).name} is not a Form stage file")
    idx, n, t = struct.unpack_from("<III", data, 4)
    need = 16 + n * 12 + t * 12
    if len(data) != need:
        raise ValueError(f"{Path(path).name} has {len(data)} bytes, expected {need}")
    P = np.frombuffer(data, dtype="<f4", count=n * 3, offset=16).reshape(n, 3)
    T = np.frombuffer(data, dtype="<u4", count=t * 3, offset=16 + n * 12).reshape(t, 3)
    if t and int(T.max()) >= n:
        raise ValueError(f"{Path(path).name} indexes a point that does not exist")
    return idx, P, T


def stage_event(path, feature: str, label: str = "", of: int = 0) -> dict:
    """A stage file as the build stream's stage event: the dict form/kernel.py's _stage_out sends, so
    Studio._draft_sink(draft, name)(event) writes it to .cache/drafts/<draft>.json for /api/drafts and Store.showStage."""
    idx, P, T = read_stage(path)
    lo, hi = (P.min(0), P.max(0)) if len(P) else (np.zeros(3), np.zeros(3))
    return {"kind": "stage", "feature": feature, "index": idx + 1, "at": idx + 1, "of": max(of, idx + 1),
            "label": label, "positions": base64.b64encode(np.ascontiguousarray(P, dtype=np.float32).tobytes()).decode(),
            "indices": base64.b64encode(np.ascontiguousarray(T, dtype=np.uint32).tobytes()).decode(),
            "bbox": [[float(x) for x in lo], [float(x) for x in hi]], "triangles": int(len(T))}
