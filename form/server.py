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
from urllib.parse import parse_qs, urlparse

from . import advisor, config
from .cad_bridges import open_output
from .studio import NODES, Studio, StudioError

WEB = Path(__file__).resolve().parent / "web"


def make_handler(st: Studio):
    from . import chat as chat_mod
    from .setup import mcp_command
    if not hasattr(st, "chat"):
        st.chat = chat_mod.Chat(st.cfg, st.root, mcp_command())
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
                self.send_header(k, v)
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
                    return self._json({"error": {"message": "FORM only answers on loopback."}}, 403)
                fn()
            except StudioError as e:
                self._json({"error": e.public()}, e.status)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                traceback.print_exc()
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
            if path == "/api/chat":
                return self._json(chat_mod.status(st.cfg))
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
                return self._json({"first_run": setup_app.first_run(st.cfg), "fresh": st.setup_app.fresh})
            ms = re.fullmatch(r"/api/setup/job/([0-9a-f]{10})", path)
            if ms:
                return self._json(st.setup_app.job(ms.group(1)).public())
            if path == "/api/updates":
                return self._json(updates.check(st.cfg, force=q.get("force") == "1"))
            # -- brief templates (presets) --
            if path == "/api/presets":
                from . import presets
                return self._json({"presets": presets.all_presets()})
            if path == "/api/studio":
                return self._json({"env": st.environment(), "projects": st.list(), "chat": chat_mod.status(st.cfg),
                                   "recipes": [r.public() for r in st.recipes.builtins().values()],
                                   "assistant": advisor.cli_status(st.cfg)})
            # -- slicer picker: every slicer FORM knows, installed or not --
            if path == "/api/studio/slicers":
                from . import slicer as slicer_mod
                return self._json({"chosen": st.cfg["slicer"].get("kind", "auto"), "config": str(slicer_mod.config_target(st.cfg)).replace(str(Path.home()), "~"),
                                   "slicers": slicer_mod.detect_all(st.cfg)})
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
            if rest == "/view":
                n = int(q["rev"]) if q.get("rev") else None
                return self._json(st.view(p, n))
            if rest == "/layers":
                layers = st.layers(p)
                if "n" in q:
                    i = max(0, min(len(layers) - 1, int(q["n"])))
                    return self._json({"index": i, "count": len(layers), **layers[i]})
                return self._json({"count": len(layers), "z": [l["z"] for l in layers],
                                   "types": sorted({pp["t"] for l in layers for pp in l["paths"]})})
            if rest == "/diff":
                a, b = int(q["a"]), int(q["b"])
                cand = st.head_summary(p, b)
                return self._json({"a": a, "b": b, "impact": st.impact(p, st.rev(p, b)["values"], cand, base_rev=a),
                                   "note_a": st.rev(p, a)["note"], "note_b": st.rev(p, b)["note"]})
            if rest.startswith("/job/"):
                job = st.jobs.get(rest[5:])
                if not job:
                    raise StudioError("Unknown job.", status=404)
                return self._json(job)
            if rest == "/archive":
                f = st.export_archive(p)
                return self._send(200, f.read_bytes(), "application/zip",
                                  {"Content-Disposition": f'attachment; filename="{f.name}"'})
            m2 = re.fullmatch(r"/file/(exports|slice|side|releases|references)/([A-Za-z0-9_.\-]+)(?:/([A-Za-z0-9_.\-]+))?", rest)
            if m2:
                node, a, b = m2.groups()
                base = st.dir(pid) / (node if node in ("releases", "references") else f"artifacts/{node}")
                if node in ("exports", "slice") and a == "current":
                    a = st.keys(p)[node]
                f = (base / a / b) if b else (base / a)
                f = f.resolve()
                if not f.is_relative_to(base.resolve()) or not f.is_file():
                    raise StudioError("That file does not exist (it may be stale and regenerated under a new key).", status=404)
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                extra = {} if ctype.startswith("image/") else {"Content-Disposition": f'attachment; filename="{f.name}"'}
                return self._send(200, f.read_bytes(), ctype, extra)
            if rest == "/freecad_macro":                         # CAD bridges: FreeCAD macro download
                name, text = st.freecad_macro(p)
                return self._send(200, text.encode("utf-8"), "text/x-python; charset=utf-8",
                                  {"Content-Disposition": f'attachment; filename="{name}"'})

            # ---- maker documents (BOM, ASSEMBLY, PRINT_REPORT, MEASUREMENT_PLAN): working files, or a release's as .zip ----
            md = re.fullmatch(r"/docs/([A-Za-z0-9_.\-]+)", rest)
            if md:
                from . import maker_docs
                rel = q.get("release")
                if rel and not re.fullmatch(r"r\d+-[0-9a-f]+", rel):
                    raise StudioError("Unknown release.", status=404)
                f = maker_docs.release_zip(st, p, rel) if rel else maker_docs.working(st, p, md.group(1))
                ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
                extra = {} if ctype.startswith("image/") else {"Content-Disposition": f'attachment; filename="{f.name}"'}
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
                p = st.create(body.get("name", ""), body.get("recipe", ""), body.get("brief", ""), body.get("values"))
                job = st.run(p["id"])
                return self._json({"id": p["id"], "job": job})
            if path == "/api/import":
                p = st.import_archive(body if isinstance(body, bytes) else b"")
                return self._json({"id": p["id"]})
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
                    raise StudioError(str(e), "Known kinds: auto, bambu, orca, prusa, superslicer, qidi.")
                except OSError as e:
                    raise StudioError(f"Could not write studio.toml: {e}", "Check that the file and its folder are writable.")
                st.slicer_info(refresh=True)
                st.activity(None, "slicer", f"Slicer set to {done['kind']} in {Path(done['path']).name}.", by="you")
                return self._json({**done, "env": st.environment()})
            m = re.fullmatch(r"/api/projects/([a-z0-9-]+)/([a-z_]+)", path)
            if not m:
                raise StudioError("Not found.", status=404)
            pid, action = m.groups()
            p = st.load(pid)
            recipe = st.recipe(p)
            auto = lambda proj: st.run(pid) if proj.get("auto_run", True) else None
            if action == "preview":
                return self._json(st.preview(p, body.get("values", {})))
            if action == "commit":
                p = st.commit(p, body.get("values", {}), body.get("note", ""), body.get("origin", "user"), body.get("provenance"))
                return self._json({"head": p["head"], "job": auto(p)})
            if action == "checkout":
                p = st.checkout(p, int(body["rev"]))
                return self._json({"head": p["head"], "job": auto(p)})
            if action == "settings":
                p = st.settings(p, body)
                return self._json({"job": auto(p)})
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
                return self._json(st.approve(p, body.get("acknowledged", []), str(body.get("note", ""))[:500]))
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
        return {"url": None, "error": "FORM binds to loopback only."}
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
    st = Studio(cfg)
    host, port = cfg["server"]["host"], int(cfg["server"]["port"])
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit("FORM binds to loopback only. Set [server].host to 127.0.0.1.")
    httpd = None
    for p_try in range(port, port + 10):                 # a busy port is not a reason to fail
        try:
            httpd = ThreadingHTTPServer((host, p_try), make_handler(st))
            port = p_try
            break
        except OSError:
            if _is_form(f"http://{host}:{p_try}", str(st.root)):
                print(f"FORM is already running for this project folder → http://{host}:{p_try}", flush=True)
                _open(f"http://{host}:{p_try}", cfg)
                return 0
    if httpd is None:
        raise SystemExit(f"No free port between {cfg['server']['port']} and {port + 9}.")
    httpd.daemon_threads = True
    # warm the kernel only once this process owns a port; an early "already running" exit must not leave it mid-call
    threading.Thread(target=lambda: _quiet(st.kernel_id), daemon=True).start()
    print(f"FORM studio → http://{host}:{port}   (data: {cfg['data']['dir']})", flush=True)
    _open(f"http://{host}:{port}", cfg)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        st.kernel.stop()
