"""Hidden-line views of the mount from OCCT, as SVG path data: the drawing's views and the iso overlay."""
import sys, json, math, re
from build123d import *
out = sys.argv[1]
part = import_step(f"{out}/mount.step")
az, el = math.radians(-55), math.radians(28)
d = Vector(math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))
T = Vector(0, 26, 29)
views = {"iso": (T + d * 300, (0, 0, 1), T), "front": (Vector(0, -300, 31), (0, 0, 1), Vector(0, 0, 31)),
         "top": (Vector(0, 26, 300), (0, 1, 0), Vector(0, 26, 0)), "right": (Vector(300, 26, 31), (0, 0, 1), Vector(0, 26, 31))}
res = {}
def pts(e, n=None):
    t = e.geom_type
    if t == GeomType.LINE: n = 1
    else: n = max(8, int(e.length / 0.35))
    return [e.position_at(i / n) for i in range(n + 1)]
for name, (o, upv, look) in views.items():
    vis, hid = part.project_to_viewport(tuple(o), upv, tuple(look))
    def path(edges):
        s = []
        for e in edges:
            p = pts(e)
            s.append("M" + "L".join(f"{q.X:.3f} {-q.Y:.3f}" for q in p))
        return "".join(s)
    res[name] = {"vis": path(vis), "hid": path(hid)}
    xs = [q.X for e in vis for q in pts(e)]; ys = [q.Y for e in vis for q in pts(e)]
    res[name]["bbox"] = [min(xs), -max(ys), max(xs), -min(ys)]
    print(name, len(vis), len(hid), res[name]["bbox"])
# where the origin and unit vectors land in the iso view (to register with the render)
o, upv, look = views["iso"]
for nm, p in (("O", (0, 0, 0)), ("X", (10, 0, 0)), ("Y", (0, 10, 0)), ("Z", (0, 0, 10))):
    v, h = Vertex(*p).project_to_viewport(tuple(o), upv, tuple(look)) if False else ([], [])
open(f"{out}/hlr.js", "w").write("const HLR = " + json.dumps(res) + ";\n")
