"""`form setup`: find what is missing, offer to fix it, fix only what the user picks, verify each fix.

Every fix states its exact command or file change before it runs. Config files
are backed up before they are edited. Nothing is downloaded or installed unless
the user selects it (or passes --yes, which applies only the recommended fixes;
large downloads are never recommended automatically).
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

HOME = Path.home()
BAMBU_URL = "https://bambulab.com/en/download/studio"


@dataclass
class Fix:
    summary: str
    commands: list[str] = field(default_factory=list)     # shown to the user, run in order
    action: Callable[[], str] | None = None               # or a Python action (file edit), returns what it did
    recommended: bool = True
    note: str = ""


@dataclass
class Item:
    id: str
    label: str
    status: str            # ok | missing | warn | info
    detail: str
    fix: Fix | None = None

    def public(self) -> dict:
        out = {"id": self.id, "label": self.label, "status": self.status, "detail": self.detail}
        if self.fix:
            out["fix"] = {"summary": self.fix.summary, "commands": self.fix.commands, "recommended": self.fix.recommended,
                          **({"note": self.fix.note} if self.fix.note else {})}
        return out


def mcp_command() -> str:
    """Absolute path of the form-mcp launcher for this installation."""
    exe = Path(sys.executable).parent
    names = ("form-mcp.exe", "form-mcp") if sys.platform.startswith("win") else ("form-mcp",)
    for d in (exe, exe / "Scripts"):            # Windows venvs keep launchers in Scripts\
        for n in names:
            if (d / n).exists():
                return str(d / n)
    return shutil.which("form-mcp") or str(exe / names[0])


def _run(cmd: list[str], timeout=30) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def _json_register(path: Path, key: str = "mcpServers") -> Callable[[], str]:
    """Add {"form": {"command": ...}} to a JSON MCP config, with a backup. Refuses to touch unreadable files."""
    def act() -> str:
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except ValueError:
                raise RuntimeError(f"{path} is not valid JSON (comments?). Add FORM by hand: "
                                   f'"{key}": {{"form": {{"command": "{mcp_command()}"}}}}')
        backup = None
        if path.exists():
            backup = path.with_name(path.name + f".bak-form-{int(time.time())}")
            shutil.copyfile(path, backup)
        path.parent.mkdir(parents=True, exist_ok=True)
        data.setdefault(key, {})["form"] = {"command": mcp_command()}
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return f"added “form” to {path}" + (f" (backup: {backup.name})" if backup else "")
    return act


def _json_has(path: Path, key: str = "mcpServers") -> bool:
    try:
        return "form" in json.loads(path.read_text(encoding="utf-8")).get(key, {})
    except (OSError, ValueError, AttributeError):
        return False


def _claude_command() -> str | None:
    """Read Claude Code's user config directly. `claude mcp get` health-checks the server and can time out on a cold start."""
    try:
        srv = json.loads((HOME / ".claude.json").read_text(encoding="utf-8")).get("mcpServers", {}).get("form")
    except (OSError, ValueError):
        return None
    return srv.get("command") if srv else None


def _codex_command() -> str | None:
    import tomllib
    path = Path(os.environ.get("CODEX_HOME", HOME / ".codex")) / "config.toml"
    try:
        srv = tomllib.loads(path.read_text(encoding="utf-8")).get("mcp_servers", {}).get("form")
    except (OSError, ValueError):
        return None
    return srv.get("command") if srv else None


def _same(a: str, b: str) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return a == b


def _agent_item(iid, label, current, mcp, summary, add_cmds, replace_cmds) -> Item:
    if not current:
        return Item(iid, label, "missing", "Installed; FORM is not registered", Fix(summary, add_cmds))
    if not Path(current).exists():
        return Item(iid, label, "warn", f"Registered, but {current} no longer exists",
                    Fix(f"Point {label} at this installation", replace_cmds))
    if not _same(current, mcp):
        return Item(iid, label, "warn", f"Registered to another FORM installation: {current}",
                    Fix(f"Point {label} at this installation", replace_cmds, recommended=False))
    return Item(iid, label, "ok", "FORM is registered")


def check(cfg: dict | None = None, studio=None) -> list[Item]:
    from . import config, slicer
    cfg = cfg or config.load()
    items: list[Item] = []
    mcp = mcp_command()

    # --- engine -----------------------------------------------------------
    v = sys.version_info
    items.append(Item("python", "Python 3.12", "ok" if (v.major, v.minor) == (3, 12) else "warn",
                      f"Running {v.major}.{v.minor}.{v.micro} at {sys.executable}",
                      None if (v.major, v.minor) == (3, 12) else
                      Fix("Reinstall FORM with uv's managed Python 3.12", ["uv tool upgrade --reinstall form-studio"])))
    try:
        if studio is not None:                                     # the app: reuse its running kernel
            kid = studio.kernel_id()
        else:
            from .worker import Kernel
            k = Kernel()
            kid = k.call("ping", timeout=120)["kernel"]
            k.stop()
        items.append(Item("kernel", "CAD kernel", "ok", kid))
    except Exception as e:                                         # broken wheel, missing OCP
        items.append(Item("kernel", "CAD kernel", "missing", f"build123d/OCP did not start: {e}",
                          Fix("Reinstall FORM and its CAD kernel", ["uv tool upgrade --reinstall form-studio"])))
    data = Path(cfg["data"]["dir"])
    try:
        data.mkdir(parents=True, exist_ok=True)
        probe = data / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        items.append(Item("data", "Project folder", "ok", str(data)))
    except OSError as e:
        items.append(Item("data", "Project folder", "missing", f"{data} is not writable: {e}",
                          Fix("Choose another folder", note="Set FORM_DATA=/some/folder or [data].dir in studio.toml.")))

    # --- slicer -----------------------------------------------------------
    s = slicer.resolve(cfg)
    if s.get("available"):
        m = s["presets"]["machine"]["name"]
        env = s.get("envelope_mm")
        items.append(Item("slicer", "Slicer (Bambu Studio)", "ok",
                          f"{slicer.version(s['app'])} · {m} · " + " / ".join(v["name"] for k, v in s["presets"].items() if k != "machine")))
        if env and [round(x) for x in env] != [round(x) for x in cfg["printer"]["envelope_mm"]]:
            items.append(Item("printer", "Printer size", "warn",
                              f"studio.toml says {cfg['printer']['envelope_mm']} mm but the selected printer is {env} mm",
                              Fix(f"Use the slicer's printer ({m}, {env[0]:.0f}×{env[1]:.0f}×{env[2]:.0f} mm)",
                                  action=_write_printer(cfg, m, env))))
        else:
            items.append(Item("printer", "Printer size", "ok", f"{cfg['printer']['name']} {cfg['printer']['envelope_mm']} mm"))
    else:
        installed = Path(s.get("app") or "/nonexistent").exists()
        if installed:
            items.append(Item("slicer", "Slicer (Bambu Studio)", "warn", s.get("reason", ""),
                              Fix("Open Bambu Studio once and select your printer, filament and process",
                                  [f"open -a BambuStudio"] if sys.platform == "darwin" else [],
                                  recommended=False,
                                  note="FORM follows whatever is selected there. Re-run `form setup` afterwards.")))
        else:
            cmds, note = [], f"Download from {BAMBU_URL}"
            if sys.platform == "darwin" and shutil.which("brew"):
                cmds = ["brew install --cask bambu-studio"]
            elif shutil.which("flatpak"):
                cmds = ["flatpak install -y flathub com.bambulab.BambuStudio"]
                note = "Then set [slicer].app to the AppImage or a wrapper script; flatpak apps need `flatpak run`."
            items.append(Item("slicer", "Slicer (Bambu Studio)", "missing",
                              "Not found. Everything except slicing works without it; slices show as BLOCKED.",
                              Fix("Install Bambu Studio (about 200 MB)", cmds, recommended=False, note=note)))

    # --- agents -----------------------------------------------------------
    if shutil.which("claude"):
        add = f"claude mcp add --scope user form -- {shlex.quote(mcp)}"
        items.append(_agent_item("agent.claude", "Claude Code", _claude_command(), mcp, "Register FORM with Claude Code (user scope)",
                                 [add], ["claude mcp remove --scope user form", add]))
    if shutil.which("codex"):
        add = f"codex mcp add form -- {shlex.quote(mcp)}"
        items.append(_agent_item("agent.codex", "Codex", _codex_command(), mcp, "Register FORM with Codex", [add],
                                 ["codex mcp remove form", add]))
    gem = HOME / ".gemini" / "settings.json"
    if shutil.which("gemini") or gem.parent.exists():
        ok = _json_has(gem)
        items.append(Item("agent.gemini", "Gemini CLI", "ok" if ok else "missing",
                          "FORM is registered" if ok else f"FORM is not in {gem}",
                          None if ok else Fix(f"Add FORM to {gem}", action=_json_register(gem))))
    cur = HOME / ".cursor" / "mcp.json"
    if cur.parent.exists() or Path("/Applications/Cursor.app").exists():
        ok = _json_has(cur)
        items.append(Item("agent.cursor", "Cursor", "ok" if ok else "missing",
                          "FORM is registered" if ok else f"FORM is not in {cur}",
                          None if ok else Fix(f"Add FORM to {cur}", action=_json_register(cur))))
    desk = (HOME / "Library/Application Support/Claude/claude_desktop_config.json" if sys.platform == "darwin"
            else HOME / ".config/Claude/claude_desktop_config.json")
    if desk.parent.exists() and (Path("/Applications/Claude.app").exists() or sys.platform != "darwin"):
        ok = _json_has(desk)
        items.append(Item("agent.desktop", "Claude Desktop", "ok" if ok else "missing",
                          "FORM is registered" if ok else f"FORM is not in {desk.name}",
                          None if ok else Fix(f"Add FORM to {desk.name} (restart Claude Desktop afterwards)",
                                              action=_json_register(desk), recommended=False)))
    # --- chat in the desktop app (app setup workstream) ------------------------
    if not shutil.which("claude"):
        cmds = ["npm install -g @anthropic-ai/claude-code"] if shutil.which("npm") else []
        items.append(Item("chat.claude", "Claude Code (chat)", "missing",
                          "Not found. Chat in the app runs Claude Code on your account; everything else works without it.",
                          Fix("Install Claude Code", cmds, recommended=False,
                              note="Then run `claude` once in a terminal to sign in. "
                                   "Other ways to install: https://docs.claude.com/en/docs/claude-code/setup")))
    if not any(i.id.startswith("agent.") for i in items):
        items.append(Item("agent.none", "Coding agent", "info",
                          "No MCP-capable agent found. Install Claude Code, Codex, Gemini CLI or Cursor, then re-run `form setup`. "
                          "Without one, the `form` CLI still works."))
    return items


def _write_printer(cfg, name, env):
    def act():
        path = Path(cfg["_path"]) if Path(cfg["_path"]).exists() else Path("~/.config/form-studio/studio.toml").expanduser()
        text = path.read_text(encoding="utf-8") if path.exists() else "# FORM configuration (written by `form setup`)\n"
        if path.exists():
            shutil.copyfile(path, path.with_name(path.name + f".bak-form-{int(time.time())}"))
        block = f'[printer]\nname = "{name}"\nenvelope_mm = [{env[0]:g}, {env[1]:g}, {env[2]:g}]\nplate_margin_mm = 2.0\n'
        import re
        if re.search(r"(?m)^\[printer\]", text):
            text = re.sub(r"(?ms)^\[printer\]\n.*?(?=^\[|\Z)", block + "\n", text)
        else:
            text = text.rstrip() + "\n\n" + block
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return f"wrote [printer] to {path}"
    return act


# ---- terminal UI ------------------------------------------------------------

def _c(code, s):
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() and not os.environ.get("NO_COLOR") else s


MARK = {"ok": _c("32", "✔"), "missing": _c("31", "✘"), "warn": _c("33", "▲"), "info": _c("36", "i")}


def _apply(item: Item, dry: bool) -> tuple[bool, str]:
    f = item.fix
    if f.action:
        if dry:
            return True, "(dry run) would edit a config file"
        try:
            return True, f.action()
        except Exception as e:
            return False, str(e)
    if not f.commands:
        return False, f.note or "Nothing to run automatically."
    for cmd in f.commands:
        print("   $", cmd)
        if dry:
            continue
        # no terminal stdin: Bun-based CLIs (claude) crash on /dev/tty with "EINVAL: invalid argument, kqueue" on macOS
        code = subprocess.call(cmd, shell=True, stdin=subprocess.DEVNULL)
        if code != 0:
            return False, f"exited with {code}"
    return True, "done" if not dry else "(dry run)"


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="form setup", description="Find what FORM needs, and fix what you choose.")
    ap.add_argument("--check", action="store_true", help="report as JSON, change nothing")
    ap.add_argument("--yes", action="store_true", help="apply recommended fixes without asking (never large downloads)")
    ap.add_argument("--dry-run", action="store_true", help="show what would run")
    a = ap.parse_args(argv)
    items = check()
    if a.check:
        print(json.dumps({"items": [i.public() for i in items], "mcp_command": mcp_command(),
                          "ready": all(i.status in ("ok", "info") for i in items if i.id in ("kernel", "data"))}, indent=1))
        return 0
    print(_c("1", "\nFORM setup") + _c("2", f"   ({mcp_command()})\n"))
    fixable = []
    for i in items:
        line = f" {MARK[i.status]} {i.label:<24} {i.detail}"
        if i.fix:
            fixable.append(i)
            line += _c("2", f"   [{len(fixable)}]")
        print(line)
    if not fixable:
        print(_c("32", "\nEverything FORM uses is set up.") + " Ask your agent for a part, or run `form serve` for the bench.\n")
        return 0
    print()
    for n, i in enumerate(fixable, 1):
        tag = "" if i.fix.recommended else _c("2", " (optional)")
        print(f"  [{n}] {i.fix.summary}{tag}")
        for c in i.fix.commands:
            print(_c("2", f"        $ {c}"))
        if i.fix.note:
            print(_c("2", f"        {i.fix.note}"))
    rec = [n for n, i in enumerate(fixable, 1) if i.fix.recommended]
    if a.yes:
        pick = rec
    else:
        try:
            ans = input(f"\nSet up which? [Enter = recommended {','.join(map(str, rec)) or 'none'} · a = all · 1,3 · n = none] ").strip().lower()
        except EOFError:
            ans = "n"
        pick = rec if ans == "" else (list(range(1, len(fixable) + 1)) if ans in ("a", "all") else
                                      [] if ans in ("n", "no", "none", "q") else
                                      [int(x) for x in ans.replace(" ", "").split(",") if x.isdigit() and 1 <= int(x) <= len(fixable)])
    if not pick:
        print("Nothing changed.")
        return 0
    failed = 0
    for n in pick:
        i = fixable[n - 1]
        print(f"\n→ {i.fix.summary}")
        ok, msg = _apply(i, a.dry_run)
        print(f"  {MARK['ok'] if ok else MARK['missing']} {msg}")
        failed += not ok
    if not a.dry_run:
        after = {i.id: i for i in check()}
        print(_c("1", "\nAfter setup"))
        for n in pick:
            i = after.get(fixable[n - 1].id)
            if i:
                print(f" {MARK[i.status]} {i.label:<24} {i.detail}")
    print("\nRestart your agent so it loads FORM. Then ask it: “design me a Gridfinity bin for my screwdrivers”.\n")
    return 1 if failed else 0
