"""Entry point of the packaged desktop app.

The same executable also serves as FORM's MCP server and CLI, so the app can hand itself to Claude Code
(`FORM -m form.mcp_server`) and to the CAD kernel worker without a separate Python on the machine.
"""
import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()          # the CAD kernel runs in a spawned worker process
    import os
    try:                                      # https from inside the bundle, and for programs started from it
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except Exception:
        pass
    argv = sys.argv[1:]
    if argv[:2] == ["-m", "form.mcp_server"]:
        from form.mcp_server import main as mcp
        return mcp(argv[2:]) or 0
    if argv[:2] == ["-m", "form.meshguard"]:   # the export's mesher in a child process (form/meshguard.py)
        from form.meshguard import main as meshguard
        return meshguard(argv[2:]) or 0
    if argv[:1] == ["cli"]:
        from form.__main__ import main as cli
        return cli(argv[1:]) or 0
    from form.app.main import main as app
    return app(argv)


if __name__ == "__main__":
    raise SystemExit(main())
