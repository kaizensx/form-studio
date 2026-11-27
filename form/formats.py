"""Every file format Form Studio reads, in one place. Each entry names its kind, and every way a file comes in asks
this table: the app's file dialogs and drop targets (through the bridge, form/app/bridge.py), conversation
attachments, import_reference, reconstruct, triage, mesh_preflight, fetch_link, the CLI and the tool descriptions.
tests/test_formats.py fails when any of them disagrees with it.

    kind        what it is                                   how it is read
    mesh        triangles: STL, OBJ, 3MF, PLY, OFF, AMF,     form/recon/mesh.py (STL, OBJ, 3MF) and form/meshformats.py,
                glTF/GLB, Collada, X3D, VRML, VTK            numpy only; units and up axis converted where the format says
    pointcloud  points from a scanner: XYZ, PTS, LAS, E57,   form/meshformats.py, then a surface is reconstructed from the
                and a PLY with vertices only                 points (form/pointcloud.py) before it is triaged like a mesh
    brep        exact CAD: STEP, IGES, OCCT BREP             the kernel (OCCT) in the worker; units converted on import
    2d          a drawing to take a profile from: DXF, SVG   read for its outlines and sizes (form/triage.py)
    archive     a zip of any of the above (Printables,       unpacked safely (unpack()), then each file is triaged
                Thingiverse "download all")
    photo, document, sketch   pictures, PDFs and Form Studio sketches (*.sketch.json)

Not read, and said so when they come in: FBX (no reader with a licence Form Studio can ship), USD/USDZ (needs Pixar's
usd-core, about 100 MB), LAZ (compressed LAS), IFC, SolidWorks/Inventor/Fusion/Creo native parts (export STEP from
them). unsupported() writes that message.
"""
from __future__ import annotations

import hashlib
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class Format:
    ext: str            # ".ply"
    kind: str           # mesh, pointcloud, brep, 2d, archive, photo, document, sketch
    name: str           # what people call it
    units: str          # what the file says about units: "file" (stated, converted), "metres" (the format's rule,
                        # converted), "none" (no units: millimetres assumed, triage's size test applies)
    note: str = ""


_F = [
    # meshes
    Format(".stl", "mesh", "STL", "none", "binary or ASCII"),
    Format(".obj", "mesh", "OBJ", "none", "named objects become parts; materials (MTL) are ignored"),
    Format(".3mf", "mesh", "3MF", "file", "named parts, plates and colours; Bambu, Orca and MakerWorld layouts"),
    Format(".ply", "mesh", "PLY", "none", "ASCII or binary; vertex colours kept as a note; vertices only: a point cloud"),
    Format(".off", "mesh", "OFF", "none"),
    Format(".amf", "mesh", "AMF", "file", "plain or zipped"),
    Format(".glb", "mesh", "glTF binary (GLB)", "metres", "metres and Y up, turned to millimetres and Z up"),
    Format(".gltf", "mesh", "glTF", "metres", "its .bin and textures must sit beside it (or send a zip)"),
    Format(".dae", "mesh", "Collada (DAE)", "file", "its <unit> and up axis are applied"),
    Format(".x3d", "mesh", "X3D", "none", "XML encoding; IndexedFaceSet and triangle sets"),
    Format(".wrl", "mesh", "VRML", "none", "VRML 2.0 / 97; IndexedFaceSet"),
    Format(".vrml", "mesh", "VRML", "none", "VRML 2.0 / 97; IndexedFaceSet"),
    Format(".vtk", "mesh", "VTK legacy", "none", "POLYDATA or UNSTRUCTURED_GRID, ASCII or binary; solid cells give "
           "their outer surface"),
    Format(".vtp", "mesh", "VTK PolyData (VTP)", "none", "XML: ASCII, base64 or appended, zlib compressed or not"),
    Format(".vtu", "mesh", "VTK UnstructuredGrid (VTU)", "none", "XML; solid cells give their outer surface"),
    # point clouds
    Format(".xyz", "pointcloud", "XYZ point cloud", "none", "x y z per line (normals and colours after them ignored)"),
    Format(".pts", "pointcloud", "PTS point cloud", "none", "Leica PTS: a count line, then x y z ..."),
    Format(".las", "pointcloud", "LAS point cloud", "metres", "uncompressed LAS 1.0-1.4 (LAZ is not read)"),
    Format(".e57", "pointcloud", "E57 point cloud", "metres", "ASTM E57: cartesian points of every scan, placed by "
           "its pose"),
    # exact CAD
    Format(".step", "brep", "STEP", "file", "AP203, AP214, AP242"),
    Format(".stp", "brep", "STEP", "file", "AP203, AP214, AP242"),
    Format(".iges", "brep", "IGES", "file"),
    Format(".igs", "brep", "IGES", "file"),
    Format(".brep", "brep", "OpenCASCADE BREP", "none"),
    Format(".brp", "brep", "OpenCASCADE BREP", "none"),
    # drawings
    Format(".dxf", "2d", "DXF drawing", "file", "outlines and sizes for a profile; $INSUNITS applied"),
    Format(".svg", "2d", "SVG drawing", "file", "outlines and sizes for a profile; width/height units applied"),
    # archives
    Format(".zip", "archive", "Zip archive", "none", "unpacked safely; every file in it that Form Studio reads is triaged"),
    # pictures and documents
    *(Format(e, "photo", "Photo", "none") for e in (".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".gif", ".bmp",
                                                   ".tif", ".tiff")),
    Format(".pdf", "document", "PDF", "none", "a drawing or a datasheet, read page by page"),
]

FORMATS: dict[str, Format] = {f.ext: f for f in _F}
SKETCH_SUFFIX = ".sketch.json"
KINDS = ("mesh", "pointcloud", "brep", "2d", "archive", "photo", "document", "sketch")
PART_KINDS = ("mesh", "pointcloud", "brep")          # a 3D part: import_reference, the attach "Part" chip
NATIVE_MESH = (".stl", ".obj", ".3mf")               # read by form/recon/mesh.py itself; the rest by form/meshformats.py

NOT_READ = {
    ".fbx": "FBX has no reader with a licence Form Studio can ship. Export OBJ, glTF (GLB) or STL from the program.",
    ".usd": "USD needs Pixar's usd-core library (about 100 MB), which Form Studio does not carry. Export glTF (GLB), "
            "OBJ or STL.",
    ".usdz": "USDZ needs Pixar's usd-core library (about 100 MB), which Form Studio does not carry. Export glTF (GLB), "
             "OBJ or STL.",
    ".usda": "USD needs Pixar's usd-core library, which Form Studio does not carry. Export glTF (GLB), OBJ or STL.",
    ".usdc": "USD needs Pixar's usd-core library, which Form Studio does not carry. Export glTF (GLB), OBJ or STL.",
    ".laz": "LAZ is compressed LAS, which Form Studio does not decompress. Save it as LAS, E57, PLY or XYZ.",
    ".ifc": "IFC (building models) is not read. Export STEP or OBJ from the program.",
    ".sldprt": "A SolidWorks part is a closed format. Save it as STEP (File > Save As > STEP AP214).",
    ".sldasm": "A SolidWorks assembly is a closed format. Save it as STEP.",
    ".ipt": "An Inventor part is a closed format. Export it as STEP.",
    ".iam": "An Inventor assembly is a closed format. Export it as STEP.",
    ".f3d": "A Fusion archive is a closed format. Export the body as STEP.",
    ".prt": "A Creo or NX part is a closed format. Export it as STEP.",
    ".catpart": "A CATIA part is a closed format. Export it as STEP.",
    ".skp": "SketchUp files are not read. Export Collada (DAE), OBJ or STL from SketchUp.",
    ".blend": "Blender files are not read. Export glTF (GLB), OBJ or STL from Blender.",
    ".rar": "RAR archives are not read. Unpack it, or send a zip.",
    ".7z": "7z archives are not read. Unpack it, or send a zip.",
}


def ext_of(path) -> str:
    s = str(path).lower()
    if s.endswith(SKETCH_SUFFIX):
        return SKETCH_SUFFIX
    return Path(s).suffix


def kind_of(path) -> str | None:
    """The kind of a file name, or None when Form Studio does not read it."""
    e = ext_of(path)
    if e == SKETCH_SUFFIX:
        return "sketch"
    f = FORMATS.get(e)
    return f.kind if f else None


def extensions(*kinds: str) -> tuple[str, ...]:
    """The extensions of the given kinds (all of them when none is given), in the table's order."""
    return tuple(f.ext for f in _F if not kinds or f.kind in kinds)


def names(*kinds: str) -> list[str]:
    """The format names of the given kinds, each once, in the table's order ("STL", "OBJ", "3MF", ...)."""
    out = []
    for f in _F:
        if (not kinds or f.kind in kinds) and f.name not in out:
            out.append(f.name)
    return out


def supported_text(*kinds: str) -> str:
    """One line naming what is read: "STL, OBJ, 3MF, PLY, ..." (photos collapsed into one word)."""
    ks = kinds or ("mesh", "pointcloud", "brep", "2d", "archive", "photo", "document")
    out = []
    for k in ks:
        if k == "photo":
            out.append("photos (PNG, JPG, HEIC, WebP, ...)")
        elif k == "document":
            out.append("PDF drawings")
        elif k == "sketch":
            out.append("Form Studio sketches")
        else:
            out += [n.replace(" point cloud", "").replace(" drawing", "") for n in names(k)]
    return ", ".join(dict.fromkeys(out))


def unsupported(path) -> str:
    """The one message for a file Form Studio does not read: why, and what it does read."""
    e = ext_of(path)
    head = NOT_READ.get(e) or f"{e or 'A file without an extension'} is not a format Form Studio reads."
    return (head + " Form Studio reads 3D parts as " + supported_text("mesh", "pointcloud", "brep")
            + "; drawings as DXF or SVG; zip archives of these; " + supported_text("photo", "document") + ".")


def _globs(exts) -> str:
    return " ".join("*" + e for e in exts)


def name_filters(which: str = "attach") -> list[str]:
    """File dialog filters, built from the table (QML asks for them through Bridge.fileFilters).

    which: "attach" (the conversation and Home: everything), "part" (Brief > Import a reference part: 3D parts and
    zips of them), "photo" (pictures only)."""
    parts = extensions(*PART_KINDS)
    if which == "part":
        return [f"3D parts ({_globs(parts + extensions('archive'))})", f"Meshes ({_globs(extensions('mesh'))})",
                f"Point clouds ({_globs(extensions('pointcloud'))})", f"CAD ({_globs(extensions('brep'))})",
                f"Zip archives ({_globs(extensions('archive'))})"]
    if which == "photo":
        return [f"Photos ({_globs(extensions('photo'))})"]
    every = extensions("photo", "document", *PART_KINDS, "2d", "archive")
    return [f"Everything Form Studio reads ({_globs(every)} *{SKETCH_SUFFIX})",
            f"Parts, meshes and scans ({_globs(parts + extensions('archive'))})",
            f"Drawings ({_globs(extensions('document', '2d'))})",
            f"Photos and pictures ({_globs(extensions('photo'))})"]


def cli_table() -> dict:
    """`form formats`: the table as JSON, with what is not read and why."""
    return {"read": [{"ext": f.ext, "kind": f.kind, "name": f.name, "units": f.units, "note": f.note} for f in _F]
            + [{"ext": SKETCH_SUFFIX, "kind": "sketch", "name": "Form Studio sketch", "units": "file", "note": ""}],
            "not_read": NOT_READ}


# ---- zip archives ----------------------------------------------------------------------------------------------------

MAX_MEMBERS = 500                  # files in one archive
MAX_UNPACKED = 4_000_000_000       # bytes, all members together
MAX_RATIO = 200                    # a member that inflates more than this is refused (a zip bomb)
MAX_DEPTH = 2                      # a zip inside a zip is unpacked once more, no further


class ArchiveError(ValueError):
    pass


def _cache_root() -> Path:
    try:
        from . import config
        data = Path(config.load()["data"]["dir"])
    except Exception:                                  # noqa: BLE001 - outside a configured Form Studio: the default folder
        data = Path(os.environ.get("FORM_DATA") or Path.home() / "FORM").expanduser()
    return data / ".cache" / "archives"


def _safe_member(name: str) -> PurePosixPath | None:
    """The member's path inside the archive, or None when it would land outside the folder (zip slip), is a folder,
    or is macOS metadata."""
    n = name.replace("\\", "/")
    if not n or n.endswith("/") or n.startswith("/") or (len(n) > 1 and n[1] == ":"):
        return None
    p = PurePosixPath(n)
    if any(part in ("..", "") for part in p.parts) or p.parts[0] == "__MACOSX" or p.name.startswith("._"):
        return None
    if p.name in (".DS_Store", "Thumbs.db"):
        return None
    return p


def unpack(path, dest: Path | None = None, depth: int = 0) -> dict:
    """Unpack a zip into a folder of its own and list the files in it that Form Studio reads. The other files are
    unpacked beside them (a glTF needs its .bin, an OBJ its textures) and listed as skipped. The folder is dest, or a
    cache folder named by the zip's checksum, so a second look reuses it. Safe: no member lands outside the folder,
    links are not followed, and the count, total size and compression ratio are bounded. Returns {"folder",
    "files": [{"name", "path", "kind", "bytes"}], "skipped": [{"name", "why"}]}."""
    src = Path(path)
    h = hashlib.sha256()
    with open(src, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 22), b""):
            h.update(b)
    folder = Path(dest) if dest else _cache_root() / h.hexdigest()[:20]
    try:
        z = zipfile.ZipFile(src)
    except zipfile.BadZipFile as e:
        raise ArchiveError(f"{src.name} is not a readable zip: {e}") from e
    files, skipped, total = [], [], 0
    with z:
        infos = z.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ArchiveError(f"{src.name} holds {len(infos)} files; Form Studio unpacks up to {MAX_MEMBERS}.")
        for i in infos:
            rel = _safe_member(i.filename)
            if rel is None:
                if not i.is_dir() and not i.filename.startswith("__MACOSX"):
                    skipped.append({"name": i.filename, "why": "a path outside the archive's folder, or metadata"})
                continue
            if (i.external_attr >> 16) & 0o170000 == 0o120000:
                skipped.append({"name": i.filename, "why": "a symbolic link"})
                continue
            k = kind_of(rel.name)
            if k is None:                     # kept beside the others (a glTF's .bin, an OBJ's textures), not listed
                skipped.append({"name": i.filename, "why": unsupported(rel.name).split(" Form Studio reads")[0]})
            if i.flag_bits & 0x1:
                skipped.append({"name": i.filename, "why": "encrypted"})
                continue
            if i.compress_size and i.file_size / max(i.compress_size, 1) > MAX_RATIO and i.file_size > 50_000_000:
                raise ArchiveError(f"{i.filename} inflates {i.file_size / max(i.compress_size, 1):.0f} times: refused "
                                   "as a zip bomb.")
            total += i.file_size
            if total > MAX_UNPACKED:
                raise ArchiveError(f"{src.name} unpacks to more than {MAX_UNPACKED // 1_000_000_000} GB.")
            target = folder.joinpath(*rel.parts)
            if not target.resolve().is_relative_to(folder.resolve()):
                skipped.append({"name": i.filename, "why": "a path outside the archive's folder"})
                continue
            if not (target.is_file() and target.stat().st_size == i.file_size):
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".part")
                written = 0
                with z.open(i) as r, open(tmp, "wb") as w:
                    for b in iter(lambda: r.read(1 << 20), b""):
                        written += len(b)
                        if written > i.file_size + 1024:        # the header lied about the size
                            raise ArchiveError(f"{i.filename} is larger than its archive says.")
                        w.write(b)
                os.replace(tmp, target)
            if k is None:
                continue
            if k == "archive":
                if depth + 1 >= MAX_DEPTH:
                    skipped.append({"name": i.filename, "why": "a zip inside a zip inside a zip"})
                    continue
                inner = unpack(target, target.with_name(target.stem + "_unzipped"), depth + 1)
                files += [{**f, "name": f"{rel.as_posix()}/{f['name']}"} for f in inner["files"]]
                skipped += [{**s, "name": f"{rel.as_posix()}/{s['name']}"} for s in inner["skipped"]]
                continue
            files.append({"name": rel.as_posix(), "path": str(target), "kind": k, "bytes": int(i.file_size)})
    return {"folder": str(folder), "files": files, "skipped": skipped}
