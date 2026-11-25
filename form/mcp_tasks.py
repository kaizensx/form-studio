"""MCP tasks (extension io.modelcontextprotocol/tasks, schema 2026-07-28, SEP-2663) for Form Studio's long tools.

    from form import mcp_tasks
    MCPServer(..., extensions=[mcp_tasks.tasks_extension(studio)])     # studio: () -> Studio

When a client declares the extension on a tools/call request (_meta["io.modelcontextprotocol/clientCapabilities"]
.extensions) and the tool is one of TASK_TOOLS (with the arguments that make it long), the server answers at once
with a CreateTaskResult (resultType "task", taskId, status "working", ttlMs, pollIntervalMs) and runs the call in
the background. The client polls tasks/get until the task is completed (result: the tool's CallToolResult), failed
(a JSON-RPC error) or cancelled; tasks/cancel asks it to stop. Every other call, and every call from a client that
did not declare the extension on that request, runs as it always has, and its result is unchanged.

The background call sees a context whose progress reports (ctx.report_progress) become the task's statusMessage,
and that has no elicitation, sampling or roots: a task never asks the person anything (headless clients cancel a
task that needs input), so a tool that would ask falls back to its no-elicitation path. Cancel is cooperative: the
engine stops at its next stage boundary (form/taskstore.py), before a revision is saved, and background jobs the
call started (a pipeline job, a refinement it was asked to run, an install) are cancelled too. A cancelled task says
what it kept: revisions saved before the cancel took effect, and the last stage built for a design that was not
saved (its draft). Tasks are records in <data>/.tasks (form/taskstore.py): they survive a server restart, and one
whose process stopped reads failed.

No push: subscriptions/listen with taskIds is acknowledged by the SDK without task ids, which the extension allows;
clients poll at pollIntervalMs.
"""
from __future__ import annotations

import dataclasses
import threading
import time
from collections.abc import Callable
from typing import Any, Literal

import anyio
from mcp.server.extension import Extension, MethodBinding
from mcp.shared.exceptions import MCPError
from mcp_types import CLIENT_CAPABILITIES_META_KEY, CallToolResult, InputRequiredResult, RequestParams, Result
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import Field

from . import taskstore

ID = "io.modelcontextprotocol/tasks"
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
MISSING_CAPABILITY = -32021
FOLLOW_POLL_S = 0.5
CANCEL_GRACE_S = 60.0              # after a cancel, how long children get to stop before the task is called cancelled


def _arg(a: dict, k: str, default=None):
    v = a.get(k, default)
    return default if v is None else v


# name -> when a call of it runs as a task (the arguments that make it long)
TASK_TOOLS: dict[str, Callable[[dict], bool]] = {
    "create_design": lambda a: True,
    "update_design": lambda a: True,
    "reconstruct": lambda a: True,
    "fit_params": lambda a: True,
    "optimize": lambda a: True,
    "build_candidates": lambda a: True,
    "propose_concepts": lambda a: True,
    "refine_design": lambda a: _arg(a, "action", "status") == "rerun",       # the action that starts a refinement
    "run_pipeline": lambda a: True,
    "commit_change": lambda a: bool(_arg(a, "run", True)),
    "render_photo": lambda a: True,
    "turntable": lambda a: True,
    "print_simulation": lambda a: True,
    "install_software": lambda a: _arg(a, "confirm", False) is True,
    "fetch_link": lambda a: True,
    # Blender work (registered by form.adapters.blender_model / form.game): a bake or an op replay takes minutes
    "model_mesh": lambda a: True,
    "game_asset": lambda a: _arg(a, "action", "build") in ("build", "export"),
}
TASK_TOOL_NAMES: tuple[str, ...] = tuple(TASK_TOOLS)
FOLLOW: dict[str, tuple[str, ...]] = {"refine_design": ("pipeline", "refine")}   # children a tool's task waits for
FOLLOW_DEFAULT = ("pipeline", "install")


# ---- wire models -----------------------------------------------------------------

class TaskIdParams(RequestParams):
    task_id: str = Field(alias="taskId")


class UpdateTaskParams(RequestParams):
    task_id: str = Field(alias="taskId")
    input_responses: dict[str, Any] = Field(default_factory=dict, alias="inputResponses")


class CreateTaskResult(Result):
    """Client side: the task handle a tools/call can return (for ResultClaim)."""
    result_type: Literal["task"] = "task"
    task_id: str
    status: str
    status_message: str | None = None
    created_at: str
    last_updated_at: str
    ttl_ms: int | None = None
    poll_interval_ms: int | None = None


# ---- helpers ------------------------------------------------------------------

def _caps(meta) -> dict | None:
    """The per-request client capabilities as a plain dict (2026-07-28 _meta), or None."""
    if not meta:
        return None
    caps = meta.get(CLIENT_CAPABILITIES_META_KEY) if hasattr(meta, "get") else None
    if caps is None:
        return None
    if hasattr(caps, "model_dump"):
        caps = caps.model_dump(by_alias=True, exclude_none=True)
    return caps if isinstance(caps, dict) else None


def declared(ctx) -> bool:
    """Whether this request declared the tasks extension (never inferred from earlier requests)."""
    caps = _caps(getattr(ctx, "meta", None))
    ext = (caps or {}).get("extensions") or {}
    return isinstance(ext, dict) and ID in ext


def _require(ctx) -> None:
    if not declared(ctx):
        raise MCPError(code=MISSING_CAPABILITY, message="Missing required client capability",
                       data={"requiredCapabilities": {"extensions": {ID: {}}}})


def _headless_meta(meta):
    """The request's _meta for the background call: the same, without elicitation, sampling and roots."""
    if not meta:
        return meta
    caps = _caps(meta)
    if caps is None:
        return meta
    caps = {k: v for k, v in caps.items() if k not in ("elicitation", "sampling", "roots")}
    return {**dict(meta), CLIENT_CAPABILITIES_META_KEY: caps}


def _dump(result) -> dict:
    if isinstance(result, dict):
        return dict(result)
    return result.model_dump(by_alias=True, mode="json", exclude_none=True)


class _NoClient(RuntimeError):
    pass


class TaskSession:
    """The session a background call sees: progress goes to the task; nothing is sent to the client (the request
    that started the task has already been answered), and it cannot ask the client anything."""

    def __init__(self, real, run: taskstore.TaskRun):
        self._real, self._run = real, run

    def __getattr__(self, name):
        return getattr(self._real, name)

    @property
    def client_params(self):
        return getattr(self._real, "client_params", None)

    @property
    def client_capabilities(self):
        c = getattr(self._real, "client_capabilities", None)
        if c is None or not hasattr(c, "model_copy"):
            return c
        return c.model_copy(update={"elicitation": None, "sampling": None, "roots": None})

    @property
    def can_send_request(self) -> bool:
        return False

    def check_client_capability(self, capability) -> bool:
        if any(getattr(capability, k, None) is not None for k in ("elicitation", "sampling", "roots")):
            return False
        return self._real.check_client_capability(capability)

    async def report_progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        frac = (progress / total) if total else None
        self._run.progress(message or (f"{frac * 100:.0f}%" if frac is not None else str(progress)), frac)

    async def _refuse(self, *a, **kw):
        raise _NoClient("A task cannot ask the client anything; call the tool without a task for that.")

    send_request = elicit = elicit_form = elicit_url = create_message = list_roots = send_ping = _refuse

    async def _quiet(self, *a, **kw) -> None:
        return None

    send_notification = send_log_message = send_progress_notification = send_resource_updated = _quiet
    send_resource_list_changed = send_tool_list_changed = send_prompt_list_changed = send_elicit_complete = _quiet


def _kept_text(run: taskstore.TaskRun) -> tuple[str, dict]:
    kept: dict[str, Any] = {}
    parts = []
    if run.saved:
        kept["revisions"] = dict(run.saved)
        parts.append("kept " + ", ".join(f"{p} r{h:02d}" for p, h in run.saved.items()) +
                     " (saved before the cancel took effect)")
    if run.draft and run.draft.get("draft") and not run.saved:
        kept["draft"] = run.draft
        parts.append(f"the last stage built ({run.draft.get('feature')}, stage {run.draft.get('index')}) is kept as "
                     f"draft {run.draft['draft']}, not as a revision")
    return ("; ".join(parts) if parts else "nothing was saved"), kept


# ---- the extension --------------------------------------------------------------

class TasksExtension(Extension):
    identifier = ID

    def __init__(self, studio_getter: Callable[[], Any], tools: dict[str, Callable[[dict], bool]] | None = None):
        self._studio = studio_getter
        self._tools = dict(TASK_TOOLS if tools is None else tools)
        self._store: taskstore.TaskStore | None = None
        self._root = None

    def settings(self) -> dict[str, Any]:
        return {}

    def store(self) -> taskstore.TaskStore:
        root = self._studio().root
        if self._store is None or self._root != root:
            self._store, self._root = taskstore.TaskStore(root), root
        return self._store

    def task_capable(self, name: str, arguments: dict | None) -> bool:
        pred = self._tools.get(name)
        try:
            return bool(pred and pred(arguments or {}))
        except Exception:                                # noqa: BLE001 - odd arguments: run it as today
            return False

    def methods(self):
        return (MethodBinding("tasks/get", TaskIdParams, self._get),
                MethodBinding("tasks/update", UpdateTaskParams, self._update),
                MethodBinding("tasks/cancel", TaskIdParams, self._cancel))

    # -- tools/call ---------------------------------------------------------------
    async def intercept_tool_call(self, params, ctx, call_next):
        if (getattr(ctx, "protocol_version", None) not in MODERN_PROTOCOL_VERSIONS or not declared(ctx)
                or not self.task_capable(params.name, params.arguments)):
            return await call_next(ctx)
        args = params.arguments or {}
        project = args.get("project") if isinstance(args.get("project"), str) else None
        store = self.store()
        rec = store.create(params.name, project, params.name, statusMessage=f"Starting {params.name}")
        run = taskstore.run(store, rec["taskId"], params.name)
        bg = dataclasses.replace(ctx, session=TaskSession(ctx.session, run), meta=_headless_meta(ctx.meta))
        threading.Thread(target=self._work, args=(run, call_next, bg), daemon=True,
                         name=f"task-{params.name}").start()
        return store.created(rec)

    def _work(self, run: taskstore.TaskRun, call_next, bg) -> None:
        store = run.store
        taskstore.use(run)                               # this thread's context; anyio.run and to_thread copy it
        result = error = None
        try:
            result = anyio.run(call_next, bg)
        except MCPError as e:
            error = {"code": e.code, "message": str(e.message if hasattr(e, "message") else e)}
            if getattr(e, "data", None) is not None:
                error["data"] = e.data
        except BaseException as e:                       # noqa: BLE001 - reported on the task
            error = {"code": INTERNAL_ERROR, "message": f"{type(e).__name__}: {e}"[:500]}
        try:
            self._follow(run)
            if run.cancelled():
                what, kept = _kept_text(run)
                store.finish(run.id, "cancelled", message=f"Cancelled: {what}.", **({"kept": kept} if kept else {}))
            elif error is not None:
                store.finish(run.id, "failed", error=error, message=error["message"])
            elif isinstance(result, InputRequiredResult) or (isinstance(result, dict)
                                                              and result.get("resultType") == "input_required"):
                msg = "This tool needs an answer from the person; a task cannot ask. Call it without a task."
                store.finish(run.id, "failed", error={"code": INTERNAL_ERROR, "message": msg}, message=msg)
            else:
                out = _dump(result)
                is_err = bool(out.get("isError")) if isinstance(result, (dict, CallToolResult)) else False
                store.finish(run.id, "completed", result=out,
                             message=("Finished with an error" if is_err else "Done"))
        finally:
            taskstore.done(run)

    def _follow(self, run: taskstore.TaskRun) -> None:
        """Wait for the background jobs the call started that are part of its work (its pipeline job, the
        refinement refine_design was asked to run, an install), with their progress as the status message."""
        kinds = FOLLOW.get(run.tool, FOLLOW_DEFAULT)
        t_cancel = None
        while True:
            open_ = [c for c in run.children if c["kind"] in kinds and not _safe_done(c)]
            if not open_:
                return
            if run.cancelled():
                t_cancel = t_cancel or time.monotonic()
                if time.monotonic() - t_cancel > CANCEL_GRACE_S:
                    return
            else:
                try:
                    txt = open_[0]["text"]()
                except Exception:                        # noqa: BLE001
                    txt = ""
                if txt:
                    run.progress(txt)
            time.sleep(FOLLOW_POLL_S)

    # -- tasks/* ----------------------------------------------------------------
    def _lookup(self, tid: str) -> dict:
        rec = self.store().get(tid)
        if rec is None:
            raise MCPError(code=INVALID_PARAMS, message="Failed to retrieve task: Task not found")
        return rec

    async def _get(self, ctx, params: TaskIdParams):
        _require(ctx)
        return self.store().detailed(self._lookup(params.task_id))

    async def _update(self, ctx, params: UpdateTaskParams):
        _require(ctx)
        self._lookup(params.task_id)            # Form Studio's tasks never ask for input: responses are ignored
        return {"resultType": "complete"}

    async def _cancel(self, ctx, params: TaskIdParams):
        _require(ctx)
        if self.store().request_cancel(params.task_id) is None:
            raise MCPError(code=INVALID_PARAMS, message="Failed to cancel task: Task not found")
        return {"resultType": "complete"}


def _safe_done(c: dict) -> bool:
    try:
        return bool(c["done"]())
    except Exception:                                    # noqa: BLE001
        return True


def tasks_extension(studio_getter: Callable[[], Any]) -> TasksExtension:
    """The tasks extension for MCPServer(extensions=[...]). studio_getter returns the server's Studio (its data
    folder holds the task records)."""
    return TasksExtension(studio_getter)


# ---- client side (tests, and clients built on the SDK) ------------------------------

def client_extension(poll_s: float | None = None):
    """A ClientExtension that declares tasks and resolves a task handle by polling tasks/get to its end."""
    from mcp.client.extension import ClientExtension, ResultClaim
    from mcp_types import Request
    from pydantic import TypeAdapter

    class GetTask(Request[TaskIdParams, Literal["tasks/get"]]):
        method: Literal["tasks/get"] = "tasks/get"
        params: TaskIdParams
        name_param = "taskId"

    async def resolve(handle: CreateTaskResult, cctx) -> CallToolResult:
        wait = poll_s if poll_s is not None else (handle.poll_interval_ms or taskstore.POLL_MS) / 1000
        while True:
            t = await cctx.session.send_request(GetTask(params=TaskIdParams(taskId=handle.task_id)),
                                                TypeAdapter(dict))
            if t["status"] == "completed":
                return CallToolResult.model_validate(t["result"])
            if t["status"] in ("failed", "cancelled"):
                raise MCPError(code=(t.get("error") or {}).get("code", INTERNAL_ERROR),
                               message=f"Task {t['status']}: {t.get('statusMessage', '')}")
            await anyio.sleep(wait)

    class TasksClient(ClientExtension):
        identifier = ID

        def claims(self):
            return (ResultClaim(result_type="task", model=CreateTaskResult, resolve=resolve),)

    return TasksClient()
