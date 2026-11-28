"""Four-bar linkage synthesis: from what the linkage must do to its link lengths, checked and played.

Three ways to say what it must do (``synthesise``):

  motion    three positions of the coupler (a point and the body's angle at each): Burmester theory for three
            positions in the standard dyad form (Erdman and Sandor, Mechanism Design, vol. 1, ch. 8; Sandor and
            Erdman 1984): W (e^{i b_j} - 1) + Z (e^{i a_j} - 1) = d_j for j = 2, 3, linear in the dyad W, Z once the
            two rotations b_2, b_3 of its grounded link are chosen. Two dyads make the four-bar. The choices are free,
            so they are searched on a grid and the linkage that passes the checks with the best transmission angle
            is returned (with the runners-up). The three positions are met exactly (to rounding).
  function  three pairs of input and output angles: Freudenstein's equation K1 cos psi - K2 cos phi + K3 =
            cos(phi - psi), K1 = d / a, K2 = d / c, K3 = (a² - b² + c² + d²) / (2 a c) (Freudenstein 1955; Norton,
            Design of Machinery, eq. 4.8), three linear equations in K1, K2, K3. Exact at the three pairs.
  path      a coupler curve through target points: nine numbers (the two ground pivots, the three moving links and
            the coupler point) found by differential evolution (Storn and Price 1997) and a Nelder-Mead polish on the
            mean squared distance from each target to the curve. An approximation: the error is reported, never
            hidden.

Checks on every result (``analyse``): Grashof's condition and the class (form/motion.py), the transmission angle
over the driven range (below 40 degrees a linkage binds: Norton, sect. 3.3, a guideline), branch defect (the
positions must lie on one assembly mode), order and circuit defect (the driver must reach them 1, 2, 3 in one
direction without passing a dead point).

Verification (``simulate``): the linkage as an Assembly with three hinges and a Loop, played by form/motion.py,
whose Newton solver knows nothing of the synthesis; the traced coupler point (or the output angle) is compared with
the targets. ``source`` writes the linkage as a design with that assembly.

numpy only; no kernel until a design is built.
"""
from __future__ import annotations

import cmath
import math

import numpy as np

VERSION = 1
EVIDENCE_EXACT = "computed (closed form; exact at the precision positions)"
EVIDENCE_PATH = "computed (optimisation; the path is approximated, error stated)"
EVIDENCE_SIM = "computed (kinematics: form/motion.py loop closure)"
MU_MIN = 40.0                        # degrees: the usual lower guide for the transmission angle (Norton, sect. 3.3)
MU_SOURCE = "Norton, Design of Machinery, sect. 3.3: keep the transmission angle above about 40°"
MODES = ("motion", "function", "path")


class LinkageError(ValueError):
    def __init__(self, msg: str, hint: str = ""):
        super().__init__(msg)
        self.hint = hint


def _c(p) -> complex:
    return complex(float(p[0]), float(p[1]))


def _xy(z: complex, n: int = 6) -> list:
    return [round(z.real, n), round(z.imag, n)]


def _wrap(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


# ── kinematics of one linkage (closed form, vectorised) ─────────────────────────────────────────────────────────

def positions(link: dict, theta) -> dict:
    """The linkage at crank angles theta (radians, absolute; an array): A, B, P (complex), the transmission angle
    (radians) and `ok` (the loop closes). Uses the linkage's branch."""
    O2, O4 = _c(link["O2"]), _c(link["O4"])
    a, b, c = float(link["a"]), float(link["b"]), float(link["c"])
    th = np.asarray(theta, float)
    A = O2 + a * np.exp(1j * th)
    D = O4 - A
    dist = np.abs(D)
    ok = (dist <= b + c + 1e-9) & (dist >= abs(b - c) - 1e-9) & (dist > 1e-12)
    ds = np.where(dist > 1e-12, dist, 1.0)
    x = (b * b - c * c + ds * ds) / (2.0 * ds)
    y = float(link.get("branch", 1)) * np.sqrt(np.maximum(b * b - x * x, 0.0))
    B = A + (D / ds) * (x + 1j * y)
    th3 = np.angle(B - A)
    cp = link.get("coupler_point") or [0.0, 0.0]
    P = A + complex(cp[0], cp[1]) * np.exp(1j * th3)
    mu = np.arccos(np.clip((b * b + c * c - ds * ds) / (2.0 * b * c), -1.0, 1.0))
    return {"A": A, "B": B, "P": P, "theta3": th3, "theta4": np.angle(B - O4), "mu": mu, "ok": ok}


def _branch_of(O4: complex, A: complex, B: complex) -> int:
    d, e = O4 - A, B - A
    return 1 if (d.real * e.imag - d.imag * e.real) >= 0 else -1


def _drive(link: dict, th1: float, deltas: list, n: int = 180) -> dict | None:
    """Can the crank reach the positions in order, in one direction, with the loop closed all the way? deltas: the
    crank's rotation from position 1 to each later position (radians). Returns the direction and the sweep."""
    full = bool(positions(link, np.linspace(0, 2 * math.pi, 361))["ok"].all())
    best = None
    for sgn in (1, -1):
        t = [(sgn * d) % (2.0 * math.pi) for d in deltas]
        if any(x < 1e-9 for x in t) or any(t[i] >= t[i + 1] - 1e-9 for i in range(len(t) - 1)):
            continue
        sweep = t[-1]
        if not full and not bool(positions(link, th1 + sgn * np.linspace(0.0, sweep, n))["ok"].all()):
            continue
        if best is None or sweep < best["sweep"]:
            best = {"direction": sgn, "sweep": sweep, "at": [0.0] + [sgn * x for x in t], "full_turn": full}
    return best


def analyse(link: dict, th1: float | None = None, deltas: list | None = None) -> dict:
    """Grashof, transmission angle, the crank's range, and (with the precision positions' crank rotations) the
    branch, order and circuit checks."""
    from .. import motion
    a, b, c, d = (float(link[k]) for k in "abcd")
    g = motion.grashof(a, b, c, d)
    th = np.linspace(0.0, 2.0 * math.pi, 721)
    full = positions(link, th)
    reach = full["ok"]
    turns = bool(reach.all())
    out = {"grashof": {**g, "evidence": "computed (s + l <= p + q)"}, "crank_turns_fully": turns,
           "links_mm": {"crank": round(a, 4), "coupler": round(b, 4), "rocker": round(c, 4), "ground": round(d, 4)}}
    drive = None
    if th1 is not None and deltas:
        drive = _drive(link, th1, deltas)
    if drive:
        rng = th1 + drive["direction"] * np.linspace(0.0, drive["sweep"], 361)
        over = "between the precision positions"
    else:
        rng = th[reach]
        over = "over the crank angles where the loop closes"
    if turns:
        rng, over = th, "over a full turn of the crank"
    mu = np.degrees(positions(link, rng)["mu"]) if len(rng) else np.array([0.0])
    dev = np.minimum(mu, 180.0 - mu)
    out["transmission"] = {"min_deg": round(float(dev.min()), 2), "over": over, "limit_deg": MU_MIN,
                           "status": "PASS" if dev.min() >= MU_MIN else "WARN", "source": MU_SOURCE,
                           "evidence": "computed (closed form)"}
    if th1 is not None and deltas:
        pts = positions({**link}, np.array([th1] + [th1 + x for x in deltas]))
        out["defects"] = {
            "branch": {"status": "PASS", "detail": "every position is on the linkage's one assembly mode"}
            if bool(pts["ok"].all()) else
            {"status": "FAIL", "detail": "a position is not reached on this assembly mode"},
            "order": ({"status": "PASS", "detail": f"the crank reaches the positions in order turning "
                                                     f"{'counter-clockwise' if drive['direction'] > 0 else 'clockwise'}, "
                                                     f"{math.degrees(drive['sweep']):.1f}° from first to last"}
                      if drive else
                      {"status": "FAIL", "detail": "no single direction of the crank reaches the positions in order "
                                                    "without the loop opening (order or circuit defect)"})}
        if drive:
            out["drive"] = {"direction": drive["direction"], "sweep_deg": round(math.degrees(drive["sweep"]), 4),
                            "crank_at_deg": [round(math.degrees(x), 6) for x in drive["at"]]}
    if not turns and reach.any():
        idx = np.where(reach)[0]
        out["crank_range_deg"] = "limited: the loop closes on " + f"{len(idx) / len(th) * 100:.0f} % of a turn"
    return out


def _link(O2: complex, O4: complex, A: complex, B: complex, P: complex | None = None) -> dict:
    a, b, c, d = abs(A - O2), abs(B - A), abs(B - O4), abs(O4 - O2)
    th3 = cmath.phase(B - A)
    cp = ((P - A) * cmath.exp(-1j * th3)) if P is not None else 0j
    return {"O2": [O2.real, O2.imag], "O4": [O4.real, O4.imag], "a": a, "b": b, "c": c, "d": d, "branch": _branch_of(O4, A, B),
            "coupler_point": [cp.real, cp.imag], "theta1": cmath.phase(A - O2)}


# ── three positions of the coupler: Burmester, standard dyad form ────────────────────────────────────────────────

def dyad(delta2: complex, delta3: complex, alpha2: float, alpha3: float, beta2, beta3):
    """W and Z of a dyad for three positions: W (e^{i beta_j} - 1) + Z (e^{i alpha_j} - 1) = delta_j, j = 2, 3.
    beta may be arrays (many free choices at once). Returns (W, Z, determinant)."""
    b2, b3 = np.exp(1j * np.asarray(beta2, float)) - 1.0, np.exp(1j * np.asarray(beta3, float)) - 1.0
    a2, a3 = cmath.exp(1j * alpha2) - 1.0, cmath.exp(1j * alpha3) - 1.0
    det = b2 * a3 - b3 * a2
    safe = np.where(np.abs(det) > 1e-12, det, 1.0)
    return (delta2 * a3 - delta3 * a2) / safe, (b2 * delta3 - b3 * delta2) / safe, det


def three_positions(poses: list, steps: int = 24, keep: int = 5, max_size: float = 6.0,
                    require_crank: bool = False) -> list:
    """Four-bars that carry the coupler through three poses [{"at": [x, y], "angle": degrees}, ...]. Every free
    choice on a grid of `steps` per turn is tried; the ones that pass the branch and order checks are ranked by
    transmission angle, then by size. max_size: the largest link or pivot distance allowed, in units of the poses'
    spread. Returns up to `keep` linkages, best first, each with its analysis."""
    if len(poses) != 3:
        raise LinkageError("Three-position synthesis takes exactly three poses.",
                           'poses=[{"at": [x, y], "angle": deg}, ...]. For more points use mode="path".')
    try:
        P = [_c(p["at"]) for p in poses]
        ang = [math.radians(float(p.get("angle", 0.0))) for p in poses]
    except (KeyError, TypeError, ValueError, IndexError):
        raise LinkageError("Each pose is {\"at\": [x, y], \"angle\": degrees}.") from None
    d2, d3 = P[1] - P[0], P[2] - P[0]
    al2, al3 = _wrap(ang[1] - ang[0]), _wrap(ang[2] - ang[0])
    spread = max(abs(d2), abs(d3), abs(P[2] - P[1]))
    if spread < 1e-9:
        raise LinkageError("The three positions are the same point.", "Move at least one of them.")
    g = np.arange(1, steps) * (2.0 * math.pi / steps)
    B2, B3 = [x.ravel() for x in np.meshgrid(g, g, indexing="ij")]
    sel = np.abs(B2 - B3) > 1e-9
    B2, B3 = B2[sel], B3[sel]
    W, Z, det = dyad(d2, d3, al2, al3, B2, B3)
    good = (np.abs(det) > 1e-6) & (np.abs(W) > 0.02 * spread) & (np.abs(W) < max_size * spread) \
        & (np.abs(Z) < max_size * spread)
    W, Z, B2, B3 = W[good], Z[good], B2[good], B3[good]
    if not len(W):
        raise LinkageError("No dyad of a usable size reaches these three poses.", "Raise max_size, or move a pose.")
    piv = P[0] - Z - W                                    # ground pivot of each dyad
    mov = P[0] - Z                                        # its moving pivot at position 1
    i, j = np.meshgrid(np.arange(len(W)), np.arange(len(W)), indexing="ij")
    i, j = i.ravel(), j.ravel()
    a, c = np.abs(W[i]), np.abs(W[j])
    b, d = np.abs(mov[j] - mov[i]), np.abs(piv[j] - piv[i])
    ok = (b > 0.05 * spread) & (d > 0.05 * spread) & (b < max_size * spread) & (d < max_size * spread)
    # one assembly mode at the three positions
    eb = np.stack([np.ones_like(B2), np.exp(1j * B2), np.exp(1j * B3)])            # crank rotation per position
    Aj = piv[None, :] + W[None, :] * eb                                            # (3, n)
    cr = np.stack([(piv[j] - Aj[k, i]).real * (Aj[k, j] - Aj[k, i]).imag
                   - (piv[j] - Aj[k, i]).imag * (Aj[k, j] - Aj[k, i]).real for k in range(3)])
    ok &= (np.sign(cr[0]) == np.sign(cr[1])) & (np.sign(cr[0]) == np.sign(cr[2])) & (np.abs(cr).min(axis=0) > 1e-9)
    # transmission angle at the three positions (a quick screen; the full range is checked on the survivors)
    mus = []
    for k in range(3):
        dist = np.abs(piv[j] - Aj[k, i])
        mu = np.degrees(np.arccos(np.clip((b * b + c * c - dist * dist) / np.maximum(2 * b * c, 1e-12), -1, 1)))
        mus.append(np.minimum(mu, 180.0 - mu))
    mu3 = np.min(mus, axis=0)
    ok &= mu3 > 15.0
    L = np.sort(np.stack([a, b, c, d]), axis=0)
    grashof = L[0] + L[3] <= L[1] + L[2]
    cranks = grashof & (a <= np.minimum(np.minimum(b, c), d) + 1e-12)
    if require_crank:
        ok &= cranks
    idx = np.where(ok)[0]
    if not len(idx):
        raise LinkageError("No four-bar passes the branch check for these three poses on this grid.",
                           "Raise steps (finer free choices) or max_size, or drop require_crank.")
    size = np.max(np.stack([a, b, c, d]), axis=0)[idx] / spread
    rank = mu3[idx] + 8.0 * cranks[idx] - 2.0 * size
    out, seen = [], []
    for k in idx[np.argsort(-rank)][:400]:
        ii, jj = int(i[k]), int(j[k])
        link = _link(piv[ii], piv[jj], mov[ii], mov[jj], P[0])
        deltas = [float(B2[ii]), float(B3[ii])]
        an = analyse(link, link["theta1"], deltas)
        if an["defects"]["branch"]["status"] != "PASS" or an["defects"]["order"]["status"] != "PASS":
            continue
        sig = tuple(round(x / spread, 2) for x in (link["a"], link["b"], link["c"], link["d"]))
        if sig in seen:
            continue
        seen.append(sig)
        link["deltas"] = deltas
        out.append({"link": link, "analysis": an,
                    "score": an["transmission"]["min_deg"] + (8.0 if an["crank_turns_fully"] else 0.0)
                    - 2.0 * max(sig)})
        if len(out) >= max(keep * 6, 24):
            break
    if not out:
        raise LinkageError("Every candidate has an order or circuit defect: the crank cannot reach the poses 1, 2, 3 "
                           "in one direction on one assembly mode.", "Raise steps or max_size, or change a pose.")
    out.sort(key=lambda r: -r["score"])
    return out[:keep]


# ── three pairs of angles: Freudenstein ──────────────────────────────────────────────────────────────────────────

def freudenstein(pairs: list, ground: float = 100.0) -> dict:
    """Link lengths from three (input angle, output angle) pairs in degrees, both measured from the ground line
    O2 -> O4, counter-clockwise. A negative K1 or K2 means that link points the other way: its length is |d / K| and
    its angle is the given one plus 180°, said in `notes`."""
    if len(pairs) != 3:
        raise LinkageError("Freudenstein's equation takes three (input, output) angle pairs.",
                           "pairs=[[phi1, psi1], [phi2, psi2], [phi3, psi3]] in degrees.")
    d = float(ground)
    if not d > 0:
        raise LinkageError("ground must be positive.")
    ph = [math.radians(float(p[0])) for p in pairs]
    ps = [math.radians(float(p[1])) for p in pairs]
    M = np.array([[math.cos(ps[k]), -math.cos(ph[k]), 1.0] for k in range(3)])
    rhs = np.array([math.cos(ph[k] - ps[k]) for k in range(3)])
    if abs(np.linalg.det(M)) < 1e-10:
        raise LinkageError("These three pairs do not determine a linkage (the equations are dependent).",
                           "Use three distinct input angles and three distinct output angles.")
    K1, K2, K3 = np.linalg.solve(M, rhs)
    if abs(K1) < 1e-9 or abs(K2) < 1e-9:
        raise LinkageError("These pairs need a link of infinite length.", "Change one of the pairs.")
    a, c = d / K1, d / K2                                   # signed
    b2 = a * a + c * c + d * d - 2.0 * a * c * K3
    if b2 <= 1e-12:
        raise LinkageError("These pairs give no real coupler length.", "Change one of the pairs.")
    b = math.sqrt(b2)
    O2, O4 = 0j, complex(d, 0.0)
    A = [O2 + a * cmath.exp(1j * x) for x in ph]
    B = [O4 + c * cmath.exp(1j * x) for x in ps]
    link = _link(O2, O4, A[0], B[0])
    link["deltas"] = [_wrap(ph[1] - ph[0]), _wrap(ph[2] - ph[0])]
    link["deltas"] = [x % (2 * math.pi) for x in link["deltas"]]
    branches = [_branch_of(O4, A[k], B[k]) for k in range(3)]
    notes = []
    if a < 0:
        notes.append("K1 is negative: the crank points opposite to the input angle (its angle is phi + 180°).")
    if c < 0:
        notes.append("K2 is negative: the rocker points opposite to the output angle (its angle is psi + 180°).")
    an = analyse(link, link["theta1"], link["deltas"])
    if len(set(branches)) > 1:
        an["defects"]["branch"] = {"status": "FAIL", "detail": "the three pairs lie on different assembly modes: the "
                                                               "linkage must be taken apart to reach them all"}
    residual = max(abs(abs(B[k] - A[k]) - b) for k in range(3))
    return {"link": link, "analysis": an, "K": [float(K1), float(K2), float(K3)], "notes": notes,
            "signed": {"a": a, "c": c}, "residual_mm": residual,
            "output_offset_deg": 180.0 if c < 0 else 0.0, "input_offset_deg": 180.0 if a < 0 else 0.0}


# ── a coupler curve through target points: optimisation ──────────────────────────────────────────────────────────

def _curve(X: np.ndarray, th: np.ndarray):
    """Coupler curves of many linkages at once. X (p, 9): O2x, O2y, ground angle, a, b, c, d, u, v. Returns P (p, m)
    complex and ok (p, m), for both... one branch (+1); the mirror branch is the same family with v, angle mirrored."""
    O2 = X[:, 0] + 1j * X[:, 1]
    a, b, c, d = (X[:, k][:, None] for k in (3, 4, 5, 6))
    O4 = O2 + X[:, 6] * np.exp(1j * X[:, 2])
    A = O2[:, None] + a * np.exp(1j * (th[None, :] + X[:, 2][:, None]))
    D = O4[:, None] - A
    dist = np.abs(D)
    ok = (dist <= b + c) & (dist >= np.abs(b - c)) & (dist > 1e-9)
    ds = np.where(dist > 1e-9, dist, 1.0)
    x = (b * b - c * c + ds * ds) / (2.0 * ds)
    y = np.sqrt(np.maximum(b * b - x * x, 0.0))
    Bp = A + (D / ds) * (x + 1j * y)
    P = A + (X[:, 7] + 1j * X[:, 8])[:, None] * np.exp(1j * np.angle(Bp - A))
    mu = np.degrees(np.arccos(np.clip((b * b + c * c - ds * ds) / (2.0 * b * c), -1.0, 1.0)))
    return P, ok, np.minimum(mu, 180.0 - mu)


def _path_cost(X: np.ndarray, T: np.ndarray, th: np.ndarray, closed: bool, scale: float) -> np.ndarray:
    P, ok, dev = _curve(X, th)
    d2 = np.abs(T[None, :, None] - P[:, None, :]) ** 2                     # (p, t, m)
    d2 = np.where(ok[:, None, :], d2, np.inf)
    near = d2.argmin(axis=2)
    best = d2.min(axis=2)
    best = np.where(np.isfinite(best), best, (10.0 * scale) ** 2)
    cost = best.mean(axis=1)
    # the targets in order along the curve (one direction, wrapping once on a closed curve)
    m = len(th)
    step = np.diff(near, axis=1)
    fwd = ((step % m) > m // 2).sum(axis=1)
    back = ((-step % m) > m // 2).sum(axis=1)
    cost = cost + (0.05 * scale) ** 2 * np.minimum(fwd, back)
    # a little weight on the transmission angle, so that of two linkages that trace the path the one that moves
    # freely wins (30° here; the check's 40° guide is reported either way)
    short = np.where(ok, np.maximum(0.0, (30.0 - dev) / 30.0), 0.0)
    cost = cost + (0.02 * scale) ** 2 * (short ** 2).mean(axis=1)
    lens = X[:, 3:7]
    srt = np.sort(lens, axis=1)
    if closed:                                                              # the crank must turn fully
        cost = cost + scale ** 2 * np.maximum(0.0, (srt[:, 0] + srt[:, 3] - srt[:, 1] - srt[:, 2]) / scale) ** 2
        cost = cost + scale ** 2 * np.maximum(0.0, (X[:, 3] - srt[:, 0]) / scale) ** 2
        cost = cost + (~ok).mean(axis=1) * scale ** 2
    return cost


def _nelder_mead(f, x0: np.ndarray, step: np.ndarray, iters: int = 1500) -> np.ndarray:
    n = len(x0)
    S = np.vstack([x0] + [x0 + np.eye(n)[k] * step[k] for k in range(n)])
    fs = f(S)
    for _ in range(iters):
        o = np.argsort(fs)
        S, fs = S[o], fs[o]
        if abs(fs[-1] - fs[0]) <= 1e-14 * (abs(fs[0]) + 1e-14):
            break
        cen = S[:-1].mean(axis=0)
        xr = cen + (cen - S[-1])
        fr = f(xr[None])[0]
        if fr < fs[0]:
            xe = cen + 2.0 * (cen - S[-1])
            fe = f(xe[None])[0]
            S[-1], fs[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < fs[-2]:
            S[-1], fs[-1] = xr, fr
        else:
            xc = cen + 0.5 * (S[-1] - cen)
            fc = f(xc[None])[0]
            if fc < fs[-1]:
                S[-1], fs[-1] = xc, fc
            else:
                S[1:] = S[0] + 0.5 * (S[1:] - S[0])
                fs[1:] = f(S[1:])
    return S[np.argmin(fs)]


def path(targets: list, closed: bool = True, seed: int = 1, population: int = 120, generations: int = 600,
         samples: int = 240, restarts: int = 4) -> dict:
    """A four-bar whose coupler point passes near the target points [[x, y], ...] in order. closed: the curve is
    traced by a crank that turns fully (a Grashof crank-rocker or double crank is required). Deterministic for a
    seed. Returns the linkage, the distance from each target to its curve and the RMS and largest error."""
    try:
        T = np.array([_c(p) for p in targets])
    except (TypeError, ValueError, IndexError):
        raise LinkageError("targets is a list of [x, y] points.") from None
    if len(T) < 4:
        raise LinkageError("Path synthesis needs at least four target points.",
                           "Three positions are met exactly by mode=\"motion\" (give each an angle).")
    if len(T) > 60:
        raise LinkageError("At most 60 target points.", "Resample the path: 12 to 24 points describe a coupler curve.")
    cen = T.mean()
    scale = float(np.abs(T - cen).max())
    if scale < 1e-9:
        raise LinkageError("The target points are all the same point.")
    th = np.linspace(0.0, 2.0 * math.pi, samples, endpoint=False)
    lo = np.array([cen.real - 4 * scale, cen.imag - 4 * scale, -math.pi, 0.1 * scale, 0.3 * scale, 0.3 * scale,
                   0.3 * scale, -4 * scale, -4 * scale])
    hi = np.array([cen.real + 4 * scale, cen.imag + 4 * scale, math.pi, 3 * scale, 5 * scale, 5 * scale, 5 * scale,
                   4 * scale, 4 * scale])
    f = lambda X: _path_cost(np.clip(X, lo, hi), T, th, closed, scale)      # noqa: E731
    rng = np.random.default_rng(int(seed))
    best_x, best_f, evals = None, math.inf, 0
    for _ in range(max(1, int(restarts))):
        X = lo + rng.random((population, 9)) * (hi - lo)
        fx = f(X)
        for _g in range(int(generations)):
            idx = np.array([rng.choice(population, 3, replace=False) for _ in range(population)])
            ib = int(np.argmin(fx))
            F = 0.5 + 0.3 * rng.random((population, 1))
            V = X[idx[:, 0]] + F * (X[ib] - X[idx[:, 0]]) + F * (X[idx[:, 1]] - X[idx[:, 2]])   # current-to-best / 1
            cross = rng.random((population, 9)) < 0.9
            cross[np.arange(population), rng.integers(0, 9, population)] = True
            U = np.clip(np.where(cross, V, X), lo, hi)
            fu = f(U)
            better = fu < fx
            X[better], fx[better] = U[better], fu[better]
            evals += population
        k = int(np.argmin(fx))
        x = _nelder_mead(f, X[k].copy(), 0.02 * (hi - lo), 4000)
        fv = float(f(x[None])[0])
        if fv < best_f:
            best_x, best_f = np.clip(x, lo, hi), fv
    x = best_x
    O2 = complex(x[0], x[1])
    O4 = O2 + x[6] * cmath.exp(1j * x[2])
    A1 = O2 + x[3] * cmath.exp(1j * x[2])
    D = O4 - A1
    dist = abs(D)
    xx = (x[4] ** 2 - x[5] ** 2 + dist ** 2) / (2 * dist)
    B1 = A1 + (D / dist) * complex(xx, math.sqrt(max(x[4] ** 2 - xx ** 2, 0.0)))
    P1 = A1 + complex(x[7], x[8]) * cmath.exp(1j * cmath.phase(B1 - A1))
    link = _link(O2, O4, A1, B1, P1)
    link["branch"] = 1
    fine = np.linspace(0.0, 2.0 * math.pi, 3600, endpoint=False)
    pos = positions(link, link["theta1"] + fine)
    Pc = pos["P"][pos["ok"]]
    if not len(Pc):
        raise LinkageError("The search found no linkage that closes.", "Try another seed, or closed=False.")
    dd = np.abs(T[:, None] - Pc[None, :])
    err = dd.min(axis=1)
    an = analyse(link)
    return {"link": link, "analysis": an,
            "error": {"rms_mm": float(np.sqrt((err ** 2).mean())), "max_mm": float(err.max()),
                      "per_target_mm": [round(float(e), 5) for e in err],
                      "relative_to_path_size": float(err.max() / (2.0 * scale)), "evidence": EVIDENCE_PATH,
                      "note": "distance from each target to the nearest point of the coupler curve (3600 samples of "
                              "the crank)"},
            "search": {"method": "differential evolution (current-to-best/1/bin) then Nelder-Mead", "seed": int(seed),
                       "evaluations": int(evals), "restarts": int(restarts), "cost": best_f}}


# ── played by form/motion.py ─────────────────────────────────────────────────────────────────────────────────────

def assembly(link: dict):
    """The linkage as an Assembly (ground, crank, coupler, rocker; three hinges about Z and the loop that pins the
    coupler to the rocker), modelled at position 1."""
    from ..recipes.assembly import Assembly, Loop, Part, hinge
    O2, O4 = _c(link["O2"]), _c(link["O4"])
    pos = positions(link, np.array([link["theta1"]]))
    A, B = complex(pos["A"][0]), complex(pos["B"][0])
    return Assembly(
        parts=[Part("ground", "Ground", 0), Part("crank", "Crank", 1), Part("coupler", "Coupler", 2),
               Part("rocker", "Rocker", 3)],
        joints=[hinge("crank", (0, 0, 1), (O2.real, O2.imag, 0), (-720, 720), id="crank", parent="ground"),
                hinge("coupler", (0, 0, 1), (A.real, A.imag, 0), (-720, 720), id="coupler", parent="crank"),
                hinge("rocker", (0, 0, 1), (O4.real, O4.imag, 0), (-720, 720), id="rocker", parent="ground")],
        loops=[Loop("coupler", "rocker", (B.real, B.imag, 0), (0, 0, 1))])


def simulate(link: dict, crank_at_deg: list | None = None, per_segment: int = 24) -> dict:
    """Play the linkage with form/motion.py and return the coupler point and the rocker angle at each of the crank
    rotations in crank_at_deg (degrees from position 1; default: a full turn or the reachable range, 73 frames).
    The motion solver closes the loop by Newton's method from the assembly alone."""
    from .. import motion
    spec = assembly(link)
    pos = positions(link, np.array([link["theta1"]]))
    P0 = complex(pos["P"][0])
    trace = [{"part": "coupler", "at": [P0.real, P0.imag, 0.0], "label": "coupler point"}]
    if crank_at_deg:
        keys = [[float(k), float(v)] for k, v in enumerate(crank_at_deg)]
        n = (len(keys) - 1) * per_segment + 1
        r = motion.study(spec, [{"joint": "crank", "keys": keys}], duration_s=float(len(keys) - 1), frames=n,
                         traces=trace)
        at = [k * per_segment for k in range(len(keys))]
    else:
        r = motion.study(spec, [{"joint": "crank", "from": 0, "to": 360}], duration_s=2.0, frames=145, traces=trace)
        at = list(range(len(r["frames"])))
    tr = r["traces"][0]["positions_mm"]
    rk = next(j for j in r["joints"] if j["joint"] == "rocker")["value"]
    cp = next(j for j in r["joints"] if j["joint"] == "coupler")["value"]
    cr = next(j for j in r["joints"] if j["joint"] == "crank")["value"]
    th4_0 = math.degrees(float(pos["theta4"][0]))
    return {"evidence": EVIDENCE_SIM, "frames": len(r["frames"]), "closed_frames": r["closed_frames"],
            "at": [{"crank_deg": cr[i], "closed": bool(r["frames"][i]["closed"]),
                    "point": [tr[i][0], tr[i][1]] if tr[i] is not None else None,
                    "rocker_deg": th4_0 + rk[i] if rk[i] is not None else None,
                    "coupler_rotation_deg": (cr[i] + cp[i]) if cp[i] is not None else None} for i in at],
            "path": [[p[0], p[1]] for f, p in zip(r["frames"], tr) if f["closed"] and p is not None],
            "notes": r.get("notes") or []}


def _report_link(link: dict) -> dict:
    return {"ground_pivots_mm": {"O2": _xy(_c(link["O2"]), 4), "O4": _xy(_c(link["O4"]), 4)},
            "links_mm": {"crank": round(link["a"], 4), "coupler": round(link["b"], 4), "rocker": round(link["c"], 4),
                         "ground": round(link["d"], 4)},
            "coupler_point_mm": {"along": round(link["coupler_point"][0], 4), "across": round(link["coupler_point"][1], 4),
                                 "frame": "from the crank pin A, along A -> B and to its left"},
            "crank_angle_at_position_1_deg": round(math.degrees(link["theta1"]), 4), "assembly_mode": link["branch"]}


def synthesise(mode: str, poses: list | None = None, pairs: list | None = None, targets: list | None = None,
               ground: float = 100.0, closed: bool = True, seed: int = 1, steps: int = 24, max_size: float = 6.0,
               require_crank: bool = False, alternatives: int = 3, verify: bool = True, generations: int = 600,
               restarts: int = 4) -> dict:
    """One call for the three modes; see the module text. Returns the linkage, its checks, the verification by
    simulation and, for motion, the runners-up."""
    mode = str(mode or "").lower()
    if mode not in MODES:
        raise LinkageError(f"Unknown mode “{mode}”.", "motion (three poses), function (three angle pairs) or path "
                                                      "(target points).")
    out: dict = {"mode": mode, "version": VERSION}
    if mode == "motion":
        cands = three_positions(poses or [], steps=steps, keep=max(1, int(alternatives)), max_size=max_size,
                                require_crank=require_crank)
        best = cands[0]
        link, an = best["link"], best["analysis"]
        out.update(method="Burmester, three positions, standard dyad form (Erdman and Sandor)", evidence=EVIDENCE_EXACT,
                   alternatives=[{**_report_link(c["link"]), "min_transmission_deg": c["analysis"]["transmission"]["min_deg"],
                                  "class": c["analysis"]["grashof"]["class"], "link": c["link"]} for c in cands[1:]],
                   free_choices=f"the two rotations of each grounded link, searched on a {360 / steps:g}° grid")
        want = [{"at": [float(p["at"][0]), float(p["at"][1])], "angle": float(p.get("angle", 0.0))} for p in poses]
    elif mode == "function":
        r = freudenstein(pairs or [], ground)
        link, an = r["link"], r["analysis"]
        out.update(method="Freudenstein's equation, three precision points", evidence=EVIDENCE_EXACT, K=r["K"],
                   notes=r["notes"], closure_residual_mm=r["residual_mm"])
        want = [[float(p[0]), float(p[1])] for p in pairs]
        off_in, off_out = r["input_offset_deg"], r["output_offset_deg"]
    else:
        r = path(targets or [], closed=closed, seed=seed, generations=generations, restarts=restarts)
        link, an = r["link"], r["analysis"]
        out.update(method="path generation by optimisation", evidence=EVIDENCE_PATH, error=r["error"], search=r["search"])
        want = [[float(p[0]), float(p[1])] for p in targets]
    out["linkage"] = _report_link(link)
    out["link"] = link
    out["checks"] = an
    if verify:
        out["verification"] = _verify(mode, link, an, want, locals().get("off_in", 0.0), locals().get("off_out", 0.0))
    out["headline"] = _headline(out)
    return out


def _verify(mode: str, link: dict, an: dict, want: list, off_in: float = 0.0, off_out: float = 0.0) -> dict:
    from .. import motion
    try:
        if mode == "path":
            sim = simulate(link)
            Pc = np.array([complex(*p) for p in sim["path"]])
            if not len(Pc):
                return {"status": "FAIL", "detail": "the simulated linkage never closes"}
            # between frames the curve is taken as straight: distance from each target to the polyline
            err = [float(_dist_polyline(complex(*t), Pc, an["crank_turns_fully"])) for t in want]
            return {"evidence": EVIDENCE_SIM, "frames": sim["frames"], "closed_frames": sim["closed_frames"],
                    "max_distance_mm": max(err), "rms_distance_mm": float(np.sqrt(np.mean(np.square(err)))),
                    "per_target_mm": [round(e, 5) for e in err], "path": sim["path"],
                    "note": "distance from each target to the simulated coupler path (145 frames joined by straight "
                            "segments)"}
        drive = an.get("drive")
        if not drive:
            return {"status": "FAIL", "detail": "the crank cannot reach the positions in order: nothing to play"}
        sim = simulate(link, drive["crank_at_deg"])
        rows, worst_p, worst_a = [], 0.0, 0.0
        for k, s in enumerate(sim["at"]):
            row = {"position": k + 1, "crank_deg": s["crank_deg"], "closed": s["closed"]}
            if mode == "motion":
                w = want[k]
                dp = math.hypot(s["point"][0] - w["at"][0], s["point"][1] - w["at"][1]) if s["point"] else math.inf
                da = abs(math.degrees(_wrap(math.radians(s["coupler_rotation_deg"] - (w["angle"] - want[0]["angle"])))))
                row.update(point=s["point"], target=w["at"], point_error_mm=dp, angle_error_deg=da)
                worst_p, worst_a = max(worst_p, dp), max(worst_a, da)
            else:
                psi = s["rocker_deg"] - off_out
                da = abs(math.degrees(_wrap(math.radians(psi - want[k][1]))))
                row.update(output_deg=psi, target_output_deg=want[k][1], angle_error_deg=da)
                worst_a = max(worst_a, da)
            rows.append(row)
        ok = all(r["closed"] for r in rows) and worst_p < 1e-4 and worst_a < 1e-4
        return {"evidence": EVIDENCE_SIM, "status": "PASS" if ok else "FAIL", "positions": rows,
                "max_point_error_mm": worst_p, "max_angle_error_deg": worst_a, "accepted": "1e-4 mm and 1e-4°",
                "frames": sim["frames"], "closed_frames": sim["closed_frames"]}
    except motion.MotionError as e:
        return {"status": "FAIL", "detail": str(e)}


def _dist_polyline(p: complex, C: np.ndarray, closed: bool) -> float:
    A = C if not closed else np.append(C, C[0])
    a, b = A[:-1], A[1:]
    ab = b - a
    t = np.clip(((p - a) * np.conj(ab)).real / np.maximum(np.abs(ab) ** 2, 1e-18), 0.0, 1.0)
    return float(np.abs(p - (a + t * ab)).min())


def _headline(r: dict) -> str:
    L = r["linkage"]["links_mm"]
    c = r["checks"]
    s = (f"Four-bar: crank {L['crank']:.2f}, coupler {L['coupler']:.2f}, rocker {L['rocker']:.2f}, ground "
         f"{L['ground']:.2f} mm; {c['grashof']['class']}; transmission angle at least {c['transmission']['min_deg']:.0f}°")
    v = r.get("verification") or {}
    if r["mode"] == "path":
        s += f"; path error RMS {r['error']['rms_mm']:.3f} mm, largest {r['error']['max_mm']:.3f} mm"
    elif v.get("status"):
        s += f"; simulated through the three positions: {v['status']}"
    return s + "."


# ── as a design ───────────────────────────────────────────────────────────────────────────────────────────────────

SOURCE = '''"""A four-bar linkage found by synthesis ({mode}). Modelled at position 1; the assembly's joints play it.
Link lengths (mm): crank {a:.4f}, coupler {b:.4f}, rocker {c:.4f}, ground {d:.4f}. Pins are coincident axes: no pin
hardware is modelled."""
import math

from build123d import Align, Box, Cylinder, Pos, Rot
from form.recipes.base import Assembly, Feature, Loop, Param, Part, Recipe, Stage, hinge

O2, O4, A, B, P = {O2!r}, {O4!r}, {A!r}, {B!r}, {P!r}
UP = (Align.CENTER, Align.CENTER, Align.MIN)


def bar(p, q, z, w, t):
    L = math.hypot(q[0] - p[0], q[1] - p[1])
    ang = math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))
    mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, z)
    s = Pos(p[0], p[1], z) * Cylinder(w / 2, t, align=UP) + Pos(q[0], q[1], z) * Cylinder(w / 2, t, align=UP)
    return s + Pos(*mid) * Rot(0, 0, ang) * Box(L, w, t, align=UP) if L > 1e-6 else s


def mid(p, q, z):
    return ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, z)


class Design(Recipe):
    title = "Four-bar linkage"
    summary = "{summary}"
    params = [Param("link_w", "Link width", {w:g}, {wlo:g}, {whi:g}, 0.5, "mm", "form", "links"),
              Param("link_t", "Link thickness", {t:g}, 1, 12, 0.5, "mm", "form", "links")]
    features = [Feature("links", "Links", "structure")]
    solids = 4

    def build(self, v):
        w, t = v["link_w"], v["link_t"]
        g = t + 0.5
        ground = bar(O2, O4, 0, w * 1.6, t)
        crank = bar(O2, A, g, w, t)
        coupler = bar(A, B, 2 * g, w, t)
        if math.hypot(P[0] - A[0], P[1] - A[1]) > 1e-6 and math.hypot(P[0] - B[0], P[1] - B[1]) > 1e-6:
            coupler = coupler + bar(A, P, 2 * g, w, t) + bar(B, P, 2 * g, w, t)
        rocker = bar(O4, B, 3 * g, w, t)
        return [Stage("links", ground + crank + coupler + rocker)]

    def assembly(self, v):
        t = v["link_t"]
        g = t + 0.5
        return Assembly(
            parts=[Part("ground", "Ground", mid(O2, O4, t / 2)), Part("crank", "Crank", mid(O2, A, g + t / 2)),
                   Part("coupler", "Coupler", mid(A, B, 2 * g + t / 2)), Part("rocker", "Rocker", mid(O4, B, 3 * g + t / 2))],
            joints=[hinge("crank", (0, 0, 1), (*O2, 0), (-720, 720), id="crank", label="Crank", parent="ground"),
                    hinge("coupler", (0, 0, 1), (*A, 0), (-720, 720), id="coupler", label="Coupler pin", parent="crank"),
                    hinge("rocker", (0, 0, 1), (*O4, 0), (-720, 720), id="rocker", label="Rocker", parent="ground")],
            loops=[Loop("coupler", "rocker", (*B, 0), (0, 0, 1), label="Coupler to rocker pin")])
'''


def source(result: dict) -> str:
    """The synthesised linkage as a design's Python source (a Recipe with an assembly)."""
    link = result["link"]
    pos = positions(link, np.array([link["theta1"]]))
    r5 = lambda z: (round(z.real, 5), round(z.imag, 5))                      # noqa: E731
    smallest = min(link["a"], link["b"], link["c"], link["d"])
    w = max(2.0, min(8.0, round(smallest / 3.0, 1)))
    return SOURCE.format(mode=result["mode"], a=link["a"], b=link["b"], c=link["c"], d=link["d"],
                         O2=r5(_c(link["O2"])), O4=r5(_c(link["O4"])), A=r5(complex(pos["A"][0])),
                         B=r5(complex(pos["B"][0])), P=r5(complex(pos["P"][0])),
                         summary=result["headline"].replace('"', "'"), w=w, wlo=min(1.0, w), whi=max(12.0, w), t=3.0)


def create(st, result: dict, name: str = "", purpose: str | None = None) -> dict:
    """A new design from a synthesis: built in the kernel before it is saved."""
    return st.create_design(name or "Four-bar linkage", source(result), brief=result["headline"], purpose=purpose or "model")


__all__ = ["LinkageError", "MODES", "positions", "analyse", "dyad", "three_positions", "freudenstein", "path",
           "assembly", "simulate", "synthesise", "source", "create", "EVIDENCE_EXACT", "EVIDENCE_PATH", "EVIDENCE_SIM"]
