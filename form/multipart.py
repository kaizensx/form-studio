"""One design, several parts: the parts of one product live in one project, not in one project each.

A multi-part design is ordinary design code (one Recipe subclass, built by the kernel like any other) that carries
each part's own code verbatim in `PARTS` and runs each in its own module namespace, so two parts may use the same
names. Its parameters and features are the parts' own, prefixed with the part id (`base__fillet1_r`); its result is
every part's solid, in the positions their code puts them; `assembly()` names the parts when each one has a point
known to lie inside it (a reconstructed mesh gives one), and otherwise Form Studio shows them as separate bodies.

Used by:
- `reconstruct_parts`: several meshes of one product ("make this editable" with three STLs) become one design with one
  part per mesh. Each mesh goes through the same reconstruction as a single one (form/recon, in the kernel); a part
  whose feature tree verifies keeps it, the others keep their verified solid.
- `add_part`: create_design(relation="part_of") adds the new code as a part of the design in front.

Engine side: no OCCT here. The kernel builds the combined code and refuses it with the usual errors.
"""
from __future__ import annotations

import ast
import re
import shutil
import tempfile
import time
from pathlib import Path

MARK = "# form-multipart/1"
ID_RE = re.compile(r"[a-z][a-z0-9_]{0,30}")

TEMPLATE = '''"""{title}: {n} parts in one design. Form Studio.

{summary}
Each part's code is kept below as it was written and runs in its own namespace. Its parameters and features appear
here with the part id in front (base__fillet1_r). Edit a part by changing its code in PARTS.
"""
{mark}
import types as _types
from dataclasses import replace as _replace

from build123d import Compound

from form.recipes.base import Assembly, Feature, Part, Recipe, RecipeError, Stage

TITLE = {title!r}
PARTS = {parts}


def _load(i, part):
    name = "%s_part%d_%s" % (__name__, i, part["id"])
    mod = _types.ModuleType(name)
    exec(compile(part["source"], "<part %s>" % part["id"], "exec"), mod.__dict__)
    found = [v for v in vars(mod).values() if isinstance(v, type) and issubclass(v, Recipe) and v is not Recipe
             and v.__module__ == name]
    if len(found) != 1:
        raise RecipeError("Part %s must define exactly one Recipe subclass; found %d." % (part["id"], len(found)),
                          "", "Define `class Design(Recipe): ...` once in the part's code.")
    return found[0]()


_RECIPES = [_load(i, p) for i, p in enumerate(PARTS)]


def _k(pid, key):
    return pid + "__" + key if key else ""


class Design(Recipe):
    title = TITLE
    summary = {summary!r}
    params = [_replace(q, key=_k(p["id"], q.key), feature=_k(p["id"], q.feature), label=p["label"] + ": " + q.label)
              for p, r in zip(PARTS, _RECIPES) for q in r.params]
    features = [Feature(_k(p["id"], f.id), p["label"] + ": " + f.label, f.role, f.doc)
                for p, r in zip(PARTS, _RECIPES) for f in r.features]
    solids = sum(int(getattr(r, "solids", 1) or 1) for r in _RECIPES)

    def _sub(self, p, r, v):
        return {{q.key: v[_k(p["id"], q.key)] for q in r.params if _k(p["id"], q.key) in v}}

    def constraints(self, v):
        out = []
        for p, r in zip(PARTS, _RECIPES):
            sv = self._sub(p, r, v)
            if len(sv) == len(r.params):
                out += r.constraints(sv)
        return out

    def build(self, v):
        done, stages = [], []
        for p, r in zip(PARTS, _RECIPES):
            sub = r.build(self._sub(p, r, v))
            for s in sub:
                stages.append(Stage(_k(p["id"], s.feature), Compound(done + [s.shape]) if done else s.shape))
            done.append(sub[-1].shape)
        return stages

    def assembly(self, v):
        if not all(p.get("point") for p in PARTS) or any(int(getattr(r, "solids", 1) or 1) != 1 for r in _RECIPES):
            return None
        return Assembly(parts=[Part(p["id"], p["label"], tuple(p["point"]), note=p.get("note", ""))
                               for p in PARTS])
'''


def part_id(label: str, taken: set, common: int = 0) -> str:
    """A short id for a part from its label, unique among `taken`. common: how many leading words all the labels
    share, left out ("Sliding wallet V1_Base" among "… V1_Slider" -> "base"; "Lid" -> "lid")."""
    words = re.findall(r"[a-z0-9]+", str(label or "").lower())
    words = words[common:] or words[-1:]
    base = "_".join(words)[:24].strip("_") or "part"
    if not base[0].isalpha():
        base = "p" + base
    pid, i = base, 2
    while pid in taken:
        pid, i = f"{base}{i}", i + 1
    return pid


def combine(title: str, parts: list[dict], summary: str = "") -> str:
    """Design code for one design made of `parts`: [{"id", "label", "source", "point": [x, y, z] | None, "note"}]."""
    if not parts:
        raise ValueError("A multi-part design needs at least one part.")
    ids = [p["id"] for p in parts]
    if len(set(ids)) != len(ids) or not all(ID_RE.fullmatch(i) for i in ids):
        raise ValueError(f"Part ids must be unique short names (a-z, 0-9, _): {ids}")
    clean = [{"id": p["id"], "label": str(p.get("label") or p["id"])[:60], "source": str(p["source"]),
              "point": [round(float(c), 4) for c in p["point"]] if p.get("point") else None,
              "note": str(p.get("note") or "")[:200]} for p in parts]
    body = "[\n" + "".join(f"    {c!r},\n" for c in clean) + "]"
    return TEMPLATE.format(title=str(title)[:80], n=len(parts), mark=MARK, parts=body,
                           summary=(summary or f"{len(parts)} parts: " + ", ".join(c["label"] for c in clean) + ".")[:1500])


def split(source: str) -> list[dict] | None:
    """The parts of a multi-part design's code, or None when it is not one."""
    if MARK not in (source or ""):
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PARTS" for t in node.targets):
            try:
                parts = ast.literal_eval(node.value)
            except ValueError:
                return None
            return parts if isinstance(parts, list) else None
    return None


def add_part(st, project: str, name: str, source: str, values: dict | None = None, origin: str = "agent",
             expect_head: int | None = None) -> dict:
    """create_design(relation="part_of"): the new code becomes one more part of `project`, as a new revision.
    A design that is not yet multi-part becomes part one of the combined design; its values carry over under the
    part's prefix."""
    from .recipes import is_source
    from .studio import StudioError
    p = st.load(project)
    rid = st.rid(p)
    cur = st.source_text(p)
    if not is_source(rid) or rid.startswith("scad-") or cur is None:
        raise StudioError("Only a design written as Python code can take another part.",
                          "Use relation=\"alternative\" (a separate design in the same family) or \"new\".")
    parts = split(cur)
    head_vals = dict(st.rev(p)["values"])
    if parts is None:
        first = part_id(p["name"], set())
        parts = [{"id": first, "label": p["name"], "source": cur, "point": None}]
        keep = {f"{first}__{k}": v for k, v in head_vals.items()}
    else:
        keep = head_vals
    new = part_id(name, {q["id"] for q in parts})
    parts.append({"id": new, "label": str(name or new)[:60], "source": source, "point": None})
    vals = {**keep, **{f"{new}__{k}": float(v) for k, v in (values or {}).items()}}
    code = combine(p["name"], parts)
    out = st.update_design(p, code, f"Added part “{name}”", vals, origin, expect_head, "python")
    _remember(st, out["id"], parts)
    return {"project": out["id"], "head": out["head"], "part": new, "parts": [q["id"] for q in parts]}


def _remember(st, pid: str, parts: list[dict], extra: dict | None = None) -> None:
    with st.lock(pid):
        p = st.load(pid)
        p["multipart"] = {"parts": [{"id": q["id"], "label": q.get("label") or q["id"]} for q in parts], **(extra or {})}
        st.save(p)


# ---- several meshes of one product -> one design with one part per mesh -------------------------------------------

def interior_point(path: Path, depth: float = 0.02) -> list[float] | None:
    """A point just inside the mesh: the middle of its largest triangle, `depth` mm in along the inward normal
    (orientation from the signed volume). Names the part in assembly(); None when the mesh cannot be read."""
    try:
        import numpy as np
        from .recon.mesh import read_triangles
        T, _ = read_triangles(Path(path))
    except Exception:
        return None
    if not len(T):
        return None
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    vol = float(np.einsum("ij,ij->i", T[:, 0], np.cross(T[:, 1], T[:, 2])).sum()) / 6.0
    a = np.linalg.norm(n, axis=1)
    i = int(np.argmax(a))
    if a[i] <= 0:
        return None
    out = n[i] / a[i] * (1.0 if vol >= 0 else -1.0)
    c = T[i].mean(axis=0) - out * depth
    return [float(x) for x in c]


def reconstruct_parts(st, srcs: list, name: str | None = None, tolerance: float = 0.02, layer: int = 2,
                      purpose: str | None = None, budget_s: float = 240.0, on_progress=None,
                      labels: list[str] | None = None) -> dict:
    """Several meshes of one product as ONE design with one part per mesh, in the positions the files give.

    Each mesh is reconstructed exactly as `reconstruct` does it for one (the kernel's "reconstruct" op, form/recon).
    A part whose Layer 2 feature tree verifies keeps its parameters; the others keep their verified solid (Layer 1 or
    0) as a reference the part's code reads. A part that cannot be reconstructed at all is reported in "failed" and
    the others go on. Every mesh is imported as a reference part, for comparison in the viewport.
    Returns {"project", "name", "parts": [{"id", "label", "from", "summary"}], "failed", "folder"}."""
    from .recon import project as recon
    from .recon.mesh import FORMATS
    from .studio import StudioError
    paths = [Path(s).expanduser() for s in srcs]
    if len(paths) < 2:
        raise StudioError("Give two or more meshes for a multi-part design.", "For one mesh, use reconstruct with that file.")
    if len(paths) > 12:
        raise StudioError("At most 12 meshes go into one design.")
    for s in paths:
        if not s.is_file():
            raise StudioError(f"File not found: {s}", "Give the absolute path of each STL, OBJ or 3MF file.")
        if s.suffix.lower() not in FORMATS:
            raise StudioError(f"{s.name} is not a mesh Form Studio reads.", "Use STL (binary or ASCII), OBJ or 3MF files.")
    if not (0.0005 <= float(tolerance) <= 5):
        raise StudioError("The tolerance must be between 0.0005 and 5 mm.")
    if int(layer) not in (0, 1, 2):
        raise StudioError("The layer must be 0, 1 or 2.")
    labels = list(labels or [])
    names = [(labels[i] if i < len(labels) and labels[i] else re.sub(r"^[0-9a-f]{6}-", "", s.stem)).strip()
             for i, s in enumerate(paths)]
    common = _common_name(names)
    n_common = len(re.findall(r"[a-z0-9]+", common.lower()))
    taken: set = set()
    plan = []
    for label, s in zip(names, paths):
        pid = part_id(label, taken, n_common)
        taken.add(pid)
        short = " ".join(re.split(r"[\s_\-]+", label)[n_common:]) or label
        plan.append({"id": pid, "label": short.replace("_", " ").strip()[:60] or pid, "src": s})
    title = (name or common or "Parts").strip()[:80]
    (st.root / ".recon").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="recon-parts-", dir=st.root / ".recon"))
    t0 = time.time()
    try:
        built, failed = [], []
        for k, q in enumerate(plan):
            def prog(d, q=q, k=k):
                if on_progress:
                    on_progress({"fraction": (k + float(d.get("fraction", 0))) / len(plan),
                                 "text": f"{q['label']}: {d.get('text', '')}".strip(), "part": q["id"]})
            st.activity(None, "reconstruct", f"{q['label']}: reconstructing (part {k + 1} of {len(plan)})", by="engine",
                        part=q["id"])
            sub = work / q["id"]
            sub.mkdir()
            try:
                rep = st._k("reconstruct", timeout=float(budget_s) * 1.5 + 120, on_progress=prog,
                            path=str(q["src"].resolve()), out_dir=str(sub), name=q["id"], tolerance=float(tolerance),
                            layer=int(layer), budget_s=float(budget_s))
            except StudioError as e:
                failed.append({"part": q["id"], "label": q["label"], "from": q["src"].name, "error": str(e)})
                continue
            res = rep.get("result")
            if not res:
                failed.append({"part": q["id"], "label": q["label"], "from": q["src"].name,
                               "error": rep.get("error") or "The mesh could not be reconstructed."})
                continue
            summ = recon.summary(rep)
            if res.get("recipe_verified"):
                code = (sub / res["recipe"]).read_text(encoding="utf-8")
                refs = [sub / r for r in res.get("recipe_references") or []]
            else:
                code = recon.WRAPPER.format(title=q["label"], file=q["src"].name, layer=res["layer"], step=res["step"],
                                            summary=f"Part {q['label']} of {title}, reconstructed from {q['src'].name}.")
                refs = [sub / res["step"]]
            built.append({**q, "code": code, "refs": refs, "summary": summ, "rep": rep, "dir": sub,
                          "point": interior_point(q["src"])})
            st.activity(None, "reconstruct", f"{q['label']}: {res.get('editable_pct') or 0:g}% editable, "
                        f"{res['hausdorff_mm']:.3g} mm from the mesh (Layer {res['layer']}, computed)", by="engine",
                        part=q["id"])
        if not built:
            raise StudioError("None of the meshes could be reconstructed.",
                              "; ".join(f"{f['label']}: {f['error']}" for f in failed)[:1500], failed=failed)
        parts = [{"id": b["id"], "label": b["label"], "source": b["code"], "point": b["point"]} for b in built]
        lines = [f"{b['label']} (from {b['src'].name}): {b['summary'].get('editable_pct') or 0:g}% editable, "
                 f"{b['summary']['hausdorff_mm']:.4g} mm from the mesh"
                 + (f" ({b['summary']['dimension_params']} dimensions that move; "
                    f"{b['summary'].get('feature_area_pct') or 0:g}% of the surface from parametric features)"
                    if b["summary"].get("recipe_verified") and b["summary"].get("dimension_params") is not None else "")
                 + f", Layer {b['summary']['layer']}" for b in built]
        brief = (f"Reconstructed from {len(built)} meshes as one design with {len(built)} parts (computed): "
                 + "; ".join(lines) + "." + (f" Not reconstructed: {', '.join(f['label'] for f in failed)}." if failed else ""))
        refs = [str(r) for b in built for r in b["refs"]]
        try:
            p = st.create_design(title, combine(title, parts, brief), brief=brief, purpose=purpose, references=refs or None)
        except StudioError as first:
            # a feature tree that verified alone can still fail next to the others: fall back to the verified solids
            parts2, refs2 = [], []
            for b in built:
                res = b["rep"]["result"]
                step = res.get("step")
                if not step:
                    raise first
                parts2.append({"id": b["id"], "label": b["label"], "point": b["point"],
                               "source": recon.WRAPPER.format(title=b["label"], file=b["src"].name, layer=res["layer"],
                                                              step=step, summary=f"Part {b['label']} of {title}.")})
                refs2.append(str(b["dir"] / step))
            p = st.create_design(title, combine(title, parts2, brief), brief=brief, purpose=purpose, references=refs2)
        keep = st.dir(p["id"]) / "reconstruction"
        keep.mkdir(parents=True, exist_ok=True)
        out_parts = []
        for b in built:
            files = []
            dest = keep / b["id"]
            dest.mkdir(exist_ok=True)
            for f in sorted(b["dir"].iterdir()):
                if f.is_file():
                    shutil.copyfile(f, dest / f.name)
                    files.append(f.name)
            try:
                st.import_reference(p, b["src"], b["src"].name)
            except StudioError:
                pass
            out_parts.append({"id": b["id"], "label": b["label"], "from": b["src"].name, "summary": b["summary"],
                              "files": files})
        with st.lock(p["id"]):
            p = st.load(p["id"])
            p["reconstruction"] = {"from": [b["src"].name for b in built], "ts": time.time(), "parts": out_parts,
                                   "failed": failed, "seconds": round(time.time() - t0, 1)}
            p["multipart"] = {"parts": [{"id": b["id"], "label": b["label"]} for b in built]}
            st.decide(p, "reconstruct", brief)
            st.save(p)
        st.activity(p["id"], "reconstruct", brief[:400], by="engine")
        return {"project": p["id"], "name": p["name"], "parts": out_parts, "failed": failed, "folder": str(keep),
                "seconds": round(time.time() - t0, 1)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _common_name(labels: list[str]) -> str:
    """"Sliding wallet V1 Base", "Sliding wallet V1 Slider" -> "Sliding wallet V1"."""
    words = [re.split(r"[\s_\-]+", x.strip()) for x in labels if x.strip()]
    if not words:
        return ""
    common = []
    for col in zip(*words):
        if all(w.lower() == col[0].lower() for w in col):
            common.append(col[0])
        else:
            break
    return " ".join(common).strip(" -_") or ""
