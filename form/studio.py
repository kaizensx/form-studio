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

NODES = ["geometry", "exports", "checks", "slice"]
STATICS_LABELS = {"tip_force_n": ("Tip-over force", "N"), "safety_factor": ("Bending safety factor", "x"),
                  "root_stress_mpa": ("Arm root stress", "MPa"), "upper_screw_pull_n": ("Upper screw load", "N")}
NODE_LABEL = {"geometry": "Solid", "exports": "STEP + STL", "checks": "Checks", "slice": "Slice"}
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
        self.recipes = RecipeBook(self.sources)
        self.calibration = fit_mod.Calibration(self.root / "calibration.json")
        self.jobs: dict = {}
        self._locks: dict = {}
        self._slicer = None
        self._slicer_at = 0.0
        self._kernel_id = None
        self._recipe_sha: dict = {}
        self._layers_cache: dict = {}
        if not any((d / "project.json").exists() for d in self.root.iterdir() if d.is_dir()):
            self.seed_examples()

    def seed_examples(self) -> list:
        """A new data folder starts with the shipped examples (design history only; outputs are rebuilt)."""
        made = []
        for f in sorted((Path(__file__).parent / "examples").glob("*.json")):
            d = self.root / f.stem
            if d.exists():
                continue
            (d / "artifacts").mkdir(parents=True)
            shutil.copyfile(f, d / "project.json")
            made.append(f.stem)
        return made

    # ---- environment -----------------------------------------------------
    def slicer_info(self, refresh=False) -> dict:
        if refresh or self._slicer is None or time.time() - self._slicer_at > 20:
            self._slicer = slicer.resolve(self.cfg)
            self._slicer_at = time.time()
        return self._slicer

    def kernel_id(self) -> str:
        if self._kernel_id is None:
            self._kernel_id = self.kernel.call("ping", timeout=120)["kernel"]
        return self._kernel_id

    def recipe_sha(self, rid: str) -> str:
        if rid not in self._recipe_sha:
            base = Path(__file__).parent / "recipes"
            h = hashlib.sha256()
            src = source_path(self.sources, rid) if is_source(rid) else base / f"{rid}.py"
            extra = (base / "scad.py", base / "meshsolid.py") if rid.startswith(SCAD_PREFIX) else ()
            for f in (base / "base.py", src, *extra):
                h.update(f.read_bytes())
            self._recipe_sha[rid] = h.hexdigest()[:16]
        return self._recipe_sha[rid]

    def profile(self) -> str:
        s = self.slicer_info()
        if not s.get("available"):
            return "unknown printer profile"
        p = s["presets"]
        return f"{p['machine']['name']} · {p['filament']['name']}"

    def environment(self) -> dict:
        s = self.slicer_info()
        return {"version": __version__, "kernel": self.kernel_id(), "slicer": slicer.public(s),
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
                                "approved_rev": (p["approvals"][-1]["rev"] if p["approvals"] else None)})
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
        tmp.replace(path)

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

    def create_design(self, name: str, source: str, brief: str = "", values: dict | None = None,
                      language: str = "python", references: list | None = None) -> dict:
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
        self._k("summary", key="pv-" + H(rid, values or {}), recipe_id=rid, refs=refs,
                values={**self.recipes[rid].defaults(), **(values or {})}, tol=0.1)        # must build before it is saved
        p = self.create(name, rid, brief, values)
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
            self._k("summary", key="pv-" + H(rid, vals), recipe_id=rid, values=vals, tol=0.1, p=p)
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

    def create(self, name: str, recipe_id: str, brief: str = "", values: dict | None = None) -> dict:
        if recipe_id not in self.recipes:
            raise StudioError("Unknown recipe.")
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
             "orientation": "as_modelled", "auto_slice": True,
             "revisions": [{"n": 1, "parent": None, "ts": now, "values": vals, "recipe": recipe_id,
                            "note": "Starting point from recipe defaults" if not is_source(recipe_id) else "First version of the design",
                            "origin": "recipe", "provenance": {pp.key: _initial_provenance(pp) for pp in r.params}}],
             "head": 1, "produced": {n: [] for n in NODES}, "decisions": [], "evidence": [], "approvals": []}
        from . import presets                       # a brief filled in from a template carries its answers
        filled = presets.attach(self.root, brief)
        if filled:
            p["brief"].update(filled)
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
        s = self.slicer_info()
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
            fit_in = [p["fit"], self.calibration.fingerprint(self.profile()), r["provenance"].get(recipe.fit["mating"])]
        ck = H("checks", ek, self.cfg["printer"]["envelope_mm"], self.cfg["printer"]["plate_margin_mm"],
               s.get("nozzle_mm", 0.4), checks_mod.CHECKS_VERSION, fit_in)
        fc = self._freecad()
        if fc and not getattr(recipe, "mesh", False):  # an installed FreeCAD adds a re-import check
            ck = H(ck, "freecad", fc)
        presets = {k: v["sha"] for k, v in s.get("presets", {}).items()} if s.get("available") else None
        sk = H("slice", ek, presets, slicer.version(s["app"], s.get("kind", "bambu")) if s.get("available") else None,
               *_slicer_tag(s))
        return {"geometry": gk, "exports": ek, "checks": ck, "slice": sk}

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
        if not self.slicer_info().get("available"):
            out["slice"]["unavailable"] = self.slicer_info().get("reason")
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
            nz = self.slicer_info().get("nozzle_mm")
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
        corr = self.calibration.correction(self.profile())
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
                from .kernel import ORIENT_LABEL
                if body["orientation"] not in ORIENT_LABEL:
                    raise StudioError("Unknown orientation.")
                if body["orientation"] != p["orientation"]:
                    self.decide(p, "orientation", f"Print orientation set to “{ORIENT_LABEL[body['orientation']]}”.")
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
        if r.get("unavailable"):
            meta["unavailable"] = r["unavailable"]
        (tmp / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        shutil.rmtree(out, ignore_errors=True)
        tmp.replace(out)

    def _make_checks(self, p, rev, keys, name):
        ex = self.read(p, "exports", keys["exports"])
        stl = self.apath(p, "exports", keys["exports"]) / ex["files"]["stl"]["name"]
        s = self.slicer_info()
        a = self._k("analyse", key=keys["geometry"], recipe_id=self.rid(p), values=rev["values"], stl_path=str(stl),
                    nozzle=s.get("nozzle_mm", 0.4), envelope=self.cfg["printer"]["envelope_mm"], orientation=p["orientation"], p=p)
        if a.get("mesh", {}).get("sha256") and a["mesh"]["sha256"] != ex["files"]["stl"]["sha256"]:
            raise StudioError("The STL on disk is not the one that was exported.", "Run the pipeline again to regenerate exports.")
        summary = self.read(p, "geometry", keys["geometry"])
        ctx = {"orientation": p["orientation"], "envelope": self.cfg["printer"]["envelope_mm"],
               "margin": self.cfg["printer"]["plate_margin_mm"], "printer": self.cfg["printer"]["name"],
               "nozzle": s.get("nozzle_mm", 0.4), "nozzle_assumed": not s.get("available")}
        fit = self.fit(p)
        items = checks_mod.build(self.recipe(p), summary, a, ctx, fit)
        fc = self._freecad()
        if fc and "step" in ex["files"]:                # optional: re-read the exported STEP in FreeCAD
            step = self.apath(p, "exports", keys["exports"]) / ex["files"]["step"]["name"]
            res = cad_bridges.freecad_recheck(fc, step, timeout=(self.cfg.get("cad") or {}).get("timeout_s", 120))
            items.append(cad_bridges.recheck_item(res, a["brep"]["volume_mm3"], summary["bbox"]))
        path = self.apath(p, "checks", keys["checks"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rev": rev["n"], "checks": items, "rollup": checks_mod.rollup(items),
                                    "orientation_table": a["orientation_table"], "fit": fit, "context": ctx,
                                    "stl_sha256": ex["files"]["stl"]["sha256"]}, indent=1), encoding="utf-8")

    def _make_slice(self, p, rev, keys, name):
        ex = self.read(p, "exports", keys["exports"])
        stl = self.apath(p, "exports", keys["exports"]) / ex["files"]["stl"]["name"]
        out = self.apath(p, "slice", keys["slice"])
        s = self.slicer_info(refresh=True)
        if self.keys(p)["slice"] != keys["slice"]:
            raise StudioError("Slicer presets changed while the pipeline was running.", "Run again to slice with the presets now selected.")
        info = slicer.slice_stl(s, stl, out, timeout=self.cfg["slicer"]["timeout_s"])
        info.update({"rev": rev["n"], "stl_sha256": ex["files"]["stl"]["sha256"], "orientation": p["orientation"],
                     "evidence": "simulated"})
        (out / "meta.json").write_text(json.dumps(info, indent=1), encoding="utf-8")

    # ---- side prints: coupon / test piece --------------------------------
    def side_slice(self, p: dict, kind: str) -> dict:
        """Slice the pocket ring (cut from this revision) so its real cost is known."""
        rev, keys = self.rev(p), self.keys(p)
        s = self.slicer_info()
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
            s = self.slicer_info()
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
                   "profile": self.profile(), "note": str(body.get("note", ""))[:1000]}
            if kind == "widths":
                cal = self.calibration.add(self.profile(), body.get("pairs", []), body.get("source", "part"), rec["note"],
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
        reasons, warns = [], []
        for n in NODES:
            st = status[n]
            if st["state"] != "current":
                why = {"stale": f"is stale (last made for r{st.get('last_rev')})", "failed": "failed",
                       "missing": "has not been produced"}[st["state"]]
                if n == "slice" and st.get("unavailable"):
                    why = "is blocked: " + st["unavailable"]
                reasons.append(f"{NODE_LABEL[n]} {why}.")
        ch = self.read(p, "checks", keys["checks"]) if status["checks"]["state"] == "current" else None
        if ch:
            for c in ch["checks"]:
                if c["status"] == "FAIL":
                    reasons.append(f"Check failed: {c['label']} ({c['value']}).")
                elif c["status"] == "WARN":
                    warns.append({"id": c["id"], "label": c["label"], "value": c["value"]})
        # a coupon calibrates the printer; only a result from this part speaks for this revision
        physical = [e for e in p["evidence"] if e["rev"] == p["head"] and (e["kind"] == "fit" or e.get("source") == "part")]
        level = "Geometry computed · slice simulated · " + ("physical result recorded for this revision" if physical else "not physically validated")
        return {"ready": not reasons, "reasons": reasons, "warnings": warns, "evidence_level": level, "physical": len(physical)}

    def approve(self, p: dict, acknowledged: list, note: str = "") -> dict:
        with self.lock(p["id"]):
            p = self.load(p["id"])
            status = self.status(p)
            g = self.gate(p, status)
            if not g["ready"]:
                raise StudioError("This revision cannot be released yet.", " ".join(g["reasons"]), status=409)
            missing = [w["label"] for w in g["warnings"] if w["id"] not in (acknowledged or [])]
            if missing:
                raise StudioError("Every warning must be acknowledged before release.", "Unacknowledged: " + ", ".join(missing) + ".", status=409)
            keys, rev = self.keys(p), self.rev(p)
            rel = self.dir(p["id"]) / "releases" / f"r{rev['n']:02d}-{keys['exports'][:6]}"
            shutil.rmtree(rel, ignore_errors=True)
            rel.mkdir(parents=True)
            ex = self.read(p, "exports", keys["exports"])
            sl = self.read(p, "slice", keys["slice"])
            ch = self.read(p, "checks", keys["checks"])
            files = {}
            for kind in ("step", "stl"):
                if kind not in ex["files"]:
                    continue
                src = self.apath(p, "exports", keys["exports"]) / ex["files"][kind]["name"]
                shutil.copyfile(src, rel / src.name)
                files[src.name] = ex["files"][kind]["sha256"]
            sdir = self.apath(p, "slice", keys["slice"])
            for fname, target in ((sl.get("threemf"), f"{p['id']}_r{rev['n']:02d}_sliced.3mf"), (sl.get("gcode"), f"{p['id']}_r{rev['n']:02d}.gcode")):
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
                "orientation": p["orientation"], "slicer": {k: sl.get(k) for k in ("slicer_version", "presets", "time_s", "filament_g", "layers", "support_used")}
                          | {k: sl[k] for k in ("slicer_kind", "slicer_name") if k in sl},
                "checks": [{k: c[k] for k in ("id", "label", "status", "value", "evidence")} for c in ch["checks"]],
                "acknowledged_warnings": [w for w in g["warnings"]], "note": note, "evidence_level": g["evidence_level"],
                "documents": sorted(documents),
                "physical_evidence": [e for e in p["evidence"] if e["rev"] == rev["n"] and (e["kind"] == "fit" or e.get("source") == "part")],
                "limits": ["Slicer output is a simulation, not a print.", "No structural analysis was performed.",
                           "Fit yield is a statistical model; see checks for the source of each input."]
                          + (["Mesh design (OpenSCAD): no STEP file and no B-rep checks."] if getattr(self.recipe(p), "mesh", False) else []),
            }
            (rel / "MANIFEST.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
            (rel / "REPORT.md").write_text(self._report(p, manifest), encoding="utf-8")
            p["approvals"].append({"rev": rev["n"], "ts": manifest["approved"], "keys": keys, "release": rel.name, "note": note,
                                   "acknowledged": [w["id"] for w in g["warnings"]]})
            self.decide(p, "approval", f"r{rev['n']} approved and released as {rel.name}. {g['evidence_level']}.")
            self.save(p)
            return {"release": rel.name, "manifest": manifest}

    def _report(self, p, m) -> str:
        t = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["approved"]))
        s = m["slicer"]
        lines = [f"# {m['name']} — release r{m['revision']:02d}", "", f"Approved {t}. Units: mm. **{m['evidence_level']}.**", "",
                 "## Files", ""] + [f"- `{k}` — sha256 `{v[:16]}…`" for k, v in m["files"].items()] + ["",
                 "## Source", "", f"- Recipe `{m['recipe']}` @ `{m['recipe_sha']}`, {m['kernel']}",
                 f"- Print orientation: {m['orientation']}", "",
                 "## Parameters", "", "| Parameter | Value | Source |", "|---|---|---|"]
        r = self.recipes[m["recipe"]]
        for k, v in m["values"].items():
            sp = r.spec(k)
            lines.append(f"| {sp.label} | {v:g} {sp.unit} | {m['provenance'].get(k, {}).get('source', 'assumed')} |")
        lines += ["", "## Checks", "", "| Check | Result | Value | Evidence |", "|---|---|---|---|"]
        lines += [f"| {c['label']} | {c['status']} | {c['value']} | {c['evidence']} |" for c in m["checks"]]
        if m["acknowledged_warnings"]:
            lines += ["", "Warnings acknowledged at approval: " + ", ".join(w["label"] for w in m["acknowledged_warnings"]) + "."]
        if s.get("time_s"):
            lines += ["", "## Slice (simulated)", "", f"- {s.get('slicer_name') or 'Bambu Studio'} {s['slicer_version']}: {s['time_s']/60:.0f} min, {s['filament_g']:.1f} g, {s['layers']} layers, supports: {'yes' if s.get('support_used') else 'no'}",
                      "- Presets: " + " · ".join(v["name"] for v in s["presets"].values())]
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
            raise StudioError("That file is not a FORM project archive.", "Choose a .formproj file exported from FORM.")
        if p.get("schema") != SCHEMA or p.get("recipe") not in self.recipes:
            raise StudioError("This archive was made by an incompatible version of FORM.")
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
        tmp.replace(target)
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
        fit = self.fit(p)
        costs = self.costs(p)
        out = {
            "project": {k: v for k, v in p.items() if k != "produced"},
            "recipe": recipe.public(), "status": status, "approval": self.approval_state(p, status),
            "gate": self.gate(p, status), "fit": fit, "actions": fit_mod.next_actions(fit, costs), "costs": costs,
            "calibration": {"profile": self.profile(), "correction": self.calibration.correction(self.profile()),
                            "records": [r for r in self.calibration.records() if r["profile"] == self.profile()][-20:]},
            "checks": self.read(p, "checks", keys["checks"]) if status["checks"]["state"] == "current" else None,
            "slice": self.read(p, "slice", keys["slice"]) if status["slice"]["state"] == "current" else None,
            "exports": self.read(p, "exports", keys["exports"]) if status["exports"]["state"] == "current" else None,
            "releases": sorted(d.name for d in (self.dir(pid) / "releases").glob("r*")) if (self.dir(pid) / "releases").exists() else [],
            "recovered": p.get("_recovered"),
        }
        from . import maker_docs
        out["documents"] = maker_docs.available(self, p)          # maker documents the working files can produce
        return out

    def layers(self, p: dict) -> list:
        key = self.keys(p)["slice"]
        if key not in self._layers_cache:
            meta = self.read(p, "slice", key)
            if not meta:
                raise StudioError("There is no current slice to inspect.", "Run the pipeline first.", status=409)
            self._layers_cache.clear()
            self._layers_cache[key] = slicer.parse_layers(self.apath(p, "slice", key) / meta["gcode"], meta.get("slicer_kind"))
        return self._layers_cache[key]
