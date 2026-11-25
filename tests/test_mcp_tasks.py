"""MCP tasks (io.modelcontextprotocol/tasks): long tools answer with a task handle only for a client that declares the
extension; the task is polled to completed, cancelled cooperatively, and kept on disk across a server restart."""
import asyncio
import functools
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Literal

from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp_types import Request
from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from form import mcp_server, mcp_tasks, taskstore  # noqa: E402

BOX = '''"""A plain box."""
from build123d import Box

from form.recipes.base import Feature, Param, Recipe, Stage


class Design(Recipe):
    title = "Task box"
    params = [Param("w", "Width", 30.0, 10, 80, 1, "mm", "form", "body")]
    features = [Feature("body", "Body", "structure")]

    def build(self, v):
        return [Stage("body", Box(v["w"], 20, 10))]
'''


class GetTask(Request[mcp_tasks.TaskIdParams, Literal["tasks/get"]]):
    method: Literal["tasks/get"] = "tasks/get"
    params: mcp_tasks.TaskIdParams
    name_param = "taskId"


class CancelTask(Request[mcp_tasks.TaskIdParams, Literal["tasks/cancel"]]):
    method: Literal["tasks/cancel"] = "tasks/cancel"
    params: mcp_tasks.TaskIdParams
    name_param = "taskId"


def server(with_tasks: bool = True):
    """mcp_server.build() with the tasks extension registered (package C does this in mcp_server itself)."""
    if not with_tasks:
        return mcp_server.build()
    real = mcp_server.MCPServer
    mcp_server.MCPServer = functools.partial(real, extensions=[mcp_tasks.tasks_extension(mcp_server.studio)])
    try:
        return mcp_server.build()
    finally:
        mcp_server.MCPServer = real


async def get(c, tid):
    return await c.session.send_request(GetTask(params=mcp_tasks.TaskIdParams(taskId=tid)), TypeAdapter(dict))


async def until_done(c, tid, timeout=180):
    t0 = time.monotonic()
    while True:
        t = await get(c, tid)
        if t["status"] in taskstore.TERMINAL:
            return t
        if time.monotonic() - t0 > timeout:
            raise AssertionError(f"task still {t['status']}: {t.get('statusMessage')}")
        await asyncio.sleep(0.2)


class Tasks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.env = {k: os.environ.get(k) for k in ("FORM_DATA", "FORM_REFINE")}
        os.environ["FORM_DATA"] = cls.tmp.name
        os.environ["FORM_REFINE"] = "off"            # refinement is not what these tests are about
        mcp_server.S["studio"] = None

    @classmethod
    def tearDownClass(cls):
        st = mcp_server.S.get("studio")
        if st is not None:
            try:
                st.kernel.stop()
            except Exception:
                pass
        mcp_server.S["studio"] = None
        for k, v in cls.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cls.tmp.cleanup()

    def test_tasks(self):
        asyncio.run(self._tasks())

    async def _tasks(self):
        st = mcp_server.studio()
        srv = server()
        async with Client(srv) as plain, Client(srv, extensions=[mcp_tasks.client_extension(0.2)]) as tc, \
                Client(server(with_tasks=False)) as bare:
            # the server advertises the extension; a sync tool answers as always
            p = json.loads((await plain.call_tool("create_project", {"name": "Task dock", "recipe": "dock",
                                                                      "run": False})).content[0].text)
            pid = p["project"]

            # a client that did not declare tasks gets today's result, the same as a server without the extension
            for name, args in (("print_simulation", {"project": pid}), ("describe_recipe", {"recipe": "dock"})):
                a = (await plain.call_tool(name, args)).model_dump()
                b = (await bare.call_tool(name, args)).model_dump()
                self.assertEqual(a, b, name)
            r = await plain.session.call_tool("run_pipeline", {"project": pid}, allow_claimed=True)
            self.assertEqual(type(r).__name__, "CallToolResult")

            # a declaring client gets a task handle, durable at once, and it reaches completed
            h = await tc.session.call_tool("run_pipeline", {"project": pid}, allow_claimed=True)
            self.assertIsInstance(h, mcp_tasks.CreateTaskResult)
            self.assertEqual(h.result_type, "task")
            self.assertEqual(h.status, "working")
            self.assertEqual(h.ttl_ms, taskstore.TTL_MS)
            self.assertEqual(h.poll_interval_ms, taskstore.POLL_MS)
            self.assertTrue(h.task_id.startswith(f"run_pipeline.{pid}."))
            self.assertTrue((Path(st.root) / ".tasks" / f"{h.task_id}.json").is_file())
            done = await until_done(tc, h.task_id)
            self.assertEqual(done["status"], "completed", done)
            self.assertEqual(done["resultType"], "complete")
            body = json.loads(done["result"]["content"][0]["text"])
            self.assertEqual(body["state"], "done", body)

            # the client extension resolves a handle transparently: call_tool returns the final CallToolResult
            fin = await tc.call_tool("run_pipeline", {"project": pid})
            self.assertFalse(fin.is_error)
            self.assertEqual(json.loads(fin.content[0].text)["state"], "done")

            # not task-capable with these arguments: synchronous even for a declaring client
            r = await tc.session.call_tool("refine_design", {"project": pid}, allow_claimed=True)
            self.assertEqual(type(r).__name__, "CallToolResult")

            # protocol errors: unknown task, and a client that did not declare the extension
            with self.assertRaises(MCPError) as e:
                await get(tc, "run_pipeline.x.nope")
            self.assertEqual(e.exception.code, -32602)
            with self.assertRaises(MCPError) as e:
                await get(plain, h.task_id)
            self.assertEqual(e.exception.code, -32021)

            # cancel: the pipeline stops between steps; the task ends cancelled
            slow = st._make_exports

            def slow_exports(*a, **kw):
                time.sleep(2.0)
                return slow(*a, **kw)
            st._make_exports = slow_exports
            try:
                h2 = await tc.session.call_tool("run_pipeline", {"project": pid, "force": True}, allow_claimed=True)
                await asyncio.sleep(0.6)
                await tc.session.send_request(CancelTask(params=mcp_tasks.TaskIdParams(taskId=h2.task_id)),
                                              TypeAdapter(dict))
                t2 = await until_done(tc, h2.task_id)
            finally:
                st._make_exports = slow
            self.assertEqual(t2["status"], "cancelled", t2)
            jobs = [j for j in st.jobs.values() if j.get("project") == pid]
            self.assertIn("cancelled", [j["state"] for j in jobs])
            last = max(jobs, key=lambda j: j["started"])
            self.assertIn("cancelled", [s["state"] for s in last["steps"]])

            # cancel before the revision is saved: no half-written revision, nothing new on disk
            heads = {d.name for d in Path(st.root).iterdir() if (d / "project.json").is_file()}
            real_try = st._try_design

            def slow_try(*a, **kw):
                out = real_try(*a, **kw)
                time.sleep(1.5)
                return out
            st._try_design = slow_try
            try:
                h3 = await tc.session.call_tool("create_design", {"name": "Task box", "source": BOX, "run": False,
                                                                  "refine": "off"}, allow_claimed=True)
                await asyncio.sleep(0.3)
                await tc.session.send_request(CancelTask(params=mcp_tasks.TaskIdParams(taskId=h3.task_id)),
                                              TypeAdapter(dict))
                t3 = await until_done(tc, h3.task_id)
            finally:
                st._try_design = real_try
            self.assertEqual(t3["status"], "cancelled", t3)
            self.assertIn("not as a revision", t3["statusMessage"])           # the built stage is kept as a draft
            self.assertTrue(t3["_meta"]["form/kept"]["draft"]["draft"].startswith("draft-"))
            self.assertIsNotNone(st.draft(t3["_meta"]["form/kept"]["draft"]["draft"]))
            after = {d.name for d in Path(st.root).iterdir() if (d / "project.json").is_file()}
            self.assertEqual(after, heads)

            # cancelling a finished task is acknowledged and changes nothing
            await tc.session.send_request(CancelTask(params=mcp_tasks.TaskIdParams(taskId=h.task_id)),
                                          TypeAdapter(dict))
            self.assertEqual((await get(tc, h.task_id))["status"], "completed")
            done_job = json.loads(fin.content[0].text)["job"]

        # a restart: a new server over the same data folder still answers tasks/get, and get_job finds the job
        mcp_server.S["studio"] = None
        st2 = mcp_server.studio()
        self.assertIsNot(st2, st)
        self.assertIn(done_job, st2.jobs)
        self.assertEqual(st2.jobs[done_job]["state"], "done")
        async with Client(server(), extensions=[mcp_tasks.client_extension(0.2)]) as tc2:
            again = await get(tc2, h.task_id)
            self.assertEqual(again["status"], "completed")
            self.assertEqual(again["result"], done["result"])
            gj = json.loads((await tc2.call_tool("get_job", {"project": pid, "job": done_job,
                                                             "wait_s": 0})).content[0].text)
            self.assertEqual(gj["state"], "done")
        st.kernel.stop()


class Store(unittest.TestCase):
    def test_process_gone_reads_failed_and_ttl(self):
        with tempfile.TemporaryDirectory() as d:
            s = taskstore.TaskStore(d)
            rec = s.create("render_photo", "p1")
            dead = subprocess.Popen([sys.executable, "-c", "pass"])
            dead.wait()
            f = s.path(rec["taskId"])
            body = json.loads(f.read_text())
            body["os_pid"] = dead.pid
            f.write_text(json.dumps(body))
            got = taskstore.TaskStore(d).get(rec["taskId"])               # another process reading it
            self.assertEqual(got["status"], "failed")
            self.assertEqual(got["error"]["code"], -32603)
            w = s.detailed(got)
            self.assertEqual(w["resultType"], "complete")
            self.assertIn("error", w)

            old = s.create("optimize", "p1")
            body = json.loads(s.path(old["taskId"]).read_text())
            body["created"] = time.time() - taskstore.TTL_MS / 1000 - 5
            s.path(old["taskId"]).write_text(json.dumps(body))
            self.assertIsNone(s.get(old["taskId"]))
            self.assertFalse(s.path(old["taskId"]).exists())

    def test_ids_unguessable_and_cancel_marker(self):
        with tempfile.TemporaryDirectory() as d:
            s = taskstore.TaskStore(d)
            a, b = s.create("fit_params", "p 1/x"), s.create("fit_params", "p 1/x")
            self.assertNotEqual(a["taskId"], b["taskId"])
            kind, proj, rnd = a["taskId"].split(".")
            self.assertEqual((kind, proj), ("fit_params", "p-1-x"))
            self.assertGreaterEqual(len(rnd), 24)
            run = taskstore.run(s, a["taskId"], "fit_params")
            tok = taskstore.use(run)
            try:
                self.assertFalse(taskstore.cancelled())
                taskstore.TaskStore(d).request_cancel(a["taskId"])       # e.g. from the app
                time.sleep(0.25)
                self.assertTrue(taskstore.cancelled())
            finally:
                taskstore._CURRENT.reset(tok)
                taskstore.done(run)
            s.finish(a["taskId"], "cancelled", message="Cancelled: nothing was saved.")
            self.assertEqual(s.get(a["taskId"])["status"], "cancelled")
            self.assertFalse(s.cancel_requested(a["taskId"]))

    def test_task_tools_exist(self):
        names = {t.name for t in asyncio.run(mcp_server.build().list_tools())}
        self.assertLessEqual(set(mcp_tasks.TASK_TOOL_NAMES), names)
        self.assertEqual(len(asyncio.run(server().list_tools())), len(names))      # the extension adds no tool


if __name__ == "__main__":
    unittest.main()
