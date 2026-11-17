"""Everything FORM uses, and how to get it: one registry, driven by the app, the CLI and MCP.

Each entry says what it is, why FORM wants it, whether it is required / recommended / optional, how it is
detected, and the install methods for each operating system in the order they are tried. An install is a
background job: the exact commands are shown first, their output is streamed line by line, the job can be
cancelled, it stops after a timeout, and the item is detected again afterwards. Nothing is ever installed
unless the user asked for that item (a tick and a button in the app, `form install <id>`, or
`install_software(id, confirm=True)` over MCP).

FORM never asks for a password. A method that needs administrator rights (sudo) is listed, skipped, and
explained; the next method is used instead, or the official download page is offered.

    form install --list                 the registry as JSON, with what was found on this computer
    form install <id> [--dry-run]       show the commands, ask, run them, check again
    form install <id> --yes             the same without the question
    form setup --yes                    everything marked recommended, without questions

Development switches (screenshots and tests; they install nothing):
    FORM_INSTALL_FAKE=<seconds>         every install command is replaced by a harmless stand-in that prints
                                        a few lines for that long. The log says so on its first line.
    FORM_SETUP_PRETEND_MISSING=a,b      report these registry ids as not installed (e.g. claude,slicer.bambu)
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

CLAUDE_DOCS = "https://code.claude.com/docs/en/setup"       # the official install page (docs.claude.com redirects here)
PARTS_PINS = ("bd_warehouse==0.4.0", "py_gearworks==0.0.24")  # the same pins as the [parts] extra in pyproject.toml
KERNEL_PIN = "build123d==0.13.0"
DEFAULT_TIMEOUT_S = 1800
LEVELS = ("required", "recommended", "optional")
GROUPS = [("engine", "Form Studio itself"), ("slicer", "Printer and slicer"), ("ai", "Your AI"),
          ("agents", "Other agents"), ("cad", "CAD and 3D apps")]


# ---- model --------------------------------------------------------------------------------------------------------

@dataclass
class Method:
    """One way to install something. kind: command | action | open | bundled."""
    id: str
    label: str
    kind: str = "command"
    commands: list[str] = field(default_factory=list)    # shown to the user exactly, then run in order
    url: str = ""                                         # kind "open": the official download page
    needs: tuple[str, ...] = ()                           # programs that must be on PATH for this method
    elevation: bool = False                               # needs sudo/admin: never run by FORM
    note: str = ""
    action: Callable[[], str] | None = None               # kind "action": a file edit; returns what it did
    available: bool = True
    reason: str = ""

    def public(self) -> dict:
        return {"id": self.id, "label": self.label, "kind": self.kind, "commands": list(self.commands), "url": self.url,
                "note": self.note, "elevation": self.elevation, "available": self.available, "reason": self.reason}


@dataclass
class Found:
    status: str                 # ok | missing | warn | info   (info: does not apply here, nothing to install)
    detail: str = ""
    version: str = ""
    path: str = ""


@dataclass
class Software:
    id: str
    label: str
    why: str
    level: str                  # required | recommended | optional
    group: str
    detect: Callable[[dict, dict], Found]
    methods: Callable[[str, dict], list[Method]]          # (platform, ctx) → methods in the order they are tried
    size: str = ""
    homepage: str = ""
    one_of: str = ""            # a family where one installed member is enough (slicers)
    needs: tuple[str, ...] = () # registry ids that must be installed first


def platform_key(p: str | None = None) -> str:
    p = p or sys.platform
    return "darwin" if p == "darwin" else "windows" if p.startswith("win") else "linux"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _q(path: str, platform: str | None = None) -> str:
    """Quote one argument for the shell the command will run in (cmd.exe on Windows, sh elsewhere)."""
    if platform_key(platform) == "windows":
        return f'"{path}"' if re.search(r'[\s&()^%!"]', path) or not path else path
    return shlex.quote(path)


def user_bin() -> Path:
    """Where the official Claude Code installer puts `claude` (all platforms)."""
    return Path.home() / ".local" / "bin"


def ensure_user_bin_on_path() -> None:
    """Desktop apps often start without ~/.local/bin on PATH; a just-installed `claude` lives there."""
    d = str(user_bin())
    parts = os.environ.get("PATH", "").split(os.pathsep)
    if d not in parts and Path(d).is_dir():
        os.environ["PATH"] = os.pathsep.join([d] + [p for p in parts if p])


def _pretend_missing(sid: str) -> bool:
    ids = [x.strip() for x in os.environ.get("FORM_SETUP_PRETEND_MISSING", "").split(",") if x.strip()]
    return sid in ids


def _run(cmd: list[str], timeout: float = 20) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace")
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


# ---- detection ----------------------------------------------------------------------------------------------------

def find_claude(cfg: dict | None = None) -> str | None:
    cli = ((cfg or {}).get("chat") or {}).get("cli") or "claude"
    hit = shutil.which(cli)
    if hit:
        return hit
    names = ("claude.exe", "claude.cmd", "claude") if platform_key() == "windows" else ("claude",)
    for d in (user_bin(), Path.home() / ".claude" / "local"):
        for n in names:
            if (d / n).is_file():
                return str(d / n)
    return None


def claude_auth(cfg: dict | None = None, exe: str | None = None) -> dict:
    """Is Claude Code signed in? Asks the CLI (`claude auth status --json`). Account details are not passed on:
    only whether it is signed in and how (subscription or API)."""
    exe = exe or find_claude(cfg)
    if not exe:
        return {"installed": False, "signed_in": False, "method": "", "plan": "", "detail": "Claude Code is not installed."}
    code, out = _run([exe, "auth", "status", "--json"], timeout=30)
    try:
        d = json.loads(out[out.index("{"):out.rindex("}") + 1])
    except ValueError:
        return {"installed": True, "signed_in": False, "method": "", "plan": "", "unknown": True,
                "detail": "This Claude Code version did not report its sign-in state (`claude auth status`). "
                          "Update Claude Code, or send a chat message to find out."}
    on = bool(d.get("loggedIn"))
    how = {"claude.ai": "Claude subscription", "console": "Anthropic Console (API billing)"}.get(str(d.get("authMethod")), str(d.get("authMethod") or ""))
    plan_name = str(d.get("subscriptionType") or "")
    return {"installed": True, "signed_in": on, "method": how, "plan": plan_name,
            "detail": ("Signed in" + (f" · {how}" if how else "") + (f" ({plan_name})" if plan_name else "")) if on
                      else "Not signed in. Chat needs your Claude account."}


def _d_kernel(cfg, ctx) -> Found:
    have = all(importlib.util.find_spec(m) is not None for m in ("build123d", "OCP"))
    if have:
        return Found("ok", "build123d and OpenCascade are " + ("included in this app" if frozen() else "installed"))
    return Found("missing", "build123d / OCP not found in Form Studio's Python environment")


def _d_data(cfg, ctx) -> Found:
    d = Path(cfg["data"]["dir"])
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / f".write-test-{secrets.token_hex(4)}"    # unique: several checks may run at once
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return Found("ok", str(d), path=str(d))
    except OSError as e:
        return Found("missing", f"{d} is not writable: {e}", path=str(d))


def _d_parts(cfg, ctx) -> Found:
    importlib.invalidate_caches()
    missing = [m for m in ("bd_warehouse", "py_gearworks") if importlib.util.find_spec(m) is None]
    if not missing:
        return Found("ok", "bd_warehouse and py_gearworks are " + ("included in this app" if frozen() else "installed"))
    if frozen():
        return Found("warn", f"This build of Form Studio was packaged without {' and '.join(missing)}.")
    return Found("missing", f"{' and '.join(missing)} not installed. Screws, threads, bearings and gears from the standard-parts "
                            "library need them; everything else works.")


def _d_claude(cfg, ctx) -> Found:
    exe = find_claude(cfg)
    if not exe:
        return Found("missing", "Not found. Chat in the app runs Claude Code on your own account.")
    code, out = _run([exe, "--version"], timeout=20)
    v = out.splitlines()[0].strip() if code == 0 and out else ""
    return Found("ok", (v or "installed") + f" · {exe}", version=v, path=exe)


def _d_signin(cfg, ctx) -> Found:
    a = ctx.get("auth") or claude_auth(cfg)
    ctx["auth"] = a
    if not a["installed"]:
        return Found("info", "Install Claude Code first.")
    if a.get("unknown"):
        return Found("warn", a["detail"])
    return Found("ok" if a["signed_in"] else "missing", a["detail"])


def _d_slicer(kind: str):
    def detect(cfg, ctx) -> Found:
        from . import slicer
        a = slicer.adapter(kind)
        try:
            app = a.find_app(cfg)
        except Exception as e:
            return Found("warn", f"Could not check: {e}")
        if not app:
            return Found("missing", "Not installed.")
        try:
            v = slicer.version(app, kind)
        except Exception:
            v = ""
        return Found("ok", (v or "installed") + f" · {app}", version=v, path=app)
    return detect


def _d_openscad(cfg, ctx) -> Found:
    from . import cad_bridges
    exe = cad_bridges.find_openscad(cfg)
    if not exe:
        return Found("missing", "Not installed. Only designs written in OpenSCAD need it.")
    v = cad_bridges.version(exe)
    return Found("ok", f"{v} · {exe}", version=v, path=exe)


def _d_freecad(cfg, ctx) -> Found:
    from . import cad_bridges
    exe = cad_bridges.find_freecad(cfg)
    if not exe:
        return Found("missing", "Not installed. Only “Open in FreeCAD” and the STEP re-import check need it.")
    return Found("ok", f"FreeCADCmd · {exe}", path=exe)


def _d_blender(cfg, ctx) -> Found:
    from .adapters import blender as bl
    b = bl.resolve(cfg)
    if b["available"]:
        return Found("ok", f"Blender {b['version']} · {b['app']}", version=b["version"], path=b["app"])
    return Found("warn" if b["app"] else "missing", ("Not installed. " if not b["app"] else b["reason"] + " ") +
                 "Only illustrative renders need it.")


def _agents(ctx) -> dict:
    if "agents" not in ctx:
        from . import setup
        try:
            ctx["agents"] = {i.id: i for i in setup.agent_items()}
        except Exception:
            ctx["agents"] = {}
    return ctx["agents"]


def _d_agent(aid: str, name: str):
    def detect(cfg, ctx) -> Found:
        it = _agents(ctx).get(aid)
        if it is None:
            return Found("info", f"{name} was not found on this computer.")
        return Found(it.status, it.detail)
    return detect


# ---- install methods ----------------------------------------------------------------------------------------------

def _open(url: str, label: str = "Open the official download page") -> Method:
    return Method("download", label, kind="open", url=url)


def _app_methods(brew: str, winget: str, flatpak: str, url: str, apt: str = ""):
    """The usual desktop-app pattern: Homebrew cask on macOS, winget on Windows, Flathub on Linux, else the download page."""
    def methods(platform: str, ctx: dict) -> list[Method]:
        out: list[Method] = []
        if platform == "darwin" and brew:
            out.append(Method("brew", "Homebrew", commands=[f"brew install --cask {brew}"], needs=("brew",)))
        if platform == "windows" and winget:
            out.append(Method("winget", "winget", needs=("winget",),
                              commands=[f"winget install --id {winget} -e --accept-package-agreements --accept-source-agreements"],
                              note="Windows may show its own permission prompt."))
        if platform == "linux":
            if flatpak:
                out.append(Method("flatpak", "Flathub", commands=[f"flatpak install -y flathub {flatpak}"], needs=("flatpak",),
                                  note="Flatpak apps start with `flatpak run`; Form Studio looks for the exported launcher."))
            if apt:
                out.append(Method("apt", "apt", commands=[f"sudo apt-get install -y {apt}"], needs=("apt-get",), elevation=True))
        out.append(_open(url))
        return out
    return methods


def _m_kernel(platform, ctx) -> list[Method]:
    if frozen():
        return [Method("bundled", "Included in the app", kind="bundled",
                       note="If it is missing, this copy is damaged: download Form Studio again."),
                _open("https://github.com/kaizensx/form-studio/releases", "Download Form Studio again")]
    return [Method("uv", "uv", commands=[f"uv pip install --python {_q(sys.executable, platform)} {KERNEL_PIN}"], needs=("uv",)),
            Method("pip", "pip", commands=[f"{_q(sys.executable, platform)} -m pip install {KERNEL_PIN}"], needs=("#pip",))]


def _m_data(platform, ctx) -> list[Method]:
    return [Method("choose", "Choose another folder", kind="bundled",
                   note="Change the project folder under Settings, General (or `form config set data.dir <folder>`).")]


def _m_parts(platform, ctx) -> list[Method]:
    if frozen():
        return [Method("bundled", "Included in the app", kind="bundled",
                       note="A packaged Form Studio cannot add Python libraries to itself. Download a build that includes them."),
                _open("https://github.com/kaizensx/form-studio/releases", "Download Form Studio again")]
    pins = " ".join(PARTS_PINS)
    return [Method("uv", "uv", commands=[f"uv pip install --python {_q(sys.executable, platform)} {pins}"], needs=("uv",)),
            Method("pip", "pip", commands=[f"{_q(sys.executable, platform)} -m pip install {pins}"], needs=("#pip",))]


def _m_claude(platform, ctx) -> list[Method]:
    # The commands on the official setup page (CLAUDE_DOCS), unchanged.
    if platform == "windows":
        return [Method("native", "Official installer",
                       commands=["curl -fsSL https://claude.ai/install.cmd -o install.cmd && install.cmd && del install.cmd"],
                       needs=("curl",), note="Anthropic's installer for Windows CMD. No administrator rights needed."),
                Method("winget", "winget", commands=["winget install Anthropic.ClaudeCode"], needs=("winget",)),
                _open(CLAUDE_DOCS, "Open the install guide")]
    out = [Method("native", "Official installer", commands=["curl -fsSL https://claude.ai/install.sh | bash"],
                  needs=("curl", "bash"), note="Anthropic's installer. It installs into your home folder; no password needed.")]
    if platform == "darwin":
        out.append(Method("brew", "Homebrew", commands=["brew install --cask claude-code"], needs=("brew",)))
    out.append(_open(CLAUDE_DOCS, "Open the install guide"))
    return out


def _m_signin(platform, ctx) -> list[Method]:
    return [Method("login", "Sign in with your browser", kind="login", commands=["claude auth login"],
                   note="Form Studio runs this in the background and shows the sign-in link. Your password goes to "
                        "Anthropic's page in your browser, never to Form Studio.")]


def _m_agent(aid: str):
    def methods(platform, ctx) -> list[Method]:
        it = _agents(ctx).get(aid)
        if it is None or it.fix is None:
            return []
        f = it.fix
        if f.action:
            return [Method("edit", f.summary, kind="action", action=f.action,
                           note="Edits that file directly. A backup copy is saved next to it first.")]
        return [Method("register", f.summary, commands=list(f.commands), note=f.note)]
    return methods


def _d_cli(cli: str, label: str):
    """An agent CLI on PATH (or set as [chat].<id>_cli), with its version."""
    def detect(cfg, ctx) -> Found:
        from .agents import ADAPTERS
        ad = ADAPTERS.get(cli)
        exe = ad.executable(cfg) if ad else shutil.which(cli)
        if not exe:
            return Found("missing", f"Not found. Form Studio works without it; {label} is one more agent to choose in chat.")
        code, out = _run([exe, "--version"], timeout=30)
        v = out.strip().splitlines()[-1].strip() if code == 0 and out.strip() else ""
        return Found("ok", (v or "installed") + f" · {exe}", version=v, path=exe)
    return detect


def _m_npm_cli(package: str, brew_cask: str, docs: str):
    """The publisher's npm package (and a Homebrew cask where the publisher's package is one)."""
    def methods(platform, ctx) -> list[Method]:
        out = []
        if platform == "darwin" and brew_cask:
            out.append(Method("brew", "Homebrew", commands=[f"brew install --cask {brew_cask}"], needs=("brew",)))
        out.append(Method("npm", "npm", commands=[f"npm install -g {package}"], needs=("npm",),
                          note="Needs Node.js. Installs for this user."))
        out.append(_open(docs, "Open the install guide"))
        return out
    return methods


def gemini_signed_in(cfg: dict | None = None) -> tuple[bool, str]:
    """How Gemini CLI can sign in without its own screen: an API key (FORM's or the environment), or a sign-in it kept."""
    from . import secrets as agent_keys
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_GCA"):
        if os.environ.get(var):
            return True, f"{var} is set in the environment."
    if agent_keys.status()["gemini_api_key"]["set"]:
        return True, "Uses the Gemini API key stored in Form Studio."
    home = Path(os.environ.get("GEMINI_CLI_HOME") or Path.home()) / ".gemini"
    if (home / "oauth_creds.json").exists():
        return True, "Signed in with Google in Gemini CLI."
    try:
        st = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        kind = ((st.get("security") or {}).get("auth") or {}).get("selectedType") or st.get("selectedAuthType")
        if kind:
            return True, f"Gemini CLI is set to sign in with {kind}."
    except (OSError, ValueError, AttributeError):
        pass
    return False, "Not signed in. Add a Gemini API key in Settings, Chat tab, or sign in once with Google in Gemini CLI."


def _d_gemini_signin(cfg, ctx) -> Found:
    if not _d_cli("gemini", "Gemini CLI")(cfg, ctx).status == "ok":
        return Found("info", "Install Gemini CLI first.")
    ok, why = gemini_signed_in(cfg)
    return Found("ok" if ok else "missing", why)


def _m_gemini_signin(platform, ctx) -> list[Method]:
    return [Method("key", "Create an API key", kind="open", url="https://aistudio.google.com/apikey",
                   note="Create a key on Google's page, then paste it in Settings, Chat tab. Form Studio keeps it in a private "
                        "file on this computer and gives it only to Gemini CLI.")]


# ---- more agent CLIs (chat workstream): install commands as each publisher documents them -------------------------

def _m_agent_cli(npm: str = "", brew: str = "", curl: str = "", winget: str = "", docs: str = ""):
    def methods(platform, ctx) -> list[Method]:
        out = []
        if curl and platform != "windows":
            out.append(Method("script", "Official installer", commands=[curl], needs=("curl", "bash"),
                              note="The publisher's install script. It installs into your home folder; no password needed."))
        if brew and platform == "darwin":
            out.append(Method("brew", "Homebrew", commands=[f"brew install {brew}"], needs=("brew",)))
        if winget and platform == "windows":
            out.append(Method("winget", "winget", commands=[f"winget install {winget}"], needs=("winget",)))
        if npm:
            out.append(Method("npm", "npm", commands=[f"npm install -g {npm}"], needs=("npm",),
                              note="Needs Node.js. Installs for this user."))
        if docs:
            out.append(_open(docs, "Open the install guide"))
        return out
    return methods


def _d_agent_signin(aid: str, label: str):
    """Sign-in as the agent's adapter can tell it without a prompt or a network call."""
    def detect(cfg, ctx) -> Found:
        from .agents import ADAPTERS
        ad = ADAPTERS[aid]
        exe = ad.executable(cfg)
        if not exe:
            return Found("info", f"Install {label} first.")
        s = ad.signin(cfg, exe) or {"signed_in": None, "how": "Not checked."}
        return Found({True: "ok", False: "missing"}.get(s["signed_in"], "info"), s["how"])
    return detect


def _m_agent_signin(how: str, docs: str):
    def methods(platform, ctx) -> list[Method]:
        return [Method("docs", "How to sign in", kind="open", url=docs, note=how)]
    return methods


AGENT_CLIS = [
    # (id, label, why, methods, sign-in note, docs)
    ("cursor", "Cursor CLI", "Cursor's agent. Pick it per conversation; it runs on your own Cursor account.",
     _m_agent_cli(curl="curl https://cursor.com/install -fsS | bash", docs="https://cursor.com/docs/cli/headless"),
     "Run `cursor-agent login` once in a terminal, or set CURSOR_API_KEY.", "https://cursor.com/docs/cli/headless"),
    ("opencode", "OpenCode", "An open-source agent that works with many model providers. Pick it per conversation.",
     _m_agent_cli(npm="opencode-ai", brew="opencode", curl="curl -fsSL https://opencode.ai/install | bash",
                  docs="https://opencode.ai/docs/"),
     "Run `opencode auth login` once in a terminal to connect a provider.", "https://opencode.ai/docs/config"),
    ("qwen", "Qwen Code", "Qwen's agent. Pick it per conversation; it runs on your own API key.",
     _m_agent_cli(npm="@qwen-code/qwen-code@latest", brew="qwen-code", docs="https://github.com/QwenLM/qwen-code"),
     "Run `qwen` once in a terminal to choose how it signs in, or set an API key (for example DASHSCOPE_API_KEY).",
     "https://github.com/QwenLM/qwen-code"),
    ("copilot", "GitHub Copilot CLI", "GitHub's agent. Pick it per conversation; it needs a GitHub Copilot plan.",
     _m_agent_cli(npm="@github/copilot", brew="copilot-cli", winget="GitHub.Copilot",
                  docs="https://github.com/github/copilot-cli"),
     "Run `copilot` once in a terminal and use /login, or set COPILOT_GITHUB_TOKEN.",
     "https://github.com/github/copilot-cli"),
]


def _agent_software() -> list["Software"]:
    out = []
    for aid, label, why, methods, how, docs in AGENT_CLIS:
        out.append(Software(aid, label, why, "optional", "agents", _d_cli(aid, label), methods, homepage=docs))
        out.append(Software(f"{aid}.signin", f"{label} sign-in", f"{label} answers only when it is signed in.",
                            "optional", "agents", _d_agent_signin(aid, label), _m_agent_signin(how, docs), needs=(aid,)))
    return out


def _slicer(kind, label, why, brew, winget, flatpak, url, size, level) -> Software:
    return Software(f"slicer.{kind}", label, why, level, "slicer", _d_slicer(kind),
                    _app_methods(brew, winget, flatpak, url), size=size, homepage=url, one_of="slicer")


REGISTRY: list[Software] = [
    Software("kernel", "CAD kernel", "Builds every part as exact geometry (build123d on OpenCascade).",
             "required", "engine", _d_kernel, _m_kernel, size="about 250 MB"),
    Software("data", "Project folder", "Where your designs, their history and releases are kept.",
             "required", "engine", _d_data, _m_data),
    Software("parts", "Standard-parts libraries", "Real screws, threads, bearings and gears (bd_warehouse, py_gearworks).",
             "recommended", "engine", _d_parts, _m_parts, size="about 5 MB"),
    _slicer("bambu", "Bambu Studio", "Slices for Bambu Lab printers. Form Studio reads the printer, filament and process selected in it.",
            "bambu-studio", "Bambulab.Bambustudio", "com.bambulab.BambuStudio", "https://bambulab.com/en/download/studio",
            "about 200 MB", "recommended"),
    _slicer("orca", "OrcaSlicer", "Slices for most printers (Bambu Lab, Prusa, Creality, Voron and more).",
            "orcaslicer", "SoftFever.OrcaSlicer", "com.orcaslicer.OrcaSlicer", "https://github.com/SoftFever/OrcaSlicer/releases",
            "about 150 MB", "optional"),
    _slicer("prusa", "PrusaSlicer", "Slices for Prusa printers and many others.",
            "prusaslicer", "Prusa3D.PrusaSlicer", "com.prusa3d.PrusaSlicer", "https://www.prusa3d.com/page/prusaslicer_424/",
            "about 100 MB", "optional"),
    _slicer("superslicer", "SuperSlicer", "A PrusaSlicer fork with more settings. Homebrew withdrew its package because it fails "
            "Apple's Gatekeeper check; the project's own downloads are the source.",
            "", "", "", "https://github.com/supermerill/SuperSlicer/releases", "about 120 MB", "optional"),
    _slicer("qidi", "QIDISlicer", "Slices for QIDI printers (Q1 Pro, Q2, X-Plus 4 and more).",
            "", "", "", "https://github.com/QIDITECH/QIDISlicer/releases", "about 170 MB", "optional"),
    Software("claude", "Claude Code", "Chat in Form Studio runs Claude Code on your own Claude account. Everything else works without it.",
             "recommended", "ai", _d_claude, _m_claude, size="about 280 MB", homepage=CLAUDE_DOCS),
    Software("claude.signin", "Claude sign-in", "Chat needs Claude Code signed in to your account.",
             "recommended", "ai", _d_signin, _m_signin, needs=("claude",)),
    Software("agent.claude", "Form Studio tools in Claude Code", "Lets Claude Code call Form Studio (design, check, slice) from chat and from a terminal.",
             "recommended", "ai", _d_agent("agent.claude", "Claude Code"), _m_agent("agent.claude"), needs=("claude",)),
    Software("codex", "Codex", "OpenAI's agent. Pick it per conversation; it runs on your own OpenAI account.",
             "optional", "agents", _d_cli("codex", "Codex"), _m_npm_cli("@openai/codex", "codex", "https://developers.openai.com/codex/cli"),
             size="about 90 MB", homepage="https://developers.openai.com/codex/cli"),
    Software("gemini", "Gemini CLI", "Google's agent. Pick it per conversation; it runs on your own Google account or API key.",
             "optional", "agents", _d_cli("gemini", "Gemini CLI"),
             _m_npm_cli("@google/gemini-cli", "", "https://github.com/google-gemini/gemini-cli"),
             size="about 150 MB", homepage="https://github.com/google-gemini/gemini-cli"),
    Software("gemini.signin", "Gemini sign-in", "Gemini CLI answers only when it is signed in or has an API key.",
             "optional", "agents", _d_gemini_signin, _m_gemini_signin, needs=("gemini",)),
    *_agent_software(),
    Software("agent.codex", "Form Studio tools in Codex", "Lets Codex call Form Studio.",
             "recommended", "agents", _d_agent("agent.codex", "Codex"), _m_agent("agent.codex")),
    Software("agent.gemini", "Form Studio tools in Gemini CLI", "Lets Gemini CLI call Form Studio.",
             "recommended", "agents", _d_agent("agent.gemini", "Gemini CLI"), _m_agent("agent.gemini")),
    Software("agent.cursor", "Form Studio tools in Cursor", "Lets Cursor call Form Studio.",
             "recommended", "agents", _d_agent("agent.cursor", "Cursor"), _m_agent("agent.cursor")),
    Software("agent.desktop", "Form Studio tools in Claude Desktop", "Lets the Claude desktop app call Form Studio. Restart Claude Desktop afterwards.",
             "optional", "agents", _d_agent("agent.desktop", "Claude Desktop"), _m_agent("agent.desktop")),
    Software("openscad", "OpenSCAD", "Builds designs written in OpenSCAD (mesh designs: no STEP).",
             "optional", "cad", _d_openscad, _app_methods("openscad", "OpenSCAD.OpenSCAD", "org.openscad.OpenSCAD",
                                                         "https://openscad.org/downloads.html", apt="openscad"),
             size="about 50 MB", homepage="https://openscad.org/downloads.html"),
    Software("blender", "Blender", "Illustrative renders of a design. Never used for measurements.",
             "optional", "cad", _d_blender, _app_methods("blender", "BlenderFoundation.Blender", "org.blender.Blender",
                                                        "https://www.blender.org/download/"),
             size="about 400 MB", homepage="https://www.blender.org/download/"),
    Software("freecad", "FreeCAD", "“Open in FreeCAD”, and re-importing each exported STEP as an extra check.",
             "optional", "cad", _d_freecad, _app_methods("freecad", "FreeCAD.FreeCAD", "org.freecad.FreeCAD",
                                                        "https://www.freecad.org/downloads.php", apt="freecad"),
             size="about 700 MB", homepage="https://www.freecad.org/downloads.php"),
]


def get(sid: str) -> Software:
    for s in REGISTRY:
        if s.id == sid:
            return s
    raise KeyError(sid)


def _has_pip() -> bool:
    return importlib.util.find_spec("pip") is not None


def methods_for(sw: Software, platform: str | None = None, which: Callable[[str], str | None] | None = None,
                ctx: dict | None = None) -> list[Method]:
    """Every method for this OS, in the order tried, each marked available or not with the reason."""
    platform = platform_key(platform)
    which = which or shutil.which
    out = []
    for m in sw.methods(platform, ctx if ctx is not None else {}):
        lacking = [n for n in m.needs if (not _has_pip() if n == "#pip" else not which(n))]
        if m.elevation:
            m.available, m.reason = False, ("Needs an administrator password. Form Studio never asks for one; "
                                            "run it yourself in a terminal if you prefer this way.")
        elif lacking:
            names = ", ".join("pip" if n == "#pip" else n for n in lacking)
            m.available, m.reason = False, f"{names} is not installed"
        out.append(m)
    return out


def plan(sw: Software, platform: str | None = None, which=None, ctx: dict | None = None, method: str | None = None) -> Method | None:
    """The method an install would use: the first available one FORM can run itself (or the one named)."""
    ms = methods_for(sw, platform, which, ctx)
    if method:
        return next((m for m in ms if m.id == method and m.available and m.kind in ("command", "action", "login")), None)
    return next((m for m in ms if m.available and m.kind in ("command", "action", "login")), None)


def manual(sw: Software, platform: str | None = None, ctx: dict | None = None) -> str:
    """The official page to get it by hand."""
    for m in sw.methods(platform_key(platform), ctx if ctx is not None else {}):
        if m.kind == "open":
            return m.url
    return sw.homepage


# ---- the registry as the app, CLI and MCP see it --------------------------------------------------------------------

def survey(cfg: dict, platform: str | None = None, which=None, only: list[str] | None = None) -> list[dict]:
    """Detect everything (or `only` these ids) and describe it. Read-only."""
    ctx: dict = {}
    home = str(Path.home())
    rows = []
    for sw in REGISTRY:
        if only is not None and sw.id not in only:
            continue
        try:
            f = Found("missing", "Reported as missing by FORM_SETUP_PRETEND_MISSING (development).") \
                if _pretend_missing(sw.id) else sw.detect(cfg, ctx)
        except Exception as e:                           # detection must never break the list
            f = Found("warn", f"Could not check: {type(e).__name__}: {e}")
        ms = methods_for(sw, platform, which, ctx) if f.status != "ok" else []
        chosen = next((m for m in ms if m.available and m.kind in ("command", "action", "login")), None)
        rows.append({"id": sw.id, "label": sw.label, "why": sw.why, "level": sw.level, "group": sw.group, "size": sw.size,
                     "status": f.status, "detail": f.detail.replace(home, "~") if len(home) > 1 else f.detail,
                     "version": f.version, "homepage": sw.homepage, "one_of": sw.one_of, "needs": list(sw.needs),
                     "methods": [m.public() for m in ms], "plan": chosen.public() if chosen else None,
                     "manual": manual(sw, platform, ctx) if f.status != "ok" else "",
                     "installable": bool(chosen) and f.status in ("missing", "warn") and chosen.kind != "login",
                     "absent": sw.id.startswith("agent.") and f.status == "info"})
    by = {r["id"]: r for r in rows}
    families_ok = {r["one_of"] for r in rows if r["one_of"] and r["status"] == "ok"}
    for r in rows:
        if r["one_of"] in families_ok and r["status"] != "ok":
            r["level"] = "optional"                      # one slicer is enough
        blocked = [n for n in r["needs"] if n in by and by[n]["status"] != "ok"]
        if blocked and r["status"] not in ("ok", "info"):
            r["installable"] = False
            r["blocked_by"] = blocked
        # pre-ticked: recommended or required, missing, and FORM can install it itself
        r["default"] = r["installable"] and r["level"] in ("required", "recommended") and r["status"] == "missing"
    return rows


def summary(rows: list[dict]) -> dict:
    need = [r for r in rows if r["level"] == "required"]
    return {"required_ok": all(r["status"] in ("ok", "info") for r in need),
            "recommended_missing": [r["id"] for r in rows if r["level"] == "recommended" and r["status"] in ("missing", "warn")],
            "groups": [{"id": g, "title": t, "items": [r["id"] for r in rows if r["group"] == g]} for g, t in GROUPS]}


# ---- jobs ---------------------------------------------------------------------------------------------------------

_SUDO = re.compile(r"sudo: (a terminal is required|a password is required|no tty present)|Password:\s*$|Need sudo access", re.I)
_FAKE = ("import sys,time\nn=max(2,int(float(sys.argv[1])*2))\n"
         "for i in range(n):\n    print('simulated: step %d of %d' % (i+1,n), flush=True)\n    time.sleep(0.5)\n")


def _kill(proc: subprocess.Popen) -> None:
    """Stop a command and what it started. Never raises."""
    try:
        if platform_key() == "windows":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, stdin=subprocess.DEVNULL)
        else:
            import signal
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
    except OSError:
        pass


def _close(proc: subprocess.Popen) -> None:
    for f in (proc.stdout, proc.stdin):
        try:
            if f is not None:
                f.close()
        except OSError:
            pass


def _popen(cmd, **kw) -> subprocess.Popen:
    if platform_key() == "windows":
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        kw["start_new_session"] = True                    # its own process group, so cancel stops the whole tree
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", bufsize=1, **kw)


class Job:
    """Installs the chosen items one after another. Poll `public(start)` for new log lines."""

    def __init__(self, cfg: dict, steps: list[tuple[Software, Method]], timeout_s: float = DEFAULT_TIMEOUT_S,
                 on_done: Callable[["Job"], None] | None = None):
        self.id = secrets.token_hex(5)
        self.cfg, self.timeout_s, self.on_done = cfg, timeout_s, on_done
        self.pairs = steps
        self.state = "running"                            # running | done | failed | cancelled
        self.started = time.time()
        self.ended: float | None = None
        self.log: list[dict] = []                         # {"n", "step", "t", "text", "kind": cmd|out|note|err}
        self.steps = [{"id": s.id, "label": s.label, "method": m.id, "method_label": m.label, "commands": list(m.commands),
                       "edits_file": m.kind == "action", "state": "waiting", "message": ""} for s, m in steps]
        self.after: dict = {}
        self._proc: subprocess.Popen | None = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    # -- log --
    def say(self, step: str, text: str, kind: str = "out") -> None:
        with self._lock:
            self.log.append({"n": len(self.log), "step": step, "t": round(time.time() - self.started, 1),
                             "text": text.rstrip("\r\n")[:2000], "kind": kind})
            if len(self.log) > 20000:                      # a runaway command must not eat memory
                del self.log[:5000]

    def public(self, start: int = 0) -> dict:
        with self._lock:
            lines = [l for l in self.log if l["n"] >= start]
            nxt = (self.log[-1]["n"] + 1) if self.log else 0
        return {"id": self.id, "state": self.state, "steps": [dict(s) for s in self.steps], "after": self.after,
                "log": lines, "next": nxt, "seconds": round((self.ended or time.time()) - self.started, 1),
                "fake": bool(os.environ.get("FORM_INSTALL_FAKE"))}

    def cancel(self) -> None:
        self._cancel.set()
        p = self._proc
        if p is not None and p.poll() is None:
            _kill(p)

    # -- run --
    def start(self) -> "Job":
        threading.Thread(target=self.run, daemon=True, name="form-install").start()
        return self

    def run(self) -> None:
        try:
            ensure_user_bin_on_path()
            for step, (sw, m) in zip(self.steps, self.pairs):
                if self._cancel.is_set():
                    step.update(state="cancelled", message="not started")
                    continue
                step["state"] = "running"
                ok, msg = self._one(sw, m)
                if self._cancel.is_set() and not ok:
                    step.update(state="cancelled", message="cancelled")
                    self.say(sw.id, "Cancelled.", "note")
                    continue
                if ok:
                    ok, msg = self._verify(sw, msg)
                step.update(state="done" if ok else "failed", message=msg)
                self.say(sw.id, ("Done: " if ok else "Failed: ") + msg, "note" if ok else "err")
            rows = survey(self.cfg, only=[s["id"] for s in self.steps])
            self.after = {r["id"]: r for r in rows}
            states = {s["state"] for s in self.steps}
            self.state = "cancelled" if "cancelled" in states else "failed" if "failed" in states else "done"
        except Exception as e:                            # never leave a job "running" forever
            self.state = "failed"
            self.say("_", f"{type(e).__name__}: {e}", "err")
        finally:
            self.ended = time.time()
            if self.on_done:
                try:
                    self.on_done(self)
                except Exception:
                    pass

    def _verify(self, sw: Software, msg: str) -> tuple[bool, str]:
        if os.environ.get("FORM_INSTALL_FAKE"):
            return True, "simulated; nothing was installed"
        ensure_user_bin_on_path()
        try:
            f = sw.detect(self.cfg, {})
        except Exception as e:
            return False, f"ran, but checking it again failed: {e}"
        if f.status == "ok":
            return True, f.detail or msg
        return False, "the command finished, but Form Studio still cannot find it. " + f.detail

    def _one(self, sw: Software, m: Method) -> tuple[bool, str]:
        if m.kind == "action":
            if os.environ.get("FORM_INSTALL_FAKE"):
                self.say(sw.id, "FORM_INSTALL_FAKE is set: simulated, no file was changed.", "note")
                return True, "simulated"
            try:
                msg = m.action()
                self.say(sw.id, msg, "out")
                return True, msg
            except Exception as e:
                return False, str(e)
        work = tempfile.mkdtemp(prefix="form-install-")
        try:
            for cmd in m.commands:
                self.say(sw.id, cmd, "cmd")
                ok, msg = self._exec(sw.id, cmd, work)
                if not ok:
                    return False, msg
            return True, "done"
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _exec(self, sid: str, cmd: str, cwd: str) -> tuple[bool, str]:
        fake = os.environ.get("FORM_INSTALL_FAKE")
        try:
            if fake:
                self.say(sid, "FORM_INSTALL_FAKE is set: this is a stand-in, nothing is downloaded or installed.", "note")
                try:
                    secs = float(fake)
                except ValueError:
                    secs = 6.0
                proc = _popen([sys.executable, "-c", _FAKE, str(secs)], stdin=subprocess.DEVNULL, cwd=cwd)
            else:
                # no terminal stdin: nothing can prompt (and Bun-based CLIs crash on /dev/tty on macOS)
                proc = _popen(cmd, shell=True, stdin=subprocess.DEVNULL, cwd=cwd)
        except OSError as e:
            return False, str(e)
        self._proc = proc
        timed_out = threading.Event()

        def watchdog():
            timed_out.set()
            _kill(proc)
        timer = threading.Timer(self.timeout_s, watchdog)
        timer.daemon = True
        timer.start()
        wants_password = False
        try:
            for line in proc.stdout:                      # ends when the command (and its children) close the pipe
                if _SUDO.search(line):
                    wants_password = True
                self.say(sid, line, "out")
            proc.wait()
        finally:
            timer.cancel()
            self._proc = None
            _close(proc)
        if timed_out.is_set():
            mins = self.timeout_s / 60
            return False, f"stopped after {mins:.0f} minutes" if mins >= 1 else f"stopped after {self.timeout_s:.0f} s"
        if self._cancel.is_set():
            return False, "cancelled"
        if proc.returncode != 0:
            if wants_password:
                return False, ("it asked for an administrator password. Form Studio never asks for one. "
                               "Run the command yourself in a terminal, or use the download page.")
            return False, f"exited with {proc.returncode}"
        return True, "done"


class LoginJob:
    """`claude auth login` in the background: the sign-in link it prints is shown in the app, the browser does the rest.
    If the page shows a code to paste back, `send_code` passes it to the CLI. No password ever reaches FORM."""
    URL = re.compile(r"https://[^\s\"'<>]+")

    def __init__(self, cfg: dict, argv: list[str] | None = None, timeout_s: float = 600):
        self.id = secrets.token_hex(5)
        self.cfg, self.timeout_s = cfg, timeout_s
        self.argv = argv or [find_claude(cfg) or "claude", "auth", "login"]
        self.state = "running"                            # running | done | failed | cancelled
        self.url = ""
        self.lines: list[str] = []
        self.message = ""
        self.auth: dict | None = None
        self.started = time.time()
        self._proc: subprocess.Popen | None = None
        self._cancelled = False

    def public(self) -> dict:
        return {"id": self.id, "state": self.state, "url": self.url, "lines": self.lines[-40:], "message": self.message,
                "auth": self.auth, "command": "claude auth login", "seconds": round(time.time() - self.started, 1)}

    def start(self) -> "LoginJob":
        threading.Thread(target=self.run, daemon=True, name="form-claude-login").start()
        return self

    def send_code(self, code: str) -> None:
        p = self._proc
        if p is None or p.poll() is not None or p.stdin is None:
            raise RuntimeError("Sign-in is not waiting for a code.")
        try:
            p.stdin.write(code.strip() + "\n")
            p.stdin.flush()
        except OSError as e:
            raise RuntimeError(f"Could not pass the code to Claude Code: {e}")

    def cancel(self) -> None:
        self._cancelled = True
        p = self._proc
        if p is not None and p.poll() is None:
            _kill(p)

    def run(self) -> None:
        try:
            ensure_user_bin_on_path()
            try:
                proc = _popen(self.argv, stdin=subprocess.PIPE)
            except OSError as e:
                self.state, self.message = "failed", f"Could not start Claude Code: {e}"
                return
            self._proc = proc
            timed = threading.Event()

            def watchdog():
                timed.set()
                _kill(proc)
            timer = threading.Timer(self.timeout_s, watchdog)
            timer.daemon = True
            timer.start()
            try:
                for line in proc.stdout:
                    line = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", line).rstrip()
                    if not line:
                        continue
                    self.lines.append(line[:600])
                    m = self.URL.search(line)
                    if m and not self.url:
                        self.url = m.group(0).rstrip(".,)")
                proc.wait()
            finally:
                timer.cancel()
                _close(proc)
            if self._cancelled:
                self.state, self.message = "cancelled", "Sign-in was cancelled."
                return
            if timed.is_set():
                self.state, self.message = "failed", "Sign-in was not finished in time. Start it again when you are ready."
                return
            self.auth = claude_auth(self.cfg, self.argv[0]) if len(self.argv) > 1 and self.argv[1:3] == ["auth", "login"] else None
            if proc.returncode == 0 and (self.auth is None or self.auth.get("signed_in")):
                self.state, self.message = "done", "Signed in."
            else:
                self.state = "failed"
                self.message = ("Claude Code did not finish signing in"
                                + (f" (exit {proc.returncode})" if proc.returncode else "") +
                                ". If this keeps happening, run `claude auth login` once in a terminal.")
        except Exception as e:
            self.state, self.message = "failed", f"{type(e).__name__}: {e}"
        finally:
            self._proc = None


class Installer:
    """One per engine: holds install jobs (one at a time) and the Claude sign-in job."""

    def __init__(self, cfg: dict, on_done: Callable[[Job], None] | None = None):
        self.cfg, self.on_done = cfg, on_done
        self.jobs: dict[str, Job] = {}
        self.logins: dict[str, LoginJob] = {}
        self._lock = threading.Lock()
        ensure_user_bin_on_path()

    def survey(self) -> list[dict]:
        return survey(self.cfg)

    def prepare(self, ids: list[str], shown: dict | None = None, methods: dict | None = None) -> list[tuple[Software, Method]]:
        """Resolve ids to (software, method), refusing anything that is not exactly what was shown."""
        if not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids):
            raise InstallError("Pick at least one thing to install.")
        ctx: dict = {}
        known = {s.id: s for s in REGISTRY}
        rows = {r["id"]: r for r in survey(self.cfg, only=None)}
        pairs = []
        for sid in dict.fromkeys(ids):
            sw = known.get(sid)
            if sw is None:
                raise InstallError(f"Unknown item “{sid}”.", "Known: " + ", ".join(known))
            row = rows[sid]
            if row["status"] == "ok":
                raise InstallError(f"{sw.label} is already installed.", row["detail"])
            if row.get("blocked_by"):
                raise InstallError(f"{sw.label} needs {known[row['blocked_by'][0]].label} first.", "Install that, then try again.")
            m = plan(sw, ctx=ctx, method=(methods or {}).get(sid))
            if m is None or m.kind == "login":
                why = "; ".join(f"{x.label}: {x.reason}" for x in methods_for(sw, ctx=ctx) if not x.available and x.reason)
                page = manual(sw, ctx=ctx)
                if m is not None:
                    raise InstallError(f"{sw.label} is a sign-in, not an install.", "Use the Sign in button (or run `claude auth login`).")
                raise InstallError(f"Form Studio cannot install {sw.label} by itself on this computer.",
                                   (why + ". " if why else "") + (f"Get it from {page}" if page else ""))
            if shown is not None and list(shown.get(sid) or []) != list(m.commands):
                raise InstallError(f"{sw.label}: the install command changed since it was shown.",
                                   "Check again and review the command before installing.", status=409)
            pairs.append((sw, m))
        return pairs

    def install(self, ids: list[str], shown: dict | None = None, methods: dict | None = None, start: bool = True,
                timeout_s: float | None = None) -> Job:
        with self._lock:
            if any(j.state == "running" for j in self.jobs.values()):
                raise InstallError("An install is already running.", "Wait for it, or cancel it.", status=409)
            pairs = self.prepare(ids, shown, methods)
            job = Job(self.cfg, pairs, timeout_s or DEFAULT_TIMEOUT_S, self.on_done)
            self.jobs[job.id] = job
        if start:
            job.start()
        return job

    # -- upgrading FORM itself (pip / uv / a source checkout; the packaged app is replaced by a download) --
    def update(self, shown: str | None = None, start: bool = True, timeout_s: float | None = None) -> Job:
        """Run FORM's own upgrade command as an install job with a streamed log. `shown` is the command the user
        was shown; a different command is refused. The running app keeps the old code until it is restarted."""
        from . import updates
        kind = updates.install_kind()
        cmd = updates.upgrade_command(kind)
        if not cmd:
            raise InstallError("This copy of Form Studio is updated by downloading the new app.",
                               "Use the download button; your projects stay where they are.")
        if shown is not None and shown != cmd:
            raise InstallError("The upgrade command changed since it was shown.", "Open the update sheet again and review it.", status=409)
        sw = Software("form.update", "Form Studio", "Upgrades Form Studio itself.", "optional", "form",
                      lambda cfg, ctx: Found("ok", "The new version is installed. Restart Form Studio to use it."),
                      lambda platform, ctx: [])
        m = Method("upgrade", "Upgrade a source checkout" if kind == "source" else "Upgrade with uv or pip", commands=[cmd])
        with self._lock:
            if any(j.state == "running" for j in self.jobs.values()):
                raise InstallError("An install is already running.", "Wait for it, or cancel it.", status=409)
            job = Job(self.cfg, [(sw, m)], timeout_s or DEFAULT_TIMEOUT_S, None)
            self.jobs[job.id] = job
        if start:
            job.start()
        return job

    def job(self, jid: str) -> Job:
        j = self.jobs.get(jid)
        if j is None:
            raise InstallError("Unknown install job.", status=404)
        return j

    def login(self, start: bool = True) -> LoginJob:
        if not find_claude(self.cfg):
            raise InstallError("Claude Code is not installed.", "Install it first, then sign in.")
        for j in self.logins.values():
            if j.state == "running":
                return j
        job = LoginJob(self.cfg)
        self.logins[job.id] = job
        if start:
            job.start()
        return job

    def login_job(self, jid: str) -> LoginJob:
        j = self.logins.get(jid)
        if j is None:
            raise InstallError("Unknown sign-in job.", status=404)
        return j


class InstallError(Exception):
    def __init__(self, message: str, hint: str = "", status: int = 400):
        super().__init__(message)
        self.message, self.hint, self.status = message, hint, status

    def public(self) -> dict:
        return {"message": self.message, **({"hint": self.hint} if self.hint else {})}


# ---- headless -----------------------------------------------------------------------------------------------------

def run_blocking(cfg: dict, ids: list[str], methods: dict | None = None, echo: Callable[[str], None] | None = None,
                 timeout_s: float | None = None) -> Job:
    """Install and wait (CLI, MCP). `echo` receives each log line as it arrives."""
    inst = Installer(cfg)
    job = inst.install(ids, None, methods, start=True, timeout_s=timeout_s)
    seen = 0
    try:
        while True:
            p = job.public(seen)
            for l in p["log"]:
                if echo:
                    echo(("$ " if l["kind"] == "cmd" else "  ") + l["text"])
            seen = p["next"]
            if p["state"] != "running":
                return job
            time.sleep(0.2)
    except KeyboardInterrupt:
        job.cancel()
        while job.state == "running":
            time.sleep(0.1)
        return job


def recommended_ids(rows: list[dict]) -> list[str]:
    return [r["id"] for r in rows if r["default"]]


def main(argv=None) -> int:
    """`form install …`"""
    import argparse
    from . import config
    ap = argparse.ArgumentParser(prog="form install", description="Install what Form Studio uses. Shows each command before it runs.")
    ap.add_argument("ids", nargs="*", help="registry ids (see --list), or “recommended”")
    ap.add_argument("--list", action="store_true", help="the registry as JSON: what was found, and how each item is installed")
    ap.add_argument("--yes", action="store_true", help="do not ask before running the commands")
    ap.add_argument("--dry-run", action="store_true", help="print what would run; run nothing")
    ap.add_argument("--method", help="use this method id instead of the first available one")
    a = ap.parse_args(argv)
    cfg = config.load()
    rows = survey(cfg)
    if a.list or not a.ids:
        print(json.dumps({"software": rows, **summary(rows)}, indent=1, ensure_ascii=False))
        return 0
    ids = recommended_ids(rows) if a.ids == ["recommended"] else a.ids
    if not ids:
        print(json.dumps({"installed": [], "note": "Nothing recommended is missing."}))
        return 0
    inst = Installer(cfg)
    try:
        pairs = inst.prepare(ids, None, {i: a.method for i in ids} if a.method else None)
    except InstallError as e:
        print(json.dumps({"error": e.public()}, indent=1, ensure_ascii=False))
        return 2
    plan_out = [{"id": s.id, "label": s.label, "method": m.label, "commands": m.commands,
                 **({"edits": m.note} if m.kind == "action" else {})} for s, m in pairs]
    if a.dry_run:
        print(json.dumps({"dry_run": True, "would_run": plan_out}, indent=1, ensure_ascii=False))
        return 0
    if not a.yes:
        for p in plan_out:
            print(f"{p['label']} ({p['method']})", file=sys.stderr)
            for c in p["commands"]:
                print(f"    $ {c}", file=sys.stderr)
        try:
            if input("Run this? [y/N] ").strip().lower() not in ("y", "yes"):
                print(json.dumps({"installed": [], "note": "Nothing was run."}))
                return 0
        except EOFError:
            print(json.dumps({"error": {"message": "No answer (not a terminal).", "hint": "Pass --yes to run without asking."}}))
            return 2
    job = run_blocking(cfg, ids, {i: a.method for i in ids} if a.method else None, echo=lambda s: print(s, file=sys.stderr))
    print(json.dumps({"state": job.state, "steps": job.steps,
                      "after": {k: {"status": v["status"], "detail": v["detail"]} for k, v in job.after.items()}},
                     indent=1, ensure_ascii=False))
    return 0 if job.state == "done" else 1


# ---- hands-free setup (engine workstream) -------------------------------------------------------------------------
# First start installs what Form Studio needs without questions, in the app, with every command in the log. It only
# stops for what a person must do: sign in, download an app Form Studio cannot install itself, or answer a system
# prompt. Then it waits, checks again every few seconds, and goes on by itself once that thing is there. Nothing runs
# with administrator rights; Gatekeeper and system prompts are left to the system. Cancel stops it; Skip leaves one item.
#
#     Installer.auto(start=True)          the app (POST /api/install/auto)
#     run_auto(cfg, echo, wait=True)      `form setup --auto`

AUTO_POLL_S = 3.0           # how often a waiting item is checked again
AUTO_WAIT_S = 1800          # how long one item may wait for the person before it is left as not done
AUTO_GROUPS = ("engine", "slicer", "ai")


def auto_ids(rows: list[dict]) -> list[str]:
    """What a hands-free setup takes care of: every required or recommended item Form Studio itself needs (the engine,
    a slicer, Claude Code for chat and its sign-in) that is missing, in registry order. One slicer is enough (survey
    makes the rest optional). Other agents' settings are never edited without a click: they stay in the list."""
    out = []
    for r in rows:
        if r["level"] not in ("required", "recommended") or r["status"] not in ("missing", "warn") or r.get("absent"):
            continue
        if r["group"] not in AUTO_GROUPS:
            continue
        if r["id"].startswith("slicer.") and any(x["one_of"] == "slicer" and x["status"] == "ok" for x in rows):
            continue
        out.append(r["id"])
    return out


def _fake_s() -> float:
    try:
        return float(os.environ.get("FORM_INSTALL_FAKE") or 0)
    except ValueError:
        return 6.0


class AutoJob(Job):
    """Installs, signs in and waits for downloads, one item after another. Step states: waiting | running |
    needs_user (the person has to do something; `action` says what) | done | failed | skipped | cancelled."""

    def __init__(self, cfg: dict, ids: list[str], installer: "Installer | None" = None, poll_s: float = AUTO_POLL_S,
                 wait_s: float = AUTO_WAIT_S, timeout_s: float = DEFAULT_TIMEOUT_S, on_done=None):
        known = {s.id: s for s in REGISTRY}
        super().__init__(cfg, [(known[i], Method("auto", "Automatic")) for i in ids if i in known], timeout_s, on_done)
        self.kind = "auto"
        self.installer, self.poll_s, self.wait_s = installer, poll_s, wait_s
        self._skip: set = set()
        for s in self.steps:
            s.update(action=None, commands=[])

    def skip(self, sid: str) -> None:
        self._skip.add(sid)

    def public(self, start: int = 0) -> dict:
        out = super().public(start)
        out["kind"] = "auto"
        out["waiting_for_you"] = next((s for s in out["steps"] if s["state"] == "needs_user"), None)
        return out

    def run(self) -> None:
        try:
            ensure_user_bin_on_path()
            for step, (sw, _m) in zip(self.steps, self.pairs):
                if self._cancel.is_set():
                    step.update(state="cancelled", message="not started")
                    continue
                if sw.id in self._skip:
                    step.update(state="skipped", message="skipped")
                    continue
                step["state"] = "running"
                ok, msg = self._auto_one(sw, step)
                if self._cancel.is_set() and not ok:
                    step.update(state="cancelled", message="cancelled", action=None)
                    continue
                if step["state"] != "skipped":
                    step.update(state="done" if ok else "failed", message=msg, action=None)
                    self.say(sw.id, ("Done: " if ok else "Not done: ") + msg, "note" if ok else "err")
            self.after = {r["id"]: r for r in survey(self.cfg, only=[s["id"] for s in self.steps])}
            states = {s["state"] for s in self.steps}
            self.state = "cancelled" if "cancelled" in states else "failed" if "failed" in states else "done"
        except Exception as e:
            self.state = "failed"
            self.say("_", f"{type(e).__name__}: {e}", "err")
        finally:
            self.ended = time.time()
            if self.on_done:
                try:
                    self.on_done(self)
                except Exception:
                    pass

    def _found(self, sw: Software) -> Found:
        if _pretend_missing(sw.id):
            return Found("missing", "reported missing by FORM_SETUP_PRETEND_MISSING (development)")
        try:
            return sw.detect(self.cfg, {})
        except Exception as e:
            return Found("warn", f"Could not check: {e}")

    def _auto_one(self, sw: Software, step: dict) -> tuple[bool, str]:
        ctx: dict = {}
        if self._found(sw).status == "ok":
            return True, "already there"
        blocked = [n for n in sw.needs if get(n).detect(self.cfg, {}).status != "ok"] if not os.environ.get("FORM_INSTALL_FAKE") else []
        if blocked:
            return False, f"needs {get(blocked[0]).label} first"
        m = plan(sw, ctx=ctx)
        if m is not None and m.kind == "login":
            return self._signin(sw, step)
        if m is not None:
            step.update(method=m.id, method_label=m.label, commands=list(m.commands), edits_file=m.kind == "action")
            ok, msg = self._one(sw, m)
            if ok:
                ok, msg = self._verify(sw, msg)
            if ok or self._cancel.is_set():
                return ok, msg
            self.say(sw.id, f"{m.label} did not finish: {msg}", "note")
        page = manual(sw, ctx=ctx)
        if not page:
            return False, (m and "could not be installed here") or "Form Studio cannot install this by itself here"
        why = "Form Studio cannot install it by itself on this computer" if m is None else "the automatic install did not work"
        return self._wait_for(sw, step, {"kind": "download", "url": page,
                                         "text": f"Download {sw.label} from its official page and install it ({why}). "
                                                 "Form Studio notices when it is there and continues."})

    def _signin(self, sw: Software, step: dict) -> tuple[bool, str]:
        if os.environ.get("FORM_INSTALL_FAKE"):
            self.say(sw.id, "FORM_INSTALL_FAKE is set: the sign-in is simulated and ends by itself.", "note")
            return self._wait_for(sw, step, {"kind": "signin", "url": "", "login": "",
                                             "text": "Sign in to your Claude account in the browser page that opens. "
                                                     "Form Studio continues when you are signed in."})
        lj = None
        if self.installer is not None:
            try:
                lj = self.installer.login(start=True)
            except InstallError as e:
                return False, e.message
        t0 = time.time()
        while lj is not None and not lj.url and lj.state == "running" and time.time() - t0 < 20 and not self._cancel.is_set():
            time.sleep(0.2)
        action = {"kind": "signin", "url": lj.url if lj else "", "login": lj.id if lj else "",
                  "text": "Sign in to your Claude account in the browser page that opens. Form Studio continues when you are signed in."}
        ok, msg = self._wait_for(sw, step, action, login=lj)
        if not ok and lj is not None and lj.state == "running":
            lj.cancel()
        return ok, msg

    def _wait_for(self, sw: Software, step: dict, action: dict, login=None) -> tuple[bool, str]:
        step.update(state="needs_user", action=action)
        self.say(sw.id, "Waiting for you: " + action["text"] + (f" ({action['url']})" if action.get("url") else ""), "note")
        t0 = time.time()
        while not self._cancel.is_set():
            if sw.id in self._skip:
                step.update(state="skipped", message="skipped", action=None)
                self.say(sw.id, "Skipped.", "note")
                return False, "skipped"
            if login is not None and login.url and not action.get("url"):
                action["url"] = login.url
            if login is not None and login.state in ("failed", "cancelled"):
                return False, login.message or "sign-in did not finish"
            f = Found("ok", "simulated") if os.environ.get("FORM_INSTALL_FAKE") and time.time() - t0 > _fake_s() else self._found(sw)
            if f.status == "ok":
                step["state"] = "running"
                return True, f.detail or "found"
            if time.time() - t0 > self.wait_s:
                return False, f"not there after {self.wait_s / 60:.0f} minutes"
            self._cancel.wait(self.poll_s)
        return False, "cancelled"


def _installer_auto(self: "Installer", ids: list[str] | None = None, start: bool = True, poll_s: float = AUTO_POLL_S) -> AutoJob:
    with self._lock:
        if any(j.state == "running" for j in self.jobs.values()):
            raise InstallError("An install is already running.", "Wait for it, or cancel it.", status=409)
        rows = survey(self.cfg)
        ids = auto_ids(rows) if ids is None else ids
        job = AutoJob(self.cfg, ids, self, poll_s=poll_s, on_done=self.on_done)
        self.jobs[job.id] = job
    if start:
        job.start()
    return job


Installer.auto = _installer_auto


def run_auto(cfg: dict, echo: Callable[[str], None] | None = None, wait: bool = True, poll_s: float = AUTO_POLL_S) -> AutoJob:
    """`form setup --auto`: the same hands-free setup in a terminal. With wait=False an item that needs the person is
    skipped instead of waited for."""
    inst = Installer(cfg)
    job = inst.auto(start=True, poll_s=poll_s)
    seen, told = 0, set()
    try:
        while True:
            p = job.public(seen)
            for l in p["log"]:
                if echo:
                    echo(("$ " if l["kind"] == "cmd" else "  ") + l["text"])
            seen = p["next"]
            w = p["waiting_for_you"]
            if w and w["id"] not in told:
                told.add(w["id"])
                if not wait:
                    job.skip(w["id"])
            if p["state"] != "running":
                return job
            time.sleep(0.2)
    except KeyboardInterrupt:
        job.cancel()
        while job.state == "running":
            time.sleep(0.1)
        return job


# ---- OrcaSlicer forks (engine workstream; adapters in form/adapters/orca_forks.py) ---------------------------------
def _add_slicers() -> None:
    at = next(i for i, s in enumerate(REGISTRY) if s.id == "slicer.qidi") + 1
    for sw in (
        _slicer("elegoo", "ElegooSlicer", "Slices for Elegoo printers (Centauri Carbon, Neptune). OrcaSlicer's CLI and presets.",
                "elegoo-slicer", "Elegoo.ElegooSlicer", "", "https://github.com/ELEGOO-3D/ElegooSlicer/releases",
                "about 200 MB", "optional"),
        _slicer("snapmaker", "Snapmaker Orca", "Slices for Snapmaker printers (U1, J1, Artisan, A-series). OrcaSlicer's CLI and presets.",
                "snapmaker-orca", "Snapmaker.OrcaSlicer", "", "https://github.com/Snapmaker/OrcaSlicer/releases",
                "about 260 MB", "optional"),
    ):
        if not any(s.id == sw.id for s in REGISTRY):
            REGISTRY.insert(at, sw)
            at += 1


_add_slicers()
