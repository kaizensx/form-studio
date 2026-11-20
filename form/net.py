"""Outgoing HTTPS for the engine: one SSL context that works inside the packaged app.

The packaged app has no system Python, so OpenSSL's default certificate folder does not exist and every https
request fails with CERTIFICATE_VERIFY_FAILED (seen as "Could not read https://…: <urlopen error …>" when an agent
reads a datasheet). certifi's CA bundle is shipped with the app; use it whenever it is there.
"""
from __future__ import annotations

import os
import ssl
import urllib.request

_CTX: ssl.SSLContext | None = None


def ca_file() -> str | None:
    try:
        import certifi
        path = certifi.where()
        return path if os.path.isfile(path) else None
    except Exception:
        return None


def ssl_context() -> ssl.SSLContext:
    global _CTX
    if _CTX is None:
        ctx = ssl.create_default_context()
        ca = ca_file()
        if ca:
            ctx.load_verify_locations(cafile=ca)        # in addition to the system store, never instead of it
        _CTX = ctx
    return _CTX


def urlopen(req, timeout: float = 30):
    """urllib.request.urlopen with certificates that work in the packaged app. Loopback URLs need no context."""
    url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
    if url.startswith("https://"):
        return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())
    return urllib.request.urlopen(req, timeout=timeout)


def plain_error(e: BaseException, host: str) -> str:
    """Why a request failed, in words a person reads: never the OS's "[Errno 8] nodename nor servname provided"."""
    import socket
    r = getattr(e, "reason", e)
    if isinstance(r, socket.gaierror) or "nodename nor servname" in str(r) or "Name or service not known" in str(r):
        return f"Form Studio could not find {host}. Check the address, and that this computer is online."
    if isinstance(r, (TimeoutError, socket.timeout)) or "timed out" in str(r):
        return f"{host} did not answer in time."
    if isinstance(r, ConnectionRefusedError):
        return f"{host} refused the connection."
    if isinstance(r, ssl.SSLError) or "CERTIFICATE" in str(r).upper():
        return f"The secure connection to {host} could not be checked."
    if isinstance(r, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return f"The connection to {host} was cut off."
    return f"Could not reach {host}."
