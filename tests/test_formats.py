"""Every format Form Studio reads, read for real: small files written here (no binaries in the repository), each
read back and taken through triage to its route, with sizes and units checked. And one table (form/formats.py) that
the app's dialogs, attachments, import_reference, reconstruct, triage, link downloads, the CLI and the tool
descriptions all agree with."""
import base64
import io
import json
import os
import re
import shutil
import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path

import numpy as np

os.environ.setdefault("FORM_SKIP_UI", "1")
_DATA = tempfile.mkdtemp(prefix="form-formats-")
os.environ["FORM_DATA"] = _DATA                      # the archive and point cloud caches land here, never in ~/FORM

from form import formats, meshformats, pointcloud, triage  # noqa: E402
from form.recon import mesh as meshmod  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# a 20 x 10 x 6 mm box, corner at the origin, triangles facing out
BOX = np.array([20.0, 10.0, 6.0])
V = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float) * BOX
F = np.array([[0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5], [2, 3, 7],
              [2, 7, 6], [3, 0, 4], [3, 4, 7]])
QUADS = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
VOLUME = float(np.prod(BOX))


def sphere_points(n=20000, r=15.0, seed=3):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 3))
    X /= np.linalg.norm(X, axis=1)[:, None]
    return X * r


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def read(self, path):
        T, info = meshmod.read_triangles(path)
        Vw, Fw, _w = meshmod.weld(T, 1e-6)
        return T, info, meshmod.topology(Vw, Fw)

    def assertBox(self, path, scale=1.0, offset=(0, 0, 0), vol=None):
        T, info, top = self.read(path)
        P = T.reshape(-1, 3)
        np.testing.assert_allclose(P.min(axis=0), np.asarray(offset, float), atol=1e-4)
        np.testing.assert_allclose(P.max(axis=0) - P.min(axis=0), BOX * scale, atol=1e-4)
        self.assertTrue(top["closed"], (path.name, top))
        self.assertAlmostEqual(top["volume_mm3"], vol or VOLUME * scale ** 3, delta=1e-3 * VOLUME * scale ** 3)
        t = triage.triage(str(path))
        self.assertEqual(t["route"], "parametric", (path.name, t["why"]))
        self.assertEqual(t["class"], "mechanical")
        return info, t


def obj_text(Vx=V, Fx=F):
    return "".join(f"v {a} {b} {c}\n" for a, b, c in Vx) + "".join(f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in Fx)


class Meshes(Tmp):
    def test_ply_ascii(self):
        p = self.tmp / "a.ply"
        p.write_text("ply\nformat ascii 1.0\ncomment made here\nelement vertex 8\nproperty float x\nproperty float y\n"
                     "property float z\nelement face 6\nproperty list uchar int vertex_indices\nend_header\n"
                     + "".join(f"{a} {b} {c}\n" for a, b, c in V) + "".join("4 " + " ".join(map(str, q)) + "\n" for q in QUADS))
        info, t = self.assertBox(p)
        self.assertEqual(info["format"], "ply (ascii)")
        self.assertIn("assumed", t["facts"]["units"]["source"])

    def test_ply_binary_with_vertex_colours(self):
        for bo, word in (("<", "little"), (">", "big")):
            head = (f"ply\nformat binary_{word}_endian 1.0\nelement vertex 8\nproperty float x\nproperty float y\n"
                    "property float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nelement face 12\n"
                    "property list uchar uint vertex_indices\nend_header\n").encode()
            vt = np.zeros(8, dtype=[("p", bo + "f4", 3), ("c", "u1", 3)])
            vt["p"], vt["c"] = V, 200
            ft = np.zeros(12, dtype=[("n", "u1"), ("i", bo + "u4", 3)])
            ft["n"], ft["i"] = 3, F
            p = self.tmp / f"c_{word}.ply"
            p.write_bytes(head + vt.tobytes() + ft.tobytes())
            info, t = self.assertBox(p)
            self.assertIn("vertex colours", " ".join(info["notes"]))

    def test_ply_of_vertices_is_a_point_cloud(self):
        P = sphere_points()
        head = (f"ply\nformat binary_little_endian 1.0\nelement vertex {len(P)}\nproperty double x\nproperty double y\n"
                "property double z\nend_header\n").encode()
        p = self.tmp / "scan.ply"
        p.write_bytes(head + P.astype("<f8").tobytes())
        t = triage.triage(str(p))
        self.assertEqual(t["input"]["kind"], "pointcloud")
        self.assertEqual(t["facts"]["points"], len(P))
        self.assertEqual(t["prepare"][0]["step"], "surface_from_points")
        self.assertTrue(t["facts"]["after_repair"]["closed"])
        self.assertEqual(t["class"], "organic")
        self.assertIn(t["route"], ("surface_body", "mesh_body"))

    def test_off(self):
        p = self.tmp / "a.off"
        p.write_text("OFF\n# a box\n8 6 0\n" + "".join(f"{a} {b} {c}\n" for a, b, c in V)
                     + "".join("4 " + " ".join(map(str, q)) + " 255 0 0\n" for q in QUADS))
        self.assertBox(p)

    def test_amf_inches_plain_and_zipped(self):
        xml = ('<?xml version="1.0"?><amf unit="inch"><object id="1"><metadata type="name">Bracket</metadata><mesh>'
               "<vertices>" + "".join(f"<vertex><coordinates><x>{a / 25.4}</x><y>{b / 25.4}</y><z>{c / 25.4}</z>"
                                       "</coordinates></vertex>" for a, b, c in V)
               + "</vertices><volume>" + "".join(f"<triangle><v1>{a}</v1><v2>{b}</v2><v3>{c}</v3></triangle>" for a, b, c in F)
               + "</volume></mesh></object></amf>")
        p = self.tmp / "a.amf"
        p.write_text(xml)
        info, t = self.assertBox(p)
        self.assertEqual(t["facts"]["units"]["units"], "inch")
        self.assertEqual(t["facts"]["units"]["converted"], "to millimetres on read")
        z = self.tmp / "z.amf"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("z.amf", xml)
        self.assertBox(z)

    def test_glb_round_trip_of_form_studios_own_export(self):
        from form import meshio
        stl = self.tmp / "box.stl"
        meshmod.write_stl(stl, V, F)
        p = self.tmp / "box.glb"
        p.write_bytes(meshio.glb_bytes(stl, "box"))            # metres and Y up in the file
        info, t = self.assertBox(p)
        self.assertEqual(t["facts"]["units"]["units"], "m")
        self.assertIn("Z up", t["facts"]["axes"])

    def _gltf_json(self, buffer_uri):
        P = (V @ meshformats.Y_UP_TO_Z_UP * 0.001).astype("<f4")      # mm Z up -> m Y up
        blob = P.tobytes() + F.astype("<u2").tobytes()
        js = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
              "nodes": [{"children": [1], "translation": [0.005, 0, 0]}, {"mesh": 0, "name": "inner"}],
              "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
              "buffers": [{"byteLength": len(blob), "uri": buffer_uri(blob)}],
              "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": P.nbytes},
                              {"buffer": 0, "byteOffset": P.nbytes, "byteLength": F.size * 2}],
              "accessors": [{"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3"},
                            {"bufferView": 1, "componentType": 5123, "count": F.size, "type": "SCALAR"}]}
        return js, blob

    def test_gltf_with_data_uri_and_node_transform(self):
        js, _ = self._gltf_json(lambda b: "data:application/octet-stream;base64," + base64.b64encode(b).decode())
        p = self.tmp / "a.gltf"
        p.write_text(json.dumps(js))
        self.assertBox(p, offset=(5, 0, 0))

    def test_gltf_with_its_bin_missing_says_what_to_send(self):
        js, _ = self._gltf_json(lambda b: "a.bin")
        p = self.tmp / "a.gltf"
        p.write_text(json.dumps(js))
        with self.assertRaisesRegex(ValueError, "beside it"):
            meshmod.read_triangles(p)

    def test_gltf_with_its_bin_in_a_zip(self):
        js, blob = self._gltf_json(lambda b: "a.bin")
        z = self.tmp / "model.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("model/a.gltf", json.dumps(js))
            zf.writestr("model/a.bin", blob)
        t = triage.triage(str(z))
        self.assertEqual(t["route"], "archive")
        self.assertEqual([m["route"] for m in t["members"]], ["parametric"])

    def test_draco_is_refused_by_name(self):
        js, _ = self._gltf_json(lambda b: "data:;base64," + base64.b64encode(b).decode())
        js["extensionsRequired"] = ["KHR_draco_mesh_compression"]
        p = self.tmp / "d.gltf"
        p.write_text(json.dumps(js))
        with self.assertRaisesRegex(ValueError, "KHR_draco_mesh_compression"):
            meshmod.read_triangles(p)

    def _dae(self, meter, up, P, translate=""):
        pos = " ".join(f"{x:.9g}" for x in P.reshape(-1))
        return f"""<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
 <asset><unit name="u" meter="{meter}"/><up_axis>{up}</up_axis></asset>
 <library_geometries><geometry id="g" name="box"><mesh>
  <source id="g-pos"><float_array id="g-arr" count="24">{pos}</float_array>
   <technique_common><accessor source="#g-arr" count="8" stride="3"><param name="X" type="float"/>
   <param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
  <vertices id="g-v"><input semantic="POSITION" source="#g-pos"/></vertices>
  <polylist count="6"><input semantic="VERTEX" source="#g-v" offset="0"/>
   <vcount>4 4 4 4 4 4</vcount><p>{" ".join(str(i) for q in QUADS for i in q)}</p></polylist>
 </mesh></geometry></library_geometries>
 <library_visual_scenes><visual_scene id="s"><node id="n" name="Box">{translate}
  <instance_geometry url="#g"/></node></visual_scene></library_visual_scenes>
 <scene><instance_visual_scene url="#s"/></scene></COLLADA>"""

    def test_dae_units_and_up_axis(self):
        p = self.tmp / "mm.dae"
        p.write_text(self._dae(0.001, "Z_UP", V))
        info, t = self.assertBox(p)
        self.assertEqual(t["facts"]["units"]["units"], "mm")
        p = self.tmp / "m.dae"                                   # metres, Y up, moved 2 cm along x
        p.write_text(self._dae(1.0, "Y_UP", V @ meshformats.Y_UP_TO_Z_UP * 0.001, "<translate>0.02 0 0</translate>"))
        info, t = self.assertBox(p, offset=(20, 0, 0))
        self.assertEqual(t["facts"]["units"]["units"], "m")

    def test_x3d_with_transform(self):
        pts = " ".join(f"{a} {b} {c}" for a, b, c in V)
        idx = " ".join(" ".join(map(str, q)) + " -1" for q in QUADS)
        p = self.tmp / "a.x3d"
        p.write_text(f'<?xml version="1.0"?><X3D version="3.3"><Scene><Transform translation="1 2 3"><Shape>'
                     f'<IndexedFaceSet coordIndex="{idx}"><Coordinate point="{pts}"/></IndexedFaceSet></Shape>'
                     "</Transform></Scene></X3D>")
        info, t = self.assertBox(p, offset=(1, 2, 3))
        self.assertIn("assumed", t["facts"]["units"]["source"])

    def test_vrml_with_def_and_use(self):
        pts = ", ".join(f"{a} {b} {c}" for a, b, c in V)
        idx = ", ".join(", ".join(map(str, q)) + ", -1" for q in QUADS)
        p = self.tmp / "a.wrl"
        p.write_text(f"#VRML V2.0 utf8\n# exported\nTransform {{ translation 0 0 10 children [\n Shape {{ appearance "
                     f"Appearance {{ material Material {{ diffuseColor 1 0 0 }} }}\n geometry IndexedFaceSet {{ coord "
                     f"DEF C Coordinate {{ point [ {pts} ] }} coordIndex [ {idx} ] }} }} ] }}\n")
        self.assertBox(p, offset=(0, 0, 10))
        self.assertEqual(formats.kind_of("x.vrml"), "mesh")

    def test_vtk_legacy_ascii_and_binary_solid_cell(self):
        p = self.tmp / "a.vtk"
        p.write_text("# vtk DataFile Version 3.0\nbox\nASCII\nDATASET POLYDATA\nPOINTS 8 float\n"
                     + "".join(f"{a} {b} {c}\n" for a, b, c in V) + f"POLYGONS 6 30\n"
                     + "".join("4 " + " ".join(map(str, q)) + "\n" for q in QUADS) + "POINT_DATA 8\n")
        self.assertBox(p)
        # one hexahedron in an unstructured grid, binary (big endian): its six outer faces
        hexa = [0, 1, 2, 3, 4, 5, 6, 7]
        b = (b"# vtk DataFile Version 3.0\nhex\nBINARY\nDATASET UNSTRUCTURED_GRID\nPOINTS 8 double\n"
             + V.astype(">f8").tobytes() + b"\nCELLS 1 9\n" + np.array([8, *hexa], ">i4").tobytes()
             + b"\nCELL_TYPES 1\n" + np.array([12], ">i4").tobytes() + b"\n")
        p = self.tmp / "hex.vtk"
        p.write_bytes(b)
        info, t = self.assertBox(p)
        self.assertIn("outer faces", " ".join(info["notes"]))

    def test_vtp_ascii_binary_zlib_and_vtu_appended(self):
        conn = np.array([i for q in QUADS for i in q], np.int64)
        offs = np.arange(4, 25, 4, dtype=np.int64)
        asc = lambda a: " ".join(map(str, a.reshape(-1)))  # noqa: E731
        p = self.tmp / "a.vtp"
        p.write_text(f'<VTKFile type="PolyData" version="1.0"><PolyData><Piece NumberOfPoints="8" NumberOfPolys="6">'
                     f'<Points><DataArray type="Float64" NumberOfComponents="3" format="ascii">{asc(V)}</DataArray>'
                     f'</Points><Polys><DataArray type="Int64" Name="connectivity" format="ascii">{asc(conn)}</DataArray>'
                     f'<DataArray type="Int64" Name="offsets" format="ascii">{asc(offs)}</DataArray></Polys></Piece>'
                     "</PolyData></VTKFile>")
        self.assertBox(p)

        def zblock(a):                                   # VTK's zlib block layout: [n, size, last, csize] + data
            raw = a.tobytes()
            c = zlib.compress(raw)
            head = np.array([1, len(raw), len(raw), len(c)], "<u4").tobytes()
            return base64.b64encode(head).decode() + base64.b64encode(c).decode()
        p = self.tmp / "z.vtp"
        p.write_text(f'<VTKFile type="PolyData" version="1.0" byte_order="LittleEndian" header_type="UInt32" '
                     f'compressor="vtkZLibDataCompressor"><PolyData><Piece NumberOfPoints="8" NumberOfPolys="6">'
                     f'<Points><DataArray type="Float32" NumberOfComponents="3" format="binary">'
                     f'{zblock(V.astype("<f4"))}</DataArray></Points><Polys>'
                     f'<DataArray type="Int64" Name="connectivity" format="binary">{zblock(conn)}</DataArray>'
                     f'<DataArray type="Int64" Name="offsets" format="binary">{zblock(offs)}</DataArray></Polys>'
                     "</Piece></PolyData></VTKFile>")
        self.assertBox(p)
        arrays = [V.astype("<f8").tobytes(), np.arange(8, dtype="<i8").tobytes(), np.array([8], "<i8").tobytes(),
                  np.array([12], "<u1").tobytes()]
        offsets, blob = [], b""
        for a in arrays:
            offsets.append(len(blob))
            blob += struct.pack("<I", len(a)) + a
        p = self.tmp / "a.vtu"
        p.write_bytes((f'<VTKFile type="UnstructuredGrid" version="1.0" byte_order="LittleEndian" header_type="UInt32">'
                       f'<UnstructuredGrid><Piece NumberOfPoints="8" NumberOfCells="1"><Points>'
                       f'<DataArray type="Float64" NumberOfComponents="3" format="appended" offset="{offsets[0]}"/>'
                       f'</Points><Cells><DataArray type="Int64" Name="connectivity" format="appended" offset="{offsets[1]}"/>'
                       f'<DataArray type="Int64" Name="offsets" format="appended" offset="{offsets[2]}"/>'
                       f'<DataArray type="UInt8" Name="types" format="appended" offset="{offsets[3]}"/></Cells></Piece>'
                       f'</UnstructuredGrid><AppendedData encoding="raw">_').encode() + blob
                      + b"</AppendedData></VTKFile>")
        self.assertBox(p)


class PointClouds(Tmp):
    def check_sphere(self, path, r=15.0, units=None):
        t = triage.triage(str(path))
        self.assertEqual(t["input"]["kind"], "pointcloud", t["why"])
        f = t["facts"]
        self.assertTrue(f["after_repair"]["closed"], f["after_repair"])
        np.testing.assert_allclose(f["size_mm"], [2 * r] * 3, rtol=0.03)
        if units:
            self.assertEqual(f["units"]["units"], units)
        T, _info = meshmod.read_triangles(path)
        Vw, Fw, _w = meshmod.weld(T, 1e-6)
        vol = abs(meshmod.topology(Vw, Fw)["volume_mm3"])
        self.assertAlmostEqual(vol / (4 / 3 * np.pi * r ** 3), 1.0, delta=0.03)
        return t

    def test_xyz_and_pts(self):
        P = sphere_points()
        p = self.tmp / "s.xyz"
        p.write_text("".join(f"{a:.5f} {b:.5f} {c:.5f}\n" for a, b, c in P))
        t = self.check_sphere(p)
        self.assertIn("estimated", t["facts"]["surface_from_points"]["normals"])
        p = self.tmp / "s.pts"
        p.write_text(f"{len(P)}\n" + "".join(f"{a:.5f} {b:.5f} {c:.5f} 120 10 20 30\n" for a, b, c in P))
        self.check_sphere(p)

    def test_xyz_with_normals_uses_them(self):
        P = sphere_points()
        N = P / np.linalg.norm(P, axis=1)[:, None]
        p = self.tmp / "n.xyz"
        p.write_text("".join(f"{a:.5f} {b:.5f} {c:.5f} {d:.5f} {e:.5f} {g:.5f}\n" for (a, b, c), (d, e, g) in zip(P, N)))
        t = self.check_sphere(p)
        self.assertEqual(t["facts"]["surface_from_points"]["normals"], "from the file")

    def test_las_metres_far_from_the_origin(self):
        P = sphere_points(r=0.015) + np.array([512000.0, 4100000.0, 200.0])      # survey coordinates, metres
        scale, off = 1e-5, P.min(axis=0).round(0)
        X = np.round((P - off) / scale).astype("<i4")
        rec = np.zeros(len(P), dtype=[("xyz", "<i4", 3), ("rest", "u1", 8)])
        rec["xyz"] = X
        h = bytearray(227)
        h[0:4] = b"LASF"
        h[24], h[25] = 1, 2
        struct.pack_into("<HIIBHI", h, 94, 227, 227, 0, 0, 20, len(P))
        struct.pack_into("<6d", h, 131, scale, scale, scale, *off)
        p = self.tmp / "s.las"
        p.write_bytes(bytes(h) + rec.tobytes())
        self.check_sphere(p, units="m")

    def test_laz_is_refused_by_name(self):
        h = bytearray(227)
        h[0:4] = b"LASF"
        h[24], h[25] = 1, 2
        h[104] = 0x80 | 3
        p = self.tmp / "s.las"
        p.write_bytes(bytes(h))
        with self.assertRaisesRegex(ValueError, "LAZ"):
            meshmod.read_triangles(p)
        self.assertIn("LAZ", formats.unsupported("x.laz"))

    def test_e57_float_and_scaled_integer(self):
        P = sphere_points(r=0.015)                                      # metres
        for kind in ("float", "scaled"):
            p = self.tmp / f"{kind}.e57"
            p.write_bytes(e57_bytes(P, kind, pose_t=(1.0, 0, 0)))
            t = self.check_sphere(p, units="m")
            self.assertAlmostEqual(t["facts"]["bbox"][0][0], 1000.0 - 15.0, delta=0.5)   # placed by its pose


def e57_bytes(P: np.ndarray, kind: str, pose_t=(0, 0, 0), page=1024) -> bytes:
    """A minimal ASTM E57 file: one scan, cartesian x, y, z as Float (double) or ScaledInteger fields."""
    n = len(P)
    if kind == "float":
        streams = [P[:, i].astype("<f8").tobytes() for i in range(3)]
        proto = "".join(f'<cartesian{c} type="Float"/>' for c in "XYZ")
    else:
        sc = 1e-6
        lo, hi = int(np.floor(P.min() / sc)) - 1, int(np.ceil(P.max() / sc)) + 1
        bits = int(np.ceil(np.log2(hi - lo + 1)))
        streams = []
        for i in range(3):
            v = (np.round(P[:, i] / sc).astype(np.int64) - lo)
            b = ((v[:, None] >> np.arange(bits)) & 1).astype(np.uint8).reshape(-1)
            streams.append(np.packbits(b, bitorder="little").tobytes())
        proto = "".join(f'<cartesian{c} type="ScaledInteger" minimum="{lo}" maximum="{hi}" scale="{sc}" offset="0"/>'
                        for c in "XYZ")
    # data packets of at most 64 KB, each carrying a share of every stream
    per = 2000                                   # 48 kB a packet (a packet is at most 64 kB)
    packets = b""
    for k in range(0, n, per):
        m = min(per, n - k)
        if kind == "float":
            parts = [s[8 * k:8 * (k + m)] for s in streams]
        else:
            nb = lambda j: (j * bits) // 8  # noqa: E731 - per packs are byte aligned below (per % 8 == 0)
            parts = [s[nb(k):nb(k + m)] if k + m < n else s[nb(k):] for s in streams]
        body = struct.pack("<3H", *[len(x) for x in parts]) + b"".join(parts)
        L = 6 + len(body)
        pad = (-L) % 4
        packets += struct.pack("<BBHH", 1, 0, L + pad - 1, 3) + body + b"\0" * pad
    phys = lambda lg: (lg // (page - 4)) * page + lg % (page - 4)  # noqa: E731
    sec_at = 48
    section = struct.pack("<B7sQQQ", 1, b"\0" * 7, 32 + len(packets), phys(sec_at + 32), 0) + packets
    xml_at = sec_at + len(section)
    xml = (f'<?xml version="1.0"?><e57Root type="Structure" xmlns="http://www.astm.org/COMMIT/E57/2010-e57-v1.0">'
           f'<data3D type="Vector" allowHeterogeneousChildren="1"><vectorChild type="Structure">'
           f'<pose type="Structure"><rotation type="Structure"><w type="Float">1</w><x type="Float">0</x>'
           f'<y type="Float">0</y><z type="Float">0</z></rotation><translation type="Structure">'
           f'<x type="Float">{pose_t[0]}</x><y type="Float">{pose_t[1]}</y><z type="Float">{pose_t[2]}</z></translation></pose>'
           f'<points type="CompressedVector" fileOffset="{phys(sec_at)}" recordCount="{n}">'
           f'<prototype type="Structure">{proto}</prototype><codecs type="Vector"/></points></vectorChild></data3D>'
           f"</e57Root>").encode()
    logical = bytearray(48) + section + xml
    total_phys = phys(len(logical)) + page
    struct.pack_into("<8sIIQQQQ", logical, 0, b"ASTM-E57", 1, 0, total_phys, phys(xml_at), len(xml), page)
    out = bytearray()
    for i in range(0, len(logical), page - 4):
        chunk = bytes(logical[i:i + page - 4]).ljust(page - 4, b"\0")
        out += chunk + b"\0\0\0\0"                                     # the page checksum (not checked on read)
    return bytes(out)


class Cad(Tmp):
    def test_step_iges_brep_triage_and_kernel_read(self):
        from build123d import Box, export_brep, export_step
        from OCP.IGESControl import IGESControl_Writer
        from form.recipes.meshsolid import import_cad
        b = Box(20, 10, 6)
        files = {"a.step": lambda p: export_step(b, str(p)), "a.brep": lambda p: export_brep(b, str(p))}

        def iges(p):
            w = IGESControl_Writer("MM", 1)
            w.AddShape(b.wrapped)
            w.ComputeModel()
            w.Write(str(p))
        files["a.igs"] = iges
        for name, write in files.items():
            p = self.tmp / name
            write(p)
            t = triage.triage(str(p))
            self.assertEqual(t["route"], "cad_reference", (name, t["why"]))
            self.assertGreaterEqual(t["facts"]["faces"], 6 if name != "a.brep" else 1, name)
            shape = import_cad(p)
            self.assertAlmostEqual(shape.volume, VOLUME, delta=1e-3 * VOLUME, msg=name)
        self.assertEqual(triage.triage(str(self.tmp / "a.igs"))["facts"]["units"]["units"], "mm")


class Drawings(Tmp):
    def test_dxf_units_and_outlines(self):
        import ezdxf
        for units, k in ((4, 1.0), (1, 25.4)):
            doc = ezdxf.new()
            doc.header["$INSUNITS"] = units
            msp = doc.modelspace()
            msp.add_lwpolyline([(0, 0), (40, 0), (40, 20), (0, 20)], close=True)
            msp.add_circle((10, 10), 3)
            p = self.tmp / f"u{units}.dxf"
            doc.saveas(p)
            t = triage.triage(str(p))
            self.assertEqual(t["route"], "profile")
            self.assertEqual(t["facts"]["closed_outlines"], 2)
            np.testing.assert_allclose(t["facts"]["size_mm"], [40 * k, 20 * k], rtol=1e-6)

    def test_svg_in_millimetres(self):
        p = self.tmp / "a.svg"
        p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="60mm" height="30mm" viewBox="0 0 60 30">'
                     '<rect x="5" y="5" width="50" height="20"/><circle cx="30" cy="15" r="4"/></svg>')
        t = triage.triage(str(p))
        self.assertEqual(t["route"], "profile")
        self.assertEqual(t["facts"]["units"]["units"], "mm")
        np.testing.assert_allclose(t["facts"]["size_mm"], [50, 20], atol=0.01)
        self.assertEqual(t["facts"]["closed_outlines"], 2)


class Archives(Tmp):
    def test_zip_of_parts_is_unpacked_safely_and_each_file_triaged(self):
        meshmod.write_stl(self.tmp / "b.stl", V, F)
        z = self.tmp / "thing.zip"
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as zi:
            zi.writestr("lid.obj", obj_text(V + [0, 0, 20], F))
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(self.tmp / "b.stl", "files/base.stl")
            zf.writestr("../evil.stl", "solid x\nendsolid x\n")                  # zip slip
            zf.writestr("/abs.stl", "solid x\nendsolid x\n")
            zf.writestr("__MACOSX/files/._base.stl", "junk")
            zf.writestr("README.txt", "hello")
            zf.writestr("more/lid.zip", inner.getvalue())
        t = triage.triage(str(z))
        self.assertEqual(t["route"], "archive")
        names = sorted(m["name"] for m in t["members"])
        self.assertEqual(names, ["files/base.stl", "more/lid.zip/lid.obj"])
        self.assertTrue(all(m["route"] == "parametric" for m in t["members"]))
        folder = Path(t["facts"]["folder"])
        for m in t["members"]:
            self.assertTrue(Path(m["path"]).resolve().is_relative_to(folder.resolve()))
        self.assertFalse((folder.parent / "evil.stl").exists())
        skipped = " ".join(s["name"] for s in t["facts"]["skipped"])
        self.assertIn("evil.stl", skipped)
        self.assertIn("README.txt", skipped)
        self.assertIn("reconstruct(files=", t["steps"][0])

    def test_a_zip_bomb_is_refused(self):
        z = self.tmp / "bomb.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("big.stl", b"\0" * 60_000_000)
        t = triage.triage(str(z))
        self.assertEqual(t["route"], "unknown")
        self.assertIn("zip bomb", t["why"])


class Unsupported(Tmp):
    def test_one_message_names_what_is_read(self):
        for ext in (".fbx", ".usdz", ".xyz123", ".sldprt"):
            p = self.tmp / f"part{ext}"
            p.write_bytes(b"x")
            t = triage.triage(str(p))
            self.assertEqual(t["route"], "unknown")
            for must in ("STL", "PLY", "E57", "STEP", "IGES", "DXF", "zip"):
                self.assertIn(must, t["why"], ext)
        self.assertIn("FBX", formats.unsupported("a.fbx"))
        self.assertIn("usd-core", formats.unsupported("a.usdz"))
        with self.assertRaisesRegex(ValueError, "Form Studio reads"):
            meshmod.read_triangles(self.tmp / "part.fbx")


class ImportReference(unittest.TestCase):
    """import_reference through the real kernel: a PLY, a glTF, an IGES, a scan and a zip of parts."""

    @classmethod
    def setUpClass(cls):
        from form import config
        from form.studio import Studio
        cls.tmp = Path(tempfile.mkdtemp())
        cls.st = Studio(config.load())

    @classmethod
    def tearDownClass(cls):
        cls.st.kernel.stop()
        shutil.rmtree(cls.tmp, True)

    def test_every_kind_of_part_comes_in(self):
        from build123d import Box
        from OCP.IGESControl import IGESControl_Writer
        from form import meshio
        from form.design_guide import EXAMPLE
        from form.studio import StudioError
        p = self.st.create_design("Formats holder", EXAMPLE)
        ply = self.tmp / "scan part.ply"
        ply.write_text("ply\nformat ascii 1.0\nelement vertex 8\nproperty float x\nproperty float y\nproperty float z\n"
                       "element face 12\nproperty list uchar int vertex_indices\nend_header\n"
                       + "".join(f"{a} {b} {c}\n" for a, b, c in V) + "".join(f"3 {a} {b} {c}\n" for a, b, c in F))
        stl = self.tmp / "b.stl"
        meshmod.write_stl(stl, V, F)
        glb = self.tmp / "b.glb"
        glb.write_bytes(meshio.glb_bytes(stl, "b"))
        igs = self.tmp / "b.igs"
        w = IGESControl_Writer("MM", 1)
        w.AddShape(Box(20, 10, 6).wrapped)
        w.ComputeModel()
        w.Write(str(igs))
        xyz = self.tmp / "ball.xyz"
        xyz.write_text("".join(f"{a:.5f} {b:.5f} {c:.5f}\n" for a, b, c in sphere_points(8000, 10.0)))
        for src, fmt, vol in ((ply, "ply", VOLUME), (glb, "glb", VOLUME), (igs, "igs", VOLUME),
                              (xyz, "xyz", 4 / 3 * np.pi * 1000)):
            rec = self.st.import_reference(self.st.load(p["id"]), src)
            self.assertEqual(rec["format"], fmt)
            self.assertAlmostEqual(rec["volume_mm3"], vol, delta=0.03 * vol, msg=fmt)
        z = self.tmp / "parts.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(ply, "a/lid.ply")
            zf.write(igs, "a/base.igs")
            zf.writestr("a/notes.txt", "x")
        rec = self.st.import_reference(self.st.load(p["id"]), z)
        self.assertEqual(sorted(rec["archive"]["imported"]), ["base.igs", "lid.ply"])
        names = {r["file"] for r in self.st.references(self.st.load(p["id"]))}
        self.assertTrue({"scan_part.ply", "b.glb", "b.igs", "ball.xyz", "lid.ply", "base.igs"} <= names, names)
        bad = self.tmp / "m.fbx"
        bad.write_bytes(b"Kaydara FBX Binary")
        with self.assertRaises(StudioError) as cm:
            self.st.import_reference(self.st.load(p["id"]), bad)
        self.assertIn("FBX", str(cm.exception))
        # a design reads a PLY reference as a solid
        d = self.st.create_design("Around a PLY", AROUND_PLY, references=[str(ply)])
        s = self.st.head_summary(self.st.load(d["id"]))
        self.assertGreater(s["bbox"][1][0] - s["bbox"][0][0], 20)


AROUND_PLY = '''"""A plate under a part read from a PLY reference."""
from build123d import Align, Box, Pos

from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = "Plate under a PLY"
    params = [Param("margin", "Margin", 3.0, 1, 10, 0.5, "mm", "form", "plate")]
    features = [Feature("plate", "Plate", "structure")]

    def build(self, v):
        bb = self.reference("scan_part.ply").bounding_box()
        w, d = bb.size.X + 2 * v["margin"], bb.size.Y + 2 * v["margin"]
        return [Stage("plate", Pos(bb.center().X, bb.center().Y, 0) * Box(w, d, 2, align=(Align.CENTER, Align.CENTER, Align.MAX)))]
'''


class OneTable(unittest.TestCase):
    """Every way a file comes in agrees with form/formats.py."""

    def test_every_listed_format_has_a_reader_and_a_route(self):
        from form.recon import mesh
        mesh_like = set(formats.extensions("mesh", "pointcloud"))
        self.assertEqual(set(mesh.FORMATS), mesh_like)
        self.assertEqual(mesh_like - set(formats.NATIVE_MESH), set(meshformats.READERS))
        for e in formats.extensions():
            k = formats.kind_of("x" + e)
            self.assertIn(k, formats.KINDS)
        self.assertEqual(set(triage.MESH), mesh_like)
        self.assertEqual(set(triage.CAD), set(formats.extensions("brep")))
        self.assertEqual(set(triage.VECTOR) | set(triage.ARCHIVE) | set(triage.PHOTO) | set(triage.DOCUMENT),
                         set(formats.extensions("2d", "archive", "photo", "document")))

    def test_imports_attachments_and_links_take_every_part_format(self):
        from form import conversations, sources, studio
        from form.agents import effort
        parts = set(formats.extensions(*formats.PART_KINDS))
        self.assertEqual(set(studio.REF_FORMATS), parts)
        self.assertEqual(conversations.CAD_EXT, parts | set(formats.extensions("2d", "archive")))
        self.assertEqual(conversations.MESH_EXT, set(formats.extensions("mesh", "pointcloud")))
        for e in formats.extensions("photo"):
            if e not in (".tif", ".tiff"):
                self.assertEqual(conversations.kind_of("x" + e), "image", e)
        self.assertEqual(set(sources.MODEL_EXT), parts | set(formats.extensions("2d", "archive")))
        self.assertTrue(set(sources.MODEL_EXT) <= set(sources.FILE_EXT))
        self.assertTrue(parts <= set(effort._MESH))
        for e in parts | set(formats.extensions("2d", "archive")):
            self.assertEqual(sources.classify("https://example.com/a/model" + e), "file", e)

    def test_dialog_filters_come_from_the_table(self):
        every = " ".join(formats.name_filters("attach"))
        for e in formats.extensions():
            self.assertIn("*" + e, every)
        part = formats.name_filters("part")[0]
        for e in formats.extensions(*formats.PART_KINDS, "archive"):
            self.assertIn("*" + e, part)
        qml = ROOT / "form" / "app" / "qml" / "Form"
        for f, which in (("Talk.qml", "attach"), ("StartComposer.qml", "attach"), ("Brief.qml", "part")):
            text = (qml / f).read_text(encoding="utf-8")
            self.assertIn(f'Bridge.fileFilters("{which}")', text, f)
            self.assertNotRegex(text, r"\*\.stl", f)                     # no list of its own beside the table
        bridge = (ROOT / "form" / "app" / "bridge.py").read_text(encoding="utf-8")
        self.assertIn("def fileFilters", bridge)

    def test_tools_cli_and_docs_name_the_formats(self):
        from form import mcp_server
        src = (ROOT / "form" / "mcp_server.py").read_text(encoding="utf-8")
        for tool in ("triage", "import_reference", "reconstruct"):
            m = re.search(rf"async def {tool}\(.*?\"\"\"(.*?)\"\"\"", src, re.S)
            doc = m.group(1)
            for word in ("PLY", "glTF", "E57", "LAS", "VTK"):
                self.assertIn(word, doc, tool)
        self.assertTrue(hasattr(mcp_server, "MESH_EXTS"))
        names = {"STL", "OBJ", "3MF", "PLY", "OFF", "AMF", "GLB", "glTF", "Collada", "X3D", "VRML", "VTK", "VTP",
                 "VTU", "XYZ", "PTS", "LAS", "E57", "STEP", "IGES", "BREP", "DXF", "SVG", "zip"}
        for doc in ("docs/FEATURES.md", "docs/CLI.md", "docs/MCP.md"):
            text = (ROOT / doc).read_text(encoding="utf-8")
            for n in names:
                self.assertIn(n, text, f"{doc} does not name {n}")
        cl = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        notes = cl[cl.index("## 1.1.0"):cl.index("\n## ", cl.index("## 1.1.0") + 5)]
        self.assertIn("Bring files from any program", notes)
        self.assertIn("E57", notes)
        table = formats.cli_table()
        self.assertEqual(len(table["read"]), len(formats.FORMATS) + 1)
        self.assertIn(".fbx", table["not_read"])


if __name__ == "__main__":
    unittest.main()
