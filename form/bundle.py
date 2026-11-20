"""Move a design to another computer, or keep it: one file with the project, its conversations and the code it was built from.

A ``.formstudio`` file is a zip:

    manifest.json                       {"format": "form-studio-archive/1", "app": version, "exported": ISO time,
                                         "project": {"id", "name"}, "conversations": [ids], "sources": [files]}
    project/…                           the project folder (history, variants, built outputs; no temp or backup files)
    sources/<sha>.py | <sha>.scad       the code every revision designed as code was built from
    conversations/<id>/meta.json        each conversation about this design
    conversations/<id>/events.jsonl
    conversations/<id>/files/…          its attachments

Importing checks everything before writing anything: the manifest, every path (no absolute paths, no "..", no links),
sizes, the project schema, and that each design source still hashes to its name. A project id or conversation id that
already exists gets a new one; nothing in the data folder is overwritten. An older ``.formproj`` (the project folder
alone) still imports.

Conversations also export alone, as Markdown (to read) or JSON (to import again).

    form export PROJECT [--out file.formstudio] [--no-conversations]
    form import FILE.formstudio | FILE.formproj | CONVERSATION.json
    form export-conversation ID [--format md|json] [--out file]
"""
from __future__ import annotations

import io
import json
import re
import shutil
import stat
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath

FORMAT = "form-studio-archive/1"
CONV_FORMAT = "form-studio-conversation/1"
EXT = ".formstudio"
MAX_FILE = 300_000_000
MAX_TOTAL = 2_000_000_000
MAX_FILES = 20_000
SOURCE_RE = re.compile(r"[0-9a-f]{16}\.(py|scad)")
CID_RE = re.compile(r"[0-9a-f]{12}")
SKIP_SUFFIX = (".tmp", ".bak")


class BundleError(ValueError):
    def __init__(self, message: str, hint: str = "", status: int = 400):
        super().__init__(message)
        self.hint, self.status = hint, status

    def public(self) -> dict:
        return {"message": str(self), "hint": self.hint}


def _iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or time.time()))


def _sources_of(st, p: dict) -> list[Path]:
    from .recipes import is_source, source_path
    out = []
    for rid in {r.get("recipe") or p["recipe"] for r in p["revisions"]} | {p["recipe"]}:
        if is_source(rid):
            f = source_path(st.sources, rid)
            if f.is_file() and f not in out:
                out.append(f)
    return out


# ---- export -------------------------------------------------------------------------------------------------

def export_project(st, pid: str, out: Path | None = None, conversations: bool = True) -> Path:
    """Write <pid>.formstudio (into the data folder unless out is given). Returns its path."""
    from .conversations import Conversations
    with st.lock(pid):
        p = st.load(pid)
        d = st.dir(pid)
        convs = Conversations(st.root).list(project=pid, limit=100000) if conversations else []
        srcs = _sources_of(st, p)
        out = Path(out) if out else st.root / f"{pid}{EXT}"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.name + ".part")
        manifest = {"format": FORMAT, "app": _version(), "exported": _iso(), "project": {"id": pid, "name": p["name"]},
                    "conversations": [c["id"] for c in convs], "sources": [f.name for f in srcs]}
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", json.dumps(manifest, indent=1, ensure_ascii=False))
            for f in sorted(d.rglob("*")):
                if f.is_file() and not f.is_symlink() and not f.name.endswith(SKIP_SUFFIX) and ".src" not in f.parts[-2:]:
                    z.write(f, "project/" + f.relative_to(d).as_posix())
            for f in srcs:
                z.write(f, "sources/" + f.name)
            for c in convs:
                cd = Conversations(st.root).dir(c["id"])
                for f in sorted(cd.rglob("*")):
                    if f.is_file() and not f.is_symlink() and not f.name.endswith(SKIP_SUFFIX):
                        z.write(f, f"conversations/{c['id']}/" + f.relative_to(cd).as_posix())
    tmp.replace(out)
    return out


def _version() -> str:
    from . import __version__
    return __version__


# ---- import -------------------------------------------------------------------------------------------------

def _safe_name(name: str) -> PurePosixPath:
    if "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name) or "\x00" in name:
        raise BundleError("The archive contains an unsafe path and was not imported.", f"Path: {name[:120]}")
    pp = PurePosixPath(name)
    if any(part in ("..", "") for part in pp.parts if part != ".") or ".." in pp.parts:
        raise BundleError("The archive contains an unsafe path and was not imported.", f"Path: {name[:120]}")
    return pp


def _check_zip(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = z.infolist()
    if len(infos) > MAX_FILES:
        raise BundleError("The archive has too many files to be a Form Studio project.")
    total = 0
    for i in infos:
        _safe_name(i.filename)
        mode = (i.external_attr >> 16) & 0o170000
        if mode == stat.S_IFLNK:
            raise BundleError("The archive contains a link and was not imported.", f"Path: {i.filename[:120]}")
        if i.file_size > MAX_FILE:
            raise BundleError("A file in the archive is too large.", f"{i.filename[:120]}: {i.file_size} bytes")
        total += i.file_size
    if total > MAX_TOTAL:
        raise BundleError("The archive is too large to import.")
    return infos


def _free(base: Path, want: str, pattern: str = "{}-{}") -> str:
    pid, i = want, 2
    while (base / pid).exists():
        pid, i = pattern.format(want, i), i + 1
    return pid


def read_manifest(data: bytes) -> dict | None:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        return json.loads(z.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        return None


def import_bytes(st, data: bytes) -> dict:
    """Import a .formstudio (or an older .formproj) archive. Returns {"id", "name", "renamed_from", "conversations": [...]}."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise BundleError("That file is not a Form Studio archive.", "Choose a .formstudio or .formproj file exported from Form Studio.") from None
    infos = _check_zip(z)
    names = {i.filename for i in infos}
    if "manifest.json" not in names:
        if "project.json" in names:                          # an older .formproj: the project folder alone
            p = st.import_archive(data)
            return {"id": p["id"], "name": p["name"], "renamed_from": None, "conversations": [], "format": "formproj"}
        raise BundleError("That file is not a Form Studio archive.", "Choose a .formstudio or .formproj file exported from Form Studio.")
    try:
        man = json.loads(z.read("manifest.json"))
    except ValueError:
        raise BundleError("The archive's manifest is damaged.") from None
    if not isinstance(man, dict) or man.get("format") != FORMAT:
        raise BundleError("This archive was made by a version of Form Studio this one does not read.",
                          f"Format: {str(man.get('format') if isinstance(man, dict) else '?')[:60]}. Update Form Studio and try again.")
    try:
        p = json.loads(z.read("project/project.json"))
    except (KeyError, ValueError):
        raise BundleError("The archive has no readable project.") from None
    from .studio import SCHEMA, slugify
    if not isinstance(p, dict) or p.get("schema") != SCHEMA or not isinstance(p.get("revisions"), list) or not p.get("revisions"):
        raise BundleError("This archive was made by an incompatible version of Form Studio.")

    # design sources: name must be the hash of the content, exactly as Form Studio stores them
    from .recipes import SCAD_PREFIX, SOURCE_PREFIX, source_id
    sources = {}
    for i in infos:
        pp = PurePosixPath(i.filename)
        if pp.parts[:1] == ("sources",) and not i.is_dir():
            if len(pp.parts) != 2 or not SOURCE_RE.fullmatch(pp.name):
                raise BundleError("The archive has a design source with an unexpected name.", pp.name[:80])
            text = z.read(i).decode("utf-8", errors="strict").replace("\r\n", "\n")   # written on Windows: CRLF on disk
            if source_id(text)[len(SOURCE_PREFIX):] != pp.name.split(".")[0]:
                raise BundleError("A design source in the archive does not match its checksum; nothing was imported.", pp.name)
            sources[pp.name] = text
    needed = {r.get("recipe") or p.get("recipe") for r in p["revisions"]} | {p.get("recipe")}
    for rid in needed:
        if str(rid).startswith((SOURCE_PREFIX, SCAD_PREFIX)):
            stem = str(rid).split(":", 1)[1]
            fname = stem + (".scad" if str(rid).startswith(SCAD_PREFIX) else ".py")
            if fname not in sources and not (st.sources / fname).is_file():
                raise BundleError("The archive is missing the code one of its revisions was built from.", fname)
        elif rid not in st.recipes:
            raise BundleError(f"The design uses a recipe this Form Studio does not have: {rid}.", "Update Form Studio and try again.")

    # conversations: validated before anything is written
    convs: dict[str, dict] = {}
    for i in infos:
        pp = PurePosixPath(i.filename)
        if pp.parts[:1] == ("conversations",) and not i.is_dir():
            if len(pp.parts) < 3 or not CID_RE.fullmatch(pp.parts[1]):
                raise BundleError("The archive has a conversation with an unexpected name.", i.filename[:120])
            rest = pp.parts[2:]
            if not (rest in (("meta.json",), ("events.jsonl",)) or (rest[0] == "files" and len(rest) == 2)):
                raise BundleError("The archive has an unexpected file in a conversation.", i.filename[:120])
            convs.setdefault(pp.parts[1], {})["/".join(rest)] = i
    for cid, files in convs.items():
        if "meta.json" not in files:
            raise BundleError("A conversation in the archive has no meta.json.", cid)

    # write: sources, then the project under a free id, then the conversations under free ids
    st.sources.mkdir(parents=True, exist_ok=True)
    for fname, text in sources.items():
        f = st.sources / fname
        if not f.exists():
            f.write_text(text, encoding="utf-8")
    want = slugify(str(p.get("id") or p.get("name") or "project"))
    pid = _free(st.root, want)
    dest = st.root / pid
    dest.mkdir(parents=True)
    try:
        for i in infos:
            pp = PurePosixPath(i.filename)
            if pp.parts[:1] != ("project",) or i.is_dir() or len(pp.parts) < 2:
                continue
            target = (dest / Path(*pp.parts[1:])).resolve()
            if not target.is_relative_to(dest.resolve()):
                raise BundleError("The archive contains an unsafe path and was not imported.")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(i))
        p["id"] = pid
        st.save(p)
        p = st.load(pid)
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    from .conversations import Conversations, _now
    store = Conversations(st.root)
    store.root.mkdir(parents=True, exist_ok=True)
    made = []
    for cid, files in convs.items():
        meta = json.loads(z.read(files["meta.json"]))
        new = cid if not (store.root / cid).exists() else uuid.uuid4().hex[:12]
        cd = store.root / new
        cd.mkdir(parents=True)
        for rel, info in files.items():
            if rel == "meta.json":
                continue
            target = cd / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
        if not (cd / "events.jsonl").exists():
            (cd / "events.jsonl").write_text("", encoding="utf-8")
        meta.update({"id": new, "project": pid, "running": False, "imported": _now()})
        meta.pop("state", None)
        (cd / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
        made.append({"id": new, "title": meta.get("title", ""), "renamed_from": cid if new != cid else None})
    p.setdefault("decisions", []).append({"ts": time.time(), "rev": p["head"], "kind": "note",
                                          "text": f"Imported from a Form Studio archive exported {man.get('exported', '')} by version {man.get('app', '?')}."})
    st.save(p)
    original = str((man.get("project") or {}).get("id") or want)
    return {"id": pid, "name": p["name"], "renamed_from": original if pid != original else None,
            "conversations": made, "format": "formstudio"}


def import_file(st, path: Path) -> dict:
    path = Path(path).expanduser()
    if path.suffix.lower() == ".json":
        return {"conversation": import_conversation(st, json.loads(path.read_text(encoding="utf-8")))}
    return import_bytes(st, path.read_bytes())


# ---- conversations alone --------------------------------------------------------------------------------------

def conversation_json(root, cid: str) -> dict:
    from .conversations import Conversations
    store = Conversations(root)
    meta = store.meta(cid)
    return {"format": CONV_FORMAT, "app": _version(), "exported": _iso(), "meta": meta, "ancestry": store.ancestry(cid),
            "events": store.events(cid)}


def conversation_markdown(root, cid: str) -> str:
    from .conversations import Conversations
    store = Conversations(root)
    m = store.meta(cid)
    lines = [f"# {m.get('title') or 'Conversation'}", ""]
    facts = [f"Exported from Form Studio {_version()} on {_iso()}"]
    if m.get("project"):
        facts.append(f"design `{m['project']}`")
    if m.get("agent"):
        facts.append(f"agent {m['agent']}" + (f" ({m.get('resolved_model') or m.get('model')})" if m.get("model") else ""))
    lines += ["_" + " · ".join(facts) + "_", ""]
    anc = store.ancestry(cid)
    if anc["ancestors"] or anc["branches"]:
        def named(r):
            return f"“{r['title']}”" if r.get("title") else "a conversation that is no longer here" if r.get("missing") else "an untitled conversation"

        def at(r):
            return (f" after event {r['fork_event'] + 1}" if isinstance(r.get("fork_event"), int) else "") + (f" ({r['fork_reason']})" if r.get("fork_reason") else "")
        lines += ["**Thread**", ""]
        for n, r in enumerate(anc["ancestors"]):
            lines.append(f"- Started as {named(r)} (`{r['id']}`)" if n == 0 else f"- Branched into {named(r)} (`{r['id']}`){at(r)}")
        if anc["ancestors"]:
            lines.append(f"- This conversation branched from {named(anc['ancestors'][-1])}{at(anc)}")
        for r in anc["branches"]:
            lines.append(f"- Branch from here: {named(r)} (`{r['id']}`){at(r)}")
        lines.append("")
    tools = 0
    for ev in store.events(cid):
        t = ev.get("t")
        if t != "tool" and tools:
            lines += [f"_{tools} tool call{'s' if tools > 1 else ''}_", ""]
            tools = 0
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(ev.get("ts") or 0))
        if t == "user":
            lines += [f"## You · {when}", "", str(ev.get("text", "")).strip(), ""]
            if ev.get("attachments"):
                lines += ["Attached: " + ", ".join(str(a.get("name", a)) if isinstance(a, dict) else str(a) for a in ev["attachments"]), ""]
        elif t == "text":
            lines += [f"## {m.get('agent') or 'Agent'} · {when}", "", str(ev.get("text", "")).strip(), ""]
        elif t == "tool":
            tools += 1
        elif t == "act":
            lines += [f"> {ev.get('by', '')}: {ev.get('text', '')}", ""]
        elif t == "error":
            lines += [f"> Error: {ev.get('text', '')}", ""]
        elif t == "end" and ev.get("cost_usd") is not None:
            lines += [f"_Reply cost ${float(ev['cost_usd']):.2f} on the agent account._", ""]
    if tools:
        lines += [f"_{tools} tool call{'s' if tools > 1 else ''}_", ""]
    return "\n".join(lines).rstrip() + "\n"


def import_conversation(st, doc: dict) -> dict:
    """A conversation exported as JSON becomes a new conversation (new id). Its design link is kept when that design
    is here; otherwise it is remembered as project_was."""
    from .conversations import EVENT_KINDS, Conversations, _now
    if not isinstance(doc, dict) or doc.get("format") != CONV_FORMAT or not isinstance(doc.get("events"), list):
        raise BundleError("That file is not a conversation exported from Form Studio.", "Export one with Export conversation (JSON).")
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    events = [e for e in doc["events"] if isinstance(e, dict) and e.get("t") in EVENT_KINDS]
    store = Conversations(st.root)
    proj = meta.get("project")
    linked = proj if isinstance(proj, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", proj) and (st.root / proj / "project.json").exists() else None
    m = store.create(linked, str(meta.get("agent") or "claude"), str(meta.get("model") or "default"), str(meta.get("effort") or ""),
                     str(meta.get("title") or "Imported conversation"))
    with open(store.dir(m["id"]) / "events.jsonl", "w", encoding="utf-8") as fh:
        for e in events:
            e = {k: v for k, v in e.items() if k != "attachments"}         # attachment files are not in a JSON export
            fh.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
    users = [e for e in events if e["t"] == "user"]
    upd = {"events": len(events), "messages": len(users), "title_auto": False, "imported": _now(),
           "preview": re.sub(r"\s+", " ", str((users[-1] if users else {}).get("text", "")))[:140],
           "cost_usd": float(meta.get("cost_usd") or 0.0)}
    if proj and not linked:
        upd["project_was"] = {"id": str(proj)[:60], "name": str((meta.get("project_was") or {}).get("name") or proj)[:80]}
    return store.update(m["id"], **upd)


# ---- command line ---------------------------------------------------------------------------------------------

def main_export(argv=None) -> int:
    import argparse
    from . import config
    from .studio import Studio, StudioError
    ap = argparse.ArgumentParser(prog="form export", description="Export a project, its conversations and its design code as one .formstudio file.")
    ap.add_argument("project")
    ap.add_argument("--out", help="where to write it (default: <data folder>/<project>.formstudio)")
    ap.add_argument("--no-conversations", action="store_true")
    a = ap.parse_args(argv)
    st = Studio(config.load())
    try:
        f = export_project(st, a.project, Path(a.out).expanduser() if a.out else None, not a.no_conversations)
        print(json.dumps({"file": str(f), "bytes": f.stat().st_size}, indent=1))
        return 0
    except (StudioError, BundleError) as e:
        print(json.dumps({"error": e.public()}, ensure_ascii=False))
        return 2
    finally:
        st.kernel.stop()


def main_import(argv=None) -> int:
    import argparse
    from . import config
    from .studio import Studio, StudioError
    ap = argparse.ArgumentParser(prog="form import", description="Import a .formstudio or .formproj archive, or a conversation .json.")
    ap.add_argument("file")
    a = ap.parse_args(argv)
    st = Studio(config.load())
    try:
        print(json.dumps(import_file(st, Path(a.file)), indent=1, ensure_ascii=False, default=str))
        return 0
    except (StudioError, BundleError, OSError, ValueError) as e:
        print(json.dumps({"error": e.public() if hasattr(e, "public") else {"message": str(e)}}, ensure_ascii=False))
        return 2
    finally:
        st.kernel.stop()


def main_export_conversation(argv=None) -> int:
    import argparse
    from . import config
    from .conversations import ConversationError
    ap = argparse.ArgumentParser(prog="form export-conversation", description="A conversation as Markdown or JSON.")
    ap.add_argument("conversation")
    ap.add_argument("--format", default="md", choices=["md", "json"])
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    root = config.load()["data"]["dir"]
    try:
        text = conversation_markdown(root, a.conversation) if a.format == "md" else \
            json.dumps(conversation_json(root, a.conversation), indent=1, ensure_ascii=False, default=str)
    except ConversationError as e:
        print(json.dumps({"error": {"message": str(e)}}))
        return 2
    if a.out:
        Path(a.out).expanduser().write_text(text, encoding="utf-8")
        print(json.dumps({"file": str(Path(a.out).expanduser())}))
    else:
        print(text)
    return 0
