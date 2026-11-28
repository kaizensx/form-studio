"""Kernel geometry for direction I's mockups: a NEMA 17 motor mount, built with build123d (OCCT), stage by stage."""
import json, sys, math
from build123d import *
out = sys.argv[1]
W, D, T, H = 56.0, 52.0, 6.0, 62.0          # width, depth, plate thickness, height
BZ = 35.0                                   # bore centre height
stages = []
base = Pos(0, D/2, T/2) * Box(W, D, T)
stages.append(("base", base))
up = base + Pos(0, D - T/2, H/2) * Box(W, T, H)
stages.append(("upright", up))
gz, gy = 38.0, 32.0
g = up
for x in (-W/2, W/2 - 5.0):
    sk = Plane(origin=(x + 5.0, D - T, T), x_dir=(0, -1, 0), z_dir=(-1, 0, 0)) * Polygon((0, 0), (gy, 0), (0, gz), align=None)
    g = g + extrude(sk, 5.0)
stages.append(("gussets", g))
bore = g - Pos(0, D - T/2, BZ) * Rot(90, 0, 0) * Cylinder(11.0, T * 3)
stages.append(("bore", bore))
h = bore
for dx in (-15.5, 15.5):
    for dz in (-15.5, 15.5):
        h = h - Pos(dx, D - T/2, BZ + dz) * Rot(90, 0, 0) * Cylinder(1.7, T * 3)
stages.append(("screws", h))
s = h
for x in (-13.0, 13.0):
    s = s - Pos(x, 20, T/2) * extrude(SlotOverall(16, 5.5, rotation=90), T * 3, both=True)
stages.append(("slots", s))
inner = [e for e in s.edges() if abs(e.center().Y - (D - T)) < 1e-6 and abs(e.center().Z - T) < 1e-6 and e.length > 20]
f = fillet(inner, 4.0)
stages.append(("fillet", f))
outer = [e for e in f.edges().filter_by(Axis.X) if e.length > W - 1 and (abs(e.center().Z - H) < 1e-6 or (abs(e.center().Y) < 1e-6))]
c = chamfer(outer, 0.8)
stages.append(("chamfer", c))
meta = {"stages": []}
for i, (n, sh) in enumerate(stages, 1):
    export_stl(sh, f"{out}/s{i}.stl", tolerance=0.01, angular_tolerance=0.08)
    bb = sh.bounding_box()
    meta["stages"].append({"n": n, "vol_mm3": sh.volume, "faces": len(sh.faces()), "bbox": [bb.size.X, bb.size.Y, bb.size.Z]})
final = stages[-1][1]
export_step(final, f"{out}/mount.step")
com = final.center(CenterOf.MASS)
meta["com"] = [com.X, com.Y, com.Z]; meta["area_mm2"] = final.area
print(json.dumps(meta, indent=1)); json.dump(meta, open(f"{out}/meta.json", "w"), indent=1)
