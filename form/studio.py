"""The studio: project state, the artifact graph, and the pipeline that fills it.

An artifact is *current* only if it exists under the key computed from the
head revision's inputs. Nothing is ever flagged stale by hand: change an input
and the expected key changes, so the old output simply stops matching.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path

from . import __version__, checks as checks_mod, fit as fit_mod, slicer
from . import cad_bridges
from .recipes import RecipeBook, RecipeError, SCAD_PREFIX, SOURCE_PREFIX, is_source, source_path, store_source
from .worker import Kernel, KernelFailure
from . import fsutil
from . import printers as printers_mod
from . import filaments as materials_mod, plates as plates_mod
from . import purpose as purpose_mod

NODES = ["geometry", "exports", "checks", "slice"]
STATICS_LABELS = {"tip_force_n": ("Tip-over force", "N"), "safety_factor": ("Bending safety factor", "x"),
                  "root_stress_mpa": ("Arm root stress", "MPa"), "upper_screw_pull_n": ("Upper screw load", "N")}
NODE_LABEL = {"geometry": "Solid", "exports": "STEP + STL", "checks": "Checks", "slice": "Slice"}
# what a Design only release does not contain or say, in the gate, the manifest and the report
NOT_COVERED = ["No slice: print time and filament are not estimated.", "No sliced 3MF or G-code in the release.",
               "No print simulation: supports, bridges and the first layer are not previewed."]
MODEL_ENVELOPE = [1e6, 1e6, 1e6]       # a 3D model is checked against no printer: nothing is too big
STL_TOL = 0.01
REF_FORMATS = (".step", ".stp", ".stl")
SCHEMA = "form-project/1"


try:
    import fcntl
except ImportError:           # Windows
    fcntl = None
try:
    import msvcrt
except ImportError:           # not Windows
    msvcrt = None


def _flock(fd: int, lock: bool) -> None:
    """Exclusive whole-file lock across processes: flock on POSIX, a one-byte region lock on Windows."""
    if fcntl:
        fcntl.flock(fd, fcntl.LOCK_EX if lock else fcntl.LOCK_UN)
    elif msvcrt:
        os.lseek(fd, 0, os.SEEK_SET)
        if lock:
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)      # retries for ~10 s, then raises
                    break
                except OSError:
                    continue
        else:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


class ProjectLock:
    """Re-entrant within a process, exclusive across processes.

    The bench, the MCP server and the CLI may all run at once against the same
    data folder; a project is only ever mutated by one of them at a time.
    """

    def __init__(self, path: Path):
        self.path, self._r, self._depth, self._fd = path, threading.RLock(), 0, None

    def __enter__(self):
        self._r.acquire()
        if self._depth == 0 and (fcntl or msvcrt):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
            _flock(self._fd, True)
        self._depth += 1
        return self

    def __exit__(self, *exc):
        self._depth -= 1
        if self._depth == 0 and self._fd is not None:
            _flock(self._fd, False)
            os.close(self._fd)
            self._fd = None
        self._r.release()


class StudioError(Exception):
    def __init__(self, message, hint="", status=400, **extra):
        super().__init__(message)
        self.hint, self.status, self.extra = hint, status, extra

    def public(self):
        return {"message": str(self), "hint": self.hint, **self.extra}


def H(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _slicer_tag(s: dict) -> list:
    """Artifact keys name the slicer kind, except Bambu Studio's, whose keys predate other slicers."""
    kind = s.get("kind", "bambu")
    return [] if kind == "bambu" else [kind]


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _initial_provenance(param) -> dict:
    """A design may declare where a default comes from (Param(..., provenance="specified", doc="Pi 5 drawing"))."""
    src = getattr(param, "provenance", "assumed")
    out = {"source": src if src in ("assumed", "specified", "measured", "calibrated", "photo") else "assumed"}
    if out["source"] != "assumed" and param.doc:
        out["note"] = param.doc[:200]
    return out


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    return s or "project"


EXAMPLES = Path(__file__).parent / "examples"


def list_examples(root: Path | None = None) -> list:
    """The example projects that ship with FORM: id, name, whether this data folder already has it."""
    out = []
    for f in sorted(EXAMPLES.glob("*.json")):
        try:
            name = json.loads(f.read_text(encoding="utf-8")).get("name", f.stem)
        except (OSError, ValueError):
            name = f.stem
        out.append({"id": f.stem, "name": name, "present": bool(root and (Path(root) / f.stem).exists())})
    return out


def add_examples(root: Path, ids=None) -> list:
    """Copy shipped examples into a data folder. Only on an explicit request: the New design sheet's
    "Open an example", `form examples add`, or POST /api/examples. Existing folders are never overwritten."""
    root = Path(root)
    known = {f.stem: f for f in sorted(EXAMPLES.glob("*.json"))}
    want = list(known) if not ids else list(ids)
    bad = [i for i in want if i not in known]
    if bad:
        raise StudioError(f"Unknown example “{bad[0]}”.", "Known: " + ", ".join(known))
    made = []
    for i in want:
        d = root / i
        if d.exists():
            continue
        (d / "artifacts").mkdir(parents=True)
        shutil.copyfile(known[i], d / "project.json")
        made.append(i)
    return made


class Studio:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.root = Path(cfg["data"]["dir"])
        self.root.mkdir(parents=True, exist_ok=True)
        self.sources = self.root / ".sources"
        os.environ["FORM_SOURCES"] = str(self.sources)       # the kernel worker inherits this and resolves src: ids
        if (cfg.get("cad") or {}).get("openscad"):
            os.environ["FORM_OPENSCAD"] = str(cfg["cad"]["openscad"])   # OpenSCAD designs build in the worker
        self.kernel = Kernel()
        self._tl = threading.local()                        # the pipeline step running on this thread (progress)
        self.recipes = RecipeBook(self.sources)
        self.calibration = fit_mod.Calibration(self.root / "calibration.json")
        self.jobs: dict = {}
        self._locks: dict = {}
        self._slicer = None
        self._slicer_at = 0.0
        self._choice_cache: dict = {}                 # printer choice -> (time, resolved), see printer_choice
        self._kernel_id = None
        self._recipe_sha: dict = {}
        self._layers_cache: dict = {}
        # A new data folder stays empty: nothing is created until the user asks (see add_examples).

    def seed_examples(self, ids=None) -> list:
        """Add shipped examples on request (design history only; outputs are rebuilt). Never called automatically."""
        return add_examples(self.root, ids)

    # ---- environment -----------------------------------------------------
    def slicer_info(self, refresh=False, p: dict | None = None, material: str | None = None) -> dict:
        """What a slice would use. With a project: its own printer choice, else the default printer, else the
        slicer's selection (form/printers.py); and when the design states a material (form/materials.py), that
        printer's filament preset for it. `material` asks for one material explicitly (a plate of one material)."""
        base = self._slicer_info(refresh, p)
        mat = materials_mod.normalise(material) if material else (materials_mod.stated(p) if isinstance(p, dict) else None)
        if not mat:
            return base
        return self._slicer_for_material(p, mat, refresh, base)

    def _slicer_for_material(self, p, mat: str, refresh: bool, base: dict) -> dict:
        choice, source = self.printer_choice(p)
        b = materials_mod.base_choice(choice, base)
        if b is None:                                   # nothing resolves: keep saying why
            return base
        c, note = materials_mod.choice_for(self.cfg, b, base, mat)
        if not note["changed"]:
            return {**base, "material": note}
        ck = json.dumps(c, sort_keys=True)
        hit = self._choice_cache.get(ck)
        if refresh or hit is None or time.time() - hit[0] > 20:
            hit = (time.time(), printers_mod.resolve(self.cfg, c))
            self._choice_cache[ck] = hit
        r = hit[1]
        if not r.get("available"):                      # that filament does not work with this printer and process
            return {**base, "material": dict(note, matched=False, changed=False, filament=b.get("filament") or "",
                                             text=f"{note['filament']} cannot be used here: {r.get('reason')}")}
        src = dict(base.get("source") or {})
        src["filament"] = f"the {materials_mod.MATERIALS[mat]['label']} set for this design"
        return {**r, "choice_source": base.get("choice_source", source or "slicer"), "source": src, "material": note}

    def _slicer_info(self, refresh=False, p: dict | None = None) -> dict:
        choice, source = self.printer_choice(p)
        if choice is not None:
            ck = json.dumps(choice, sort_keys=True)
            hit = self._choice_cache.get(ck)
            if refresh or hit is None or time.time() - hit[0] > 20:
                r = printers_mod.resolve(self.cfg, choice)
                hit = (time.time(), r)
                self._choice_cache[ck] = hit
            said = "this design's printer in Form Studio" if source == "project" else "the default printer in Form Studio"
            return {**hit[1], "choice_source": source, "source": {k: said for k in ("machine", "process", "filament")}}
        if refresh:
            self._choice_cache.clear()
        if refresh or self._slicer is None or time.time() - self._slicer_at > 20:
            self._slicer = slicer.resolve(self.cfg)
            self._slicer_at = time.time()
        return self._slicer

    # ---- the printer a design uses (form/printers.py) ----------------------
    def printer_choice(self, p: dict | None = None) -> tuple:
        """(choice, "project" | "default") or (None, "") when the slicer's own selection applies."""
        c = printers_mod.normalise(p.get("printer")) if isinstance(p, dict) else None
        if c is not None:
            return c, "project"
        c = printers_mod.default_choice(self.cfg)
        return (c, "default") if c is not None else (None, "")

    def printer_env(self, p: dict | None = None) -> dict:
        """Bed size, margin and printer name the checks use: the chosen printer's when there is a choice and its
        slicer states a bed, else [printer] in studio.toml (as before)."""
        pr = self.cfg["printer"]
        out = {"envelope": list(pr["envelope_mm"]), "margin": pr["plate_margin_mm"], "name": pr["name"], "source": "studio.toml"}
        choice, source = self.printer_choice(p)
        if choice is not None:
            s = self.slicer_info(p=p)
            if s.get("available") and s.get("envelope_mm"):
                out.update(envelope=[round(float(x), 3) for x in s["envelope_mm"]], name=choice["machine"], source=source)
        return out

    def printer_state(self, p: dict) -> dict:
        """The printer this design uses and where that choice comes from (project, default, slicer)."""
        choice, source = self.printer_choice(p)
        s = self.slicer_info(p=p)
        return {"choice": choice, "source": source or "slicer", "slicer": slicer.public(s), "env": self.printer_env(p)}

    # ---- Design only: slicing is optional (per design, for every design, or because no slicer is installed) ----
    def slice_mode(self, p: dict | None = None) -> dict:
        """{"on": bool, "why": "" | "purpose" | "settings" | "project" | "no_slicer", "text", "how"}."""
        if purpose_mod.is_model(p):
            return {"on": False, "why": "purpose", "text": "This design is a 3D model, not made for 3D printing, so it is not sliced.",
                    "how": "To print it, set its purpose to “For 3D printing” in the design's settings."}
        if not self.cfg["slicer"].get("enabled", True):
            return {"on": False, "why": "settings", "text": "Slicing is turned off for every design.",
                    "how": "Turn on Settings › Printer and slicer › Slice designs, or set [slicer].enabled = true in studio.toml."}
        if isinstance(p, dict) and p.get("design_only"):
            return {"on": False, "why": "project", "text": "This design is set to Design only.",
                    "how": "Turn slicing on for this design in Prove, or run `form design-only <project> off`."}
        s = self.slicer_info(p=p)
        app = s.get("app") or ""
        if not s.get("available") and not (app and (Path(app).is_file() or shutil.which(app))):
            return {"on": False, "why": "no_slicer", "text": "No slicer is installed, so designs are not sliced.",
                    "how": "Install Bambu Studio, OrcaSlicer or PrusaSlicer (Settings › Set up); slicing starts on its own."}
        return {"on": True, "why": "", "text": "", "how": ""}

    def set_part(self, pid: str, part: str, by: str = "you", **fields) -> dict:
        """Per-part print settings: orientation (named, "down:x,y,z" or "auto"), material, color. "" clears one."""
        from . import analysis
        part = str(part or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,60}", part):
            raise StudioError("Name the part by its id.", "Part ids are listed in the checks (`form plates <project>`).")
        with self.lock(pid):
            p = self.load(pid)
            parts = dict(p.get("parts") or {})
            cur = dict(parts.get(part) or {})
            said = []
            for k, v in fields.items():
                if k not in ("orientation", "material", "color") or v is None:
                    continue
                v = str(v).strip()
                if k == "orientation" and v and v != "auto" and not analysis.valid_orientation(v):
                    raise StudioError("Unknown orientation.", "Use auto, one of: " + ", ".join(analysis.NAMED) + ", or a “down:x,y,z” id.")
                if k == "material" and v and not materials_mod.normalise(v):
                    raise StudioError(f"Unknown material “{v}”.", "Known: " + ", ".join(materials_mod.MATERIALS) + ".")
                if k == "material" and v:
                    v = materials_mod.normalise(v)
                if k == "color" and v and not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
                    raise StudioError("A colour is #rrggbb.")
                if v:
                    cur[k] = v
                else:
                    cur.pop(k, None)
                said.append(f"{k} {v or 'cleared'}")
            if cur:
                parts[part] = cur
            else:
                parts.pop(part, None)
            p["parts"] = parts
            text = f"Part {part}: " + ", ".join(said) + "."
            self.decide(p, "part", text)
            self.save(p)
        self.activity(pid, "part", text, by=by)
        return {"project": pid, "part": part, "settings": parts.get(part, {})}

    def _plate_inputs(self, p: dict, recipe) -> dict:
        """Inputs of the plate plan and the material notes that are not at their defaults (they join the checks and
        slice keys only when set, so designs that use none of this keep their keys)."""
        from . import config as config_mod
        out = {}
        if p.get("material"):
            out["material"] = materials_mod.normalise(p["material"])
        # a colour is only how a part is shown: it changes neither the checks nor the slice
        own = {k: w for k, w in ((k, {kk: vv for kk, vv in v.items() if kk != "color"})
                                 for k, v in sorted((p.get("parts") or {}).items()) if isinstance(v, dict)) if w}
        if own:
            out["parts"] = own
        if getattr(recipe, "solids", 1) > 1:
            if plates_mod.spacing(self.cfg) != plates_mod.DEFAULT_SPACING_MM:
                out["spacing"] = plates_mod.spacing(self.cfg)
            if float(self.cfg["printer"].get("plate_margin_mm", 2.0)) != float(config_mod.DEFAULTS["printer"]["plate_margin_mm"]):
                out["margin"] = float(self.cfg["printer"]["plate_margin_mm"])
        if out.get("material") or any("material" in v for v in own.values()):
            out["brief"] = H(p["brief"].get("text", ""))           # the material notes read the brief
        return out

    def set_printer(self, pid: str, choice, by: str = "you") -> dict:
        """Use this printer (with its filament and process) for one design; None goes back to the default."""
        with self.lock(pid):
            p = self.load(pid)
            if choice is None:
                p.pop("printer", None)
                text = "Printer: back to the default."
            else:
                try:
                    c = printers_mod.validate(self.cfg, choice)
                except printers_mod.PrinterError as e:
                    raise StudioError(e.message, e.hint)
                p["printer"] = c
                text = "Printer: " + printers_mod.describe(c)
            self.decide(p, "printer", text)
            self.save(p)
        self.activity(pid, "printer", text, by=by)
        s = self.slicer_info(p=p)
        return {"project": pid, "printer": p.get("printer"), "source": self.printer_choice(p)[1] or "slicer",
                "slicer": slicer.public(s), "env": self.printer_env(p)}

    def kernel_id(self) -> str:
        if self._kernel_id is None:
            self._kernel_id = self.kernel.call("ping", timeout=120)["kernel"]
        return self._kernel_id

    def recipe_sha(self, rid: str) -> str:
        if rid not in self._recipe_sha:
            base = Path(__file__).parent / "recipes"
            h = hashlib.sha256()
            src = source_path(self.sources, rid) if is_source(rid) else base / f"{rid}.py"
            extra = (base / "scad.py", base / "meshsolid.py") if rid.startswith(SCAD_PREFIX) else \
                (base / "style.py",) if not is_source(rid) else ()      # the library's shared design helpers
            for f in (base / "base.py", src, *extra):
                h.update(f.read_bytes())
            self._recipe_sha[rid] = h.hexdigest()[:16]
        return self._recipe_sha[rid]

    def profile(self, p: dict | None = None) -> str:
        s = self.slicer_info(p=p)
        if not s.get("available"):
            return "unknown printer profile"
        p = s["presets"]
        return f"{p['machine']['name']} · {p['filament']['name']}"

    def environment(self) -> dict:
        s = self.slicer_info()
        return {"version": __version__, "kernel": self.kernel_id(), "slicer": slicer.public(s), "slicing": self.slice_mode(),
                "purpose": purpose_mod.catalogue(self.cfg),
                "printer": self.cfg["printer"], "profile": self.profile(),
                "models": {k: v for k, v in self.cfg["models"].items()},
                "config_path": self.cfg["_path"], "data_dir": str(self.root),
                "kernel_restarts": self.kernel.restarts, "kernel_last_failure": self.kernel.last_failure,
                "cad": cad_bridges.status(self.cfg)}

    # ---- project store ---------------------------------------------------
    def dir(self, pid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", pid or ""):
            raise StudioError("Unknown project.", status=404)
        return self.root / pid

    def lock(self, pid: str) -> ProjectLock:
        self.dir(pid)
        return self._locks.setdefault(pid, ProjectLock(self.root / ".locks" / f"{pid}.lock"))

    def list(self) -> list:
        out = []
        for d in sorted(self.root.iterdir()):
            if (d / "project.json").exists():
                try:
                    p = self.load(d.name)
                    out.append({"id": p["id"], "name": p["name"], "recipe": p["recipe"], "head": p["head"],
                                "revisions": len(p["revisions"]), "updated": p.get("updated", p["created"]),
                                "approved_rev": (p["approvals"][-1]["rev"] if p["approvals"] else None),
                                "purpose": purpose_mod.of(p)})
                except StudioError as e:
                    out.append({"id": d.name, "name": d.name, "error": str(e)})
        return out

    def load(self, pid: str) -> dict:
        path = self.dir(pid) / "project.json"
        if not path.exists() and not path.with_suffix(".json.bak").exists():
            raise StudioError("Unknown project.", status=404)
        recovered = None
        for cand in (path, path.with_suffix(".json.bak")):
            try:
                p = json.loads(cand.read_text(encoding="utf-8"))
                if p.get("schema") != SCHEMA:
                    raise ValueError("unsupported schema")
                if cand != path:
                    recovered = "project.json was unreadable; restored from the previous save."
                    path.write_text(json.dumps(p, indent=1), encoding="utf-8")
                p["_recovered"] = recovered
                self._complete(p)
                return p
            except (ValueError, OSError):
                continue
        raise StudioError("This project's state file and its backup are both unreadable.",
                          "Restore the project from an exported .formproj archive.", status=500)

    def _complete(self, p: dict) -> None:
        """Built-in recipes gain parameters between versions (marks, vent patterns). A revision saved before
        that gets the new parameter at its default, with provenance "assumed", so it can be edited like any other."""
        for r in p.get("revisions", []):
            rid = r.get("recipe") or p.get("recipe")
            if not isinstance(rid, str) or is_source(rid) or not dict.__contains__(self.recipes, rid):
                continue
            for q in self.recipes[rid].params:
                if q.key not in r["values"]:
                    r["values"][q.key] = float(q.default)
                    r.setdefault("provenance", {}).setdefault(q.key, _initial_provenance(q))

    # ---- marks: label text and revision stamp (form/marks.py) ---------------
    def mark_context(self, p: dict, rid: str, values: dict, n: int | None = None) -> dict | None:
        """What a design that carries marks needs to know for this build: the revision the geometry is for, the
        project's label text and the stamp hash. None unless one of the recipe's mark_params is switched on,
        so designs without marks keep the keys (and outputs) they always had."""
        try:
            keys = getattr(self.recipes[rid], "mark_params", ())
        except Exception:
            return None
        if not any(values.get(k) for k in keys):
            return None
        from . import marks
        if n is None:                               # the revision these values belong to; a draft is the next one
            same = lambda r: all(abs(float(values.get(k, v)) - v) < 1e-9 for k, v in r["values"].items()) and len(values) <= len(r["values"])
            cands = [self.rev(p)] + sorted(p["revisions"], key=lambda r: -r["n"])
            n = next((r["n"] for r in cands if (r.get("recipe") or p["recipe"]) == rid and same(r)),
                     max(r["n"] for r in p["revisions"]) + 1)
        full = {**self.recipes[rid].defaults(), **{k: float(v) for k, v in values.items()}}
        return {"rev": int(n), "text": marks.clean(p.get("mark_text") or p["name"]), "hash": marks.short_hash(rid, full)}

    def save(self, p: dict) -> None:
        p = {k: v for k, v in p.items() if not k.startswith("_")}
        p["updated"] = time.time()
        path = self.dir(p["id"]) / "project.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(p, indent=1), encoding="utf-8")
        if path.exists():
            try:
                json.loads(path.read_text(encoding="utf-8"))          # never back up a corrupt file over a good backup
                shutil.copyfile(path, path.with_suffix(".json.bak"))
            except ValueError:
                pass
        fsutil.replace(tmp, path)

    def rid(self, p: dict, n: int | None = None) -> str:
        """Recipe id a revision was built with (designs written as code change it per revision)."""
        return self.rev(p, n).get("recipe") or p["recipe"]

    def recipe(self, p: dict, n: int | None = None):
        return self.recipes[self.rid(p, n)]

    def _load_design(self, source: str, language: str = "python") -> str:
        if len(source) > 200_000:
            raise StudioError("Design source is larger than 200 kB.")
        if language not in ("python", "openscad"):
            raise StudioError(f"Unknown design language “{language}”.", "Use language=\"python\" (build123d) or \"openscad\".")
        if language == "openscad" and not cad_bridges.find_openscad(self.cfg):
            raise StudioError("OpenSCAD is not installed, so an OpenSCAD design cannot be built.",
                              "Install it from https://openscad.org/downloads.html (or set [cad].openscad in studio.toml), "
                              "or write the design in Python with build123d.", status=409)
        rid = store_source(self.sources, source, language)
        self.recipes.pop(rid, None)
        try:
            self.recipes[rid]
        except RecipeError as e:
            raise StudioError(str(e), e.hint, kind="source")
        return rid

    def _check_assembly(self, rid: str, values: dict) -> None:
        """Refuse a design whose assembly() declaration cannot be used (unknown parts, loops, two parents, ...),
        before it becomes a revision. Plain data: no kernel needed."""
        recipe = self.recipes[rid]
        if not self._declares_assembly(recipe):
            return
        try:
            spec = recipe.assembly(recipe.validate(values))
        except RecipeError:
            return                                     # the build reports parameter problems with their own hints
        except Exception as e:
            raise StudioError(f"assembly() raised {type(e).__name__}: {e}", "Fix assembly() in the design source.", kind="source")
        if spec is None:
            return
        probs = spec.validate(getattr(recipe, "solids", 1)) if hasattr(spec, "validate") else ["assembly() must return an Assembly."]
        if probs:
            raise StudioError("The assembly declaration cannot be used: " + " ".join(probs),
                              "Fix assembly() in the design source; design_guide (ASSEMBLIES) shows parts, attach, joints with "
                              "parent, and mates.", kind="source", problems=probs)

    def create_design(self, name: str, source: str, brief: str = "", values: dict | None = None,
                      language: str = "python", references: list | None = None, purpose: str | None = None,
                      process: str | None = None) -> dict:
        """A new project whose geometry is defined by source: Python (one Recipe subclass) or OpenSCAD.

        references: STEP/STL files to import first, so the design can call self.reference(name) on its first build.
        """
        rid = self._load_design(source, language)
        refs = {}
        for r in references or []:
            src = Path(r).expanduser()
            if not src.is_file() or src.suffix.lower() not in REF_FORMATS:
                raise StudioError(f"Not a STEP or STL file: {src}", "Give the absolute path of a .step, .stp or .stl file.")
            refs[self._ref_name(src.name)] = str(src.resolve())
        self._check_assembly(rid, {**self.recipes[rid].defaults(), **(values or {})})
        self._k("summary", key="pv-" + H(rid, values or {}), recipe_id=rid, refs=refs,
                values={**self.recipes[rid].defaults(), **(values or {})}, tol=0.1, timeout=180)   # must build before it is saved
        p = self.create(name, rid, brief, values, purpose=purpose, process=process)
        for path in refs.values():
            self.import_reference(p, Path(path))
        return self.load(p["id"])

    def update_design(self, p: dict, source: str, note: str = "", values: dict | None = None, origin: str = "agent",
                      expect_head: int | None = None, language: str | None = None) -> dict:
        """New revision with new source. Values for parameters that still exist carry over."""
        if language is None:                       # keep the project's language unless told otherwise
            language = "openscad" if self.rid(p).startswith(SCAD_PREFIX) else "python"
        rid = self._load_design(source, language)
        new = self.recipes[rid]
        with self.lock(p["id"]):
            p = self.load(p["id"])
            if expect_head is not None and p["head"] != expect_head:
                raise StudioError(f"The design moved on: head is r{p['head']}, not r{expect_head}.",
                                  "Read the project again, then re-apply your edit.", status=409, head=p["head"])
            head = self.rev(p)
            keep = {k: v for k, v in head["values"].items() if k in {q.key for q in new.params}}
            vals = {**new.defaults(), **keep, **{k: float(v) for k, v in (values or {}).items()}}
            vals = self._validate(rid, vals)
            self._check_assembly(rid, vals)
            self._k("summary", key="pv-" + H(rid, vals), recipe_id=rid, values=vals, tol=0.1, p=p, timeout=180)
            prov = {q.key: (head["provenance"][q.key] if q.key in head["provenance"] and q.key in keep
                            and head["provenance"][q.key].get("source") != "assumed" else _initial_provenance(q)) for q in new.params}
            n = max(r["n"] for r in p["revisions"]) + 1
            old_keys = set(head["values"])
            added = sorted(set(vals) - old_keys)
            removed = sorted(old_keys - set(vals))
            summ = "Design source changed" + (f"; new: {', '.join(added)}" if added else "") + (f"; removed: {', '.join(removed)}" if removed else "")
            p["revisions"].append({"n": n, "parent": head["n"], "ts": time.time(), "values": vals, "note": note.strip() or summ,
                                   "summary": summ, "origin": origin, "provenance": prov, "recipe": rid, "touched": []})
            p["head"], p["recipe"] = n, rid
            self.decide(p, "source", f"r{n}: {summ}.")
            self.save(p)
            return p

    # ---- live activity: what agents are doing, for the bench to follow ------------------------------
    def activity(self, pid: str | None, kind: str, text: str, by: str = "agent", **extra) -> dict:
        ev = {"ts": time.time(), "project": pid, "kind": kind, "text": text[:400], "by": by, **extra}
        f = self.root / ".activity.jsonl"
        try:
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, default=str) + "\n")
            if f.stat().st_size > 2_000_000:                 # keep it small
                lines = f.read_text(encoding="utf-8").splitlines()[-2000:]
                f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass
        return ev

    def activity_since(self, ts: float = 0, limit: int = 60) -> list:
        f = self.root / ".activity.jsonl"
        if not f.exists():
            return []
        out = []
        for line in f.read_text(encoding="utf-8").splitlines()[-400:]:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("ts", 0) > ts:
                out.append(ev)
        return out[-limit:]

    def source_text(self, p: dict, n: int | None = None) -> str | None:
        rid = self.rid(p, n)
        if not is_source(rid):
            f = Path(__file__).parent / "recipes" / f"{rid}.py"
        else:
            f = source_path(self.sources, rid)
        return f.read_text(encoding="utf-8") if f.exists() else None

    def _purpose_args(self, purpose, process) -> tuple[str, str]:
        pur = purpose_mod.normalise(purpose) if purpose not in (None, "") else purpose_mod.default(self.cfg)
        if pur is None:
            raise StudioError(f"Unknown purpose “{purpose}”.", "Use “print” (for 3D printing) or “model” (just a 3D model).")
        pr = purpose_mod.normalise_process(process) if process not in (None, "") else ""
        if pr is None:
            raise StudioError(f"Unknown process “{process}”.", "Known: " + ", ".join(k for k in purpose_mod.PROCESSES if k) + ".")
        return pur, (pr if pur == "model" else "")

    def create(self, name: str, recipe_id: str, brief: str = "", values: dict | None = None, purpose: str | None = None,
               process: str | None = None) -> dict:
        if recipe_id not in self.recipes:
            raise StudioError("Unknown recipe.")
        pur, proc = self._purpose_args(purpose, process)
        r = self.recipes[recipe_id]
        base = slugify(name)
        pid, i = base, 2
        while (self.root / pid).exists():
            pid, i = f"{base}-{i}", i + 1
        vals = {**r.defaults(), **(values or {})}
        self._validate(recipe_id, vals)
        (self.root / pid / "artifacts").mkdir(parents=True)
        now = time.time()
        p = {"schema": SCHEMA, "id": pid, "name": name.strip() or r.title, "recipe": recipe_id, "created": now,
             "brief": {"text": brief, "references": []},
             "fit": dict(zip(("gap_min", "gap_max"), (r.fit or {}).get("window", (0.10, 0.80)))),
             "orientation": "as_modelled", "auto_slice": True, "purpose": pur,
             "revisions": [{"n": 1, "parent": None, "ts": now, "values": vals, "recipe": recipe_id,
                            "note": "Starting point from recipe defaults" if not is_source(recipe_id) else "First version of the design",
                            "origin": "recipe", "provenance": {pp.key: _initial_provenance(pp) for pp in r.params}}],
             "head": 1, "produced": {n: [] for n in NODES}, "decisions": [], "evidence": [], "approvals": []}
        from . import presets                       # a brief filled in from a template carries its answers
        filled = presets.attach(self.root, brief)
        if filled:
            p["brief"].update(filled)
        if proc:
            p["process"] = proc
        if pur == "model":
            p["decisions"].append({"ts": now, "rev": 1, "kind": "purpose", "text": "Purpose: just a 3D model, not for 3D printing"
                                   + (f" ({purpose_mod.PROCESSES[proc]['label']})." if proc else ".")})
        self.save(p)
        return p

    def rev(self, p: dict, n: int | None = None) -> dict:
        n = p["head"] if n is None else n
        for r in p["revisions"]:
            if r["n"] == n:
                return r
        raise StudioError(f"Revision r{n} does not exist.", status=404)

    def decide(self, p: dict, kind: str, text: str, **extra) -> None:
        p["decisions"].append({"ts": time.time(), "rev": p["head"], "kind": kind, "text": text, **extra})
        p["decisions"] = p["decisions"][-300:]

    # ---- keys and status -------------------------------------------------
    def keys(self, p: dict, n: int | None = None) -> dict:
        r = self.rev(p, n)
        s = self.slicer_info(p=p)
        rid = self.rid(p, r["n"])
        recipe = self.recipes[rid]
        gk = H("geometry", rid, self.recipe_sha(rid), self.kernel_id(), r["values"])
        if self.uses_references(rid):                  # the design reads imported parts: their bytes are inputs too
            gk = H(gk, self._refs_fp(p))
        mc = self.mark_context(p, rid, r["values"], r["n"])
        if mc:                                         # label text and revision stamp are part of the solid
            gk = H(gk, "mark", mc)
        ek = H("exports", gk, p["orientation"], STL_TOL)
        fit_in = None
        if recipe.fit:
            fit_in = [p["fit"], self.calibration.fingerprint(self.profile(p)), r["provenance"].get(recipe.fit["mating"])]
        if purpose_mod.is_model(p):                    # a 3D model: no printer, nozzle or fit model enters its checks
            ck = H("checks", ek, "model", purpose_mod.process(p), checks_mod.CHECKS_VERSION)
        else:
            pe = self.printer_env(p)
            ck = H("checks", ek, pe["envelope"], pe["margin"],
                   s.get("nozzle_mm", 0.4), checks_mod.CHECKS_VERSION, fit_in)
        if self._declares_assembly(recipe):            # the assembly checks' method and time budget shape their results
            from .assembly import ASSEMBLY_VERSION
            ck = H(ck, "assembly", ASSEMBLY_VERSION, self.assembly_budget())
        fc = self._freecad()
        if fc and not getattr(recipe, "mesh", False):  # an installed FreeCAD adds a re-import check
            ck = H(ck, "freecad", fc)
        extra = self._plate_inputs(p, recipe)          # per-part orientation and material, plate spacing (form/plates.py)
        if extra:
            ck = H(ck, "plates", extra)
        from . import materials as appearance_mod      # a chosen material adds its notes (none chosen: key unchanged)
        mfp = appearance_mod.fingerprint(p) if not purpose_mod.is_model(p) else None
        if mfp:
            ck = H(ck, "material", mfp)
        presets = {k: v["sha"] for k, v in s.get("presets", {}).items()} if s.get("available") else None
        sk = H("slice", ek, presets, slicer.version(s["app"], s.get("kind", "bambu")) if s.get("available") else None,
               *_slicer_tag(s))
        if extra:
            sk = H(sk, "plates", plates_mod.PLATES_VERSION, {k: v for k, v in extra.items() if k != "brief"})
        return {"geometry": gk, "exports": ek, "checks": ck, "slice": sk}

    @staticmethod
    def _declares_assembly(recipe) -> bool:
        from .recipes.base import Recipe
        f = getattr(type(recipe), "assembly", None)
        return f is not None and f is not Recipe.assembly

    def assembly_budget(self) -> float:
        """Seconds the assembly checks may take ([assembly].budget_s; a design's Assembly(budget_s=...) wins)."""
        try:
            return float((self.cfg.get("assembly") or {}).get("budget_s", 45))
        except (TypeError, ValueError):
            return 45.0

    def _assembly_checks(self, p, rev, keys, step=None) -> list:
        """The assembly checks in their own kernel call, with their own budget. Never fails the checks step: a kernel
        timeout or crash becomes a WARN row saying what was not checked."""
        budget = self.assembly_budget()
        try:
            recipe = self.recipe(p)
            spec = recipe.assembly(rev["values"]) if self._declares_assembly(recipe) else None
            if spec is not None and getattr(spec, "budget_s", None):
                budget = float(spec.budget_s)
        except Exception:
            spec = None
        if spec is None:
            return []

        def prog(d):
            if step is not None:
                step["progress"] = {k: d.get(k) for k in ("phase", "label", "done", "total", "value", "joint")}
                step["progress"]["seconds"] = round(time.perf_counter() - t0, 1)
        t0 = time.perf_counter()
        try:
            r = self._k("assembly", key=keys["geometry"], recipe_id=self.rid(p), values=rev["values"], budget_s=budget,
                        p=p, timeout=budget + 180, on_progress=prog)
        except StudioError as e:
            return [{"id": "asm_budget", "label": "Assembly checks finished in their time budget", "status": "WARN",
                     "value": "not finished", "evidence": "computed", "frame": None, "partial": True,
                     "detail": f"The assembly checks did not finish: {e} Nothing about how the parts meet or move "
                               "was verified in this run; the other checks are unaffected."}]
        if step is not None:
            step.pop("progress", None)
        return r.get("checks") or []

    def apath(self, p: dict, node: str, key: str) -> Path:
        base = self.dir(p["id"]) / "artifacts" / node
        return base / key if node in ("exports", "slice") else base / f"{key}.json"

    def _failed(self, p, node, key) -> Path:
        return self.dir(p["id"]) / "artifacts" / node / f"{key}.failed.json"

    def read(self, p: dict, node: str, key: str):
        path = self.apath(p, node, key)
        meta = path / "meta.json" if node in ("exports", "slice") else path
        if meta.exists():
            try:
                return json.loads(meta.read_text(encoding="utf-8"))
            except ValueError:
                return None
        return None

    def status(self, p: dict) -> dict:
        keys = self.keys(p)
        out, upstream_ok = {}, True
        for node in NODES:
            key = keys[node]
            hist = p["produced"].get(node, [])
            data = self.read(p, node, key)
            fail = self._failed(p, node, key)
            if data is not None:
                st = "current"
            elif fail.exists():
                st = "failed"
            elif any(h["ok"] for h in hist):
                st = "stale"
            else:
                st = "missing"
            entry = {"state": st, "key": key, "label": NODE_LABEL[node], "blocked": not upstream_ok and st != "current"}
            if st == "failed":
                entry["error"] = json.loads(fail.read_text(encoding="utf-8"))
            if st == "stale":
                last = next(h for h in reversed(hist) if h["ok"])
                entry["last_rev"], entry["last_key"] = last["rev"], last["key"]
            if st == "current":
                made = next((h for h in reversed(hist) if h["key"] == key), None)
                entry["made"] = made["ts"] if made else None
            out[node] = entry
            upstream_ok = upstream_ok and st == "current"
        mode = self.slice_mode(p)
        if not mode["on"]:                             # Design only: the slice is not part of this design's outputs
            out["slice"] = {"state": "off", "key": keys["slice"], "label": NODE_LABEL["slice"], "blocked": False, "off": mode}
        elif not self.slicer_info(p=p).get("available"):
            out["slice"]["unavailable"] = self.slicer_info(p=p).get("reason")
        return out

    def approval_state(self, p: dict, status: dict | None = None) -> dict:
        status = status or self.status(p)
        keys = {n: status[n]["key"] for n in NODES}
        last = p["approvals"][-1] if p["approvals"] else None
        if last and last["keys"] == keys:
            return {"state": "approved", "rev": last["rev"], "ts": last["ts"], "release": last["release"]}
        if last:
            changed = [NODE_LABEL[n] for n in NODES if last["keys"].get(n) != keys[n]]
            return {"state": "superseded", "rev": last["rev"], "ts": last["ts"], "release": last["release"],
                    "changed": changed}
        return {"state": "none"}

    # ---- kernel wrappers -------------------------------------------------
    def _validate(self, recipe_id, values):
        try:
            return self.recipes[recipe_id].validate(values)
        except Exception as e:
            pub = e.public() if hasattr(e, "public") else {"message": str(e)}
            raise StudioError(pub["message"], pub.get("hint", ""), feature=pub.get("feature"), params=pub.get("params", []), kind="recipe")

    def _k(self, op, timeout=60, p=None, refs=None, rev=None, **kw):
        """One kernel call. With p (the project), a design that reads imported parts gets their paths, and a
        design with marks gets the label text and the revision (rev, or the one the values belong to)."""
        if p is not None and kw.get("recipe_id"):
            vals = kw.get("values") if kw.get("values") is not None else kw.get("base")
            mc = self.mark_context(p, kw["recipe_id"], vals, rev) if isinstance(vals, dict) else None
            if mc and "key" in kw:
                kw["key"] = f"{kw['key']}-{H(mc)}"
            nz = self.slicer_info(p=p).get("nozzle_mm")
            ctx = {**(mc or {}), **({"nozzle": nz} if nz else {})}
            if ctx:
                kw["_mark"] = ctx
        if refs is None and p is not None and self.uses_references(kw.get("recipe_id", "")):
            refs = self.reference_paths(p)
        if refs:
            kw["_refs"] = refs
            if "key" in kw:
                kw["key"] = f"{kw['key']}-{H(sorted((k, sha_file(Path(v))) for k, v in refs.items()))}"
        try:
            return self.kernel.call(op, timeout=timeout, **kw)
        except KernelFailure as e:
            i = e.info
            raise StudioError(i.get("message", "Kernel failure"), i.get("hint", ""), status=422 if i.get("kind") == "recipe" else 500,
                              feature=i.get("feature"), params=i.get("params", []), kind=i.get("kind"))

    def view(self, p: dict, n: int | None = None, tol=0.03) -> dict:
        r = self.rev(p, n)
        gk = self.keys(p, r["n"])["geometry"]
        v = self._k("view", key=gk, recipe_id=self.rid(p, r["n"]), values=r["values"], tol=tol, dock_mass_g=self._sliced_mass(p, r["n"]), p=p,
                    rev=r["n"])
        v["companions"] = (v.get("companions") or []) + self.reference_companions(p)
        return v

    def _sliced_mass(self, p, n=None):
        try:
            meta = self.read(p, "slice", self.keys(p, n)["slice"])
            return float(meta["filament_g"]) if meta and meta.get("filament_g") else None
        except StudioError:
            return None

    def fit(self, p: dict, values: dict | None = None, provenance: dict | None = None) -> dict | None:
        r = self.rev(p)
        recipe = self.recipe(p)
        corr = self.calibration.correction(self.profile(p))
        return fit_mod.analyse(recipe, values or r["values"], provenance or r["provenance"], p["fit"], corr)

    def preview(self, p: dict, values: dict) -> dict:
        """Uncommitted candidate: real geometry, plus what committing it would touch."""
        unknown = [k for k in values if k not in self.rev(p)["values"]]
        if unknown:
            raise StudioError("Unknown parameter(s): " + ", ".join(unknown) + ".", "List valid keys with describe_recipe (MCP) or `form recipe <id>` (CLI).")
        vals = {**self.rev(p)["values"], **{k: float(v) for k, v in values.items()}}
        key = "pv-" + H(self.rid(p), vals)
        t0 = time.perf_counter()
        v = self._k("view", key=key, recipe_id=self.rid(p), values=vals, tol=0.06, p=p)
        v["companions"] = (v.get("companions") or []) + self.reference_companions(p)
        v["impact"] = self.impact(p, vals, v)
        v["fit"] = self.fit(p, v["values"])
        v["round_trip_s"] = round(time.perf_counter() - t0, 4)
        return v

    def head_summary(self, p: dict, n=None) -> dict:
        r = self.rev(p, n)
        gk = self.keys(p, r["n"])["geometry"]
        cached = self.read(p, "geometry", gk)
        return cached or self._k("summary", key=gk, recipe_id=self.rid(p, r["n"]), values=r["values"], p=p, rev=r["n"])

    def impact(self, p: dict, vals: dict, cand: dict, base_rev: int | None = None) -> dict:
        """What a change touches: parameters, features, interfaces, artifacts."""
        r = self.rev(p, base_rev)
        recipe = self.recipe(p)
        base = self.head_summary(p, r["n"])
        changed = [{"key": k, "label": recipe.spec(k).label, "unit": recipe.spec(k).unit, "from": r["values"][k], "to": vals[k],
                    "group": recipe.spec(k).group}
                   for k in r["values"] if abs(vals.get(k, r["values"][k]) - r["values"][k]) > 1e-9]
        feats = []
        labels = {f.id: f for f in recipe.features}
        for fid in labels:
            a, b = base["signature"].get(fid), cand["signature"].get(fid)
            if a != b:
                if a is None or b is None:
                    kind = "added" if a is None else "removed"
                else:
                    span = lambda s: [h - l for l, h in zip(s["lo"], s["hi"])]
                    same_size = all(abs(x - y) < 1e-3 for x, y in zip(span(a), span(b)))
                    same_place = a["lo"] == b["lo"] and a["hi"] == b["hi"]
                    same_area = abs(a["area"] - b["area"]) < 1e-3
                    kind = "moved" if (same_size and same_area and not same_place) else ("trimmed" if same_size and same_place else "resized")
                feats.append({"id": fid, "label": labels[fid].label, "role": labels[fid].role,
                              "change": kind,
                              "area_delta": (b["area"] if b else 0) - (a["area"] if a else 0)})
        bd = {d["key"]: d for d in base["derived"]}
        derived = [{"key": d["key"], "label": d["label"], "unit": d["unit"], "from": bd[d["key"]]["value"], "to": d["value"],
                    "interface": bool(d.get("interface"))}
                   for d in cand["derived"] if d["key"] in bd and abs(d["value"] - bd[d["key"]]["value"]) > 1e-6]
        metrics = [{"key": "volume", "label": "Material volume", "unit": "cm³", "from": base["volume_mm3"] / 1000, "to": cand["volume_mm3"] / 1000}]
        bs, cs = base.get("statics") or {}, cand.get("statics") or {}
        for k, (label, unit) in STATICS_LABELS.items():
            if isinstance(bs.get(k), (int, float)) and isinstance(cs.get(k), (int, float)):
                metrics.append({"key": k, "label": label, "unit": unit, "from": bs[k], "to": cs[k]})
        f0, f1 = self.fit(p, r["values"]), self.fit(p, cand["values"])
        if f0 and f1 and abs(f0["yield"] - f1["yield"]) > 1e-4:
            metrics.append({"key": "fit", "label": "Modelled fit yield", "unit": "%", "from": f0["yield"] * 100, "to": f1["yield"] * 100})
        geometry_changes = bool(feats) or any(c["group"] != "brief" or True for c in changed) and cand["signature"] != base["signature"]
        invalid = []
        if changed:
            invalid = [NODE_LABEL[n] for n in NODES]          # values enter the geometry key
        ap = self.approval_state(p)
        return {"params": changed, "features": feats, "derived": derived, "metrics": metrics,
                "interfaces_touched": [d["label"] for d in derived if d["interface"]],
                "geometry_changes": geometry_changes, "invalidates": invalid,
                "revokes_approval": bool(changed) and ap["state"] == "approved"}

    # ---- mutations -------------------------------------------------------
    def commit(self, p: dict, values: dict, note: str = "", origin: str = "user", provenance: dict | None = None,
               expect_head: int | None = None) -> dict:
        with self.lock(p["id"]):
            p = self.load(p["id"])                 # another process may have committed since p was read
            if expect_head is not None and p["head"] != expect_head:
                raise StudioError(f"The design moved on: head is r{p['head']}, not r{expect_head}.",
                                  "Read the project again, check what changed, then re-apply your edit.", status=409,
                                  head=p["head"])
            unknown = [k for k in values if k not in p["revisions"][0]["values"]]
            if unknown:
                raise StudioError("Unknown parameter(s): " + ", ".join(unknown) + ".", "List valid keys with describe_recipe (MCP) or `form recipe <id>` (CLI).")
            head = self.rev(p)
            vals = {**head["values"], **values}
            prov = {k: dict(v) for k, v in head["provenance"].items()}
            for k, v in (provenance or {}).items():
                if k in prov and isinstance(v, dict) and v.get("source") in fit_mod.SIGMA_BY_SOURCE:
                    prov[k] = {kk: v[kk] for kk in ("source", "sigma", "note", "instrument") if kk in v}
            if vals == head["values"] and prov == head["provenance"]:
                raise StudioError("Nothing changed.", "Edit a parameter or its provenance first.")
            key = "pv-" + H(self.rid(p), vals)
            cand = self._k("summary", key=key, recipe_id=self.rid(p), values=vals, tol=0.06, p=p)   # must build before it becomes a revision
            imp = self.impact(p, cand["values"], cand)
            n = max(r["n"] for r in p["revisions"]) + 1
            auto = ", ".join(f"{c['label']} {c['from']:g} → {c['to']:g} {c['unit']}" for c in imp["params"]) or "Provenance updated"
            p["revisions"].append({"n": n, "parent": head["n"], "ts": time.time(), "values": cand["values"], "recipe": self.rid(p), "note": note.strip() or auto,
                                   "summary": auto, "origin": origin, "provenance": prov,
                                   "touched": [f["id"] for f in imp["features"]]})
            p["head"] = n
            if imp["revokes_approval"]:
                self.decide(p, "approval", f"r{n} supersedes approved r{head['n']}; the release of r{head['n']} no longer describes the current design.")
            self.save(p)
            return p

    def checkout(self, p: dict, n: int) -> dict:
        with self.lock(p["id"]):
            p = self.load(p["id"])
            self.rev(p, n)
            if n != p["head"]:
                self.decide(p, "checkout", f"Switched head from r{p['head']} to r{n}.")
                p["head"] = n
                p["recipe"] = self.rid(p, n)
                self.save(p)
            return p

    def settings(self, p: dict, body: dict) -> dict:
        with self.lock(p["id"]):
            p = self.load(p["id"])
            if "orientation" in body:
                from . import analysis             # named orientations, or "down:x,y,z" from the orientation finder
                if not analysis.valid_orientation(body["orientation"]):
                    raise StudioError("Unknown orientation.", "Use one of: " + ", ".join(analysis.NAMED) + ", or a "
                                      "“down:x,y,z” id from suggest_orientation / `form orient`.")
                if body["orientation"] != p["orientation"]:
                    self.decide(p, "orientation", f"Print orientation set to “{analysis.orientation_label(body['orientation'])}”.")
                p["orientation"] = body["orientation"]
            if "fit" in body:
                lo, hi = float(body["fit"]["gap_min"]), float(body["fit"]["gap_max"])
                if not (-1 <= lo < hi <= 5):
                    raise StudioError("The acceptance window needs a minimum below its maximum.", "Typical sliding fits: 0.10–0.80 mm total gap.")
                p["fit"] = {"gap_min": lo, "gap_max": hi}
            if "auto_slice" in body:
                p["auto_slice"] = bool(body["auto_slice"])
            if "auto_run" in body:
                p["auto_run"] = bool(body["auto_run"])
            if "design_only" in body:
                on = bool(body["design_only"]) if not isinstance(body["design_only"], str) else \
                    body["design_only"].strip().lower() in ("1", "true", "yes", "on")
                if on != bool(p.get("design_only")):
                    self.decide(p, "design_only", "Design only: this design is not sliced." if on else "Slicing turned on for this design.")
                p["design_only"] = on
            if "purpose" in body or "process" in body:  # what the design is for (form/purpose.py)
                pur = purpose_mod.normalise(body["purpose"]) if "purpose" in body else purpose_mod.of(p)
                if pur is None:
                    raise StudioError(f"Unknown purpose “{body['purpose']}”.", "Use “print” (for 3D printing) or “model” (just a 3D model).")
                proc = purpose_mod.normalise_process(body["process"]) if "process" in body else purpose_mod.process(p)
                if proc is None:
                    raise StudioError(f"Unknown process “{body['process']}”.", "Known: " + ", ".join(k for k in purpose_mod.PROCESSES if k) + ".")
                proc = proc if pur == "model" else ""
                if pur != purpose_mod.of(p) or proc != purpose_mod.process(p):
                    self.decide(p, "purpose", "Purpose: for 3D printing." if pur == "print" else
                                "Purpose: just a 3D model, not for 3D printing"
                                + (f" ({purpose_mod.PROCESSES[proc]['label']})." if proc else "."))
                p["purpose"] = pur
                if proc:
                    p["process"] = proc
                else:
                    p.pop("process", None)
            if "material" in body:                     # the whole design's material (form/materials.py); "" clears it
                m = str(body["material"] or "").strip()
                if m and not materials_mod.normalise(m):
                    raise StudioError(f"Unknown material “{m}”.", "Known: " + ", ".join(materials_mod.MATERIALS) + ".")
                m = materials_mod.normalise(m) or ""
                if m != (p.get("material") or ""):
                    self.decide(p, "material", f"Material: {m}." if m else "Material: the selected filament.")
                if m:
                    p["material"] = m
                else:
                    p.pop("material", None)
            if "brief" in body:
                p["brief"]["text"] = str(body["brief"])[:8000]
            if "name" in body and str(body["name"]).strip():
                p["name"] = str(body["name"]).strip()[:80]
            if "mark_text" in body:                    # label text for designs with marks; empty = the project name
                from . import marks
                text = marks.clean(str(body["mark_text"] or ""))
                if text != (p.get("mark_text") or ""):
                    self.decide(p, "mark", f"Label text set to “{text or p['name']}”.")
                p["mark_text"] = text
            self.save(p)
            return p

    # ---- pipeline --------------------------------------------------------
    def _record(self, p, node, key, ok, error=None):
        p["produced"].setdefault(node, []).append({"key": key, "rev": p["head"], "ts": time.time(), "ok": ok})
        p["produced"][node] = p["produced"][node][-60:]
        fail = self._failed(p, node, key)
        fail.parent.mkdir(parents=True, exist_ok=True)
        if ok:
            fail.unlink(missing_ok=True)
        else:
            fail.write_text(json.dumps(error, indent=1), encoding="utf-8")

    def run(self, pid: str, nodes: list | None = None, force: bool = False) -> str:
        job = {"id": uuid.uuid4().hex[:10], "project": pid, "state": "running", "started": time.time(), "steps": []}
        self.jobs[job["id"]] = job
        if len(self.jobs) > 50:
            for k in list(self.jobs)[:-50]:
                self.jobs.pop(k, None)
        threading.Thread(target=self._run, args=(job, nodes, force), daemon=True).start()
        return job["id"]

    def run_sync(self, pid: str, nodes: list | None = None, force: bool = False) -> dict:
        job = {"id": "sync", "project": pid, "state": "running", "started": time.time(), "steps": []}
        self._run(job, nodes, force)
        return job

    def _run(self, job, nodes, force):
        pid = job["project"]
        with self.lock(pid):
            try:
                p = self.load(pid)
                want = [n for n in NODES if not nodes or n in nodes]
                if "slice" in want and not nodes and not p.get("auto_slice", True):
                    want.remove("slice")
                if "slice" in want and not self.slice_mode(p)["on"]:     # Design only: nothing to slice
                    want.remove("slice")
                job["steps"] = [{"node": n, "label": NODE_LABEL[n], "state": "queued"} for n in want]
                keys = self.keys(p)
                rev = self.rev(p)
                name = f"{p['id']}_r{rev['n']:02d}"
                blocked = False
                for step in job["steps"]:
                    node = step["node"]
                    key = keys[node]
                    idx = NODES.index(node)
                    missing_up = [u for u in NODES[:idx] if self.read(p, u, keys[u]) is None]
                    if blocked or missing_up:
                        step["state"] = "blocked"
                        step["error"] = {"message": f"Waiting on {NODE_LABEL[(missing_up or [NODES[idx-1]])[0]]}.",
                                         "hint": "Fix the step above, then run again."}
                        blocked = True
                        continue
                    if not force and self.read(p, node, key) is not None:
                        step["state"] = "cached"
                        continue
                    step["state"] = "running"
                    self._tl.step = step                         # long steps report progress on it
                    t0 = time.perf_counter()
                    try:
                        getattr(self, f"_make_{node}")(p, rev, keys, name)
                        self._record(p, node, key, True)
                        step["state"] = "done"
                    except slicer.SlicerBlocked as e:
                        step["state"], step["error"] = "blocked", {"message": str(e), "hint": "Geometry and checks are unaffected."}
                        blocked = True
                    except (StudioError, slicer.SlicerFailed) as e:
                        err = e.public() if isinstance(e, StudioError) else {"message": str(e), "hint": e.hint, "log": e.log}
                        self._record(p, node, key, False, err)
                        step["state"], step["error"] = "failed", err
                        blocked = True
                    except Exception as e:  # unexpected: record it, never lose the project
                        err = {"message": f"Unexpected {type(e).__name__}: {e}", "hint": "The project state is intact. Run again; if it repeats, export the project and report it."}
                        self._record(p, node, key, False, err)
                        step["state"], step["error"] = "failed", err
                        blocked = True
                    step["seconds"] = round(time.perf_counter() - t0, 3)
                    self.save(p)
                job["state"] = "failed" if any(s["state"] == "failed" for s in job["steps"]) else \
                    ("blocked" if any(s["state"] == "blocked" for s in job["steps"]) else "done")
            except StudioError as e:
                job["state"], job["error"] = "failed", e.public()
            except Exception as e:
                job["state"], job["error"] = "failed", {"message": f"{type(e).__name__}: {e}"}
            job["finished"] = time.time()

    def _make_geometry(self, p, rev, keys, name):
        s = self._k("summary", key=keys["geometry"], recipe_id=self.rid(p), values=rev["values"], p=p)
        path = self.apath(p, "geometry", keys["geometry"])
        path.parent.mkdir(parents=True, exist_ok=True)
        s.update({"rev": rev["n"], "recipe_sha": self.recipe_sha(self.rid(p))})
        path.write_text(json.dumps(s, indent=1), encoding="utf-8")

    def _make_exports(self, p, rev, keys, name):
        out = self.apath(p, "exports", keys["exports"])
        tmp = out.with_name(out.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        r = self._k("export", key=keys["geometry"], recipe_id=self.rid(p), values=rev["values"], out_dir=str(tmp),
                    name=name, orientation=p["orientation"], tol=STL_TOL, p=p)
        files = {}
        for kind in ("step", "stl"):
            if not r.get(kind):
                continue                                  # mesh designs have no STEP
            f = Path(r[kind])
            files[kind] = {"name": f.name, "bytes": f.stat().st_size, "sha256": sha_file(f)}
        meta = {"rev": rev["n"], "files": files, "orientation": p["orientation"], "stl_tolerance_mm": STL_TOL,
                "print_bbox": r["print_bbox"], "units": "mm", "source": f"recipe {self.rid(p)}@{self.recipe_sha(self.rid(p))}",
                "kernel": self.kernel_id(), "geometry_key": keys["geometry"]}
        if "stl" in files:                                # OBJ and GLB for viewers, renderers and other tools (form/meshio.py)
            from . import meshio
            for kind, (_, _, make) in meshio.FORMATS.items():
                f = tmp / f"{name}.{kind}"
                f.write_bytes(make(tmp / files["stl"]["name"], p["name"]))
                files[kind] = {"name": f.name, "bytes": f.stat().st_size, "sha256": sha_file(f)}
        if r.get("unavailable"):
            meta["unavailable"] = r["unavailable"]
        (tmp / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        fsutil.replace_dir(tmp, out)

    def _make_checks(self, p, rev, keys, name):
        ex = self.read(p, "exports", keys["exports"])
        stl = self.apath(p, "exports", keys["exports"]) / ex["files"]["stl"]["name"]
        model = purpose_mod.is_model(p)
        s = self.slicer_info(p=p) if not model else {}
        pe = self.printer_env(p) if not model else {"envelope": MODEL_ENVELOPE, "margin": 0.0, "name": "no printer"}
        a = self._k("analyse", key=keys["geometry"], recipe_id=self.rid(p), values=rev["values"], stl_path=str(stl),
                    nozzle=s.get("nozzle_mm", 0.4), envelope=pe["envelope"], orientation=p["orientation"], p=p,
                    orient=plates_mod.part_orientations(p), margin=pe["margin"])
        if a.get("mesh", {}).get("sha256") and a["mesh"]["sha256"] != ex["files"]["stl"]["sha256"]:
            raise StudioError("The STL on disk is not the one that was exported.", "Run the pipeline again to regenerate exports.")
        asm_rows = self._assembly_checks(p, rev, keys, getattr(self._tl, "step", None))
        if asm_rows:
            a["assembly"] = asm_rows
        summary = self.read(p, "geometry", keys["geometry"])
        ctx = {"orientation": p["orientation"], "envelope": pe["envelope"],
               "margin": pe["margin"], "printer": pe["name"],
               "nozzle": s.get("nozzle_mm", 0.4), "nozzle_assumed": not s.get("available")}
        if model:                                      # a 3D model: no printer, no plates, no filament (form/purpose.py)
            ctx = {"orientation": p["orientation"], "purpose": "model", "process": purpose_mod.process(p)}
            items = checks_mod.build(self.recipe(p), summary, a, ctx, None)
            fc = self._freecad()
            if fc and "step" in ex["files"]:
                step = self.apath(p, "exports", keys["exports"]) / ex["files"]["step"]["name"]
                res = cad_bridges.freecad_recheck(fc, step, timeout=(self.cfg.get("cad") or {}).get("timeout_s", 120))
                items.append(cad_bridges.recheck_item(res, a["brep"]["volume_mm3"], summary["bbox"]))
            path = self.apath(p, "checks", keys["checks"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"rev": rev["n"], "checks": items, "rollup": checks_mod.rollup(items),
                                        "orientation_table": a["orientation_table"], "fit": None, "context": ctx, "parts": [],
                                        "not_applicable": [label for _, label in purpose_mod.PRINT_ONLY],
                                        "stl_sha256": ex["files"]["stl"]["sha256"]}, indent=1), encoding="utf-8")
            return
        mats = materials_mod.of_project(p, a.get("parts") or [])
        parts = [dict(x, material=mats["parts"].get(x["id"], {}).get("material") or "",
                      color=mats["parts"].get(x["id"], {}).get("color") or "") for x in a.get("parts") or []]
        if parts:                                      # several printed parts: how they go onto plates (form/plates.py)
            ctx["parts"] = parts
            ctx["plates"] = plates_mod.plan(parts, pe["envelope"], plates_mod.spacing(self.cfg), pe["margin"])
            ctx["plates"]["needed"] = plates_mod.needed(parts, ex.get("print_bbox") or [0, 0, 0], pe["envelope"], pe["margin"])
        design_mat = materials_mod.stated(p) if not parts else None
        if not design_mat and not parts and materials_mod.normalise(p.get("material")):
            design_mat = materials_mod.normalise(p.get("material"))
        ctx["materials"] = {x["label"]: x["material"] for x in parts if x["material"]} if parts else \
            ({p["name"]: design_mat} if design_mat else {})
        own = bool(self._plate_inputs(p, self.recipe(p)).get("brief"))     # the brief is in the key only then
        ctx["material_brief"] = p["brief"].get("text", "") if own else ""
        if mats["unknown"]:
            ctx["materials_unknown"] = mats["unknown"]
        fit = self.fit(p)
        items = checks_mod.build(self.recipe(p), summary, a, ctx, fit)
        from . import materials as appearance_mod      # material notes: heat, sunlight, warping, flexible, fibre
        items += appearance_mod.check_items(p, a, ctx)
        fc = self._freecad()
        if fc and "step" in ex["files"]:                # optional: re-read the exported STEP in FreeCAD
            step = self.apath(p, "exports", keys["exports"]) / ex["files"]["step"]["name"]
            res = cad_bridges.freecad_recheck(fc, step, timeout=(self.cfg.get("cad") or {}).get("timeout_s", 120))
            items.append(cad_bridges.recheck_item(res, a["brep"]["volume_mm3"], summary["bbox"]))
        path = self.apath(p, "checks", keys["checks"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rev": rev["n"], "checks": items, "rollup": checks_mod.rollup(items),
                                    "orientation_table": a["orientation_table"], "fit": fit, "context": ctx,
                                    "parts": ctx.get("parts") or [],
                                    "stl_sha256": ex["files"]["stl"]["sha256"]}, indent=1), encoding="utf-8")

    def _make_slice(self, p, rev, keys, name):
        ex = self.read(p, "exports", keys["exports"])
        stl = self.apath(p, "exports", keys["exports"]) / ex["files"]["stl"]["name"]
        out = self.apath(p, "slice", keys["slice"])
        s = self.slicer_info(refresh=True, p=p)
        if self.keys(p)["slice"] != keys["slice"]:
            raise StudioError("Slicer presets changed while the pipeline was running.", "Run again to slice with the presets now selected.")
        if getattr(self.recipe(p), "solids", 1) > 1:
            parts = self._plate_parts(p, rev, keys, name, s)
            if parts:
                pe = self.printer_env(p)
                bed = list(pe["envelope"])               # the bed the checks planned with, so "N plates" is what is sliced
                if plates_mod.needed(parts, ex.get("print_bbox") or [0, 0, 0], bed, pe["margin"]):
                    return self._slice_plates(p, rev, keys, out, parts, bed, pe["margin"], s, ex)
        info = slicer.slice_stl(s, stl, out, timeout=self.cfg["slicer"]["timeout_s"])
        info.update({"rev": rev["n"], "stl_sha256": ex["files"]["stl"]["sha256"], "orientation": p["orientation"],
                     "evidence": "simulated"})
        if s.get("material"):
            info["material"] = s["material"]
        if s.get("plate_note"):
            info["plate_note"] = s["plate_note"]
        (out / "meta.json").write_text(json.dumps(info, indent=1), encoding="utf-8")

    # ---- several plates (form/plates.py) ---------------------------------
    def _plate_parts(self, p, rev, keys, name, s) -> list:
        """Each printed part as its own STL in its print orientation, with its material. [] for one solid."""
        pe = self.printer_env(p)
        tmp = self.dir(p["id"]) / "artifacts" / "slice" / f"{keys['slice']}.parts"
        shutil.rmtree(tmp, ignore_errors=True)
        r = self._k("plate_parts", key=keys["geometry"], recipe_id=self.rid(p), values=rev["values"], out_dir=str(tmp), name=name,
                    orientation=p["orientation"], orient=plates_mod.part_orientations(p),
                    envelope=list(pe["envelope"]), margin=pe["margin"], p=p, timeout=300)
        mats = materials_mod.of_project(p, r["parts"])
        return [dict(x, material=mats["parts"].get(x["id"], {}).get("material") or "",
                     color=mats["parts"].get(x["id"], {}).get("color") or "") for x in r["parts"]]

    def _slice_plates(self, p, rev, keys, out, parts, bed, margin, s, ex):
        """Pack the parts onto plates, slice each plate on its own, and add up the slicer's estimates."""
        pl = plates_mod.plan(parts, bed, plates_mod.spacing(self.cfg), margin)
        if pl["too_big"]:
            b = pl["too_big"][0]
            raise StudioError(f"{b['label']} is {' × '.join(f'{v:g}' for v in b['size'])} mm: larger than the plate "
                              f"({bed[0]:g} × {bed[1]:g} mm, {margin:g} mm margin) however it lies.",
                              "Split or scale the part, or choose a printer with a larger bed.")
        stl_of = {x["id"]: x["stl"] for x in parts}
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
        rows, t0 = [], time.time()
        for plate in pl["plates"]:
            n = plate["n"]
            work = out / f".plate_{n}"
            work.mkdir()
            model = work / f"{p['id']}_r{rev['n']:02d}_plate{n}.stl"
            geo = plates_mod.write_plate_stl(model, plate["parts"], stl_of)
            res = s
            if plate["material"] and plate["material"] != (s.get("material") or {}).get("material"):
                res = self.slicer_info(p=p, material=plate["material"])       # this plate's filament
            try:
                info = slicer.slice_stl(res, model, work / "sliced", timeout=self.cfg["slicer"]["timeout_s"])
            except (slicer.SlicerFailed, slicer.SlicerBlocked) as e:
                why = f"Plate {n} of {pl['count']} ({', '.join(q['label'] for q in plate['parts'])}): {e}"
                if isinstance(e, slicer.SlicerBlocked):
                    raise slicer.SlicerBlocked(why)
                raise slicer.SlicerFailed(why, e.hint, e.log)
            sliced = work / "sliced"
            files = {}
            for src, dst in ((info.get("gcode"), f"plate_{n}.gcode"), (info.get("threemf"), f"plate_{n}.3mf")):
                if src and (sliced / src).exists():
                    shutil.move(str(sliced / src), out / dst)
                    files[src] = dst
            imgs = []
            for img in info.get("images") or []:
                if (sliced / img).exists():
                    dst = f"plate_{n}.png" if img.startswith("plate") else f"plate_{n}_{img}"
                    shutil.move(str(sliced / img), out / dst)
                    imgs.append(dst)
            if (sliced / "slicer.log").exists():
                shutil.move(str(sliced / "slicer.log"), out / f"plate_{n}.slicer.log")
            shutil.move(str(model), out / f"plate_{n}.stl")
            shutil.rmtree(work, ignore_errors=True)
            mat = res.get("material") or {}
            rows.append({k: info.get(k) for k in ("time_s", "filament_g", "filament_mm", "layers", "max_z_mm", "support_used",
                                                  "slicer_version", "presets", "warnings", "plate_warnings", "seconds")}
                        | {"n": n, "gcode": files.get(info.get("gcode")), "threemf": files.get(info.get("threemf")),
                           "images": imgs, "thumbnail": imgs[0] if imgs else None, "stl": f"plate_{n}.stl",
                           "material": plate["material"], "filament": (info.get("presets") or {}).get("filament", {}).get("name"),
                           "filament_note": mat.get("text") if mat.get("changed") or not mat.get("matched", True) else "",
                           "plate_note": res.get("plate_note") or "",
                           "parts": plate["parts"], "used_mm": plate["used_mm"], "triangles": geo["triangles"]})
        def total(k):
            vals = [r.get(k) for r in rows]
            return None if any(v is None for v in vals) else round(sum(vals), 3)
        first = rows[0]
        meta = {"rev": rev["n"], "stl_sha256": ex["files"]["stl"]["sha256"], "orientation": p["orientation"], "evidence": "simulated",
                "plates": rows, "plate_count": len(rows), "time_s": total("time_s"), "filament_g": total("filament_g"),
                "filament_mm": total("filament_mm"), "layers": max((r.get("layers") or 0) for r in rows),
                "max_z_mm": max((r.get("max_z_mm") or 0) for r in rows), "support_used": any(r.get("support_used") for r in rows),
                "gcode": first["gcode"], "threemf": first["threemf"], "images": ["plate_1.png"] if "plate_1.png" in first["images"] else [],
                "slicer_version": first.get("slicer_version"), "presets": first.get("presets"),
                "slicer_kind": s.get("kind", "bambu"), "slicer_name": slicer.label(s.get("kind", "bambu")),
                "seconds": round(time.time() - t0, 2), "warnings": sorted({w for r in rows for w in (r.get("warnings") or [])})[:12],
                "plan": {k: pl[k] for k in ("count", "bed_mm", "spacing_mm", "margin_mm", "evidence", "note")},
                "how": "one slice per plate"}
        if s.get("material"):
            meta["material"] = s["material"]
        (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        shutil.rmtree(self.dir(p["id"]) / "artifacts" / "slice" / f"{keys['slice']}.parts", ignore_errors=True)

    def plate_meta(self, p: dict, plate: int | None = None) -> tuple[dict, Path, str]:
        """(meta of one plate, the slice folder, its G-code name) of the current slice; plate None or 1 for a single slice."""
        key = self.keys(p)["slice"]
        meta = self.read(p, "slice", key)
        if not meta:
            raise StudioError("There is no current slice to inspect.", "Run the pipeline first.", status=409)
        plates = meta.get("plates") or []
        if plates and plate:
            if not 1 <= int(plate) <= len(plates):
                raise StudioError(f"There is no plate {plate}.", f"This slice has {len(plates)} plates.", status=404)
            m = dict(meta, **{k: v for k, v in plates[int(plate) - 1].items() if v is not None})
            return m, self.apath(p, "slice", key), m["gcode"]
        return meta, self.apath(p, "slice", key), meta["gcode"]

    # ---- side prints: coupon / test piece --------------------------------
    def side_slice(self, p: dict, kind: str) -> dict:
        """Slice the pocket ring (cut from this revision) so its real cost is known."""
        rev, keys = self.rev(p), self.keys(p)
        s = self.slicer_info(p=p)
        presets = {k: v["sha"] for k, v in s.get("presets", {}).items()}
        key = H(kind, keys["geometry"], presets, *_slicer_tag(s))
        out = self.dir(p["id"]) / "artifacts" / "side" / key
        meta = out / "meta.json"
        if meta.exists():
            return json.loads(meta.read_text(encoding="utf-8"))
        name = f"{p['id']}_r{rev['n']:02d}_{kind}"
        tmp = out.with_name(out.name + ".src")
        r = self._k("test_piece", key=keys["geometry"], recipe_id=self.rid(p), values=rev["values"], out_dir=str(tmp), name=name, p=p)
        try:
            info = slicer.slice_stl(s, Path(r["stl"]), out, timeout=self.cfg["slicer"]["timeout_s"])
        except slicer.SlicerBlocked as e:
            raise StudioError(str(e), "The test piece STL was still written.", status=409)
        except slicer.SlicerFailed as e:
            raise StudioError(str(e), e.hint, status=422)
        shutil.copyfile(r["stl"], out / Path(r["stl"]).name)
        shutil.rmtree(tmp, ignore_errors=True)
        info.update({"kind": kind, "rev": rev["n"], "piece": {k: r[k] for k in ("bbox", "volume_mm3", "label", "doc")},
                     "stl": Path(r["stl"]).name, "key": key, "evidence": "simulated"})
        meta.write_text(json.dumps(info, indent=1), encoding="utf-8")
        return info

    def costs(self, p: dict) -> dict:
        out = {}
        try:
            keys = self.keys(p)
            m = self.read(p, "slice", keys["slice"])
            if m:
                out["part"] = {"time_s": m.get("time_s"), "filament_g": m.get("filament_g")}
            s = self.slicer_info(p=p)
            presets = {k: v["sha"] for k, v in s.get("presets", {}).items()}
            side = self.dir(p["id"]) / "artifacts" / "side" / H("test_piece", keys["geometry"], presets, *_slicer_tag(s)) / "meta.json"
            if side.exists():
                m = json.loads(side.read_text(encoding="utf-8"))
                out["test_piece"] = {"time_s": m.get("time_s"), "filament_g": m.get("filament_g")}
        except (StudioError, ValueError):
            pass
        for q in self.list():
            if q.get("recipe") == "coupon":
                try:
                    qp = self.load(q["id"])
                    m = self.read(qp, "slice", self.keys(qp)["slice"])
                    if m:
                        out["coupon"] = {"time_s": m.get("time_s"), "filament_g": m.get("filament_g"), "project": q["id"]}
                        break
                except StudioError:
                    pass
        return out

    # ---- evidence, approval, release ------------------------------------
    def add_evidence(self, p: dict, body: dict) -> dict:
        with self.lock(p["id"]):
            p = self.load(p["id"])
            kind = body.get("kind")
            rec = {"id": uuid.uuid4().hex[:8], "ts": time.time(), "rev": p["head"], "kind": kind, "class": "physical",
                   "profile": self.profile(p), "note": str(body.get("note", ""))[:1000]}
            if kind == "widths":
                cal = self.calibration.add(self.profile(p), body.get("pairs", []), body.get("source", "part"), rec["note"],
                                           {"project": p["id"], "rev": p["head"]})
                rec.update({"pairs": cal["pairs"], "calibration_id": cal["id"], "source": cal["source"]})
            elif kind == "fit":
                if body.get("result") not in ("too_tight", "good", "too_loose"):
                    raise StudioError("Choose how the printed part fitted.")
                rec["result"] = body["result"]
            else:
                raise StudioError("Unknown evidence type.")
            p["evidence"].append(rec)
            self.decide(p, "evidence", f"Physical result recorded for r{p['head']}: " +
                        (f"{len(rec['pairs'])} measured width(s)" if kind == "widths" else rec["result"].replace("_", " ")))
            self.save(p)
            return rec

    def gate(self, p: dict, status: dict | None = None) -> dict:
        status = status or self.status(p)
        keys = self.keys(p)
        reasons, warns, failures = [], [], []
        off = status["slice"].get("off") if status["slice"]["state"] == "off" else None
        for n in NODES:
            st = status[n]
            if n == "slice" and off:                  # Design only: said below, never a reason to block
                continue
            if st["state"] != "current":
                why = {"stale": f"is stale (last made for r{st.get('last_rev')})", "failed": "failed",
                       "missing": "has not been produced"}[st["state"]]
                if n == "slice" and st.get("unavailable"):
                    why = "is blocked: " + st["unavailable"]
                reasons.append(f"{NODE_LABEL[n]} {why}.")
        blocking = list(reasons)                  # outputs that are missing, stale or failed: there is nothing to release
        ch = self.read(p, "checks", keys["checks"]) if status["checks"]["state"] == "current" else None
        if ch:
            for c in ch["checks"]:
                if c["status"] == "FAIL":
                    reasons.append(f"Check failed: {c['label']} ({c['value']}).")
                    failures.append({"id": c["id"], "label": c["label"], "value": c["value"]})
                elif c["status"] == "WARN":
                    warns.append({"id": c["id"], "label": c["label"], "value": c["value"]})
        # a coupon calibrates the printer; only a result from this part speaks for this revision
        physical = [e for e in p["evidence"] if e["rev"] == p["head"] and (e["kind"] == "fit" or e.get("source") == "part")]
        model = bool(off) and off.get("why") == "purpose"
        level = "Geometry computed · 3D model, not for 3D printing" if model else \
            ("Geometry computed · not sliced (Design only) · " if off else "Geometry computed · slice simulated · ") \
            + ("physical result recorded for this revision" if physical else "not physically validated")
        # a person may still release over failed checks: each one acknowledged and a reason written, and the release
        # says so in its manifest and report. Missing or stale outputs always block: there would be no files to freeze.
        out = {"ready": not reasons, "reasons": reasons, "warnings": warns, "failures": failures, "blocking": blocking,
               "can_override": not blocking and bool(failures), "evidence_level": level, "physical": len(physical)}
        if model:                                      # nothing about slicing is missing from a model: it is not a print
            out["purpose"] = "model"
        elif off:
            out["design_only"] = off
            out["not_covered"] = NOT_COVERED
        return out

    def approve(self, p: dict, acknowledged: list, note: str = "", override_failures: list | None = None) -> dict:
        """Release the head revision. Warnings must each be acknowledged. Failed checks block, unless the person
        acknowledges every one of them in `override_failures` and writes the reason in `note`."""
        with self.lock(p["id"]):
            p = self.load(p["id"])
            status = self.status(p)
            g = self.gate(p, status)
            overridden = []
            if not g["ready"]:
                if not g["can_override"] or not override_failures:
                    raise StudioError("This revision cannot be released yet.", " ".join(g["reasons"]), status=409)
                left = [f["label"] for f in g["failures"] if f["id"] not in override_failures]
                if left:
                    raise StudioError("Every failed check must be acknowledged to release with it.",
                                      "Not acknowledged: " + ", ".join(left) + ".", status=409)
                if len(note.strip()) < 3:
                    raise StudioError("Say why this revision is released with failed checks.",
                                      "The reason goes into the release note, the report and the manifest.", status=409)
                overridden = g["failures"]
            missing = [w["label"] for w in g["warnings"] if w["id"] not in (acknowledged or [])]
            if missing:
                raise StudioError("Every warning must be acknowledged before release.", "Unacknowledged: " + ", ".join(missing) + ".", status=409)
            keys, rev = self.keys(p), self.rev(p)
            rel = self.dir(p["id"]) / "releases" / f"r{rev['n']:02d}-{keys['exports'][:6]}"
            shutil.rmtree(rel, ignore_errors=True)
            rel.mkdir(parents=True)
            ex = self.read(p, "exports", keys["exports"])
            model = g.get("purpose") == "model"
            sl = None if (g.get("design_only") or model) else self.read(p, "slice", keys["slice"])
            ch = self.read(p, "checks", keys["checks"])
            files = {}
            for kind in ("step", "stl", "obj", "glb"):
                if kind not in ex["files"]:
                    continue
                src = self.apath(p, "exports", keys["exports"]) / ex["files"][kind]["name"]
                shutil.copyfile(src, rel / src.name)
                files[src.name] = ex["files"][kind]["sha256"]
            files.update(self._release_extras(p, rel, ex, keys, model))
            sdir = self.apath(p, "slice", keys["slice"])
            stem = f"{p['id']}_r{rev['n']:02d}"
            outs = []
            if sl and sl.get("plates"):                   # several plates: every plate's sliced 3MF and G-code
                for pl in sl["plates"]:
                    outs += [(pl.get("threemf"), f"{stem}_plate{pl['n']}_sliced.3mf"), (pl.get("gcode"), f"{stem}_plate{pl['n']}.gcode")]
            elif sl:
                outs = [(sl.get("threemf"), f"{stem}_sliced.3mf"), (sl.get("gcode"), f"{stem}.gcode")]
            for fname, target in outs:
                if fname and (sdir / fname).exists():
                    shutil.copyfile(sdir / fname, rel / target)
                    files[target] = sha_file(rel / target)
            from . import maker_docs                      # BOM, ASSEMBLY, PRINT_REPORT, MEASUREMENT_PLAN (+ images), hashed like the rest
            documents = maker_docs.write(self, p, rel, release=rel.name)
            files.update(documents)
            manifest = {
                "schema": "form-release/1", "project": p["id"], "name": p["name"], "revision": rev["n"], "approved": time.time(),
                "units": "mm", "recipe": self.rid(p), "recipe_sha": self.recipe_sha(self.rid(p)), "kernel": self.kernel_id(),
                "values": rev["values"], "provenance": rev["provenance"], "keys": keys, "files": files,
                "orientation": p["orientation"],
                "slicer": ({k: sl.get(k) for k in ("slicer_version", "presets", "time_s", "filament_g", "layers", "support_used")}
                           | {k: sl[k] for k in ("slicer_kind", "slicer_name") if k in sl}
                           | ({"plates": [{k: x.get(k) for k in ("n", "time_s", "filament_g", "layers", "material", "filament")}
                                          | {"parts": [q["label"] for q in x.get("parts", [])]} for x in sl["plates"]]}
                              if sl.get("plates") else {})
                           | ({"material": sl["material"]} if sl.get("material") else {}))
                          if sl else {"not_for_printing": True, "text": "A 3D model, not made for 3D printing."} if model else
                          {"design_only": True, "why": g["design_only"]["why"], "text": g["design_only"]["text"]},
                "purpose": purpose_mod.describe(p),
                "not_covered": g.get("not_covered", []),
                "checks": [{k: c[k] for k in ("id", "label", "status", "value", "evidence")} for c in ch["checks"]],
                "acknowledged_warnings": [w for w in g["warnings"]], "released_with_failed_checks": overridden,
                "note": note, "evidence_level": g["evidence_level"] + (" · released with failed checks" if overridden else ""),
                "documents": sorted(documents),
                "physical_evidence": [e for e in p["evidence"] if e["rev"] == rev["n"] and (e["kind"] == "fit" or e.get("source") == "part")],
                "limits": (["A 3D model: print checks and slicing do not apply."] if model else
                           ["Not sliced (Design only): print time, filament and toolpaths were not estimated."] if not sl else
                           ["Slicer output is a simulation, not a print."]) + ["No structural analysis was performed."]
                          + ([] if model else ["Fit yield is a statistical model; see checks for the source of each input."])
                          + (["Mesh design (OpenSCAD): no STEP file and no B-rep checks."] if getattr(self.recipe(p), "mesh", False) else []),
            }
            (rel / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
            (rel / "REPORT.md").write_text(self._report(p, manifest), encoding="utf-8")
            p["approvals"].append({"rev": rev["n"], "ts": manifest["approved"], "keys": keys, "release": rel.name, "note": note,
                                   "acknowledged": [w["id"] for w in g["warnings"]], "overridden": [f["id"] for f in overridden]})
            self.decide(p, "approval", f"r{rev['n']} approved and released as {rel.name}. {manifest['evidence_level']}."
                        + (" Released with failed checks: " + ", ".join(f"{f['label']} ({f['value']})" for f in overridden)
                           + f". Reason: {note.strip()}" if overridden else ""))
            self.save(p)
            return {"release": rel.name, "manifest": manifest}

    def _release_extras(self, p, rel: Path, ex: dict, keys: dict, model: bool) -> dict:
        """What a release carries besides the exports: for a 3D model, a 3MF and rendered views (a four-view sheet and
        an iso view), so it can go to a renderer, a machine shop or a client without Form Studio. {file: sha256}."""
        out = {}
        stem = f"{p['id']}_r{p['head']:02d}"
        if model:
            try:
                from . import materials as appearance_mod
                (rel / f"{stem}.3mf").write_bytes(appearance_mod.threemf(self, p))
                out[f"{stem}.3mf"] = sha_file(rel / f"{stem}.3mf")
            except Exception:                         # a 3MF is a convenience; the STEP and STL are the record
                pass
            try:
                from . import render as rendering
                v = self.view(p)
                feats = [{"id": f.id, "label": f.label} for f in self.recipe(p).features]
                title = f"{p['name']} - r{p['head']:02d}"
                (rel / f"{stem}_views.png").write_bytes(rendering.contact_sheet(
                    [rendering.render_png(v, feats, vw, None, size=(640, 460), title=title) for vw in ("iso", "front", "top", "right")]))
                (rel / f"{stem}_iso.png").write_bytes(rendering.render_png(v, feats, "iso", None, size=(1280, 900), title=title))
                for f in (f"{stem}_views.png", f"{stem}_iso.png"):
                    out[f] = sha_file(rel / f)
            except Exception:
                pass
        return out

    def _report(self, p, m) -> str:
        t = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["approved"]))
        s = m["slicer"]
        lines = [f"# {m['name']} — release r{m['revision']:02d}", "", f"Approved {t}. Units: mm. **{m['evidence_level']}.**", "",
                 "## Files", ""] + [f"- `{k}` — sha256 `{v[:16]}…`" for k, v in m["files"].items()] + ["",
                 "## Source", "", f"- Recipe `{m['recipe']}` @ `{m['recipe_sha']}`, {m['kernel']}"]
        if not s.get("not_for_printing"):
            lines.append(f"- Print orientation: {m['orientation']}")
        lines += ["",
                 "## Parameters", "", "| Parameter | Value | Source |", "|---|---|---|"]
        r = self.recipes[m["recipe"]]
        for k, v in m["values"].items():
            sp = r.spec(k)
            lines.append(f"| {sp.label} | {v:g} {sp.unit} | {m['provenance'].get(k, {}).get('source', 'assumed')} |")
        lines += ["", "## Checks", "", "| Check | Result | Value | Evidence |", "|---|---|---|---|"]
        lines += [f"| {c['label']} | {c['status']} | {c['value']} | {c['evidence']} |" for c in m["checks"]]
        if m["acknowledged_warnings"]:
            lines += ["", "Warnings acknowledged at approval: " + ", ".join(w["label"] for w in m["acknowledged_warnings"]) + "."]
        if m.get("released_with_failed_checks"):
            lines += ["", "**Released with failed checks:** " + ", ".join(f"{f['label']} ({f['value']})" for f in m["released_with_failed_checks"])
                      + f". Reason given at approval: {m.get('note') or '—'}"]
        if s.get("not_for_printing"):
            pu = m.get("purpose") or {}
            lines += ["", "## Purpose", "", "A 3D model, not made for 3D printing"
                      + (f": {pu['process_label']}" if pu.get("process") else "") + ". Print checks and slicing do not apply."]
        elif s.get("design_only"):
            lines += ["", "## Slice", "", f"Not part of this release: Design only. {s.get('text', '')}"] + [f"- {x}" for x in m.get("not_covered", [])]
        elif s.get("time_s"):
            lines += ["", "## Slice (simulated)", "", f"- {s.get('slicer_name') or 'The slicer'} {s['slicer_version']}: {(f"{s['time_s']/60:.0f} min" if s.get('time_s') is not None else 'no time estimate')}, {(f"{s['filament_g']:.1f} g" if s.get('filament_g') is not None else 'no filament estimate')}, {s['layers']} layers, supports: {'yes' if s.get('support_used') else 'no'}",
                      "- Presets: " + " · ".join(v["name"] for v in s["presets"].values())]
            for pl in s.get("plates") or []:
                lines.append(f"- Plate {pl['n']}: " + ", ".join(pl["parts"]) + " · "
                             + (f"{pl['time_s']/60:.0f} min" if pl.get("time_s") is not None else "no time estimate") + ", "
                             + (f"{pl['filament_g']:.1f} g" if pl.get("filament_g") is not None else "no filament estimate")
                             + (f" · {pl['filament']}" if pl.get("filament") else ""))
        lines += ["", "## Limits", ""] + [f"- {x}" for x in m["limits"]] + [""]
        return "\n".join(lines)

    def verify_release(self, p: dict, name: str) -> dict:
        rel = self.dir(p["id"]) / "releases" / name
        if not re.fullmatch(r"r\d+-[0-9a-f]+", name) or not (rel / "MANIFEST.json").exists():
            raise StudioError("Unknown release.", status=404)
        m = json.loads((rel / "MANIFEST.json").read_text(encoding="utf-8"))
        rows = []
        for fname, sha in m["files"].items():
            f = rel / fname
            rows.append({"file": fname, "ok": f.exists() and sha_file(f) == sha})
        return {"release": name, "revision": m["revision"], "intact": all(r["ok"] for r in rows), "files": rows,
                "matches_head": m["keys"] == self.keys(p)}

    # ---- save / restore --------------------------------------------------
    def export_archive(self, p: dict) -> Path:
        d = self.dir(p["id"])
        out = self.root / f"{p['id']}.formproj"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(d.rglob("*")):
                if f.is_file() and not f.name.endswith((".tmp", ".bak")) and ".src" not in f.parts[-2:]:
                    z.write(f, f.relative_to(d).as_posix())
        return out

    def import_archive(self, data: bytes) -> dict:
        import io
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
            p = json.loads(z.read("project.json"))
        except (zipfile.BadZipFile, KeyError, ValueError):
            raise StudioError("That file is not a Form Studio project archive.", "Choose a .formproj file exported from Form Studio.")
        if p.get("schema") != SCHEMA or p.get("recipe") not in self.recipes:
            raise StudioError("This archive was made by an incompatible version of Form Studio.")
        base = slugify(p.get("id", "project"))
        pid, i = base, 2
        while (self.root / pid).exists():
            pid, i = f"{base}-{i}", i + 1
        dest = self.root / pid
        for info in z.infolist():
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(dest.resolve()) or info.file_size > 200_000_000:
                shutil.rmtree(dest, ignore_errors=True)
                raise StudioError("The archive contains an unsafe path and was not restored.")
            if info.is_dir():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
        p["id"] = pid
        self.save(p)
        return self.load(pid)

    # ---- other CAD tools: imported reference parts, FreeCAD -------------
    def _freecad(self) -> str | None:
        """FreeCADCmd for the optional re-import check; cached briefly like the slicer."""
        now = time.time()
        if getattr(self, "_fc_at", 0) < now - 30:
            self._fc, self._fc_at = cad_bridges.find_freecad(self.cfg), now
        return self._fc

    @staticmethod
    def _ref_name(name: str) -> str:
        base, ext = os.path.splitext(Path(name).name)
        base = re.sub(r"[^A-Za-z0-9_.\-]+", "_", base).strip("._-")[:60] or "part"
        return base + ext.lower()

    def references(self, p: dict) -> list:
        return [r for r in p["brief"].get("references", []) if r.get("kind") == "part"]

    def reference_paths(self, p: dict) -> dict:
        d = self.dir(p["id"]) / "references"
        return {r["file"]: str(d / r["file"]) for r in self.references(p) if (d / r["file"]).exists()}

    def _refs_fp(self, p: dict) -> str:
        return H(sorted((r["file"], r.get("sha256")) for r in self.references(p)))

    def uses_references(self, rid: str) -> bool:
        """Only designs that call self.reference(...) depend on imported parts (cheap text test, cached per source)."""
        if not rid.startswith(SOURCE_PREFIX):
            return False
        cache = self.__dict__.setdefault("_uses_refs", {})
        if rid not in cache:
            f = source_path(self.sources, rid)
            cache[rid] = f.exists() and "reference(" in f.read_text(encoding="utf-8")
        return cache[rid]

    def import_reference(self, p: dict, src: Path, name: str | None = None, data: bytes | None = None) -> dict:
        """Copy a STEP or STL into the project's references, measure it in the kernel, keep a display mesh.

        The part is drawn as a blueprint companion in its own coordinates (the design's frame), and a design can
        read it with self.reference(name). Re-importing the same name replaces the file.
        """
        name = self._ref_name(name or src.name)
        if Path(name).suffix not in REF_FORMATS:
            raise StudioError("Only STEP (.step, .stp) and STL (.stl) parts can be imported.",
                              "Export the part from its CAD program as STEP, or as STL for a mesh.")
        d = self.dir(p["id"]) / "references"
        d.mkdir(parents=True, exist_ok=True)
        target = d / name
        tmp = d / (name + ".tmp")
        if data is not None:
            if len(data) > 200_000_000:
                raise StudioError("The file is larger than 200 MB.")
            tmp.write_bytes(data)
        else:
            if not src.is_file():
                raise StudioError(f"File not found: {src}", "Give the absolute path of a STEP or STL file.")
            shutil.copyfile(src, tmp)
        try:
            info = self._k("reference", timeout=180, path=str(tmp), fmt=Path(name).suffix,
                           out=str(d / (name + ".view.json")))
        except StudioError as e:
            tmp.unlink(missing_ok=True)
            raise StudioError(f"Could not read {name}: {e}", e.hint or "Check that the file is a valid STEP or a closed STL.")
        fsutil.replace(tmp, target)
        rec = {"file": name, "kind": "part", "format": "step" if name.endswith((".step", ".stp")) else "stl",
               "ts": time.time(), "sha256": sha_file(target), "bytes": target.stat().st_size,
               "bbox": info["bbox"], "volume_mm3": info["volume_mm3"], "solids": info.get("solids"),
               "triangles": info.get("triangles"), "evidence": "computed", "imported_from": src.name if src else name}
        with self.lock(p["id"]):
            p = self.load(p["id"])
            refs = [r for r in p["brief"]["references"] if not (r.get("kind") == "part" and r["file"] == name)]
            p["brief"]["references"] = refs + [rec]
            self.decide(p, "reference", f"Imported reference part {name}: "
                        + " × ".join(f"{b - a:.1f}" for a, b in zip(*info["bbox"])) + " mm"
                        + (f", {info['volume_mm3'] / 1000:.2f} cm³" if info.get("volume_mm3") else "") + " (computed).")
            self.save(p)
        self.__dict__.get("_uses_refs", {}).clear()
        return rec

    def reference_companions(self, p: dict) -> list:
        """Imported parts as viewport companions. `size`/`origin` give older viewers a bounding box to draw."""
        out, d = [], self.dir(p["id"]) / "references"
        for r in self.references(p):
            f = d / (r["file"] + ".view.json")
            try:
                v = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            (x0, y0, z0), (x1, y1, z1) = r["bbox"]
            out.append({"kind": "part", "label": r["file"], "size": [x1 - x0, y1 - y0, z1 - z0],
                        "origin": [(x0 + x1) / 2, (y0 + y1) / 2, z0], "rot_x_deg": 0,
                        "mesh": {"positions": v["positions"], "indices": v["indices"]}, "edges": v.get("edges", "")})
        return out

    def freecad_macro(self, p: dict) -> tuple[str, str]:
        """(file name, text) of a FreeCAD macro that rebuilds the current export from its STEP."""
        keys = self.keys(p)
        ex = self.read(p, "exports", keys["exports"])
        if not ex:
            raise StudioError("There is no current export.", "Run the pipeline first.", status=409)
        if "step" not in ex["files"]:
            raise StudioError("This is a mesh design (OpenSCAD); there is no STEP file for FreeCAD to rebuild from.",
                              "Open the STL in FreeCAD instead (Mesh workbench).", status=409)
        rev, recipe = self.rev(p), self.recipe(p)
        params = [{"key": k, "label": recipe.spec(k).label, "value": v, "unit": recipe.spec(k).unit,
                   "source": rev["provenance"].get(k, {}).get("source", "assumed")} for k, v in rev["values"].items()]
        st = ex["files"]["step"]
        name = f"{p['id']}_r{rev['n']:02d}.FCMacro"
        return name, cad_bridges.freecad_macro(p["name"], rev["n"], st["name"], st["sha256"], params)

    # ---- composed state for the UI --------------------------------------
    def state(self, pid: str) -> dict:
        p = self.load(pid)
        recipe = self.recipe(p)
        status = self.status(p)
        keys = {n: status[n]["key"] for n in NODES}
        model = purpose_mod.is_model(p)
        fit = None if model else self.fit(p)          # the fit model is about a printer's accuracy
        costs = {} if model else self.costs(p)
        out = {
            "purpose": purpose_mod.describe(p),
            "project": {k: v for k, v in p.items() if k != "produced"},
            "recipe": recipe.public(), "status": status, "approval": self.approval_state(p, status),
            "gate": self.gate(p, status), "fit": fit, "actions": fit_mod.next_actions(fit, costs), "costs": costs,
            "calibration": {"profile": self.profile(p), "correction": self.calibration.correction(self.profile(p)),
                            "records": [r for r in self.calibration.records() if r["profile"] == self.profile(p)][-20:]},
            "printer": self.printer_state(p),
            "checks": self.read(p, "checks", keys["checks"]) if status["checks"]["state"] == "current" else None,
            "slice": self.read(p, "slice", keys["slice"]) if status["slice"]["state"] == "current" else None,
            "exports": self.read(p, "exports", keys["exports"]) if status["exports"]["state"] == "current" else None,
            "releases": sorted(d.name for d in (self.dir(pid) / "releases").glob("r*")) if (self.dir(pid) / "releases").exists() else [],
            "recovered": p.get("_recovered"),
        }
        from . import maker_docs
        out["documents"] = maker_docs.available(self, p)          # maker documents the working files can produce
        return out

    def layers(self, p: dict, plate: int | None = None) -> list:
        key = self.keys(p)["slice"]
        ck = f"{key}:{plate or 1}"
        if ck not in self._layers_cache:
            meta, folder, gcode = self.plate_meta(p, plate)
            self._layers_cache.clear()
            self._layers_cache[ck] = slicer.parse_layers(folder / gcode, meta.get("slicer_kind"))
        return self._layers_cache[ck]

    # ── project housekeeping: rename, duplicate, delete (app shell) ──────────────────────────────────────────
    def _summary(self, pid: str) -> dict:
        """One project as Studio.list() reports it."""
        for row in self.list():
            if row["id"] == pid:
                return row
        raise StudioError("Unknown project.", status=404)

    @staticmethod
    def _pid(p_or_id) -> str:
        return p_or_id["id"] if isinstance(p_or_id, dict) else str(p_or_id or "")

    @staticmethod
    def _clean_name(name) -> str:
        name = " ".join(str(name or "").split())
        if not name:
            raise StudioError("A project needs a name.", "Type a name of up to 80 characters.")
        if len(name) > 80:
            raise StudioError("That name is too long.", "Use 80 characters or fewer.")
        return name

    def rename_project(self, p_or_id, name) -> dict:
        """Change the display name only. The id (and so the folder, links and releases) stays what it was."""
        pid, name = self._pid(p_or_id), self._clean_name(name)
        with self.lock(pid):
            p = self.load(pid)
            p["name"] = name
            self.save(p)
        return self._summary(pid)

    def duplicate_project(self, p_or_id, name=None) -> dict:
        """Copy a project (revisions, variants, built artifacts) under a new id derived from the new name.
        The copy is not approved: approvals and release folders describe the original and are left out."""
        src_id = self._pid(p_or_id)
        with self.lock(src_id):
            src = self.load(src_id)
            if name is None or not str(name).strip():
                name = str(src["name"])[:75] + " copy"
            name = self._clean_name(name)
            base = slugify(name)
            pid, i = base, 2
            while (self.root / pid).exists():
                pid, i = f"{base}-{i}", i + 1
            dest = self.root / pid
            try:
                shutil.copytree(self.dir(src_id), dest, ignore=shutil.ignore_patterns("*.tmp", "*.bak", "releases"))
                p = json.loads((dest / "project.json").read_text(encoding="utf-8"))
                had = len(p.get("approvals") or [])
                p.update({"id": pid, "name": name, "created": time.time(), "approvals": []})
                p.setdefault("decisions", []).append({
                    "ts": time.time(), "rev": p["head"], "kind": "note",
                    "text": f"Copied from “{src['name']}” ({src_id})."
                            + (" Its approval and releases stay with the original; this copy is not approved." if had else "")})
                self.save(p)
            except (OSError, ValueError) as e:
                shutil.rmtree(dest, ignore_errors=True)
                raise StudioError(f"Could not copy the project: {e}",
                                  "Check that the projects folder is writable and has free space.", status=500)
        return self._summary(pid)

    def delete_project(self, p_or_id) -> dict:
        """Move the project folder to <data dir>/.trash/<id>-<UTC timestamp>. Nothing is erased: moving the folder
        back restores the project."""
        pid = self._pid(p_or_id)
        d = self.dir(pid)
        if not (d / "project.json").exists() and not (d / "project.json.bak").exists():
            raise StudioError("Unknown project.", status=404)
        if any(j.get("project") == pid and j.get("state") == "running" for j in list(self.jobs.values())):
            raise StudioError("This project is still building.", "Wait for the pipeline to finish, then delete it.", status=409)
        try:
            name = self.load(pid).get("name") or pid
        except Exception:
            name = pid
        trash = self.root / ".trash"
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        dest, i = trash / f"{pid}-{stamp}", 2
        with self.lock(pid):
            try:
                trash.mkdir(parents=True, exist_ok=True)
                while dest.exists():
                    dest, i = trash / f"{pid}-{stamp}-{i}", i + 1
                shutil.move(str(d), str(dest))
            except OSError as e:
                raise StudioError(f"Could not move the project to the trash: {e}",
                                  "Close any program that has the project's files open and try again.", status=500)
        self._locks.pop(pid, None)
        self._layers_cache.clear()
        # conversations about this design stay, but no longer point at a project that is gone
        detached, missed = 0, []
        from .conversations import Conversations
        store = Conversations(self.root)              # shares the chat service's lock on the same folder
        try:
            metas = store.list(project=pid, limit=100000)
        except Exception as e:                        # the project is in the trash either way; say what was not done
            metas, missed = [], [f"list: {type(e).__name__}: {e}"]
        for m in metas:
            try:
                store.update(m["id"], project=None, project_was={"id": pid, "name": name})
                detached += 1
            except Exception as e:
                missed.append(f"{m['id']}: {type(e).__name__}: {e}")
        if missed:
            self.activity(None, "warning", f"{len(missed)} conversation(s) still name the deleted design {name}.", by="Form Studio")
        return {"ok": True, "id": pid, "trash": str(dest), "conversations_detached": detached, "conversations_missed": missed}
