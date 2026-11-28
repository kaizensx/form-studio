"""The parts list a buyer can order from: purchased items by standard designation, with quantity, material and mass,
the printed or made parts with their mass, and supplier numbers only where the person (or a link they gave) supplied
them.

    from form import bom
    b = bom.build(st, p)                    # {"purchased": [...], "made": [...], "totals": {...}, "suppliers": ...}
    bom.csv_text(b)                         # the CSV
    bom.pdf(st, p, b)                       # a one-page PDF for the drawing set (path)
    bom.add_supplier(st, p, "ISO 4762 M3×10 A2-70", supplier="...", part_number="...", url="...", by="person")

Where each number comes from:
  * designation, material and the dimensions: form.catalog (each table cites its standard or datasheet);
  * mass of a purchased item: the maker's catalogue when it gives one, else the part's modelled volume computed on the
    B-rep times the density of its material from the sourced library (form/material_library.py, wave C), else none;
  * mass of a made part: form.massprops on the design's B-rep with the material set for it (none when no material is
    set; nothing is assumed);
  * supplier numbers: only from the person, or from a page at a link they gave, each stamped with who added it, the
    link and the date. Form Studio never makes one up, and never looks one up on its own.

The optional catalogue service (Settings › General: off by default) is an interface, ``Provider``: before each search
it says exactly what would be sent and to whom, and it searches only when asked again with confirm. No provider is
shipped: suppliers that offer a public API need an account and their terms accepted, so the state is "no provider
configured" until one is added here.
"""
from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path

VERSION = 1
HEADER = ["item", "kind", "designation", "standard", "quantity", "material", "unit_grams", "total_grams",
          "mass_evidence", "mass_source", "supplier", "supplier_part_number", "supplier_url", "supplier_added_by",
          "supplier_date", "placed_as", "source_table"]


def _err(msg: str, hint: str = ""):
    from .studio import StudioError
    return StudioError(msg, hint)


# ── supplier references (the person's data, beside the project) ────────────────────────────────────────────────────
def _sup_path(st, p) -> Path:
    return st.dir(p["id"]) / "suppliers.json"


def suppliers(st, p) -> dict:
    """{designation: [reference, ...]} as the person (or a link they gave) supplied them."""
    f = _sup_path(st, p)
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    except (OSError, ValueError):
        return {}


def _write_sup(st, p, data: dict) -> None:
    from . import fsutil
    f = _sup_path(st, p)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    fsutil.replace(tmp, f)


def add_supplier(st, p, designation: str, supplier: str, part_number: str, url: str = "", note: str = "",
                 by: str = "person", relayed: bool = False) -> dict:
    """Record a supplier's part number for a designation. by="person" (typed by the person) or "agent" (read from the
    page at `url`, a link the person gave; an agent must give the url)."""
    d, s, n, u = (str(x or "").strip() for x in (designation, supplier, part_number, url))
    if not d or not s or not n:
        raise _err("A supplier reference needs the designation, the supplier and their part number.")
    if by not in ("person", "agent"):
        raise _err('by is "person" or "agent".')
    if by == "agent" and not u.startswith(("http://", "https://")):
        raise _err("A part number the agent adds must come from a page the person linked: give its url.",
                   "Ask the person for the supplier's page (or the number), then fetch_link it.")
    if len(n) > 64 or len(s) > 80 or len(u) > 500:
        raise _err("That reference is too long to be a part number.")
    with st.lock(p["id"]):
        data = suppliers(st, p)
        refs = [r for r in data.get(d, []) if not (r["supplier"].lower() == s.lower() and r["part_number"] == n)]
        ref = {"supplier": s, "part_number": n, "url": u, "note": str(note or "")[:200], "added_by": by,
               "source": (("the person, through the agent" if relayed else "the person") if by == "person"
                          else f"the agent, from the page at {u} (a link the person gave)"),
               "date": time.strftime("%Y-%m-%d")}
        data[d] = refs + [ref]
        _write_sup(st, p, data)
    return {"designation": d, "references": data[d]}


def remove_supplier(st, p, designation: str, supplier: str = "", part_number: str = "") -> dict:
    with st.lock(p["id"]):
        data = suppliers(st, p)
        refs = data.get(designation, [])
        left = [r for r in refs if not ((not supplier or r["supplier"].lower() == supplier.lower())
                                        and (not part_number or r["part_number"] == part_number))]
        if len(left) == len(refs):
            raise _err(f"No supplier reference for “{designation}” matches.")
        if left:
            data[designation] = left
        else:
            data.pop(designation, None)
        _write_sup(st, p, data)
    return {"designation": designation, "references": left}


# ── the optional catalogue service ─────────────────────────────────────────────────────────────────────────────────
class Provider:
    """A supplier catalogue service. A provider must use a public API or a documented endpoint under its terms (never
    scraping), and say before each search what is sent and to whom."""
    id = ""
    name = ""
    host = ""
    terms = ""

    def disclosure(self, query: str) -> dict:
        return {"to": f"{self.name} ({self.host})", "sends": {"query": query}, "terms": self.terms,
                "not_sent": "your designs, files, project names and the rest of the parts list"}

    def search(self, query: str, cfg: dict) -> list[dict]:
        raise NotImplementedError


PROVIDERS: dict[str, Provider] = {}           # none shipped (see the module docstring)


def catalogue_status(cfg: dict) -> dict:
    sec = cfg.get("parts") or {}
    on = bool(sec.get("catalogue", False))
    pid = str(sec.get("catalogue_provider", "") or "")
    if not on:
        return {"enabled": False, "state": "off", "provider": pid or None,
                "text": "The catalogue service is off (Settings › General). Supplier numbers come from you or a link you give."}
    if not pid or pid not in PROVIDERS:
        return {"enabled": True, "state": "no provider configured", "provider": pid or None,
                "available": sorted(PROVIDERS),
                "text": "No catalogue provider is configured, so nothing is searched or sent. Give supplier numbers "
                        "yourself, or a link to the supplier's page."}
    pr = PROVIDERS[pid]
    return {"enabled": True, "state": "ready", "provider": pid, "to": f"{pr.name} ({pr.host})"}


def catalogue_search(cfg: dict, query: str, confirm: bool = False) -> dict:
    """Search the configured catalogue. Without confirm it returns only what would be sent and to whom."""
    s = catalogue_status(cfg)
    if s["state"] != "ready":
        return {**s, "results": []}
    pr = PROVIDERS[s["provider"]]
    q = str(query or "").strip()[:200]
    if not q:
        raise _err("Say what to search for (a designation such as ISO 4762 M3×10).")
    disc = pr.disclosure(q)
    if not confirm:
        return {**s, "confirm_needed": True, "would_send": disc, "results": []}
    res = pr.search(q, cfg)
    return {**s, "sent": disc, "results": [{**r, "source": f"{pr.name} catalogue search, {time.strftime('%Y-%m-%d')}"} for r in res]}


# ── the list ───────────────────────────────────────────────────────────────────────────────────────────────────────
def _declared_hardware(st, p) -> list:
    """Hardware rows a design's own assembly() declares (not the placed standard parts), as dicts."""
    from .placement import NOTE
    try:
        rec = st.recipe(p)
        if not st._declares_assembly(rec):
            return []
        a = rec.assembly(st.rev(p)["values"])
        if a is None:
            return []
        return [h for h in a.hardware if not str(h.note).startswith(NOTE)]
    except Exception:                                     # noqa: BLE001 - a design that does not build: no rows
        return []


def build(st, p, made: bool = True) -> dict:
    """The parts list of the head revision. made=False leaves out the made parts (no kernel call for their mass)."""
    from . import catalog, placement
    placed = placement.list_parts(st, p)
    sup = suppliers(st, p)
    groups: dict[str, dict] = {}
    for q in placed:
        it = catalog.resolve(q["spec"])
        f = catalog.family(it["family"])
        dsg = f.designation(it)
        g = groups.get(dsg)
        if g is None:
            info = catalog.part_info(st, it)
            mk, what, _why = f.material(it)
            g = groups[dsg] = {"designation": dsg, "standard": f.standard, "family": f.id, "label": f.label,
                               "quantity": 0, "material": what, "material_key": mk, "unit": info["mass"],
                               "placed_as": [], "source_table": f.source(), "spec": it}
        g["quantity"] += int(q.get("qty", 1))
        g["placed_as"].append(q["id"])
    for h in _declared_hardware(st, p):
        dsg = f"{h.name}" + (f" {h.size}" if h.size and h.size not in h.name else "")
        g = groups.setdefault(dsg, {"designation": dsg, "standard": h.source, "family": "", "label": h.name,
                                    "quantity": 0, "material": h.material, "material_key": None,
                                    "unit": ({"grams": h.grams, "evidence": "computed", "source": "the design's assembly()"}
                                             if h.grams is not None else {"grams": None, "evidence": "unsourced",
                                                                          "source": "the design's assembly() gives none"}),
                                    "placed_as": ["assembly()"], "source_table": "declared in the design's source"})
        g["quantity"] += int(h.qty)
    purchased = []
    for g in groups.values():
        u = g["unit"].get("grams")
        g["unit_grams"] = u
        g["total_grams"] = round(u * g["quantity"], 3) if u is not None else None
        g["suppliers"] = sup.get(g["designation"], [])
        purchased.append(g)
    purchased.sort(key=lambda g: (g["family"] or "~", g["designation"]))
    made_rows, made_note = [], ""
    if made:
        try:
            from . import massprops
            mp = massprops.compute(st, p)
            for x in mp.get("parts", []):
                m = x.get("mass_g")
                mat = (x.get("material") or {})
                made_rows.append({"label": x.get("label") or p["name"], "id": x.get("id") or "", "quantity": 1,
                                  "material": mat.get("label", ""), "unit_grams": round(m, 3) if m is not None else None,
                                  "mass_evidence": mp.get("evidence", "computed") if m is not None else "no material set",
                                  "mass_source": (f"B-rep volume × {mat.get('density_kg_m3'):g} kg/m³, {mat.get('density_source')}"
                                                  if m is not None else "Set a material (set_appearance) to get its mass."),
                                  "volume_mm3": x.get("volume_mm3")})
        except Exception as e:                            # noqa: BLE001 - the list still lists what is bought
            made_note = f"Made parts not measured: {getattr(e, 'msg', e)}"
    tp = [g["total_grams"] for g in purchased]
    tm = [r["unit_grams"] for r in made_rows]
    totals = {"purchased_items": sum(g["quantity"] for g in purchased), "purchased_lines": len(purchased),
              "purchased_grams": round(sum(x for x in tp if x is not None), 3),
              "purchased_without_mass": sum(1 for x in tp if x is None),
              "made_grams": round(sum(x for x in tm if x is not None), 3),
              "made_without_mass": sum(1 for x in tm if x is None)}
    return {"version": VERSION, "project": p["id"], "name": p["name"], "rev": st.rev(p)["n"], "purchased": purchased,
            "made": made_rows, "totals": totals, "catalogue": catalogue_status(st.cfg),
            **({"note": made_note} if made_note else {}),
            "supplier_rule": "Supplier numbers only from you, or a page at a link you gave; none is generated."}


def csv_text(b: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(HEADER)
    n = 0
    for g in b["purchased"]:
        refs = g["suppliers"] or [{}]
        for k, r in enumerate(refs):
            n += 1
            w.writerow([n, "purchased", g["designation"], g["standard"], g["quantity"] if k == 0 else "",
                        g["material"], _g(g["unit_grams"]), _g(g["total_grams"]) if k == 0 else "",
                        g["unit"].get("evidence", ""), g["unit"].get("source", ""), r.get("supplier", ""),
                        r.get("part_number", ""), r.get("url", ""), r.get("source", ""), r.get("date", ""),
                        " ".join(g["placed_as"]), g["source_table"]])
    for r in b["made"]:
        n += 1
        w.writerow([n, "made", r["label"], "", r["quantity"], r["material"], _g(r["unit_grams"]), _g(r["unit_grams"]),
                    r["mass_evidence"], r["mass_source"], "", "", "", "", "", r["id"], ""])
    return out.getvalue()


def _g(x) -> str:
    return "" if x is None else f"{x:.3f}".rstrip("0").rstrip(".")


def write_csv(st, p, b: dict | None = None) -> Path:
    b = b or build(st, p)
    f = _out_dir(st, p) / f"{p['id']}_r{b['rev']:02d}_parts.csv"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(csv_text(b), encoding="utf-8")
    return f


def _out_dir(st, p) -> Path:
    return st.dir(p["id"]) / "artifacts" / "parts"


def pdf(st, p, b: dict | None = None) -> Path:
    """One A4 page (two or more when the list is long): the parts list for the drawing set."""
    from PIL import Image, ImageDraw
    from . import render
    from .instructions import PAGE, _font, _wrap, text
    b = b or build(st, p)
    rows = [("Designation", "Qty", "Material", "g each", "Supplier · part no.")]
    for g in b["purchased"]:
        sup = "; ".join(f"{r['supplier']} {r['part_number']}" for r in g["suppliers"]) or "—"
        rows.append((g["designation"], str(g["quantity"]), g["material"] or "—",
                     _g(g["unit_grams"]) or "no source", sup))
    for r in b["made"]:
        rows.append((r["label"] + " (made)", str(r["quantity"]), r["material"] or "not set", _g(r["unit_grams"]) or "—", "—"))
    cols = (90, 640, 720, 900, 1020)
    per = 30
    body = rows[1:] or [("Nothing to list yet", "", "", "", "")]
    chunks = [body[i:i + per] for i in range(0, len(body), per)][:20]
    foot = f"{b['name']} · r{b['rev']:02d} · parts list · Form Studio"
    t = b["totals"]
    sub = (f"{t['purchased_items']} purchased items in {t['purchased_lines']} lines · {t['purchased_grams']:g} g purchased"
           + (f" ({t['purchased_without_mass']} without a mass source)" if t["purchased_without_mass"] else ""))
    notes = ["Mass: the maker's catalogue where it gives one, else the modelled volume (B-rep) times the sourced "
             "density; 'no source' where neither exists.",
             "Supplier numbers only from the person or a page at a link they gave. Threads are cosmetic in the models."]
    pages = []
    for k, chunk in enumerate(chunks):
        pg = Image.new("RGB", PAGE, render.PAPER)
        d = ImageDraw.Draw(pg)
        d.text((90, 90), "Parts list" + (f" ({k + 1}/{len(chunks)})" if len(chunks) > 1 else ""), fill=render.INK, font=_font(54))
        d.text((90, 162), sub, fill=render.MUTED, font=_font(24))
        f, y = _font(22), 240
        for j, row in enumerate([rows[0]] + chunk):
            for c, (x, cell) in enumerate(zip(cols, row)):
                width = (cols[c + 1] - x - 16) if c + 1 < len(cols) else PAGE[0] - 90 - x
                s = str(cell)
                while len(s) > 1 and d.textlength(s, font=f) > width:
                    s = s[:-2] + "…"
                text(d, (x, y), s, f, render.MUTED if j == 0 else render.INK)
            y += 40
            d.line((90, y - 8, PAGE[0] - 90, y - 8), fill=(214, 209, 199), width=1)
        yy, nf = PAGE[1] - 230, _font(18)
        for n in notes:
            for w in _wrap(d, n, nf, PAGE[0] - 180):
                text(d, (90, yy), w, nf, render.MUTED)
                yy += 28
        d.text((90, PAGE[1] - 80), foot, fill=render.MUTED, font=_font(20))
        pages.append(pg)
    out = _out_dir(st, p)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{p['id']}_r{b['rev']:02d}_parts.pdf"
    pages[0].save(path, "PDF", resolution=150.0, save_all=True, append_images=pages[1:],
                  title=f"{p['name']} parts list", producer="Form Studio")
    return path


# ── the Bench (form/studies.py) ──────────────────────────────────────────────────────────────────────────────────
def _sup_hash(st, p) -> str:
    import hashlib
    f = _sup_path(st, p)
    return hashlib.sha256(f.read_bytes()).hexdigest()[:16] if f.is_file() else "-"


def _list_key(ctx) -> str:
    from .studio import H
    return H("parts-list", VERSION, ctx.keys["geometry"], _sup_hash(ctx.st, ctx.p), ctx.p.get("material"),
             json.dumps(ctx.p.get("parts") or {}, sort_keys=True, default=str))


def _list_run(ctx) -> dict:
    b = build(ctx.st, ctx.p)
    f, g = write_csv(ctx.st, ctx.p, b), pdf(ctx.st, ctx.p, b)
    t = b["totals"]
    head = (f"{t['purchased_items']} to buy in {t['purchased_lines']} lines · {len(b['made'])} made"
            if t["purchased_lines"] else f"Nothing to buy yet · {len(b['made'])} made")
    return {"headline": head, "evidence": "computed", "files": [str(f), str(g)],
            "data": {"totals": t, "purchased": [{k: x[k] for k in ("designation", "quantity", "unit_grams")}
                                                for x in b["purchased"]]}}


def _parts_run(ctx) -> dict:
    from . import placement
    r = placement.fit(ctx.st, ctx.p)
    return {"headline": r["headline"], "evidence": "computed", "data": r}


def _parts_key(ctx) -> str:
    from .studio import H
    from . import catalog
    return H("parts-fit", VERSION, catalog.VERSION, ctx.keys["geometry"])


def register_studies(register) -> None:
    """The Bench's "Standard parts" study and "Parts list" document (the list replaces the plain BOM.csv entry)."""
    from .studies import Study
    register(Study("parts.standard", "study", "Standard parts",
                   "Purchased parts placed on the design, each with its mating cut, checked for fit on the B-rep.",
                   "computed", run=_parts_run, key=_parts_key, inputs=("geometry (the placements are in the source)",),
                   app="parts", tool="standard_part", order=74))
    register(Study("doc.bom", "document", "Parts list",
                   "What to buy by standard designation, with quantity, material, mass and supplier numbers; CSV and a "
                   "PDF page.", "computed", run=_list_run, key=_list_key,
                   inputs=("geometry", "materials", "supplier references"), app="partsList", tool="bom", order=10))
