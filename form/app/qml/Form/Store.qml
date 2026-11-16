pragma Singleton
import QtQuick
import FormNative
import "F.js" as F

// One store for the app. Screens bind to these properties; actions keep the engine,
// the 3D viewport and the panels in step. Objects are replaced, never mutated, so bindings update.
QtObject {
    id: s

    // ── state ────────────────────────────────────────────────
    property var studio: null          // { env, projects, chat, recipes, assistant }
    property string pid: ""
    property var data: null            // full project state from the engine
    property var view: null            // head geometry: { mesh, edges, bbox, volume_mm3, derived, companions, ... }
    property string screen: "boot"     // boot | home | work
    property var fatal: null
    property string stage: "shape"     // brief | shape | fit | prove | release
    property string feature: ""        // selected feature id, "" for none
    property var draftValues: ({})     // param key → value, only where it differs from head
    property var draftProv: ({})       // param key → { source, sigma }
    property string draftNote: ""
    property string draftOrigin: ""
    property string draftAgent: ""
    property var preview: null         // engine preview of the draft (geometry + impact)
    property var draftError: null
    property string job: ""
    property var running: ({})         // pipeline node → state while a job runs
    property var ack: []               // acknowledged warning ids (release gate)
    property var compare: null         // { rev, view, diff }
    property var layers: null          // { count, z, types, n } while inspecting the slice
    property var section: null         // { axis, t } ; axis "" = explicitly off
    property bool companions: true
    property bool dims: true
    property string viewName: "iso"
    property bool paletteOpen: false
    property var sheet: null           // { kind, props }
    property var toasts: []
    property var viewer: null          // the Viewport item; set by it
    property var thumbTick: ({})       // pid → counter, bumps when a project's thumbnail should reload

    // chat with Claude, and the live feed of what any agent does
    property bool talkOpen: true
    property string chatSession: ""
    property string chatJob: ""
    property int chatNext: 0
    property bool chatBusy: false
    property var chatItems: []
    property var chatTools: ({})
    property var chatLive: null
    property real actTs: Date.now() / 1000

    // ── derived ──────────────────────────────────────────────
    readonly property var project: data ? data.project : null
    readonly property var recipe: data ? data.recipe : null
    readonly property var head: project ? revision(project.head) : null
    readonly property bool hasDraft: F.keys(draftValues).length > 0 || F.keys(draftProv).length > 0
    readonly property var values: head ? Object.assign({}, head.values, draftValues) : ({})
    readonly property var shown: preview || view         // geometry currently on screen
    readonly property var chat: studio && studio.chat ? studio.chat : ({ available: false, note: "" })
    readonly property var slicer: studio ? studio.env.slicer : ({ available: false })
    readonly property var stages: [
        { id: "brief", title: "Brief", hint: "What it is for, what is known" },
        { id: "shape", title: "Shape", hint: "Select a feature, change it" },
        { id: "fit", title: "Fit", hint: "Clearance under uncertainty" },
        { id: "prove", title: "Prove", hint: "Checks and the slice" },
        { id: "release", title: "Release", hint: "Gate, history, files" }
    ]

    function revision(n) {
        if (!project) return null
        for (var i = 0; i < project.revisions.length; i++) if (project.revisions[i].n === n) return project.revisions[i]
        return null
    }
    function spec(key) {
        if (!recipe) return null
        for (var i = 0; i < recipe.params.length; i++) if (recipe.params[i].key === key) return recipe.params[i]
        return null
    }
    function featureById(id) {
        if (!recipe) return null
        for (var i = 0; i < recipe.features.length; i++) if (recipe.features[i].id === id) return recipe.features[i]
        return null
    }
    function file(rest) { return Bridge.baseUrl + "/api/projects/" + pid + "/file/" + rest }
    function thumb(id, head) { return Bridge.baseUrl + "/api/projects/" + id + "/thumb?v=" + head + "-" + (thumbTick[id] || 0) }

    // ── engine calls ─────────────────────────────────────────
    property int _rid: 0
    property var _pending: ({})
    property var _conn: Connections {
        target: Bridge
        function onReply(id, ok, payload) {
            var p = s._pending[id]
            if (!p) return
            delete s._pending[id]
            if (ok) p[0](payload); else p[1](payload)
        }
    }
    function get(path) { return new Promise(function (res, rej) { var id = ++_rid; _pending[id] = [res, rej]; Bridge.request(id, "GET", path, null) }) }
    function post(path, body) { return new Promise(function (res, rej) { var id = ++_rid; _pending[id] = [res, rej]; Bridge.request(id, "POST", path, body || ({})) }) }
    function upload(path, fileUrl) { return new Promise(function (res, rej) { var id = ++_rid; _pending[id] = [res, rej]; Bridge.upload(id, path, fileUrl) }) }
    function pget(rest) { return get("/projects/" + pid + (rest || "")) }
    function ppost(rest, body) { return post("/projects/" + pid + rest, body) }

    // ── toasts ───────────────────────────────────────────────
    property int _toastId: 0
    function toast(msg, hint, bad) {
        var t = toasts.slice(); t.push({ id: ++_toastId, msg: msg, hint: hint || "", bad: !!bad }); toasts = t
    }
    function dropToast(id) { toasts = toasts.filter(function (t) { return t.id !== id }) }
    function fail(e) { toast(e.message || "Something went wrong", e.hint, true) }

    // ── viewport coupling ────────────────────────────────────
    function sectionNow() {
        if (section) return section.axis ? section : null
        if (stage === "fit" && recipe && recipe.fit && viewer) {     // cut through the middle of the fit feature
            var sp = spec(recipe.fit.clearance), fb = sp ? viewer.featureBox(sp.feature) : null, b = viewer.bounds
            var t = fb && b ? ((fb.lo.y + fb.hi.y) / 2 - b.lo.y) / Math.max(1e-6, b.hi.y - b.lo.y) : 0.2
            return { axis: "y", t: Math.min(0.9, Math.max(0.05, t)) }
        }
        return null
    }
    function applyStageView() {
        if (!viewer) return
        viewer.showCompanions = stage === "fit" ? true : (companions && stage !== "prove")
        var sec = sectionNow()
        viewer.setSection(sec ? sec.axis : "", sec ? sec.t : 0.5)
        viewer.showDims = dims && !sec
    }
    function showHead() {
        if (!view || !viewer) return
        viewer.setModel(view)
        viewer.setGhost(compare ? compare.view : null)
        viewer.selected = feature
        Qt.callLater(applyStageView)
    }

    // ── boot / navigation ────────────────────────────────────
    function boot(startProject, startStage) {
        get("/studio").then(function (st) {
            studio = st
            var want = startProject, found = null
            for (var i = 0; i < st.projects.length; i++) if (st.projects[i].id === want && !st.projects[i].error) found = st.projects[i]
            if (found) open(found.id).then(function () { if (startStage) setStage(startStage) })
            else screen = "home"
        }, function (e) { fatal = e; screen = "home" })
    }
    function reloadStudio() { return get("/studio").then(function (st) { studio = st }) }
    function home() {
        screen = "home"; pid = ""; data = null; view = null; compare = null; layers = null; preview = null
        draftValues = ({}); draftProv = ({}); _stamp = ""
        reloadStudio()
    }
    function open(id) {
        pid = id
        draftValues = ({}); draftProv = ({}); draftNote = ""; draftOrigin = ""; draftAgent = ""
        preview = null; draftError = null; feature = ""; compare = null; layers = null; section = null; ack = []
        _stamp = ""
        return refresh(true).then(function () {
            screen = "work"; viewName = "iso"
            if (viewer) { showHead(); viewer.setView("iso", false) }
            if (data.project.auto_run !== false && !job) {
                var st = F.vals(data.status)
                for (var i = 0; i < st.length; i++) if (st[i].state !== "current") { run(); break }
            }
        }, function (e) { fail(e); screen = "home"; pid = "" })
    }
    function refresh(withView) {
        return pget().then(function (d) {
            data = d
            if (d.recovered) toast("Project recovered", d.recovered)
            if (withView || !view || view.rev !== d.project.head) {
                return pget("/view").then(function (v) {
                    v.rev = d.project.head; view = v
                    if (!hasDraft) showHead()
                }, function (e) { fail(e) })
            }
            if (!hasDraft) showHead()
        })
    }

    // ── draft: live preview with computed impact ─────────────
    property int _seq: 0
    property var _previewTimer: Timer { interval: 70; onTriggered: s.runPreview() }
    function setParam(key, value, immediate) {
        var v = Object.assign({}, draftValues)
        if (Math.abs(value - head.values[key]) < 1e-9) delete v[key]; else v[key] = value
        draftValues = v
        if (immediate) { _previewTimer.stop(); runPreview() } else _previewTimer.restart()
    }
    function setProv(key, prov) { var p = Object.assign({}, draftProv); p[key] = prov; draftProv = p }
    function loadDraft(vals, origin, note, agent) {
        var v = ({})
        for (var k in vals) if (head.values[k] !== undefined && Math.abs(vals[k] - head.values[k]) > 1e-9) v[k] = vals[k]
        draftValues = v
        if (origin !== undefined) draftOrigin = origin
        if (note !== undefined) draftNote = note
        draftAgent = agent || ""
        runPreview()
    }
    function runPreview() {
        var seq = ++_seq
        if (!F.keys(draftValues).length) {
            preview = null; draftError = null
            showHead(); if (viewer) viewer.flagged = []
            return
        }
        ppost("/preview", { values: draftValues }).then(function (pv) {
            if (seq !== _seq) return
            preview = pv; draftError = null
            if (viewer) {
                viewer.setModel(pv)
                viewer.setGhost(view)
                viewer.selected = feature
                viewer.flagged = pv.impact.features.filter(function (f) { return f.change !== "trimmed" }).map(function (f) { return f.id })
                Qt.callLater(applyStageView)
            }
        }, function (e) {
            if (seq !== _seq) return
            draftError = e                      // keep showing the last geometry that built
            if (viewer) viewer.flagged = e.feature ? [e.feature] : []
        })
    }
    function discard() {
        draftValues = ({}); draftProv = ({}); draftNote = ""; draftOrigin = ""; draftAgent = ""
        preview = null; draftError = null; _seq++
        if (viewer) viewer.flagged = []
        showHead()
    }
    function commit() {
        ppost("/commit", { values: draftValues, provenance: draftProv, note: draftNote, origin: draftOrigin || "user" }).then(function (r) {
            draftValues = ({}); draftProv = ({}); draftNote = ""; draftOrigin = ""; draftAgent = ""; preview = null; ack = []
            if (viewer) viewer.flagged = []
            toast("Committed as " + F.pad(r.head), r.job ? "Regenerating solid, exports, checks and slice." : "Auto-regenerate is off: outputs are now stale.")
            if (r.job) track(r.job)
            refresh(true)
        }, function (e) { draftError = e })
    }
    function checkout(n) {
        if (hasDraft) return toast("Commit or discard the draft first.", "", true)
        ppost("/checkout", { rev: n }).then(function (r) {
            compare = null; ack = []
            if (r.job) track(r.job)
            refresh(true)
            toast("Head is now " + F.pad(n))
        }, fail)
    }

    // ── selection ────────────────────────────────────────────
    function select(f) {
        feature = f || ""
        if (!viewer) return
        viewer.selected = feature
        if (feature) viewer.focusFeature(feature); else viewer.setView(viewName, true)
    }
    function pick(f) { if (f && stage !== "shape") setStage("shape"); select(f) }
    function hover(f) { if (viewer) viewer.hovered = f || "" }

    // ── pipeline ─────────────────────────────────────────────
    property var _poll: Timer { interval: 160; onTriggered: s._tick() }
    function run(nodes, force) { ppost("/run", { nodes: nodes || [], force: !!force }).then(function (r) { track(r.job) }, fail) }
    function settings(body) { return ppost("/settings", body).then(function (r) { if (r.job) track(r.job); return refresh() }, fail) }
    function track(id) { if (!id) return; job = id; _poll.restart() }
    function _tick() {
        var id = job
        pget("/job/" + id).then(function (j) {
            if (job !== id) return
            var r = ({})
            for (var i = 0; i < j.steps.length; i++) r[j.steps[i].node] = j.steps[i].state
            running = r
            if (j.state === "running") { _poll.restart(); return }
            job = ""; running = ({}); layers = null
            var bad = null
            for (var k = 0; k < j.steps.length; k++) if (j.steps[k].state === "failed" || j.steps[k].state === "blocked") { bad = j.steps[k]; break }
            if (!bad && j.error) bad = { label: "Pipeline", error: j.error }
            if (bad) toast(bad.label + ": " + (bad.error && bad.error.message || "stopped"), bad.error && bad.error.hint, true)
            var t = Object.assign({}, thumbTick); t[pid] = (t[pid] || 0) + 1; thumbTick = t
            refresh(true)
        }, function () { job = ""; running = ({}) })
    }

    // ── stage & view ─────────────────────────────────────────
    function setStage(id) {
        stage = id; section = null
        if (id !== "prove") layers = null
        if (id !== "release" && compare) { compare = null; if (viewer) viewer.setGhost(hasDraft ? view : null) }
        if (viewer) viewer.setMarker(null)
        applyStageView()
    }
    function setView(name) { viewName = name; if (viewer) viewer.setView(name, true) }
    function setSection(axis, t) { section = { axis: axis || "", t: t === undefined ? 0.5 : t }; applyStageView() }
    function toggleCompanions() { companions = !companions; applyStageView() }
    function toggleDims() { dims = !dims; applyStageView() }
    function setAck(id, on) { ack = on ? ack.concat([id]) : ack.filter(function (x) { return x !== id }) }

    function compareWith(n) {
        if (compare && compare.rev === n) { compare = null; if (viewer) { viewer.setGhost(null); viewer.flagged = [] } return }
        Promise.all([pget("/view?rev=" + n), pget("/diff?a=" + n + "&b=" + project.head)]).then(function (r) {
            compare = { rev: n, view: r[0], diff: r[1] }
            if (viewer) {
                viewer.setGhost(r[0])
                viewer.flagged = r[1].impact.features.filter(function (f) { return f.change !== "trimmed" }).map(function (f) { return f.id })
            }
        }, fail)
    }
    function marker(c) {
        if (!viewer) return
        asmFor(c)
        if (c.at) viewer.setMarker({ at: c.at, to: c.to })
        else if (c.feature) { viewer.setMarker(null); feature = c.feature; viewer.selected = c.feature; viewer.focusFeature(c.feature) }
    }
    function showLayers(on) {
        if (!on) { layers = null; return }
        pget("/layers").then(function (m) { m.n = Math.min(m.count - 1, 3); layers = m }, fail)
    }
    function setLayer(n) { if (layers) layers = Object.assign({}, layers, { n: n }) }
    function openSheet(kind, props) { sheet = kind ? { kind: kind, props: props || ({}) } : null }

    function create(name, recipeId, brief) {
        post("/projects", { name: name, recipe: recipeId, brief: brief || "" }).then(function (r) {
            sheet = null; stage = "shape"
            reloadStudio().then(function () { open(r.id).then(function () { track(r.job) }) })
        }, fail)
    }
    function importArchive(fileUrl) {
        upload("/import", fileUrl).then(function (r) {
            sheet = null
            reloadStudio().then(function () { open(r.id) })
            toast("Project restored", "Artifacts were re-verified against this machine’s kernel and presets.")
        }, fail)
    }

    // ── CAD bridges: imported reference parts, opening files in FreeCAD ──
    signal importPartRequested()                 // the palette asks the Brief stage to show its file dialog
    function askImportPart() { setStage("brief"); Qt.callLater(function () { s.importPartRequested() }) }
    function importPart(fileUrl) {
        var name = String(fileUrl).replace(/^.*[\/\\]/, "")
        return upload("/projects/" + pid + "/import_part?name=" + encodeURIComponent(decodeURIComponent(name)), fileUrl).then(function (r) {
            var b = r.reference.bbox, sz = [0, 1, 2].map(function (i) { return F.fmt(b[1][i] - b[0][i], 1) }).join(" × ")
            toast("Imported " + r.reference.file, sz + " mm, computed from the file. Shown in blueprint in the 3D view.")
            return refresh(true)
        }, fail)
    }
    function openIn(what, app) {
        ppost("/open", { what: what, app: app || "" }).then(function (r) { toast("Opened in " + (app === "freecad" ? "FreeCAD" : r.with), String(r.opened).replace(/^.*[\/\\]/, "")) }, fail)
    }

    // ── follow agents: any agent that writes the activity log (Claude here, Claude Code, Codex, CLI) ──
    property string _stamp: ""
    property var _watch: Timer {
        interval: 2000; repeat: true; running: s.screen === "work" && s.pid !== ""
        onTriggered: {
            if (s.job) return
            s.pget("/stamp").then(function (st) {
                var key = st.head + ":" + st.updated
                if (s._stamp && key !== s._stamp && !s.hasDraft) {
                    var last = st.last || ({})
                    if (last.origin && last.origin.indexOf("agent") === 0) s.toast(F.pad(st.head) + " by " + last.origin.replace("agent:", ""), last.note || "")
                    s.refresh(true)
                }
                s._stamp = key
            }, function () {})
        }
    }
    property var _activity: Timer {
        interval: 1200; repeat: true; running: s.screen !== "boot"
        onTriggered: s.get("/activity?since=" + s.actTs).then(function (r) {
            for (var i = 0; i < r.events.length; i++) {
                var ev = r.events[i]
                s.actTs = Math.max(s.actTs, ev.ts)
                if (ev.by === "you") continue
                if (!s.chatBusy) s.chatItems = s.chatItems.concat([{ t: "act", by: ev.by, text: ev.text }])
                s.follow(ev)
            }
        }, function () {})
    }
    readonly property var _viewMap: ({ iso: "iso", sheet: "iso", front: "front", back: "back", iso_back: "back", left: "side", right: "side", top: "top", bottom: "under" })
    function follow(ev) {
        if (!ev.project) return
        if (ev.project !== pid) {
            if (["commit", "draft", "look", "search"].indexOf(ev.kind) < 0) return
            reloadStudio().then(function () { open(ev.project) })
            toast("Following " + ev.by, ev.text)
            return
        }
        var userDraft = hasDraft && !draftAgent
        if (ev.kind === "commit") {
            if (draftAgent) discard()
            var t = Object.assign({}, thumbTick); t[pid] = (t[pid] || 0) + 1; thumbTick = t
            refresh(true)
        } else if (ev.values && F.keys(ev.values).length && !userDraft) {
            loadDraft(Object.assign({}, head.values, ev.values), "agent:" + ev.by, undefined, ev.by)
        } else if (userDraft && ev.values) {
            toast(ev.by + " is trying a change", "Your own draft is kept; discard it to watch.")
        }
        if (ev.kind === "look" && ev.view && _viewMap[ev.view]) setView(_viewMap[ev.view])
        if (ev.kind === "look" && ev.highlight) select(ev.highlight)
    }

    // ── assembly: Assembled / Exploded / Print layout (designs that declare assembly()) ──
    // The Workspace viewport binds asmMode, explode and pose; the engine's view carries `assembly` (parts, placements, joints).
    property string asmMode: "print"   // print | assembled | exploded
    property real explode: 1.0
    property var pose: ({})            // joint id → degrees or mm
    readonly property var assembly: shown && shown.assembly && !shown.assembly.error ? shown.assembly : null
    function setAsmMode(m) { asmMode = m; if (viewer) viewer.setMarker(null) }
    function setExplode(f) { explode = f }
    function setPose(id, v) { var o = Object.assign({}, pose); o[id] = v; pose = o }
    function asmFor(c) {               // a check's marker is in the frame it was computed in
        if (!assembly) return
        if (c.frame === "assembled") {
            if (asmMode !== "assembled") asmMode = "assembled"
            var o = ({}); if (c.pose && c.pose.joint) o[c.pose.joint] = c.pose.value
            pose = o
            if (c.at && c.status !== "PASS" && viewer) {   // overlaps hide inside parts: cut through the middle of the marked region
                var d = [Math.abs(c.to[0] - c.at[0]), Math.abs(c.to[1] - c.at[1]), Math.abs(c.to[2] - c.at[2])]
                var i = d[0] >= d[1] && d[0] >= d[2] ? 0 : d[1] >= d[2] ? 1 : 2, ax = ["x", "y", "z"][i]
                var b = viewer.bounds, sh = viewer.shiftTo, mid = (c.at[i] + c.to[i]) / 2 + sh[ax]
                setView(["side", "front", "top"][i])
                setSection(ax, Math.min(0.98, Math.max(0.02, (mid - b.lo[ax]) / Math.max(1e-6, b.hi[ax] - b.lo[ax]))))
            }
        } else if (c.at && asmMode !== "print") asmMode = "print"
    }
    property var _asmReset: Connections { target: s; function onPidChanged() { s.asmMode = "print"; s.pose = ({}); s.explode = 1.0 } }

    // ── chat with Claude ─────────────────────────────────────
    property var _chatPoll: Timer { interval: 600; onTriggered: s._chatTick() }
    function send(text) {
        text = (text || "").trim()
        if (!text || chatBusy) return
        chatBusy = true; talkOpen = true
        chatItems = chatItems.concat([{ t: "user", text: text }])
        post("/chat", { message: text, project: pid || null, session: chatSession || null }).then(function (r) {
            chatJob = r.id; chatNext = 1; _chatPoll.restart()
        }, function (e) { chatBusy = false; chatItems = chatItems.concat([{ t: "error", text: e.message }]) })
    }
    function _chatTick() {
        if (!chatJob) return
        get("/chat/" + chatJob + "?from=" + chatNext).then(function (r) {
            var items = chatItems.slice(), tools = Object.assign({}, chatTools), changed = false
            for (var i = 0; i < r.events.length; i++) {
                var ev = r.events[i]
                if (ev.t === "result") { tools[ev.id] = ev; changed = true }
                else if (ev.t !== "start" && ev.t !== "user") { items.push(ev); changed = true }
            }
            if (changed) { chatItems = items; chatTools = tools }
            chatNext = r.next; chatLive = r.live
            if (r.session) chatSession = r.session
            if (r.state === "running") { _chatPoll.restart(); return }
            chatBusy = false; chatJob = ""; chatLive = null
            if (r.state === "failed") chatItems = chatItems.concat([{ t: "error", text: r.error || "Claude stopped with an error." }])
            reloadStudio()
            if (pid) refresh(true)
        }, function () { _chatPoll.restart() })
    }
    function stopChat() { if (chatJob) post("/chat/" + chatJob + "/stop", {}) }
    function newChat() { chatSession = ""; chatItems = []; chatTools = ({}) }

    // ── setup and updates (app setup workstream) ─────────────
    // Nothing is installed unless the user ticks an item and presses Apply; the engine re-checks the
    // commands it runs against the ones shown here (setupShown). Updates: notice only, never installed.
    property var setup: null           // GET /setup: { items, groups, detected, required_ok, first_run, attention }
    property bool setupChecking: false
    property bool welcome: false       // the full-window first-run screen
    property var setupPick: ({})       // item id → ticked
    property var setupJob: null        // GET /setup/job/<id> while fixes run, and after
    property var update: null          // GET /updates
    property bool updateHidden: false
    readonly property var setupAttention: setup ? setup.attention : []
    function setupItem(id) { if (!setup) return null; for (var i = 0; i < setup.items.length; i++) if (setup.items[i].id === id) return setup.items[i]; return null }
    function bootSetup(headless) {
        // headless (--shot/--check) shows the welcome only for an empty data folder, so other screenshots are unaffected
        get("/setup/state").then(function (r) {
            var empty = r.fresh
            if (r.first_run && (!headless || empty)) welcome = true
            checkSetup().then(function (st) { if (st && !st.required_ok && (!headless || empty)) welcome = true })
        }, function () {})
        if (!headless) checkUpdates(false)
    }
    function checkSetup() {
        setupChecking = true
        return get("/setup").then(function (st) {
            setup = st; setupChecking = false
            var p = ({})
            for (var i = 0; i < st.items.length; i++) { var it = st.items[i]; if (it.runnable) p[it.id] = setupPick[it.id] !== undefined ? setupPick[it.id] : it["default"] }
            setupPick = p
            return st
        }, function (e) { setupChecking = false; fail(e); return null })
    }
    function setPick(id, on) { var p = Object.assign({}, setupPick); p[id] = on; setupPick = p }
    readonly property var setupChosen: F.keys(setupPick).filter(function (k) { return setupPick[k] })
    function applySetup() {
        var ids = setupChosen, shown = ({})
        if (!ids.length) return
        ids.forEach(function (id) { var it = setupItem(id); shown[id] = it && it.fix ? it.fix.commands : [] })
        post("/setup/apply", { ids: ids, shown: shown }).then(function (j) { setupJob = j; _setupPoll.restart() }, function (e) { fail(e); checkSetup() })
    }
    property var _setupPoll: Timer { interval: 500; onTriggered: s._setupTick() }
    function _setupTick() {
        if (!setupJob) return
        get("/setup/job/" + setupJob.id).then(function (j) {
            setupJob = j
            if (j.state === "running") { _setupPoll.restart(); return }
            setupPick = ({})
            checkSetup(); reloadStudio()
            toast(j.state === "done" ? "Setup finished" : "Some setup steps failed", j.state === "done" ? "Each item was checked again." : "The output is shown under each step.", j.state !== "done")
        }, function () { _setupPoll.restart() })
    }
    function closeWelcome(how) { welcome = false; post("/setup/seen", { how: how || "skipped" }).then(function () {}, function () {}) }
    function openSetup() { setupJob = setupJob && setupJob.state === "running" ? setupJob : null; openSheet("setup"); checkSetup() }
    function checkUpdates(force) {
        return get("/updates" + (force ? "?force=1" : "")).then(function (u) { update = u; return u }, function () {})
    }
    // ── design review on demand (skills workstream) ─────────
    // Sends the design-review approach (silhouette / relationships / details, three passes, six-criterion rubric)
    // for the head revision into the existing chat. No model call outside the chat.
    readonly property bool canAskReview: !!project && chat.available && !chatBusy
    function reviewPrompt() {
        if (!project) return ""
        return "Give me a design review of " + F.pad(project.head) + " of “" + project.name + "” (project " + pid + "). "
            + "Look at the current head with the FORM tools, not from memory: get_project, then render(view=\"sheet\"), "
            + "render(view=\"bottom\") and render(view=\"iso_back\").\n\n"
            + "Review at three scales. Silhouette: is the mass balanced, the useful volume clear, does it look stable and intentional? "
            + "Relationships: spacing, wall thickness, radius families, repeated features, contact points. "
            + "Details: seam, entry chamfers, finger relief, drainage, support scars, tool access, the underside and the assembled state.\n\n"
            + "Do three passes: designer (proportion, interaction, finish); engineer (interfaces, load path, assembly, tolerances, "
            + "from the checks and the fit model); print technician (orientation, layer direction at loaded roots, overhangs, "
            + "supports, seams, from the simulated slice).\n\n"
            + "Score 0 to 5: function and fit, proportion, geometric coherence, manufacturing integration, assembly and use, "
            + "visual restraint. Explain the two weakest with evidence from the renders or checks. Then list concrete defects, "
            + "each with the parameter or feature to change. Call out any critical functional defect regardless of the scores.\n\n"
            + "Do not commit anything; you may preview_change the most important fix. Say that the scores are subjective, "
            + "not a certification and not physical validation."
    }
    function askReview() { if (canAskReview) send(reviewPrompt()) }

    // ── analysis on the model: maps, measuring, print orientation (form/analysis.py) ──
    // Maps describe the committed head revision; the Workspace hides them while a draft is open.
    property string analysisMap: ""            // "" | thickness | overhang | section | features
    property var analysis: null                // the engine's map: mesh, per-vertex values and colours, legend, stats, markers
    property bool analysisBusy: false
    property int _aseq: 0
    readonly property var analysisMaps: [{ value: "", text: "None" }, { value: "thickness", text: "Thickness" }, { value: "overhang", text: "Overhang" },
                                         { value: "section", text: "Section" }, { value: "features", text: "Features" }]
    function analysisLabel(m) { for (var i = 0; i < analysisMaps.length; i++) if (analysisMaps[i].value === m) return analysisMaps[i].text; return "" }
    function setAnalysis(map) {
        analysisMap = map || ""
        var seq = ++_aseq
        if (!analysisMap) { analysis = null; analysisBusy = false; return }
        if (assembly && asmMode !== "print") setAsmMode("print")          // maps are computed on the parts as printed
        if (viewer) viewer.setMarker(null)
        analysisBusy = true
        pget("/analysis?map=" + analysisMap).then(function (r) { if (seq !== s._aseq) return; s.analysis = r; s.analysisBusy = false },
            function (e) { if (seq !== s._aseq) return; s.analysisBusy = false; s.analysisMap = ""; s.analysis = null; s.fail(e) })
    }
    function analysisCheck() {                 // the pipeline check that the shown map belongs to, if it is current
        var id = ({ thickness: "wall", overhang: "overhang" })[analysisMap], cs = data && data.checks ? data.checks.checks : []
        for (var i = 0; id && i < cs.length; i++) if (cs[i].id === id) return cs[i]
        return null
    }
    // head geometry or print orientation changed: what is shown no longer describes the part
    readonly property string analysisKey: project ? pid + "|" + project.head + "|" + project.orientation : ""
    onAnalysisKeyChanged: { if (analysisMap) setAnalysis(analysisMap); if (orient) findOrientation(); if (measures.length || measureFrom) clearMeasures() }
    property var _analysisReset: Connections { target: s; function onPidChanged() {
        s._aseq++; s.analysisMap = ""; s.analysis = null; s.analysisBusy = false; s.orient = null; s.measures = []; s.measureFrom = null; s.measuring = false; s.measureOpen = false } }

    // measure tool: click points on the part. Every number comes back from the engine (POST /probe, /measure).
    property bool measuring: false             // clicks on the part measure instead of selecting
    property bool measureOpen: false           // the readout panel is showing
    property string measureKind: "distance"    // distance | face | diameter
    property var measures: []                  // [{ id, kind, label, detail, how, label_at, ... }], kept until cleared
    property var measureFrom: null             // first point of a distance: { at: [x, y, z], snap }
    property int _mid: 0
    function setMeasuring(on) {
        measuring = !!on; measureFrom = null
        if (on) { measureOpen = true; if (assembly && asmMode !== "print") setAsmMode("print"); if (viewer) viewer.setMarker(null) }
    }
    function clearMeasures() { measures = []; measureFrom = null }
    function dropMeasure(id) { measures = measures.filter(function (m) { return m.id !== id }) }
    function _addMeasure(m) { m.id = ++_mid; measures = measures.concat([m]) }
    function measureClick(pt, reach) {         // pt: [x, y, z] on the surface, design frame; reach: snap radius in mm
        var kind = measureKind
        return ppost("/probe", { at: pt }).then(function (pr) {
            if (kind === "distance") {
                var at = pr.on, snap = "surface"
                if (pr.snaps.length && pr.snaps[0].distance_mm <= reach) { at = pr.snaps[0].at; snap = pr.snaps[0].kind }    // nearest first
                if (!s.measureFrom) { s.measureFrom = { at: at, snap: snap }; return }
                var from = s.measureFrom
                s.measureFrom = null
                return s.ppost("/measure", { from: from.at, to: at }).then(function (r) {
                    s._addMeasure({ kind: "distance", a: r.from, b: r.to, how: "computed", label: F.fmt(r.distance_mm, 2) + " mm",
                        detail: "dX " + F.fmt(Math.abs(r.dx_mm), 2) + "  dY " + F.fmt(Math.abs(r.dy_mm), 2) + "  dZ " + F.fmt(Math.abs(r.dz_mm), 2) + "  ·  " + from.snap + " to " + snap,
                        label_at: [(r.from[0] + r.to[0]) / 2, (r.from[1] + r.to[1]) / 2, (r.from[2] + r.to[2]) / 2] })
                }, s.fail)
            } else if (kind === "face") {
                var f = pr.face, feat = s.featureById(pr.feature)
                s._addMeasure({ kind: "face", at: pr.on, face: f, how: "computed", label: F.fmt(f.area_mm2, f.area_mm2 < 100 ? 2 : 1) + " mm²",
                    detail: f.type + (feat ? " of " + feat.label : "") + " · normal " + F.fmt(f.tilt_deg, 1) + "° from straight up: " + f.tilt + " · " + f.method,
                    label_at: [pr.on[0] + f.normal[0] * 7, pr.on[1] + f.normal[1] * 7, pr.on[2] + f.normal[2] * 7] })
            } else {
                var c = pr.circle
                if (!c || (c.edge_distance_mm !== undefined && c.edge_distance_mm > Math.max(reach * 2, 1.5)))
                    return s.toast("No circle here", "Click the wall of a hole or round boss, or close to its rim.")
                s._addMeasure({ kind: "diameter", at: pr.on, circle: c, how: c.method === "fitted" ? "fitted" : "computed", label: "Ø " + F.fmt(c.diameter_mm, 2) + " mm",
                    detail: (c.hole === true ? "hole" : c.hole === false ? "round boss" : c.surface || "circle") + " · "
                        + (c.method === "fitted" ? "fitted to " + c.points + " mesh edge points, rms " + F.fmt(c.rms_mm, 3) + " mm" : "exact, from the CAD solid"),
                    label_at: c.center || pr.on })
            }
        }, fail)
    }

    // print orientation finder (GET /orient): candidates ranked by a score whose terms are shown
    property var orient: null
    property bool orientBusy: false
    function findOrientation() {
        orientBusy = true
        var want = pid
        pget("/orient").then(function (r) { if (want !== s.pid) return; s.orient = r; s.orientBusy = false }, function (e) { s.orientBusy = false; s.fail(e) })
    }
}
