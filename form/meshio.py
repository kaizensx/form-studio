"""OBJ and GLB from the exported STL, with numpy only (no kernel, no GPU), so they work headless and in the CLI.

The geometry is the exported STL's triangles, welded (identical vertices shared) so viewers smooth and count them
correctly. Units stay millimetres in OBJ. glTF is in metres by definition, so the GLB is scaled by 0.001 and turned
from Z-up (CAD) to Y-up (glTF); a viewer shows the part the right size and the right way up.

    obj_bytes(stl_path, name)    Wavefront OBJ (text)
    glb_bytes(stl_path, name)    binary glTF 2.0, one mesh with normals
    glb_scene(nodes, materials, images)
                                 binary glTF 2.0 with several named nodes, UVs (TEXCOORD_0), PBR materials and
                                 embedded PNG textures: the game asset writer (form/game). Positions go in as given
                                 (the caller converts to metres, Y up); node extras carry LOD and collision labels.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np


def read_stl(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(vertices float64 (n, 3), faces int64 (m, 3)) from a binary or ASCII STL, welded."""
    data = Path(path).read_bytes()
    tris = None
    if len(data) >= 84:
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + 50 * n == len(data):
            rec = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n, offset=84)
            tris = rec["v"].astype(np.float64)
    if tris is None:
        vals = [ln.split()[1:4] for ln in data.decode("utf-8", "replace").splitlines() if ln.strip().startswith("vertex")]
        if not vals or len(vals) % 3:
            raise ValueError(f"{Path(path).name} is not a readable STL.")
        tris = np.asarray(vals, dtype=np.float64).reshape(-1, 3, 3)
    flat = tris.reshape(-1, 3)
    verts, inv = np.unique(np.round(flat, 6), axis=0, return_inverse=True)
    faces = inv.reshape(-1, 3).astype(np.int64)
    keep = (faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])
    return verts, faces[keep]


def _normals(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    vn = np.zeros_like(v)
    for i in range(3):
        np.add.at(vn, f[:, i], fn)
    ln = np.linalg.norm(vn, axis=1, keepdims=True)
    ln[ln == 0] = 1.0
    return vn / ln


def obj_bytes(stl_path: Path, name: str = "part") -> bytes:
    v, f = read_stl(stl_path)
    out = [f"# {name}: exported by Form Studio from the CAD solid's STL. Units: millimetres.",
           f"o {''.join(c if c.isalnum() or c in '-_.' else '_' for c in name) or 'part'}"]
    out += [f"v {x:.6g} {y:.6g} {z:.6g}" for x, y, z in v]
    out += [f"f {a + 1} {b + 1} {c + 1}" for a, b, c in f]
    return ("\n".join(out) + "\n").encode("utf-8")


def glb_bytes(stl_path: Path, name: str = "part") -> bytes:
    v, f = read_stl(stl_path)
    # Z-up millimetres (CAD) to Y-up metres (glTF): (x, y, z) -> (x, z, -y) * 0.001
    p = np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1) * 0.001
    n = _normals(p, f)
    pos = p.astype("<f4").tobytes()
    nor = n.astype("<f4").tobytes()
    idx = f.astype("<u4").tobytes()
    pad = lambda b, c=b"\x00": b + c * ((4 - len(b) % 4) % 4)
    blob = pad(pos) + pad(nor) + pad(idx)
    o_nor, o_idx = len(pad(pos)), len(pad(pos)) + len(pad(nor))
    gltf = {
        "asset": {"version": "2.0", "generator": "Form Studio"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": name}],
        "materials": [{"name": "Default", "pbrMetallicRoughness": {"baseColorFactor": [0.85, 0.83, 0.78, 1], "metallicFactor": 0,
                                                                   "roughnessFactor": 0.6}}],
        "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos), "target": 34962},
                        {"buffer": 0, "byteOffset": o_nor, "byteLength": len(nor), "target": 34962},
                        {"buffer": 0, "byteOffset": o_idx, "byteLength": len(idx), "target": 34963}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(p), "type": "VEC3",
                       "min": [float(x) for x in p.min(axis=0)], "max": [float(x) for x in p.max(axis=0)]},
                      {"bufferView": 1, "componentType": 5126, "count": len(n), "type": "VEC3"},
                      {"bufferView": 2, "componentType": 5125, "count": int(f.size), "type": "SCALAR"}],
    }
    js = pad(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + blob
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


def _pad(b: bytes, c: bytes = b"\x00") -> bytes:
    return b + c * ((4 - len(b) % 4) % 4)


def glb_scene(nodes: list[dict], materials: list[dict] | None = None, images: list[bytes] | None = None,
              generator: str = "Form Studio", extras: dict | None = None) -> bytes:
    """A binary glTF 2.0 file of several meshes.

    nodes: [{"name", "P" (n, 3) float, "idx" (t, 3) int, optional "N" (n, 3), "UV" (n, 2) (glTF convention: v down,
    so pass 1 - v of a Blender UV), "material" (index into materials), "extras" (dict)}]. Each node has one mesh with
    one primitive.
    materials: [{"name", "base_color" [r,g,b,a], "metallic", "roughness", optional "base_color_tex", "orm_tex",
    "normal_tex", "emissive_tex" (indices into images; the ORM image serves as occlusion and metallicRoughness, as
    glTF intends; an emissive texture is read with emissiveFactor 1)}].
    images: PNG bytes, embedded in the binary chunk."""
    materials, images = list(materials or []), list(images or [])
    blob = bytearray()
    views, accessors = [], []

    def view(data: bytes, target=None) -> int:
        off = len(blob)
        blob.extend(_pad(data))
        v = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target:
            v["target"] = target
        views.append(v)
        return len(views) - 1

    def acc(arr: np.ndarray, kind: str, comp: int, target=34962, minmax=False) -> int:
        a = np.ascontiguousarray(arr, dtype="<u4" if comp == 5125 else "<f4")
        d = {"bufferView": view(a.tobytes(), target), "componentType": comp, "count": int(len(a) if a.ndim > 1 else a.size),
             "type": kind}
        if minmax:
            d["min"] = [float(x) for x in a.min(axis=0)]
            d["max"] = [float(x) for x in a.max(axis=0)]
        accessors.append(d)
        return len(accessors) - 1

    gnodes, meshes = [], []
    for nd in nodes:
        P = np.asarray(nd["P"], dtype=np.float64).reshape(-1, 3)
        T = np.asarray(nd["idx"], dtype=np.int64).reshape(-1, 3)
        if len(T) and (T.min() < 0 or T.max() >= len(P)):
            raise ValueError(f"node {nd.get('name')}: an index points past its {len(P)} points")
        attrs = {"POSITION": acc(P, "VEC3", 5126, minmax=True)}
        if nd.get("N") is not None:
            N = np.asarray(nd["N"], dtype=np.float64).reshape(-1, 3)
            ln = np.linalg.norm(N, axis=1, keepdims=True)
            ln[ln == 0] = 1.0
            attrs["NORMAL"] = acc(N / ln, "VEC3", 5126)
        if nd.get("UV") is not None:
            attrs["TEXCOORD_0"] = acc(np.asarray(nd["UV"], dtype=np.float64).reshape(-1, 2), "VEC2", 5126)
        prim = {"attributes": attrs, "indices": acc(T.reshape(-1), "SCALAR", 5125, target=34963), "mode": 4}
        if nd.get("material") is not None:
            prim["material"] = int(nd["material"])
        meshes.append({"name": nd.get("name", "mesh"), "primitives": [prim]})
        g = {"name": nd.get("name", "node"), "mesh": len(meshes) - 1}
        if nd.get("extras"):
            g["extras"] = nd["extras"]
        gnodes.append(g)
    gimages, textures = [], []
    for im in images:
        gimages.append({"bufferView": view(bytes(im)), "mimeType": "image/png"})
        textures.append({"source": len(gimages) - 1, "sampler": 0})
    gmats = []
    for m in materials:
        pbr = {"baseColorFactor": [float(x) for x in (m.get("base_color") or [1, 1, 1, 1])],
               "metallicFactor": float(m.get("metallic", 0.0)), "roughnessFactor": float(m.get("roughness", 0.5))}
        g = {"name": m.get("name", "material"), "pbrMetallicRoughness": pbr}
        if m.get("base_color_tex") is not None:
            pbr["baseColorTexture"] = {"index": int(m["base_color_tex"])}
        if m.get("orm_tex") is not None:
            pbr["metallicRoughnessTexture"] = {"index": int(m["orm_tex"])}
            g["occlusionTexture"] = {"index": int(m["orm_tex"])}
        if m.get("normal_tex") is not None:
            g["normalTexture"] = {"index": int(m["normal_tex"])}
        if m.get("emissive_tex") is not None:
            g["emissiveTexture"] = {"index": int(m["emissive_tex"])}
            g["emissiveFactor"] = [1.0, 1.0, 1.0]
        gmats.append(g)
    gltf = {"asset": {"version": "2.0", "generator": generator}, "scene": 0,
            "scenes": [{"nodes": list(range(len(gnodes)))}], "nodes": gnodes, "meshes": meshes,
            "buffers": [{"byteLength": len(blob)}], "bufferViews": views, "accessors": accessors}
    if gmats:
        gltf["materials"] = gmats
    if gimages:
        gltf.update(images=gimages, textures=textures,
                    samplers=[{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}])
    if extras:
        gltf["asset"]["extras"] = extras
    js = _pad(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


FORMATS = {"obj": ("OBJ", "model/obj", obj_bytes), "glb": ("glTF binary (GLB)", "model/gltf-binary", glb_bytes)}
