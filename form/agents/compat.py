"""Which versions of each agent CLI this Form Studio was checked against, and a plain error when a failure is
explained by a version outside that range.

TESTED lists, per adapter, the lowest and highest version Form Studio's adapter was written and checked against
(by a live run, or by the CLI's --help and its documented output format; each adapter's `verified` says which).
"x" in the last place means any patch release of that minor version. A version outside the range is not an error
by itself: it is named only when a run also fails the way a changed command line or output format fails (an
unknown flag, or output Form Studio could not read), so a working newer CLI never gets a warning.
"""
from __future__ import annotations

import re
import subprocess

TESTED: dict[str, tuple[str, str]] = {
    "claude": ("2.1.312", "2.1.x"),           # live runs on this Form Studio version
    "codex": ("0.164.0", "0.164.x"),          # live runs; `codex exec --json` and its session files
    "gemini": ("0.68.0", "0.68.x"),           # a live run up to the sign-in error, plus `gemini --help`
    "opencode": ("1.19.6", "1.19.x"),         # `opencode run --help` and its run command's source
    "qwen": ("0.28.0", "0.28.x"),             # `qwen --help` and its stream-json output adapter
    "copilot": ("1.0.113", "1.0.x"),          # `copilot --help` and `copilot help permissions`
}

# what a CLI prints when it does not know a flag or a value Form Studio passed (clap, commander, yargs, argparse)
FLAG_ERRORS = re.compile(
    r"unexpected argument|unknown (?:option|argument|flag|command)|unrecognized (?:option|argument|arguments)"
    r"|invalid value .{0,40}for|no such (?:option|flag|subcommand)|found argument .{0,80} which wasn't expected"
    r"|error: unknown|not a valid (?:option|flag)|did you mean", re.I)

_VERSIONS: dict = {}


def parse(text: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    return tuple(int(x) for x in m.groups() if x is not None) if m else None


def _bound(v: str, high: bool) -> tuple:
    parts = v.split(".")
    nums = [int(x) for x in parts if x.isdigit()]
    if parts and parts[-1] == "x":
        return tuple(nums) + ((10**9,) if high else (0,))
    return tuple(nums)


def version(exe: str, timeout: float = 8.0) -> str | None:
    """`<cli> --version`, cached per executable for the life of the process."""
    if exe not in _VERSIONS:
        try:
            r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
            v = parse((r.stdout or "") + " " + (r.stderr or ""))
            _VERSIONS[exe] = ".".join(map(str, v)) if v else None
        except (OSError, subprocess.SubprocessError):
            _VERSIONS[exe] = None
    return _VERSIONS[exe]


def outside(agent: str, ver: str | None) -> str | None:
    """"older" | "newer" | None (inside the range, unknown, or no range for this agent)."""
    rng, v = TESTED.get(agent), parse(ver or "")
    if not rng or not v:
        return None
    lo, hi = _bound(rng[0], False), _bound(rng[1], True)
    pad = lambda t, n: tuple(t) + (0,) * (n - len(t))
    n = max(len(lo), len(hi), len(v))
    if pad(v, n) < pad(lo, n):
        return "older"
    if pad(v, n) > pad(hi, n):
        return "newer"
    return None


def range_text(agent: str) -> str:
    lo, hi = TESTED[agent]
    if hi.endswith(".x") and lo.startswith(hi[:-1]):
        return hi                                     # "0.164.x"
    return lo if lo == hi else f"{lo}–{hi}"


def diagnose(agent: str, label: str, exe: str, rc: int | None, stderr: str, unread_lines: int, events: int,
             form_version: str = "") -> dict | None:
    """{"message", "hint"} when this failure is most likely a CLI version Form Studio does not handle, else None.

    Only for a failed run (rc != 0, or no events at all) whose output shows an interface problem: the CLI refused a
    flag Form Studio passed, or it printed lines Form Studio could not read and nothing it could."""
    if agent not in TESTED or (rc == 0 and events):
        return None
    flag = bool(FLAG_ERRORS.search(stderr or ""))
    unreadable = unread_lines > 0 and events == 0
    if not (flag or unreadable):
        return None
    ver = version(exe)
    side = outside(agent, ver)
    if not side:
        return None
    rng = range_text(agent)
    fs = f"Form Studio {form_version}" if form_version else "This Form Studio"
    what = "did not accept the command line Form Studio sends" if flag else "printed output Form Studio cannot read"
    if side == "newer":
        return {"message": f"{label} {ver} {what}. {fs} is tested with {label} {rng}; you have {ver}.",
                "hint": f"Update Form Studio (a newer release may support {label} {ver}), or install {label} {rng}."}
    return {"message": f"{label} {ver} {what}. {fs} is tested with {label} {rng}; you have {ver}, which is older.",
            "hint": f"Update {label} to {TESTED[agent][0]} or newer."}
