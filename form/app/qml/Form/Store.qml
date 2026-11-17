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

    // chat: saved conversations with an agent, and the live feed of what any agent does (chat workstream)
    property bool talkOpen: true
    property string convId: ""         // the open conversation; "" = a new one that is not saved yet
    property var conv: null            // its record: { id, title, project, agent, model, effort, resolved_model, cost_usd, … }
    property var convs: []             // every saved conversation, pinned first, then newest
    property int chatNext: 0           // how many saved events of the open conversation are loaded
    property bool chatBusy: false      // the open conversation is answering
    property var chatItems: []         // its events (user, start, text, tool, act, end, error), plus unsent local ones
    property var chatTools: ({})       // tool call id → its result
    property var chatLive: null        // what is streaming right now: { kind, name, chars, text }
    property real chatSeconds: 0
    property string chatAgent: ""      // the composer's choice; "" until the studio is loaded
    property string chatModel: ""
    property string chatEffort: ""
    property var chatAttach: []        // files attached to the next message: { id, name, kind, file, size }
    property int chatFocus: 0          // bumps when the composer should take the keyboard
    property string chatRecall: ""     // text to put back into the composer (edit the last message)
    property real actTs: Date.now() / 1000

    // ── derived ──────────────────────────────────────────────
    readonly property var project: data ? data.project : null
    readonly property var recipe: data ? data.recipe : null
    readonly property var head: project ? revision(project.head) : null
    readonly property bool hasDraft: F.keys(draftValues).length > 0 || F.keys(draftProv).length > 0
    readonly property var values: head ? Object.assign({}, head.values, draftValues) : ({})
    readonly property var shown: (scrub && scrub.view) || preview || view         // geometry currently on screen
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
        var t = toasts.slice(); t.push({ id: ++_toastId, msg: msg, hint: hint || "", bad: !!bad, ts: Date.now() }); toasts = t
        if (toasts.length > 4) toasts = toasts.slice(-4)          // a burst must not cover the screen
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
        if (!view || !viewer || scrub) return       // while a revision is being viewed from the timeline, leave it up
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
        if (viewer) { var had = !!viewer.marker; viewer.setMarker(null); if (had) viewer.setView(viewName, true) }    // a check's marker zoomed in: frame the part again
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
    // ── print simulation (LayerView.qml): open it in a given state from anywhere ──
    // o: { at: 0..1 of the slicer's time, layer: 1-based, fraction, ghost, only: [line types] | null, mode: "3d" | "2d" | "plate",
    //      copies: N (plate preview), play: true, speed }
    property var simAsk: null
    signal revealInspector(real y)     // scroll the stage inspector (y in its content; a large value = the end)
    function simulate(o) { simAsk = o || ({}); if (!layers) showLayers(true) }
    // Open a native file or folder dialog. Under the interaction tests (form/app/uitest.py) no native window opens:
    // the dialog is answered at once with a path in the test's folder, so its own onAccepted handler runs as usual.
    function ask(dlg) {
        if (!Bridge.testDir) { dlg.open(); return }
        var pick = Bridge.testPick()
        if (dlg.selectedFolder !== undefined && dlg.fileMode === undefined) dlg.selectedFolder = Bridge.fileUrl(pick || Bridge.testDir)
        else {
            var name = String(dlg.selectedFile || dlg.currentFile || "").replace(/^.*\//, "") || "file"
            dlg.selectedFile = Bridge.fileUrl(pick || (Bridge.testDir + "/" + name))
        }
        dlg.accepted()
    }
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
                s.noteAct(ev)
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

    // ── chat: conversations with an agent (chat workstream) ──
    // A conversation is saved by the engine as it streams (form/conversations.py). The open one is polled while it
    // answers; others keep running in the background (up to three at once) and show a dot in the list.
    readonly property var chatAgents: chat.agents || []
    readonly property var chatDefault: chat["default"] || ({ agent: "claude", model: "default", effort: "" })
    function agentInfo(id) { for (var i = 0; i < chatAgents.length; i++) if (chatAgents[i].id === id) return chatAgents[i]; return null }
    readonly property var chatAgentInfo: agentInfo(chatAgent)
    readonly property bool chatReady: !!chatAgentInfo && chatAgentInfo.available
    readonly property string chatAgentLabel: chatAgentInfo ? chatAgentInfo.label : "Claude Code"
    function modelLabel(agent, model) {
        var a = agentInfo(agent), ms = a ? a.models : []
        for (var i = 0; i < ms.length; i++) if (ms[i].id === model) return ms[i].label
        return model || "Default"
    }
    property var _chatInit: Connections { target: s; function onStudioChanged() { if (s.studio && !s.chatAgent) s._useDefaults() } }
    function _useDefaults() { chatAgent = chatDefault.agent; chatModel = chatDefault.model; chatEffort = chatDefault.effort }

    property var _chatPoll: Timer { interval: 250; onTriggered: s._chatTick() }
    property var _convPoll: Timer {
        interval: 3000; repeat: true
        running: s.screen !== "boot" && (s.chatBusy || s.convs.some(function (c) { return c.state === "running" }))
        onTriggered: s.loadConvs()
    }
    function loadConvs() { return get("/conversations").then(function (r) { convs = r.conversations }, function () {}) }
    function convTitle() { return conv ? conv.title : "New conversation" }

    function newChat() {
        _chatPoll.stop()
        convId = ""; conv = null; chatItems = []; chatTools = ({}); chatLive = null; chatNext = 0; chatBusy = false; chatAttach = []
        if (studio) _useDefaults()
        talkOpen = true; chatFocus++
    }
    function openConv(id) {
        if (!id) return newChat()
        _chatPoll.stop()
        // the feed is emptied first: a message of the old conversation must never be drawn under the new id
        // (its attachment thumbnails would be asked for from the wrong conversation)
        chatItems = []; chatTools = ({}); chatLive = null; chatNext = 0; chatBusy = false; chatAttach = []
        convId = id
        talkOpen = true
        return get("/conversations/" + id).then(function (r) {
            if (convId !== id) return
            _take(r)
            chatAgent = r.agent; chatModel = r.model; chatEffort = r.effort || ""
            if (r.state === "running") _chatPoll.restart()
            chatFocus++
        }, function (e) { fail(e); newChat(); loadConvs() })
    }
    // merge a reply from GET /conversations/<id>?from=chatNext into the feed
    function _take(r) {
        var items = chatItems.filter(function (it) { return !it.local }), tools = Object.assign({}, chatTools)
        for (var i = 0; i < r.items.length; i++) {
            var ev = r.items[i]
            if (ev.t === "result") tools[ev.id] = ev
            else items.push(ev)
        }
        if (r.items.length || items.length !== chatItems.length) { chatItems = items; chatTools = tools }
        chatNext = r.next; chatLive = r.live; chatSeconds = r.seconds || 0
        chatBusy = r.state === "running"
        var m = Object.assign({}, r); delete m.items; delete m.live
        conv = m
    }
    function _chatTick() {
        var id = convId
        if (!id) return
        get("/conversations/" + id + "?from=" + chatNext).then(function (r) {
            if (convId !== id) return
            var was = chatBusy
            _take(r)
            if (r.state === "running") { _chatPoll.restart(); return }
            if (was) { loadConvs(); reloadStudio(); if (pid) refresh(true) }
        }, function () { if (convId === id) _chatPoll.restart() })
    }
    function send(text) {
        text = (text || "").trim()
        if (!text || chatBusy) return
        var att = chatAttach, id = convId
        chatBusy = true; talkOpen = true; chatAttach = []; chatLive = null
        chatItems = chatItems.concat([{ t: "user", text: text, attachments: att, local: true }])
        var body = { message: text, project: pid || null, agent: chatAgent, model: chatModel || "default", effort: chatEffort,
                     attachments: att.map(function (a) { return a.id }) }
        post(id ? "/conversations/" + id + "/send" : "/conversations/send", body).then(function (r) {
            if (convId !== id) return
            convId = r.conversation; conv = r.meta
            _chatPoll.restart(); loadConvs()
        }, function (e) {
            if (convId !== id) return
            chatBusy = false; chatAttach = att
            chatItems = chatItems.concat([{ t: "error", text: e.message, local: true }])
        })
    }
    function stopChat() { if (convId) post("/conversations/" + convId + "/stop", {}).then(function () { s._chatTick() }, function () {}) }
    function lastUserText() {
        for (var i = chatItems.length - 1; i >= 0; i--) if (chatItems[i].t === "user") return chatItems[i].text
        return ""
    }
    function retryChat() { var t = lastUserText(); if (t && !chatBusy) send(t) }
    function recallChat(text) { chatRecall = ""; chatRecall = text || lastUserText(); chatFocus++ }

    // what another agent did while you watch: a quiet line in the open conversation
    function noteAct(ev) {
        if (chatBusy) return
        if (convId && conv && (!ev.project || !conv.project || ev.project === conv.project))
            post("/conversations/" + convId + "/note", { by: ev.by, text: ev.text }).then(function () { s._chatTick() }, function () {})
        else if (!convId) chatItems = chatItems.concat([{ t: "act", by: ev.by, text: ev.text, local: true }])
    }

    // the agent, model and effort for this conversation; remembered as the default for new ones
    function setChatChoice(agent, model, effort) {
        if (agent !== undefined && agent !== chatAgent) {
            chatAgent = agent
            if (model === undefined) model = "default"
            if (effort === undefined) effort = ""
        }
        if (model !== undefined) chatModel = model || "default"
        if (effort !== undefined) chatEffort = effort || ""
        var body = { agent: chatAgent, model: chatModel, effort: chatEffort }
        post("/chat/defaults", body).then(function (r) {
            if (studio) studio = Object.assign({}, studio, { chat: Object.assign({}, studio.chat, { "default": r["default"] }) })
        }, function () {})
        if (convId) post("/conversations/" + convId + "/settings", body).then(function (m) { if (convId === m.id) conv = Object.assign({}, conv, m) }, function () {})
    }

    // attachments: images, PDFs, STEP/STL. Copied into the conversation's folder; sent with the next message.
    function attachFiles(urls) {
        var list = []
        for (var i = 0; i < urls.length; i++) list.push(urls[i])
        if (!list.length) return
        var go = function (id) {
            list.forEach(function (u) {
                var name = decodeURIComponent(String(u).replace(/^.*[\/\\]/, ""))
                upload("/conversations/" + id + "/attach?name=" + encodeURIComponent(name), u).then(function (r) {
                    if (convId === id) chatAttach = chatAttach.concat(r.attachments)
                }, fail)
            })
        }
        if (convId) return go(convId)
        post("/conversations", { project: pid || null, agent: chatAgent, model: chatModel, effort: chatEffort }).then(function (m) {
            if (convId !== "") return
            convId = m.id; conv = m; go(m.id)
        }, fail)
    }
    function dropAttachment(id) { chatAttach = chatAttach.filter(function (a) { return a.id !== id }) }
    function attachmentUrl(file, cid) { return Bridge.baseUrl + "/api/conversations/" + (cid || convId) + "/file/" + file }

    function renameConv(id, title) {
        return post("/conversations/" + id + "/rename", { title: title }).then(function (m) { if (convId === id) conv = Object.assign({}, conv, m); return loadConvs() }, fail)
    }
    function pinConv(id, on) { return post("/conversations/" + id + "/pin", { on: on }).then(function () { return loadConvs() }, fail) }
    function deleteConv(id) {
        return post("/conversations/" + id + "/delete", {}).then(function () { if (convId === id) newChat(); return loadConvs() }, fail)
    }
    // opening a design shows its most recent conversation; going home shows a fresh prompt
    property var _convFollow: Connections {
        target: s
        function onPidChanged() {
            var id = s.pid
            if (id === "") { if (!s.chatBusy && s.convId) s.newChat(); return }
            if (s.conv && s.conv.project === id) return
            if (s.chatBusy) return                       // the running conversation is probably making this design
            s.get("/conversations?project=" + id).then(function (r) {
                if (s.pid !== id || s.chatBusy) return
                var best = null
                r.conversations.forEach(function (c) { if (c.messages && (!best || c.updated > best.updated)) best = c })
                if (best) { if (best.id !== s.convId) s.openConv(best.id) }
                else if (s.convId || s.chatItems.length) s.newChat()
            }, function () {})
        }
        function onScreenChanged() { if (s.screen !== "boot") s.loadConvs() }
    }

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
            if (r.onboarding) onboardStep = r.onboarding.step
            if (r.first_run && (!headless || empty)) { welcome = true; checkSoftware() }
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
    function openSetup() { openSettings("software"); checkSetup() }

    // ── installer, sign-in, settings, examples (setup workstream) ─────────────
    // The registry is form/installer.py. An install runs only for ids the user ticked (or pressed Install on), and the
    // engine refuses if the commands differ from the ones shown here. FORM never asks for a password.
    property var software: null        // GET /install: { software: [...], groups, required_ok, onboarding, platform, packaged }
    property bool softwareChecking: false
    property var installPick: ({})     // registry id → ticked
    property var installJob: null      // { id, state, steps, after, seconds, fake }
    property var installLog: []        // every log line of the current or last job
    property bool installLogOpen: false // the log drawer (opens by itself when an install fails)
    property var claudeLogin: null     // { id, state, url, lines, message }
    property var config: null          // GET /config
    property int onboardStep: 0        // first-run step the user reached (kept in the data folder)
    readonly property bool installing: !!installJob && installJob.state === "running"
    readonly property var installChosen: F.keys(installPick).filter(function (k) { return installPick[k] })
    function softwareItem(id) {
        if (!software) return null
        for (var i = 0; i < software.software.length; i++) if (software.software[i].id === id) return software.software[i]
        return null
    }
    function installStep(id) {
        if (!installJob) return null
        for (var i = 0; i < installJob.steps.length; i++) if (installJob.steps[i].id === id) return installJob.steps[i]
        return null
    }
    function checkSoftware() {
        softwareChecking = true
        return get("/install").then(function (r) {
            software = r; softwareChecking = false
            var p = ({})
            r.software.forEach(function (it) { if (it.installable) p[it.id] = installPick[it.id] !== undefined ? installPick[it.id] : it["default"] })
            installPick = p
            return r
        }, function (e) { softwareChecking = false; fail(e); return null })
    }
    function setInstallPick(id, on) { var p = Object.assign({}, installPick); p[id] = on; installPick = p }
    function installSoftware(ids) {
        var shown = ({})
        ids = (ids || installChosen).filter(function (id) { var it = softwareItem(id); return it && it.installable })
        if (!ids.length || installing) return
        ids.forEach(function (id) { shown[id] = softwareItem(id).plan.commands })
        post("/install", { ids: ids, shown: shown }).then(function (j) { installLog = j.log; installJob = j; _installPoll.restart() },
                                                           function (e) { fail(e); checkSoftware() })
    }
    function cancelInstall() { if (installJob) post("/install/job/" + installJob.id + "/cancel", {}).then(function () {}, fail) }
    property var _installPoll: Timer { interval: 400; onTriggered: s._installTick() }
    function _installTick() {
        if (!installJob) return
        get("/install/job/" + installJob.id + "?from=" + (installLog.length ? installLog[installLog.length - 1].n + 1 : 0)).then(function (j) {
            if (j.log.length) installLog = installLog.concat(j.log).slice(-800)
            installJob = j
            if (j.state === "running") { _installPoll.restart(); return }
            installPick = ({})
            checkSoftware(); checkSetup(); reloadStudio()
            toast(j.state === "done" ? "Installed" : j.state === "cancelled" ? "Install cancelled" : "Some installs failed",
                  j.state === "done" ? "Each item was checked again." : j.state === "cancelled" ? "" : "The log shows what happened.", j.state === "failed")
        }, function () { _installPoll.restart() })
    }
    function startClaudeLogin() {
        post("/claude/login", {}).then(function (j) { claudeLogin = j; _loginPoll.restart() }, fail)
    }
    function cancelClaudeLogin() { if (claudeLogin) post("/claude/login/" + claudeLogin.id + "/cancel", {}).then(function () {}, function () {}) }
    function sendClaudeCode(code) { if (claudeLogin) post("/claude/login/" + claudeLogin.id + "/code", { code: code }).then(function (j) { claudeLogin = j }, fail) }
    property var _loginPoll: Timer { interval: 700; onTriggered: s._loginTick() }
    function _loginTick() {
        if (!claudeLogin) return
        get("/claude/login/" + claudeLogin.id).then(function (j) {
            claudeLogin = j
            if (j.state === "running") { _loginPoll.restart(); return }
            checkSoftware(); reloadStudio()
            if (j.state === "done") toast("Signed in to Claude")
            else if (j.state === "failed") toast("Sign-in did not finish", j.message, true)
        }, function () { _loginPoll.restart() })
    }
    function loadConfig() { return get("/config").then(function (c) { config = c; return c }, function (e) { fail(e); return null }) }
    function saveConfig(values) {
        return post("/config", { values: values }).then(function (r) {
            config = r.config; reloadStudio()
            var n = F.keys(r.changed).length
            if (!n) toast("Nothing to change")
            else toast("Saved " + F.plural(n, "setting"), r.restart ? "The project folder changes when FORM restarts." : r.backup ? "The previous file was kept as a backup next to it." : "", false)
            return r
        }, function (e) { fail(e); return null })
    }
    // saves run one after another, so two quick presses cannot land on the engine out of order
    property var _stepSave: null
    function setOnboardStep(n) {
        onboardStep = Math.max(0, Math.min(2, n))
        var v = onboardStep, send = function () { return post("/setup/step", { step: v }).then(function () {}, function () {}) }
        _stepSave = _stepSave ? _stepSave.then(send) : send()
    }
    function openSettings(tab) { openSheet("settings", { tab: tab || "general" }); loadConfig(); checkSoftware() }
    function addExample(id) {
        return post("/examples", { ids: [id] }).then(function () { sheet = null; return reloadStudio().then(function () { return open(id) }) }, fail)
    }
    // "Update now" (pip / uv / source installs): the upgrade command runs as an install job with a streamed log.
    // The running app keeps its code until it is restarted; the sheet says so.
    property var updateJob: null       // { id, state, steps, log, seconds, fake }
    property var updateLog: []
    readonly property bool updating: !!updateJob && updateJob.state === "running"
    property var _updatePoll: Timer { interval: 400; onTriggered: s._updateTick() }
    function installUpdate() {
        if (!update || updating || installing) return
        updateLog = []
        post("/updates/install", { shown: update.command }).then(function (j) { updateLog = j.log; updateJob = j; _updatePoll.restart() }, fail)
    }
    function cancelUpdate() { if (updateJob) post("/install/job/" + updateJob.id + "/cancel", {}).then(function () {}, fail) }
    function _updateTick() {
        if (!updateJob) return
        get("/install/job/" + updateJob.id + "?from=" + (updateLog.length ? updateLog[updateLog.length - 1].n + 1 : 0)).then(function (j) {
            if (j.log.length) updateLog = updateLog.concat(j.log).slice(-400)
            updateJob = j
            if (j.state === "running") _updatePoll.restart()
        }, function () { _updatePoll.restart() })
    }
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

    // ── design tools: revision timeline, variants, quick actions (design tools workstream) ─────────
    // Scrubbing shows another revision read-only (engine /view?rev=); nothing changes until "Branch from here" (checkout).
    property bool timelineOpen: false
    property var revViews: ({})        // "<head stamp>:<n>" → engine view, so scrubbing does not rebuild
    property var scrub: null           // { rev, view } while a revision other than the head is on screen
    property bool morphing: false      // playing through the revisions
    property int tlHover: -1           // timeline tick under the pointer (index into revList)
    property var hidden: []            // feature ids hidden in the viewport (visual only; the solid is unchanged)
    property var ctxMenu: null         // { feature, x, y } while the viewport's context menu is open
    signal chatPrefill(string text)    // Talk puts this in the composer and focuses it
    signal fadeTo(var apply)           // the workspace cross-fades the picture while apply() swaps the geometry
    readonly property var revList: project ? project.revisions.slice().sort(function (a, b) { return a.n - b.n }) : []
    function who(origin) {
        var o = origin || "user"
        if (o.indexOf("agent:") === 0) return o.slice(6) || "agent"
        if (o.indexOf("proposal:") === 0) return "you (" + o.slice(9) + " proposal)"
        return o === "user" || o === "recipe" || o === "variant" ? "you" : o === "cli" ? "you (CLI)" : o
    }
    function loadRev(n) {
        var key = pid + ":" + (project ? project.updated : 0) + ":" + n
        if (revViews[key]) return Promise.resolve(revViews[key])
        if (n === project.head && view) return Promise.resolve(view)
        return pget("/view?rev=" + n).then(function (v) {
            v.rev = n
            var c = ({}), ks = F.keys(revViews).filter(function (k) { return k.indexOf(pid + ":" + project.updated + ":") === 0 })
            ks.forEach(function (k) { c[k] = revViews[k] })
            c[key] = v; revViews = c
            return v
        })
    }
    function _showScrub(n, v) {
        if (!viewer) return
        if (n === project.head) { scrub = null; if (preview) { viewer.setModel(preview); viewer.setGhost(view) } else showHead() }
        else { scrub = { rev: n, view: v }; viewer.flagged = []; viewer.setModel(v); viewer.setGhost(null) }
    }
    function showRev(n, fade) {
        if (!project) return Promise.resolve()
        return loadRev(n).then(function (v) {
            if (fade) fadeTo(function () { s._showScrub(n, v) }); else s._showScrub(n, v)
        }, fail)
    }
    function endScrub() { stopMorph(); if (scrub) showRev(project.head, true) }
    property int _morphAt: 0
    property var _morphTimer: Timer { interval: 950; onTriggered: s._morphStep() }
    function playMorph() {
        if (!project || revList.length < 2) return
        if (morphing) return stopMorph()
        morphing = true; _morphAt = 0
        Promise.all(revList.map(function (r) { return s.loadRev(r.n) })).then(function () { if (s.morphing) s._morphStep() }, function (e) { s.morphing = false; s.fail(e) })
    }
    function _morphStep() {
        if (!morphing) return
        if (_morphAt >= revList.length) { morphing = false; showRev(project.head, true); return }
        showRev(revList[_morphAt].n, true)
        _morphAt += 1
        _morphTimer.restart()
    }
    function stopMorph() { morphing = false; _morphTimer.stop() }
    function branchFrom(n) { stopMorph(); scrub = null; checkout(n) }
    property var _scrubReset: Connections { target: s
        function onPidChanged() { s.scrub = null; s.morphing = false; s.hidden = []; s.ctxMenu = null; s.revViews = ({}) } }

    // variants (form/variants.py): named sets of values kept in the project
    function saveVariant(name, values, source, note) {
        return ppost("/variant_save", { name: name, values: values || null, source: source || "", note: note || "" }).then(function (r) {
            toast("Saved variant “" + r.variant.name + "”", r.variant.rev ? "It is " + F.pad(r.variant.rev) + "." : "A saved draft: not a revision until you promote it.")
            return refresh()
        }, fail)
    }
    function promoteVariant(id) {
        if (hasDraft) return toast("Commit or discard the draft first.", "", true)
        return ppost("/variant_promote", { id: id }).then(function (r) {
            toast("Head is now " + F.pad(r.head), "Variant promoted: " + r.how + ".")
            if (r.job) track(r.job)
            return refresh(true)
        }, fail)
    }
    function deleteVariant(id) { return ppost("/variant_delete", { id: id }).then(function () { return refresh() }, fail) }

    // quick actions on the model
    function toggleHidden(f) { if (!f) return; hidden = hidden.indexOf(f) >= 0 ? hidden.filter(function (x) { return x !== f }) : hidden.concat([f]) }
    function showAll() { hidden = [] }
    function frameSelection() { if (!viewer) return; if (feature) viewer.focusFeature(feature); else viewer.setView(viewName, true) }
    function resetView() { section = null; viewName = "iso"; if (viewer) viewer.setView("iso", true); applyStageView() }
    function toggleSection() { var now = sectionNow(); setSection(now ? "" : "y", 0.5) }
    function featureDims(f) {
        var b = viewer ? viewer.featureBox(f) : null
        return b ? [b.hi.x - b.lo.x, b.hi.y - b.lo.y, b.hi.z - b.lo.z] : null
    }
    function featureText(f) {              // a feature's size and parameters as plain text
        var ft = featureById(f); if (!ft || !project) return ""
        var d = featureDims(f), lines = [ft.label + " — " + project.name + " " + F.pad(scrub ? scrub.rev : project.head)]
        if (d) lines.push("Extent: " + F.fmt(d[0], 1) + " × " + F.fmt(d[1], 1) + " × " + F.fmt(d[2], 1) + " mm (computed)")
        recipe.params.filter(function (p) { return p.feature === f }).forEach(function (p) {
            lines.push(p.label + ": " + F.trim(values[p.key]) + (p.unit ? " " + p.unit : "")) })
        if (shown && shown.derived) shown.derived.filter(function (x) { return x.feature === f }).forEach(function (x) {
            lines.push(x.label + ": " + F.trim(x.value) + (x.unit ? " " + x.unit : "") + " (derived)") })
        return lines.join("\n")
    }
    function overallText() {
        if (!shown || !project) return ""
        var b = shown.bbox
        return project.name + " " + F.pad(scrub ? scrub.rev : project.head) + ": " + F.fmt(b[1][0] - b[0][0], 1) + " × " + F.fmt(b[1][1] - b[0][1], 1) + " × "
            + F.fmt(b[1][2] - b[0][2], 1) + " mm, " + F.fmt(shown.volume_mm3 / 1000, 1) + " cm³ (computed)"
    }
    function copyDims(f) { var t = f ? featureText(f) : overallText(); if (t) { Bridge.copy(t); toast("Copied", t.split("\n")[0]) } }
    function askAbout(f) {
        var ft = featureById(f); if (!ft) return
        var ps = recipe.params.filter(function (p) { return p.feature === f }).map(function (p) { return p.label + " " + F.trim(values[p.key]) + (p.unit ? " " + p.unit : "") })
        talkOpen = true
        chatPrefill("About the “" + ft.label + "” feature (" + f + ") of " + project.name + ", " + F.pad(project.head)
            + (ps.length ? ": " + ps.join(", ") : "") + ". ")
    }

    // ── app shell: column width, lightbox, palette memory, project housekeeping ──
    property real talkWidth: 340                 // the agent column in a project; dragged by its edge, remembered by Main.qml
    property var lightbox: null                  // { url, caption, note } — an image shown large over the window
    function showImage(url, caption, note) { lightbox = { url: url, caption: caption || "", note: note || "" } }
    property var paletteRecent: []               // ids of the commands run last, newest first (remembered by Main.qml)
    function notePaletteRun(id) { if (!id) return; var r = paletteRecent.filter(function (x) { return x !== id }); r.unshift(id); paletteRecent = r.slice(0, 8) }
    function renameProject(id, name) {
        return post("/projects/" + id + "/rename", { name: name }).then(function (r) { reloadStudio(); if (id === s.pid) refresh(false); return r }, fail)
    }
    function duplicateProject(id) {
        return post("/projects/" + id + "/duplicate", {}).then(function (r) { reloadStudio(); toast("Duplicated as “" + r.name + "”", "The copy is not released; approve it on its own."); return r }, fail)
    }
    // Moves the folder to .trash inside the projects folder. Nothing is erased.
    function deleteProject(id) {
        return post("/projects/" + id + "/delete", {}).then(function (r) {
            if (id === s.pid) home(); else reloadStudio()
            toast("Moved to the trash", "It is in .trash inside your projects folder until you remove it."); return r }, fail)
    }
}
