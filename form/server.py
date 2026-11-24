"""Loopback HTTP server: JSON API plus the static studio UI."""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import advisor, config
from .cad_bridges import open_output
from .studio import NODES, Studio, StudioError

WEB = Path(__file__).resolve().parent / "web"


_HEADER_CTL = re.compile(r"[\x00-\x1f\x7f]")


def start_purposes() -> tuple:
    """The purposes a new conversation or design may ask for (form/start.py: print, model, game)."""
    from .start import PURPOSES
    return PURPOSES


def _attachment(name: str) -> str:
    """A Content-Disposition value for a download: an ASCII fallback name plus the exact name, percent-encoded."""
    name = _HEADER_CTL.sub("", str(name))
    plain = re.sub(r'[^A-Za-z0-9._ -]', "_", name) or "download"
    return f'attachment; filename="{plain}"; filename*=UTF-8\'\'{quote(name, safe="")}'


def _log_error(root, method: str, path: str, exc: BaseException) -> None:
    """An unexpected error, with its traceback, appended to <data>/.logs/engine-errors.log (kept under ~1 MB). The
    packaged app has no console, so this is where a report's details come from. Never raises."""
    try:
        import datetime
        d = Path(root) / ".logs"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "engine-errors.log"
        if f.exists() and f.stat().st_size > 1_000_000:
            f.replace(d / "engine-errors.old.log")
        q = path.split("?", 1)[0]                     # the query can carry text the person typed; it is not needed
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        with f.open("a", encoding="utf-8") as out:
            out.write(f"--- {datetime.datetime.now().isoformat(timespec='seconds')} {method} {q}\n{tb}\n")
    except Exception:
        pass


def make_handler(st: Studio):
    from . import chat as chat_mod
    from .setup import mcp_command
    if not hasattr(st, "chat"):
        st.chat = chat_mod.Chat(st.cfg, st.root, mcp_command())
        from .conversations import migrate_once           # once per data folder: designs for older conversations
        threading.Thread(target=lambda: _quiet(lambda: migrate_once(st.root)), daemon=True,
                         name="form-migrate-conversations").start()
    if getattr(st.chat, "studio", None) is None:      # names the printer in the agent's "Purpose:" line
        try:
            st.chat.studio = st
        except AttributeError:                      # a stand-in chat (tests) that takes no attributes
            pass
    from . import setup_app, updates           # first-run setup and update notices (desktop app)
    if not hasattr(st, "setup_app"):
        st.setup_app = setup_app.Setup(st.cfg, st)

    class Handler(BaseHTTPRequestHandler):
        server_version = "FORM"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        # -- plumbing ------------------------------------------------------
        def _send(self, code, body: bytes, ctype="application/json", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, _HEADER_CTL.sub("", str(v)))     # no CR/LF: a value can never start a new header
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, allow_nan=False, default=str).encode())

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 300_000_000:
                raise StudioError("Upload too large.")
            raw = self.rfile.read(n) if n else b""
            if self.headers.get("Content-Type", "").startswith("application/json"):
                try:
                    return json.loads(raw or b"{}")
                except ValueError:
                    raise StudioError("Malformed request.")
            return raw

        def _guard(self, fn):
            try:
                host = (self.headers.get("Host") or "").split(":")[0]
                if host not in ("127.0.0.1", "localhost", "[::1]"):
                    return self._json({"error": {"message": "Form Studio only answers on loopback."}}, 403)
                origin = self.headers.get("Origin")
                if origin and origin != "null" and urlparse(origin).hostname not in ("127.0.0.1", "localhost", "::1"):
                    # a web page in a browser can reach loopback too; only Form Studio's own pages may call the engine
                    return self._json({"error": {"message": "Form Studio does not answer other websites."}}, 403)
                fn()
            except StudioError as e:
                self._json({"error": e.public()}, e.status)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                traceback.print_exc()
                _log_error(st.root, self.command, self.path, e)
                self._json({"error": {"message": f"Unexpected {type(e).__name__}: {e}",
                                      "hint": "Your project state is unchanged. If this repeats, export the project and report it."}}, 500)

        def do_GET(self):
            self._guard(self._get)

        def do_POST(self):
            self._guard(self._post)

        # -- GET -----------------------------------------------------------
        def _get(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            path = u.path
            if not path.startswith("/api/"):
                return self._static(path)
            if path == "/api/activity":
                return self._json({"events": st.activity_since(float(q.get("since") or 0)), "now": time.time()})
            md = re.fullmatch(r"/api/drafts/(draft-[0-9a-f]{1,32})", path)
            if md:                                      # the last stage a build made (Studio._draft_sink)
                d = st.draft(md.group(1))
                return self._json(d) if d else self._json({"error": "No such draft."}, 404)
            if path == "/api/chat":
                if q.get("refresh"):                        # agents workstream: look for providers and local servers again
                    from .agents import providers as _prov
                    _prov.forget()
                return self._json(st.chat.status())
            if path.startswith("/api/conversations"):       # saved conversations (chat workstream)
                return self._conv_get(path, q)
            mc = re.fullmatch(r"/api/chat/([0-9a-f]{10})", path)
            if mc:
                job = st.chat.jobs.get(mc.group(1))
                if not job:
                    raise StudioError("Unknown chat job.", status=404)
                return self._json(job.public(int(q.get("from") or 0)))
            # -- setup and updates (app setup workstream) --
            if path == "/api/setup":
                return self._json(st.setup_app.report())
            if path == "/api/setup/state":                  # instant: no checks run
                return self._json({"first_run": setup_app.first_run(st.cfg), "fresh": st.setup_app.fresh,
                                   "onboarding": setup_app.onboarding(st.cfg)})
            ms = re.fullmatch(r"/api/setup/job/([0-9a-f]{10})", path)
            if ms:
                return self._json(st.setup_app.job(ms.group(1)).public())
            if path == "/api/updates":
                return self._json(updates.check(st.cfg, force=q.get("force") == "1"))
            # -- installer, sign-in, settings, examples (setup workstream; routes live in form/setup_app.py) --
            owned = setup_app.route_get(st, path, q)
            if owned is not None:
                return self._json(owned)
            # -- Home and new design: starters, recipe library, archives, What's New (home workstream; form/home_api.py) --
            from . import home_api
            got = home_api.route_get(st, path, q)
            if isinstance(got, tuple):
                return self._send(200, got[0], got[1], {"Content-Disposition": _attachment(got[2])})
            if got is not None:
                return self._json(got)
            # -- brief templates (presets) --
            if path == "/api/presets":
                from . import presets
                return self._json({"presets": presets.all_presets()})
            if path == "/api/boot":                      # the opening screen's status line; answers at once
                return self._json(st.boot_state())
            if path == "/api/studio":
                return self._json({"env": st.environment(), "projects": st.list(), "chat": chat_mod.status(st.cfg),
                                   "recipes": [r.public() for r in st.recipes.builtins().values()],
                                   # every built-in's title, legacy ones too: older designs still name them
                                   "recipe_titles": {k: r.title for k, r in st.recipes.all_builtins().items()},
                                   "assistant": advisor.cli_status(st.cfg)})
            # -- slicer picker: every slicer FORM knows, installed or not --
            if path == "/api/studio/slicers":
                from . import slicer as slicer_mod
                return self._json({"chosen": st.cfg["slicer"].get("kind", "auto"), "config": str(slicer_mod.config_target(st.cfg)).replace(str(Path.home()), "~"),
                                   "slicers": slicer_mod.detect_all(st.cfg)})
            # -- printers: every printer in every installed slicer, per-design choice (form/printers.py) --
            if path.startswith("/api/printers"):
                from . import printers as printers_mod
                owned = printers_mod.route_get(st, path, q)
                if owned is not None:
                    return self._json(owned)
            if path == "/api/materials":                   # colours and materials (form/materials.py)
                from . import materials
                return self._json(materials.catalogue())
            if path == "/api/photos":                      # Blender renders: newest current one per project
                from . import photo
                return self._json({"latest": photo.latest_all(st)})
            m = re.fullmatch(r"/api/projects/([a-z0-9-]+)(/.*)?", path)
            if not m:
                raise StudioError("Not found.", status=404)
            pid, rest = m.group(1), m.group(2) or ""
            if rest == "":
                return self._json(st.state(pid))
            p = st.load(pid)
            if rest == "/stamp":
                last = p["revisions"][-1]
                return self._json({"head": p["head"], "updated": p.get("updated"),
                                   "last": {"n": last["n"], "origin": last.get("origin"), "note": last["note"]}})
            # -- selections, annotations, colours and materials (form/selection.py, form/materials.py) --
            if rest == "/annotations":
                return self._json({"annotations": p.get("annotations") or []})
            if rest == "/colour.3mf":
                from . import materials
                return self._send(200, materials.threemf(st, p), "model/3mf")
            # -- analysis on the model (form/analysis.py): maps, orientations --
            if rest == "/analysis":
                from . import analysis
                return self._json(analysis.run_map(st, p, q.get("map") or "thickness", int(q["rev"]) if q.get("rev") else None))
            if rest == "/analysis.png":
                from . import analysis
                r = analysis.run_map(st, p, q.get("map") or "thickness", int(q["rev"]) if q.get("rev") else None)
                return self._send(200, analysis.render_map_png(r, f"{p['name']} - r{r['rev']:02d}", q.get("view") or "iso",
                                                               edges=st.view(p, r["rev"]).get("edges")), "image/png")
            if rest == "/orient":
                from . import analysis
                return self._json(analysis.orientations(st, p))
            if rest == "/view":
                n = int(q["rev"]) if q.get("rev") else None
                return self._json(st.view(p, n))
            plate = int(q["plate"]) if str(q.get("plate") or "").isdigit() else None      # several plates (form/plates.py)
            if rest == "/plates":
                from . import plates
                return self._json(plates.for_project(st, p))
            if rest == "/layers":
                layers = st.layers(p, plate)
                if "n" in q:
                    i = max(0, min(len(layers) - 1, int(q["n"])))
                    return self._json({"index": i, "count": len(layers), **layers[i]})
                return self._json({"count": len(layers), "z": [l["z"] for l in layers],
                                   "types": sorted({pp["t"] for l in layers for pp in l["paths"]})})
            # -- print simulation, cost, plate packing (form/toolpath.py, simulate.py, cost.py, packing.py) --
            if rest == "/toolpath":
                from . import toolpath
                return self._json(toolpath.for_project(st, p, plate).public())
            if rest == "/simulation.png":
                from . import simulate, toolpath
                tp = toolpath.for_project(st, p, plate)
                pr = float(q["progress"]) if q.get("progress") else float(int(q.get("layer") or tp.layers))
                return self._send(200, simulate.png_at(tp, pr, title=f"{p['name']}  r{p['head']:02d}"), "image/png")
            if rest == "/cost":
                from . import cost
                return self._json(cost.project(st, p, int(q.get("copies") or 1)))
            if rest == "/pack":
                from . import packing
                return self._json(packing.project(st, p, int(q.get("copies") or 1),
                                                  float(q["spacing"]) if q.get("spacing") else None))
            if rest == "/diff":
                a, b = int(q["a"]), int(q["b"])
                cand = st.head_summary(p, b)
                return self._json({"a": a, "b": b, "impact": st.impact(p, st.rev(p, b)["values"], cand, base_rev=a),
                                   "note_a": st.rev(p, a)["note"], "note_b": st.rev(p, b)["note"]})
            # -- maker tools: geometric diff, text on faces, assembly instructions (form/geomdiff.py, engrave.py, instructions.py) --
            if rest == "/geomdiff":
                from . import geomdiff
                return self._json(geomdiff.compute(st, p, int(q["a"]), int(q["b"]) if q.get("b") else None))
            if rest == "/text":
                from . import engrave
                return self._json({"marks": engrave.list_marks(st, p)})
            # -- standard features at a face, comparing slicers, turntables (form/feature_helpers.py, slicecompare.py, animate.py) --
            if rest == "/features":
                from . import feature_helpers
                return self._json({"features": feature_helpers.list_features(st, p)})
            if rest == "/features/check":
                from . import feature_helpers
                o = {k: q[k] for k in ("size", "hole", "height", "outer_d", "hole_d", "hole_depth", "length", "thickness",
                                       "width", "lip", "lip_height") if q.get(k) not in (None, "")}
                return self._json(feature_helpers.preview(q.get("kind") or "boss", nozzle=st.slicer_info(p=p).get("nozzle_mm"),
                                                          allow_strain=float(q["allow_strain"]) if q.get("allow_strain") else None, **o))
            if rest == "/slicecompare":
                from . import slicecompare
                return self._json(slicecompare.cached(st, p) or {"rows": [], "cached": False})
            if rest == "/lighten":                       # the last "Make it lighter" search for this revision (form/lighten.py)
                from . import lighten
                return self._json(lighten.cached(st, p) or {"candidates": [], "cached": False, "none": True})
            if rest == "/text/check":
                from . import engrave
                return self._json(engrave.printability(q.get("text") or "", float(q.get("height") or 6), float(q.get("depth") or 0.6),
                                                       q.get("sunk") == "1", st.slicer_info(p=p).get("nozzle_mm")))
            if rest.startswith("/job/"):
                job = st.jobs.get(rest[5:])
                if not job:
                    raise StudioError("Unknown job.", status=404)
                return self._json(job)
            if rest == "/archive":
                f = st.export_archive(p)
                return self._send(200, f.read_bytes(), "application/zip",
                                  {"Content-Disposition": _attachment(f.name)})
            # -- design tools: revision timeline, variants board, share card (form/share.py, form/variants.py) --
            if rest == "/revisions":
                from . import share
                return self._json({"head": p["head"], "revisions": share.revisions(st, p)})
            if rest == "/variants":
                from . import variants
                return self._json(variants.board(st, p))
            mv = re.fullmatch(r"/variants/(@head|[a-z0-9-]+)/view", rest)
            if mv:
                from . import variants
                return self._json(variants.view(st, p, mv.group(1)))
            if rest in ("/share", "/share.png"):
                from . import share
                c = share.card(st, p, picture="photo" if q.get("picture") == "photo" else "model")
                if rest == "/share":
                    return self._json(c)
                return self._send(200, Path(c["file"]).read_bytes(), "image/png")
            m2 = re.fullmatch(r"/file/(exports|slice|side|motion|releases|references|share)/([A-Za-z0-9_.\-]+)(?:/([A-Za-z0-9_.\-]+))?", rest)
            if m2:
                node, a, b = m2.groups()
                base = st.dir(pid) / (node if node in ("releases", "references", "share") else f"artifacts/{node}")
                if node in ("exports", "slice") and a == "current":
                    a = st.keys(p)[node]
                f = (base / a / b) if b else (base / a)
                f = f.resolve()
                if not f.is_relative_to(base.resolve()) or not f.is_file():
                    raise StudioError("That file does not exist (it may be stale and regenerated under a new key).", status=404)
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                extra = {} if ctype.startswith("image/") else {"Content-Disposition": _attachment(f.name)}
                return self._send(200, f.read_bytes(), ctype, extra)
            if rest == "/freecad_macro":                         # CAD bridges: FreeCAD macro download
                name, text = st.freecad_macro(p)
                return self._send(200, text.encode("utf-8"), "text/x-python; charset=utf-8",
                                  {"Content-Disposition": _attachment(name)})

            # ---- maker documents (BOM, ASSEMBLY, PRINT_REPORT, MEASUREMENT_PLAN): working files, or a release's as .zip ----
            md = re.fullmatch(r"/docs/([A-Za-z0-9_.\-]+)", rest)
            if md:
                from . import maker_docs
                rel = q.get("release")
                if rel and not re.fullmatch(r"r\d+-[0-9a-f]+", rel):
                    raise StudioError("Unknown release.", status=404)
                if rel and md.group(1) == "files.zip":
                    f = maker_docs.release_files_zip(st, p, rel)
                else:
                    f = maker_docs.release_zip(st, p, rel) if rel else maker_docs.working(st, p, md.group(1))
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                extra = {} if ctype.startswith("image/") else {"Content-Disposition": _attachment(f.name)}
                return self._send(200, f.read_bytes(), ctype, extra)
            m3 = re.fullmatch(r"/release/(r\d+-[0-9a-f]+)", rest)
            if m3:
                return self._json(st.verify_release(p, m3.group(1)))
            # -- Blender renders (form/photo.py) --
            if rest == "/photo":
                from . import photo
                return self._json(photo.state(st, p))
            m4 = re.fullmatch(r"/photo/([0-9a-f]{16}|latest)\.png", rest)
            if m4:
                from . import photo
                return self._send(200, photo.file(st, p, m4.group(1)).read_bytes(), "image/png")
            raise StudioError("Not found.", status=404)

        # -- conversations: saved chats, attachments, the agent/model choice (chat workstream) ----------------
        def _conv(self, fn):
            from .conversations import ConversationError
            try:
                return fn()
            except ConversationError as e:
                raise StudioError(str(e), status=404 if "Unknown conversation" in str(e) else 400)
            except RuntimeError as e:
                raise StudioError(str(e), status=409)

        def _conv_get(self, path, q):
            if path == "/api/conversations":
                proj = q.get("project")
                if q.get("thread"):
                    return self._json({"conversations": st.chat.list(None, q.get("q"), thread=q["thread"]),
                                       "running": len(st.chat.running())})
                if q.get("involving"):                      # every conversation that made or touched this design
                    return self._json({"conversations": st.chat.list(None, q.get("q"), involving=q["involving"]),
                                       "running": len(st.chat.running())})
                return self._json({"conversations": st.chat.list(proj if proj else None, q.get("q")),
                                   "running": len(st.chat.running())})
            mr = re.fullmatch(r"/api/conversations/render/([a-z0-9-]+)/([A-Za-z0-9_.\-]+\.png)", path)
            if mr:                                          # a render the agent looked at, for the inline thumbnail
                base = (st.root / mr.group(1) / "artifacts" / "renders").resolve()
                f = (base / mr.group(2)).resolve()
                if not f.is_relative_to(base) or not f.is_file():
                    raise StudioError("That render is no longer on disk.", status=404)
                return self._send(200, f.read_bytes(), "image/png")
            if path == "/api/conversations/fetches":       # downloads running now, for a progress toast
                from . import start as start_mod
                return self._json({"fetches": start_mod.progress()})
            mp = re.fullmatch(r"/api/conversations/([0-9a-f]{12})/preflight/([A-Za-z0-9_.\-]+)", path)
            if mp:                                          # a mesh attachment's preflight and display proxy
                from . import meshprep
                f = self._conv(lambda: st.chat.store.attachment(mp.group(1), mp.group(2)))
                try:
                    return self._json(meshprep.preflight(f, cache=st.root / ".cache" / "meshprep"))
                except ValueError as e:
                    raise StudioError(f"{mp.group(2)[7:]} could not be read as a mesh: {e}")
            mf = re.fullmatch(r"/api/conversations/([0-9a-f]{12})/file/([A-Za-z0-9_.\-]+)", path)
            if mf:
                f = self._conv(lambda: st.chat.store.attachment(mf.group(1), mf.group(2)))
                return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
            md = re.fullmatch(r"/api/conversations/([0-9a-f]{12})/designs", path)
            if md:                                          # the designs it made or touched, in order, state now
                cid = md.group(1)
                return self._json(self._conv(lambda: {"conversation": cid, "project": st.chat.store.meta(cid).get("project"),
                                                      "designs": st.chat.store.designs(cid)}))
            mi = re.fullmatch(r"/api/conversations/([0-9a-f]{12})/ask/([0-9a-f]{10})/image", path)
            if mi:                                          # the picture of a measurement question (ask_measurement)
                f = self._conv(lambda: st.chat.ask_image(mi.group(1), mi.group(2)))
                return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "image/png")
            m = re.fullmatch(r"/api/conversations/([0-9a-f]{12})", path)
            if m:
                return self._json(self._conv(lambda: st.chat.conversation(m.group(1), int(q.get("from") or 0))))
            raise StudioError("Not found.", status=404)

        def _conv_post(self, path, body):
            from . import chat as chat_mod2
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if path == "/api/chat/defaults":
                try:
                    return self._json(chat_mod2.set_defaults(st.cfg, body.get("agent"), body.get("model"), body.get("effort")))
                except ValueError as e:
                    raise StudioError(str(e))
            if path == "/api/conversations":
                # draft: files, sketches or links attached before the first message; it becomes a conversation (and
                # is listed) when that message is sent, and is cleared if it never is
                d = st.chat.status()["default"]
                return self._json(st.chat.store.create(body.get("project") or None, body.get("agent") or d["agent"],
                                                       body.get("model") or d["model"],
                                                       body.get("effort") if body.get("effort") is not None else d["effort"],
                                                       str(body.get("title") or ""), draft=bool(body.get("draft"))))
            if path == "/api/conversations/send":           # first message of a new conversation
                cid = None
            else:
                m = re.fullmatch(r"/api/conversations/([0-9a-f]{12})/(send|stop|rename|pin|delete|attach|settings|note|answer|fetch|sketch|fork|link)", path)
                if not m:
                    raise StudioError("Not found.", status=404)
                cid, verb = m.group(1), m.group(2)
                if verb == "stop":
                    return self._json({"stopped": st.chat.stop(cid)})
                if verb == "rename":
                    return self._json(self._conv(lambda: st.chat.store.rename(cid, str(body.get("title", "")))))
                if verb == "fork":                          # a branch of this conversation, in the same thread
                    at = body.get("at_event")
                    return self._json(self._conv(lambda: st.chat.store.fork(
                        cid, None if at is None else at, body.get("project") or None, str(body.get("reason") or ""))))
                if verb == "link":                          # the conversation follows its design to another project
                    proj = body.get("project") or None
                    if proj:
                        st.load(proj)                       # 404 for a design that does not exist
                    return self._json(self._conv(lambda: st.chat.store.link(cid, proj)))
                if verb == "pin":
                    return self._json(self._conv(lambda: st.chat.store.pin(cid, bool(body.get("on", True)))))
                if verb == "delete":
                    self._conv(lambda: st.chat.delete(cid))
                    return self._json({"deleted": cid})
                if verb == "answer":                        # the person's answer to ask_user / ask_measurement
                    from . import start as start_mod      # a measurement is committed first (form/start.py)
                    return self._json(self._conv(lambda: start_mod.answer(
                        st, cid, str(body.get("id", "")), str(body.get("text") or ""),
                        [str(c) for c in (body.get("choices") or [])], body.get("measure"))))
                if verb == "fetch":                         # a pasted link: a file or a model's files attached, a page passed on
                    from . import start as start_mod
                    return self._json(start_mod.fetch(st, cid, str(body.get("url") or "")))
                if verb == "sketch":                        # a sketch drawn in Form Studio, as structured geometry
                    from . import sketch as sketch_mod
                    try:
                        sk = sketch_mod.validate(body.get("sketch"))
                        summary = sketch_mod.summarize(sk)
                    except ValueError as e:
                        raise StudioError(f"The sketch could not be read: {e}", "Draw it again, or send the picture instead.")
                    name = re.sub(r"\.sketch\.json$|\.json$", "", str(body.get("name") or "sketch"), flags=re.I) or "sketch"
                    data = json.dumps(sk, ensure_ascii=False).encode("utf-8")
                    rec = self._conv(lambda: st.chat.store.attach(cid, name=name + ".sketch.json", data=data))
                    return self._json({"attachments": [rec], "summary": summary})
                if verb == "note":
                    return self._json(self._conv(lambda: st.chat.note(cid, body.get("by", "agent"), body.get("text", ""))))
                if verb == "settings":
                    keep = {k: str(body[k]) for k in ("agent", "model", "effort") if body.get(k) is not None}
                    if "project" in body:
                        keep["project"] = body["project"] or None
                    return self._json(self._conv(lambda: st.chat.store.update(cid, **keep)))
                if verb == "attach":
                    if isinstance(body, bytes):             # raw upload: ?name=file.png
                        rec = self._conv(lambda: st.chat.store.attach(cid, name=q.get("name") or "file", data=body))
                        return self._json({"attachments": [rec]})
                    paths, names = list(body.get("paths") or []), list(body.get("names") or [])
                    names += [""] * (len(paths) - len(names))
                    recs = self._conv(lambda: [st.chat.store.attach(cid, Path(str(p)), name=str(n) or None)    # by path:
                                               for p, n in zip(paths, names)])                            # never read whole
                    return self._json({"attachments": recs})
            msg = str(body.get("message", "")).strip()[:16000]
            if not msg:
                raise StudioError("Write a message first.")
            purpose = body.get("purpose") or None          # "print" | "model" | "game" (form/start.py), kept on the conversation
            if purpose is not None and purpose not in start_purposes():
                raise StudioError(f"Unknown purpose “{purpose}”.", "Use \"print\", \"model\" or \"game\".")
            attach_ids = list(body.get("attachments") or [])
            from . import start as start_mod              # links pasted in the message: the engine fetches them now
            if start_mod.links_in(msg):
                if cid is None:
                    cid = self._conv(lambda: start_mod.conversation_for(st, body))
                got_ids, link_note = start_mod.fetch_message_links(st, cid, msg)
                attach_ids += [i for i in got_ids if i not in attach_ids]
            else:
                link_note = ""
            job = self._conv(lambda: st.chat.send(msg, cid, body.get("project") or None, body.get("agent") or None,
                                                  body.get("model") or None, body.get("effort"), attach_ids,
                                                  purpose=purpose, note=link_note))
            st.activity(job.project, "chat", msg[:200], by="you")
            return self._json({"id": job.id, "conversation": job.conversation, "meta": st.chat.store.meta(job.conversation)})

        def _static(self, path):
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            f = (WEB / rel).resolve()
            if not f.is_relative_to(WEB.resolve()) or not f.is_file():
                return self._send(404, b"Not found", "text/plain")
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if f.suffix == ".js":
                ctype = "text/javascript"
            self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))

        # -- POST ----------------------------------------------------------
        def _post(self):
            path = urlparse(self.path).path
            body = self._body()
            if path == "/api/projects":
                p = st.create(body.get("name", ""), body.get("recipe", ""), body.get("brief", ""), body.get("values"),
                              purpose=body.get("purpose"), process=body.get("process"))
                job = st.run(p["id"])
                return self._json({"id": p["id"], "job": job})
            if path == "/api/replace/brief":                # Home › Replace a broken part (form/replace.py): the message only
                from . import replace
                return self._json({"message": replace.brief(str(body.get("name") or ""), str(body.get("what") or ""),
                                                            str(body.get("reference") or "card"), str(body.get("coin") or ""),
                                                            str(body.get("broke") or ""), str(body.get("purpose") or "print")),
                                   "steps": replace.STEPS})
            if path == "/api/import":
                p = st.import_archive(body if isinstance(body, bytes) else b"")
                return self._json({"id": p["id"]})
            if path.startswith("/api/conversations") or path == "/api/chat/defaults":   # chat workstream
                return self._conv_post(path, body)
            if path == "/api/chat":
                msg = str(body.get("message", "")).strip()[:8000]
                if not msg:
                    raise StudioError("Write a message first.")
                try:
                    job = st.chat.start(msg, body.get("project") or None, body.get("session") or None)
                except RuntimeError as e:
                    raise StudioError(str(e), status=409)
                st.activity(body.get("project"), "chat", msg[:200], by="you")
                return self._json({"id": job.id})
            mc = re.fullmatch(r"/api/chat/([0-9a-f]{10})/stop", path)
            if mc:
                st.chat.stop(mc.group(1))
                return self._json({"ok": True})
            # -- setup (app setup workstream) --
            if path == "/api/setup/apply":
                job = st.setup_app.apply(body.get("ids"), body.get("shown"))
                return self._json({"job": job.id, **job.public()})
            if path == "/api/setup/seen":
                return self._json(setup_app.mark_seen(st.cfg, str(body.get("how") or "seen")[:20]))
            # -- installer, sign-in, settings, examples (setup workstream; routes live in form/setup_app.py) --
            owned = setup_app.route_post(st, path, body)
            if owned is not None:
                return self._json(owned)
            # -- Home and new design (home workstream; form/home_api.py) --
            from . import home_api
            got = home_api.route_post(st, path, body, {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()})
            if got is not None:
                return self._json(got)
            # -- brief templates: save a filled-in brief, get the chat prompt that carries it --
            if path == "/api/briefs":
                from . import presets
                try:
                    return self._json(presets.start_brief(st.root, str(body.get("preset", "")), body.get("answers") or {},
                                                          bool(body.get("measured"))))
                except ValueError as e:
                    raise StudioError(str(e), "Fill in the required fields; numbers use the unit shown.")
            if path == "/api/studio/refresh":
                st.slicer_info(refresh=True)
                return self._json({"env": st.environment()})
            # -- slicer picker: change only [slicer].kind in studio.toml (backed up first) --
            if path == "/api/studio/slicer":
                from . import slicer as slicer_mod
                try:
                    done = slicer_mod.set_kind(st.cfg, str(body.get("kind", "")))
                except slicer_mod.SlicerBlocked as e:
                    raise StudioError(str(e), "Known kinds: auto, " + ", ".join(slicer_mod.SLICERS) + ".")
                except OSError as e:
                    raise StudioError(f"Could not write studio.toml: {e}", "Check that the file and its folder are writable.")
                st.slicer_info(refresh=True)
                from . import printers as printers_mod
                printers_mod.clear_cache()
                st.activity(None, "slicer", f"Slicer set to {done['kind']} in {Path(done['path']).name}.", by="you")
                return self._json({**done, "env": st.environment()})
            # -- printers: choose the printer of a design, or the default (form/printers.py) --
            if path.startswith("/api/printers"):
                from . import printers as printers_mod
                owned = printers_mod.route_post(st, path, body)
                if owned is not None:
                    return self._json(owned)
            m = re.fullmatch(r"/api/projects/([a-z0-9-]+)/([a-z_]+)", path)
            if not m:
                raise StudioError("Not found.", status=404)
            pid, action = m.groups()
            # -- project housekeeping: rename, duplicate, delete (app shell). Before the load below, so a project
            #    whose state file is unreadable can still be moved to the trash. --
            if action in ("rename", "duplicate", "delete"):
                body = body if isinstance(body, dict) else {}
                if action == "rename":
                    row = st.rename_project(pid, body.get("name"))
                    st.activity(pid, "project", f"Renamed to “{row['name']}”.", by="you")
                    return self._json(row)
                if action == "duplicate":
                    row = st.duplicate_project(pid, body.get("name"))
                    st.activity(row["id"], "project", f"Copied from {pid} as “{row['name']}”.", by="you")
                    return self._json(row)
                res = st.delete_project(pid)
                st.activity(None, "project", f"Moved {pid} to the trash folder.", by="you")
                return self._json(res)
            p = st.load(pid)
            recipe = st.recipe(p)
            auto = lambda proj: st.run(pid) if proj.get("auto_run", True) else None
            # -- "Make editable": an imported mesh reconstructed as a new design (form/recon) --
            if action == "reconstruct":
                kw = {k: body[k] for k in ("name",) if body.get(k)}
                if body.get("tolerance") is not None:
                    kw["tolerance"] = float(body["tolerance"])
                if body.get("layer") is not None:
                    kw["layer"] = int(body["layer"])
                files = [str(f) for f in body.get("files") or [] if f]
                if len(files) >= 2:                     # the parts of one product: one design, one part per mesh
                    from . import multipart
                    known = {r["file"] for r in st.references(p)}
                    bad = [f for f in files if f not in known]
                    if bad:
                        raise StudioError(f"There is no reference part {', '.join(bad)} in this project.",
                                          "Import the meshes first (Brief > Import part).")
                    out = multipart.reconstruct_parts(st, [st.dir(pid) / "references" / f for f in files], **kw)
                    what = f"{len(out['parts'])} meshes"
                else:
                    out = st.reconstruct_reference(p, str(body.get("file") or (files[0] if files else "")), **kw)
                    what = str(body.get("file") or files[0])
                # it comes from this design: same family, and the conversations about this design list it
                st.adopt(out["project"], pid, "reconstruct")
                from .conversations import Conversations
                store = Conversations(st.root)
                last = store.latest(pid)
                if last:
                    store.record(last["id"], out["project"], "made", tool="reconstruct", front=False)
                st.activity(out["project"], "design", f"Made {what} editable as “{out['name']}”.", by="you")
                return self._json(out)
            # -- "Rebuild as editable CAD": the message that starts the agent remodel (form/remodel) --
            if action == "rebuild_brief":
                from .remodel import project as remodel
                return self._json(remodel.rebuild_brief(st, p, body.get("files") or None))
            # -- measuring (form/analysis.py) --
            if action == "probe":
                from . import analysis
                return self._json(analysis.probe(st, p, body.get("at"), body.get("rev")))
            if action == "measure":
                from . import analysis
                return self._json(analysis.measure(st, p, body.get("from"), body.get("to"), body.get("rev"),
                                                   body.get("from_on"), body.get("to_on")))
            # -- colours and materials (form/materials.py): a material changes the checks' notes, so they re-run --
            if action == "appearance":
                from . import materials
                had = materials.fingerprint(p)
                out = materials.set_appearance(st, pid, str(body.get("part") or ""), body.get("color", "keep"),
                                               body.get("material", "keep"), by="you")
                if materials.fingerprint(st.load(pid)) != had:
                    auto(st.load(pid))
                return self._json(out)
            # -- drag a face, change the parameter behind it (form/dragface.py) --
            if action == "drag_face":
                from . import dragface
                return self._json(dragface.find(st, p, body.get("at"), body.get("normal"),
                                                int(body["rev"]) if body.get("rev") is not None else None,
                                                body.get("values") if isinstance(body.get("values"), dict) else None))
            # -- selections and annotations (form/selection.py) --
            if action in ("select", "annotate", "annotation", "annotation_delete", "annotation_analyze"):
                from . import selection
                rv = int(body["rev"]) if body.get("rev") is not None else None
                if action == "select":
                    return self._json(selection.analyze(st, p, body.get("items"), rv))
                if action == "annotate":
                    return self._json(selection.add(st, pid, body.get("items"), body.get("name", ""), body.get("note", ""), rv, by="you"))
                if action == "annotation":
                    return self._json(selection.update(st, pid, str(body.get("id", "")), body.get("name"), body.get("note")))
                if action == "annotation_delete":
                    return self._json(selection.delete(st, pid, str(body.get("id", ""))))
                return self._json(selection.reanalyze(st, pid, str(body.get("id", "")), rv))
            if action in ("text", "text_remove"):
                from . import engrave
                eh = int(body["expect_head"]) if body.get("expect_head") is not None else None
                if action == "text_remove":
                    out = engrave.remove(st, p, str(body.get("id", "")), eh)
                else:
                    out = engrave.add(st, p, body.get("text", ""), body.get("at"), body.get("normal"), float(body.get("height") or 6),
                                      float(body.get("depth") or 0.6), bool(body.get("sunk")), body.get("up"), eh)
                st.activity(pid, "design", f"Text on a face: r{out['head']:02d}.", by="you")
                out["job"] = auto(st.load(pid))
                return self._json(out)
            if action in ("feature", "feature_remove"):
                from . import feature_helpers
                eh = int(body["expect_head"]) if body.get("expect_head") is not None else None
                if action == "feature_remove":
                    out = feature_helpers.remove(st, p, str(body.get("id", "")), eh)
                else:
                    o = {k: v for k, v in (body.get("options") or {}).items()}
                    out = feature_helpers.add(st, p, body.get("kind", ""), body.get("at"), body.get("normal"), eh, "you", **o)
                st.activity(pid, "design", f"Standard feature: r{out['head']:02d}.", by="you")
                out["job"] = auto(st.load(pid))
                return self._json(out)
            if action == "lighten":
                from . import lighten
                return self._json(lighten.search(st, p, builds=int(body.get("builds") or 4)))
            if action == "lighten_apply":
                from . import lighten
                eh = int(body["expect_head"]) if body.get("expect_head") is not None else None
                out = lighten.apply_values(st, p, body.get("changes"), body.get("settings"), eh, "you")
                st.activity(pid, "design", "Lighter: " + (f"r{out['head']:02d}" if body.get("changes") else "print settings") + ".", by="you")
                out["job"] = auto(st.load(pid))
                return self._json(out)
            if action == "slicer_open":                    # Open in <Slicer>: chosen settings, sliced, opened (form/slicer_open.py)
                from . import slicer_open
                out = slicer_open.run(st, p, body.get("printer") or None, open_app=body.get("open", True) is not False)
                st.activity(pid, "look", f"Opened in {out['slicer']} with settings chosen for this part.", by="you")
                return self._json(out)
            if action == "slicecompare":
                from . import slicecompare
                return self._json(slicecompare.compare(st, p, limit=int(body.get("limit") or slicecompare.LIMIT),
                                                       ids=body.get("printers") or None))
            if action == "turntable":
                from . import animate
                return self._json(animate.export(st, p, body.get("fmt") or "webp", int(body.get("frames") or 36),
                                                 float(body.get("elevation") if body.get("elevation") is not None else 24)))
            if action == "instructions":
                from . import instructions
                return self._json(instructions.build(st, p, int(body["rev"]) if body.get("rev") is not None else None))
            if action == "preview":
                return self._json(st.preview(p, body.get("values", {})))
            if action == "commit":
                p = st.commit(p, body.get("values", {}), body.get("note", ""), body.get("origin", "user"), body.get("provenance"))
                return self._json({"head": p["head"], "job": auto(p)})
            if action == "checkout":
                p = st.checkout(p, int(body["rev"]))
                return self._json({"head": p["head"], "job": auto(p)})
            if action == "cost":                           # prices and printer power: kept in <data dir>/cost.json
                from . import cost
                try:
                    cost.save_prefs(st.cfg, body if isinstance(body, dict) else {})
                except ValueError as e:
                    raise StudioError(str(e))
                return self._json(cost.project(st, p, int(body.get("copies") or 1)))
            if action == "settings":
                p = st.settings(p, body)
                return self._json({"job": auto(p)})
            if action == "part":                           # per-part orientation, material, colour (form/plates.py, materials.py)
                st.set_part(pid, str(body.get("part") or ""), **{k: body.get(k) for k in ("orientation", "material", "color")})
                return self._json({"job": auto(st.load(pid))})
            if action == "run":
                nodes = [n for n in body.get("nodes", []) if n in NODES] or None
                return self._json({"job": st.run(pid, nodes, bool(body.get("force")))})
            if action == "intent":
                values = st.rev(p)["values"]
                text, feature = str(body.get("text", ""))[:2000], body.get("feature") or None
                tier = body.get("tier", "rule")
                if tier == "rule":
                    prop = advisor.parse_intent(recipe, values, text, feature)
                    if prop is None:
                        return self._json({"proposal": None, "assistant": advisor.cli_status(st.cfg),
                                           "message": "I could not read that as a single parameter change."})
                else:
                    state = st.state(pid)
                    ctx = {"brief": p["brief"]["text"],
                           "derived": recipe.derived(values),
                           "checks": [{k: c[k] for k in ("label", "status", "value", "detail")} for c in (state["checks"] or {}).get("checks", [])],
                           "fit": {k: state["fit"][k] for k in ("yield", "expected_gap", "window", "recommended_clearance")} if state["fit"] else None,
                           "printer": st.profile()}
                    try:
                        prop = advisor.consult(st.cfg, recipe, values, ctx, text, feature, "specialist" if tier == "specialist" else "default")
                    except RuntimeError as e:
                        raise StudioError(str(e), "Nothing was changed. You can still edit parameters directly.", status=502)
                    with st.lock(pid):
                        p = st.load(pid)
                        st.decide(p, "consult", f"Asked {prop['requested_model']}: “{text[:160]}” → {prop['summary'][:200]}",
                                  model=prop["resolved_models"], cost_usd=prop["cost_usd"], tier=prop["tier"])
                        st.save(p)
                if prop["changes"]:
                    try:
                        pv = st.preview(p, {c["key"]: c["to"] for c in prop["changes"]})
                        prop["impact"], prop["buildable"] = pv["impact"], True
                    except StudioError as e:
                        prop["buildable"], prop["build_error"] = False, e.public()
                return self._json({"proposal": prop})
            if action == "alternatives":
                try:
                    return self._json(advisor.alternatives(st, p, body.get("axes", []), body.get("weights", {})))
                except (ValueError, KeyError) as e:
                    raise StudioError(str(e))
            if action == "evidence":
                try:
                    rec = st.add_evidence(p, body)
                except ValueError as e:
                    raise StudioError(str(e))
                return self._json({"evidence": rec, "job": auto(st.load(pid))})
            if action == "calibration_remove":
                st.calibration.remove(str(body.get("id")))
                return self._json({"job": auto(p)})
            if action == "render_photo":                   # Blender render, in the background (form/photo.py)
                from . import photo
                return self._json(photo.start(st, pid, body if isinstance(body, dict) else {}))
            if action == "test_piece":
                return self._json(st.side_slice(p, "test_piece"))
            if action == "approve":
                return self._json(st.approve(p, body.get("acknowledged", []), str(body.get("note", ""))[:500],
                                             override_failures=body.get("override_failures") or None))
            if action == "reference":
                m2 = re.fullmatch(r"data:image/(png|jpeg|webp);base64,(.+)", body.get("data", ""), re.S)
                if not m2:
                    raise StudioError("Only PNG, JPEG or WebP images can be attached.")
                raw = base64.b64decode(m2.group(2))
                if len(raw) > 25_000_000:
                    raise StudioError("Image is larger than 25 MB.")
                d = st.dir(pid) / "references"
                d.mkdir(exist_ok=True)
                name = f"ref_{int(time.time())}.{ 'jpg' if m2.group(1) == 'jpeg' else m2.group(1)}"
                (d / name).write_bytes(raw)
                with st.lock(pid):
                    p = st.load(pid)
                    p["brief"]["references"].append({"file": name, "ts": time.time(), "scale_mm_per_px": None, "measurements": []})
                    st.save(p)
                return self._json({"file": name})
            # -- CAD bridges: import a reference part, open a file in another program ------------------
            if action == "import_part":
                q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                if isinstance(body, bytes):
                    rec = st.import_reference(p, Path(q.get("name", "part.step")), q.get("name"), data=body)
                else:
                    rec = st.import_reference(p, Path(str(body.get("path", ""))).expanduser(), body.get("name"))
                return self._json({"reference": rec})
            if action == "open":
                return self._json(open_output(st, pid, str(body.get("what", "step")), str(body.get("app", ""))))
            # -- design tools: variants and the history animation --
            if action in ("variant_save", "variant_delete", "variant_promote"):
                from . import variants
                if action == "variant_save":
                    rev = body.get("rev")
                    return self._json({"variant": variants.save(st, p, str(body.get("name", "")), body.get("values") or None,
                                                                 int(rev) if rev else None, str(body.get("note", "")),
                                                                 str(body.get("by") or "you")[:40], str(body.get("source") or "")[:20])})
                if action == "variant_delete":
                    return self._json(variants.delete(st, p, str(body.get("id", ""))))
                res = variants.promote(st, p, str(body.get("id", "")))
                return self._json({**res, "job": auto(st.load(pid))})
            if action == "history_export":
                from . import share
                fmt = "webp" if body.get("format") == "webp" else "gif"
                out = st.dir(pid) / "share" / f"{pid}_history.{fmt}"
                info = share.history(st, p, out)
                return self._json({**info, "name": out.name})
            if action == "reference_update":
                with st.lock(pid):
                    p = st.load(pid)
                    for ref in p["brief"]["references"]:
                        if ref["file"] == body.get("file"):
                            ref["scale_mm_per_px"] = body.get("scale_mm_per_px")
                            ref["scale_note"] = str(body.get("scale_note", ""))[:200]
                            ref["measurements"] = body.get("measurements", [])[:40]
                    st.save(p)
                return self._json({"ok": True})
            raise StudioError("Not found.", status=404)

    return Handler


def _is_form(url: str, data_dir: str) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(url + "/api/studio", timeout=2) as r:
            return json.loads(r.read()).get("env", {}).get("data_dir") == data_dir
    except Exception:
        return False


def start_bench(st: Studio, tries: int = 10) -> dict:
    """Serve the bench from a background thread (used by the MCP server).

    If a FORM bench for the same data folder is already listening on the
    configured port, reuse it: both processes share the project files, and
    project locks make concurrent edits safe.
    """
    host, port = st.cfg["server"]["host"], int(st.cfg["server"]["port"])
    if host not in ("127.0.0.1", "localhost", "::1"):
        return {"url": None, "error": "Form Studio binds to loopback only."}
    for p in range(port, port + tries):
        url = f"http://{host}:{p}"
        try:
            httpd = ThreadingHTTPServer((host, p), make_handler(st))
        except OSError:
            if _is_form(url, str(st.root)):
                return {"url": url, "shared": True}
            continue
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, daemon=True, name="form-bench").start()
        return {"url": url, "shared": False, "httpd": httpd}
    return {"url": None, "error": f"No free port in {port}-{port + tries - 1}."}


def _quiet(fn):
    try:
        fn()
    except Exception:
        pass   # a failed warm-up is reported on the first real kernel call


def _open(url, cfg):
    import os
    import webbrowser
    if cfg.get("bench", {}).get("auto_open", True) and not os.environ.get("FORM_NO_BROWSER"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()


def serve(cfg=None):
    cfg = cfg or config.load()
    from .capabilities import migrate_safely
    migrate_safely(cfg)                                  # once: people who already print keep printing
    st = Studio(cfg)
    host, port = cfg["server"]["host"], int(cfg["server"]["port"])
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("Form Studio binds to loopback only. Set [server].host to 127.0.0.1.")
    httpd = None
    for p_try in range(port, port + 10):                 # a busy port is not a reason to fail
        try:
            httpd = ThreadingHTTPServer((host, p_try), make_handler(st))
            port = p_try
            break
        except OSError:
            if _is_form(f"http://{host}:{p_try}", str(st.root)):
                print(f"Form Studio is already running for this project folder → http://{host}:{p_try}", flush=True)
                _open(f"http://{host}:{p_try}", cfg)
                return 0
    if httpd is None:
        raise SystemExit(f"No free port between {cfg['server']['port']} and {port + 9}.")
    httpd.daemon_threads = True
    # warm the kernel only once this process owns a port; an early "already running" exit must not leave it mid-call
    threading.Thread(target=lambda: _quiet(st.kernel_id), daemon=True).start()
    print(f"Form Studio → http://{host}:{port}   (data: {cfg['data']['dir']})", flush=True)
    _open(f"http://{host}:{port}", cfg)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        st.kernel.stop()
