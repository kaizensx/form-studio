"""Strength studies with a stated error: linear static, modal, linear buckling, steady heat and thermal stress on a
design's B-rep.

    form/fea/study.py     define, run (in the background, with progress and cancel), read; results stored beside the
                          revision under a key of the geometry, the material's numbers, the loads and the engine,
                          so a newer revision makes them stale by construction
    form/fea/material.py  E, Poisson's ratio, yield and density with their sources (form/material_library.py)
    form/fea/prep.py      kernel side: the solid as STEP in the assembled frame, and the picked faces
    form/fea/run.py       the engine's entry: `<engine python> -m form.fea.run <job folder>`
    form/fea/core.py      one study from geometry to a result: refinement until it stops changing, singularities
                          named, equilibrium checked
    form/fea/mesh.py      Netgen: tetrahedra from the B-rep, finer on fillets and holes
    form/fea/solve.py     quadratic tetrahedra, sparse solvers (scikit-fem shape functions, SciPy, PyAMG)
    form/fea/thermal.py   steady heat conduction, and the temperature field as a load (thermal stress)
    form/fea/hand.py      a closed-form estimate beside a static result, where the part reads as a beam
    form/fea/constraint.py  a study as a constraint in optimize and make_lighter (fea.safety_factor >= 2)
    form/fea/verify.py    the verification suite: textbook cases with the reference value and accepted error
    form/fea/cli.py       `form strength ...` and `form study strength|modal|buckling ...` (JSON)
    form/fea/bench.py     the Bench entry (form/studies.py)

The solver libraries are an optional engine with a Python of its own (form/engines.py "fea": Netgen, scikit-fem,
SciPy, PyAMG, NumPy), installed from Settings with one click. Nothing in this package imports them except core, mesh,
solve, verify and run, which only that Python runs. docs/STRENGTH.md has the method and the verification table.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ENGINE = "fea"
KINDS = ("static", "modal", "buckling", "thermal", "thermal_stress")
KIND_LABEL = {"static": "linear static", "modal": "modal", "buckling": "linear buckling", "thermal": "steady heat",
              "thermal_stress": "thermal stress"}
ENGINE_KIND = {"thermal_stress": "static"}        # what the solver runs: thermal stress is a static study with a
                                                  # temperature field as a load
NEEDS = ("netgen", "skfem", "scipy", "pyamg", "numpy")
HOW_TO_GET = ("The strength solver is an optional engine: install “Strength studies (FEA)” in Settings, Engines & "
              "software (or `form setup`). It gets a Python of its own with Netgen, scikit-fem, SciPy and PyAMG.")


def python(cfg: dict | None = None) -> Path | None:
    """The interpreter that runs the solver: $FORM_FEA_PYTHON, else the installed engine's own Python, else this
    Python when it has the libraries (a developer's environment). None when there is none."""
    env = os.environ.get("FORM_FEA_PYTHON")
    if env:
        p = Path(env).expanduser()
        return p if p.exists() else None
    try:
        from .. import engines
        p = engines.python(ENGINE, cfg)
        if p is not None:
            return p
    except Exception:                               # noqa: BLE001 - no configuration: fall through
        pass
    if not getattr(sys, "frozen", False) and all(importlib.util.find_spec(m) is not None for m in NEEDS):
        return Path(sys.executable)
    return None


def available(cfg: dict | None = None) -> bool:
    return python(cfg) is not None
