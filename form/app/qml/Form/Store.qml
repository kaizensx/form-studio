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
    property var backdrop: null        // the room behind the panes of the screen in front (what Glass blurs): the 3D view, or the window's Room
    property bool floorGrid: false     // the 10 mm grid on the studio floor (the grid button beside the views)
    property real barY: 100000         // the conversation bar in the window (Main.qml): its top edge, left edge and width
    property real barRestY: 100000     // its top edge once no build plays (during one the bar is one line)
    property real barX: 0
    property bool talkDragging: false  // its edge is being dragged: what follows it follows at once
    property real talkCol: 0           // a workspace's conversation column: its right edge (0: folded to the bar)
    property real barW: 600
    property int buildAt: 0            // the build-up playing in the workspace: which step of how many (0: none)
    property int buildOf: 0
    property var builtIds: []          // features already in place in the build that is playing (the Program listing ticks them)
    property var thumbTick: ({})       // pid → counter, bumps when a project's thumbnail should reload

    // chat: saved conversations with an agent, and the live feed of what any agent does (chat workstream)
    property bool talkOpen: true
    // Calm: a click into the 3D view or Esc folds an open conversation column to the bar, without forgetting that it
    // is open. The prompt under the part is written in as it is; sending a message, the bar's status line or Ctrl+J
    // bring the column back. Focus (Ctrl+.) hides both side columns.
    property bool talkCalm: false
    property bool focusView: false
    property bool paneFolded: false    // the pane on the right folded to its button by hand (its tab), until it is asked back
    onTalkOpenChanged: talkCalm = false
    onChatAskingChanged: if (chatAsking) talkCalm = false
    onScreenChanged: { talkCalm = false; focusView = false; paneFolded = false }
    function toggleTalk() { if (focusView) { focusView = false; talkCalm = false; talkOpen = true } else if (talkOpen && talkCalm) talkCalm = false; else talkOpen = !talkOpen }
    property string convId: ""         // the open conversation; "" = a new one that is not saved yet
    property var conv: null            // its record: { id, title, project, agent, model, effort, resolved_model, cost_usd, … }
    property var convs: []             // every saved conversation, pinned first, then newest
    property var convBranches: []      // the open conversation's thread: the first conversation, then its branches
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
    property var chatAsking: null      // the agent's open question (ask_user), while it waits for your answer
    property real actTs: Date.now() / 1000

    // ── derived ──────────────────────────────────────────────
    readonly property var project: data ? data.project : null
    readonly property var recipe: data ? data.recipe : null
    readonly property var head: project ? revision(project.head) : null
    // a partial revision (form/featureprog.py): features left out, a feature that hung, or parts still to come
    readonly property var partial: head && head.partial ? head.partial : null
    readonly property string partialLine: {
        var p = partial
        if (!p) return ""
        var out = (p.skipped || []).filter(function (x) { return !x.not_tried }).map(function (x) { return x.feature })
        var hang = p.hang && p.hang.feature ? p.hang : null
        var t = hang ? hang.feature + (hang.kind === "crash" ? " crashed the geometry kernel" : " did not finish")
                       + (hang.s ? " after " + Number(hang.s).toFixed(1) + " s" : "")
                     : out.length ? "Left out: " + out.join(", ") : ""
        if (p.parts) t += (t ? ". " : "") + p.parts.built + " of " + p.parts.declared + " parts built so far"
        return (t || "Only part of the design built") + ". Release waits until every feature builds."
    }
    readonly property bool hasDraft: F.keys(draftValues).length > 0 || F.keys(draftProv).length > 0
    readonly property var values: head ? Object.assign({}, head.values, draftValues) : ({})
    readonly property var shown: (scrub && scrub.view) || preview || view         // geometry currently on screen
    readonly property var chat: studio && studio.chat ? studio.chat : ({ available: false, note: "" })
    readonly property var slicer: studio ? studio.env.slicer : ({ available: false })
    // engine workstream: what the open design slices with (its own printer, the default, or the slicer's selection)
    readonly property var printing: pid && data && data.printer ? data.printer.slicer : slicer
    // ── purpose (form/purpose.py): does this person print at all, and what is the open design for ──
    // prints: the 3D printing capability (form/capabilities.py; off unless chosen). printingDecided: a choice is saved.
    readonly property var purposeInfo: studio && studio.env.purpose ? studio.env.purpose : ({ printing: true, decided: true, "default": "model", purposes: [], processes: [] })
    readonly property bool prints: purposeInfo.printing !== false
    readonly property bool printingDecided: !!purposeInfo.decided
    // the open design: "print" | "model" | "game"; a model or a game asset is never sliced or checked against a printer
    readonly property string purpose: data && data.purpose ? data.purpose.purpose : ""
    readonly property bool modelDesign: purpose === "model" || purpose === "game"
    readonly property bool gameDesign: purpose === "game"
    // what the next new design is for: "" = the default (purposeInfo.default). The new-design flow sets it.
    property string newPurpose: ""
    property string newProcess: ""
    readonly property string newPurposeEffective: newPurpose || purposeInfo["default"] || "model"
    function setPrinting(on) {           // 3D printing on or off (general.printing is written as general.capabilities)
        if (!on) {                       // nothing printing-related is installed for someone who only designs
            if (installJob && installJob.state === "running")
                installJob.steps.forEach(function (st) { if (st.id.indexOf("slicer.") === 0 && st.state !== "done") skipInstall(st.id) })
            var pk = Object.assign({}, installPick); F.keys(pk).forEach(function (k) { if (k.indexOf("slicer.") === 0) pk[k] = false }); installPick = pk
        }
        return saveConfig({ "general.printing": !!on }, true).then(function (r) {
            if (r) { checkSoftware(); checkSetup() }
            return r })
    }
    function setPurpose(purpose, process) {   // the open design: "print" | "model" | "game", and for a model how it is made
        var b = { purpose: purpose }
        if (process !== undefined) b.process = process
        return settings(b)
    }
    // one call for every way to start a design: { name, recipe, brief, purpose, process } (purpose/process optional)
    // New design (Ctrl+N, the menus, the palette): Home with an empty composer. A conversation under way is kept in
    // the list and a fresh one starts, as a new chat does in Claude.
    function startNew() {
        openSheet(null)
        if (chatItems.length || chatBusy) newChat()         // files already attached to an unsent message stay
        if (screen !== "home") home()
        startFocus++
    }
    function newDesign(o) { o = o || {}; return create(o.name || "", o.recipe, o.brief || "", o.purpose, o.process) }
    readonly property var stages: [
        { id: "brief", title: "Describe", hint: "The brief: what it is for, what is known" },
        { id: "shape", title: "Design", hint: "The shape: select a feature, change it" },
        { id: "fit", title: "Fit", hint: "Clearance under uncertainty" },
        { id: "prove", title: "Review", hint: modelDesign ? "Prove it: the checks" : "Prove it: the checks and the slice" },
        { id: "release", title: "Make", hint: "Release it: the gate, the files, the history" }
    ].filter(function (x) { return x.id !== "fit" || printUi })     // the fit model is a printer's accuracy: only for a print
    onPrintUiChanged: if (!printUi && stage === "fit") stage = "prove"
    readonly property var stageKey: ({ brief: 1, shape: 2, fit: 3, prove: 4, release: 5 })     // Ctrl+n; the same whether Fit shows or not

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
    // the feature a partial revision left out, with the reason the build measured; null when it built
    function leftOut(id) {
        var p = partial
        if (!p || !id) return null
        var sk = p.skipped || []
        for (var i = 0; i < sk.length; i++) if (sk[i].feature === id) return sk[i]
        if (p.failed === id) return p
        if ((p.left_out || []).indexOf(id) >= 0 || (p.dropped || []).indexOf(id) >= 0)
            return { feature: id, message: "Not built yet: the build stopped at " + (p.failed || "an earlier feature") + ".", not_tried: true }
        return null
    }
    // one or two whole sentences of a left-out reason, never cut mid-sentence
    function leftOutReason(x) {
        if (!x) return ""
        var r = String((x.diagnosis && x.diagnosis.summary) || x.message || x.reason || "").replace(/\s+/g, " ").trim()
        if (r.length <= 220) return r
        var cut = r.slice(0, 220), end = Math.max(cut.lastIndexOf(". "), cut.lastIndexOf("; "))
        return end > 40 ? cut.slice(0, end + 1) : cut.slice(0, cut.lastIndexOf(" ")) + "\u2026"
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
    function get(path) { return _track(new Promise(function (res, rej) { var id = ++_rid; _pending[id] = [res, rej]; Bridge.request(id, "GET", path, null) }), "GET", path) }
    function post(path, body) { return _track(new Promise(function (res, rej) { var id = ++_rid; _pending[id] = [res, rej]; Bridge.request(id, "POST", path, body || ({})) }), "POST", path) }
    function upload(path, fileUrl) { return _track(new Promise(function (res, rej) { var id = ++_rid; _pending[id] = [res, rej]; Bridge.upload(id, path, fileUrl) }), "UPLOAD", path) }
    function pget(rest) { return get("/projects/" + pid + (rest || "")) }
    // What a revision changed against the one before (features, parameters), for the conversation's revision cards.
    // Asked quietly (never named in the activity bar: nobody clicked for it) and kept, since a revision never changes.
    property var _revDiffs: ({})
    function revDiff(project, a, b) {
        var k = project + ":" + a + ":" + b
        if (_revDiffs[k]) return Promise.resolve(_revDiffs[k])
        return new Promise(function (res, rej) { var id = ++_rid; _pending[id] = [res, rej]
            Bridge.request(id, "GET", "/projects/" + project + "/diff?a=" + a + "&b=" + b, null) }).then(function (r) { s._revDiffs[k] = r; return r })
    }
    function ppost(rest, body) { return post("/projects/" + pid + rest, body) }

    // ── toasts ───────────────────────────────────────────────
    property int _toastId: 0
    function toast(msg, hint, bad) {
        _toastAt = Date.now()
        var t = toasts.slice(); t.push({ id: ++_toastId, msg: msg, hint: hint || "", bad: !!bad, ts: Date.now() }); toasts = t
        if (toasts.length > 4) toasts = toasts.slice(-4)          // a burst must not cover the screen
    }
    function dropToast(id) { toasts = toasts.filter(function (t) { return t.id !== id }) }
    function fail(e) { toast(e.message || "Something went wrong", e.hint, true) }

    // ── activity: what the engine is working on, named, for the bar under the top bar (ActivityBar.qml) ──
    // Every request is timed. One that takes longer than 300 ms and has a name (from what the person clicked, from
    // act(), or from the table in _labelFor) appears in the bar until it answers, and stays at least 400 ms. When a
    // click's work answers and nobody said anything about it, a toast says it finished, or why it did not.
    property var _clickOwner: null     // the Btn whose click is running right now (Btn.qml sets it)
    property var activity: []          // on screen: [{ id, label, t0, progress (0..1 or -1), detail, done, ok }]
    property var _acts: ({})
    property var activityLog: []       // the last 30 named pieces of work: { label, ms, shown, ok } (diagnostics, tests)
    property int _actId: 0
    property real _toastAt: 0
    property var _actTimer: Timer { interval: 100; repeat: true; onTriggered: s._actTick() }
    function _labelFor(m, path) {
        var p = String(path).replace(/\?.*$/, ""), r = p.replace(/^\/projects\/[a-z0-9-]+/, "")
        var proj = p !== r
        if (/\/(job|stamp)(\/|$)|^\/activity|^\/drafts\/|^\/conversations|^\/chat|^\/setup\/(job|state|step|seen)|^\/install\/job|^\/claude\/login\/|^\/starters|^\/presets|^\/start$|^\/concepts|^\/whatsnew|^\/recipes\/builtin|^\/recipes\/(mine|pending)\/|\/photo$|\/thumb/.test(p)) return ""
        if (proj) {
            var t = { "": m === "GET" ? "Loading the design" : "", "/view": "Loading the geometry", "/analysis": "Computing the analysis map", "/orient": "Ranking print orientations",
                      "/layers": "Loading the sliced layers", "/toolpath": "Loading the toolpath", "/diff": "Comparing revisions", "/cost": "Estimating the cost",
                      "/pack": "Packing the plate", "/preview": "", "/commit": "Saving the revision", "/checkout": "Switching revision",
                      "/run": "Starting the pipeline", "/settings": "Saving the design settings", "/render_photo": "Starting the render", "/alternatives": "Building alternatives",
                      "/variant_save": "Saving the variant", "/variant_promote": "Making the variant the design", "/variant_delete": "Deleting the variant",
                      "/history_export": "Exporting the history", "/import_part": "Importing the part", "/reconstruct": "Reconstructing the mesh as CAD", "/open": "Opening the file", "/approve": "Recording the release",
                      "/evidence": "Recording the result", "/test_piece": "Making the test piece", "/measure": "Measuring", "/intent": "Reading the request",
                      "/duplicate": "Duplicating the design", "/delete": "Moving the design to the trash", "/rename": "Renaming", "/revisions": "Loading revisions",
                      "/variants": "Loading variants", "/reference": "Saving the reference" }
            return t[r] !== undefined ? t[r] : ""
        }
        var g = [[/^\/projects$/, "Creating the design"], [/^\/recipes\/create$/, "Creating the design"],
                 [/^\/(archive\/)?import/, "Importing"], [/^\/capabilities$/, m === "POST" ? "Saving what Form Studio is set up for" : ""],
                 [/^\/setup$/, "Checking this computer"], [/^\/install$/, m === "GET" ? "Checking software" : "Starting the install"], [/^\/install\/remove$/, "Removing"], [/^\/updates/, "Checking for updates"],
                 [/^\/studio\/slicers/, "Finding slicers"], [/^\/studio\/slicer$/, "Switching slicer"], [/^\/printers/, "Reading printers"], [/^\/briefs/, "Writing the brief"],
                 [/^\/config$/, m === "POST" ? "Saving settings" : ""]]
        for (var i = 0; i < g.length; i++) if (g[i][0].test(p)) return g[i][1]
        return ""
    }
    function _track(p, m, path) {
        // a click owns the actions it starts (POST, upload); reads (GET) may come from whatever the click redraws
        var o = m === "GET" ? null : _clickOwner, label = _labelFor(m, path)
        // the button may be on its way out (its sheet was swapped by the same click): then it is not followed
        if (o) { try { o.track(p); if (!label) label = o.busyText ? String(o.busyText).replace(/…$/, "") : o.text } catch (e) { o = null } }
        if (!label) return p
        return _act(label, p, { click: !!o, owner: o })
    }
    // Name a piece of work that is not one request (several in a row, or a file dialog's save): act("Exporting", promise)
    function act(label, p, opts) { try { if (_clickOwner) _clickOwner.track(p) } catch (e) {} return _act(label, p, Object.assign({ click: true, explicit: true }, opts || {})) }
    function _act(label, p, o) {
        var id = ++_actId
        _acts[id] = { id: id, label: label, t0: Date.now(), click: !!o.click, explicit: !!o.explicit, owner: o.owner || null, quiet: !!o.quiet, done: 0, ok: true }
        _actTimer.start()
        p.then(function () { s._actDone(id, true, null) }, function (e) { s._actDone(id, false, e) })
        return p
    }
    function _actDone(id, ok, e) {
        var a = _acts[id]
        if (!a) return
        a.done = Date.now(); a.ok = ok
        activityLog = activityLog.concat([{ label: a.label, ms: a.done - a.t0, shown: !!a.shown, ok: ok }]).slice(-30)
        if (!a.shown) { delete _acts[id]; _actTick(); return }
        // a click whose work took a while gets a word when it ends, unless its own code already said something
        if (a.click && !a.quiet) _afterAct.later(function () {
            if (s._toastAt >= a.done - 5) return
            if (!ok) s.toast((e && e.message) || (a.label + " did not finish"), e && e.hint, true)
            // success is said only where nothing else shows it: the button that asked is still on screen
            // only long, named work: a step that moved the screen on, or anything quick, needs no word of its own
            else if (a.done - a.t0 > 3000 && a.explicit) s.toast(a.label + " · done", "Took " + ((a.done - a.t0) / 1000).toFixed(1) + " s.")
        })
        _actTick()
    }
    property var _afterAct: Timer { interval: 220; property var jobs: []
        function later(f) { jobs.push(f); restart() }
        onTriggered: { var j = jobs; jobs = []; j.forEach(function (f) { f() }) } }
    function _alive(o) { try { return !!o && o.visible === true && o.width > 0 } catch (e) { return false } }
    function _actTick() {
        var now = Date.now(), list = [], left = false
        for (var k in _acts) {
            var a = _acts[k]
            if (!a.shown && !a.done && now - a.t0 >= 300) { a.shown = now }
            if (a.done && (!a.shown || now - a.shown >= 400) && now - a.done >= 160) { delete _acts[k]; continue }
            left = true
            if (a.shown) list.push({ id: a.id, label: a.label, t0: a.t0, progress: a.done ? 1 : -1, detail: "", done: !!a.done, ok: a.ok, click: !!a.click })
        }
        if (job && jobSteps.length) {
            var n = jobSteps.length, fin = jobSteps.filter(function (x) { return x.state !== "queued" && x.state !== "running" }).length
            var cur = jobSteps.filter(function (x) { return x.state === "running" })[0]
            list.push({ id: "job", label: "Running the pipeline", t0: _jobT0, progress: n ? fin / n : -1, done: false, ok: true,
                        detail: (cur ? cur.label + _stepProgress(cur) : "") + " · " + fin + " of " + n })
            left = true
        }
        if (JSON.stringify(list) !== JSON.stringify(activity)) activity = list
        if (!left) _actTimer.stop()
    }
    property var jobSteps: []          // the running pipeline job's steps: [{ node, label, state, progress? }]
    function _stepProgress(st) {       // a long step's own progress: the assembly checks say which joint and position
        var p = st && st.progress
        if (!p || !p.label) return ""
        return " · " + p.label + (p.value !== undefined && p.value !== null ? " at " + p.value : "")
    }
    property real _jobT0: 0

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
        // the saved design takes over from the streamed stage on screen (or from the Designing screen's): in place,
        // at once; it is the same solid, or what the partial build kept when a stage was dropped
        var handoff = _handoff && (!viewer.model || !!viewer.model.stage)
        if (_handoff) { _handoff = false; building = null; _buildNext = handoff ? 0 : _buildNext }
        if (!handoff && viewer.model && viewer.model.stage) building = null
        var grow = !handoff && Date.now() - _buildNext < 15000          // a new build (see _buildNext): it grows in, feature by feature
        if (grow) _buildNext = 0
        viewer.setModel(view, grow ? "build" : "")
        var rg = recon && recon.project === pid && !recon.settled ? recon.ghost : null
        viewer.setGhost(compare ? compare.view : rg)       // Compare's revision, or the mesh a reconstruction grows inside
        if (recon && !rg && !recon.settled) recon = null
        if (peek) peek = null                               // a peek belongs to the head it was asked on
        viewer.selected = feature
        Qt.callLater(applyStageView)
    }

    // ── boot / navigation ────────────────────────────────────
    // What the opening screen says. Each value is something that has happened, never a guess:
    //   "engine"   nothing has answered yet        "kernel"   the engine answers; the CAD kernel has not yet
    //   "designs"  the kernel answered; /studio is being read (the designs, and the setup: slicers, agents)   "ready"   it is here
    property string bootStep: "engine"
    property int bootDesigns: 0                  // design folders the engine counted (0 until it answers)
    property string bootKernel: ""               // the kernel's own name once it answered, e.g. "build123d 0.13.0 / OCP 8.0.1.1"
    readonly property string bootStatus: bootStep === "engine" ? "Starting the engine…"
        : bootStep === "kernel" ? "Starting the CAD kernel…"
        : bootStep === "designs" ? (bootDesigns > 0 ? "Loading " + F.plural(bootDesigns, "design") + " and your setup…" : "Loading your setup…")
        : "Ready"
    function boot(startProject, startStage) {
        var load = function () { bootStep = "designs"; _bootLoad(startProject, startStage) }
        var ask = function () {
            get("/boot").then(function (b) {
                bootDesigns = b.designs || 0
                if (b.kernel) { bootKernel = b.kernel; load() }
                else { bootStep = "kernel"; _bootPoll.next = ask; _bootPoll.restart() }
            }, load)                             // an engine without /boot: load as before, with no step it cannot name
        }
        ask()
    }
    property Timer _bootPoll: Timer { property var next: null; interval: 120; onTriggered: if (next) next() }
    function _bootLoad(startProject, startStage) {
        get("/studio").then(function (st) {
            studio = st; bootStep = "ready"
            var want = startProject, found = null
            for (var i = 0; i < st.projects.length; i++) if (st.projects[i].id === want && !st.projects[i].error) found = st.projects[i]
            if (found) open(found.id).then(function () { if (startStage) setStage(startStage) })
            else screen = "home"
        }, function (e) { fatal = e; bootStep = "ready"; screen = "home" })
    }
    function reloadStudio() { return get("/studio").then(function (st) { studio = st }) }
    function home() {
        steered = false; agentElsewhere = null; convNoDesign = false
        screen = "home"; pid = ""; data = null; view = null; compare = null; layers = null; preview = null; blankCanvas = false
        draftValues = ({}); draftProv = ({}); _stamp = ""
        reloadStudio()
    }
    // after a change outside the design (the printer, a setting): bring its outputs up to date when Auto is on
    function rerunIfStale() {
        if (!data || data.project.auto_run === false || job) return
        var st = F.vals(data.status)
        for (var i = 0; i < st.length; i++) if (st[i].state === "stale" || st[i].state === "missing") { run(); return }
    }
    // how: "" (the person opened it: from then on an agent working elsewhere never takes the view away),
    // "follow" (an agent's activity brought it in) or "conv" (it is the design of the conversation just opened)
    function open(id, how) {
        steered = !how
        agentElsewhere = null; convNoDesign = false; showPlate = true
        pid = id
        draftValues = ({}); draftProv = ({}); draftNote = ""; draftOrigin = ""; draftAgent = ""
        preview = null; draftError = null; feature = ""; compare = null; instructions = null; layers = null; section = null; ack = []
        slicerOpened = null
        _stamp = ""
        return refresh(true).then(function () {
            // the person left for Home, or opened another design, while this one loaded: it does not take the
            // screen back (a workspace with no design in it, on a machine slow enough to see it)
            if (pid !== id || !data) return
            screen = "work"; viewName = "iso"; blankCanvas = false
            if (viewer) { showHead(); viewer.setView("iso", false) }
            if (data.project.auto_run !== false && !job) {
                var st = F.vals(data.status)
                for (var i = 0; i < st.length; i++) if (st[i].state !== "current") { run(); break }
            }
        }, function (e) { fail(e); screen = "home"; pid = "" })
    }
    function refresh(withView) {
        // An answer that arrives after another design was opened belongs to the design that asked: it is dropped, so
        // the design you left can never be drawn (or built up) for a moment in the one you opened.
        var at = pid
        return pget().then(function (d) {
            if (pid !== at) return
            data = d
            if (d.recovered) toast("Project recovered", d.recovered)
            loadRefine()                                   // the head's refine changes follow the head
            if (withView || !view || view.rev !== d.project.head) {
                return pget("/view").then(function (v) {
                    if (pid !== at) return
                    v.rev = d.project.head; v.pid = d.project.id; view = v
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
        steered = true
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
    // One preview is built at a time. Values that change while it builds go next, as one request with the latest
    // values, and an answer that arrives while newer values wait is drawn anyway: dragging a slider shows the part
    // following it, instead of a queue of builds that are thrown away one after another.
    property bool _pvBusy: false
    property bool _pvAgain: false
    function runPreview() {
        var seq = ++_seq
        if (!F.keys(draftValues).length) {
            _pvAgain = false
            preview = null; draftError = null
            showHead(); if (viewer) viewer.flagged = []
            return
        }
        if (_pvBusy) { _pvAgain = true; return }
        _pvBusy = true; _pvAgain = false
        var at = pid
        function next() { s._pvBusy = false; if (s._pvAgain && s.pid === at) s.runPreview(); else s._pvAgain = false }
        ppost("/preview", { values: draftValues }).then(function (pv) {
            var show = s.pid === at && (seq === s._seq || s._pvAgain)
            next()
            if (!show) return
            preview = pv; draftError = null
            if (viewer) {
                viewer.setModel(pv)
                viewer.setGhost(view)
                viewer.selected = feature
                viewer.flagged = pv.impact.features.filter(function (f) { return f.change !== "trimmed" }).map(function (f) { return f.id })
                Qt.callLater(applyStageView)
            }
        }, function (e) {
            next()
            if (seq !== _seq) return
            draftError = e                      // keep showing the last geometry that built
            if (viewer) viewer.flagged = e.feature ? [e.feature] : []
        })
    }
    function discard() {
        draftValues = ({}); draftProv = ({}); draftNote = ""; draftOrigin = ""; draftAgent = ""
        preview = null; draftError = null; _seq++; _pvAgain = false
        if (viewer) viewer.flagged = []
        showHead()
    }
    function commit() {
        ppost("/commit", { values: draftValues, provenance: draftProv, note: draftNote, origin: draftOrigin || "user" }).then(function (r) {
            draftValues = ({}); draftProv = ({}); draftNote = ""; draftOrigin = ""; draftAgent = ""; preview = null; ack = []
            _seq++; _pvAgain = false                // a preview still on its way is not the head
            if (viewer) viewer.flagged = []
            toast("Committed as " + F.pad(r.head), r.job ? "Regenerating solid, exports, checks and slice." : "Auto-regenerate is off: outputs are now stale.")
            if (r.job) track(r.job)
            refresh(true)
        }, function (e) {
            // the draft is the head revision again (a value moved and moved back): nothing to commit, not a failure
            if (e && e.message === "Nothing changed.") { discard(); return toast("Nothing to commit", "The draft is the same as the head revision.") }
            draftError = e
        })
    }
    function checkout(n) {
        if (hasDraft) return toast("Commit or discard the draft first.", "", true)
        ppost("/checkout", { rev: n }).then(function (r) {
            endCompare(); ack = []
            if (r.job) track(r.job)
            refresh(true)
            toast("Head is now " + F.pad(n))
        }, fail)
    }

    // ── selection ────────────────────────────────────────────
    function select(f) {
        feature = f || ""; if (f) steered = true
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
    // A pipeline that starts by itself as a design opens is not news when it ends: the dock and the bar show it.
    property real _openT: 0
    property bool _jobQuiet: false
    onPidChanged: _openT = Date.now()
    function track(id) { if (!id) return; job = id; jobSteps = []; _jobT0 = Date.now(); _jobQuiet = _jobT0 - _openT < 4000; _poll.restart(); _actTimer.start() }
    function _tick() {
        var id = job
        pget("/job/" + id).then(function (j) {
            if (job !== id) return
            var r = ({})
            for (var i = 0; i < j.steps.length; i++) r[j.steps[i].node] = j.steps[i].state
            running = r; jobSteps = j.steps
            if (j.state === "running") { _poll.restart(); return }
            job = ""; running = ({}); layers = null; jobSteps = []
            var bad = null
            for (var k = 0; k < j.steps.length; k++) if (j.steps[k].state === "failed" || j.steps[k].state === "blocked") { bad = j.steps[k]; break }
            if (!bad && j.error) bad = { label: "Pipeline", error: j.error }
            if (bad) toast(bad.label + ": " + (bad.error && bad.error.message || "stopped"), bad.error && bad.error.hint, true)
            else if (!_jobQuiet && Date.now() - _jobT0 > 1500 && j.steps.some(function (x) { return x.state === "done" }))
                toast("Outputs are current", F.plural(j.steps.filter(function (x) { return x.state === "done" }).length, "step") + " rebuilt in " + ((Date.now() - _jobT0) / 1000).toFixed(1) + " s.")
            var t = Object.assign({}, thumbTick); t[pid] = (t[pid] || 0) + 1; thumbTick = t
            refresh(true)
        }, function () { job = ""; running = ({}); jobSteps = [] })
    }

    // ── stage & view ─────────────────────────────────────────
    function setStage(id) {
        stage = id; section = null
        if (id !== "prove") layers = null
        if (id !== "release" && compare) endCompare()
        if (viewer) { var had = !!viewer.marker; viewer.setMarker(null); if (had) viewer.setView(viewName, true) }    // a check's marker zoomed in: frame the part again
        applyStageView()
    }
    function setView(name) { viewName = name; if (viewer) viewer.setView(name, true) }
    function setSection(axis, t) { section = { axis: axis || "", t: t === undefined ? 0.5 : t }; applyStageView() }
    function toggleCompanions() { companions = !companions; applyStageView() }
    function toggleDims() { dims = !dims; applyStageView() }
    function setAck(id, on) { ack = on ? ack.concat([id]) : ack.filter(function (x) { return x !== id }) }

    // Compare: an older revision as a ghost over the head. It ends from the same button (a toggle), the Done on the
    // viewport's "Comparing" chip, Esc, another stage, or showing or checking out another revision.
    function endCompare() {
        if (!compare) return
        compare = null
        if (viewer) { viewer.setGhost(hasDraft ? view : null); viewer.flagged = [] }
    }
    function compareWith(n) {
        if (compare && compare.rev === n) return endCompare()
        Promise.all([pget("/view?rev=" + n), pget("/diff?a=" + n + "&b=" + project.head)]).then(function (r) {
            compare = { rev: n, view: r[0], diff: r[1], geo: null, geoBusy: true, geoError: "" }
            if (viewer) {
                viewer.setGhost(r[0])
                viewer.flagged = r[1].impact.features.filter(function (f) { return f.change !== "trimmed" }).map(function (f) { return f.id })
            }
            // the geometric diff: booleans on both solids in the kernel, slower than the parameter diff, so it follows
            pget("/geomdiff?a=" + n + "&b=" + project.head).then(function (g) {
                if (compare && compare.rev === n) compare = Object.assign({}, compare, { geo: g, geoBusy: false })
            }, function (e) {
                if (compare && compare.rev === n) compare = Object.assign({}, compare, { geoBusy: false, geoError: e.message || "The kernel could not compare the solids." })
            })
        }, fail)
    }

    // ── maker tools: text on a face (form/engrave.py), assembly instructions (form/instructions.py) ──
    function addText(body) {
        body.expect_head = project ? project.head : null
        return ppost("/text", body).then(function (r) {
            toast("Text added as " + F.pad(r.head), "“" + body.text + "” is a feature in the design's code now.")
            selItems = []; selection = null
            if (r.job) track(r.job)
            return refresh(true).then(function () { return true })
        }, function (e) { fail(e); return false })
    }
    // standard features at a face (form/feature_helpers.py): a screw boss or a snap-fit hook, written into the code
    function addFeature(body) {
        body.expect_head = project ? project.head : null
        return ppost("/feature", body).then(function (r) {
            var f = r.features[r.features.length - 1]
            toast("Feature added as " + F.pad(r.head), (f.kind === "boss" ? f.size + " screw boss" : "Snap-fit hook") + " is a feature in the design's code now.")
            selItems = []; selection = null
            if (r.job) track(r.job)
            return refresh(true).then(function () { return true })
        }, function (e) { fail(e); return false })
    }
    // Make it lighter (form/lighten.py): real candidates, every passing check kept, then one applied as a new revision
    property var lighter: null
    property bool lighterBusy: false
    function searchLighter() {
        if (lighterBusy) return Promise.resolve(null)
        lighterBusy = true
        var at = pid
        return ppost("/lighten", { builds: 4 }).then(function (r) {
            lighterBusy = false
            if (pid === at) lighter = r
            return r
        }, function (e) { lighterBusy = false; fail(e); return null })
    }
    function loadLighter() {
        var at = pid
        lighter = null
        pget("/lighten").then(function (r) { if (pid === at && !r.none) lighter = r }, function () {})
    }
    function applyLighter(c) {
        return ppost("/lighten_apply", { changes: c.changes || null, settings: c.settings || null, expect_head: project ? project.head : null }).then(function (r) {
            toast(c.changes ? "Lighter design as " + F.pad(r.head) : "Lighter print settings",
                  (c.saves_slice_g !== null && c.saves_slice_g !== undefined ? F.fmt(c.saves_slice_g, 1) + " g less filament in the slicer" : F.fmt(c.saves_mass_g, 1) + " g less computed mass")
                  + (c.settings ? "; the slice is redone with them." : "."))
            sheet = null; lighter = null
            if (r.job) track(r.job)
            _buildNext = Date.now()
            return refresh(true).then(function () { buildTick++; return true })
        }, function (e) { fail(e); return false })
    }
    // Replace a broken part (form/replace.py): the conversation it started, and how far the agent has got
    property string replaceConv: ""
    readonly property bool replaceActive: {
        if (!convId) return false
        if (replaceConv === convId) return true
        for (var i = 0; i < chatItems.length; i++) if (chatItems[i].t === "user") return String(chatItems[i].text || "").indexOf("Replace a broken part:") === 0
        return false
    }
    // {done, active}: Photo is done once sent; Estimate while the agent first works; Measure from its first
    // ask_measurement until answered; Design once a design is created
    readonly property var replaceProgress: {
        var asked = false, answered = false, designed = false, open = !!chatAsking && chatAsking.kind === "measure"
        var askIds = ({})
        for (var i = 0; i < chatItems.length; i++) {
            var ev = chatItems[i]
            if (ev.t === "tool" && ev.name === "ask_measurement") asked = true
            if (ev.t === "ask" && ev.kind === "measure") { asked = true; askIds[ev.id] = true }
            if (ev.t === "answer" && askIds[ev.id]) answered = true
            if (ev.t === "tool" && ["create_design", "create_project", "pick_concept", "propose_concepts"].indexOf(ev.name) >= 0) designed = true
        }
        if (open) return { done: 2, active: 2 }                 // a measurement card is waiting for you
        if (designed && !chatBusy) return { done: 4, active: -1 }
        if (designed || answered) return { done: 3, active: chatBusy ? 3 : -1 }
        if (asked) return { done: 2, active: chatBusy ? 2 : -1 }
        return { done: 1, active: chatBusy ? 1 : -1 }
    }
    // print time and cost on every printer (form/slicecompare.py): real slices, cached per model and presets
    property var printerCompare: null
    property bool printerCompareBusy: false
    function comparePrinters(limit) {
        if (printerCompareBusy) return Promise.resolve(null)
        printerCompareBusy = true
        var at = pid
        return ppost("/slicecompare", { limit: limit || 8 }).then(function (r) {
            printerCompareBusy = false
            if (pid === at) printerCompare = r
            var ok = r.rows.filter(function (x) { return x.status === "ok" }).length
            toast("Compared on " + F.plural(ok, "printer"), "Each one sliced for real; times and grams are the slicers' simulations.")
            return r
        }, function (e) { printerCompareBusy = false; fail(e); return null })
    }
    function loadPrinterCompare() {
        var at = pid
        printerCompare = null
        pget("/slicecompare").then(function (r) { if (pid === at && r.rows.length) printerCompare = r }, function () {})
    }
    function removeText(id) {
        return ppost("/text_remove", { id: id, expect_head: project ? project.head : null }).then(function (r) {
            toast("Text removed", "New revision " + F.pad(r.head) + ".")
            if (r.job) track(r.job)
            return refresh(true)
        }, fail)
    }
    property var instructions: null            // { rev, key, pdf, pages, steps } for the open design
    property bool instructionsBusy: false
    function makeInstructions() {
        if (instructionsBusy) return Promise.resolve(null)
        instructionsBusy = true
        return ppost("/instructions", {}).then(function (r) {
            instructionsBusy = false; instructions = r
            toast("Assembly instructions ready", r.steps.length + " steps, " + r.pages.length + " pages")
            return r
        }, function (e) { instructionsBusy = false; fail(e); return null })
    }
    function marker(c) {
        if (!viewer) return
        asmFor(c)
        if (c.at) viewer.setMarker({ at: c.at, to: c.to })
        else if (c.feature) { viewer.setMarker(null); feature = c.feature; viewer.selected = c.feature; viewer.focusFeature(c.feature) }
    }
    function showLayers(on) {
        if (!on) { layers = null; return }
        pget("/layers" + plateQuery).then(function (m) { m.n = Math.min(m.count - 1, 3); layers = m }, fail)
    }
    function setLayer(n) { if (layers) layers = Object.assign({}, layers, { n: n }) }
    // ── print simulation (LayerView.qml): open it in a given state from anywhere ──
    // o: { at: 0..1 of the slicer's time, layer: 1-based, fraction, ghost, only: [line types] | null, mode: "3d" | "2d" | "plate",
    //      copies: N (plate preview), play: true, speed }
    property var simAsk: null
    // ── engine workstream: several plates (form/plates.py) and Design only (slicing turned off) ──
    property int plate: 1                // the plate Prove and the print simulation show, when a design has several
    readonly property var plates: data && data.slice && data.slice.plates ? data.slice.plates : []
    readonly property int plateShown: plates.length ? Math.max(1, Math.min(plates.length, plate)) : 1
    readonly property string plateQuery: plates.length ? "?plate=" + plateShown : ""
    function setPlate(n) {                // the open simulation stays open and loads the other plate's toolpaths
        if (n === plate) return
        plate = n
        if (layers) pget("/layers" + plateQuery).then(function (m) { if (layers) { m.n = Math.min(m.count - 1, layers.n); layers = m } }, fail)
    }
    function designOnlyEverywhere(on) {   // Settings or first run: no slicing for any design; a waiting slicer install is skipped
        if (on && installJob && installJob.state === "running")
            installJob.steps.forEach(function (st) { if (st.id.indexOf("slicer.") === 0 && st.state !== "done") skipInstall(st.id) })
        if (on) { var pk = Object.assign({}, installPick); F.keys(pk).forEach(function (k) { if (k.indexOf("slicer.") === 0) pk[k] = false }); installPick = pk }
        return saveConfig({ "slicer.enabled": !on }).then(function (r) { if (pid) refresh(); return r })
    }
    signal revealInspector(real y)     // scroll the stage inspector (y in its content; a large value = the end)
    function simulate(o) { simAsk = o || ({}); if (!layers) showLayers(true) }
    // Open a native file or folder dialog. Under the interaction tests (form/app/uitest.py) no native window opens:
    // the dialog is answered at once with a path in the test's folder, so its own onAccepted handler runs as usual.
    function ask(dlg) {
        if (!Bridge.testDir) { dlg.open(); return }
        var pick = Bridge.testPick()
        if (dlg.selectedFolder !== undefined && dlg.fileMode === undefined) { dlg.currentFolder = dlg.selectedFolder = Bridge.fileUrl(pick || Bridge.testDir) }
        else {
            var name = String(dlg.selectedFile || dlg.currentFile || "").replace(/^.*\//, "") || "file"
            dlg.selectedFile = Bridge.fileUrl(pick || (Bridge.testDir + "/" + name))
        }
        dlg.accepted()
    }
    function openSheet(kind, props) { sheet = kind ? { kind: kind, props: props || ({}) } : null }

    // ── the game asset of the open design (form/game/app.py; GameSheet) ──
    // game: GET /game (engines, budgets, software, the last asset built); gameLod: the LOD drawn; gameLods: their meshes
    property var game: null
    property bool gameBusy: false
    property string gameError: ""
    property string gameErrorHint: ""          // what to do about it, when the engine says
    property int gameLod: 0
    property var gameLods: ({})
    readonly property var gameAsset: game && game.last ? game.last : null
    function loadGame() {
        if (!pid) return Promise.resolve(null)
        var at = pid
        return get("/projects/" + pid + "/game").then(function (r) {
            if (at !== pid) return null
            game = r; gameError = ""; gameErrorHint = ""
            if (r.last) showGameLod(gameLod)
            return r }, function (e) { gameError = e && e.message ? e.message : String(e); gameErrorHint = e && e.hint ? e.hint : ""; return null })
    }
    // build (or export) with an engine preset: { preset, texture_px, bake, budgets?, action? }
    function buildGame(opts) {
        if (!pid || gameBusy) return Promise.resolve(null)
        var at = pid, body = Object.assign({ action: "build", preset: "gltf", texture_px: 1024, bake: "fast" }, opts || ({}))
        gameBusy = true; gameError = ""; gameErrorHint = ""
        return post("/projects/" + pid + "/game", body).then(function (r) {
            gameBusy = false
            if (at !== pid) return null
            gameLods = ({})
            game = Object.assign({}, game || ({}), { last: r })
            showGameLod(Math.min(gameLod, (r.lods || []).length - 1))
            return r
        }, function (e) { gameBusy = false; gameError = e && e.message ? e.message : String(e); gameErrorHint = e && e.hint ? e.hint : ""; return null })
    }
    function showGameLod(i) {
        var a = gameAsset
        if (!a || !a.lods || i < 0 || i >= a.lods.length) return
        gameLod = i
        var k = a.key + ":" + i
        if (gameLods[k]) return
        get("/projects/" + pid + "/game/" + a.key + "/lod/" + i).then(function (m) {
            var c = Object.assign({}, gameLods); c[k] = m; gameLods = c })
    }
    function gameTexUrl(map) {
        var a = gameAsset
        // a local file: Qt Quick 3D's Texture reads files, not http (the engine also serves them at /game/<key>/tex/)
        return a && a.textures && a.textures[map] ? String(Bridge.fileUrl(a.textures[map])) : ""
    }

    function create(name, recipeId, brief, purpose, process) {
        var b = { name: name, recipe: recipeId, brief: brief || "", purpose: purpose || newPurpose || "" }
        if (process || newProcess) b.process = process || newProcess
        return post("/projects", b).then(function (r) {
            sheet = null; stage = "shape"; newPurpose = ""; newProcess = ""
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
    // "Make editable": the mesh becomes a new design, rebuilt as CAD and checked against the mesh (form/recon)
    function makeEditable(file) {
        toast("Reconstructing " + file, "Building the solid and fitting surfaces. A large mesh takes a few minutes.")
        var mesh = ((shown && shown.companions) || []).filter(function (c) { return !!c.mesh && c.label === file })[0] || null
        return ppost("/reconstruct", { file: file }).then(function (r) {
            var m = r.summary || ({})
            var ed = Number(m.editable_pct || 0)
            if (r.parts)                               // one file that held several bodies: one design, a part each
                toast("“" + r.name + "”: " + r.parts.length + " parts", "The file held " + r.parts.length
                      + " separate bodies; each is a part of one design, reconstructed and checked on its own.")
            else if (m.tier)                           // a sculpt or a scan: a surface body or a mesh body (form/sculpt.py)
                toast("“" + r.name + "”: " + (m.route === "surface_body" ? "a surface body" : "a mesh body"),
                      F.fmt(m.hausdorff_mm, 3) + " mm from the file (measured) · "
                      + (m.route === "surface_body" ? "edit its cage; exports STEP" : "Scale and Flat base; exact cuts; STL and 3MF"))
            else if (m.recipe_verified && ed > 0)      // "editable" only for a share of real dimensions (form/recon)
                toast("“" + r.name + "”: " + F.fmt(ed, 0) + "% editable", F.fmt(m.hausdorff_mm, 4) + " mm from the mesh"
                      + (m.within_tolerance === false ? " (outside the tolerance)" : "")
                      + " · " + (m.dimension_params || 0) + " dimensions you can change · "
                      + F.fmt(m.feature_area_pct || 0, 0) + "% of the surface from features · Layer " + m.layer + " (computed)")
            else if (m.recipe_verified)
                toast("“" + r.name + "”: 0% editable", F.fmt(m.hausdorff_mm, 4) + " mm from the mesh. Its Params are "
                      + "positions, not dimensions. Rebuild as editable CAD has the agent model it with named features.")
            else                                       // no verified feature recipe: the agent remodel is the next step
                toast("“" + r.name + "” reached Layer " + m.layer, F.fmt(m.frozen_area_pct, 0) + "% frozen facets, no verified feature "
                      + "model. Rebuild as editable CAD has the agent model it with named features.")
            return reloadStudio().then(function () { s._reconReveal(r.project, mesh, m); return open(r.project) })
        }, fail)
    }
    // The reconstruction's reveal: the mesh's own edges stay on screen in blueprint (the viewport's ghost), the CAD
    // grows inside them with the build-up, and a readout counts to the largest distance the comparison measured
    // between the two (summary.hausdorff_mm, computed by form/recon). When the build is in, the mesh's lines fade.
    property var recon: null           // { project, file, ghost: { edges }, mm, within, settled }
    function _reconReveal(project, mesh, m) {
        if (!mesh || !mesh.edges || m.hausdorff_mm === undefined || m.hausdorff_mm === null) { recon = null; return }
        recon = { project: project, file: mesh.label, ghost: { edges: mesh.edges }, mm: Number(m.hausdorff_mm), within: m.within_tolerance !== false, settled: false }
        _buildNext = Date.now()
    }
    function reconSettle() {            // the build-up is in: the mesh's lines leave, the number stays a little longer
        if (!recon || recon.settled || recon.project !== pid) return
        recon = Object.assign({}, recon, { settled: true })
        _reconFade.restart(); _reconEnd.restart()
    }
    property var _reconFade: Timer { interval: 900; onTriggered: if (s.viewer && s.recon && !s.compare && !s.hasDraft) s.viewer.fadeGhost() }
    property var _reconEnd: Timer { interval: 4200; onTriggered: s.recon = null }
    property var _reconReset: Connections { target: s
        function onPidChanged() { if (s.recon && s.recon.project !== s.pid) s.recon = null } }
    // "Rebuild as editable CAD": a conversation that remodels the project's meshes as clean CAD with named features
    // and Params, compared with the meshes until within tolerance (form/remodel, design_guide "reference_parts")
    function rebuildAsCad(files) {
        return ppost("/rebuild_brief", { files: files || [] }).then(function (r) { send(r.message); return r }, fail)
    }
    // Open in <Slicer>: settings chosen for this part, sliced for real, the project opened in the slicer (form/slicer_open.py)
    property bool slicerOpenBusy: false
    property var slicerOpened: null                // the last result for this design: decisions, time, grams, file
    readonly property string slicerName: (data && data.slice && data.slice.slicer_name) || slicer.label || "your slicer"
    function openInSlicer() {
        if (slicerOpenBusy) return Promise.resolve(null)
        slicerOpenBusy = true
        var at = pid
        return ppost("/slicer_open", {}).then(function (r) {
            slicerOpenBusy = false
            if (pid === at) slicerOpened = r
            toast("Opened in " + r.slicer, F.dur(r.time_s) + " · " + F.fmt(r.filament_g, 1) + " g (the slicer's estimate) · "
                  + r.decisions.filter(function (d) { return d.changed }).length + " settings chosen for this part")
            return r
        }, function (e) { slicerOpenBusy = false; fail(e); return null })
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
                    if (last.origin && last.origin.indexOf("agent") === 0) {
                        s.toast(F.pad(st.head) + " by " + last.origin.replace("agent:", ""), last.note || "")
                        s._buildNext = Date.now()     // the agent's revision grows in, whichever of this and the activity feed sees it first
                    } else if (last.origin === "refine" && !s.refineBusy) {
                        s.toast(F.pad(st.head) + " · " + (last.note || "Refined").replace(/ \(.*$/, ""), "Each change is listed in the Refinement panel, with its own undo.")
                    }
                    s.refresh(true)
                }
                s._stamp = key
            }, function () {})
        }
    }
    // ── design refinement (form/refine/jobs.py): the job after every build, and the head's refine changes ──
    property var refine: null          // GET /projects/<id>/refine: { state, stage, events, changes: [{ id, label, reason, kind }] }
    property bool refineBusy: false
    function loadRefine() {
        if (!pid) { refine = null; return }
        var want = pid
        pget("/refine").then(function (r) { if (s.pid === want && JSON.stringify(r) !== JSON.stringify(s.refine)) s.refine = r }, function () {})
    }
    function _refinePost(body, label) {
        refineBusy = true
        return act(label, ppost("/refine", body)).then(function (r) { s.refineBusy = false; s.refine = r; s.refresh(true); return r },
                                                       function (e) { s.refineBusy = false; s.fail(e) })
    }
    function refineUndo(id) { return _refinePost({ action: "undo", feature: id || "", expect_head: project ? project.head : null },
                                                 id ? "Undoing the refine change" : "Undoing the refinement") }
    // Before / After: hold to see the revision before the refinement, cross-faded over the head; let go and the head
    // is back. Looking changes nothing.
    property var peek: null            // { rev, view, on }
    property bool _peekWant: false
    readonly property int refineBase: {                 // the revision the head's refinement started from; 0 = none
        if (!project) return 0
        var best = 0, rs = project.revisions || []
        for (var i = 0; i < rs.length; i++) if (rs[i].n <= project.head && rs[i].n > best && (rs[i].refine || rs[i].origin === "refine")) best = rs[i].n
        return best > 1 ? best - 1 : 0
    }
    function peekBefore(on) {
        _peekWant = !!on
        if (!on) { if (peek && peek.on) peek = Object.assign({}, peek, { on: false }); return }
        var n = refineBase, at = pid
        if (!n || hasDraft || scrub || compare) return
        if (peek && peek.rev === n) { peek = Object.assign({}, peek, { on: true }); return }
        loadRev(n).then(function (v) { if (s.pid === at && !s.compare && !s.scrub) s.peek = { rev: n, view: v, on: s._peekWant } }, function () {})
    }
    function refineAgain() { return _refinePost({ action: "rerun" }, "Starting refinement") }
    function resetRefineLedger() {
        return act("Resetting what refinement learned", post("/refine/ledger/reset", {})).then(function (r) {
            s.toast("Refinement starts fresh", r.rows ? F.plural(r.rows, "learned row") + " cleared on this computer." : "Nothing was learned yet.") }, fail)
    }
    property var _refinePoll: Timer {
        interval: 1500; repeat: true; running: s.screen === "work" && s.pid !== "" && !!s.refine && s.refine.state === "running"
        onTriggered: s.loadRefine()
    }
    property var _refineReset: Connections { target: s; function onPidChanged() { s.refine = null; s.loadRefine() } }
    property var _activity: Timer {
        interval: s.chatBusy || s.building ? 400 : 1200; repeat: true; running: s.screen !== "boot"   // quicker while a build streams
        onTriggered: s.get("/activity?since=" + s.actTs).then(function (r) {
            for (var i = 0; i < r.events.length; i++) {
                var ev = r.events[i]
                s.actTs = Math.max(s.actTs, ev.ts)
                if (ev.by === "you") continue
                if (ev.draft) s._noteDraft(ev)
                if (ev.kind === "stage") { if (ev.draft) s.onStage(ev); continue }    // drawn, not said in the chat
                if (ev.kind === "refine") { if (ev.project === s.pid) s.loadRefine(); continue }   // the dock's panel says it
                if (s._mine(ev)) s.noteAct(ev)          // another conversation's steps are never written into this one
                if (!s._waitCommit(ev)) s.follow(ev)
            }
        }, function () {})
    }

    // ── a build streamed stage by stage (form/studio.py _draft_sink) ──
    // While an agent creates or rewrites a design, every stage the kernel builds is written as a draft and named in
    // the activity log (kind "stage", draft=<id>). The newest one is drawn as it arrives: it grows in over the one
    // before with the build-up animation (Viewport: fade and rise), and the one before goes once it is in place, so
    // the part never blinks. When the design is saved its head takes over in place (showHead, _handoff), the same
    // solid, or the one the partial build kept if a stage was dropped: the saved design wins.
    property var building: null        // the stage on screen: { draft, project, feature, label, at, of, index }
    property var revealing: []         // feature ids the viewport is building up right now (the Design list marks their rows)
    readonly property string buildingText: building ? "Building " + building.label + (building.of > 1 ? " (" + building.at + " of " + building.of + ")" : "") : ""
    property var stageLog: []          // stages drawn: { draft, feature, at, of, t (ms) } (diagnostics, tests)
    property var stageViewer: null     // the Designing screen's viewport (the workspace's is `viewer`)
    property var _draftOf: ({})        // draft id -> the design it rewrites ("" for a new one), from its "design" event
    property var _draftDone: ({})      // drafts whose build was saved: their stages are history
    property bool _handoff: false      // the next head shown replaces a drawn stage, in place, with no build-up
    property bool calmArrive: false    // the workspace takes over from a drawn stage: it arrives without a fade (Main.qml)
    property bool _stageBusy: false
    property string _stageAgain: ""
    property real _framedDiag: 0
    function _noteDraft(ev) {
        if (ev.kind === "design") { var o = Object.assign({}, _draftOf); o[ev.draft] = ev.project || ""; _draftOf = o }
        if (ev.kind === "stage") { var sn = Object.assign({}, _stageSeen); sn[ev.draft] = Math.max(sn[ev.draft] || 0, ev.index || 0); _stageSeen = sn }
        // a commit for a build that is being drawn waits for _waitCommit; any other one ends its draft now
        if (ev.kind === "commit" && !(building && building.draft === ev.draft)) _endDraft(ev.draft)
    }
    function _endDraft(draft) { var dn = Object.assign({}, _draftDone); dn[draft] = true; _draftDone = dn }
    // The last stage and the commit often arrive in the same poll. The commit then waits until that stage has been
    // fetched, drawn and has grown into place (at most 3 s), so the last feature is never skipped; then the saved
    // design takes over in place.
    property var _stageSeen: ({})      // draft id -> the newest stage index the activity log named
    property var _commitWait: null     // { ev, until }: the commit of the build on screen, held until its last stage is in
    function _waitCommit(ev) {
        if (ev.kind !== "commit" || !ev.draft || !building || building.draft !== ev.draft || !_mine(ev)) return false
        _commitWait = { ev: ev, until: Date.now() + 3000 }
        _commitTick()
        if (_commitWait) _commitTimer.start()
        return true
    }
    property var _commitTimer: Timer { interval: 60; repeat: true; onTriggered: s._commitTick() }
    function _commitTick() {
        var w = _commitWait
        if (!w) { _commitTimer.stop(); return }
        var vp = _stageView(), d = w.ev.draft
        var drawn = !!building && building.draft === d && building.index >= (_stageSeen[d] || 0) && !_stageBusy
        var settled = !vp || (!vp.revealing && !(vp.model && vp.model.stage && vp.model.mesh.length > 1))
        if (!(drawn && settled) && Date.now() < w.until) return
        _commitWait = null; _commitTimer.stop()
        _endDraft(d)
        if (building && building.draft === d) { _handoff = true; if (screen === "designing") calmArrive = true }
        follow(w.ev)
        if (building) _stageEnd.restart()          // the head takes over; if it never does, the caption still goes
    }
    function _stageView() { return screen === "designing" ? stageViewer : screen === "work" ? viewer : null }
    // the agent of this conversation (or any agent, while the open design was not worked on) starts a new design while
    // a design is open: the workspace hands over to the being-designed view, where its stages are drawn as they come
    function _toDesigning(ts) {
        agentElsewhere = null; convNoDesign = false; blankCanvas = false; showPlate = true
        pid = ""; data = null; view = null; preview = null; compare = null; layers = null; section = null; scrub = null
        draftValues = ({}); draftProv = ({}); draftNote = ""; draftOrigin = ""; draftAgent = ""; _stamp = ""
        designingSince = ts - 0.5
        screen = "designing"
    }
    function onStage(ev) {
        if (_draftDone[ev.draft]) return
        if (!_mine(ev)) { _noteElsewhere(ev); return }      // another conversation's build is never drawn here
        var target = _draftOf[ev.draft] || ev.project || ""
        if (screen === "work" && !target) {                    // a new design while one is open
            if ((steered && !chatBusy) || scrub || compare || (hasDraft && !draftAgent)) return
            _toDesigning(ev.ts)
        }
        if (screen === "designing") { if (target || ev.ts < designingSince - 1) return }      // this conversation's new design
        else if (screen === "work") { if (target !== pid || scrub || compare || (hasDraft && !draftAgent)) return }   // a rewrite of the open one
        else return
        if (_stageBusy) { _stageAgain = ev.draft; return }    // the draft file always holds the newest stage: fetch it once more
        _stageBusy = true
        var again = function () {
            s._stageBusy = false
            var d = s._stageAgain; s._stageAgain = ""
            if (d) s.onStage({ draft: d, project: s._draftOf[d] || "", ts: Date.now() / 1000 })
        }
        get("/drafts/" + ev.draft).then(function (d) { s.showStage(d); again() }, again)
    }
    function _human(id) { var t = String(id || "").replace(/[_-]+/g, " ").trim(); return t ? t.charAt(0).toUpperCase() + t.slice(1) : "" }
    function showStage(d) {
        var vp = _stageView()
        if (!d || !d.mesh || !d.mesh.length || !vp || _draftDone[d.draft]) return
        if (building && building.draft === d.draft && building.index >= d.index) return     // not newer than what is drawn
        var old = vp.model
        // what stays drawn under the new stage while it grows in: the stage before (its last piece), or the design
        // that is being rewritten
        var under = !old || !old.mesh ? [] : old.stage ? [old.mesh[old.mesh.length - 1]] : old.mesh
        var piece = { feature: "stage:" + d.index + ":" + d.feature, part: "", positions: d.mesh[0].positions, indices: d.mesh[0].indices }
        var first = !building || building.draft !== d.draft
        building = { draft: d.draft, project: _draftOf[d.draft] || "", feature: d.feature, label: d.label || _human(d.feature),
                     at: d.at || d.index, of: d.of || 0, index: d.index }
        stageLog = stageLog.concat([{ draft: d.draft, feature: d.feature, label: building.label, at: building.at, of: building.of, t: Date.now() }]).slice(-40)
        vp.glideFrame()
        vp.setModel({ pid: old && old.pid ? old.pid : d.draft, rev: -1, stage: true, draft: d.draft, bbox: d.bbox, mesh: under.concat([piece]) }, "build")
        if (vp === stageViewer) {                 // the Designing screen frames the part as it grows
            var b = d.bbox, diag = Math.hypot(b[1][0] - b[0][0], b[1][1] - b[0][1], b[1][2] - b[0][2])
            if (first || diag > _framedDiag * 1.12) { _framedDiag = diag; vp.setView("iso", !first) }
        }
        if (!vp.revealing) _stageSettle(vp)
    }
    function _stageSettle(vp) {                   // the new stage is in place: the one under it goes
        var m = vp ? vp.model : null
        if (!m || !m.stage || m.mesh.length < 2 || vp.revealing) return
        vp.setModel(Object.assign({}, m, { mesh: [m.mesh[m.mesh.length - 1]] }))
    }
    function _stageClear() {                      // the agent stopped without saving it: the plate is empty again
        building = null; _handoff = false; calmArrive = false; _framedDiag = 0; _commitWait = null
        if (stageViewer && stageViewer.model && stageViewer.model.stage) stageViewer.setModel(null)
    }
    // The caption of a streamed build never outlives it. 3 s after the last stage, the last commit or the end of the
    // reply: a build that was saved (or handed to the saved head) drops its caption whatever else happened (a commit
    // that arrived with its last stages, a head that was never shown because a revision was being viewed); a build
    // nobody saved is cleared once the reply has ended. A build still streaming while the agent works keeps it.
    property var _stageEnd: Timer { interval: 3000; onTriggered: s._stageTimeout() }
    function _stageTimeout() {
        if (!building || _commitWait) return
        if (_handoff || _draftDone[building.draft]) {
            building = null; _handoff = false; calmArrive = false; _framedDiag = 0
            if (screen === "work" && viewer && viewer.model && viewer.model.stage) showHead()     // the saved head, not a stage
            return
        }
        if (!chatBusy) _stageClear()
    }
    property var _stageWatch: Connections { target: s
        function onChatBusyChanged() { if (!s.chatBusy && s.building) s._stageEnd.restart() }
        function onBuildingChanged() { if (s.building) s._stageEnd.restart() }
        function onScreenChanged() { if (s.screen !== "designing" && s.screen !== "work") s._stageClear() }
        function onPidChanged() { if (s.building && s.building.project && s.building.project !== s.pid) s.building = null } }
    property var _stageDone1: Connections { target: s.stageViewer; ignoreUnknownSignals: true; function onRevealDone() { s._stageSettle(s.stageViewer) } }
    property var _stageDone2: Connections { target: s.viewer; ignoreUnknownSignals: true; function onRevealDone() { s._stageSettle(s.viewer) } }
    readonly property var _viewMap: ({ iso: "iso", sheet: "iso", front: "front", back: "back", iso_back: "back", left: "side", right: "side", top: "top", bottom: "under" })
    function follow(ev) {
        if (!_mine(ev)) {                              // another conversation, or an outside agent on a design one owns
            if (ev.kind === "concepts") loadConcepts()       // its concepts wait on Home
            if (ev.kind === "concepts" || (ev.project && ev.project !== pid && ["commit", "draft", "look", "search"].indexOf(ev.kind) >= 0))
                _noteElsewhere(ev)
            return
        }
        if (ev.kind === "concepts") {                  // the agent proposed concepts, or one was picked
            loadConcepts().then(function () {
                if (ev.picked) { if (screen === "designing") reloadStudio().then(function () { open(ev.picked, "follow") }); return }
                // the concepts this conversation asked for are shown at once, unless another sheet is up
                if (ev.group && (screen === "designing" || screen === "home" || (screen === "work" && !sheet))) openSheet("concepts", { group: ev.group })
            })
            return
        }
        if (!ev.project) return
        if (screen === "designing" && ev.ts < designingSince - 1) return
        if (ev.project !== pid) {
            if (["commit", "draft", "look", "search"].indexOf(ev.kind) < 0) return
            if (_conceptSheetOpen()) return            // the concepts are being looked at: a render of one never takes them away
            var fresh = screen === "designing"
            // once the person has worked on the open design, an agent busy elsewhere is named, never jumped to
            if (!fresh && steered && screen === "work") { _noteElsewhere(ev); return }
            var target = ev.project, grow = fresh && !_handoff     // after a streamed build the saved design takes over in place
            reloadStudio().then(function () {
                // a concept waiting for a pick lives in the concepts sheet: the agent looking at it never opens it here
                if (s._pendingConcept(target) || s._conceptSheetOpen()) return
                if (grow) s._buildNext = Date.now()
                s.open(target, "follow").then(function () { if (fresh) s.buildTick++ })
                if (!fresh) s.toast("Following " + ev.by, ev.text)
            })
            return
        }
        var userDraft = hasDraft && !draftAgent
        if (ev.kind === "commit") {
            if (draftAgent) discard()
            var t = Object.assign({}, thumbTick); t[pid] = (t[pid] || 0) + 1; thumbTick = t
            _buildNext = Date.now()
            refresh(true).then(function () { buildTick++ })     // the new build grows in, feature by feature
        } else if (ev.values && F.keys(ev.values).length && !userDraft) {
            loadDraft(Object.assign({}, head.values, ev.values), "agent:" + ev.by, undefined, ev.by)
        } else if (userDraft && ev.values) {
            toast(ev.by + " is trying a change", "Your own draft is kept; discard it to watch.")
        }
        if (ev.kind === "look" && ev.view && _viewMap[ev.view]) setView(_viewMap[ev.view])
        if (ev.kind === "look" && ev.highlight) { var was = steered; select(ev.highlight); steered = was }
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
    // a provider with many models and none used yet has no Default: the first message asks for a model first
    readonly property bool chatNeedsModel: chatReady && (chatModel === "" || (chatModel === "default" && !!chatAgentInfo.pick))
    property string pendingSend: ""          // the message waiting for that pick; sent as soon as a model is chosen
    signal modelPickWanted()
    readonly property string chatAgentLabel: chatAgentInfo ? chatAgentInfo.label : "your agent"
    function modelLabel(agent, model) {
        var a = agentInfo(agent), ms = a ? a.models : []
        for (var i = 0; i < ms.length; i++) if (ms[i].id === model) return ms[i].label
        return model || "Default"
    }
    // the composer's chip: the version the alias resolved to ("Opus 5.5"), else the picker's label
    function modelShort(agent, model) {
        var a = agentInfo(agent), ms = a ? a.models : []
        if (a && a.available && (!model || (model === "default" && a.pick))) return "Choose a model"
        for (var i = 0; i < ms.length; i++) if (ms[i].id === model) return ms[i].resolved_label || ms[i].label
        return model || "Default"
    }
    property var _chatInit: Connections { target: s; function onStudioChanged() { if (s.studio && !s.chatAgent) s._useDefaults() } }
    function _useDefaults() { chatAgent = chatDefault.agent; chatModel = chatDefault.model; chatEffort = chatDefault.effort }

    property var _chatPoll: Timer { interval: 250; onTriggered: s._chatTick() }
    property var _convPoll: Timer {
        interval: 3000; repeat: true
        running: s.screen !== "boot" && (s.chatBusy || s.convs.some(function (c) { return c.state === "running" || c.state === "asking" }))
        onTriggered: s.loadConvs()
    }
    function loadConvs() { return get("/conversations").then(function (r) { convs = r.conversations }, function () {}) }
    function convTitle() { return conv ? conv.title : "New conversation" }

    function newChat() {
        _chatPoll.stop()
        convId = ""; conv = null; convBranches = []; chatItems = []; chatTools = ({}); chatLive = null; chatNext = 0; chatBusy = false; chatAttach = []; chatLinks = []
        chatAsking = null
        if (studio) _useDefaults()
        talkOpen = true; chatFocus++
    }
    function openConv(id) {
        if (!id) return newChat()
        _chatPoll.stop()
        // the feed is emptied first: a message of the old conversation must never be drawn under the new id
        // (its attachment thumbnails would be asked for from the wrong conversation)
        chatItems = []; chatTools = ({}); chatLive = null; chatNext = 0; chatBusy = false; chatAttach = []; chatAsking = null
        convId = id
        talkOpen = true
        return get("/conversations/" + id).then(function (r) {
            if (convId !== id) return
            _take(r)
            chatAgent = r.agent; chatModel = r.model; chatEffort = r.effort || ""
            if (r.state === "running") _chatPoll.restart()
            chatFocus++
            return _landOnConv(r)
        }, function (e) { fail(e); newChat(); loadConvs() })
    }
    // ── a conversation's designs: opening one lands on what it made; a strip when it made several ──
    // The engine keeps `designs` on the conversation ([{ project, role, ts, state }], roles made | concept |
    // reference-study | continued, state live | trashed) and `project` as the one in front. A record written before
    // that has only `project` and the older `projects`; both read the same here. A design whose folder is gone is
    // shown as trashed whatever the record says.
    property bool steered: false       // the person has worked on the open design: follow() names other designs instead of jumping
    property var agentElsewhere: null  // { project, name, by, kind }: an agent is working on another design than the open one
    property bool convNoDesign: false  // the open conversation has made no design yet (Designing.qml says so)
    function projectRow(id) {
        var ps = studio ? studio.projects : []
        for (var i = 0; i < ps.length; i++) if (ps[i].id === id) return ps[i]
        return null
    }
    function convDesigns(c) {
        if (!c) return []
        var seen = ({}), out = []
        function add(id, role, state, ts) {
            if (!id || seen[id]) return
            seen[id] = true
            var row = projectRow(id), live = !!row && !row.error && (!state || state === "live")      // trashed or gone: not openable
            out.push({ project: id, role: role || "made", state: live ? "live" : "trashed", ts: ts || 0,
                       name: row ? row.name : id, head: row ? row.head : 0, live: live })
        }
        var ds = c.designs
        if (ds && ds.length) ds.forEach(function (d) { if (typeof d === "string") add(d); else if (d) add(d.project, d.role, d.state, d.ts) })
        else (c.projects || []).forEach(function (id) { add(id) })
        add(c.project)                 // the one in front is always listed
        // concepts open in their own sheet until one is picked (then it is "continued" or "made"), so they stay out of the strip
        return out.filter(function (d) { return d.role !== "concept" && (d.role !== "reference-study" || d.live) })
    }
    readonly property var designsHere: convDesigns(conv)
    readonly property var liveDesignsHere: designsHere.filter(function (d) { return d.live })
    function _landOnConv(r) {
        var ds = convDesigns(r).filter(function (d) { return d.live })
        var want = r.project && ds.some(function (d) { return d.project === r.project }) ? r.project : ds.length ? ds[ds.length - 1].project : ""
        if (want) {
            convNoDesign = false
            if (want === pid && screen === "work") return
            return reloadStudio().then(function () { return open(want, "conv") })
        }
        // nothing to show: the conversation's own "no design yet" state, never the Home question
        convNoDesign = true; steered = false; agentElsewhere = null       // first: pid "" below must not start a new chat
        pid = ""; data = null; view = null; compare = null; layers = null; preview = null; blankCanvas = false
        draftValues = ({}); draftProv = ({})
        convNoDesign = true; designingSince = Date.now() / 1000
        screen = "designing"
    }
    function openConvDesign(id) {     // the strip: the person picks one of the conversation's designs
        if (!id || id === pid) return Promise.resolve()
        return open(id)
    }
    // ── whose event is it ──
    // Every event an agent run of a conversation writes names that conversation (form/studio.py activity). Only the
    // open conversation's agent moves what is on screen: its builds are drawn, its designs and views followed. Before
    // the first reply names a new conversation (convId still ""), the run being started is the open one. An event
    // with no conversation comes from an agent outside Form Studio's chat: it is followed only while no conversation
    // here owns the open design. Everything else is named in one calm note (agentElsewhere), never jumped to.
    function _mine(ev) {
        var c = ev && ev.conversation ? String(ev.conversation) : ""
        if (c) {
            if (c === convId) return true
            // a conversation that was already there before this message was sent is another one
            var r = !convId && chatBusy ? _convRow(c) : null
            return !convId && chatBusy && !(r && (r.created || 0) < _sendAt - 2)
        }
        return !pid || !_owned(pid)
    }
    function _owned(id) {          // a conversation of this app made or continued this design
        if (conv && (conv.project === id || convDesigns(conv).some(function (d) { return d.project === id }))) return true
        return (convs || []).some(function (c) {
            return c.project === id || (c.designs || []).some(function (d) { return (typeof d === "string" ? d : d && d.project) === id }) })
    }
    property real _sendAt: 0           // when the first message of a new conversation was sent (_mine)
    function _convRow(id) { var cs = convs || []; for (var i = 0; i < cs.length; i++) if (cs[i].id === id) return cs[i]; return null }
    function _pendingConcept(id) {  // a concept of an open group, not picked yet: it belongs to the concepts sheet
        var row = projectRow(id)
        if (row && row.concept && !row.concept.picked) return true
        return (concepts || []).some(function (g) { return (g.members || []).some(function (m) { return m.project === id }) })
    }
    function _conceptSheetOpen() { return !!sheet && sheet.kind === "concepts" }
    function _noteElsewhere(ev) {
        var row = ev.project ? projectRow(ev.project) : null, c = ev.conversation ? String(ev.conversation) : ""
        var cr = c ? _convRow(c) : null
        var by = ev.by && ["engine", "you", "agent"].indexOf(ev.by) < 0 ? ev.by : "The agent"
        var name = row ? row.name : ev.kind === "concepts" ? "concepts" : cr && cr.title ? "“" + cr.title + "”" : "a new design"
        var a = agentElsewhere
        // one calm note: it is not rewritten for every stage of the same build
        if (!a || a.project !== (ev.project || "") || a.conversation !== c || a.name !== name || a.by !== by)
            agentElsewhere = { project: ev.project || "", name: name, by: by, kind: ev.kind, conversation: c,
                               title: cr && cr.title ? cr.title : "", group: ev.group || "" }
        if (ev.kind === "commit") {          // a design just saved: its name arrives with the studio
            var pj = ev.project || ""
            Promise.all([reloadStudio(), loadConvs()]).then(function () {
                var n = s.agentElsewhere, r2 = pj ? s.projectRow(pj) : null
                if (n && r2 && n.project === pj && n.name !== r2.name) s.agentElsewhere = Object.assign({}, n, { name: r2.name })
            })
        }
    }
    // Show: the conversation that is working (it lands on its design), or for an outside agent the design itself
    function showElsewhere() {
        var a = agentElsewhere
        if (!a) return
        agentElsewhere = null
        if (a.conversation && a.conversation !== convId) { openConv(a.conversation); return }
        if (a.kind === "concepts" && a.group) { openConcepts(a.group); return }
        if (a.project) reloadStudio().then(function () { open(a.project, "follow") })
    }
    // a usage limit, said calmly: which agent, until when; no upsell links. Only an error event the engine marked
    // kind "usage_limit" (form/agents/limits.py) is one; any other error, a 429 or a word like "quota" in it, is not.
    function usageLimit(ev) {
        if (!ev || ev.kind !== "usage_limit") return null
        var u = String(ev.until || "")
        return { until: u, again: String(ev.again || (u ? (/^\d/.test(u) ? "at " : "") + u : "")) }
    }
    // a message: every https link in it is offered to the engine first (a file is fetched and attached; a page goes
    // with the message as a link), then the message is sent. The words keep the links as written.
    function sendWithLinks(text) {
        text = String(text || "").trim()
        var urls = text.match(/https?:\/\/[^\s<>"'`)\]]+/gi) || []
        if (!urls.length) return send(text)
        var seen = ({}); urls = urls.filter(function (u) { u = u.replace(/[.,;:!?]+$/, ""); if (seen[u]) return false; seen[u] = true; return true })
        return Promise.all(urls.map(function (u) { return fetchLink(u.replace(/[.,;:!?]+$/, "")) })).then(function () { send(text) }, function () { send(text) })
    }
    // downloads and uploads under way (links fetched, files attached): the engine reports each one's progress at
    // GET /conversations/fetches; polled only while one runs. Each row: { name|url, bytes|done, total, state }.
    property int fetching: 0
    property var fetches: []
    readonly property var fetchProgress: {
        var rows = (fetches || []).filter(function (f) { return f && f.state !== "done" && f.state !== "failed" })
        if (!rows.length) return null
        var done = 0, total = 0, known = true
        rows.forEach(function (f) { done += Number(f.bytes || f.done || 0); var t = Number(f.total || f.size || 0); if (t > 0) total += t; else known = false })
        var first = rows[0], name = first.name || (first.url ? decodeURIComponent(String(first.url).replace(/[?#].*$/, "").replace(/^.*\//, "")) : "")
        return { count: rows.length, name: name, done: done, total: known ? total : 0, fraction: known && total > 0 ? Math.min(1, done / total) : -1 }
    }
    property var _fetchPoll: Timer {
        interval: 400; repeat: true; running: s.fetching > 0
        onTriggered: s.get("/conversations/fetches").then(function (r) { s.fetches = r && r.fetches ? r.fetches : (Array.isArray(r) ? r : []) }, function () {})
        onRunningChanged: if (!running) s.fetches = []
    }

    // merge a reply from GET /conversations/<id>?from=chatNext into the feed
    function _take(r) {
        var items = chatItems.filter(function (it) { return !it.local }), tools = Object.assign({}, chatTools)
        for (var i = 0; i < r.items.length; i++) {
            var ev = r.items[i]
            ev.n = (r.events_from || 0) + i              // its place in the saved conversation ("Fork from here")
            if (ev.t === "result") tools[ev.id] = ev
            else items.push(ev)
        }
        if (r.items.length || items.length !== chatItems.length) { chatItems = items; chatTools = tools }
        chatNext = r.next; chatLive = r.live; chatSeconds = r.seconds || 0
        chatBusy = r.state === "running"
        chatAsking = r.asking || null
        var m = Object.assign({}, r); delete m.items; delete m.live
        var thread = conv && conv.id === m.id ? conv.thread : ""
        conv = m
        if (m.thread !== thread || !convBranches.length) loadBranches()
    }
    // the open conversation's branches (form/conversations.py threads)
    function loadBranches() {
        var c = conv
        if (!c || !c.id) { convBranches = []; return Promise.resolve([]) }
        return get("/conversations?thread=" + (c.thread || c.id)).then(function (r) {
            if (!conv || conv.id !== c.id) return []
            convBranches = r.conversations.slice().sort(function (a, b) {
                return (a.id === a.thread ? 0 : 1) - (b.id === b.thread ? 0 : 1) || a.created - b.created })
            return convBranches
        }, function () { return [] })
    }
    // "Fork from here": a new branch holding this conversation up to event n; the agent gets a transcript of it
    function forkConv(n, reason) {
        if (!convId) return Promise.resolve(null)
        if (chatBusy) { toast("The conversation is still answering", "Fork it when the reply has ended.", true); return Promise.resolve(null) }
        return post("/conversations/" + convId + "/fork", { at_event: n === undefined ? null : n, reason: reason || "" }).then(function (m) {
            loadConvs()
            return openConv(m.id).then(function () {
                toast("Branched the conversation", "The earlier messages are here; the original is unchanged. Switch branches at the top of the column.")
                return m
            })
        }, fail)
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
        if (!text) return
        if (chatBusy) { chatPrefill(text); return }        // never lose a message: it waits in the box until the reply ends
        if (chatNeedsModel) { pendingSend = text; modelPickWanted(); return }
        var att = chatAttach, id = convId, links = chatLinks
        if (!id) _sendAt = Date.now() / 1000
        links = links.filter(function (l) { return text.indexOf(l.url) < 0 })      // a link already in the words is not listed twice
        if (links.length) text += "\n\nLinks:\n" + links.map(function (l) { return "- " + l.url }).join("\n")
        chatBusy = true; talkOpen = true; talkCalm = false; chatAttach = []; chatLinks = []; chatLive = null      // a message sent from the bar brings the conversation back
        chatItems = chatItems.concat([{ t: "user", text: text, attachments: att, local: true }])
        // a new design: what it is for goes with the conversation (form/start.py), so the agent reads it on every
        // message and the designs it creates get it; how a model will be made is said in words
        var said = text, fresh = !pid && !(conv && conv.messages)
        if (fresh && newPurposeEffective === "model" && newProcess) said += "\n\nThis 3D model will be made by: " + newProcess + " (pass process=\"" + newProcess + "\")."
        var body = { message: said, project: pid || null, agent: chatAgent, model: chatModel || "default", effort: chatEffort,
                     attachments: att.map(function (a) { return a.id }) }
        // only a purpose the person chose goes with it: unsaid, the design is a 3D model unless the request itself
        // says it is for printing (the agent then passes purpose="print")
        if (fresh) { if (newPurpose) body.purpose = newPurpose; newPurpose = ""; newProcess = "" }
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
    // ── the agent asks, you answer (ask_user); its follow-ups; Fix with the agent (chat workstream) ──
    // two designs of one family: one came from the other, or both from the same first design (lineage)
    function rootOf(id) {
        var ps = studio ? studio.projects : []
        for (var i = 0; i < ps.length; i++) if (ps[i].id === id) return ps[i].lineage && ps[i].lineage.root ? ps[i].lineage.root : id
        return id
    }
    function sameFamily(a, b) { return !!a && !!b && rootOf(a) === rootOf(b) }
    function projectExists(id) {
        var ps = studio ? studio.projects : []
        for (var i = 0; i < ps.length; i++) if (ps[i].id === id && !ps[i].error) return true
        return false
    }
    function answerAsk(qid, text, choices) {
        var id = convId
        if (!id) return Promise.resolve()
        chatAsking = null                                   // the card shows the answer at once; the engine confirms it
        return post("/conversations/" + id + "/answer", { id: qid, text: text || "", choices: choices || [] }).then(function () {
            if (convId === id) _chatTick()
        }, function (e) { fail(e); if (convId === id) _chatTick() })
    }
    // a revision named in a reply ("r04"): show it, read-only, from the timeline
    function openRevRef(n) {
        var want = conv && conv.project ? conv.project : pid
        if (!want) return
        var go = function () { if (project && n <= project.head) { timelineOpen = true; showRev(n, true) } else toast(F.pad(n) + " is not in this design") }
        if (want !== pid && projectExists(want)) open(want).then(go); else go()
    }
    // a change the agent made, from its reply card: compare with the revision before, or go back to it
    function compareChange(c) {
        // the same card again ends it: setStage would have ended it and compareWith started it again, so it never went off
        if (c.project === pid && compare && compare.rev === c.from) return endCompare()
        var go = function () { if (stage !== "shape") setStage("shape"); compareWith(c.from) }
        if (c.project !== pid) open(c.project).then(go); else go()
    }
    function undoChange(c) {
        var go = function () { checkout(c.from) }
        if (c.project !== pid) open(c.project).then(go); else go()
    }
    function fixPrompt(subject, details) {
        var where = project ? "“" + project.name + "” (project " + pid + "), " + F.pad(project.head) : "this design"
        return "Fix this in " + where + ": " + subject + "\n\n" + (details ? details + "\n\n" : "")
            + "Read the current state with Form Studio's tools first and explain the cause in one or two lines. Then preview "
            + "the smallest change that fixes it and render it. Commit it (with expect_head) only if it builds and no check "
            + "fails; if the fix changes how the part fits or looks, ask me first with ask_user. Say what is still unverified."
    }
    // "Fix with <agent>": open this design's conversation (or a new one) and send the failure, word for word
    function fixWith(subject, details) {
        if (!chat.available || !chatReady) return toast("No agent is connected", "Choose one under Settings, Agents.", true)
        if (chatBusy) return toast("The conversation is still answering", "Wait for it, or stop it, then press Fix again.", true)
        var text = fixPrompt(subject, details), here = pid
        talkOpen = true
        if (conv && conv.project === here) return send(text)
        get("/conversations?project=" + here).then(function (r) {
            var best = null
            r.conversations.forEach(function (c) { if (c.messages && (!best || c.updated > best.updated)) best = c })
            if (best && best.state !== "running") openConv(best.id).then(function () { if (s.pid === here && !s.chatBusy) s.send(text) })
            else { newChat(); send(text) }
        }, function () { newChat(); send(text) })
    }
    function stopChat() { if (convId) post("/conversations/" + convId + "/stop", {}).then(function () { s._chatTick() }, function () {}) }
    function lastUserText() {
        for (var i = chatItems.length - 1; i >= 0; i--) if (chatItems[i].t === "user") return chatItems[i].text
        return ""
    }
    function retryChat() { var t = lastUserText(); if (t && !chatBusy) send(t) }
    // ── agents workstream: retry with another model, look for agents again ──
    property bool retryAfterPick: false     // the model picker was opened from "Try another model": picking one resends
    property bool agentsChecking: false
    function refreshAgents() {
        agentsChecking = true
        return get("/chat?refresh=1").then(function (r) {
            agentsChecking = false
            if (studio) studio = Object.assign({}, studio, { chat: r })
        }, function (e) { agentsChecking = false; fail(e) })
    }
    // a label for a model id on a message footer, when the engine did not name it
    function modelName(ev) { return ev ? (ev.label || ev.model || "") : "" }
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
            // the model last used with this agent; a provider that lists many and was never used asks for one
            var info = agentInfo(agent)
            if (model === undefined) model = info && info.last_model ? info.last_model : (info && info.pick ? "" : "default")
            if (effort === undefined) effort = ""
        }
        if (model !== undefined) chatModel = model || (agent !== undefined && agentInfo(chatAgent) && agentInfo(chatAgent).pick ? "" : "default")
        if (effort !== undefined) chatEffort = effort || ""
        var body = { agent: chatAgent, model: chatModel, effort: chatEffort }
        post("/chat/defaults", body).then(function (r) {
            if (studio) studio = Object.assign({}, studio, { chat: Object.assign({}, studio.chat, { "default": r["default"] }) })
        }, function () {})
        if (convId) post("/conversations/" + convId + "/settings", body).then(function (m) { if (convId === m.id) conv = Object.assign({}, conv, m) }, function () {})
        if (retryAfterPick && model !== undefined) { retryAfterPick = false; retryChat() }
        else if (pendingSend && !chatNeedsModel) { var t = pendingSend; pendingSend = ""; send(t) }
    }

    // attachments: images, PDFs, sketches and every part, mesh, scan, drawing or zip form/formats.py lists. Copied into the conversation's folder; sent with the next message.
    function attachFiles(urls) {
        var list = []
        for (var i = 0; i < urls.length; i++) list.push(urls[i])
        if (!list.length) return
        var go = function (id) {
            list.forEach(function (u) {
                var name = decodeURIComponent(String(u).replace(/^.*[\/\\]/, ""))
                fetching++
                upload("/conversations/" + id + "/attach?name=" + encodeURIComponent(name), u).then(function (r) {
                    fetching = Math.max(0, fetching - 1)
                    if (convId === id) chatAttach = chatAttach.concat(r.attachments)
                }, function (e) { fetching = Math.max(0, fetching - 1); fail(e) })
            })
        }
        ensureConv().then(go, fail)
    }
    function dropAttachment(id) { chatAttach = chatAttach.filter(function (a) { return a.id !== id }) }
    function attachmentUrl(file, cid) { return Bridge.baseUrl + "/api/conversations/" + (cid || convId) + "/file/" + file }

    function renameConv(id, title) {
        return post("/conversations/" + id + "/rename", { title: title }).then(function (m) { if (convId === id) conv = Object.assign({}, conv, m); return loadConvs() }, fail)
    }
    function pinConv(id, on) { return post("/conversations/" + id + "/pin", { on: on }).then(function () { return loadConvs() }, fail) }
    function deleteConv(id) {
        if (convId === id) newChat()
        return post("/conversations/" + id + "/delete", {}).then(function () { return loadConvs() }, fail)
    }
    // opening a design shows its most recent conversation; going home shows a fresh prompt
    property var _convFollow: Connections {
        target: s
        function onPidChanged() {
            var id = s.pid
            if (id === "") { if (!s.chatBusy && s.convId && !s.convNoDesign) s.newChat(); return }
            if (s.conv && (s.conv.project === id || s.convDesigns(s.conv).some(function (d) { return d.project === id }))) return      // one of its designs: the strip
            if (s.chatBusy) return                       // the running conversation is probably making this design
            s.get("/conversations?involving=" + id).then(function (r) {      // the one that made it, or touched it
                if (s.pid !== id || s.chatBusy) return
                var best = null
                r.conversations.forEach(function (c) { if (c.messages && (!best || c.updated > best.updated)) best = c })
                if (best) { if (best.id !== s.convId) s.openConv(best.id) }
                // the same design family (a copy, a picked concept): the conversation goes along, it does not restart
                else if (s.conv && s.convId && s.sameFamily(s.conv.project, id))
                    s.post("/conversations/" + s.convId + "/link", { project: id }).then(function (m) { if (s.convId === m.id) s.conv = Object.assign({}, s.conv, m); s.loadConvs() }, function () {})
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
            // the launcher asks what to set up; nothing is installed before its last step (Welcome.qml)
            if (r.first_run && (!headless || empty)) { welcome = true; checkSoftware(); loadCaps() }
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
    // ── what Form Studio is set up for (form/capabilities.py): the launcher's cards and Settings › Set up for ──
    // Printing is the capability "print" and is off unless the person turns it on. printOn: printing is on;
    // printUi: printing is on and a design made for printing is open. With no design open (Home, a design being made)
    // there is nothing to print, so nothing about printing shows. Every print surface follows printUi.
    property var caps: null            // GET /capabilities: { capabilities: [...], chosen, download_mb, decided, install }
    readonly property bool printOn: !!studio && !!studio.env.purpose && studio.env.purpose.printing === true
    readonly property bool printUi: printOn && purpose === "print"
    // the ground under the part (Viewport.stageMode): a neutral studio floor for a 3D model. A design made for printing
    // stands on its printer's build plate from Describe on (the person can hide it in Describe and Design with "Hide
    // the build plate"; Fit, Review and Make always show it). A model never shows a plate.
    property bool showPlate: true
    readonly property bool plateWanted: printUi && (showPlate || stage === "fit" || stage === "prove" || stage === "release")
    readonly property string stageMode: plateWanted ? "plate" : "studio"
    function capOn(id) { return !!caps && caps.chosen.indexOf(id) >= 0 }
    function loadCaps() { return get("/capabilities").then(function (r) { caps = r; return r }, function (e) { fail(e); return null }) }
    // the whole list (the launcher's first step): written, nothing installed yet
    function setCaps(list) {
        return post("/capabilities", { capabilities: list }).then(function (r) {
            caps = r; reloadStudio(); checkSoftware(); checkSetup(); return r }, function (e) { fail(e); return null })
    }
    // Settings: on installs only what that capability needs; off hides it and never uninstalls anything
    function setCap(id, on) {
        return post("/capabilities", { id: id, on: !!on }).then(function (r) {
            caps = r
            reloadStudio().then(function () { if (pid) refresh() })
            checkSoftware(); checkSetup()
            var c = r.capabilities.filter(function (x) { return x.id === id })[0]
            if (on && c && c.install.length) runSetup(c.install)
            else toast((c ? c.title : id) + (on ? " is on" : " is off"), on ? (c && c.manual.length ? "Some of it is downloaded from its own page: Settings › Engines & software." : "Nothing to download.") : "Hidden in Form Studio. Nothing was uninstalled.")
            return r }, function (e) { fail(e); return null })
    }
    // a setup run of exactly these registry ids, with every command in the log (form/installer.py AutoJob)
    function runSetup(ids) {
        if (installing || !ids || !ids.length) return
        post("/install/auto", { ids: ids }).then(function (j) { installLog = j.log; installJob = j; installPick = ({}); _installPoll.restart() }, fail)
    }
    function openSetup() { openSettings("software"); checkSetup() }

    // ── installer, sign-in, settings (setup workstream) ─────────────
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
    // "Use in Form Studio" (form/use.py): the switch on an engine's card. It is written to studio.toml and applies at
    // once; the card shows the new state straight away and the software list is read again behind it.
    property var useOverride: ({})          // id → on, while the engine confirms
    function useOn(r) { return useOverride[r.id] !== undefined ? useOverride[r.id] : !!(r.use && r.use.on) }
    function _useSettle(id) { var o = Object.assign({}, useOverride); delete o[id]; useOverride = o }
    function setUse(r, on) {
        if (!r || !r.use) return null
        var o = Object.assign({}, useOverride), v = ({})
        o[r.id] = on; useOverride = o
        v[r.use.key] = on
        return saveConfig(v, true).then(function (res) {
            if (!res) { _useSettle(r.id); return null }
            toast(on ? "Form Studio now uses " + r.label : "Form Studio no longer uses " + r.label,
                  on ? "From the next time it is needed." : "It stays installed; turn it back on any time.")
            return checkSoftware().then(function (x) { _useSettle(r.id); return x })
        })
    }
    // Remove what Form Studio downloaded for one optional engine (installer.REMOVABLE); the row asks first
    function removeSoftware(id) {
        return post("/install/remove", { id: id }).then(function (r) {
            toast(r.message, "Your designs are not affected.")
            return checkSoftware()
        }, function (e) { fail(e); return checkSoftware() })
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
    // ── hands-free setup (engine workstream): first start installs what Form Studio needs by itself, every command in
    // the log, and pauses only where the person must act (sign in, a download page); the engine notices and goes on.
    property bool autoTried: false
    function autoSetup(force) {
        if (installing || (autoTried && !force)) return
        autoTried = true
        get("/install/auto").then(function (r) {
            if ((!force && !r.enabled) || !r.ids.length) return
            post("/install/auto", {}).then(function (j) { installLog = j.log; installJob = j; installPick = ({}); _installPoll.restart() }, fail)
        }, function () {})
    }
    function skipInstall(id) { if (installJob) post("/install/job/" + installJob.id + "/skip", { id: id }).then(function (j) { installJob = j }, fail) }
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
    function saveConfig(values, quiet) {     // quiet: the change shows itself (no "Saved" toast)
        return post("/config", { values: values }).then(function (r) {
            config = r.config
            // every setting applies at once: the studio (printer chip, purpose), the open design (checks, plate) and setup
            reloadStudio().then(function () { if (pid) refresh().then(function () { rerunIfStale() }) })
            var n = F.keys(r.changed).length
            if (quiet) {}
            else if (!n) toast("Nothing to change")
            else toast("Saved " + F.plural(n, "setting"), r.restart ? "The project folder changes when Form Studio restarts." : r.backup ? "The previous file was kept as a backup next to it." : "", false)
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
    // tab: general | printer | chat | apps | updates | advanced | software. "agents" (what the tab reads) means chat;
    // a tab that does not exist, or Printing while printing is off, opens General instead of an empty sheet.
    function openSettings(tab) {
        var t = tab === "agents" ? "chat" : tab
        if (t === "engines") t = "software"
        if (["general", "printer", "chat", "apps", "updates", "advanced", "software"].indexOf(t) < 0 || (t === "printer" && !printOn)) t = "general"
        openSheet("settings", { tab: t }); loadConfig(); checkSoftware(); loadCaps()
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
            + "Look at the current head with the Form Studio tools, not from memory: get_project, then render(view=\"sheet\"), "
            + "render(view=\"bottom\") and render(view=\"iso_back\").\n\n"
            + "Review at three scales. Silhouette: is the mass balanced, the useful volume clear, does it look stable and intentional? "
            + "Relationships: spacing, wall thickness, radius families, repeated features, contact points. "
            + "Details: seam, entry chamfers, finger relief, drainage, support scars, tool access, the underside and the assembled state.\n\n"
            + (modelDesign
               ? "Do two passes: designer (proportion, interaction, finish); engineer (interfaces, load path, assembly, tolerances, "
                 + "from the checks). It is a 3D model, not for 3D printing: say nothing about printing, slicing or supports"
                 + (data && data.purpose && data.purpose.process ? "; judge manufacturability for " + data.purpose.process_label : "") + ".\n\n"
               : "Do three passes: designer (proportion, interaction, finish); engineer (interfaces, load path, assembly, tolerances, "
                 + "from the checks and the fit model); print technician (orientation, layer direction at loaded roots, overhangs, "
                 + "supports, seams, from the simulated slice).\n\n")
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
    // A click gives the point on the part as printed (where the engine computes) and the part's id; the viewport
    // draws each measurement where that part is shown now, so measuring works in print layout, assembled and exploded.
    property bool measuring: false             // clicks on the part measure instead of selecting
    property bool measureOpen: false           // the readout panel is showing
    property string measureKind: "distance"    // distance | face | diameter
    property var measures: []                  // [{ id, kind, label, detail, how, label_at, part | pa/pb, frame, ... }], kept until cleared
    property var measureFrom: null             // first point of a distance: { at, shown, part, snap }
    property int measureBusy: 0                // clicks the engine is still answering
    property string measureSay: ""             // a short note in the tool's hint (a miss, a click with nothing to measure)
    property int _mid: 0
    property var _measureSayOff: Timer { interval: 2600; onTriggered: s.measureSay = "" }
    function measureNote(t) { measureSay = t; _measureSayOff.restart() }
    function setMeasuring(on) {
        if (on && selecting) setSelecting(false)
        measuring = !!on; measureFrom = null; measureSay = ""
        if (on) { measureOpen = true; if (viewer) viewer.setMarker(null) }
    }
    function clearMeasures() { measures = []; measureFrom = null }
    function dropMeasure(id) { measures = measures.filter(function (m) { return m.id !== id }) }
    function _addMeasure(m) { m.id = ++_mid; measures = measures.concat([m]) }
    function _frameName(tag) { return !tag || tag === "print" ? "print layout" : tag.indexOf("assembled") === 0 ? "assembled view" : "exploded view" }
    function measureClick(hit, reach) {        // hit: from Viewport.hitAt; reach: snap radius in mm
        var kind = measureKind, part = hit.part || "", tag = viewer ? viewer.frameTag : "print"
        measureBusy++
        var done = function () { s.measureBusy = Math.max(0, s.measureBusy - 1) }
        return ppost("/probe", { at: hit.at }).then(function (pr) {
            done()
            var shown = function (p) { return s.viewer ? s.viewer.shownPoint(part, p) : p }
            if (kind === "distance") {
                var at = pr.on, snap = "surface"
                if (pr.snaps.length && pr.snaps[0].distance_mm <= reach) { at = pr.snaps[0].at; snap = pr.snaps[0].kind }    // nearest first
                var end = { at: at, shown: shown(at), part: part, snap: snap }
                if (!s.measureFrom) { s.measureFrom = end; return }
                var from = s.measureFrom
                s.measureFrom = null
                s.measureBusy++
                return s.ppost("/measure", { from: from.shown, to: end.shown, from_on: from.at, to_on: end.at }).then(function (r) {
                    s.measureBusy = Math.max(0, s.measureBusy - 1)
                    var across = from.part !== end.part
                    s._addMeasure({ kind: "distance", a: from.at, b: end.at, pa: from.part, pb: end.part, frame: tag, how: "computed",
                        label: F.fmt(r.distance_mm, 2) + " mm",
                        detail: "dX " + F.fmt(Math.abs(r.dx_mm), 2) + "  dY " + F.fmt(Math.abs(r.dy_mm), 2) + "  dZ " + F.fmt(Math.abs(r.dz_mm), 2),
                        context: from.snap.charAt(0).toUpperCase() + from.snap.slice(1) + " to " + snap + (across && tag !== "print" ? " · between parts, in the " + s._frameName(tag) : ""),
                        label_at: [(from.at[0] + end.at[0]) / 2, (from.at[1] + end.at[1]) / 2, (from.at[2] + end.at[2]) / 2] })
                }, function (e) { s.measureBusy = Math.max(0, s.measureBusy - 1); s.fail(e) })
            } else if (kind === "face") {
                var f = pr.face, feat = s.featureById(pr.feature)
                s._addMeasure({ kind: "face", at: pr.on, part: part, face: f, how: "computed", label: F.fmt(f.area_mm2, f.area_mm2 < 100 ? 2 : 1) + " mm²",
                    detail: f.type + (feat ? " of " + feat.label : "") + " · normal " + F.fmt(f.tilt_deg, 1) + "° from straight up as printed: " + f.tilt + " · " + f.method,
                    label_at: [pr.on[0] + f.normal[0] * 7, pr.on[1] + f.normal[1] * 7, pr.on[2] + f.normal[2] * 7] })
            } else {
                var c = pr.circle
                if (!c || (c.edge_distance_mm !== undefined && c.edge_distance_mm > Math.max(reach * 2, 1.5)))
                    return s.measureNote("No circle there. Click the wall or rim of a hole or round boss.")
                s._addMeasure({ kind: "diameter", at: pr.on, part: part, circle: c, how: c.method === "fitted" ? "fitted" : "computed", label: "Ø " + F.fmt(c.diameter_mm, 2) + " mm",
                    detail: (c.hole === true ? "hole" : c.hole === false ? "round boss" : c.surface || "circle") + " · "
                        + (c.method === "fitted" ? "fitted to " + c.points + " mesh edge points, rms " + F.fmt(c.rms_mm, 3) + " mm" : "exact, from the CAD solid"),
                    label_at: c.center || pr.on })
            }
        }, function (e) { done(); s.fail(e) })
    }

    // ── selections and annotations (form/selection.py) ──
    // The Annotate tool picks points, edges, faces or paints a region on the part; the engine analyses the selection
    // on the CAD solid. Kept, it becomes an annotation of the head revision: a pin in the viewport, a row in the
    // panel, and a message for the agent with the exact numbers.
    property bool selecting: false
    property string selMode: "face"            // point | edge | face | brush | lasso
    property real brushMm: 3                   // brush radius, mm
    property var selItems: []                  // what was picked: [{ kind, at | points, radius, part }] (print frame)
    property var selection: null               // the engine's analysis of selItems: items with numbers and meshes, summary, text
    property int selBusy: 0
    property string selSay: ""
    property int _selSeq: 0
    property var annFocus: null                // a kept annotation being looked at: { id, analysis }
    readonly property var annotations: project && project.annotations ? project.annotations : []
    property var _selSayOff: Timer { interval: 2600; onTriggered: s.selSay = "" }
    function selNote(t) { selSay = t; _selSayOff.restart() }
    function setSelecting(on) {
        if (on && measuring) setMeasuring(false)
        selecting = !!on; selSay = ""
        if (on && viewer) viewer.setMarker(null)
    }
    function selAdd(items, add) {              // add: keep what is selected (Shift); else start again
        if (!items || !items.length) return
        selItems = (add ? selItems : []).concat(items).slice(-24)
        annFocus = null
        _selRun()
    }
    function selRemove(i) { var a = selItems.slice(); a.splice(i, 1); selItems = a; if (a.length) _selRun(); else selection = null }
    function selClear() { _selSelSeq(); selItems = []; selection = null }
    function _selSelSeq() { return ++_selSeq }
    function _selRun() {
        var seq = _selSelSeq(), items = selItems
        selBusy++
        return ppost("/select", { items: items }).then(function (r) {
            s.selBusy = Math.max(0, s.selBusy - 1)
            if (seq === s._selSeq) s.selection = r
        }, function (e) { s.selBusy = Math.max(0, s.selBusy - 1); if (seq === s._selSeq) s.fail(e) })
    }
    function keepSelection(name, note) {
        if (!selItems.length) return Promise.resolve(null)
        return ppost("/annotate", { items: selItems, name: name || "", note: note || "" }).then(function (a) {
            s.toast("Kept as “" + a.name + "”", "Saved with " + F.pad(a.rev) + ". Its pin stays on the part.")
            var an = s.selection
            s.selItems = []; s.selection = null
            s.annFocus = { id: a.id, analysis: an }
            return s.refresh(false).then(function () { return a })
        }, function (e) { s.fail(e); return null })
    }
    function focusAnnotation(a) {              // show a kept annotation: its numbers again, and its overlay
        if (!a) { annFocus = null; return }
        annFocus = { id: a.id, analysis: null }
        var seq = _selSelSeq()
        ppost("/annotation_analyze", { id: a.id, rev: a.rev <= (project ? project.head : a.rev) ? a.rev : null }).then(function (r) {
            if (s.annFocus && s.annFocus.id === a.id) s.annFocus = { id: a.id, analysis: r }
        }, function (e) { s.fail(e) })
    }
    function updateAnnotation(id, name, note) {
        return ppost("/annotation", { id: id, name: name, note: note }).then(function () { return s.refresh(false) }, fail)
    }
    function deleteAnnotation(id) {
        if (annFocus && annFocus.id === id) annFocus = null
        return ppost("/annotation_delete", { id: id }).then(function () { s.toast("Annotation deleted"); return s.refresh(false) }, fail)
    }
    function cutThrough(x) {                   // a section through a selected point that contains its normal: the wall there, in section
        if (!viewer || !x || !x.on) return
        var part = x.part || "", p = viewer.shownPoint(part, x.on), n = viewer.shownDir(part, x.normal || [0, 0, 1])
        var k = Math.abs(n[0]) >= Math.abs(n[1]) && Math.abs(n[0]) >= Math.abs(n[2]) ? 0 : Math.abs(n[1]) >= Math.abs(n[2]) ? 1 : 2
        var i = k === 1 ? 0 : 1                 // facing X or Z: cut across Y; facing Y: cut across X
        var ax = ["x", "y", "z"][i], b = viewer.bounds, sh = viewer.shiftTo
        var v = p[i] + sh[ax], t = (v - b.lo[ax]) / Math.max(1e-6, b.hi[ax] - b.lo[ax])
        setSection(ax, Math.min(0.98, Math.max(0.02, t)))
    }
    function annotationById(id) { for (var i = 0; i < annotations.length; i++) if (annotations[i].id === id) return annotations[i]; return null }
    function askAboutSelection(text, what) {   // puts the selection, with its numbers, in the composer; you add the question
        talkOpen = true
        recallChat((what ? "About " + what + " on " + (project ? project.name : "this design") + ":\n" : "About this selection on " + (project ? project.name : "this design") + ":\n")
            + text + "\n\nMy question: ")
    }
    property var _selReset: Connections { target: s
        function onPidChanged() { s._selSeq++; s.selItems = []; s.selection = null; s.annFocus = null; s.selecting = false; s.selBusy = 0 }
        function onAnalysisKeyChanged() { if (s.selItems.length) { s.selItems = []; s.selection = null }; s.annFocus = null } }

    // ── colours and materials (form/materials.py) ──
    // The project keeps color and material, and parts: { id: { color, material, ... } } (the slicer reads the same
    // fields to pick the filament per part); a part's own wins over the design's.
    property var materialCat: null             // GET /materials: [{ id, label, heat_c, density_g_cm3, color, note }], swatches
    readonly property var appearance: {
        if (!project) return { color: null, material: null, parts: ({}) }
        var ps = project.parts || ({}), out = ({})
        for (var k in ps) if (ps[k] && (ps[k].color || ps[k].material)) out[k] = { color: ps[k].color || null, material: ps[k].material || null }
        return { color: project.color || null, material: project.material || null, parts: out }
    }
    function loadMaterials() { if (!materialCat) get("/materials").then(function (r) { s.materialCat = r }, function () {}) }
    function material(id) {
        var ms = materialCat ? materialCat.materials : [], k = id ? String(id).toUpperCase() : ""
        if (k === "NYLON" || k === "PA/NYLON") k = "PA"
        for (var i = 0; i < ms.length; i++) if (ms[i].id === k) return ms[i]
        return null
    }
    function look(part) {                      // { color, material, own } as drawn and printed
        var a = appearance, own = part && a.parts ? (a.parts[part] || {}) : {}
        var mat = material(own.material) || material(a.material)
        return { color: own.color || a.color || (mat ? mat.color : null), material: mat ? mat.id : null, own: !!(own.color || own.material) }
    }
    function setLook(part, color, material) {  // undefined keeps, null clears
        var body = { part: part || "" }
        if (color !== undefined) body.color = color
        if (material !== undefined) body.material = material
        return ppost("/appearance", body).then(function () { return s.refresh(false) }, fail)
    }
    property var _matLoad: Connections { target: s; function onPidChanged() { if (s.pid) s.loadMaterials() } }
    property var _gameReset: Connections { target: s; function onPidChanged() { s.game = null; s.gameLods = ({}); s.gameLod = 0; s.gameError = ""; s.gameErrorHint = "" } }

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
        endCompare()                         // another revision on screen: the ghost would describe the wrong pair
        if (n === project.head) { scrub = null; if (preview) { viewer.setModel(preview); viewer.setGhost(view) } else showHead() }
        else { scrub = { rev: n, view: v }; viewer.flagged = []; viewer.setModel(v); viewer.setGhost(null) }
    }
    // Dragging along the timeline asks for several revisions in a row and the answers can arrive out of order.
    // Only the latest request is shown: a late answer must not put an old revision back after "Back to head".
    property int _revAsk: 0
    function showRev(n, fade) {
        if (!project) return Promise.resolve()
        var ask = ++_revAsk
        return loadRev(n).then(function (v) {
            if (ask !== s._revAsk) return
            if (fade) fadeTo(function () { if (ask === s._revAsk) s._showScrub(n, v) }); else s._showScrub(n, v)
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
    function branchFrom(n) { stopMorph(); _revAsk++; scrub = null; checkout(n) }
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
        // show the new name at once: the engine may be busy building thumbnails and answer seconds later
        if (studio && studio.projects) {
            var before = studio
            studio = Object.assign({}, studio, { projects: studio.projects.map(function (p) { return p.id === id ? Object.assign({}, p, { name: name }) : p }) })
            return post("/projects/" + id + "/rename", { name: name }).then(function (r) { reloadStudio(); if (id === s.pid) refresh(false); return r },
                                                                             function (e) { studio = before; reloadStudio(); fail(e) })
        }
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

    // ── How a design starts (form/start.py): Home's composer, purpose, blank, links, sketches; concepts; measurements ──
    // Recipes and briefs are not offered here any more; agents may still use recipes, and older designs open as before.
    property var whatsNew: null        // GET /whatsnew: { version, show, markdown, highlights } while the modal is up
    property var startInfo: null       // GET /start: { purpose, printer: { name, available } }
    signal morphFrom(rect r)           // Home: the composer's place as it hands over to the workspace (MorphFrame)
    property var chatLinks: []         // page links pasted into the composer: { url, host }; passed on, never downloaded
    property var concepts: []          // open concept groups (form/concepts.py): boards with members and numbers
    property int startFocus: 0         // bumps when Home's composer should take the keyboard
    property var _startLoad: Connections { target: s
        function onScreenChanged() {
            if (s.screen !== "home") return
            s.loadStart(); s.loadConcepts()
            if (!s.chatBusy && s.conv && s.conv.messages) s.newChat()      // Home's composer always starts something new
        } }
    function loadStart() {
        return get("/start").then(function (r) { startInfo = r; return r }, function () { return null })
    }
    // what the next design is for, chosen on Home: Store.newPurpose (form/purpose.py's default until one is picked)
    // "any" (Home's "Make it for: Anything") leaves it unsaid: a 3D model unless the request says it is for printing
    function setNewPurpose(p) { if (p === "print" || p === "model" || p === "game") newPurpose = p; else if (p === "any" || p === "") newPurpose = "" }
    readonly property string printerName: startInfo && startInfo.printer && startInfo.printer.name ? startInfo.printer.name : ""
    // Start blank: the workspace with an empty build plate and nothing on it. No design exists until something is
    // described, sketched or imported; what it is for (newPurpose) waits for that first message.
    property bool blankCanvas: false
    function startBlank() {
        newChat()
        pid = ""; data = null; view = null; compare = null; layers = null; preview = null
        blankCanvas = true; designingSince = Date.now() / 1000; convNoDesign = false; steered = false; agentElsewhere = null
        screen = "designing"
        return Promise.resolve(true)
    }
    // the starting block (form/start.py BLANK_SOURCE): a rounded block with its sizes as parameters, no agent needed
    function startBlock(name) {
        var pu = newPurposeEffective; newPurpose = ""; blankCanvas = false
        return post("/start/blank", { name: name || "", purpose: pu }).then(function (r) {
            return reloadStudio().then(function () { return open(r.id).then(function () { track(r.job); setStage("shape") }) })
        }, fail)
    }
    // the conversation that files, sketches and links attach to before the first message is sent
    function ensureConv() {
        if (convId) return Promise.resolve(convId)
        return post("/conversations", { project: pid || null, agent: chatAgent, model: chatModel, effort: chatEffort, draft: true }).then(function (m) {
            if (convId === "") { convId = m.id; conv = m }
            return convId
        })
    }
    // a link: a file (STL, STEP, 3MF, PDF, picture) is fetched and attached; a page is passed to the agent as a link
    function fetchLink(url) {
        url = String(url || "").trim()
        if (!/^https?:\/\//i.test(url)) { toast("That is not a web address", "Paste a link that starts with https://", true); return Promise.resolve(null) }
        return ensureConv().then(function (id) {
            fetching++                                     // the download shows its progress (fetchProgress) while it runs
            return post("/conversations/" + id + "/fetch", { url: url }).then(function (r) {
                fetching = Math.max(0, fetching - 1)
                if (convId !== id) return r
                if (r.attachments) {
                    chatAttach = chatAttach.concat(r.attachments)
                    toast("Fetched " + r.fetched.name, F.bytes(r.fetched.bytes) + " from " + r.fetched.host)
                } else if (r.link) {
                    chatLinks = chatLinks.filter(function (l) { return l.url !== r.link.url }).concat([r.link])
                    // a site that will not hand the file over (a sign-in, a token): say why and what to do, calmly
                    if (r.link.reason) toast(r.link.reason, r.link.how || "")
                }
                return r
            })
        }).then(function (r) { return r }, function (e) { fetching = Math.max(0, fetching - 1); fail(e); return null })
    }
    function dropLink(url) { chatLinks = chatLinks.filter(function (l) { return l.url !== url }) }
    // a sketch from the sketch pad: its structured geometry (JSON) and its picture go with the next message
    function attachSketch(sketch, pngUrl) {
        return ensureConv().then(function (id) {
            var both = [post("/conversations/" + id + "/sketch", { "sketch": sketch, "name": "sketch" })]
            if (pngUrl) both.push(upload("/conversations/" + id + "/attach?name=sketch.png", pngUrl))
            return Promise.all(both).then(function (rs) {
                if (convId !== id) return rs[0]
                var add = []
                rs.forEach(function (r) { add = add.concat(r.attachments || []) })
                chatAttach = chatAttach.concat(add)
                return rs[0]
            })
        }).then(function (r) { return r }, function (e) { fail(e); return null })
    }
    // Home's composer: the message goes to the agent and the workspace opens at once, in its "being designed" state;
    // the design is attached the moment the agent creates it (follow, below)
    function startDesign(text) {
        text = (text || "").trim()
        if (!text && !chatAttach.length && !chatLinks.length) return
        if (!text) text = chatAttach.some(function (a) { return a.kind === "sketch" }) ? "Design this from my sketch."
                        : chatAttach.some(function (a) { return a.kind === "image" }) ? "Design a part from this photo."
                        : chatAttach.length ? "Design a part around this file." : "Start from this link."
        if (!chatReady) { toast("No agent is connected", "Start blank, or connect an agent in Settings › Agents & models.", true); return }
        if (pid) { pid = ""; data = null; view = null }
        designingSince = Date.now() / 1000
        blankCanvas = false; convNoDesign = false; steered = false; agentElsewhere = null
        screen = "designing"
        send(text)
    }
    property real designingSince: 0
    function leaveDesigning() { if (screen === "designing") home() }
    function answerMeasure(qid, value, method) {
        var id = convId
        if (!id) return Promise.resolve()
        chatAsking = null
        return post("/conversations/" + id + "/answer", { id: qid, text: String(value), choices: [method], measure: { value: value, method: method } }).then(function (a) {
            if (convId === id) _chatTick()
            var m = a && a.rev ? a : null
            if (m && pid) { _buildNext = Date.now(); refresh(true).then(function () { buildTick++ }) }
            if (m) toast("Measured " + F.fmt(value, 2) + " mm", "Committed as " + F.pad(m.rev) + (method === "estimate" ? ", still assumed." : ", measured with " + method + "."))
            return a
        }, function (e) { fail(e); if (convId === id) _chatTick() })
    }
    // concepts: several real designs side by side; the person picks one, or asks the agent for a mix
    function loadConcepts() { return get("/concepts?state=open").then(function (r) { concepts = r.groups || []; return concepts }, function () { return [] }) }
    function openConcepts(gid) { loadConcepts().then(function () { openSheet("concepts", { group: gid }) }) }
    function pickConcept(gid, project, keepOthers) {
        return post("/concepts/" + gid + "/pick", { project: project, keep_others: !!keepOthers }).then(function (r) {
            sheet = null; loadConcepts()
            _buildNext = Date.now()
            return reloadStudio().then(function () { return open(project) }).then(function () {
                buildTick++
                toast("Continuing with " + (r.group && r.group.name ? r.group.name : "the concept you picked"), r.trashed && r.trashed.length ? F.plural(r.trashed.length, "other concept") + " moved to .trash, kept until you remove it." : "")
            })
        }, fail)
    }
    // close a group without a pick: keep "all" leaves every concept as a design of its own, "none" moves them to .trash
    function dismissConcepts(gid, keep) {
        return post("/concepts/" + gid + "/dismiss", { keep: keep === "none" ? "none" : "all" }).then(function (r) {
            if (sheet && sheet.kind === "concepts") sheet = null
            loadConcepts(); reloadStudio()
            if (r.keep === "none") toast("Concepts discarded", F.plural(r.trashed.length, "concept") + " moved to .trash, kept until you remove it.")
            else toast("Concepts kept as designs", F.plural(r.kept.length, "design") + " added to your designs.")
            return r
        }, fail)
    }
    function mixConcepts(gid, words) {
        var g = concepts.filter(function (c) { return c.id === gid })[0]
        if (!g || !String(words).trim()) return
        var list = g.members.map(function (m) { return m.letter + " = " + m.project + " (" + m.title + ")" }).join("; ")
        sheet = null
        if (convId && conv && conv.project && pid) { pid = ""; data = null; view = null }
        screen = "designing"; designingSince = Date.now() / 1000
        send("Mix the concepts of group " + gid + ": " + String(words).trim() + ". The concepts are " + list
             + ". Write the mix as one new concept with propose_concepts(group=\"" + gid + "\").")
    }
    property int buildTick: 0          // bumps when the workspace should build the part up, feature by feature
    // when a new build was asked to grow in: the next head geometry shown (showHead) is revealed feature by feature.
    // Set before the geometry loads, so the finished part is never drawn first and then taken apart.
    property real _buildNext: 0
    // .formstudio (or an older .formproj) archive, or a conversation exported as JSON
    function importFile(fileUrl) {
        var name = decodeURIComponent(String(fileUrl).replace(/^.*[\/\\]/, ""))
        return upload("/archive/import?name=" + encodeURIComponent(name), fileUrl).then(function (r) {
            sheet = null
            if (r.conversation) {
                loadConvs(); openConv(r.conversation.id); talkOpen = true
                toast("Conversation imported", r.conversation.title); return r
            }
            var n = r.conversations ? r.conversations.length : 0
            toast("Imported “" + r.name + "”", (r.renamed_from ? "A design with the id “" + r.renamed_from + "” exists, so this one is “" + r.id + "”. " : "")
                  + (n ? F.plural(n, "conversation") + " came with it." : "Outputs are rebuilt on this computer."))
            return reloadStudio().then(function () { loadConvs(); return open(r.id) })
        }, fail)
    }
    signal exportRequested(string kind, string id, string fmt)          // Exports.qml opens the save dialog
    function exportProject(id) { if (id) exportRequested("project", id, "") }
    function exportConversation(id, fmt) { if (id) exportRequested("conversation", id, fmt || "md") }
    function askImport() { exportRequested("import", "", "") }
    function checkWhatsNew(headless) {
        if (headless) return
        // shown once: it counts as seen the moment it opens, however it is closed
        get("/whatsnew").then(function (r) {
            if (!r.show || welcome) return
            whatsNew = r; openSheet("whatsnew")
            post("/whatsnew/seen", { version: r.version }).then(function () {}, function () {})
        }, function () {})
    }
    function showWhatsNew(version) {
        get("/whatsnew?version=" + encodeURIComponent(version || Bridge.version)).then(function (r) { whatsNew = r; openSheet("whatsnew") }, fail)
    }
    function closeWhatsNew() { openSheet(null) }
}
