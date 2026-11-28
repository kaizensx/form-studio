"""Backups of every design and conversation, on a schedule, to a folder you pick and optionally a Git repo you own.

A backup is one file, ``form-backup-<UTC time>.zip``:

    MANIFEST.json            {"format": "form-studio-backup/1", "app", "made", "projects": [{id, name}],
                              "conversations": n, "files": {path: {"sha256", "size"}}}
    projects/<id>/…          each project folder as it is on disk (built outputs too, unless [backup] built = false)
    conversations/<id>/…     each conversation: meta.json, events.jsonl, files/ (the reference leaves chats out)
    sources/<sha>.py|.scad   the code every revision designed as code was built from

Nothing is changed on the way: a restore writes back the same bytes, and verify() reads every file of a backup and
checks it against the SHA-256 in its manifest. Backups are written beside the old ones as a .part file and renamed
when complete, then the oldest are removed down to [backup] keep. Only files named form-backup-*.zip with a manifest
are ever removed; nothing else in the folder is touched.

A Git destination is optional: the address of a repository the person created and owns. Form Studio clones it into
<data>/.backup/git/, writes the same tree (without built outputs, which are made again from the revisions), commits and
pushes with the person's own Git and its credentials (SSH keys, a credential helper). It never creates a repository,
never asks for or stores a password, refuses an address with a password in it, and never prompts: a push that needs a
login fails and says so. Nothing leaves the computer unless the folder or the repository does.

Recently deleted: a deleted design is moved to <data>/.trash (Studio.delete_project) and listed here for 30 days, with
the days left and whether a verified backup holds it. It can be put back with its conversations re-attached. After 30
days an entry is removed from the bin only when a verified backup in the backup folder holds the same project;
otherwise it stays, and the listing says why.

The schedule runs in the app's engine (start_scheduler): [backup] enabled, every = hourly | daily | weekly. A machine
without the app open can run `form backup run --if-due` from its own scheduler.

    form backup status | run [--if-due] | list | verify [FILE] | restore FILE [--project ID ...] [--replace]
    form backup deleted | undelete ENTRY | purge
"""
from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath

FORMAT = "form-studio-backup/1"
PREFIX = "form-backup-"
NAME_RE = re.compile(r"form-backup-(\d{8}T\d{6}Z)(?:-\d+)?\.zip")
EVERY = {"hourly": 3600, "daily": 86400, "weekly": 7 * 86400}
BIN_DAYS = 30
SKIP_SUFFIX = (".tmp", ".part", ".running")
CHECK_S = 600                      # the scheduler looks this often
GIT_TIMEOUT = 600
DEFAULTS = {"enabled": False, "every": "daily", "folder": "", "keep": 10, "conversations": True, "built": True,
            "git_remote": "", "git_branch": "main"}
_RUN = threading.Lock()


class BackupError(Exception):
    def __init__(self, message: str, hint: str = "", status: int = 400):
        super().__init__(message)
        self.message, self.hint, self.status = message, hint, status

    def public(self) -> dict:
        return {"message": self.message, "hint": self.hint}


def _studio_error(e: BackupError):
    from .studio import StudioError
    return StudioError(e.message, e.hint, status=e.status)


def settings(cfg: dict) -> dict:
    s = {**DEFAULTS, **(cfg.get("backup") or {})}
    s["every"] = s["every"] if s["every"] in EVERY else "daily"
    try:
        s["keep"] = max(1, min(365, int(s["keep"])))
    except (TypeError, ValueError):
        s["keep"] = DEFAULTS["keep"]
    return s


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _state_path(root: Path) -> Path:
    return Path(root) / ".backup" / "state.json"


def _state(root: Path) -> dict:
    try:
        return json.loads(_state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"history": []}


def _save_state(root: Path, s: dict) -> None:
    from . import fsutil
    p = _state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"state.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(s, indent=1), encoding="utf-8")
    fsutil.replace(tmp, p)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- what is backed up -----------------------------------------------------------------------------------------------
def folder_of(cfg: dict, root: Path) -> Path | None:
    """The backup folder, checked: never inside the project folder (a backup must not back itself up)."""
    f = str(settings(cfg)["folder"] or "").strip()
    if not f:
        return None
    path = Path(f).expanduser()
    if not path.is_absolute():
        raise BackupError("The backup folder needs a full path.", "Choose it in Settings › Backups.")
    r = Path(root).resolve()
    rp = path.resolve()
    if rp == r or rp.is_relative_to(r):
        raise BackupError("The backup folder is inside the project folder.",
                          "Choose a folder outside it: another drive or a synced folder.")
    if r.is_relative_to(rp):
        raise BackupError("The project folder is inside the backup folder.", "Choose a folder of its own for backups.")
    return path


def _files(root: Path, conversations: bool = True, built: bool = True) -> list[tuple[str, Path]]:
    """(path in the backup, file on disk) for every file that is backed up, in a stable order."""
    root = Path(root)
    out = []
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if d.name.startswith(".") or not d.is_dir() or not (d / "project.json").exists():
            continue
        for f in sorted(d.rglob("*")):
            rel = f.relative_to(d)
            if not f.is_file() or f.is_symlink() or f.name.endswith(SKIP_SUFFIX):
                continue
            if not built and rel.parts[0] == "artifacts":
                continue
            out.append((f"projects/{d.name}/{rel.as_posix()}", f))
    src = root / ".sources"
    if src.is_dir():
        for f in sorted(src.iterdir()):
            if f.is_file() and not f.is_symlink() and re.fullmatch(r"[0-9a-f]{16}\.(py|scad)", f.name):
                out.append((f"sources/{f.name}", f))
    conv = root / ".conversations"
    if conversations and conv.is_dir():
        for d in sorted(conv.iterdir()):
            if not d.is_dir() or not re.fullmatch(r"[0-9a-f]{12}", d.name):
                continue
            for f in sorted(d.rglob("*")):
                if f.is_file() and not f.is_symlink() and not f.name.endswith(SKIP_SUFFIX):
                    out.append((f"conversations/{d.name}/{f.relative_to(d).as_posix()}", f))
    return out


def _projects(root: Path) -> list:
    out = []
    for d in sorted(Path(root).iterdir()) if Path(root).is_dir() else []:
        if d.is_dir() and not d.name.startswith(".") and (d / "project.json").exists():
            try:
                name = json.loads((d / "project.json").read_text(encoding="utf-8")).get("name") or d.name
            except (OSError, ValueError):
                name = d.name
            out.append({"id": d.name, "name": name})
    return out


# ---- making a backup -------------------------------------------------------------------------------------------------
def snapshot(st, out_dir: Path, conversations: bool = True, built: bool = True, now: float | None = None) -> dict:
    """Write one backup file into out_dir. Each project is read under its lock so no half-written revision is taken."""
    now = now or time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(now))
    name, i = f"{PREFIX}{stamp}.zip", 2
    while (out_dir / name).exists():
        name, i = f"{PREFIX}{stamp}-{i}.zip", i + 1
    dest = out_dir / name
    part = dest.with_name(dest.name + ".part")
    files = _files(st.root, conversations, built)
    manifest = {"format": FORMAT, "app": _version(), "made": _iso(now), "projects": _projects(st.root),
                "conversations": len({p.split("/")[1] for p, _ in files if p.startswith("conversations/")}),
                "built_outputs": bool(built), "files": {}}
    by_project: dict[str, list] = {}
    rest = []
    for arc, f in files:
        if arc.startswith("projects/"):
            by_project.setdefault(arc.split("/")[1], []).append((arc, f))
        else:
            rest.append((arc, f))
    try:
        with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            def put(arc, f):
                try:
                    data = f.read_bytes()
                except OSError:
                    return                                   # removed while the backup ran: not in this backup
                z.writestr(zipfile.ZipInfo(arc, date_time=time.gmtime(f.stat().st_mtime)[:6]), data, zipfile.ZIP_DEFLATED)
                manifest["files"][arc] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            for pid, items in by_project.items():
                with st.lock(pid):
                    for arc, f in items:
                        put(arc, f)
            for arc, f in rest:
                put(arc, f)
            z.writestr("MANIFEST.json", json.dumps(manifest, indent=1, ensure_ascii=False))
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    return {"file": str(dest), "name": dest.name, "bytes": dest.stat().st_size, "files": len(manifest["files"]),
            "projects": len(manifest["projects"]), "conversations": manifest["conversations"], "made": manifest["made"]}


def _version() -> str:
    from . import __version__
    return __version__


def backups(folder: Path) -> list:
    """The backups in a folder, newest first (only form-backup-*.zip files; nothing else is listed or touched)."""
    folder = Path(folder)
    out = []
    if not folder.is_dir():
        return out
    for f in folder.iterdir():
        m = NAME_RE.fullmatch(f.name)
        if m and f.is_file():
            st = f.stat()
            out.append({"name": f.name, "file": str(f), "bytes": st.st_size, "stamp": m.group(1), "mtime": st.st_mtime})
    return sorted(out, key=lambda x: (x["stamp"], x["name"]), reverse=True)


def prune(folder: Path, keep: int) -> list:
    """Remove the oldest backups beyond keep. Returns the names removed. Only valid backup files are removed."""
    removed = []
    for b in backups(folder)[max(1, int(keep)):]:
        try:
            with zipfile.ZipFile(b["file"]) as z:
                if json.loads(z.read("MANIFEST.json")).get("format") != FORMAT:
                    continue
        except (zipfile.BadZipFile, KeyError, ValueError, OSError):
            continue                                         # not ours, or damaged: never removed here
        Path(b["file"]).unlink(missing_ok=True)
        removed.append(b["name"])
    return removed


# ---- reading a backup: a .zip, or a folder holding MANIFEST.json (a Git work tree) ------------------------------------
class _Source:
    def __init__(self, path: Path):
        self.path = Path(path).expanduser()
        self.zip = None
        if self.path.is_file():
            try:
                self.zip = zipfile.ZipFile(self.path)
            except zipfile.BadZipFile:
                raise BackupError("That file is not a Form Studio backup.", str(self.path)) from None
        elif not (self.path / "MANIFEST.json").is_file():
            raise BackupError("No backup there.", f"{self.path} is neither a backup file nor a folder with MANIFEST.json.", 404)
        try:
            self.manifest = json.loads(self.read("MANIFEST.json"))
        except (KeyError, OSError, ValueError):
            raise BackupError("The backup has no readable manifest.", str(self.path)) from None
        if not isinstance(self.manifest, dict) or self.manifest.get("format") != FORMAT:
            raise BackupError("This backup was made by a version of Form Studio this one does not read.", str(self.path))

    def read(self, arc: str) -> bytes:
        _safe(arc)
        if self.zip is not None:
            return self.zip.read(arc)
        return (self.path / arc).read_bytes()

    def close(self):
        if self.zip is not None:
            self.zip.close()


def _safe(arc: str) -> PurePosixPath:
    if "\\" in arc or arc.startswith("/") or re.match(r"^[A-Za-z]:", arc) or "\x00" in arc:
        raise BackupError("The backup holds an unsafe path; nothing was restored.", arc[:120])
    pp = PurePosixPath(arc)
    if ".." in pp.parts or not pp.parts:
        raise BackupError("The backup holds an unsafe path; nothing was restored.", arc[:120])
    if pp.parts[0] not in ("projects", "conversations", "sources", "MANIFEST.json"):
        raise BackupError("The backup holds a file outside its folders; nothing was restored.", arc[:120])
    return pp


def verify(path: Path) -> dict:
    """Read every file of a backup and compare it with the SHA-256 and size in its manifest."""
    src = _Source(path)
    try:
        bad, missing = [], []
        files = src.manifest.get("files") or {}
        for arc, meta in files.items():
            try:
                data = src.read(arc)
            except (KeyError, OSError):
                missing.append(arc)
                continue
            if len(data) != meta.get("size") or hashlib.sha256(data).hexdigest() != meta.get("sha256"):
                bad.append(arc)
        extra = []
        if src.zip is not None:
            names = {i.filename for i in src.zip.infolist() if not i.is_dir()}
            extra = sorted(names - set(files) - {"MANIFEST.json"})
        ok = not bad and not missing and not extra
        return {"ok": ok, "file": str(src.path), "checked": len(files), "damaged": bad, "missing": missing, "extra": extra,
                "projects": src.manifest.get("projects") or [], "made": src.manifest.get("made"),
                "evidence": "SHA-256 of every file against the manifest"}
    finally:
        src.close()


# ---- restoring ---------------------------------------------------------------------------------------------------------
def restore(st, path: Path, projects: list | None = None, replace: bool = False, conversations: bool = True) -> dict:
    """Write a backup's designs (all, or the ids given), their sources and the conversations back into the data folder.
    A design that exists is skipped, or with replace=True moved to Recently deleted first. Checked before writing."""
    v = verify(path)
    if not v["ok"]:
        raise BackupError("The backup does not match its manifest; nothing was restored.",
                          f"{len(v['damaged'])} damaged, {len(v['missing'])} missing, {len(v['extra'])} unexpected files.", 409)
    src = _Source(path)
    try:
        files = src.manifest["files"]
        want = set(projects) if projects else {p["id"] for p in src.manifest.get("projects") or []}
        known = {p["id"] for p in src.manifest.get("projects") or []}
        unknown = sorted(want - known)
        if unknown:
            raise BackupError("Not in this backup: " + ", ".join(unknown) + ".", "backup list names what each holds.", 404)
        root = Path(st.root)
        restored, skipped, moved, reattach = [], [], [], []
        for pid in sorted(want):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", pid):
                raise BackupError("The backup names a design with an unsafe id.", pid[:80])
            dest = root / pid
            if dest.exists():
                if not replace:
                    skipped.append({"id": pid, "why": "a design with this id exists; restore with replace to put the "
                                                     "backup's copy in its place (the current one goes to Recently deleted)"})
                    continue
                moved.append(st.delete_project(pid)["trash"])
            tmp = root / f".{pid}.restore"
            shutil.rmtree(tmp, ignore_errors=True)
            n = 0
            for arc in files:
                pp = PurePosixPath(arc)
                if pp.parts[:2] == ("projects", pid):
                    target = tmp / Path(*pp.parts[2:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(src.read(arc))
                    n += 1
            os.replace(tmp, dest)
            restored.append({"id": pid, "files": n})
            reattach.append(pid)
        sources = 0
        (root / ".sources").mkdir(parents=True, exist_ok=True)
        for arc in files:
            pp = PurePosixPath(arc)
            if pp.parts[0] == "sources" and not (root / ".sources" / pp.name).exists():
                (root / ".sources" / pp.name).write_bytes(src.read(arc))
                sources += 1
        convs_done, convs_kept = [], []
        if conversations:
            cids = sorted({PurePosixPath(a).parts[1] for a in files if a.startswith("conversations/")})
            croot = root / ".conversations"
            for cid in cids:
                if not re.fullmatch(r"[0-9a-f]{12}", cid):
                    continue
                if (croot / cid).exists():
                    convs_kept.append(cid)
                    continue
                for arc in files:
                    pp = PurePosixPath(arc)
                    if pp.parts[:2] == ("conversations", cid):
                        target = croot / cid / Path(*pp.parts[2:])
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(src.read(arc))
                convs_done.append(cid)
        for pid in reattach:                                 # conversations a replace detached point at it again
            _reattach(st, pid, pid)
        try:
            st._layers_cache.clear()
        except AttributeError:
            pass
        return {"restored": restored, "skipped": skipped, "moved_to_recently_deleted": moved, "sources": sources,
                "conversations": convs_done, "conversations_already_here": convs_kept, "from": str(src.path),
                "verified": v["checked"]}
    finally:
        src.close()


# ---- Git ---------------------------------------------------------------------------------------------------------------
def check_remote(url: str) -> str:
    u = (url or "").strip()
    if not u:
        raise BackupError("No Git repository is set.", "Settings › Backups: the address of a private repository you created.")
    if u.startswith("-") or any(c in u for c in "\n\r\t ") or "\x00" in u:
        raise BackupError("That is not a repository address.", u[:120])
    if re.match(r"^[a-z][a-z0-9+.-]*://[^/@]*:[^/@]*@", u, re.I):
        raise BackupError("The address has a password or token in it.",
                          "Use the plain address. Git signs in with your SSH key or credential helper; Form Studio never "
                          "stores a password.")
    return u


def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"                     # never ask: a push that needs a login fails and says so
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return env


def _git(args: list, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    exe = shutil.which("git")
    if not exe:
        raise BackupError("Git is not installed.", "Install Git to back up to a repository, or use the folder alone.")
    r = subprocess.run([exe, *args], cwd=str(cwd) if cwd else None, env=_git_env(), capture_output=True, text=True,
                       timeout=GIT_TIMEOUT)
    if check and r.returncode != 0:
        msg = (r.stderr or r.stdout or "").strip().splitlines()
        raise BackupError(f"git {args[0]} failed: " + (msg[-1] if msg else f"exit {r.returncode}"),
                          "Check that the repository exists, that it is yours, and that `git push` works for it from a "
                          "terminal. Form Studio never creates a repository.", 502)
    return r


def git_dir(root: Path, url: str) -> Path:
    return Path(root) / ".backup" / "git" / hashlib.sha1(url.encode()).hexdigest()[:12]


def push_git(st, url: str, branch: str = "main", conversations: bool = True, now: float | None = None) -> dict:
    """Write the backup tree (no built outputs) into a clone of the person's repository, commit and push."""
    url = check_remote(url)
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", branch or "") or branch.startswith(("-", "/")) or ".." in branch:
        raise BackupError("That is not a branch name.", branch[:60])
    now = now or time.time()
    work = git_dir(st.root, url)
    if not (work / ".git").is_dir():
        shutil.rmtree(work, ignore_errors=True)
        work.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--quiet", "--", url, str(work)])
    has_branch = _git(["ls-remote", "--heads", "origin", branch], cwd=work).stdout.strip() != ""
    if has_branch:
        _git(["fetch", "--quiet", "origin", branch], cwd=work)
        _git(["checkout", "--quiet", "-B", branch, f"origin/{branch}"], cwd=work)
    else:
        _git(["checkout", "--quiet", "--orphan", branch], cwd=work, check=False)
    # the tree: exactly what a folder backup holds, without built outputs
    try:
        before = json.loads((work / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        before = {}
    for child in work.iterdir():
        if child.name == ".git":
            continue
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    files = _files(st.root, conversations, built=False)
    manifest = {"format": FORMAT, "app": _version(), "made": _iso(now), "projects": _projects(st.root),
                "conversations": len({p.split("/")[1] for p, _ in files if p.startswith("conversations/")}),
                "built_outputs": False, "files": {}}
    for arc, f in files:
        try:
            data = f.read_bytes()
        except OSError:
            continue
        target = work / arc
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest["files"][arc] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    if before.get("files") == manifest["files"] and before.get("projects") == manifest["projects"]:
        manifest = before                                   # nothing changed: no new commit for a new time stamp
    (work / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    (work / ".gitattributes").write_text("* -text\n", encoding="utf-8")      # bytes in, the same bytes out
    _git(["add", "-A"], cwd=work)
    changed = _git(["status", "--porcelain"], cwd=work).stdout.strip() != ""
    commit = None
    if changed:
        ident = []
        if not _git(["config", "user.email"], cwd=work, check=False).stdout.strip():
            ident = ["-c", "user.name=Form Studio backup", "-c", "user.email=backup@form-studio.invalid"]
        _git(ident + ["commit", "--quiet", "-m", f"Form Studio backup {_iso(now)}"], cwd=work)
        commit = _git(["rev-parse", "HEAD"], cwd=work).stdout.strip()
    if changed or not has_branch:
        _git(["push", "--quiet", "origin", f"HEAD:refs/heads/{branch}"], cwd=work)
    return {"remote": url, "branch": branch, "commit": commit, "changed": changed, "files": len(manifest["files"]),
            "work_tree": str(work)}


# ---- one run, the schedule ---------------------------------------------------------------------------------------------
def run(st, cfg: dict | None = None, reason: str = "by hand") -> dict:
    """Back up now to the folder (and the repository when one is set), verify, prune, tidy the bin. One at a time."""
    cfg = cfg or st.cfg
    s = settings(cfg)
    folder = folder_of(cfg, st.root)
    if folder is None and not s["git_remote"]:
        raise BackupError("No backup destination is set.", "Settings › Backups: choose a folder (and optionally a Git repository).")
    if not _RUN.acquire(blocking=False):
        raise BackupError("A backup is already running.", "Wait for it to finish.", 409)
    t0 = time.time()
    out = {"ts": t0, "reason": reason, "ok": False}
    try:
        if folder is not None:
            made = snapshot(st, folder, s["conversations"], s["built"], now=t0)
            v = verify(Path(made["file"]))
            made["verified"] = v["ok"]
            if not v["ok"]:
                raise BackupError("The backup just written does not read back as written.",
                                  f"{made['file']}: {len(v['damaged'])} damaged, {len(v['missing'])} missing.", 500)
            made["pruned"] = prune(folder, s["keep"])
            out["folder"] = made
        if s["git_remote"]:
            out["git"] = push_git(st, s["git_remote"], s["git_branch"] or "main", s["conversations"], now=t0)
        try:
            out["bin"] = purge_expired(st, cfg)
        except (OSError, BackupError) as e:                  # the backup is made either way; the bin waits
            out["bin"] = {"error": str(e)}
        out["ok"] = True
        return out
    except BackupError as e:
        out["error"] = e.public()
        raise
    except Exception as e:                                   # noqa: BLE001 - said in the status, then raised
        out["error"] = {"message": f"{type(e).__name__}: {e}", "hint": ""}
        raise
    finally:
        out["seconds"] = round(time.time() - t0, 2)
        stt = _state(st.root)
        stt["last"] = out
        if out.get("ok"):
            stt["last_ok"] = out
        stt["history"] = ([{k: out.get(k) for k in ("ts", "ok", "reason", "seconds")} | {
            "file": (out.get("folder") or {}).get("name"), "commit": (out.get("git") or {}).get("commit"),
            "error": (out.get("error") or {}).get("message")}] + (stt.get("history") or []))[:50]
        try:
            _save_state(st.root, stt)
        except OSError:
            pass
        _RUN.release()


def due(st, cfg: dict, now: float | None = None) -> bool:
    s = settings(cfg)
    if not s["enabled"] or (not s["folder"] and not s["git_remote"]):
        return False
    last = (_state(st.root).get("last_ok") or {}).get("ts") or 0
    return (now or time.time()) - last >= EVERY[s["every"]]


def start_scheduler(st) -> threading.Thread | None:
    """Back up on the schedule while the engine runs (the app, `form serve`). FORM_NO_BACKUP_SCHEDULE=1 turns it off."""
    if os.environ.get("FORM_NO_BACKUP_SCHEDULE", "").strip() in ("1", "true", "yes"):
        return None

    def loop():
        time.sleep(90)                                       # let the app open first
        while True:
            try:
                from . import config
                cfg = config.load()
                if due(st, cfg):
                    try:
                        run(st, cfg, reason="scheduled")
                        st.activity(None, "project", "Backed up every design and conversation.", by="Form Studio")
                    except BackupError as e:
                        st.activity(None, "warning", f"The scheduled backup did not run: {e.message}", by="Form Studio")
            except Exception:                                # noqa: BLE001 - the schedule never takes the engine down
                pass
            time.sleep(CHECK_S)
    t = threading.Thread(target=loop, daemon=True, name="form-backup")
    t.start()
    return t


# ---- recently deleted --------------------------------------------------------------------------------------------------
_TRASH_RE = re.compile(r"(.+)-(\d{8}T\d{6}Z)(?:-\d+)?")


def _held_by_backup(cfg, root, pid: str, pj_sha: str) -> str | None:
    """The newest backup in the folder whose copy of the design has this project.json (by SHA-256)."""
    try:
        folder = folder_of(cfg, root)
    except BackupError:
        return None
    if folder is None:
        return None
    for b in backups(folder):
        try:
            with zipfile.ZipFile(b["file"]) as z:
                m = json.loads(z.read("MANIFEST.json"))
        except (zipfile.BadZipFile, KeyError, ValueError, OSError):
            continue
        if ((m.get("files") or {}).get(f"projects/{pid}/project.json") or {}).get("sha256") == pj_sha:
            return b["name"]
    return None


def deleted(st, cfg: dict | None = None, now: float | None = None) -> list:
    """Designs in Recently deleted: name, when, days left of the 30, and whether a backup holds them."""
    cfg = cfg or st.cfg
    now = now or time.time()
    trash = Path(st.root) / ".trash"
    out = []
    if not trash.is_dir():
        return out
    for d in sorted(trash.iterdir()):
        m = _TRASH_RE.fullmatch(d.name)
        if not d.is_dir() or not m or not (d / "project.json").is_file():
            continue
        try:
            when = float(calendar.timegm(time.strptime(m.group(2), "%Y%m%dT%H%M%SZ")))
        except ValueError:
            continue
        try:
            pj = (d / "project.json").read_bytes()
            name = json.loads(pj).get("name") or m.group(1)
        except (OSError, ValueError):
            pj, name = b"", m.group(1)
        age = (now - when) / 86400
        held = _held_by_backup(cfg, st.root, m.group(1), hashlib.sha256(pj).hexdigest()) if pj else None
        out.append({"entry": d.name, "id": m.group(1), "name": name, "deleted": _iso(when), "deleted_ts": when,
                    "days_left": max(0, int(BIN_DAYS - age + 0.999)), "expired": age >= BIN_DAYS, "backup": held})
    return sorted(out, key=lambda x: -x["deleted_ts"])


def _reattach(st, old: str, pid: str) -> int:
    """Conversations detached when a design was deleted point at it again (Studio.delete_project detached them)."""
    n = 0
    from .conversations import Conversations
    store = Conversations(st.root)
    try:
        for meta in store.list(limit=100000):
            was = meta.get("project_was") or {}
            designs = meta.get("designs") or []
            hit = False
            for e in designs:
                if e.get("project") == old and e.get("state") == "trashed":
                    e.pop("state", None)
                    if pid != old:
                        e["project"] = pid
                    hit = True
            if meta.get("project") is None and was.get("id") == old:
                store.update(meta["id"], project=pid, project_was=None, designs=designs)
                n += 1
            elif hit:
                store.update(meta["id"], designs=designs)
    except Exception:                                        # noqa: BLE001 - the design is back either way
        pass
    return n


def undelete(st, entry: str) -> dict:
    """Put a deleted design back, under its own id when it is free, and re-attach its conversations."""
    if not _TRASH_RE.fullmatch(entry or "") or "/" in entry or "\\" in entry:
        raise BackupError("Not an entry of Recently deleted.", "backup deleted lists them.", 404)
    src = Path(st.root) / ".trash" / entry
    if not (src / "project.json").is_file():
        raise BackupError("Not an entry of Recently deleted.", "backup deleted lists them.", 404)
    old = _TRASH_RE.fullmatch(entry).group(1)
    pid, i = old, 2
    while (Path(st.root) / pid).exists():
        pid, i = f"{old}-{i}", i + 1
    shutil.move(str(src), str(Path(st.root) / pid))
    if pid != old:
        with st.lock(pid):
            p = st.load(pid)
            p["id"] = pid
            st.save(p)
    attached = _reattach(st, old, pid)
    try:
        st._layers_cache.clear()
    except AttributeError:
        pass
    return {"ok": True, "id": pid, "renamed_from": old if pid != old else None, "conversations_reattached": attached}


def purge_expired(st, cfg: dict | None = None, now: float | None = None) -> dict:
    """Remove designs deleted more than 30 days ago, but only those a verified backup in the folder holds."""
    cfg = cfg or st.cfg
    removed, kept = [], []
    for e in deleted(st, cfg, now):
        if not e["expired"]:
            continue
        if not e["backup"]:
            kept.append({"entry": e["entry"], "why": "deleted over 30 days ago, but no backup holds it, so it stays"})
            continue
        v = verify(Path(folder_of(cfg, st.root)) / e["backup"])
        if not v["ok"]:
            kept.append({"entry": e["entry"], "why": f"the backup holding it ({e['backup']}) does not verify"})
            continue
        shutil.rmtree(Path(st.root) / ".trash" / e["entry"])
        removed.append({"entry": e["entry"], "held_by": e["backup"]})
    return {"removed": removed, "kept": kept}


# ---- status --------------------------------------------------------------------------------------------------------------
def status(st, cfg: dict | None = None) -> dict:
    cfg = cfg or st.cfg
    s = settings(cfg)
    stt = _state(st.root)
    try:
        folder = folder_of(cfg, st.root)
        problem = None
    except BackupError as e:
        folder, problem = None, e.public()
    listed = backups(folder) if folder else []
    last_ok = (stt.get("last_ok") or {}).get("ts")
    nxt = (last_ok or 0) + EVERY[s["every"]] if s["enabled"] and (folder or s["git_remote"]) else None
    return {"settings": {k: s[k] for k in DEFAULTS}, "folder": str(folder) if folder else "", "problem": problem,
            "last": stt.get("last"), "last_ok": stt.get("last_ok"), "next": nxt, "due": due(st, cfg),
            "running": _RUN.locked(), "backups": listed[:60], "count": len(listed),
            "bytes": sum(b["bytes"] for b in listed), "deleted": deleted(st, cfg),
            "git_work_tree": str(git_dir(st.root, s["git_remote"])) if s["git_remote"] else "",
            "note": "Nothing leaves this computer unless the backup folder or the Git repository does."}


# ---- engine routes (form/server.py) -------------------------------------------------------------------------------------
def route_get(st, path: str, q: dict):
    if path == "/api/backup":
        return status(st)
    return None


def _file_in_folder(st, name: str) -> Path:
    folder = folder_of(st.cfg, st.root)
    if folder is None or not NAME_RE.fullmatch(name or ""):
        raise BackupError("Not a backup in the backup folder.", "backup list names them.", 404)
    return folder / name


def route_post(st, path: str, body: dict):
    b = body if isinstance(body, dict) else {}
    try:
        if path == "/api/backup/run":
            if _RUN.locked():
                raise BackupError("A backup is already running.", "Wait for it to finish.", 409)

            def go():
                try:
                    run(st, st.cfg, reason="by hand")
                    st.activity(None, "project", "Backed up every design and conversation.", by="you")
                except Exception as e:                       # noqa: BLE001 - said in the activity log and the status
                    st.activity(None, "warning", f"The backup did not finish: {getattr(e, 'message', e)}", by="Form Studio")
            threading.Thread(target=go, daemon=True, name="form-backup-now").start()
            return {"started": True}
        if path == "/api/backup/verify":
            return verify(_file_in_folder(st, b.get("name") or ""))
        if path == "/api/backup/restore":
            return restore(st, _file_in_folder(st, b.get("name") or ""), b.get("projects") or None, bool(b.get("replace")))
        if path == "/api/backup/undelete":
            return undelete(st, b.get("entry") or "")
    except BackupError as e:
        raise _studio_error(e) from None
    return None


# ---- MCP ----------------------------------------------------------------------------------------------------------------
def register_mcp(mcp, get_studio, run_async) -> None:
    from mcp.types import ToolAnnotations
    ann = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)

    async def backup(action: str = "status", file: str | None = None, projects: list[str] | None = None,
                     replace: bool = False, entry: str | None = None) -> dict:
        """Backups of every design and conversation, and Recently deleted. action:
        status (settings, last run, backups in the folder, the bin); run (back up now to the folder and, if set, push
        to the person's own Git repository; then verify and prune); list; verify (file: a backup name, default the
        newest; every file against its SHA-256); restore (file, optional projects=[ids]; an existing design is skipped
        unless replace=True, which moves it to Recently deleted first); deleted (the bin, 30 days, with which backup
        holds each); undelete (entry from deleted). Restore and undelete only when the person asks. Destinations are
        set by the person in Settings › Backups; this tool never creates a repository or changes where backups go."""
        st = get_studio()

        def go():
            try:
                if action == "status":
                    return status(st)
                if action == "run":
                    return run(st, st.cfg, reason="agent")
                if action == "list":
                    f = folder_of(st.cfg, st.root)
                    return {"folder": str(f) if f else "", "backups": backups(f) if f else []}
                if action == "verify":
                    if file:
                        return verify(_file_in_folder(st, file))
                    f = folder_of(st.cfg, st.root)
                    newest = backups(f)[:1] if f else []
                    if not newest:
                        raise BackupError("No backup to verify.", "backup(action=\"run\") makes one.", 404)
                    return verify(Path(newest[0]["file"]))
                if action == "restore":
                    return restore(st, _file_in_folder(st, file or ""), projects, replace)
                if action == "deleted":
                    return {"deleted": deleted(st), "days": BIN_DAYS}
                if action == "undelete":
                    return undelete(st, entry or "")
                raise BackupError(f"Unknown action “{action}”.", "status, run, list, verify, restore, deleted or undelete.")
            except BackupError as e:
                raise _studio_error(e) from None
        return await run_async(go)

    mcp.tool(name="backup", annotations=ann)(backup)


# ---- command line --------------------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog="form backup", description="Backups of every design and conversation, and "
                                 "Recently deleted. Prints JSON.")
    ap.add_argument("action", choices=("status", "run", "list", "verify", "restore", "deleted", "undelete", "purge"))
    ap.add_argument("target", nargs="?", help="verify/restore: a backup file or name; undelete: an entry")
    ap.add_argument("--project", action="append", help="restore: only this design (repeat)")
    ap.add_argument("--replace", action="store_true", help="restore: put the backup's copy in place of an existing design "
                    "(the current one goes to Recently deleted)")
    ap.add_argument("--if-due", action="store_true", help="run: only when the schedule says a backup is due")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    from . import config
    from .studio import Studio
    cfg = config.load()
    st = Studio(cfg)

    def resolve(t):
        if not t:
            f = folder_of(cfg, st.root)
            newest = backups(f)[:1] if f else []
            if not newest:
                raise BackupError("No backup found.", "form backup run makes one.", 404)
            return Path(newest[0]["file"])
        p = Path(t).expanduser()
        if p.exists():
            return p
        return _file_in_folder(st, t)
    try:
        if a.action == "status":
            out = status(st, cfg)
        elif a.action == "run":
            out = {"skipped": "not due"} if a.if_due and not due(st, cfg) else run(st, cfg, reason="command line")
        elif a.action == "list":
            f = folder_of(cfg, st.root)
            out = {"folder": str(f) if f else "", "backups": backups(f) if f else []}
        elif a.action == "verify":
            out = verify(resolve(a.target))
        elif a.action == "restore":
            if not a.target:
                raise BackupError("Name the backup to restore.", "form backup list names them.")
            out = restore(st, resolve(a.target), a.project, a.replace)
        elif a.action == "deleted":
            out = {"deleted": deleted(st, cfg), "days": BIN_DAYS}
        elif a.action == "undelete":
            out = undelete(st, a.target or "")
        else:
            out = purge_expired(st, cfg)
        print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
        return 0 if out.get("ok", True) else 1
    except BackupError as e:
        print(json.dumps({"error": e.public()}, indent=1, ensure_ascii=False))
        return 2
    finally:
        try:
            st.kernel.shutdown()
        except Exception:                                    # noqa: BLE001
            pass
