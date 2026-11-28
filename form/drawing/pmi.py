"""STEP AP242 with semantic PMI, through OCCT's XCAF document (XCAFDoc_DimTolTool), and the file read back.

Annotations (the same list the drawing draws) are attached to the solid's faces by index (shape.faces() order):

    {"kind": "dimension", "id": "d3", "type": "diameter" | "radius" | "linear" | "thickness", "value": 26.15,
     "upper": 0.021, "lower": 0.0, "fit": "H7", "faces": [6], "faces2": [] }
    {"kind": "gdt", "id": "g1", "type": "flatness" | "position" | ..., "value": 0.05, "diameter": False,
     "modifier": "M" | "L" | None, "datums": ["A"], "faces": [3]}
    {"kind": "datum", "letter": "A", "faces": [0]}

read(path) lists what the file holds in the same shape, each referenced face described by its surface type, area and
centre, so compare(written, read) can say annotation by annotation whether it survived and is on the same face.
Worker process only (OCCT).
"""
from __future__ import annotations

import math

DIM_TYPES = {"diameter": "Size_Diameter", "radius": "Size_Radius", "thickness": "Size_Thickness",
             "linear": "Location_LinearDistance", "angle": "Size_Angular"}


def _face_sig(face) -> dict:
    from build123d import Face
    f = face if hasattr(face, "geom_type") else Face(face)
    c = f.center()
    return {"type": f.geom_type.name, "area": round(f.area, 3), "center": [round(c.X, 3), round(c.Y, 3), round(c.Z, 3)]}


def _seq(labels):
    from OCP.OCP.collections import Sequence_TDF_Label
    s = Sequence_TDF_Label()
    for lab in labels:
        s.Append(lab)
    return s


def write(shape, path: str, annotations: list) -> list:
    """Write `shape` with `annotations` as STEP AP242. Returns the annotations with each face's signature."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.STEPControl import STEPControl_AsIs
    from OCP.TCollection import TCollection_ExtendedString, TCollection_HAsciiString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDimTolObjects import (XCAFDimTolObjects_DatumObject, XCAFDimTolObjects_DimensionObject,
                                       XCAFDimTolObjects_DimensionType, XCAFDimTolObjects_GeomToleranceMatReqModif,
                                       XCAFDimTolObjects_GeomToleranceObject, XCAFDimTolObjects_GeomToleranceType,
                                       XCAFDimTolObjects_GeomToleranceTypeValue)
    from OCP.XCAFDoc import XCAFDoc_Datum, XCAFDoc_Dimension, XCAFDoc_DocumentTool, XCAFDoc_GeomTolerance
    from . import gdt as G
    faces = list(shape.faces())
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(doc)
    st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    dt = XCAFDoc_DocumentTool.DimTolTool_s(doc.Main())
    root = st.AddShape(getattr(shape, "wrapped", shape), False)
    from OCP.TCollection import TCollection_ExtendedString as ES
    from OCP.TDataStd import TDataStd_Name
    TDataStd_Name.Set_s(root, ES("part"))
    sub: dict[int, object] = {}

    def lab(i):
        if i not in sub:
            if not 0 <= i < len(faces):
                raise ValueError(f"face {i} is not a face of this solid (it has {len(faces)})")
            sub[i] = st.AddSubShape(root, faces[i].wrapped)
        return sub[i]

    out, datums = [], {}
    order = []
    for a in annotations:
        for d in a.get("datums") or ():
            letter = str(d).rstrip("MLP")
            if letter not in order:
                order.append(letter)
    for a in annotations:
        if a["kind"] != "datum":
            continue
        dl = dt.AddDatum()
        o = XCAFDimTolObjects_DatumObject()
        o.SetName(TCollection_HAsciiString(a["letter"]))
        o.SetPosition(order.index(a["letter"]) + 1 if a["letter"] in order else 1)
        XCAFDoc_Datum.Set_s(dl).SetObject(o)
        dt.SetDatum(_seq([lab(i) for i in a["faces"]]), dl)
        datums[a["letter"]] = dl
        out.append({**a, "face_sig": [_face_sig(faces[i]) for i in a["faces"]]})
    for a in annotations:
        if a["kind"] == "dimension":
            dl = dt.AddDimension()
            o = XCAFDimTolObjects_DimensionObject()
            o.SetType(getattr(XCAFDimTolObjects_DimensionType, "XCAFDimTolObjects_DimensionType_" + DIM_TYPES[a["type"]]))
            o.SetValue(float(a["value"]))
            if a.get("upper") is not None:
                # limits as a range (min, max): OCCT's plus/minus writer keeps only the lower deviation's size, so
                # a range is the form that carries g6 (-7/-20 µm) or k6 (+15/+2 µm) without losing a sign
                v = float(a["value"])
                o.SetLowerBound(v + float(a.get("lower") or 0.0))
                o.SetUpperBound(v + float(a["upper"]))
            if a.get("fit"):
                o.AddDescription(TCollection_HAsciiString(str(a["fit"])), TCollection_HAsciiString("fit"))
            XCAFDoc_Dimension.Set_s(dl).SetObject(o)
            first = [lab(i) for i in a["faces"]]
            second = [lab(i) for i in a.get("faces2") or ()]
            if second or len(first) > 1:
                dt.SetDimension(_seq(first), _seq(second), dl)
            else:
                dt.SetDimension(first[0], dl)
            out.append({**a, "face_sig": [_face_sig(faces[i]) for i in a["faces"] + list(a.get("faces2") or ())]})
        elif a["kind"] == "gdt":
            problems = G.validate(a)
            if problems:
                raise ValueError("; ".join(problems))
            gl = dt.AddGeomTolerance()
            o = XCAFDimTolObjects_GeomToleranceObject()
            o.SetType(getattr(XCAFDimTolObjects_GeomToleranceType,
                              "XCAFDimTolObjects_GeomToleranceType_" + G.CHARACTERISTICS[a["type"]][2]))
            o.SetValue(float(a["value"]))
            if a.get("diameter"):
                o.SetTypeOfValue(XCAFDimTolObjects_GeomToleranceTypeValue.XCAFDimTolObjects_GeomToleranceTypeValue_Diameter)
            if a.get("modifier") in ("M", "L"):
                o.SetMaterialRequirementModifier(getattr(XCAFDimTolObjects_GeomToleranceMatReqModif,
                                                         "XCAFDimTolObjects_GeomToleranceMatReqModif_" + a["modifier"]))
            XCAFDoc_GeomTolerance.Set_s(gl).SetObject(o)
            if len(a["faces"]) > 1:
                dt.SetGeomTolerance(_seq([lab(i) for i in a["faces"]]), gl)
            else:
                dt.SetGeomTolerance(lab(a["faces"][0]), gl)
            for d in a.get("datums") or ():
                letter = str(d).rstrip("MLP")
                if letter not in datums:
                    raise ValueError(f"{a['type']} refers to datum {letter}, which is not declared on a face")
                dt.SetDatumToGeomTol(datums[letter], gl)
            out.append({**a, "face_sig": [_face_sig(faces[i]) for i in a["faces"]]})
    w = STEPCAFControl_Writer()
    Interface_Static.SetCVal_s("write.step.schema", "AP242DIS")    # set after the writer exists: it resets statics
    w.SetDimTolMode(True)
    w.SetNameMode(True)
    if not w.Transfer(doc, STEPControl_AsIs) or w.Write(str(path)) != IFSelect_RetDone:
        raise RuntimeError("OCCT could not write the AP242 file")
    return out


def read(path: str) -> dict:
    """What an AP242 file holds: its schema, and every dimension, geometric tolerance and datum with its faces."""
    from OCP.OCP.collections import Sequence_TDF_Label as Seq
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_Datum, XCAFDoc_Dimension, XCAFDoc_DocumentTool, XCAFDoc_GeomTolerance, XCAFDoc_ShapeTool
    from . import gdt as G
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.InitDocument(doc)
    r = STEPCAFControl_Reader()
    r.SetGDTMode(True)
    r.SetNameMode(True)
    if str(r.ReadFile(str(path))).split(".")[-1] != "IFSelect_RetDone" or not r.Transfer(doc):
        raise RuntimeError(f"OCCT could not read {path}")
    dt = XCAFDoc_DocumentTool.DimTolTool_s(doc.Main())
    schema = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
        i = head.find("FILE_SCHEMA")
        schema = head[i:head.find(";", i)].split("'")[1] if i >= 0 else ""
    except (OSError, IndexError):
        pass

    def shapes(L):
        f1, f2 = Seq(), Seq()
        dt.GetRefShapeLabel_s(L, f1, f2)
        sig = []
        for s in (f1, f2):
            for i in range(1, s.Length() + 1):
                sh = XCAFDoc_ShapeTool.GetShape_s(s.Value(i))
                sig.append(_face_sig(sh))
        return sig

    rev_dim = {"XCAFDimTolObjects_DimensionType_" + v: k for k, v in DIM_TYPES.items()}
    rev_gt = {"XCAFDimTolObjects_GeomToleranceType_" + v[2]: k for k, v in G.CHARACTERISTICS.items()}
    out = {"schema": schema, "dimensions": [], "gdt": [], "datums": []}
    s = Seq()
    dt.GetDimensionLabels(s)
    for i in range(1, s.Length() + 1):
        L = s.Value(i)
        o = XCAFDoc_Dimension.Set_s(L).GetObject()
        row = {"type": rev_dim.get(o.GetType().name, o.GetType().name), "value": round(o.GetValue(), 6),
               "face_sig": shapes(L)}
        if o.IsDimWithRange():
            row.update(upper=round(o.GetUpperBound() - o.GetValue(), 6), lower=round(o.GetLowerBound() - o.GetValue(), 6))
        elif o.IsDimWithPlusMinusTolerance():
            row.update(upper=round(o.GetUpperTolValue(), 6), lower=round(-abs(o.GetLowerTolValue()), 6))
        for j in range(1, o.NbDescriptions() + 1):
            try:
                if o.GetDescriptionName(j).ToCString() == "fit":
                    row["fit"] = o.GetDescription(j).ToCString()
            except Exception:  # noqa: BLE001  (a description without text)
                pass
        if row.get("upper") is not None:              # limits as sizes: OCCT keeps a range's mid value as nominal
            row["min"] = round(row["value"] + row["lower"], 6)
            row["max"] = round(row["value"] + row["upper"], 6)
        out["dimensions"].append(row)
    s = Seq()
    dt.GetGeomToleranceLabels(s)
    for i in range(1, s.Length() + 1):
        L = s.Value(i)
        o = XCAFDoc_GeomTolerance.Set_s(L).GetObject()
        ds = Seq()
        dt.GetDatumOfTolerLabels_s(L, ds)
        names = []
        for j in range(1, ds.Length() + 1):
            names.append(XCAFDoc_Datum.Set_s(ds.Value(j)).GetObject().GetName().ToCString())
        tv = o.GetTypeOfValue().name.endswith("_Diameter")
        mr = o.GetMaterialRequirementModifier().name.rsplit("_", 1)[-1]
        out["gdt"].append({"type": rev_gt.get(o.GetType().name, o.GetType().name), "value": round(o.GetValue(), 6),
                           "diameter": tv, "modifier": mr if mr in ("M", "L") else None, "datums": names,
                           "face_sig": shapes(L)})
    s = Seq()
    dt.GetDatumLabels(s)
    for i in range(1, s.Length() + 1):
        L = s.Value(i)
        o = XCAFDoc_Datum.Set_s(L).GetObject()
        out["datums"].append({"letter": o.GetName().ToCString(), "face_sig": shapes(L)})
    return out


def _same_face(a: dict, b: dict, tol: float = 1e-2) -> bool:
    return a["type"] == b["type"] and abs(a["area"] - b["area"]) <= tol * max(1.0, a["area"]) and \
        math.dist(a["center"], b["center"]) <= tol * 10


def compare(written: list, back: dict) -> list:
    """One row per annotation written: found in the file with the same value, tolerance, datums and faces, or not."""
    rows = []
    pools = {"dimension": list(back["dimensions"]), "gdt": list(back["gdt"]), "datum": list(back["datums"])}
    for a in written:
        pool = pools[a["kind"]]
        hit, why = None, "not in the file"
        for c in pool:
            if a["kind"] == "datum":
                ok = c["letter"] == a["letter"]
            elif a["kind"] == "dimension":
                ok = c["type"] == a["type"]
                if ok and a.get("upper") is not None:      # compare the limit sizes
                    v = float(a["value"])
                    ok = abs(c.get("min", 1e9) - (v + float(a.get("lower") or 0))) < 1e-6 and \
                        abs(c.get("max", 1e9) - (v + float(a["upper"]))) < 1e-6
                elif ok:
                    ok = abs(c["value"] - float(a["value"])) < 1e-6
                if ok and a.get("fit") and c.get("fit") and c["fit"] != a["fit"]:
                    ok = False
            else:
                ok = c["type"] == a["type"] and abs(c["value"] - float(a["value"])) < 1e-6 and \
                    sorted(c["datums"]) == sorted(str(d).rstrip("MLP") for d in a.get("datums") or ()) and \
                    bool(c["diameter"]) == bool(a.get("diameter")) and (c["modifier"] or None) == (a.get("modifier") or None)
            if not ok:
                continue
            faces_ok = len(c["face_sig"]) == len(a["face_sig"]) and all(
                any(_same_face(x, y) for y in c["face_sig"]) for x in a["face_sig"])
            if faces_ok:
                hit = c
                break
            why = "in the file, on other faces"
        if hit is not None:
            pool.remove(hit)
        rows.append({"kind": a["kind"], "id": a.get("id") or a.get("letter"), "what": _what(a),
                     "status": "PASS" if hit is not None else "FAIL", "why": "" if hit is not None else why,
                     "read": hit})
    return rows


def _what(a: dict) -> str:
    if a["kind"] == "datum":
        return f"datum {a['letter']}"
    if a["kind"] == "dimension":
        t = f"{a['type']} {float(a['value']):g}"
        if a.get("fit"):
            t += f" {a['fit']}"
        if a.get("upper") is not None:
            t += f" (+{float(a['upper']):g}/{float(a.get('lower') or 0):+g})"
        return t
    from .gdt import text
    return text(a)
