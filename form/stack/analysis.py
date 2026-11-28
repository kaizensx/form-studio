"""The arithmetic of a tolerance stack: worst case, RSS, Monte Carlo, capability, contributions and what to tighten.

Pure Python and numpy; no CAD kernel. A stack is a nominal gap and a list of contributors. Each contributor is one
dimension (or one float) that varies independently of the others:

    {"id", "label", "sensitivity": s, "lower": lo, "upper": hi, "dist": "normal" | "uniform", ...}

``lower`` and ``upper`` are the contributor's limit deviations from its nominal (mm or degrees; ``lower <= upper``),
so an ISO 286 class such as g6 (-7 to -20 µm) is a shifted, asymmetric range. ``sensitivity`` is d(gap)/d(dimension),
from the linearised geometric model (finite differences on the rebuilt CAD, form/stack/kernel.py). The gap is

    gap = gap_nominal + sum_i s_i * x_i,     x_i in [lower_i, upper_i]

Methods (each states what it assumes):

    worst case   every contributor at the limit that moves the gap the same way:  mean ± sum |s_i| t_i
    RSS          statistical, independent contributors; sigma_i = t_i / 3 for a normal (±3 sigma = the tolerance),
                 t_i / sqrt(3) for a uniform; sigma_gap = sqrt(sum (s_i sigma_i)^2); limits mean ± 3 sigma_gap.
                 Reading those limits as 99.73 % assumes the sum is close to normal (central limit theorem).
    Monte Carlo  every contributor sampled from its own distribution (seeded, so a run repeats exactly), the gap
                 evaluated by the same linear model; quantiles, the share out of spec, with its standard error.

Here t_i = (upper - lower) / 2 is the half range and m_i = (upper + lower) / 2 its centre (the mean shift).

Capability against the gap's specification (LSL, USL; either may be open):

    Cpk = min(USL - mean, mean - LSL) / (3 sigma),   share out = P(gap < LSL) + P(gap > USL)

Contribution of a contributor: its share of the gap's variance, (s_i sigma_i)^2 / sigma_gap^2. Suggestions rank the
contributors by how much halving each one's tolerance would shrink sigma_gap and the worst-case range.
"""
from __future__ import annotations

import math

import numpy as np

DISTS = ("normal", "uniform")
DEFAULT_SAMPLES = 200_000
DEFAULT_SEED = 1
Z3 = 3.0


def phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def sigma_of(c: dict) -> float:
    """Standard deviation of one contributor's dimension: t/3 for a normal (±3 sigma = its tolerance), t/sqrt(3) for a
    uniform over its range."""
    t = (float(c["upper"]) - float(c["lower"])) / 2.0
    if c.get("dist", "normal") == "uniform":
        return t / math.sqrt(3.0)
    return t / Z3


def _clean(contributors: list) -> list:
    out = []
    for c in contributors:
        lo, hi = float(c["lower"]), float(c["upper"])
        if hi < lo:
            raise ValueError(f"{c.get('id')}: upper deviation {hi} is below the lower {lo}")
        d = c.get("dist", "normal")
        if d not in DISTS:
            raise ValueError(f"{c.get('id')}: distribution is normal or uniform (got {d!r})")
        out.append({**c, "lower": lo, "upper": hi, "dist": d, "sensitivity": float(c["sensitivity"])})
    return out


def worst_case(nominal: float, contributors: list) -> dict:
    cs = _clean(contributors)
    mean = nominal + sum(c["sensitivity"] * (c["lower"] + c["upper"]) / 2 for c in cs)
    half = sum(abs(c["sensitivity"]) * (c["upper"] - c["lower"]) / 2 for c in cs)
    return {"mean": mean, "min": mean - half, "max": mean + half, "half_range": half,
            "assumes": "every contributor at its limit at once, each in the direction that moves the gap the same way"}


def rss(nominal: float, contributors: list) -> dict:
    cs = _clean(contributors)
    mean = nominal + sum(c["sensitivity"] * (c["lower"] + c["upper"]) / 2 for c in cs)
    var = sum((c["sensitivity"] * sigma_of(c)) ** 2 for c in cs)
    sd = math.sqrt(var)
    return {"mean": mean, "sigma": sd, "min": mean - Z3 * sd, "max": mean + Z3 * sd,
            "assumes": "independent contributors; sigma = tolerance/3 for a normal, tolerance/sqrt(3) for a uniform; "
                       "±3 sigma read as 99.73 % assumes the sum is close to normal"}


def monte_carlo(nominal: float, contributors: list, samples: int = DEFAULT_SAMPLES, seed: int = DEFAULT_SEED,
                lsl: float | None = None, usl: float | None = None, bins: int = 40) -> dict:
    cs = _clean(contributors)
    n = int(samples)
    if not 1000 <= n <= 5_000_000:
        raise ValueError("samples must be between 1000 and 5000000")
    rng = np.random.default_rng(int(seed))
    g = np.full(n, float(nominal))
    for c in cs:
        lo, hi = c["lower"], c["upper"]
        if hi == lo:
            x = np.full(n, lo)
        elif c["dist"] == "uniform":
            x = rng.uniform(lo, hi, n)
        else:
            x = rng.normal((lo + hi) / 2, (hi - lo) / 2 / Z3, n)
        g += c["sensitivity"] * x
    mean, sd = float(g.mean()), float(g.std(ddof=1))
    q = np.quantile(g, [0.00135, 0.5, 0.99865])
    out = {"samples": n, "seed": int(seed), "mean": mean, "sigma": sd, "min_sampled": float(g.min()),
           "max_sampled": float(g.max()), "q00135": float(q[0]), "median": float(q[1]), "q99865": float(q[2]),
           "se_mean": sd / math.sqrt(n),
           "assumes": "the same linear model as RSS, each contributor sampled from its own distribution "
                      "(normal: ±3 sigma = tolerance, not truncated; uniform over its range); seeded, so it repeats"}
    below = int(np.count_nonzero(g < lsl)) if lsl is not None else 0
    above = int(np.count_nonzero(g > usl)) if usl is not None else 0
    if lsl is not None or usl is not None:
        p = (below + above) / n
        out.update({"out_of_spec": p, "out_of_spec_se": math.sqrt(max(p * (1 - p), 1.0 / n) / n),
                    "below_lsl": below / n, "above_usl": above / n})
    lo_e, hi_e = float(g.min()), float(g.max())
    if hi_e > lo_e:
        h, e = np.histogram(g, bins=bins, range=(lo_e, hi_e))
        out["histogram"] = {"edges": [float(x) for x in e], "counts": [int(x) for x in h]}
    return out


def capability(mean: float, sigma: float, lsl: float | None, usl: float | None) -> dict:
    """Cpk and the share out of spec of a normal gap with this mean and sigma (one-sided when a limit is open)."""
    if lsl is None and usl is None:
        return {"cpk": None, "why": "no specification limit (give spec=[LSL, USL]; either may be null)"}
    if sigma <= 0:
        inside = (lsl is None or mean >= lsl) and (usl is None or mean <= usl)
        return {"cpk": None, "out_of_spec": 0.0 if inside else 1.0,
                "why": "no variation: every contributor has a zero tolerance, so Cpk is not defined"}
    ks = []
    if usl is not None:
        ks.append((usl - mean) / (Z3 * sigma))
    if lsl is not None:
        ks.append((mean - lsl) / (Z3 * sigma))
    p = (phi((lsl - mean) / sigma) if lsl is not None else 0.0) + (1 - phi((usl - mean) / sigma) if usl is not None else 0.0)
    out = {"cpk": min(ks), "out_of_spec": p, "ppm": p * 1e6,
           "assumes": "the gap is normal with the RSS mean and sigma"}
    if lsl is not None and usl is not None:
        out["cp"] = (usl - lsl) / (6 * sigma)
    return out


def contributions(contributors: list) -> list:
    """Each contributor's share of the gap's variance and of the worst-case range, largest first."""
    cs = _clean(contributors)
    var = [(c["sensitivity"] * sigma_of(c)) ** 2 for c in cs]
    tot = sum(var)
    wc = [abs(c["sensitivity"]) * (c["upper"] - c["lower"]) / 2 for c in cs]
    wtot = sum(wc)
    rows = []
    for c, v, w in zip(cs, var, wc):
        rows.append({"id": c["id"], "label": c.get("label", c["id"]), "variance_share": (v / tot) if tot else 0.0,
                     "worst_case_share": (w / wtot) if wtot else 0.0, "sigma_contrib": math.sqrt(v),
                     "half_range_contrib": w})
    rows.sort(key=lambda r: -r["variance_share"])
    return rows


def what_if(nominal: float, contributors: list, cid: str, factor: float) -> dict:
    """RSS sigma and worst-case half range with one contributor's range scaled by factor about its centre."""
    cs = []
    for c in _clean(contributors):
        if c["id"] == cid:
            m, t = (c["lower"] + c["upper"]) / 2, (c["upper"] - c["lower"]) / 2 * factor
            c = {**c, "lower": m - t, "upper": m + t}
        cs.append(c)
    return {"rss": rss(nominal, cs), "worst_case": worst_case(nominal, cs)}


def thermal_shift(links: list, t: float, t_ref: float = 20.0) -> dict:
    """Change of the gap at temperature t: every part's link grows by its own expansion,
    d_i(T) = d_i (1 + alpha_i (T - t_ref)), so  delta_gap = (T - t_ref) * sum_i alpha_i d_i.
    links: [{"part", "length": signed d_i along the gap (mm), "alpha": 1/K or None}]. A link whose alpha is None
    leaves the result out (None), never assumed."""
    dt = float(t) - float(t_ref)
    if any(x.get("alpha") is None and abs(x.get("length") or 0) > 0 for x in links):
        return {"t": t, "shift": None, "terms": []}
    terms = [{"part": x["part"], "shift": dt * float(x["alpha"] or 0) * float(x["length"])} for x in links]
    return {"t": t, "shift": sum(x["shift"] for x in terms), "terms": terms}
