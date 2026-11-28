"""Robot files from an assembly: URDF and SRDF (ROS, MoveIt) and MJCF (MuJoCo), with meshes per link, checked.

From the design's own declaration (form/recipes/assembly.py):
  * links are the parts; a part fixed to the world is a root (several roots hang from one ``base`` link);
  * joints come from the declared joints with their limits: hinge -> revolute (continuous when the range is a full
    turn or more), slide -> prismatic, fixed and ``Part(attach=)`` -> fixed; a cylindrical joint is a revolute and a
    prismatic joint through a massless link (URDF), two joints on one body (MJCF); a ball joint is three revolute
    joints through two massless links (URDF has no ball joint), a ball joint (MJCF);
  * couplings with a ratio are ``<mimic>`` (URDF) and ``<equality><joint>`` (MJCF); a cam is not written (neither
    format has a non-linear coupling) and is listed;
  * closed loops are ``<equality><connect>`` in MJCF; URDF is a tree, so a loop is listed as not representable;
  * inertia: mass, centre of mass and the inertia tensor about it, in the link frame, from the mass properties of wave
    C (B-rep, the part's sourced density). Link frames are parallel to the assembled frame at rest, at the joint's
    origin, so the tensor is wave C's unchanged and only the centre is shifted;
  * meshes: one visual STL per link (the kernel's tessellation, in mm, scale 0.001) and collision as CoACD convex
    pieces when that engine is installed, else one convex hull per part (or a box), labelled.

Health checks (computed): inertia positive definite, principal moments satisfying the triangle inequality, every mesh
path present, joint axes of unit length, a tree with one root, limits ordered, no two links (not adjacent, not joined
by design) overlapping at the zero pose. The files are then loaded by a parser: yourdfpy or urdfpy (MIT) for the URDF
and MuJoCo (Apache-2.0) for the MJCF, here or in the optional engine environment "robot.mujoco"; without them the
files are validated structurally (XML, the tree, the references), and the result says which.

    from form import robot
    r = robot.write(st, p)            # {"files": {...}, "checks": [...], "validation": {...}}
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

VERSION = 1
ENGINE = "robot.mujoco"
EVIDENCE = "computed (B-rep)"
CHECK_TIMEOUT_S = 180


def _name(s: str) -> str:
    n = re.sub(r"[^A-Za-z0-9_]", "_", str(s)) or "link"
    return n if not n[0].isdigit() else "l_" + n


def _f(x) -> str:
    return f"{float(x):.9g}"


def _v(xs) -> str:
    return " ".join(_f(x) for x in xs)


def _unit(v):
    v = np.asarray(v, float)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


# ── STL ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def write_stl(path: Path, P, T, name: str = "form") -> None:
    P = np.asarray(P, np.float32)
    T = np.asarray(T, np.int64)
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    n = np.cross(b - a, c - a)
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-30)
    rec = np.zeros(len(T), dtype=[("n", "<f4", 3), ("a", "<f4", 3), ("b", "<f4", 3), ("c", "<f4", 3), ("x", "<u2")])
    rec["n"], rec["a"], rec["b"], rec["c"] = n, a, b, c
    with open(path, "wb") as f:
        f.write(name.encode("ascii", "replace")[:80].ljust(80, b" "))
        f.write(np.uint32(len(T)).tobytes())
        f.write(rec.tobytes())


def read_stl(path: Path):
    raw = Path(path).read_bytes()
    n = int(np.frombuffer(raw[80:84], np.uint32)[0])
    rec = np.frombuffer(raw[84:84 + 50 * n], dtype=[("n", "<f4", 3), ("a", "<f4", 3), ("b", "<f4", 3), ("c", "<f4", 3), ("x", "<u2")])
    return np.stack([rec["a"], rec["b"], rec["c"]], 1)


# ── the model: links, joints, frames ─────────────────────────────────────────────────────────────────────────────

def model(spec) -> dict:
    """Links and joints in tree order, with link origins (assembled frame, mm) and everything the writers need."""
    from .recipes.assembly import placement_matrix
    by = {p.id: p for p in spec.parts}
    origin, parent, joint = {}, {}, {}
    for p in spec.parts:
        par, j = spec.link(p.id)
        parent[p.id] = par
        joint[p.id] = j
    order, seen = [], set()

    def visit(pid):
        if pid in seen:
            return
        if parent[pid] and parent[pid] in by:
            visit(parent[pid])
        seen.add(pid)
        order.append(pid)
    for p in spec.parts:
        visit(p.id)
    for pid in order:
        j, par = joint[pid], parent[pid]
        if j is not None and j.kind in ("hinge", "cylindrical", "ball"):
            origin[pid] = np.asarray(j.origin, float)
        else:
            origin[pid] = origin[par] if par else np.zeros(3)
    roots = [pid for pid in order if not parent[pid]]
    return {"order": order, "parent": parent, "joint": joint, "origin": origin, "roots": roots,
            "place": {pid: placement_matrix(by[pid]) for pid in order}, "label": {p.id: p.label for p in spec.parts}}


def _mimic(spec, jid):
    return next((c for c in spec.couplings if c.follower == jid), None)


def _conv(kf, kd, ratio, offset):
    """A coupling's ratio and offset (degrees or mm) in SI (rad or m) for follower kind kf and driver kind kd."""
    def si(kind):
        return math.pi / 180 if kind != "slide" else 1e-3
    return ratio * si(kf) / si(kd), offset * si(kf)


# ── URDF ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def urdf(spec, mdl, inertial: dict, meshes: dict, name: str, limits: dict | None = None) -> tuple[str, list]:
    """URDF text and what could not be written. inertial: {pid: {mass_kg, com_mm, inertia_kg_m2}} (assembled frame);
    meshes: {pid: {"visual": rel path, "collision": [rel paths]}}."""
    limits = limits or {}
    rob = ET.Element("robot", name=_name(name))
    notes = []
    base = None
    if len(mdl["roots"]) > 1:
        base = "base"
        ET.SubElement(rob, "link", name=base)
    for pid in mdl["order"]:
        ln = ET.SubElement(rob, "link", name=_name(pid))
        o = mdl["origin"][pid]
        if pid in inertial:
            m = inertial[pid]
            el = ET.SubElement(ln, "inertial")
            ET.SubElement(el, "origin", xyz=_v((np.asarray(m["com_mm"]) - o) / 1000), rpy="0 0 0")
            ET.SubElement(el, "mass", value=_f(m["mass_kg"]))
            I = np.asarray(m["inertia_kg_m2"], float)
            ET.SubElement(el, "inertia", ixx=_f(I[0, 0]), ixy=_f(I[0, 1]), ixz=_f(I[0, 2]), iyy=_f(I[1, 1]),
                          iyz=_f(I[1, 2]), izz=_f(I[2, 2]))
        ms = meshes.get(pid) or {}
        if ms.get("visual"):
            vis = ET.SubElement(ln, "visual")
            ET.SubElement(vis, "origin", xyz="0 0 0", rpy="0 0 0")
            g = ET.SubElement(vis, "geometry")
            ET.SubElement(g, "mesh", filename=ms["visual"], scale="0.001 0.001 0.001")
        for c in ms.get("collision") or []:
            col = ET.SubElement(ln, "collision")
            ET.SubElement(col, "origin", xyz="0 0 0", rpy="0 0 0")
            g = ET.SubElement(col, "geometry")
            ET.SubElement(g, "mesh", filename=c, scale="0.001 0.001 0.001")
    jd = {j.id: j for j in spec.joints}

    def add_joint(jname, kind, parent_link, child_link, xyz, axis=None, lim=None, mimic=None):
        el = ET.SubElement(rob, "joint", name=jname, type=kind)
        ET.SubElement(el, "parent", link=parent_link)
        ET.SubElement(el, "child", link=child_link)
        ET.SubElement(el, "origin", xyz=_v(xyz), rpy="0 0 0")
        if axis is not None:
            ET.SubElement(el, "axis", xyz=_v(_unit(axis)))
        if lim is not None:
            ET.SubElement(el, "limit", **{k: _f(v) for k, v in lim.items()})
        if mimic is not None:
            ET.SubElement(el, "mimic", **mimic)
        return el

    for pid in mdl["order"]:
        j, par = mdl["joint"][pid], mdl["parent"][pid]
        o = mdl["origin"][pid]
        pl = _name(par) if par else base
        po = mdl["origin"][par] if par else np.zeros(3)
        xyz = (o - po) / 1000
        if pl is None:
            continue                                     # the single root
        if j is None or j.kind == "fixed":
            add_joint(_name(j.id) if j is not None else f"{_name(pid)}_fixed", "fixed", pl, _name(pid), xyz)
            continue
        lm = limits.get(j.id) or {}
        eff, vel = float(lm.get("effort", 0.0)), float(lm.get("velocity", 0.0))
        lo, hi = j.range
        mim = None
        c = _mimic(spec, j.id)
        if c is not None and c.kind != "cam":
            r, off = _conv(j.kind, jd[c.driver].kind, c.ratio, c.offset)
            mim = {"joint": _name(c.driver), "multiplier": _f(r), "offset": _f(off)}
        elif c is not None:
            notes.append(f"Cam {c.driver} → {c.follower}: not written (URDF has no non-linear coupling); "
                         f"{c.follower} is an independent joint in the file.")
        if j.kind == "hinge":
            if hi - lo >= 360 - 1e-9:
                add_joint(_name(j.id), "continuous", pl, _name(pid), xyz, j.axis,
                          {"effort": eff, "velocity": vel}, mim)
            else:
                add_joint(_name(j.id), "revolute", pl, _name(pid), xyz, j.axis,
                          {"lower": math.radians(lo), "upper": math.radians(hi), "effort": eff, "velocity": vel}, mim)
        elif j.kind == "slide":
            add_joint(_name(j.id), "prismatic", pl, _name(pid), xyz, j.axis,
                      {"lower": lo / 1000, "upper": hi / 1000, "effort": eff, "velocity": vel}, mim)
        elif j.kind == "cylindrical":
            mid = f"{_name(pid)}__cyl"
            ET.SubElement(rob, "link", name=mid)
            add_joint(_name(j.id), "revolute", pl, mid, xyz, j.axis,
                      {"lower": math.radians(lo), "upper": math.radians(hi), "effort": eff, "velocity": vel}, mim)
            add_joint(f"{_name(j.id)}__slide", "prismatic", mid, _name(pid), (0, 0, 0), j.axis,
                      {"lower": j.range2[0] / 1000, "upper": j.range2[1] / 1000, "effort": eff, "velocity": vel})
            notes.append(f"Cylindrical joint {j.id}: written as a revolute ({_name(j.id)}) and a prismatic "
                         f"({_name(j.id)}__slide) joint through the massless link {mid}.")
        elif j.kind == "ball":
            l1, l2 = f"{_name(pid)}__ball1", f"{_name(pid)}__ball2"
            ET.SubElement(rob, "link", name=l1)
            ET.SubElement(rob, "link", name=l2)
            lim = {"lower": math.radians(lo), "upper": math.radians(hi), "effort": eff, "velocity": vel}
            add_joint(f"{_name(j.id)}__x", "revolute", pl, l1, xyz, (1, 0, 0), lim)
            add_joint(f"{_name(j.id)}__y", "revolute", l1, l2, (0, 0, 0), (0, 1, 0), lim)
            add_joint(f"{_name(j.id)}__z", "revolute", l2, _name(pid), (0, 0, 0), (0, 0, 1), lim)
            notes.append(f"Ball joint {j.id}: URDF has no ball joint; written as three revolute joints (X, Y, Z) through "
                         f"the massless links {l1} and {l2}.")
    for lp in spec.loops:
        notes.append(f"Loop {lp.a} / {lp.b} at ({_v(lp.at)}) mm: not in the URDF (a URDF is a tree); it is in the MJCF "
                     "as an equality constraint.")
    ET.indent(rob)
    head = ('<?xml version="1.0"?>\n<!-- Written by Form Studio from the design\'s assembly declaration. Units: m, kg, '
            'kg·m², rad. Meshes in mm with scale 0.001. Inertia from the B-rep and the part\'s density. -->\n')
    return head + ET.tostring(rob, encoding="unicode") + "\n", notes


def _urdf_joints(text: str) -> list:
    root = ET.fromstring(text)
    return [(j.get("name"), j.get("type"), j.find("parent").get("link"), j.find("child").get("link"))
            for j in root.findall("joint")]


# ── SRDF ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def srdf(spec, mdl, urdf_text: str, name: str, never: list, never_n: int, at_rest: list) -> str:
    root_link = "base" if len(mdl["roots"]) > 1 else _name(mdl["roots"][0])
    rob = ET.Element("robot", name=_name(name))
    js = [x for x in _urdf_joints(urdf_text) if x[1] != "fixed"]
    g = ET.SubElement(rob, "group", name="all")
    for n, _, _, _ in js:
        ET.SubElement(g, "joint", name=n)
    gs = ET.SubElement(rob, "group_state", name="zero", group="all")
    for n, _, _, _ in js:
        ET.SubElement(gs, "joint", name=n, value="0")
    ET.SubElement(rob, "virtual_joint", name="world_joint", type="fixed", parent_frame="world", child_link=root_link)
    from . import motion
    solved = {j for j, _ in motion.Mechanism(spec).unknowns(set())} if spec.loops else set()
    for jid in sorted(solved):
        ET.SubElement(rob, "passive_joint", name=_name(jid))
    done = set()

    def dis(a, b, why):
        k = tuple(sorted((a, b)))
        if k in done:
            return
        done.add(k)
        ET.SubElement(rob, "disable_collisions", link1=k[0], link2=k[1], reason=why)
    for _, _, a, b in _urdf_joints(urdf_text):
        dis(a, b, "Adjacent")
    for m in spec.mates:
        dis(_name(m.a), _name(m.b), "Default")
    for lp in spec.loops:
        dis(_name(lp.a), _name(lp.b), "Default")
    for a, b in at_rest:
        dis(_name(a), _name(b), "Default")
    for a, b in never:
        dis(_name(a), _name(b), "Never")
    ET.indent(rob)
    return ('<?xml version="1.0"?>\n<!-- Written by Form Studio. Adjacent: joined by a joint. Default: joined by design '
            f'(a Mate or a Loop) or touching at rest. Never: no contact at any of {never_n} sampled poses within the '
            'joint limits (sampled, not proven). -->\n' + ET.tostring(rob, encoding="unicode") + "\n")


# ── MJCF ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def mjcf(spec, mdl, inertial: dict, meshes: dict, name: str, limits: dict | None = None) -> tuple[str, list]:
    limits = limits or {}
    mj = ET.Element("mujoco", model=_name(name))
    ET.SubElement(mj, "compiler", angle="radian", meshdir=".", autolimits="true")
    ET.SubElement(mj, "option", gravity="0 0 -9.81")
    asset = ET.SubElement(mj, "asset")
    wb = ET.SubElement(mj, "worldbody")
    notes = []
    for pid in mdl["order"]:
        ms = meshes.get(pid) or {}
        if ms.get("visual"):
            ET.SubElement(asset, "mesh", name=f"{_name(pid)}_visual", file=ms["visual"], scale="0.001 0.001 0.001")
        for k, c in enumerate(ms.get("collision") or []):
            ET.SubElement(asset, "mesh", name=f"{_name(pid)}_col{k}", file=c, scale="0.001 0.001 0.001")
    bodies = {}
    jd = {j.id: j for j in spec.joints}
    for pid in mdl["order"]:
        j, par = mdl["joint"][pid], mdl["parent"][pid]
        o = mdl["origin"][pid]
        po = mdl["origin"][par] if par else np.zeros(3)
        holder = bodies[par] if par else wb
        b = ET.SubElement(holder, "body", name=_name(pid), pos=_v((o - po) / 1000))
        bodies[pid] = b
        if pid in inertial:
            m = inertial[pid]
            I = np.asarray(m["inertia_kg_m2"], float)
            ET.SubElement(b, "inertial", pos=_v((np.asarray(m["com_mm"]) - o) / 1000), mass=_f(m["mass_kg"]),
                          fullinertia=_v([I[0, 0], I[1, 1], I[2, 2], I[0, 1], I[0, 2], I[1, 2]]))
        if j is not None and j.kind != "fixed":
            lo, hi = j.range
            ax = _v(_unit(j.axis))
            if j.kind == "hinge":
                kw = {"range": _v([math.radians(lo), math.radians(hi)])} if hi - lo < 360 - 1e-9 else {"limited": "false"}
                ET.SubElement(b, "joint", name=_name(j.id), type="hinge", axis=ax, pos="0 0 0", **kw)
            elif j.kind == "slide":
                ET.SubElement(b, "joint", name=_name(j.id), type="slide", axis=ax, pos="0 0 0", range=_v([lo / 1000, hi / 1000]))
            elif j.kind == "cylindrical":
                ET.SubElement(b, "joint", name=_name(j.id), type="hinge", axis=ax, pos="0 0 0", range=_v([math.radians(lo), math.radians(hi)]))
                ET.SubElement(b, "joint", name=f"{_name(j.id)}__slide", type="slide", axis=ax, pos="0 0 0",
                              range=_v([j.range2[0] / 1000, j.range2[1] / 1000]))
            elif j.kind == "ball":
                ET.SubElement(b, "joint", name=_name(j.id), type="ball", pos="0 0 0",
                              range=_v([0, math.radians(max(abs(lo), abs(hi)))]))
        ms = meshes.get(pid) or {}
        if ms.get("visual"):
            ET.SubElement(b, "geom", name=f"{_name(pid)}_visual", type="mesh", mesh=f"{_name(pid)}_visual",
                          contype="0", conaffinity="0", group="2", density="0")
        for k, _ in enumerate(ms.get("collision") or []):
            ET.SubElement(b, "geom", name=f"{_name(pid)}_col{k}", type="mesh", mesh=f"{_name(pid)}_col{k}", group="3",
                          density="0")
    con = ET.SubElement(mj, "contact")
    pairs = set()
    for m in spec.mates:
        pairs.add(tuple(sorted((_name(m.a), _name(m.b)))))
    for lp in spec.loops:
        pairs.add(tuple(sorted((_name(lp.a), _name(lp.b)))))
    for a, b in sorted(pairs):
        ET.SubElement(con, "exclude", body1=a, body2=b)
    eq = ET.SubElement(mj, "equality")
    for lp in spec.loops:
        anchor = (np.asarray(lp.at, float) - mdl["origin"][lp.a]) / 1000
        ET.SubElement(eq, "connect", body1=_name(lp.a), body2=_name(lp.b), anchor=_v(anchor))
        if lp.axis is not None:
            notes.append(f"Loop {lp.a} / {lp.b}: MJCF connect keeps the point common; the pin's axis is kept by the "
                         "joints' own axes in a planar linkage, not by the constraint.")
    for c in spec.couplings:
        if c.kind == "cam":
            notes.append(f"Cam {c.driver} → {c.follower}: not written (MJCF couples joints by a polynomial only).")
            continue
        r, off = _conv(jd[c.follower].kind, jd[c.driver].kind, c.ratio, c.offset)
        ET.SubElement(eq, "joint", joint1=_name(c.follower), joint2=_name(c.driver), polycoef=_v([off, r, 0, 0, 0]))
    if not len(con):
        mj.remove(con)
    if not len(eq):
        mj.remove(eq)
    ET.indent(mj)
    return ('<?xml version="1.0"?>\n<!-- Written by Form Studio from the design\'s assembly declaration. Units: m, kg, rad. '
            'Visual geoms in group 2 (no contact), collision geoms in group 3. -->\n' + ET.tostring(mj, encoding="unicode") + "\n"), notes


# ── checks ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _row(id_, label, status, detail, **kw):
    return {"id": id_, "label": label, "status": status, "detail": detail, "evidence": "computed", **kw}


def health(urdf_path: Path, mjcf_path: Path, inertial: dict, moving: list, self_hits: list, limit_rows: list) -> list:
    """The checks named in the module docstring, on the files as written."""
    out = []
    root = ET.parse(urdf_path).getroot()
    bad_pd, bad_tri = [], []
    for ln in root.findall("link"):
        el = ln.find("inertial")
        if el is None:
            continue
        i = el.find("inertia").attrib
        I = np.array([[float(i["ixx"]), float(i["ixy"]), float(i["ixz"])], [float(i["ixy"]), float(i["iyy"]), float(i["iyz"])],
                      [float(i["ixz"]), float(i["iyz"]), float(i["izz"])]])
        w = np.linalg.eigvalsh(I)
        m = float(el.find("mass").get("value"))
        if m <= 0 or w.min() <= 0:
            bad_pd.append(ln.get("name"))
        a, b, c = sorted(w)
        if a + b < c * (1 - 1e-6):
            bad_tri.append(f"{ln.get('name')} ({a:.3g} + {b:.3g} < {c:.3g})")
    n_in = len([ln for ln in root.findall("link") if ln.find("inertial") is not None])
    out.append(_row("robot_inertia_pd", "Inertia is positive definite", "FAIL" if bad_pd else "PASS",
                    ("Not positive definite (or no mass): " + ", ".join(bad_pd)) if bad_pd else
                    f"Mass > 0 and every eigenvalue of the tensor > 0 on all {n_in} links with an inertial."))
    out.append(_row("robot_inertia_triangle", "Principal moments satisfy the triangle inequality", "FAIL" if bad_tri else "PASS",
                    ("Violated: " + "; ".join(bad_tri)) if bad_tri else "I1 + I2 >= I3 for every link (as any real body)."))
    missing_mass = [m for m in moving if m not in inertial]
    out.append(_row("robot_mass", "Every moving link has a mass", "FAIL" if missing_mass else "PASS",
                    ("No material, so no mass or inertia written: " + ", ".join(missing_mass) +
                     ". Choose a material (set_appearance) or pass assume_material for a labelled what-if.") if missing_mass
                    else "Mass and inertia from the B-rep and each part's density (wave C)."))
    miss = []
    base = urdf_path.parent
    for m in root.iter("mesh"):
        if not (base / m.get("filename")).is_file():
            miss.append(m.get("filename"))
    mroot = ET.parse(mjcf_path).getroot()
    for m in mroot.iter("mesh"):
        if m.get("file") and not (mjcf_path.parent / m.get("file")).is_file():
            miss.append(m.get("file"))
    out.append(_row("robot_mesh_paths", "Every mesh path exists", "FAIL" if miss else "PASS",
                    ("Missing: " + ", ".join(miss)) if miss else
                    f"{len(list(root.iter('mesh')))} URDF and {len(list(mroot.iter('mesh')))} MJCF mesh references resolve."))
    bad_ax = []
    for j in root.findall("joint"):
        a = j.find("axis")
        if a is not None:
            n = float(np.linalg.norm([float(x) for x in a.get("xyz").split()]))
            if abs(n - 1) > 1e-6:
                bad_ax.append(f"{j.get('name')} ({n:.6g})")
    out.append(_row("robot_axes", "Joint axes are unit vectors", "FAIL" if bad_ax else "PASS",
                    ("Not normalised: " + ", ".join(bad_ax)) if bad_ax else "Every axis written has length 1 (to 1e-6)."))
    names = [ln.get("name") for ln in root.findall("link")]
    children = [j.find("child").get("link") for j in root.findall("joint")]
    roots = [n for n in names if n not in children]
    dup = len(set(children)) != len(children)
    out.append(_row("robot_tree", "Links form one tree", "FAIL" if (len(roots) != 1 or dup) else "PASS",
                    f"Root{'s' if len(roots) != 1 else ''}: {', '.join(roots) or 'none'}" + ("; a link has two parents" if dup else "")
                    + "." if (len(roots) != 1 or dup) else f"One root ({roots[0]}), {len(names)} links, every link reached once."))
    out.append(_row("robot_self_collision", "No self-collision at the zero pose", "FAIL" if self_hits else "PASS",
                    ("Overlapping at rest (not adjacent, not joined by design): " + "; ".join(self_hits)) if self_hits else
                    "No two links that are neither adjacent nor joined by design overlap at the zero pose (mesh distance)."))
    out += limit_rows
    return out


def _limit_rows(spec, limits: dict) -> list:
    bad = [j.id for j in spec.joints if j.kind != "fixed" and not j.range[0] < j.range[1]]
    rows = [_row("robot_limits", "Joint limits are ordered", "FAIL" if bad else "PASS",
                 ("lower >= upper: " + ", ".join(bad)) if bad else "lower < upper on every moving joint.")]
    unset = [j.id for j in spec.joints if j.kind != "fixed" and not (limits.get(j.id) or {}).get("effort")]
    if unset:
        rows.append(_row("robot_effort", "Effort and velocity limits are stated", "WARN",
                         "Not known from the design, written as 0 (a placeholder a controller must not use): "
                         + ", ".join(unset) + ". Pass limits={joint: {\"effort\": N·m or N, \"velocity\": rad/s or m/s}}."))
    return rows


# ── validation by parsers ────────────────────────────────────────────────────────────────────────────────────────

def _validate_here(urdf_path: Path, mjcf_path: Path) -> dict:
    """Load the files with whatever parser this Python has. Missing parsers are reported, never passed."""
    out = {}
    try:
        import yourdfpy
        u = yourdfpy.URDF.load(str(urdf_path), build_scene_graph=True, load_meshes=True)
        ok = u.validate()
        out["urdf"] = {"parser": f"yourdfpy {getattr(yourdfpy, '__version__', '')}".strip(), "ok": bool(ok),
                       "links": len(u.link_map), "joints": len(u.joint_map), "actuated": len(u.actuated_joint_names)}
    except ImportError:
        try:
            import urdfpy
            u = urdfpy.URDF.load(str(urdf_path))
            out["urdf"] = {"parser": "urdfpy", "ok": True, "links": len(u.links), "joints": len(u.joints)}
        except ImportError:
            pass
        except Exception as e:                                        # noqa: BLE001 - the parser's own verdict
            out["urdf"] = {"parser": "urdfpy", "ok": False, "error": f"{type(e).__name__}: {e}"}
    except Exception as e:                                            # noqa: BLE001
        out["urdf"] = {"parser": "yourdfpy", "ok": False, "error": f"{type(e).__name__}: {e}"}
    try:
        import mujoco
        m = mujoco.MjModel.from_xml_path(str(mjcf_path))
        d = mujoco.MjData(m)
        mujoco.mj_forward(m, d)
        ncon0 = int(d.ncon)
        steps = int(round(1.0 / m.opt.timestep))
        for _ in range(steps):
            mujoco.mj_step(m, d)
        qv = float(np.max(np.abs(d.qvel))) if m.nv else 0.0
        fin = bool(np.all(np.isfinite(d.qpos)))
        out["mjcf"] = {"parser": f"MuJoCo {mujoco.__version__}", "ok": True, "bodies": int(m.nbody), "joints": int(m.njnt),
                       "dof": int(m.nv), "contacts_at_zero": ncon0, "simulated_s": round(steps * m.opt.timestep, 3),
                       "finite_after": fin, "max_joint_speed_after": round(qv, 6),
                       "evidence": "simulated (MuJoCo, 1 s under gravity from the zero pose, joints unactuated)"}
    except ImportError:
        pass
    except Exception as e:                                            # noqa: BLE001
        out["mjcf"] = {"parser": "MuJoCo", "ok": False, "error": f"{type(e).__name__}: {e}"}
    return out


def _validate_engine(urdf_path: Path, mjcf_path: Path, cfg) -> dict:
    from . import engines, use
    if not use.on(ENGINE, cfg):
        return {}
    py = engines.python(ENGINE, cfg)
    if py is None:
        return {}
    r = subprocess.run([str(py), "-m", "form.robot", "validate", str(urdf_path), str(mjcf_path)], env=engines.child_env(),
                       capture_output=True, text=True, timeout=CHECK_TIMEOUT_S)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
        for v in out.values():
            v["where"] = "the robot.mujoco engine's own Python"
        return out
    except (ValueError, IndexError):
        return {"mjcf": {"parser": "robot.mujoco engine", "ok": False, "error": (r.stderr or r.stdout)[-400:]}}


def structural(urdf_path: Path, mjcf_path: Path) -> dict:
    """Without a parser: XML well-formed, every joint's parent and child a link, every type known, limits on revolute
    and prismatic joints; MJCF well-formed with unique body names and every mesh asset referenced by a geom."""
    out = {}
    try:
        root = ET.parse(urdf_path).getroot()
        links = {ln.get("name") for ln in root.findall("link")}
        errs = []
        for j in root.findall("joint"):
            if j.get("type") not in ("revolute", "continuous", "prismatic", "fixed", "floating", "planar"):
                errs.append(f"{j.get('name')}: type {j.get('type')}")
            for t in ("parent", "child"):
                if j.find(t) is None or j.find(t).get("link") not in links:
                    errs.append(f"{j.get('name')}: {t} is not a link")
            if j.get("type") in ("revolute", "prismatic") and j.find("limit") is None:
                errs.append(f"{j.get('name')}: no limit")
        out["urdf"] = {"parser": "structural (xml.etree)", "ok": not errs, **({"errors": errs} if errs else {}),
                       "links": len(links), "joints": len(root.findall("joint"))}
    except ET.ParseError as e:
        out["urdf"] = {"parser": "structural (xml.etree)", "ok": False, "error": str(e)}
    try:
        root = ET.parse(mjcf_path).getroot()
        names = [b.get("name") for b in root.iter("body")]
        assets = {m.get("name") for m in root.iter("mesh") if m.get("file")}
        used = {g.get("mesh") for g in root.iter("geom") if g.get("mesh")}
        errs = ([f"duplicate body names"] if len(set(names)) != len(names) else []) + \
               [f"geom mesh {u} has no asset" for u in used - assets]
        out["mjcf"] = {"parser": "structural (xml.etree)", "ok": not errs, **({"errors": errs} if errs else {}),
                       "bodies": len(names)}
    except ET.ParseError as e:
        out["mjcf"] = {"parser": "structural (xml.etree)", "ok": False, "error": str(e)}
    return out


def validate(urdf_path: Path, mjcf_path: Path, cfg=None) -> dict:
    got = _validate_here(urdf_path, mjcf_path)
    if "urdf" not in got or "mjcf" not in got:
        try:
            eng = _validate_engine(urdf_path, mjcf_path, cfg)
        except (OSError, subprocess.SubprocessError) as e:
            eng = {"mjcf": {"parser": "robot.mujoco engine", "ok": False, "error": str(e)}}
        for k, v in eng.items():
            got.setdefault(k, v)
    st = structural(urdf_path, mjcf_path)
    for k in ("urdf", "mjcf"):
        if k not in got:
            got[k] = {**st[k], "note": ("No URDF parser here (yourdfpy or urdfpy)" if k == "urdf" else "MuJoCo is not installed")
                      + ": validated structurally only. Settings › Engines & software › MuJoCo adds both."}
        else:
            got[k]["structural"] = st[k]
    return got


# ── on a design ──────────────────────────────────────────────────────────────────────────────────────────────────

def _collision(P, T, how: str, cfg, work: Path):
    from .game import lod
    if how in ("auto", "coacd"):
        try:
            return lod.coacd_parts(P, T, cfg, work=work), "CoACD convex decomposition"
        except RuntimeError as e:
            if how == "coacd":
                from .studio import StudioError
                raise StudioError(str(e))
    if how == "box":
        lo, hi = P.min(0), P.max(0)
        V = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)
        V2, H = lod.hull(V)
        return [{"V": V2, "T": H}], "bounding box"
    parts = lod.convex_parts(P, T)
    return parts, "convex hull per shell (CoACD not installed: concave parts are closed over)"


def _sample_never(spec, mdl, B, n: int, seed: int = 0) -> tuple[list, int]:
    """Pairs of links that come into contact at none of n random poses within the joint limits (couplings applied;
    loops solved when the design has them)."""
    from . import collide, motion
    from .recipes.assembly import placement_matrix
    mech = motion.Mechanism(spec)
    rng = np.random.default_rng(seed)
    ids = [x for x in mdl["order"] if x in B]
    hit = set()
    loop_unk = mech.unknowns(set())                  # a loop's first joint is sampled, the loop solves the rest
    unk = loop_unk[1:] if loop_unk else []
    unk_ids = {j for j, _ in unk}
    done = 0
    for _ in range(n):
        pose = {}
        for j in spec.joints:
            if j.kind == "fixed":
                continue
            v = []
            for k in range(motion._dofs(j)):
                lo, hi = motion._limits(j, k)
                v.append(float(rng.uniform(lo, hi)) if j.id not in unk_ids else 0.0)
            pose[j.id] = v
        pose, info = mech.solve(pose, unk)
        if not info["closed"]:
            continue
        done += 1
        W = {pid: mech.motion(pid, pose) @ placement_matrix(next(x for x in spec.parts if x.id == pid)) for pid in ids}
        for i in range(len(ids)):
            for k in range(i + 1, len(ids)):
                a, b = ids[i], ids[k]
                if (a, b) in hit:
                    continue
                r = collide.query(B[a], B[b], np.linalg.inv(W[b]) @ W[a], 0.5)
                if r.state(2 * B[a].tol) in ("overlap", "contact"):
                    hit.add((a, b))
    never = [(ids[i], ids[k]) for i in range(len(ids)) for k in range(i + 1, len(ids)) if (ids[i], ids[k]) not in hit]
    return never, done


def write(st, p: dict, collision: str = "auto", assume_material: str | None = None, limits: dict | None = None,
          samples: int = 64, rev: int | None = None, name: str | None = None) -> dict:
    """URDF, SRDF and MJCF of a revision with meshes, health checks and parser validation, under
    artifacts/robot/<key>/. Cached by geometry, materials and inputs."""
    from . import collide, fsutil, massprops, motion
    from .studio import H, StudioError
    if collision not in ("auto", "coacd", "hull", "box"):
        raise StudioError("collision is auto, coacd, hull or box.")
    r = st.rev(p, rev)
    gk = st.keys(p, r["n"])["geometry"]
    mats = sorted(((k, (v or {}).get("material")) for k, v in (p.get("parts") or {}).items() if isinstance(v, dict)), key=str)
    key = H("robot", VERSION, gk, p.get("material"), mats, collision, assume_material, limits, samples)
    out = st.dir(p["id"]) / "artifacts" / "robot" / key
    meta = out / "robot.json"
    if meta.is_file():
        try:
            res = json.loads(meta.read_text(encoding="utf-8"))
            if all((out / f).is_file() for f in res["files"].values()):
                return res | {"cached": True}
        except (ValueError, KeyError):
            pass
    t0 = time.perf_counter()
    view = st.view(p, r["n"])
    try:
        spec = motion._spec(view)
    except motion.MotionError as e:
        raise StudioError(str(e), "Robot files need an assembly() with at least one joint that moves.")
    mdl = model(spec)
    mres = massprops.compute(st, p, frame="assembled", rev=r["n"], assume=assume_material)
    inertial = {}
    for x in mres["parts"]:
        if x.get("mass_g") and x["id"]:
            inertial[x["id"]] = {"mass_kg": x["mass_g"] / 1000.0, "com_mm": x["com_mm"],
                                 "inertia_kg_m2": x["inertia_kg_m2"], "material": (x.get("material") or {}).get("id"),
                                 "density_source": (x.get("material") or {}).get("density_source"),
                                 "why": (x.get("material") or {}).get("why")}
    tmp = out.with_name(out.name + ".partial")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "meshes").mkdir(parents=True)
    pm = motion.part_meshes(view)
    tol = float(view.get("tol") or 0.05)
    meshes, col_how, B = {}, {}, {}
    for pid in mdl["order"]:
        if pid not in pm:
            continue
        P, T = pm[pid]
        M = mdl["place"][pid]
        Pw = P @ M[:3, :3].T + M[:3, 3]                   # assembled frame at rest
        Pl = Pw - mdl["origin"][pid]                      # link frame (parallel axes, origin at the joint)
        vis = f"meshes/{_name(pid)}.stl"
        write_stl(tmp / vis, Pl, T, pid)
        cols, how = _collision(Pl, T, collision, st.cfg, tmp)
        files = []
        for k, c in enumerate(cols):
            f = f"meshes/{_name(pid)}_col{k}.stl"
            write_stl(tmp / f, c["V"], c["T"], f"{pid} collision {k}")
            files.append(f)
        meshes[pid] = {"visual": vis, "collision": files}
        col_how[pid] = f"{how}: {len(files)} piece{'s' if len(files) != 1 else ''}"
        B[pid] = collide.Body(P, T, tol)
    nm = name or p["name"]
    utext, unotes = urdf(spec, mdl, inertial, meshes, nm, limits)
    # self-collision at rest and sampled never-colliding pairs
    W0 = {pid: mdl["place"][pid] for pid in B}
    adj = {tuple(sorted((pid, mdl["parent"][pid]))) for pid in mdl["order"] if mdl["parent"][pid]}
    hits, at_rest = [], []
    ids = list(B)
    for i in range(len(ids)):
        for k in range(i + 1, len(ids)):
            a, b = ids[i], ids[k]
            q = collide.query(B[a], B[b], np.linalg.inv(W0[b]) @ W0[a], 0.5)
            s = q.state(2 * tol)
            joined = spec.mate(a, b) is not None or spec.pinned(a, b) is not None
            if s == "overlap" and tuple(sorted((a, b))) not in adj and not joined:
                hits.append(f"{mdl['label'][a]} / {mdl['label'][b]} (at least {q.depth:.2f} mm)")
            if s in ("overlap", "contact") and not joined and tuple(sorted((a, b))) not in adj:
                at_rest.append((a, b))
    never, done = _sample_never(spec, mdl, B, int(samples))
    stext = srdf(spec, mdl, utext, nm, never, done, at_rest)
    mtext, mnotes = mjcf(spec, mdl, inertial, meshes, nm, limits)
    (tmp / "robot.urdf").write_text(utext, encoding="utf-8")
    (tmp / "robot.srdf").write_text(stext, encoding="utf-8")
    (tmp / "robot.xml").write_text(mtext, encoding="utf-8")
    moving = [pid for pid in mdl["order"] if mdl["joint"][pid] is not None and mdl["joint"][pid].kind != "fixed"]
    checks = health(tmp / "robot.urdf", tmp / "robot.xml", inertial, moving, hits, _limit_rows(spec, limits or {}))
    val = validate(tmp / "robot.urdf", tmp / "robot.xml", st.cfg)
    for k, v in val.items():
        checks.append(_row(f"robot_parse_{k}", f"{'URDF' if k == 'urdf' else 'MJCF'} loads in a parser",
                           "PASS" if v.get("ok") else "FAIL",
                           f"{v.get('parser')}: " + ("loaded" if v.get("ok") else (v.get("error") or "; ".join(v.get("errors", [])))),
                           **({"evidence": v["evidence"]} if v.get("evidence") else {})))
    shutil.rmtree(out, ignore_errors=True)
    fsutil.replace(tmp, out)
    files = {"urdf": "robot.urdf", "srdf": "robot.srdf", "mjcf": "robot.xml"}
    res = {"project": p["id"], "rev": r["n"], "key": key, "dir": str(out), "evidence": EVIDENCE,
           "files": files, "paths": {k: str(out / v) for k, v in files.items()},
           "meshes": {pid: m for pid, m in meshes.items()}, "collision": col_how,
           "links": [{"part": pid, "link": _name(pid), "parent": mdl["parent"][pid] or ("base" if len(mdl["roots"]) > 1 else ""),
                      "origin_mm": [float(x) for x in mdl["origin"][pid]],
                      "inertial": ({"mass_kg": inertial[pid]["mass_kg"],
                                    "com_link_mm": [float(x) for x in np.asarray(inertial[pid]["com_mm"]) - mdl["origin"][pid]],
                                    "inertia_kg_m2": inertial[pid]["inertia_kg_m2"], "material": inertial[pid]["material"],
                                    "density_source": inertial[pid]["density_source"], "why": inertial[pid]["why"]}
                                   if pid in inertial else None)} for pid in mdl["order"]],
           "checks": checks, "validation": val, "srdf_never": {"pairs": [list(x) for x in never], "poses_sampled": done},
           "notes": unotes + mnotes + (["Effort and velocity are not known from the design."] if not limits else []),
           "seconds": round(time.perf_counter() - t0, 2)}
    res["text"] = text(res)
    tmpm = meta.with_name("robot.json.tmp")
    tmpm.write_text(json.dumps(res, indent=1), encoding="utf-8")
    fsutil.replace(tmpm, meta)
    return res | {"cached": False}


def headline(res: dict) -> str:
    bad = [c for c in res["checks"] if c["status"] == "FAIL"]
    v = res["validation"]
    how = ", ".join(f"{k.upper()} {x.get('parser', '').split(' (')[0]}" for k, x in v.items())
    return (f"{len(res['links'])} links · " + (f"{len(bad)} check{'s' if len(bad) != 1 else ''} failed" if bad else "checks pass")
            + f" · parsed by {how}")


def text(res: dict) -> str:
    out = [f"Robot files for r{res['rev']:02d} in {res['dir']}: robot.urdf, robot.srdf, robot.xml (MJCF), "
           f"{len(res['links'])} links."]
    for c in res["checks"]:
        out.append(f"{c['label']}: {c['status']}. {c['detail']}")
    out += res["notes"]
    return " ".join(out)


if __name__ == "__main__":                       # the robot.mujoco engine's own Python runs this
    import sys
    if len(sys.argv) == 4 and sys.argv[1] == "validate":
        print(json.dumps(_validate_here(Path(sys.argv[2]), Path(sys.argv[3]))))
        sys.exit(0)
    sys.exit("usage: python -m form.robot validate <robot.urdf> <robot.xml>")
