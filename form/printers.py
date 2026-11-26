"""Every printer the person has set up, in every installed slicer, and which one a design uses.

A printer is a printer preset of one slicer: the person's own (user presets) and the system presets they enabled
in that slicer. Read-only: FORM never writes a slicer's files.

    Bambu Studio, OrcaSlicer and its forks   <config>/user/<id>/machine/*.json, and the system printers enabled in
                                             <App>.conf "models" ([{model, nozzle_diameter: "0.2;0.4", vendor}])
                                             found as JSON (<config>/system/<vendor>/machine, resources/profiles)
                                             or in packed <vendor>.opc caches (OrcaSlicer 2.5+)
    PrusaSlicer, SuperSlicer, QIDISlicer     <config>/printer/*.ini, and the vendor printers enabled in
                                             <App>.ini [vendor:<Id>] (model = "0.4; 0.6") from the vendor bundles

Filaments and processes offered for a printer are the ones its slicer would offer: compatible_printers names it
(or the system printer it inherits from), or compatible_printers_condition holds for it (form/adapters/condition.py;
a condition FORM cannot evaluate is listed and marked "not checked"). Filaments are limited to the ones enabled
in the slicer when it keeps such a list.

The choice:
    per design       project.json "printer": {kind, machine, process, filament}
    default          studio.toml [printer] slicer / machine / process / filament (written by `form printers use --default`)
    otherwise        [slicer].kind and the selection in that slicer, as before.

A choice is applied by giving the slicer adapter those preset names (form.slicer.resolve on a copy of the config),
so slicing, the bed size and the nozzle used by the checks all follow it.

    form printers                         every printer, with slicer, bed and nozzle (JSON)
    form printers options <kind> <name>   the filaments and processes for one printer
    form printers use <kind> <name> [--filament F] [--process P] (--project ID | --default)
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

from . import slicer as slicer_mod
from .adapters import AUTO_ORDER, condition
from .adapters.common import SlicerBlocked

KINDS = ("machine", "process", "filament")
BBL_KINDS = ("bambu", "orca", "elegoo", "snapmaker")
PRUSA_KINDS = ("prusa", "superslicer", "qidi")
LIBRARY = "OrcaFilamentLibrary"
_cache: dict = {}            # (kind, app, config_dir, mtime of the conf) -> inventory, kept for 30 s


class PrinterError(ValueError):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message, self.hint = message, hint


# ---- where each slicer keeps things --------------------------------------------------------------------------

def _config_dir(kind: str, a, cfg: dict) -> Path:
    if kind == "bambu":
        return Path(cfg["slicer"]["config_dir"]).expanduser()
    return Path(a.config_dir(cfg))


def _app(a, cfg: dict) -> str | None:
    try:
        return a.find_app(cfg)
    except Exception:
        return None


# ---- Bambu Studio family --------------------------------------------------------------------------------------

def _json_files(root: Path):
    try:
        return sorted(root.rglob("*.json"))
    except OSError:
        return []


class _BblCatalog:
    """Presets of one Bambu-family slicer, read lazily: user JSON, system JSON, shipped JSON, packed caches."""

    def __init__(self, fam, app: Path, cdir: Path, vendors: set | None):
        self.fam, self.app, self.cdir, self.vendors = fam, app, cdir, vendors
        self._by: dict = {}

    def _want(self, vendor: str) -> bool:
        return self.vendors is None or vendor in self.vendors or vendor == LIBRARY

    def all(self, kind: str) -> dict:
        """name -> (own dict as written, "user" | "system")."""
        if kind in self._by:
            return self._by[kind]
        out: dict = {}

        def add(d, src):
            name = d.get("name") if isinstance(d, dict) else None
            if name and name not in out:
                out[name] = (d, src)
        for f in sorted((self.cdir / "user").glob(f"*/{kind}/*.json")) if (self.cdir / "user").is_dir() else []:
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                d.setdefault("name", f.stem)
                add(d, "user")
            except (OSError, ValueError):
                continue
        roots = [self.cdir / "system"] + (list(self.fam.shipped(self.app)) if self.fam.shipped else [])
        for root in roots:
            if not Path(root).is_dir():
                continue
            for vdir in sorted(Path(root).iterdir()):
                if not vdir.is_dir() or not self._want(vdir.name) or not (vdir / kind).is_dir():
                    continue
                for f in _json_files(vdir / kind):
                    try:
                        d = json.loads(f.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    if isinstance(d, dict):
                        d.setdefault("name", f.stem)
                        d["_vendor"] = vdir.name
                        add(d, "system")
        if self.fam.cache_dirs:
            from .adapters import orca_cache
            for f in orca_cache.cache_files(self.fam.cache_dirs(self.app, self.cdir)):
                if not self._want(f.stem):
                    continue
                try:
                    c = orca_cache.read(f)
                except (orca_cache.CacheError, OSError):
                    continue
                for name, p in c.presets.get(kind, {}).items():
                    d = p.to_json()
                    d["_vendor"] = f.stem
                    add(d, "system")
        self._by[kind] = out
        return out

    def chain_get(self, kind: str, name: str, key: str):
        """A key as the preset states it or inherits it (nearest wins)."""
        seen = 0
        presets = self.all(kind)
        while name and seen < 14:
            hit = presets.get(name)
            if not hit:
                return None
            d = hit[0]
            if key in d:
                return d[key]
            name = d.get("inherits") or ""
            seen += 1
        return None

    def parents(self, kind: str, name: str) -> list:
        out, seen = [], 0
        presets = self.all(kind)
        while name and seen < 14:
            out.append(name)
            hit = presets.get(name)
            name = hit[0].get("inherits") if hit else ""
            seen += 1
        return out


def _first(v):
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v or "").split(";")[0].strip()


def _bbl_flat(a, cdir: Path, app: Path, name: str) -> dict | None:
    from .adapters import _bbl
    fam = a.FAMILY
    packed = None
    if fam.cache_dirs or fam.shipped:
        packed = _bbl.Packed(list(fam.cache_dirs(app, cdir)) if fam.cache_dirs else [],
                             json_roots=list(fam.shipped(app)) if fam.shipped else [])
    try:
        return _bbl.flatten(fam, cdir, "machine", name, packed=packed)
    except (SlicerBlocked, ValueError, OSError):
        return None


def _envelope_bbl(m: dict):
    area = m.get("printable_area") or []
    try:
        xs = [float(p.split("x")[0]) for p in area]
        ys = [float(p.split("x")[1]) for p in area]
        return [max(xs) - min(xs), max(ys) - min(ys), float(m.get("printable_height") or 0)] if area else None
    except (ValueError, IndexError):
        return None


def _bbl_printers(kind: str, a, cfg: dict) -> dict:
    from .adapters import _bbl
    app = _app(a, cfg)
    cdir = _config_dir(kind, a, cfg)
    conf = _bbl.read_conf(cdir, a.FAMILY.conf_name)
    sel = a.FAMILY.selection(conf) if a.FAMILY.selection else {
        "machine": (conf.get("presets") or {}).get("machine", ""), "process": (conf.get("presets") or {}).get("process", ""),
        "filament": ((conf.get("presets") or {}).get("filaments") or [""])[0]}
    models = [m for m in (conf.get("models") or []) if isinstance(m, dict) and m.get("model")]
    vendors = {str(m.get("vendor") or "") for m in models} | ({"BBL"} if kind == "bambu" else set())
    cat = _BblCatalog(a.FAMILY, Path(app or ""), cdir, vendors or None)
    nozzles = {m["model"]: {x.strip() for x in str(m.get("nozzle_diameter") or "").split(";") if x.strip()} for m in models}
    names: list = []
    for name, (d, src) in cat.all("machine").items():
        if src == "user":
            names.append((name, "user"))
            continue
        if str(d.get("instantiation", "true")).lower() == "false":
            continue
        model = d.get("printer_model") or cat.chain_get("machine", name, "printer_model")
        if model not in nozzles:
            continue
        variant = d.get("printer_variant") or _first(d.get("nozzle_diameter") or cat.chain_get("machine", name, "nozzle_diameter"))
        try:
            ok = not nozzles[model] or any(abs(float(variant) - float(n)) < 1e-6 for n in nozzles[model])
        except ValueError:
            ok = True
        if ok:
            names.append((name, "system"))
    if sel.get("machine") and sel["machine"] not in [n for n, _ in names]:
        names.insert(0, (sel["machine"], "user" if sel["machine"] in cat.all("machine") and cat.all("machine")[sel["machine"]][1] == "user" else "system"))
    remembered = {}
    for entry in conf.get("orca_presets") or []:
        if isinstance(entry, dict) and entry.get("machine"):
            remembered[entry["machine"]] = entry
    out = []
    for name, src in names:
        m = _bbl_flat(a, cdir, Path(app or ""), name) if app else None
        if m is None:
            continue
        mem = remembered.get(name) or ({"process": sel.get("process"), "filament": sel.get("filament")}
                                       if name == sel.get("machine") else {})
        out.append({
            "name": name, "source": src, "model": m.get("printer_model") or "",
            "nozzle_mm": _num(_first(m.get("nozzle_diameter") or "0.4")), "envelope_mm": _envelope_bbl(m),
            "selected": name == sel.get("machine"),
            "process": mem.get("process") or m.get("default_print_profile") or "",
            "filament": mem.get("filament") or _first(m.get("default_filament_profile") or ""),
        })
    return {"printers": out, "catalog": cat, "conf": conf, "config_dir": str(cdir), "app": app}


def _compatible(cat_get, preset_cfg: dict, machine_names: list, machine_cfg: dict, kind_key="compatible_printers",
                cond_key="compatible_printers_condition") -> str:
    """"yes", "no" or "unchecked" for one filament or process preset against one printer."""
    lst = preset_cfg.get(kind_key)
    if lst is None:
        lst = cat_get(kind_key)
    if isinstance(lst, str):
        from .adapters.prusa import split_list
        lst = split_list(lst)
    if lst:
        return "yes" if any(n in lst for n in machine_names) else "no"
    cond = preset_cfg.get(cond_key)
    if cond is None:
        cond = cat_get(cond_key)
    if not cond:
        return "yes"
    try:
        return "yes" if condition.evaluate(str(cond), machine_cfg) else "no"
    except condition.Unknown:
        return "unchecked"


def _bbl_options(kind: str, a, cfg: dict, machine: str) -> dict:
    inv = _bbl_printers(kind, a, cfg)
    cat, conf = inv["catalog"], inv["conf"]
    app = Path(inv["app"] or "")
    m = _bbl_flat(a, Path(inv["config_dir"]), app, machine)
    if m is None:
        raise PrinterError(f"Printer “{machine}” was not found in {a.LABEL}.", "Run `form printers` to see the printers there.")
    machine_names = cat.parents("machine", machine) or [machine]
    enabled = set(conf.get("filaments") or []) if isinstance(conf.get("filaments"), list) else set()
    res = {}
    for k in ("process", "filament"):
        rows = []
        for name, (d, src) in cat.all(k).items():
            if str(d.get("instantiation", "true")).lower() == "false":
                continue
            if k == "filament" and enabled and src != "user" and name not in enabled:
                continue
            ok = _compatible(lambda key, n=name, kk=k: cat.chain_get(kk, n, key), d, machine_names, m)
            if ok == "no":
                continue
            rows.append({"name": name, "source": src, "checked": ok == "yes"})
        rows.sort(key=lambda r: (r["source"] != "user", r["name"].lower()))
        res[k] = rows
    entry = next((p for p in inv["printers"] if p["name"] == machine), None) or {}
    return {"processes": res["process"], "filaments": res["filament"],
            "default_process": entry.get("process") or m.get("default_print_profile") or "",
            "default_filament": entry.get("filament") or _first(m.get("default_filament_profile") or "")}


# ---- PrusaSlicer family -----------------------------------------------------------------------------------------

def _prusa_bundle(a, cfg):
    from .adapters import prusa
    app = _app(a, cfg)
    cdir = _config_dir("prusa", a, cfg)
    variant = a._A.v
    ini = prusa.read_ini(cdir / variant.ini) if (cdir / variant.ini).exists() else {}
    bundle = prusa.Bundle(cdir, prusa.shipped_profiles(app, variant.label))
    return prusa, variant, cdir, ini, bundle, app


def _prusa_printers(kind: str, a, cfg: dict) -> dict:
    prusa, variant, cdir, ini, bundle, app = _prusa_bundle(a, cfg)
    sel = ini.get("presets", {})
    enabled = {}
    for sec, body in ini.items():
        if sec.startswith("vendor:"):
            # AppConfig::set_vendors writes "model_<id> = 0.4; 0.6" (older files: "<id> = ...")
            enabled[sec[len("vendor:"):]] = {(m[len("model_"):] if m.startswith("model_") else m): {x.strip() for x in v.split(";") if x.strip()}
                                             for m, v in body.items()}
    names = []
    for f in sorted((cdir / "printer").glob("*.ini")) if (cdir / "printer").is_dir() else []:
        names.append((f.stem, "user"))
    for name, found in bundle.system["printer"].items():
        if name.startswith("*") or not any(Path(fname).stem in enabled for fname, _ in found):
            continue
        try:
            flat = bundle.flatten(variant.label, "printer", name)
        except SlicerBlocked:
            continue
        vend = next(Path(fname).stem for fname, _ in found if Path(fname).stem in enabled)
        models = enabled[vend]
        model, var = flat.get("printer_model", ""), flat.get("printer_variant", "")
        if model in models and (not models[model] or var in models[model]):
            names.append((name, "system"))
    if sel.get("printer") and sel["printer"] not in [n for n, _ in names]:
        names.insert(0, (sel["printer"], "user" if bundle.user("printer", sel["printer"]) else "system"))
    out = []
    for name, src in names:
        try:
            m = bundle.flatten(variant.label, "printer", name)
        except SlicerBlocked:
            continue
        if m.get("printer_technology", "FFF") != "FFF":
            continue
        pts = [tuple(float(c) for c in pt.split("x")) for pt in (m.get("bed_shape") or "").split(",") if "x" in pt]
        env = None
        if pts:
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            env = [max(xs) - min(xs), max(ys) - min(ys), float(m.get("max_print_height") or 0)]
        is_sel = name == sel.get("printer")
        out.append({"name": name, "source": src, "model": m.get("printer_model", ""),
                    "nozzle_mm": _num((m.get("nozzle_diameter") or "0.4").split(",")[0]), "envelope_mm": env,
                    "selected": is_sel,
                    "process": (sel.get("print") if is_sel else "") or m.get("default_print_profile", ""),
                    "filament": (sel.get("filament") if is_sel else "") or
                    (prusa.split_list(m.get("default_filament_profile", "")) or [""])[0]})
    return {"printers": out, "bundle": bundle, "ini": ini, "variant": variant, "config_dir": str(cdir), "app": app}


def _prusa_options(kind: str, a, cfg: dict, machine: str) -> dict:
    from .adapters import prusa
    inv = _prusa_printers(kind, a, cfg)
    bundle, ini, variant = inv["bundle"], inv["ini"], inv["variant"]
    try:
        m = bundle.flatten(variant.label, "printer", machine)
    except SlicerBlocked:
        raise PrinterError(f"Printer “{machine}” was not found in {variant.label}.", "Run `form printers` to see the printers there.")
    m = dict(m, printer_preset=machine)
    machine_names = [machine] + prusa.split_list(m.get("inherits", ""))
    installed = {k for k, v in (ini.get("filaments") or {}).items() if v.strip() not in ("0", "")}
    res = {}
    for k, sec in (("process", "print"), ("filament", "filament")):
        rows, seen = [], set()
        user_dir = bundle.dir / sec
        users = sorted(user_dir.glob("*.ini")) if user_dir.is_dir() else []
        cands = [(f.stem, "user") for f in users] + [(n, "system") for n in bundle.system[sec] if not n.startswith("*")]
        for name, src in cands:
            if name in seen:
                continue
            seen.add(name)
            if k == "filament" and src == "system" and installed and name not in installed:
                continue
            try:
                d = bundle.flatten(variant.label, sec, name)
            except SlicerBlocked:
                continue
            ok = _compatible(lambda key: None, d, machine_names, m)
            if ok == "no":
                continue
            rows.append({"name": name, "source": src, "checked": ok == "yes"})
        rows.sort(key=lambda r: (r["source"] != "user", r["name"].lower()))
        res[k] = rows
    entry = next((p for p in inv["printers"] if p["name"] == machine), None) or {}
    return {"processes": res["process"], "filaments": res["filament"],
            "default_process": entry.get("process") or m.get("default_print_profile", ""),
            "default_filament": entry.get("filament") or (prusa.split_list(m.get("default_filament_profile", "")) or [""])[0]}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---- the inventory ------------------------------------------------------------------------------------------------

def slicer_printers(cfg: dict, kind: str) -> dict:
    """{kind, label, installed, printers: [...], reason} for one slicer."""
    a = slicer_mod.adapter(kind)
    app = _app(a, cfg)
    out = {"kind": kind, "label": a.LABEL, "installed": bool(app), "printers": [], "reason": ""}
    if not app:
        return out
    if not slicer_mod.used(kind, cfg):                  # installed, but its "Use in Form Studio" switch is off
        out.update(off=True, reason=f"{a.LABEL} is switched off in Settings › Engines & software.")
        return out
    try:
        inv = _bbl_printers(kind, a, cfg) if kind in BBL_KINDS else _prusa_printers(kind, a, cfg)
        out["printers"] = inv["printers"]
        out["config_dir"] = inv["config_dir"]
    except Exception as e:                      # one slicer's odd files must never hide the others
        out["reason"] = f"Could not read {a.LABEL} printers: {type(e).__name__}: {e}"
    if not out["printers"] and not out["reason"]:
        out["reason"] = f"No printers set up in {a.LABEL} yet. Open it once and add your printer."
    return out


def inventory(cfg: dict, kinds=None) -> dict:
    """Every printer in every installed slicer, plus the default choice."""
    key = json.dumps([cfg["slicer"].get(k) for k in ("kind", "app", "config_dir")] + [cfg.get("use")] +
                     [cfg["slicer"].get(k) for k in AUTO_ORDER if isinstance(cfg["slicer"].get(k), dict)], sort_keys=True, default=str)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 30 and kinds is None:
        return copy.deepcopy(hit[1])
    slicers = [slicer_printers(cfg, k) for k in (kinds or AUTO_ORDER)]
    printers = []
    for s in slicers:
        for p in s["printers"]:
            printers.append({"id": f"{s['kind']}:{p['name']}", "kind": s["kind"], "slicer": s["label"], **p})
    out = {"printers": printers, "slicers": [{k: v for k, v in s.items() if k != "printers"} | {"count": len(s["printers"])}
                                              for s in slicers], "default": default_choice(cfg)}
    if kinds is None:
        _cache[key] = (time.time(), copy.deepcopy(out))
    return out


def clear_cache() -> None:
    _cache.clear()


def options(cfg: dict, kind: str, machine: str) -> dict:
    """The filaments and processes a printer can use, with the slicer's own defaults for it."""
    if kind not in slicer_mod.SLICERS:
        raise PrinterError(f"Unknown slicer “{kind}”.", "Known: " + ", ".join(slicer_mod.SLICERS))
    a = slicer_mod.adapter(kind)
    if not _app(a, cfg):
        raise PrinterError(f"{a.LABEL} is not installed.")
    if not slicer_mod.used(kind, cfg):
        raise PrinterError(f"{a.LABEL} is switched off in Settings › Engines & software.", "Turn “Use in Form Studio” on for it.")
    fn = _bbl_options if kind in BBL_KINDS else _prusa_options
    out = fn(kind, a, cfg, machine)
    out.update(kind=kind, machine=machine, slicer=a.LABEL)
    return out


# ---- choices ----------------------------------------------------------------------------------------------------

def normalise(choice) -> dict | None:
    if not isinstance(choice, dict) or not choice.get("kind") or not choice.get("machine"):
        return None
    return {"kind": str(choice["kind"]), "machine": str(choice["machine"]),
            "process": str(choice.get("process") or ""), "filament": str(choice.get("filament") or "")}


def default_choice(cfg: dict) -> dict | None:
    p = cfg.get("printer") or {}
    return normalise({"kind": p.get("slicer"), "machine": p.get("machine"), "process": p.get("process"),
                      "filament": p.get("filament")})


def apply(cfg: dict, choice: dict) -> dict:
    """A copy of the config whose slicer settings select exactly this printer, filament and process."""
    c = {k: (copy.deepcopy(v) if isinstance(v, dict) else v) for k, v in cfg.items()}
    s = c["slicer"]
    kind = choice["kind"]
    s["kind"] = kind
    names = {k: choice.get(k) or "auto" for k in KINDS}
    if kind == "bambu":
        s.update(names)
    else:
        sub = dict(s.get(kind) or {}) if isinstance(s.get(kind), dict) else {}
        sub.update(names)
        s[kind] = sub
    return c


def complete(cfg: dict, choice: dict) -> dict:
    """Fill in a missing filament or process with what the slicer would pick for that printer."""
    choice = dict(choice)
    if choice.get("process") and choice.get("filament"):
        return choice
    opts = options(cfg, choice["kind"], choice["machine"])
    if not choice.get("process"):
        choice["process"] = opts["default_process"] or (opts["processes"][0]["name"] if opts["processes"] else "")
    if not choice.get("filament"):
        choice["filament"] = opts["default_filament"] or (opts["filaments"][0]["name"] if opts["filaments"] else "")
    return choice


def resolve(cfg: dict, choice: dict) -> dict:
    """What a slice with this choice would use (form.slicer.resolve on the applied config)."""
    out = slicer_mod.resolve(apply(cfg, choice))
    out["choice"] = dict(choice)
    return out


def validate(cfg: dict, choice) -> dict:
    """A complete choice that resolves, or PrinterError naming what is wrong."""
    c = normalise(choice)
    if c is None:
        raise PrinterError("Name a slicer (kind) and a printer (machine).", "Run `form printers` to see them.")
    if c["kind"] not in slicer_mod.SLICERS:
        raise PrinterError(f"Unknown slicer “{c['kind']}”.", "Known: " + ", ".join(slicer_mod.SLICERS))
    c = complete(cfg, c)
    r = resolve(cfg, c)
    if not r.get("available"):
        raise PrinterError(r.get("reason") or "That printer cannot be used.", "Pick another filament or process for it.")
    return c


def set_default(cfg: dict, choice) -> dict:
    """Write the default printer to studio.toml [printer] (backed up first). None clears it."""
    from . import config_edit
    if choice is None:
        values = {"printer.slicer": "", "printer.machine": "", "printer.process": "", "printer.filament": ""}
    else:
        c = validate(cfg, choice)
        values = {"printer.slicer": c["kind"], "printer.machine": c["machine"], "printer.process": c["process"],
                  "printer.filament": c["filament"]}
    done = config_edit.set_values(cfg, values)
    clear_cache()
    return {**done, "default": default_choice(cfg)}


def describe(choice: dict | None, resolved: dict | None = None) -> str:
    if not choice:
        return ""
    label = slicer_mod.label(choice["kind"])
    return f"{choice['machine']} · {choice.get('filament') or 'auto'} · {choice.get('process') or 'auto'} ({label})"


# ---- CLI ------------------------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    import argparse
    import sys
    from . import config
    ap = argparse.ArgumentParser(prog="form printers", description="The printers set up in your slicers, and which one Form Studio uses.")
    sub = ap.add_subparsers(dest="cmd")
    o = sub.add_parser("options", help="filaments and processes for one printer")
    o.add_argument("kind")
    o.add_argument("machine")
    u = sub.add_parser("use", help="use a printer for one project or as the default")
    u.add_argument("kind")
    u.add_argument("machine")
    u.add_argument("--filament", default="")
    u.add_argument("--process", default="")
    where = u.add_mutually_exclusive_group(required=True)
    where.add_argument("--project")
    where.add_argument("--default", action="store_true")
    c = sub.add_parser("clear", help="forget the printer of a project, or the default")
    cw = c.add_mutually_exclusive_group(required=True)
    cw.add_argument("--project")
    cw.add_argument("--default", action="store_true")
    a = ap.parse_args(argv)
    cfg = config.load()

    def out(d):
        print(json.dumps(d, indent=1, ensure_ascii=False, default=str))
    try:
        if a.cmd is None:
            out(inventory(cfg))
            return 0
        if a.cmd == "options":
            out(options(cfg, a.kind, a.machine))
            return 0
        if a.cmd in ("use", "clear"):
            choice = None if a.cmd == "clear" else {"kind": a.kind, "machine": a.machine, "process": a.process, "filament": a.filament}
            if a.default:
                out(set_default(cfg, choice))
                return 0
            from .studio import Studio, StudioError
            st = Studio(cfg)
            try:
                out(st.set_printer(a.project, choice, by="cli"))
            except StudioError as e:
                out({"error": e.public()})
                return 2
            return 0
    except PrinterError as e:
        out({"error": {"message": e.message, **({"hint": e.hint} if e.hint else {})}})
        return 2
    except Exception as e:                                          # config_edit.ConfigError and the like
        out({"error": {"message": str(getattr(e, "message", e)), "hint": getattr(e, "hint", "")}})
        return 2
    print("unknown command", file=sys.stderr)
    return 2


# ---- engine routes (form/server.py hands these over) -------------------------------------------------------------
#   GET  /api/printers?project=<id>&refresh=1     every printer, the default, and the project's choice
#   GET  /api/printers/options?kind=&machine=     filaments and processes for one printer
#   POST /api/printers/use {kind, machine, process?, filament?, project? | default: true, clear?: true}

def _studio_error(e):
    from .studio import StudioError
    if isinstance(e, PrinterError):
        return StudioError(e.message, e.hint)
    return StudioError(str(getattr(e, "message", e)), getattr(e, "hint", ""))


def route_get(st, path: str, q: dict):
    if path == "/api/printers":
        if q.get("refresh") == "1":
            clear_cache()
        out = inventory(st.cfg)
        pid = q.get("project")
        if pid:
            out["project"] = {"id": pid, **st.printer_state(st.load(pid))}
        return out
    if path == "/api/printers/options":
        try:
            return options(st.cfg, str(q.get("kind") or ""), str(q.get("machine") or ""))
        except PrinterError as e:
            raise _studio_error(e)
    return None


def route_post(st, path: str, body: dict):
    if path != "/api/printers/use":
        return None
    body = body if isinstance(body, dict) else {}
    choice = None if body.get("clear") else {k: body.get(k) for k in ("kind", "machine", "process", "filament")}
    if body.get("default"):
        try:
            done = set_default(st.cfg, choice)
        except Exception as e:                        # PrinterError, config_edit.ConfigError
            raise _studio_error(e)
        st.slicer_info(refresh=True)
        st.activity(None, "printer", "Default printer: " + (describe(done["default"]) or "the slicer's own selection") + ".", by="you")
        return {**done, "inventory": inventory(st.cfg)}
    pid = str(body.get("project") or "")
    if not pid:
        from .studio import StudioError
        raise StudioError("Say which project, or set the default.")
    return st.set_printer(pid, choice)
