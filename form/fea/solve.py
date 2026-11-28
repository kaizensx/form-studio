"""The finite-element solver of the strength studies: linear elasticity on quadratic tetrahedra (FEA engine's Python).

Units: mm, N, MPa (N/mm2), tonne (so that N = tonne x mm/s2), seconds, Hz. Density is tonne/mm3 (kg/m3 x 1e-12).

    sp = Space(mesh)                               # 10-node (quadratic) shape functions on Netgen's tetrahedra
    K = sp.stiffness(lam, mu)                      # per-element Lame constants
    f = sp.traction(tris, t) + sp.body(rho, g)
    con = Constraints(sp); con.fix(nodes); con.slide(nodes, normals)
    u = solve_static(sp, K, f, con)
    s = sp.stress(u, lam, mu)                      # smoothed nodal stress, element stress, error indicator

The model is linear elastic and small strain: stress is proportional to load, a part that yields, buckles, slips or
comes apart is not modelled here. Shape functions come from scikit-fem (ElementTetP2); the element matrices are
assembled here from their gradients so stiffness, mass, geometric stiffness and the stress recovery share one code
path. Equations are solved with conjugate gradients preconditioned by smoothed-aggregation multigrid (PyAMG) with the
six rigid-body modes as its near-null space, to a relative residual of SOLVE_TOL; a small system is solved directly.
"""
from __future__ import annotations

import numpy as np
import scipy.sparse as sp_
import scipy.sparse.linalg as spla

SOLVE_TOL = 1e-9
DIRECT_BELOW = 15000          # free unknowns below which one load case is solved by a sparse direct factorisation
DIRECT_EIG_BELOW = 160000     # ... and below which an eigenproblem is (it needs many solves with one matrix)
CHUNK = 20000                 # elements per assembly block

# reference mass matrix of a 6-node triangle (3 corners, then mid-sides 01, 12, 20), times area: integral of Ni Nj
_M6 = np.array([[6, -1, -1, 0, -4, 0], [-1, 6, -1, 0, 0, -4], [-1, -1, 6, -4, 0, 0],
                [0, 0, -4, 32, 16, 16], [-4, 0, 0, 16, 32, 16], [0, -4, 0, 16, 16, 32]], dtype=float) / 180.0


class SolveError(RuntimeError):
    pass


def lame(E, nu):
    E, nu = np.asarray(E, float), np.asarray(nu, float)
    return E * nu / ((1 + nu) * (1 - 2 * nu)), E / (2 * (1 + nu))


def von_mises(s: np.ndarray) -> np.ndarray:
    """s[..., 6] = xx, yy, zz, xy, yz, zx."""
    return np.sqrt(np.maximum(0.5 * ((s[..., 0] - s[..., 1]) ** 2 + (s[..., 1] - s[..., 2]) ** 2 + (s[..., 2] - s[..., 0]) ** 2)
                              + 3 * (s[..., 3] ** 2 + s[..., 4] ** 2 + s[..., 5] ** 2), 0.0))


def principal(s: np.ndarray) -> np.ndarray:
    """Principal stresses, descending, of s[..., 6]."""
    m = np.empty(s.shape[:-1] + (3, 3))
    m[..., 0, 0], m[..., 1, 1], m[..., 2, 2] = s[..., 0], s[..., 1], s[..., 2]
    m[..., 0, 1] = m[..., 1, 0] = s[..., 3]
    m[..., 1, 2] = m[..., 2, 1] = s[..., 4]
    m[..., 0, 2] = m[..., 2, 0] = s[..., 5]
    return np.linalg.eigvalsh(m)[..., ::-1]


class Space:
    """Quadratic displacement on a tetrahedral mesh. Node k has unknowns 3k, 3k+1, 3k+2 (x, y, z)."""

    def __init__(self, mesh):
        from skfem import Basis, ElementTetP2, MeshTet
        self.mesh = mesh
        self.sk = MeshTet(np.ascontiguousarray(mesh.P.T), np.ascontiguousarray(mesh.T.T), validate=False) \
            if _accepts_validate(MeshTet) else MeshTet(np.ascontiguousarray(mesh.P.T), np.ascontiguousarray(mesh.T.T))
        el = ElementTetP2()
        self.b2 = Basis(self.sk, el, intorder=2)
        self.edofs = np.asarray(self.b2.element_dofs)            # (10, nel)
        self.X = np.asarray(self.b2.doflocs).T.copy()            # (N, 3)
        self.N = self.X.shape[0]
        self.nel = self.edofs.shape[1]
        self.ndof = 3 * self.N
        self.nv = mesh.P.shape[0]
        self.dx = np.asarray(self.b2.dx)                         # (nel, nq)
        self.dN = np.stack([np.asarray(self.b2.basis[a][0].grad) for a in range(10)])     # (10, 3, nel, nq)
        self.vol = self.dx.sum(axis=1)
        w = np.full(10, 1.0 / 60.0)
        self.bn = Basis(self.sk, el, quadrature=(np.asarray(el.doflocs).T.copy(), w))     # gradients at the 10 nodes
        self.dNn = np.stack([np.asarray(self.bn.basis[a][0].grad) for a in range(10)])    # (10, 3, nel, 10)
        # mid-side node of every mesh edge, by its two vertices
        ed = np.sort(np.asarray(self.sk.edges), axis=0)
        code = ed[0].astype(np.int64) * self.nv + ed[1]
        order = np.argsort(code)
        self._ecode, self._edof = code[order], np.asarray(self.b2.edge_dofs)[0][order]
        self._vdof = np.asarray(self.b2.nodal_dofs)[0]

    # ---- nodes of boundary triangles -----------------------------------------------------------------------------
    def mid(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        lo, hi = np.minimum(a, b).astype(np.int64), np.maximum(a, b).astype(np.int64)
        k = np.searchsorted(self._ecode, lo * self.nv + hi)
        return self._edof[k]

    def tri_nodes(self, tris: np.ndarray) -> np.ndarray:
        """(n, 6) nodes of boundary triangles: corners 0, 1, 2 and mid-sides 01, 12, 20."""
        S = self.mesh.S[tris]
        v = self._vdof[S]
        return np.column_stack([v, self.mid(S[:, 0], S[:, 1]), self.mid(S[:, 1], S[:, 2]), self.mid(S[:, 2], S[:, 0])])

    # ---- matrices --------------------------------------------------------------------------------------------------
    def _rows(self, s: slice):
        d = self.edofs[:, s].T                                    # (n, 10)
        return (3 * d[:, :, None] + np.arange(3)[None, None, :]).reshape(len(d), 30)

    def stiffness(self, lam: np.ndarray, mu: np.ndarray) -> sp_.csr_matrix:
        I, J, V = [], [], []
        eye = np.eye(3)
        for a in range(0, self.nel, CHUNK):
            s = slice(a, min(a + CHUNK, self.nel))
            G = np.einsum("aieq,bjeq,eq->eaibj", self.dN[:, :, s], self.dN[:, :, s], self.dx[s], optimize=True)
            la, m = lam[s, None, None, None, None], mu[s, None, None, None, None]
            tr = np.einsum("eakbk->eab", G)
            Ke = la * G + m * np.swapaxes(G, 2, 4) + m * tr[:, :, None, :, None] * eye[None, None, :, None, :]
            n = Ke.shape[0]
            r = self._rows(s)
            I.append(np.repeat(r, 30, axis=1).ravel())
            J.append(np.tile(r, (1, 30)).ravel())
            V.append(Ke.reshape(n, 900).ravel())
        K = sp_.coo_matrix((np.concatenate(V), (np.concatenate(I), np.concatenate(J))), shape=(self.ndof, self.ndof)).tocsr()
        K.sum_duplicates()
        return ((K + K.T) * 0.5).tocsr()

    def _scalar(self, Ae: np.ndarray) -> sp_.csr_matrix:
        d = self.edofs.T
        I = np.repeat(d, 10, axis=1).ravel()
        J = np.tile(d, (1, 10)).ravel()
        A = sp_.coo_matrix((Ae.reshape(-1), (I, J)), shape=(self.N, self.N)).tocsr()
        A.sum_duplicates()
        return A

    def mass(self, rho: np.ndarray) -> sp_.csr_matrix:
        """Consistent mass matrix (tonne), density per element in tonne/mm3."""
        from skfem import Basis, ElementTetP2
        b4 = Basis(self.sk, ElementTetP2(), intorder=4)
        Nq = np.stack([np.asarray(b4.basis[a][0].value) for a in range(10)])     # (10, nel, nq)
        Me = np.einsum("aeq,beq,eq->eab", Nq, Nq, np.asarray(b4.dx) * rho[:, None], optimize=True)
        return sp_.kron(self._scalar(Me), sp_.identity(3), format="csr")

    def element_stress_q(self, u: np.ndarray, lam, mu) -> np.ndarray:
        """Stress at the stiffness quadrature points, (nel, nq, 3, 3)."""
        ue = u.reshape(-1, 3)[self.edofs.T]                       # (nel, 10, 3)
        H = np.einsum("ajeq,eai->eqij", self.dN, ue, optimize=True)            # du_i/dx_j
        e = 0.5 * (H + np.swapaxes(H, 2, 3))
        tr = np.einsum("eqii->eq", e)
        return lam[:, None, None, None] * tr[..., None, None] * np.eye(3) + 2 * mu[:, None, None, None] * e

    def geometric(self, sq: np.ndarray) -> sp_.csr_matrix:
        """Geometric (initial stress) stiffness from the stress sq of a solved load case."""
        Se = np.einsum("akeq,bleq,eqkl,eq->eab", self.dN, self.dN, sq, self.dx, optimize=True)
        return sp_.kron(self._scalar(Se), sp_.identity(3), format="csr")

    # ---- loads -----------------------------------------------------------------------------------------------------
    def traction(self, tris: np.ndarray, t: np.ndarray) -> np.ndarray:
        """Nodal forces of a traction t (N/mm2; (3,) or one row per triangle) on boundary triangles."""
        f = np.zeros(self.ndof)
        if len(tris) == 0:
            return f
        nodes = self.tri_nodes(tris)
        a, b, c = (self.mesh.P[self.mesh.S[tris][:, i]] for i in range(3))
        area = np.linalg.norm(np.cross(b - a, c - a), axis=1) / 2
        t = np.broadcast_to(np.asarray(t, float), (len(tris), 3))
        w = (area / 3.0)[:, None] * t                             # a quadratic triangle: all of it on the mid-sides
        for k in (3, 4, 5):
            np.add.at(f, 3 * nodes[:, k][:, None] + np.arange(3), w)
        return f

    def body(self, rho: np.ndarray, g) -> np.ndarray:
        """Nodal forces of an acceleration field g (mm/s2) on the mass (density per element, tonne/mm3)."""
        from skfem import Basis, ElementTetP2
        b = Basis(self.sk, ElementTetP2(), intorder=2)
        Nq = np.stack([np.asarray(b.basis[a][0].value) for a in range(10)])
        fe = np.einsum("aeq,eq->ea", Nq, np.asarray(b.dx) * rho[:, None])
        fs = np.zeros(self.N)
        np.add.at(fs, self.edofs.T, fe)
        return (fs[:, None] * np.asarray(g, float)[None, :]).ravel()

    def rigid_modes(self) -> np.ndarray:
        B = np.zeros((self.ndof, 6))
        x = self.X - self.X.mean(axis=0)
        for i in range(3):
            B[i::3, i] = 1.0
        B[0::3, 3], B[1::3, 3] = -x[:, 1], x[:, 0]
        B[1::3, 4], B[2::3, 4] = -x[:, 2], x[:, 1]
        B[0::3, 5], B[2::3, 5] = x[:, 2], -x[:, 0]
        return B

    # ---- stress ----------------------------------------------------------------------------------------------------
    def stress(self, u: np.ndarray, lam: np.ndarray, mu: np.ndarray, dom: np.ndarray | None = None) -> dict:
        """Stress from a displacement field.

        "element": (nel, 10, 6) the stress of each element at its own 10 nodes (linear inside an element);
        "nodal": (N, 6) the smoothed stress: the volume-weighted mean over the elements at each node, taken within one
        solid when several are glued (stress jumps where the material changes), then the solid with the highest von
        Mises stress at a shared node; "eta": (nel,) each element's error indicator in the energy norm (the difference
        between its own stress and the smoothed one; Zienkiewicz and Zhu 1987); "energy": u K u / 2."""
        ue = u.reshape(-1, 3)[self.edofs.T]
        H = np.einsum("ajen,eai->enij", self.dNn, ue, optimize=True)           # (nel, 10 nodes, 3, 3)
        e = 0.5 * (H + np.swapaxes(H, 2, 3))
        tr = np.einsum("enii->en", e)
        s = lam[:, None, None, None] * tr[..., None, None] * np.eye(3) + 2 * mu[:, None, None, None] * e
        se = np.stack([s[..., 0, 0], s[..., 1, 1], s[..., 2, 2], s[..., 0, 1], s[..., 1, 2], s[..., 0, 2]], axis=-1)
        d = self.edofs.T
        doms = [None] if dom is None or dom.max() == dom.min() else list(np.unique(dom))
        nodal = np.zeros((self.N, 6))
        best = np.full(self.N, -1.0)
        sm_e = np.zeros_like(se)                                  # the smoothed stress back at each element's nodes
        for k in doms:
            sel = slice(None) if k is None else (dom == k)
            w = np.zeros(self.N)
            acc = np.zeros((self.N, 6))
            vw = self.vol[sel]
            np.add.at(w, d[sel], vw[:, None])
            np.add.at(acc, d[sel], se[sel] * vw[:, None, None])
            has = w > 0
            acc[has] /= w[has, None]
            sm_e[sel] = acc[d[sel]]
            vm = von_mises(acc)
            take = has & (vm > best)
            nodal[take], best[take] = acc[take], vm[take]
        ds = sm_e - se
        E = mu * (3 * lam + 2 * mu) / (lam + mu)
        nu = lam / (2 * (lam + mu))
        trd = ds[..., 0] + ds[..., 1] + ds[..., 2]
        # complementary energy density of the stress difference: (1+nu)/E s:s - nu/E tr(s)^2
        ss = (ds[..., :3] ** 2).sum(-1) + 2 * (ds[..., 3:] ** 2).sum(-1)
        dens = ((1 + nu) / E)[:, None] * ss - (nu / E)[:, None] * trd ** 2
        eta2 = self.vol * np.maximum(dens, 0).mean(axis=1)
        return {"element": se, "nodal": nodal, "eta": np.sqrt(eta2)}


def _accepts_validate(cls) -> bool:
    try:
        import inspect
        return "validate" in inspect.signature(cls).parameters
    except (TypeError, ValueError):
        return False


class Constraints:
    """Supports as directions that may not move at a node. A node with three independent directions is fixed; with
    one it slides in the plane across that direction (a roller, a symmetry plane); with two it moves along a line."""

    def __init__(self, space: Space):
        self.sp = space
        self.dirs: dict[int, list] = {}

    def fix(self, nodes) -> None:
        for n in np.unique(nodes):
            self.dirs[int(n)] = [np.array([1.0, 0, 0]), np.array([0, 1.0, 0]), np.array([0, 0, 1.0])]

    def hold(self, nodes, directions) -> None:
        """No displacement along directions[i] (unit vector, or one for all) at nodes[i]."""
        directions = np.broadcast_to(np.asarray(directions, float), (len(nodes), 3))
        for n, v in zip(nodes, directions):
            self.dirs.setdefault(int(n), []).append(np.asarray(v, float))

    def build(self):
        """(Q, fixed): u = Q u_local, and the local unknowns that are zero."""
        idx, blocks, fixed = [], [], []
        for n, vs in self.dirs.items():
            basis = []
            for v in vs:
                w = v - sum((v @ b) * b for b in basis) if basis else v.copy()
                nw = np.linalg.norm(w)
                if nw > 0.17 and len(basis) < 3:                    # more than 10 degrees from the directions so far
                    basis.append(w / nw)
            r = len(basis)
            if r == 0:
                continue
            if r == 3:
                fixed.extend((3 * n, 3 * n + 1, 3 * n + 2))
                continue
            if r == 1:
                t = np.eye(3)[int(np.argmin(np.abs(basis[0])))]
                t = t - (t @ basis[0]) * basis[0]
                basis.append(t / np.linalg.norm(t))
            basis.append(np.cross(basis[0], basis[1]))
            idx.append(n)
            blocks.append(np.column_stack(basis))                   # columns: local axes; the first r are held
            fixed.extend(3 * n + k for k in range(r))
        ndof = self.sp.ndof
        plain = np.ones(ndof, bool)
        nodes = np.array(idx, dtype=np.int64)
        rot = (3 * nodes[:, None] + np.arange(3)).ravel() if len(nodes) else np.zeros(0, np.int64)
        plain[rot] = False
        keep = np.where(plain)[0]
        rows = np.concatenate([keep, np.repeat(rot, 3)])
        cols = np.concatenate([keep, np.tile((3 * nodes[:, None] + np.arange(3)), (1, 3)).ravel() if len(nodes) else rot])
        vals = np.concatenate([np.ones(len(keep)), np.array(blocks, dtype=float).reshape(-1) if blocks else np.zeros(0)])
        Q = sp_.coo_matrix((vals, (rows, cols)), shape=(ndof, ndof)).tocsr()
        return Q, np.array(sorted(set(fixed)), dtype=np.int64)


def _amg(A, B):
    import pyamg
    return pyamg.smoothed_aggregation_solver(A.tocsr(), B=B, strength=("symmetric", {"theta": 0.0}),
                                             smooth=("jacobi", {"omega": 4.0 / 3.0}), max_coarse=400,
                                             improve_candidates=[("block_gauss_seidel", {"sweep": "symmetric", "iterations": 4}), None])


class System:
    """K reduced to the free unknowns of a set of constraints, with a solver kept for repeated right-hand sides."""

    def __init__(self, space: Space, K, con: Constraints, cancelled=None):
        self.sp, self.K = space, K
        self.Q, self.fixed = con.build()
        free = np.ones(space.ndof, bool)
        free[self.fixed] = False
        self.free = np.where(free)[0]
        self.Kl = (self.Q.T @ K @ self.Q).tocsr()
        self.A = self.Kl[self.free][:, self.free].tocsr()
        self.A = ((self.A + self.A.T) * 0.5).tocsr()
        self.cancelled = cancelled
        self.iterations = 0
        self.method = ""
        self._lu = self._ml = None

    @property
    def n(self) -> int:
        return len(self.free)

    def reduce(self, M):
        return ((self.Q.T @ M @ self.Q).tocsr()[self.free][:, self.free]).tocsr()

    def expand(self, x: np.ndarray) -> np.ndarray:
        ul = np.zeros(self.sp.ndof)
        ul[self.free] = x
        return self.Q @ ul

    def restrict(self, v: np.ndarray) -> np.ndarray:
        return (self.Q.T @ v)[self.free]

    def prepare(self, shift=None, direct: bool | None = None):
        """Factor (direct) or build the multigrid hierarchy for A, or for A + shift."""
        A = self.A if shift is None else (self.A + shift).tocsr()
        if direct is None:
            direct = self.n <= DIRECT_BELOW
        self._lu = self._ml = None
        if direct:
            # symmetric positive definite: minimum degree on A + A', no pivoting
            self._lu = spla.splu(A.tocsc(), permc_spec="MMD_AT_PLUS_A", diag_pivot_thresh=0.0,
                                 options={"SymmetricMode": True})
            self.method = "sparse direct (SuperLU)"
        else:
            B = (self.Q.T @ self.sp.rigid_modes())[self.free]
            np.random.seed(0)                            # PyAMG estimates spectral radii from random vectors
            self._ml, self._A = _amg(A, B), A
            self.method = "conjugate gradients, smoothed-aggregation multigrid (PyAMG)"
        return self

    def solve(self, b: np.ndarray, tol: float = SOLVE_TOL) -> np.ndarray:
        if self._lu is None and self._ml is None:
            self.prepare()
        if self._lu is not None:
            return self._lu.solve(b)
        nb = np.linalg.norm(b)
        if nb == 0:
            return np.zeros_like(b)
        its = [0]

        def cb(_x):
            its[0] += 1
            if self.cancelled is not None and its[0] % 20 == 0 and self.cancelled():
                raise SolveError("cancelled")
        x, info = spla.cg(self._A, b, rtol=tol, atol=0.0, maxiter=4000, M=self._ml.aspreconditioner(cycle="V"), callback=cb)
        self.iterations += its[0]
        res = np.linalg.norm(self._A @ x - b) / nb
        if info != 0 or not np.isfinite(res) or res > 100 * tol:
            raise SolveError(f"The equation solver did not converge (relative residual {res:.2e} after {its[0]} "
                             "iterations). The part may not be held: check that the supports stop it from moving "
                             "and turning in every direction.")
        return x


def solve_static(system: System, f: np.ndarray) -> dict:
    """Displacement for the load vector f, with the reactions at the supports and the balance of forces."""
    if system.n == 0:
        raise SolveError("Every node is fixed: nothing can move.")
    x = system.solve(system.restrict(f))
    u = system.expand(x)
    r = system.K @ u - f                                         # reaction forces: zero at free unknowns
    R = r.reshape(-1, 3).sum(axis=0)
    F = f.reshape(-1, 3).sum(axis=0)
    X = system.sp.X
    Mr = np.cross(X, r.reshape(-1, 3)).sum(axis=0)
    Mf = np.cross(X, f.reshape(-1, 3)).sum(axis=0)
    scale = max(np.abs(f).sum(), 1e-300)
    L = max(np.ptp(X, axis=0).max(), 1e-300)
    return {"u": u, "reaction": R, "applied": F, "energy": 0.5 * float(u @ (system.K @ u)),
            "force_residual": float(np.linalg.norm(R + F) / scale),
            "moment_residual": float(np.linalg.norm(Mr + Mf) / (scale * L)),
            "free_residual": float(np.linalg.norm((system.Q.T @ r)[system.free]) / scale)}


def solve_modal(system: System, M, k: int, free_body: bool, w_ref: float) -> dict:
    """The lowest k natural frequencies (Hz) and mode shapes. free_body: nothing holds the part, so its six rigid-body
    modes (0 Hz) are computed and left out. w_ref: a circular frequency of the order of the first mode (the shift)."""
    Mr = system.reduce(M)
    Mr = ((Mr + Mr.T) * 0.5).tocsr()
    n = system.n
    want = k + (6 if free_body else 0)
    if n <= want + 2:
        raise SolveError("The mesh has too few unknowns for the modes asked for.")
    A = system.A
    sigma = -w_ref ** 2                                  # K - sigma M is positive definite, also for a free body
    direct = n <= DIRECT_EIG_BELOW
    system.prepare(shift=-sigma * Mr, direct=direct)
    op = spla.LinearOperator((n, n), matvec=lambda b: system.solve(np.asarray(b).ravel(), tol=1e-11), dtype=float)
    # a wide Krylov space: the six rigid-body modes of a free body are one eigenvalue six times over
    w, V = spla.eigsh(A, k=want, M=Mr, sigma=sigma, which="LM", OPinv=op, tol=1e-10 if direct else 1e-8,
                      ncv=min(n - 1, max(4 * want, 48)), v0=np.ones(n))
    method = "shift-invert Lanczos (ARPACK), " + system.method
    order = np.argsort(w)
    w, V = w[order], V[:, order]
    if free_body:
        if not abs(w[5]) < 1e-2 * abs(w[6]):               # six zeros (to rounding), then the first elastic mode
            raise SolveError("A free body has six rigid-body modes at 0 Hz; the solver did not separate them from "
                             "the elastic modes.")
        w, V = w[6:], V[:, 6:]
    w, V = w[:k], V[:, :k]
    f = np.sqrt(np.maximum(w, 0)) / (2 * np.pi)
    return {"hz": f, "modes": np.stack([system.expand(V[:, i]) for i in range(V.shape[1])], axis=0), "method": method}


def solve_buckling(system: System, Kg, k: int = 3) -> dict:
    """Load factors at which the part buckles under the solved load case: K x = factor (-Kg) x, lowest positive."""
    G = -system.reduce(Kg)
    G = ((G + G.T) * 0.5).tocsr()
    n = system.n
    if system._lu is None:
        system.prepare(direct=n <= DIRECT_EIG_BELOW)
    op = spla.LinearOperator((n, n), matvec=lambda b: system.solve(np.asarray(b).ravel(), tol=1e-11), dtype=float)
    kk = min(max(k + 2, 4), n - 2)
    mu, V = spla.eigsh(G, k=kk, M=system.A, Minv=op, which="LA", tol=1e-8)       # G x = mu K x, mu = 1/factor
    order = np.argsort(-mu)
    mu, V = mu[order], V[:, order]
    pos = mu > 1e-12 * max(abs(mu).max(), 1e-300)
    if not pos.any():
        return {"factors": np.array([]), "modes": np.zeros((0, system.sp.ndof)), "note": "no compressive mode"}
    mu, V = mu[pos][:k], V[:, pos][:, :k]
    return {"factors": 1.0 / mu, "modes": np.stack([system.expand(V[:, i]) for i in range(V.shape[1])], axis=0)}
