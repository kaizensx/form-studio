"""Derived meshes for the mockups: an ILLUSTRATIVE stress field (not FEA) and a real z-map stock-removal simulation."""
import sys, json, numpy as np, trimesh
from scipy import ndimage
out = sys.argv[1]
W, D, T, H, BZ = 56.0, 52.0, 6.0, 62.0, 35.0
m = trimesh.load(f"{out}/s8.stl")
# ---------- illustrative stress field ----------
v, f = trimesh.remesh.subdivide_to_size(m.vertices, m.faces, max_edge=0.6)
x, y, z = v.T
def g(d, s): return np.exp(-(d / s) ** 2)
r = np.hypot(x, z - BZ); th = np.arctan2(z - BZ, x)
onup = (y > D - T - 0.01) & (np.abs(x) < W / 2 - 0.01) & (z < H - 0.01)
bore = onup * 0.55 * g(np.clip(r - 11, 0, None), 3.2) * (0.55 + 0.45 * np.cos(2 * th) ** 2) * (0.6 + 0.4 * (z < BZ))
root = 0.95 * g(np.hypot(y - (D - T - 1.2), z - (T + 1.2)) - 2.2, 2.6) * (0.55 + 0.45 * g(np.abs(x) - 6, 16)) * (np.abs(x) < W / 2 - 5.0)
hyp = np.abs((y - (D - T)) / 32.0 * -1 + (z - T) / 38.0 - 1) * 24.0    # distance-ish from the gusset's free edge
gus = (np.abs(x) > W / 2 - 5.01) * 0.42 * g(hyp, 4.0) * g(np.hypot(y - (D - T - 16), z - (T + 19)), 17)
bend = onup * 0.20 * np.clip((BZ + 12 - z) / 40, 0, 1) * (z > T)
scr = 0
for dx in (-15.5, 15.5):
    for dz in (-15.5, 15.5):
        scr = scr + onup * 0.30 * g(np.clip(np.hypot(x - dx, z - BZ - dz) - 1.7, 0, None), 1.4)
slot = 0
for sx in (-13.0, 13.0):
    dd = np.hypot(x - sx, np.clip(np.abs(y - 20) - 5.25, 0, None)) - 2.75
    slot = slot + (z < T + 0.01) * 0.36 * g(np.clip(dd, 0, None), 2.2) * (0.5 + 0.5 * (y > 20))
t = np.clip(bore + root + gus + bend + scr + slot, 0, 1)
ramp = np.array([[0.00, 0.80, 0.765, 0.70], [0.10, 0.60, 0.66, 0.66], [0.30, 0.16, 0.50, 0.62], [0.55, 0.05, 0.72, 0.90], [0.78, 0.30, 0.92, 1.0], [1.0, 1.0, 1.0, 1.0]])
col = np.stack([np.interp(t, ramp[:, 0], ramp[:, k]) for k in (1, 2, 3)], 1)
rgba = np.concatenate([col, t[:, None]], 1)
hm = trimesh.Trimesh(v, f, process=False); hm.visual.vertex_colors = (rgba * 255).astype(np.uint8)
hm.export(f"{out}/heat.ply")
imax = int(np.argmax(t)); print("peak at", v[imax], "verts", len(v))
# ---------- z-map stock simulation (milling frame: back face on the table) ----------
cell = 0.1; mx, my, mz = 2.0, 2.0, 2.0
P = np.stack([-m.vertices[:, 0], H - m.vertices[:, 2], D - m.vertices[:, 1]], 1)        # x, y', z'
SX, SY, SZ = W + 2 * mx, H + 2 * my, D + mz
nx, ny = int(round(SX / cell)), int(round(SY / cell))
gx = (np.arange(nx) + 0.5) * cell - SX / 2; gy = (np.arange(ny) + 0.5) * cell - my
zp = np.zeros((ny, nx), np.float32)
tri = P[m.faces]
for a, b, c in tri:
    n = np.cross(b - a, c - a)
    if abs(n[2]) < 1e-9: continue
    lo = np.minimum(np.minimum(a, b), c); hi = np.maximum(np.maximum(a, b), c)
    i0, i1 = np.searchsorted(gx, [lo[0], hi[0]]); j0, j1 = np.searchsorted(gy, [lo[1], hi[1]])
    if i1 <= i0 or j1 <= j0: continue
    X, Y = np.meshgrid(gx[i0:i1], gy[j0:j1])
    d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
    l1 = ((b[1] - c[1]) * (X - c[0]) + (c[0] - b[0]) * (Y - c[1])) / d
    l2 = ((c[1] - a[1]) * (X - c[0]) + (a[0] - c[0]) * (Y - c[1])) / d
    l3 = 1 - l1 - l2; ins = (l1 >= -1e-6) & (l2 >= -1e-6) & (l3 >= -1e-6)
    Z = l1 * a[2] + l2 * b[2] + l3 * c[2]
    sub = zp[j0:j1, i0:i1]; np.maximum(sub, np.where(ins, Z, 0), out=sub)
tool_r, allow, step = 3.0, 0.4, 2.0
rr = int(round((tool_r + allow) / cell)); yy, xx = np.ogrid[-rr:rr + 1, -rr:rr + 1]
reach = ndimage.grey_dilation(zp, footprint=(xx * xx + yy * yy <= rr * rr)) + allow
levels = np.arange(SZ - step, -1e-6, -step)                                           # 52, 50, ... 0
rough = np.maximum(np.ceil((reach - 1e-4) / step) * step, 0)                          # each cell stops at the level above its floor
rough = np.minimum(rough, SZ)
Lcur, Lprev, yprog = 8.0, 10.0, 30.0                                                 # the pass being cut, and how far along it is
done = np.maximum(rough, Lcur); before = np.maximum(rough, Lprev)
stock = np.where(gy[:, None] < yprog, done, before).astype(np.float32)
removed = 1 - stock.sum() * cell * cell / (SX * SY * SZ)
total_removed = 1 - np.maximum(rough, 0).sum() * cell * cell / (SX * SY * SZ)
print("stock", SX, SY, SZ, "removed so far", removed, "after roughing", total_removed, "progress", removed / total_removed)
st = 2                                                                                 # mesh every 0.2 mm
Zs = stock[::st, ::st]; Xs, Ys = np.meshgrid(gx[::st], gy[::st]); ex = (Zs - zp[::st, ::st])
Zs = np.pad(Zs, 1); Xs = np.pad(Xs, 1, mode='edge'); Ys = np.pad(Ys, 1, mode='edge'); ex = np.pad(ex, 1, mode='edge') + 99 * (np.pad(np.ones_like(ex[1:-1,1:-1] if False else ex), 1) == 0)
h, w = Zs.shape; idx = np.arange(h * w).reshape(h, w)
vv = np.stack([Xs.ravel(), Ys.ravel(), Zs.ravel()], 1)
q = np.stack([idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]], -1).reshape(-1, 4)
ff = np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]])
e = np.clip(ex.ravel() / 6.0, 0, 1); near = (ex.ravel() < allow + step + 0.05)
c0 = np.array([0.74, 0.76, 0.78]); c1 = np.array([0.42, 0.70, 0.76])
cc = np.where(near[:, None], c1, c0) ; a = np.where(near, 0.35, 0.0)
sm = trimesh.Trimesh(vv, ff, process=False); sm.visual.vertex_colors = (np.concatenate([cc, a[:, None]], 1) * 255).astype(np.uint8)
sm.export(f"{out}/stock.ply")
json.dump({"stock": [SX, SY, SZ], "cell": cell, "tool_d": 2 * tool_r, "allow": allow, "step": step, "level": Lcur, "yprog": yprog,
           "removed_frac": float(removed), "rough_total_frac": float(total_removed), "stock_cm3": SX * SY * SZ / 1000}, open(f"{out}/cam.json", "w"), indent=1)
