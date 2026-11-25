"""Whether a process is still running, on every platform.

os.kill(pid, 0) is the POSIX idiom for "does this pid exist"; on Windows os.kill with any signal other than the
console events calls TerminateProcess, so the same line would end the process it asks about. Every liveness check
in Form Studio goes through pid_alive."""
import os


def pid_alive(pid) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)            # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k32.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:                               # exists, owned by someone else
        return True
    except OSError:
        return False
