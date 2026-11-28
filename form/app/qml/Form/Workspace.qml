import QtQuick
import QtQuick.Controls
import QtQuick.Window
import QtCore
import "F.js" as F
import "ToolSet.js" as ToolSet
import "." as Tools      // Timeline and ContextMenu are also Qt type names; qualify ours

// A project, as Lightdesk: the 3D view fills the window and everything else is a pane of glass over it.
//
//   left          the tool dock (one tool active at a time); the active tool's options sit beside it
//   bottom left   the size of what is on screen, one small line, above the view buttons
//   right         the Program: the stage's panel. In Design it is the features as a listing that runs while a build
//                 plays; in the other stages it is that stage (Describe, Fit, Review, Make)
//   bottom right  the pipeline: where the artifacts of this revision stand
//   bottom centre the conversation bar (Main.qml) and, while a build plays, the cue above it
// Legends and measurements dock left of the Program and fold to their header. The camera is told how much of the view
// these cover and keeps the part in the rest; it eases when that changes (the transcript opening, a build starting).
Item {
    id: ws
    readonly property var d: Store.data
    function noteColor(c) { return c === "ok" ? Theme.pass : c === "warn" ? Theme.amber : c === "fail" ? Theme.signal : c === "draft" ? Theme.datum : Theme.ink3 }
    // the stage's status, as one sentence under the tabs
    function stageSay(id) {
        if (!d || !Store.head) return ["", ""]
        var head = F.pad(d.project.head), roll = d.checks ? d.checks.rollup : null
        if (id === "brief") {
            var k = d.recipe.params.filter(function (p) { return p.group === "brief" })
            var m = k.filter(function (p) { var pv = Store.head.provenance[p.key]; return pv && pv.source === "measured" }).length
            return !k.length ? ["What it is for, and what is known about the things it must fit.", ""]
                : m === k.length ? ["Every dimension of the object is measured.", "ok"]
                : ["Anything not measured is carried as an assumption, all the way to release.", m ? "" : "warn"]
        }
        if (id === "shape") {
            var ft = Store.featureById(Store.feature), n = F.keys(Store.draftValues).length
            if (Store.hasDraft) return ["Draft open: " + F.plural(n, "parameter") + " changed, not committed.", "draft"]
            return ft ? ["A change here opens a draft of " + head + ". Nothing is kept until you commit it.", ""]
                : [F.plural(d.recipe.features.length, "feature") + " in build order. Select one here or on the model to change it.", ""]
        }
        if (id === "fit") return d.fit ? [Math.round(d.fit.yield * 100) + "% of prints are modelled to fit, from what is known today.", d.fit.yield >= 0.95 ? "ok" : "warn"]
            : ["How accurate this printer is on this profile.", ""]
        if (id === "prove") {
            if (!roll) return ["The checks do not describe " + head + " yet.", "warn"]
            var all = roll.PASS + roll.WARN + roll.FAIL
            return roll.FAIL ? [F.plural(roll.FAIL, "check") + " of " + all + " failed for " + head + ".", "fail"]
                : roll.WARN ? [F.plural(roll.WARN, "check") + " of " + all + " " + (roll.WARN === 1 ? "needs" : "need") + " a look for " + head + ". None failed.", "warn"]
                : ["All " + all + " checks pass for " + head + ".", "ok"]
        }
        if (id === "release") return d.approval.state === "approved" ? [F.pad(d.approval.rev) + " is released.", "ok"]
            : d.gate.ready ? [head + " is ready to approve." + (d.gate.warnings && d.gate.warnings.length ? " " + F.plural(d.gate.warnings.length, "warning") + " to acknowledge first." : ""), ""]
            : [head + " is not ready to release.", "warn"]
        if (id === "document") return [Store.documentCount ? F.plural(Store.documentCount, "document") + " made for " + head + "." : "No documents made for " + head + " yet.", ""]
        return ["", ""]
    }

    // ── tools ────────────────────────────────────────────────
    readonly property string tool: Ws.tool
    readonly property bool compact: ws.width - shift < 1300                 // a narrow window: controls shorten, docks fold
    readonly property bool sim: !!Store.layers
    // the conversation column (Main.qml) takes the left of the window: the tools, the size line, the view buttons and
    // the stage begin right of it. 0 while it is folded to the bar.
    readonly property bool col: Store.talkCol > 0
    // A window under 1200 px has room for the conversation column or for the panes on the right, not both: while the
    // column is open the panes fold to one button in their corner (it folds the conversation and brings them back).
    readonly property bool panesOff: (col && ws.width < 1200) || Store.focusView || Store.paneFolded
    // a click into the 3D view from the conversation folds its column to the bar (calm); a message sent from the bar,
    // the bar's status line or Ctrl+J bring it back
    // (a press, not the keyboard arriving: a design that has just opened already has the keyboard on the part, and
    // the first click into the view must fold the column like any other)
    Connections { target: vp; function onTouched() { if (ws.col) Store.talkCalm = true } }
    // the part goes back to the middle of the free stage when the layout changes (Viewport.layoutChanged): a column
    // folds, opens or is resized, the pane folds, Focus. A view the person panned or zoomed is theirs until then.
    onPaneXChanged: vp.layoutChanged()
    Connections { target: Store; function onTalkColChanged() { vp.layoutChanged() } }
    readonly property real colFoot: ws.height - Theme.edge        // the foot of the side columns
    readonly property real paneX: panesOff ? ws.width - Theme.edge - 44 : insp.x      // where the right column begins
    // (the project rail opened takes 220 px at the left: with the conversation folded the stage starts right of it)
    property real shift: col ? Store.talkCol + Theme.gap - Theme.edge : (Frame.railOpen && !Store.focusView ? 220 + Theme.gap : 0)
    // the folded rail stands under the dock, above the size line (ProjectRail.qml, placed by Main.qml)
    Binding { target: Frame; property: "dockFoot"; value: rail.y + rail.height }
    Binding { target: Frame; property: "footTop"; value: status.y - 48 }
    Behavior on shift { enabled: insp.settled && !Store.talkDragging; NumberAnimation { duration: Motion.camera; easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } }
    // a design that declares how its parts go together: assembled / exploded / as printed. Separate bodies
    // with no declaration (form/recipes/assembly.py from_solids): as modelled / pulled apart.
    // A design with separate bodies and no declaration is shown as modelled, or pulled apart; Assembled is there but
    // off, and says what it needs: the design has to say where each part goes (assembly() in its source).
    readonly property bool asmDerived: !!Store.assembly && !!Store.assembly.derived
    readonly property var asmModes: asmDerived
        ? [{ value: "assembled", text: "Assembled", off: true, tip: "This design does not say how its parts go together, so Form Studio cannot place them. Ask the agent to add that to the design." },
           { value: "exploded", text: "Exploded" }, { value: "print", text: "As modelled" }]
        : [{ value: "assembled", text: "Assembled" }, { value: "exploded", text: "Exploded" }, { value: "print", text: "Print layout" }]
    function askAssembly() {
        var a = Store.assembly, n = a ? a.parts.length : 0
        Store.talkOpen = true
        Store.recallChat("This design prints " + n + " separate parts but does not say how they go together. "
            + "Add assembly() to the design source (design_guide, ASSEMBLIES) so Form Studio can show it assembled and check it: "
            + "place each part, give it an exploded offset and an assembly step, and declare the joints and any hardware. "
            + "Keep the print layout as it is.")
    }
    // the bed of the printer this design uses (form/printers.py), for the plate caption
    readonly property string bed: d && d.printer ? d.printer.env.envelope.slice(0, 2).map(function (x) { return F.fmt(x, 0) }).join(" × ") : "180 × 180"
    readonly property bool mapBlocked: !!Store.analysisMap && (Store.hasDraft || !!Store.compare)

    // ── the ribbon: the mode's tools, labelled and grouped at the head of the stage (ToolRibbon.qml, ToolSet.js) ──
    // Hidden (its own Hide, remembered between runs) the tools are icons in the dock again, as before.
    Settings { id: wsMem; category: "workspace"; property bool ribbon: true }
    readonly property bool ribbonOn: wsMem.ribbon && !!Store.view
    function setRibbon(on) { wsMem.ribbon = on }
    // where the stage's head begins: under the ribbon when it shows (38 + 6: the stage gives up 44 px, no more)
    readonly property real headY: Theme.paneTop + (ribbonOn ? 44 : 0)
    // the feature kinds the engine builds (GET /studio, form/modelling.py KINDS): a tool waiting for one appears
    // when it is listed (sweep, loft, rib, mirror, draft, split, move face, planes)
    readonly property var kinds: Store.studio && Store.studio.feature_kinds ? Store.studio.feature_kinds
                                 : ["fillet", "chamfer", "hole", "pattern", "shell", "extrude", "cut", "revolve"]
    function _benchFor(t) {                     // the Bench entry a tool opens: current first, then any that applies
        var ids = t.need && t.need.bench ? t.need.bench : [], best = null
        for (var i = 0; i < ids.length; i++) {
            var e = Store.benchEntry(ids[i])
            if (!e || e.state === "n/a") continue
            if (e.state === "current") return e
            if (!best) best = e
        }
        return best
    }
    function _toolDef(id) {
        var gs = ToolSet.MODES[Store.mode] || []
        for (var g = 0; g < gs.length; g++) for (var i = 0; i < gs[g].tools.length; i++) if (gs[g].tools[i].id === id) return gs[g].tools[i]
        for (var m in ToolSet.MODES) for (var g2 = 0; g2 < ToolSet.MODES[m].length; g2++)
            for (var j = 0; j < ToolSet.MODES[m][g2].tools.length; j++) if (ToolSet.MODES[m][g2].tools[j].id === id) return ToolSet.MODES[m][g2].tools[j]
        return null
    }
    function toolAvail(t) {
        var n = t.need
        if (!n) return true
        if (n.kind) { for (var i = 0; i < n.kind.length; i++) if (ws.kinds.indexOf(n.kind[i]) >= 0) return true; return false }
        if (n.bench) return !!ws._benchFor(t)
        if (n.when === "assembly") return !!Store.assembly
        if (n.when === "plates") return !!Store.assembly && Store.printUi
        if (n.when === "print") return Store.printUi
        if (n.when === "game") return Store.gameDesign
        if (n.when === "companions") return !!(Store.shown && Store.shown.companions && Store.shown.companions.length)
        return true
    }
    // the groups of the mode in front, cut to the tools this design can use; a group left empty is not shown
    // (kept as text and handed on only when it changes: the Bench is polled while a study runs, and a new list each
    // time would make the ribbon's buttons anew under the pointer, dropping a click)
    readonly property string _groupsSig: {
        Store.bench; Store.assembly; Store.printUi; Store.shown; ws.kinds         // what availability reads
        return JSON.stringify((ToolSet.MODES[Store.mode] || []).map(function (g) {
            return { id: g.id, caption: g.caption, tools: g.tools.filter(function (t) { return ws.toolAvail(t) }) }
        }).filter(function (g) { return g.tools.length > 0 }))
    }
    readonly property var ribbonGroups: JSON.parse(_groupsSig)
    readonly property var _sketchKinds: ["sketch", "extrude", "cut", "revolve"]
    readonly property var _annotateKinds: ["fillet", "chamfer", "hole", "shell", "part", "text"]
    // what the ribbon shows of a tool: lit, marked, off, and the label of a switch
    function toolState(id) {
        var t = ws._toolDef(id), sim = ws.sim
        if (_sketchKinds.indexOf(id) >= 0) return { active: sketch.busyHere && Ws.want === id, enabled: !sim && !Store.hasDraft,
                                                    hint: Store.hasDraft ? "Commit or discard the draft first." : undefined }
        if (_annotateKinds.indexOf(id) >= 0) return { active: ws.tool === "annotate" && Ws.want === id, enabled: !sim }
        if (id === "pattern") return { active: Ws.want === "pattern", enabled: !sim }
        if (id === "analyze") return { active: ws.tool === "analyze" && !sim, marked: !!Store.analysisMap }
        if (id === "mass") return { active: Store.massOn, toggle: true, enabled: !sim, label: Store.massOn ? "Hide mass" : "Mass" }
        if (id === "section") return { active: ws.tool === "section" && !sim, marked: !!Store.sectionNow() }
        if (id === "assembly") return { active: ws.tool === "assembly" && !sim, marked: Store.asmMode !== "print" }
        if (id === "history") return { active: ws.tool === "history" && !sim, marked: !!Store.scrub }
        if (id === "holds") return { active: vp.showCompanions, toggle: true, enabled: !sim, label: Store.companions ? "Hide what it holds" : "What it holds" }
        if (id === "plates") return { active: Store.asmMode === "print" && ws.tool === "assembly" }
        if (id === "slice") return { active: sim, enabled: !!ws.d && !!ws.d.slice, hint: ws.d && ws.d.slice ? undefined : "Needs a current slice of this revision." }
        if (id === "game" || id === "render") return { enabled: !Store.hasDraft, hint: Store.hasDraft ? "Commit or discard the draft first." : undefined }
        if (id === "views") return { active: ws.tool === "views" && !sim, enabled: !sim }
        if (id === "dims") return { active: Store.dims, toggle: true, enabled: !sim, label: Store.dims ? "Hide dimensions" : "Dimensions" }
        if (id === "frame") return { enabled: !sim, label: Store.feature ? "Frame selection" : "Frame" }
        if (t && t.need && t.need.bench) {
            var e = ws._benchFor(t)
            if (!e) return { enabled: false }
            var ch = Store.benchChapter(e)
            return { active: (Results.id === e.id && Results.on) || (Store.mode === Store.benchModeOf(ch) && (Store.benchSel[ch] || "") === e.id),
                     marked: e.state === "current", hint: (t.hint || "") + " " + Store.benchSays(e).replace(/^./, function (c) { return c.toUpperCase() }) + "." }
        }
        if (t && t.need && t.need.kind) return { enabled: !Store.hasDraft,
            hint: (t.hint || "") + " Opens the conversation with the request written for you to finish; the agent adds it as a feature of the design." }
        return {}
    }
    function toolRun(id) {
        var t = ws._toolDef(id)
        if (_sketchKinds.indexOf(id) >= 0) { ws.setTool("sketch", id); return }
        if (_annotateKinds.indexOf(id) >= 0) { ws.setTool("annotate", id); return }
        if (id === "pattern") { ws.setTool("select", "pattern"); return }
        if (id === "analyze" || id === "section" || id === "assembly" || id === "history" || id === "views") { ws.setTool(id); return }
        if (id === "mass") { Store.massOn = !Store.massOn; return }
        if (id === "holds") { Store.toggleCompanions(); return }
        if (id === "plates") { if (ws.tool !== "assembly") ws.setTool("assembly"); Store.setAsmMode("print"); return }
        if (id === "slice") { if (ws.sim) Store.showLayers(false); else Store.simulate({ at: 0, play: true }); return }
        if (id === "game") { Store.openSheet("game"); return }
        if (id === "render") { Store.openSheet("render"); return }
        if (id === "dims") { Store.toggleDims(); return }
        if (id === "frame") { Store.frameSelection(); return }
        if (t && t.need && t.need.bench) {                // a study, route or document: its row opened in the Bench pane
            var e = ws._benchFor(t)
            if (!e) return
            var ch = Store.benchChapter(e), m = Store.benchModeOf(ch)
            if (Store.mode !== m) Store.setStage(m)
            Store.benchPick(ch, e)
            return
        }
        // a feature kind the engine builds that has no panel in the window yet: the request, written in the conversation
        if (t && t.need && t.need.kind) { Store.talkOpen = true; Store.talkCalm = false; Store.recallChat(t.ask || ("Add a " + t.label.toLowerCase() + " to this design: ")) }
    }
    function setTool(t, want) {
        if (ws.sim) Store.showLayers(false)
        want = want || ""
        if (t === "sketch") {                                       // Sketch, Extrude, Cut, Revolve: a profile on a face or a plane
            if (sketch.picking && Ws.want === want) { sketch.end(); return }
            if (Ws.tool !== "select") ws.setTool("select")
            Ws.want = want; sketch.pick(want === "sketch" ? "extrude" : want)
            return
        }
        if (sketch.busyHere) sketch.end()
        if (t === Ws.tool && want === Ws.want && t !== "select") { t = "select"; want = "" }   // the active tool, clicked again, hands back to Select
        var was = Ws.tool
        Ws.want = want
        if (t === "annotate" && want) Store.selMode = want === "fillet" || want === "chamfer" ? "edge" : "face"
        if (was === t) return
        Ws.tool = t
        if (was === "measure") Store.setMeasuring(false)
        if (was === "annotate") Store.setSelecting(false)
        if (t === "annotate") Store.setSelecting(true)
        if (was === "history") { Store.timelineOpen = false; Store.endScrub() }
        if (t === "measure") Store.setMeasuring(true)
        if (t === "history") Store.timelineOpen = true
        if (t === "section" && !Store.sectionNow()) Store.setSection("y", 0.5)
    }
    // the store can change these from the palette, a key, a check's marker or Esc: the rail follows
    Connections {
        target: Store
        function onMeasuringChanged() { if (Store.measuring) Ws.tool = "measure"; else if (Ws.tool === "measure") Ws.tool = "select" }
        function onSelectingChanged() { if (Store.selecting) Ws.tool = "annotate"; else if (Ws.tool === "annotate") { Ws.tool = "select"; Ws.want = "" } }
        function onTimelineOpenChanged() { if (Store.timelineOpen) Ws.tool = "history"; else if (Ws.tool === "history") Ws.tool = "select" }
        function onSectionChanged() {
            var on = !!(Store.section && Store.section.axis)
            if (on && Ws.tool === "select") Ws.tool = "section"; else if (!on && Ws.tool === "section") Ws.tool = "select"
        }
        function onAnalysisMapChanged() { if (Store.analysisMap && Ws.tool === "select") Ws.tool = "analyze" }
        function onAsmModeChanged() { if (Store.asmMode !== "print" && Ws.tool === "select" && Store.assembly) Ws.tool = "assembly" }
        function onPidChanged() { sketch.end(); Ws.tool = "select"; Ws.want = ""; Ws.refineWant = -1; Store.overview = false }
        function onModeChanged() { if (Store.mode !== "shape" && (sketch.busyHere || Ws.want)) ws.setTool("select") }
        function onFadeTo(apply) { vp.swap(apply) }                 // the timeline and anything else that swaps the geometry
    }
    // a design that has just opened has the keyboard on the part, not in the conversation box Home left it in
    Component.onCompleted: { Store.backdrop = studio; Ws.tool = Store.measuring ? "measure" : Store.timelineOpen ? "history" : "select"; vp.forceActiveFocus() }

    readonly property Item focusItem: Window.activeFocusItem
    readonly property bool keys: Store.screen === "work" && !Store.sheet && !Store.paletteOpen && !(focusItem && focusItem.cursorPosition !== undefined) && !sketch.on
    // the mode's own tools answer to their keys only in that mode (Design: Sketch S, then Shift with the tool's letter)
    readonly property bool designKeys: keys && Store.mode === "shape" && !ws.sim
    Shortcut { sequence: "S"; enabled: ws.designKeys && !Store.hasDraft; onActivated: ws.setTool("sketch", "sketch") }
    Shortcut { sequence: "Shift+E"; enabled: ws.designKeys && !Store.hasDraft; onActivated: ws.setTool("sketch", "extrude") }
    Shortcut { sequence: "Shift+X"; enabled: ws.designKeys && !Store.hasDraft; onActivated: ws.setTool("sketch", "cut") }
    Shortcut { sequence: "Shift+R"; enabled: ws.designKeys && !Store.hasDraft; onActivated: ws.setTool("sketch", "revolve") }
    Shortcut { sequence: "Shift+F"; enabled: ws.designKeys; onActivated: ws.setTool("annotate", "fillet") }
    Shortcut { sequence: "Shift+C"; enabled: ws.designKeys; onActivated: ws.setTool("annotate", "chamfer") }
    // Hole is Shift+H. (It did nothing while "Show all features" held the same keys in ContextMenu.qml: two Shortcuts
    // with one sequence in a window are ambiguous to Qt, and neither fires. Show all features is Alt+H now.)
    Shortcut { sequence: "Shift+H"; enabled: ws.designKeys; onActivated: ws.setTool("annotate", "hole") }
    Shortcut { sequence: "Shift+P"; enabled: ws.designKeys; onActivated: ws.setTool("select", "pattern") }
    Shortcut { sequence: "Shift+S"; enabled: ws.designKeys; onActivated: ws.setTool("annotate", "shell") }
    Shortcut { sequence: "Shift+B"; enabled: ws.designKeys; onActivated: ws.setTool("annotate", "part") }
    Shortcut { sequence: "C"; enabled: ws.keys && Store.mode === "prove" && ws.tool !== "measure" && ws.tool !== "annotate"; onActivated: Store.massOn = !Store.massOn }
    Shortcut { sequence: "W"; enabled: ws.keys && Store.mode === "document"; onActivated: ws.setTool("views") }
    Shortcut { sequence: "V"; enabled: ws.keys; onActivated: ws.setTool("select") }
    Shortcut { sequence: "M"; enabled: ws.keys; onActivated: ws.setTool("measure") }
    Shortcut { sequence: "N"; enabled: ws.keys; onActivated: ws.setTool("annotate") }
    // inside a tool: its modes by key (measure: distance, face, diameter; annotate: point, edge, face, brush, lasso)
    Shortcut { sequence: "D"; enabled: ws.keys && ws.tool === "measure"; onActivated: { Store.measureKind = "distance"; Store.measureFrom = null } }
    Shortcut { sequence: "G"; enabled: ws.keys && ws.tool === "measure"; onActivated: { Store.measureKind = "face"; Store.measureFrom = null } }
    Shortcut { sequence: "O"; enabled: ws.keys && ws.tool === "measure"; onActivated: { Store.measureKind = "diameter"; Store.measureFrom = null } }
    Shortcut { sequence: "P"; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.selMode = "point" }
    Shortcut { sequence: "G"; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.selMode = "face" }
    Shortcut { sequence: "R"; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.selMode = "edge" }
    Shortcut { sequence: "B"; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.selMode = "brush" }
    Shortcut { sequence: "L"; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.selMode = "lasso" }
    Shortcut { sequence: "["; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.brushMm = Math.max(0.5, Store.brushMm / 1.25) }
    Shortcut { sequence: "]"; enabled: ws.keys && ws.tool === "annotate"; onActivated: Store.brushMm = Math.min(25, Store.brushMm * 1.25) }
    // Analyze, Assembly and History are tools of Check: from any mode their key goes there, so the dock shows the
    // tool lit (a key that started a tool whose button was not on screen read as nothing happening)
    function checkTool(t) {
        if (Store.mode !== "prove") { Store.setStage("prove"); if (Ws.tool === t) return }
        ws.setTool(t)
    }
    Shortcut { sequence: "A"; enabled: ws.keys; onActivated: ws.checkTool("analyze") }
    Shortcut { sequence: "E"; enabled: ws.keys && !!Store.assembly; onActivated: ws.checkTool("assembly") }
    Shortcut { sequence: "T"; enabled: ws.keys; onActivated: ws.checkTool("history") }

    // ── the build-up: a new build from the agent (or a pick, or a measurement) grows in feature by feature, in build
    //    order, each one named as it arrives, so you watch the part being made. It is the real geometry of this
    //    revision revealed stage by stage (Viewport's build-up, started by Store.showHead); no extra builds run. ──
    QtObject {
        id: build
        property string label: ""
        property string sub: ""
        property int at: 0
        property int of: 0
        property bool running: false
        property string before: ""            // the step before this one, and the feature that comes after it
        property string after: ""
        property var last: []
        function labelsOf(ids) {
            var n = ids.map(function (id) { var f = Store.featureById(id); return f && f.label ? f.label : id }).filter(function (x) { return !!x })
            return n.length > 2 ? n.slice(0, 2).join(", ") + " and " + (n.length - 2) + " more" : n.join(", ") }
        function step(ids, at, count) {
            if (Store.building) return            // a streamed stage names itself (Store.buildingText)
            var names = ids.map(function (id) { var f = Store.featureById(id); return f && f.label ? f.label : id }).filter(function (n) { return !!n })
            label = names.length > 2 ? names.slice(0, 2).join(", ") + " and " + (names.length - 2) + " more" : names.join(", ")
            sub = count > 1 ? (at + 1) + " of " + count : ""
            // the steps before this one are in place; the feature after this step's last one is next
            if (at === 0) { Store.builtIds = []; before = "" } else { Store.builtIds = Store.builtIds.concat(last); before = build.labelsOf(last) }
            last = ids
            var fs = Store.recipe ? Store.recipe.features : [], nx = ""
            for (var i = 0; i < fs.length; i++) if (fs[i].id === ids[ids.length - 1] && i + 1 < fs.length) nx = fs[i + 1].label || fs[i + 1].id
            after = at + 1 < count ? nx : ""
            build.at = at + 1; build.of = count; running = true
            Store.buildAt = at + 1; Store.buildOf = count
            Store.revealing = ids                 // the Design list marks the rows being built
            flash.stop()
        }
        function done() { Store.revealing = []; Store.builtIds = []; Store.buildAt = 0; Store.buildOf = 0; last = []; if (Store.building) return; sub = ""; running = false; flash.restart() }
    }
    Timer { id: flash; interval: 1400; onTriggered: { build.label = ""; build.sub = "" } }
    Component.onDestruction: { Store.revealing = []; Store.builtIds = []; Store.buildAt = 0; Store.buildOf = 0 }
    // a build is playing: the stages an agent streams for this design, or the build-up of a new revision
    readonly property bool cueOn: (!!Store.building && Store.building.project === Store.pid) || build.running
    property bool cueRoom: false             // a build-up is playing in the view: the camera holds the framing of the finished part

    // ── centre: the part ─────────────────────────────────────
    Item {
        id: centre
        anchors.fill: parent
        // ── the free stage: the one rectangle the part, the cue and every overlay are laid out in ──
        // Right of the tool dock, under the top row, left of the panes (and of the legends' dock when it is open),
        // above the bottom row (the bar, taller when the transcript is open; the size line).
        QtObject {
            id: lay
            // The tool dock floats inside the stage at its left edge, over the room: it takes no column of its own.
            // The frame starts 28 px right of it: a part's left dimension line and its number stand outside the part's
            // own box, and must stay clear of the dock.
            readonly property real freeL: Theme.edge + 76 + ws.shift
            readonly property real freeR: ws.paneX - 12
            // The part stands on the bar's centre line (the window's) whenever the free stage has room on both sides
            // of it: at least 60 % of its width. Otherwise, a legend open or a narrow window, it stands in the middle
            // of the free stage.
            // (with the conversation as a column there is no bar: the stage is the free stage, and its middle the line)
            readonly property real axis: ws.col ? (freeL + freeR) / 2 : Store.barX + Store.barW / 2
            readonly property real half: Math.min(axis - freeL, freeR - axis)
            readonly property bool centred: 2 * half >= 0.6 * (freeR - freeL)
            readonly property real mid: (left + right) / 2          // the line the part, the cue and the stage's capsules stand on
            readonly property real left: centred ? axis - half : freeL
            readonly property real right: centred ? axis + half : freeR
            // While a build plays the finished part is framed as large as it stands at rest, not shrunk into the room
            // above the cue (a part half built would fill a quarter of the window; the mockup's fills a third). The
            // free area is the one at rest (over the bar as it will be, Store.barRestY; at most 100 px past the cue's
            // top), lifted so the last features end above the cue's first line. When the cue leaves the camera
            // settles down by that lift; it never re-frames and nothing changes size.
            readonly property bool cueing: cue.shown || ws.cueRoom
            readonly property real floorY: cueing ? Math.min(Store.barRestY, Store.barY, status.restY, cue.rest + 100) : Math.min(Store.barY, status.y, strip.on ? strip.y - 8 : 1e9, rstrip.on ? rstrip.y - 8 : 1e9)
            readonly property real cueLift: cueing ? Math.round(centre.height * 0.045) : 0
            readonly property real top: ws.headY + 4 - cueLift
            readonly property real bottom: centre.height - Math.max(60, centre.height - floorY + 26 + cueLift)
        }
        // the room: the 3D view and what belongs to it. This is what the panes blur, so nothing of theirs is in it.
        Item { id: studio; anchors.fill: parent
        Viewport {
            id: vp
            objectName: "viewport"
            labelRight: ws.paneX
            slack: 0.98
            scaleLeft: status.x; scaleFoot: status.y - 12
            floorGrid: Store.floorGrid
            results: true                // results of the later engines are drawn on the part here (Results.qml)
            anchors.fill: parent
            visible: !Store.layers
            asmMode: Store.asmMode; explode: Store.explode; pose: Store.pose
            platePlan: ws.d && ws.d.checks && ws.d.checks.context ? ws.d.checks.context.plates || null : null   // several plates (form/plates.py)
            stageMode: Store.stageMode                                            // the studio floor; the build plate only where the printer matters
            plateSize: ws.d && ws.d.printer ? Math.max(60, Math.max(ws.d.printer.env.envelope[0], ws.d.printer.env.envelope[1])) : 180
            hiddenFeatures: Store.hidden                                           // design tools: quick actions
            order: ws.d && ws.d.recipe && ws.d.recipe.features ? ws.d.recipe.features.map(function (f) { return f.id }) : []
            onRevealStep: function (ids, at, count) { build.step(ids, at, count) }
            onRevealDone: { build.done(); Store.reconSettle() }
            // another revision as a solid: right of Compare's wipe line, or cross-faded in while Before is held
            alt: Store.compare ? Store.compare.view : Store.peek ? Store.peek.view : null
            altK: !Store.compare && Store.peek && Store.peek.on ? 1 : 0
            wipeX: Store.compare ? wipe.at : -1
            // colours and materials: re-made whenever the design's appearance or the catalogue changes
            colorOf: { var a = Store.appearance, c = Store.materialCat; return function (part) { return Store.look(part).color || "" } }
            // what the HUD leaves free (lay, below): the camera keeps the part there and eases when it changes
            insetLeft: lay.left; insetTop: lay.top; insetRight: centre.width - lay.right; insetBottom: centre.height - lay.bottom
            // The build's frame is taken the moment a build-up starts, at once and before its first feature is drawn, so
            // the part never changes size while it grows; the camera settles with a glide when the cue has left.
            onRevealingChanged: if (revealing && !ws.cueRoom && !Theme.reduced) { var g = vp.insetGlide; vp.insetGlide = false; ws.cueRoom = true; vp.insetGlide = g }
                                else if (!revealing) ws.cueRoom = false
            onContextRequested: function (f, x, y) { Store.ctxMenu = { feature: f, x: x, y: y } }
            Component.onCompleted: { Store.viewer = vp; if (Store.view) { Store.showHead(); vp.setView("iso", false) }; glide.start() }
            Component.onDestruction: if (Store.viewer === vp) Store.viewer = null
            Timer { id: glide; interval: 400; onTriggered: vp.insetGlide = true }
            onPicked: function (f) { Store.pick(f) }
            onHoveredFeature: function (f, x, y) { chip.feat = Store.featureById(f); chip.x = Math.min(x + 14, centre.width - chip.width - 8); chip.y = y + 14 }
            // analysis maps and measuring (maps describe the committed revision, so a draft hides them)
            analysis: Store.hasDraft || Store.compare ? null : Store.analysis
            measuring: Store.measuring; measures: Store.measures; measureFrom: Store.measureFrom
            onProbed: function (hit, reach) { Store.measureClick(hit, reach) }
            massTotal: Store.massOn && Store.massShown ? Store.mass.total || null : null          // MassLayer: centre of mass, principal axes
            // selecting and annotations (form/selection.py)
            selecting: Store.selecting; selectMode: Store.selMode; brushMm: Store.brushMm
            selection: Store.selection ? Store.selection.items : []
            focusItems: Store.annFocus && Store.annFocus.analysis ? Store.annFocus.analysis.items : []
            annotations: Store.hasDraft || Store.scrub ? [] : Store.annotations
            headRev: Store.project ? Store.project.head : 0
            annFocusId: Store.annFocus ? Store.annFocus.id : ""
            onSelPicked: function (items, add) { Store.selAdd(items, add) }
            onSelMissed: Store.selNote("Nothing there. Pick on the part’s surface.")
            onAnnotationClicked: function (id) { Store.focusAnnotation(Store.annFocus && Store.annFocus.id === id ? null : Store.annotationById(id)) }
            onProbeMissed: Store.measureNote("Nothing there. Click on the part’s surface.")
            onHoveredValue: function (v, x, y, on) { vchip.on = on; vchip.v = v; vchip.x = Math.min(x + 14, centre.width - vchip.width - 8); vchip.y = y + 14 }
        }
        Loader { id: lv; anchors.fill: parent; active: !!Store.layers; source: "LayerView.qml"
            onLoaded: { item.leftInset = Qt.binding(function () { return Theme.edge + 62 + ws.shift }); item.topInset = Qt.binding(function () { return ws.headY + 4 }); item.rightInset = Qt.binding(function () { return centre.width - ws.paneX + 12 }); item.stripHeight = Qt.binding(function () { return Math.max(60, centre.height - Store.barY) }); item.axisX = Qt.binding(function () { return lay.mid }) } }
        // the corners of the room fall away
        Room { anchors.fill: parent; wall: false; poolK: 0; visible: !Store.layers }
        }
        // the key light answers: a faint pool over the floor that breathes while nothing happens, and narrows and warms
        // while a build plays. It lies over the room, not in it, so its breathing never makes the glass blur again.
        Room { id: keyLight; anchors.fill: parent; wall: false; vignetteK: 0; visible: !Store.layers && !Store.plateWanted
            poolX: (vp.shownLeft + (centre.width - vp.shownRight)) / 2 / Math.max(1, centre.width)
            poolY: Math.min(0.72, (vp.shownTop + (centre.height - vp.shownBottom)) / 2 / Math.max(1, centre.height) + 0.1)
            poolW: ws.cueOn ? 640 : 900; poolH: ws.cueOn ? 300 : 380
            poolK: Theme.dark ? (ws.cueOn ? 0.16 : 0.09) : (ws.cueOn ? 0.5 : 0.25)
            // (it does not breathe here: the pool's breath changed it by under one 8-bit level a step, which nobody
            // could see, and cost a still workspace two and a half redraws a second)
            breathe: false
            Behavior on poolW { NumberAnimation { duration: Theme.move(600); easing.type: Easing.InOutQuad } }
            Behavior on poolH { NumberAnimation { duration: Theme.move(600); easing.type: Easing.InOutQuad } }
            Behavior on poolK { NumberAnimation { duration: 600; easing.type: Easing.InOutQuad } } }

        // a sketch drawn on the part: the profile on its plane, its tools in the capsule, what to make of it at the foot
        SketchOnPart { id: sketch; anchors.fill: parent; z: 4; vp: vp; source: studio
            capX: Theme.edge + 60 + ws.shift; capY: ws.headY + 2
            capMax: Math.max(240, ws.paneX - capX - Theme.gap - (cube.visible ? cube.width + Theme.gap : 0))
            midX: ws.col ? (lay.freeL + lay.freeR) / 2 : lay.mid
            footL: rail.visible && rail.y + rail.height + 8 > footY - 44 ? capX : Theme.edge + ws.shift; footR: ws.paneX - Theme.gap
            footY: Math.min(centre.height - Theme.edge, status.y - 36, ws.col ? 1e9 : Store.barY - Theme.gap)      // above the scale cue, the size line and the bar
            onBusyHereChanged: { if (!busyHere && ["sketch", "extrude", "cut", "revolve"].indexOf(Ws.want) >= 0) Ws.want = ""; if (on && ["sketch", "extrude", "cut", "revolve"].indexOf(Ws.want) < 0) { if (Ws.tool !== "select") ws.setTool("select"); Ws.want = "sketch" } }
            onOnChanged: if (on && ["sketch", "extrude", "cut", "revolve"].indexOf(Ws.want) < 0) Ws.want = "sketch"
            Component.onCompleted: Store.sketchHost = sketch
            Component.onDestruction: if (Store.sketchHost === sketch) Store.sketchHost = null }

        // the cue: the build's lower third, over the room and above the bar. The same step is lit in the Program.
        Item {
            id: cue; objectName: "buildCaption"; z: 6
            // a stage streamed while the agent rewrites the design, or a step of the build-up of a new revision
            readonly property var st: Store.building && Store.building.project === Store.pid ? Store.building : null
            readonly property bool shown: !!build.label || !!st
            readonly property string caption: st ? Store.buildingText : build.label ? (build.running ? "Building " : "Built ") + build.label + (build.sub ? " " + build.sub : "") : ""
            function stagedBefore() {             // the stage this draft drew just before the one on screen
                if (!st) return ""
                for (var i = Store.stageLog.length - 1; i >= 0; i--) { var e = Store.stageLog[i]; if (e.draft === st.draft && e.at === st.at - 1) return e.label || "" }
                return "" }
            function stagedAfter() {              // known only when the design being rewritten already lists what follows
                var fs = Store.recipe ? Store.recipe.features : []
                for (var i = 0; st && i < fs.length; i++) if (fs[i].id === st.feature && i + 1 < fs.length) return fs[i + 1].label || ""
                return "" }
            width: Math.round(ws.col ? Math.max(360, Math.min(600, lay.right - lay.left)) : Math.max(360, Store.barW)); x: Math.round(lay.mid - width / 2)
            // the lower third: it stands clear above the bar (116 px in a 900 px window, less in a low one), not on it
            readonly property int clear: Math.round(Math.max(26, Math.min(116, centre.height * 0.129)))
            // where it stands once it has arrived: over the bar as it is during a build (one line, 64 px, 16 from the
            // foot). Not over the bar as it is this instant: the bar grows back when the build is in, a moment before
            // the cue leaves, and the cue (and with it the camera) must not hop up for that moment.
            readonly property real rest: Math.round(centre.height - 16 - 64 - height - clear)
            height: title.height; y: rest + lift
            onXChanged: title.place(); onYChanged: title.place()
            property real lift: shown ? 0 : Theme.shift(14)
            Behavior on lift { NumberAnimation { duration: Theme.move(Theme.panel); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
            opacity: shown ? 1 : 0; visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: cue.shown ? Theme.base : 420 } }
            Cue { id: title; width: parent.width; source: studio
                label: cue.st ? cue.st.label : build.label
                at: cue.st ? cue.st.at : build.at; of: cue.st ? cue.st.of : build.of
                before: cue.st ? cue.stagedBefore() : build.running ? build.before : ""
                after: cue.st ? cue.stagedAfter() : build.running ? build.after : ""
                running: !!cue.st || build.running; pulse: !!cue.st || build.running } }

        // a mesh made editable: how far the CAD is from the mesh at most, counted up as the CAD grows inside the mesh's lines
        Rectangle {
            id: reconCap; objectName: "reconReadout"; z: 6
            readonly property var rc: Store.recon && Store.recon.project === Store.pid ? Store.recon : null
            x: Math.round(Math.max(Theme.edge + 62 + ws.shift, Math.min(parent.width - width - 12, cue.x + (cue.width - width) / 2))); y: cue.y - height - Theme.s4
            width: rcr.implicitWidth + 2 * Theme.s4; height: 32; radius: 16
            color: Theme.glassSolid; border.color: Theme.alpha(Theme.blueprint, 0.35)
            opacity: rc ? 1 : 0; visible: opacity > 0.01
            Behavior on opacity { NumberAnimation { duration: reconCap.rc ? Theme.fast : Theme.cross } }
            Row { id: rcr; x: Theme.s3; anchors.verticalCenter: parent.verticalCenter; spacing: Theme.s2
                Txt { mono: true; kind: "fine"; tone: 2; text: "max deviation"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap }
                Loader { active: !!reconCap.rc; anchors.verticalCenter: parent.verticalCenter       // made anew for each reconstruction, so it counts from zero
                    sourceComponent: Tick { countIn: true; countMs: 1600; decimals: 3; unit: " mm"; font.pixelSize: Theme.tBody; font.weight: Theme.wMedium
                        value: reconCap.rc ? reconCap.rc.mm : 0; color: reconCap.rc && !reconCap.rc.within ? Theme.amber : Theme.ink } }
                Tag { text: "computed"; anchors.verticalCenter: parent.verticalCenter }
                Txt { kind: "fine"; tone: 3; visible: !!reconCap.rc && !reconCap.rc.within; text: "outside the tolerance"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap } } }

        // Compare's wipe: the head left of the line, the other revision right of it. Drag the line; a tag on each side
        // says which revision it is.
        Item {
            id: wipe; objectName: "compareWipe"; z: 3
            property real frac: 0.5                 // across the free area of the view
            readonly property real lo: vp.shownLeft + 24
            readonly property real hi: Math.max(lo + 40, vp.width - vp.shownRight - 24)
            readonly property real at: Math.round(lo + (hi - lo) * frac)
            readonly property bool on: vp.wipeOn && !ws.sim
            visible: on; x: at; y: 40; width: 1; height: Math.min(Store.barY, centre.height) - 60
            Rectangle { x: 0; y: 44; width: 1; height: parent.height - 56; color: Theme.alpha(Theme.blueprint, 0.7) }
            Rectangle { id: grip; anchors.horizontalCenter: parent.left; y: Math.round(parent.height / 2) - 18; width: 14; height: 36; radius: 7
                color: wm.pressed ? Theme.plate4 : Theme.plate3; border.color: Theme.alpha(Theme.blueprint, wm.containsMouse || wm.pressed ? 0.9 : 0.55)
                scale: wm.pressed ? Theme.from(0.96) : 1
                Behavior on scale { Glide { duration: Theme.press } } Behavior on border.color { Tint {} }
                Column { anchors.centerIn: parent; spacing: 3
                    Repeater { model: 3; Rectangle { width: 2; height: 2; radius: 1; color: Theme.blueprint } } } }
            Tag { objectName: "wipeTagHead"; anchors.right: parent.left; anchors.rightMargin: Theme.s2; y: 52; tint: Theme.ink2
                color: Theme.alpha(Theme.plate1, 0.95); border.color: Theme.rule2
                text: Store.project ? F.pad(Store.project.head) + " · head" : "" }
            Tag { objectName: "wipeTagOther"; anchors.left: parent.right; anchors.leftMargin: Theme.s2; y: 52; kind: "draft"
                color: Theme.alpha(Theme.plate1, 0.95); border.color: Theme.alpha(Theme.blueprint, 0.4)
                text: Store.compare ? F.pad(Store.compare.rev) : "" }
            MouseArea { id: wm; x: -22; width: 44; y: 44; height: parent.height - 56; hoverEnabled: true; cursorShape: Qt.SplitHCursor
                preventStealing: true
                onPositionChanged: function (e) { if (pressed) { var p = mapToItem(centre, e.x, e.y).x; wipe.frac = Math.max(0, Math.min(1, (p - wipe.lo) / Math.max(1, wipe.hi - wipe.lo))) } }
                onDoubleClicked: wipe.frac = 0.5 }
            Tip { show: wm.containsMouse && !wm.pressed; text: "Drag to wipe between the two revisions" }
            Connections { target: Store; function onCompareChanged() { if (!Store.compare) wipe.frac = 0.5 } }
        }

        // what is under the pointer: appears at once, no delay
        Rectangle { id: chip; property var feat: null; visible: !!feat && !Store.layers; z: 5
            width: ct.implicitWidth + 20; height: 26; radius: 13; color: Theme.glassSolid; border.color: Theme.rule2
            Row { id: ct; anchors.centerIn: parent; spacing: 6
                Txt { text: chip.feat ? chip.feat.label : ""; font.pixelSize: 12; font.weight: 550 }
                Txt { text: chip.feat ? chip.feat.role : ""; kind: "fine" } } }
        // the map's value under the pointer
        Rectangle { id: vchip; property bool on: false; property real v: 0; z: 5
            readonly property var lg: Store.analysis ? Store.analysis.legend : null
            readonly property string say: !lg ? "" : isNaN(v) ? (lg.none || "") : String(lg.hover || "{v}").replace("{v}", F.fmt(v, Store.analysisMap === "thickness" || Store.analysisMap === "features" ? 2 : 0))
            visible: on && !Store.layers && say !== "" && !!vp.analysis
            width: vt.implicitWidth + 20; height: 26; radius: 13; color: Theme.glassSolid; border.color: Theme.rule2
            Txt { id: vt; anchors.centerIn: parent; mono: true; font.pixelSize: 12; text: vchip.say; wrapMode: Text.NoWrap } }

        // ── the tool dock: four tools that are always there, then the tools of the mode you are in ──
        // (docs/design/directions/i/IA.md, decision 8). The four never move. The mode's group cross-fades in 180 ms and
        // the capsule's foot glides with it; nothing else on the stage is laid out from the dock's height.
        Glass {
            id: rail; objectName: "toolDock"
            source: studio; arrive: 3
            x: Theme.edge + ws.shift; y: ws.headY; z: 6; width: 48; height: railCol.height + 12; radius: 24
            visible: !!Store.view
            readonly property string mode: Store.mode
            // while a build plays the tools step back: the part and its cue have the room
            // (as one picture while it is dimmed, so the filled disc and its icon fade together and not one through the other)
            Item { anchors.fill: parent; opacity: ws.cueOn ? 0.45 : 1; layer.enabled: opacity < 0.999; Behavior on opacity { NumberAnimation { duration: Theme.cross } }
            Column {
                id: railCol; x: 6; y: 6; spacing: 2
                RailBtn { objectName: "railSelect"; icon: "mouse_pointer_2"; label: "Select"; keys: "V"; hint: "Click a feature to edit it. Drag to orbit, shift-drag to pan."
                    active: ws.tool === "select" && !ws.sim && !sketch.busyHere && !Ws.want; onClicked: ws.setTool("select") }
                RailBtn { objectName: "railMeasure"; icon: "pencil_ruler"; label: "Measure"; keys: "M"; hint: "Distances, faces and hole diameters, computed from the part’s surface."
                    active: ws.tool === "measure" && !ws.sim; marked: Store.measures.length > 0; onClicked: ws.setTool("measure") }
                RailBtn { objectName: "railSection"; icon: "scissors"; label: "Section"; keys: "X"; hint: "Cut the part open along X, Y or Z."
                    active: ws.tool === "section" && !ws.sim; marked: !!Store.sectionNow(); onClicked: ws.setTool("section") }
                RailBtn { objectName: "railAnnotate"; icon: "map_pin"; label: "Annotate"; keys: "N"; hint: "Pick faces, edges and points or paint a region; see what the solid says there, keep it with a note, ask the agent about it."
                    active: ws.tool === "annotate" && !ws.sim && !Ws.want; marked: Store.annotations.length > 0 || Store.selItems.length > 0; onClicked: ws.setTool("annotate") }
                // with the ribbon at the head of the stage the dock keeps the four; the mode's tools are in the ribbon
                Item { visible: !ws.ribbonOn; width: 36; height: 9; Rectangle { objectName: "railSep"; x: 8; y: 4; width: 20; height: 1; color: Theme.rule } }
                Item {
                    id: modeBox; objectName: "railModeBox"; width: 36; clip: true; visible: !ws.ribbonOn
                    readonly property Item cur: rail.mode === "prove" ? gCheck : rail.mode === "release" ? gMake : rail.mode === "document" ? gDoc : gDesign
                    height: cur.implicitHeight
                    Behavior on height { NumberAnimation { duration: Theme.move(Theme.base); easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } }
                    // Design: modelling by hand (form/modelling.py): each becomes a feature in the design's code
                    RailGroup { id: gDesign; objectName: "railGroup-shape"; on: modeBox.cur === gDesign
                        RailBtn { objectName: "railSketch"; icon: "pen_tool"; label: "Sketch"; keys: "S"; hint: "Pick a flat face or a plane and draw a profile on it; then extrude, cut or revolve it."
                            enabled: !ws.sim && !Store.hasDraft; active: sketch.busyHere && Ws.want === "sketch"; onClicked: ws.setTool("sketch", "sketch") }
                        RailBtn { objectName: "railExtrude"; icon: "arrow_up"; label: "Extrude"; keys: "Shift+E"; hint: "A profile drawn on a face or a plane, pulled out of it."
                            enabled: !ws.sim && !Store.hasDraft; active: sketch.busyHere && Ws.want === "extrude"; onClicked: ws.setTool("sketch", "extrude") }
                        RailBtn { objectName: "railCut"; icon: "arrow_down_to_line"; label: "Cut"; keys: "Shift+X"; hint: "A profile drawn on a face, cut into the part: a pocket, a slot, a hole of any shape."
                            enabled: !ws.sim && !Store.hasDraft; active: sketch.busyHere && Ws.want === "cut"; onClicked: ws.setTool("sketch", "cut") }
                        RailBtn { objectName: "railRevolve"; icon: "rotate_3d"; label: "Revolve"; keys: "Shift+R"; hint: "A profile turned about one of its lines."
                            enabled: !ws.sim && !Store.hasDraft; active: sketch.busyHere && Ws.want === "revolve"; onClicked: ws.setTool("sketch", "revolve") }
                        Item { width: 36; height: 9; Rectangle { x: 8; y: 4; width: 20; height: 1; color: Theme.rule } }
                        RailBtn { objectName: "railRound"; icon: "radius"; label: "Fillet"; keys: "Shift+F"; hint: "Pick the edges to round."
                            enabled: !ws.sim; active: ws.tool === "annotate" && Ws.want === "fillet"; onClicked: ws.setTool("annotate", "fillet") }
                        RailBtn { objectName: "railChamfer"; icon: "triangle"; label: "Chamfer"; keys: "Shift+C"; hint: "Pick the edges to bevel."
                            enabled: !ws.sim; active: ws.tool === "annotate" && Ws.want === "chamfer"; onClicked: ws.setTool("annotate", "chamfer") }
                        RailBtn { objectName: "railHole"; icon: "circle_dot"; label: "Hole"; keys: "Shift+H"; hint: "Pick a flat face: a hole there, to a standard size."
                            enabled: !ws.sim; active: ws.tool === "annotate" && Ws.want === "hole"; onClicked: ws.setTool("annotate", "hole") }
                        RailBtn { objectName: "railPattern"; icon: "layout_grid"; label: "Pattern"; keys: "Shift+P"; hint: "Repeat a feature along a line or about an axis. Select the feature first, on the part or in the tree."
                            enabled: !ws.sim; active: Ws.want === "pattern"; onClicked: ws.setTool("select", "pattern") }
                        RailBtn { objectName: "railShell"; icon: "box"; label: "Shell"; keys: "Shift+S"; hint: "Pick a flat face: the part hollowed out and open there."
                            enabled: !ws.sim; active: ws.tool === "annotate" && Ws.want === "shell"; onClicked: ws.setTool("annotate", "shell") }
                        RailBtn { objectName: "railPart"; icon: "wrench"; label: "Part here…"; keys: "Shift+B"; hint: "Pick a hole or a face: a screw, insert, bearing or other bought part on it, its hole cut and its fit checked."
                            enabled: !ws.sim; active: ws.tool === "annotate" && Ws.want === "part"; onClicked: ws.setTool("annotate", "part") }
                    }
                    // Check: what the solid says
                    RailGroup { id: gCheck; objectName: "railGroup-prove"; on: modeBox.cur === gCheck
                        RailBtn { objectName: "railAnalyze"; icon: "scan_line"; label: "Analyze"; keys: "A"; hint: "Colour the part by wall thickness, overhang, section area or small features."
                            active: ws.tool === "analyze" && !ws.sim; marked: !!Store.analysisMap; onClicked: ws.setTool("analyze") }
                        RailBtn { objectName: "railMass"; icon: "weight"; toggle: true; label: Store.massOn ? "Hide the centre of mass" : "Centre of mass"; keys: "C"
                            hint: "The centre of mass and the principal axes, with the mass and inertia (computed on the B-rep)."
                            active: Store.massOn; enabled: !ws.sim; onClicked: Store.massOn = !Store.massOn }
                        RailBtn { objectName: "railAssembly"; icon: "boxes"; label: "Assembly"; keys: "E"; hint: "Assembled, exploded or as printed. Move the joints."
                            visible: !!Store.assembly
                            active: ws.tool === "assembly" && !ws.sim; marked: Store.asmMode !== "print"; onClicked: ws.setTool("assembly") }
                        RailBtn { objectName: "railHistory"; icon: "history"; label: "History"; keys: "T"; hint: "Scrub through the revisions. Looking changes nothing."
                            active: ws.tool === "history" && !ws.sim; marked: !!Store.scrub; onClicked: ws.setTool("history") }
                        RailBtn { icon: "box"; toggle: true; label: Store.companions ? "Hide what the part holds" : "Show what the part holds"; hint: "The object or reference part, drawn in blueprint."
                            visible: !!(Store.shown && Store.shown.companions && Store.shown.companions.length)
                            active: vp.showCompanions; enabled: !ws.sim; onClicked: Store.toggleCompanions() }
                    }
                    // Make: the routes that have something to show on the stage
                    RailGroup { id: gMake; objectName: "railGroup-release"; on: modeBox.cur === gMake
                        RailBtn { objectName: "railSimulate"; icon: "layers"; label: "Simulate the print"; hint: ws.d && ws.d.slice ? "Play the slicer’s toolpaths. Simulated, not a print." : "Needs a current slice of this revision."
                            enabled: !!ws.d && !!ws.d.slice; active: ws.sim
                            onClicked: { if (ws.sim) Store.showLayers(false); else Store.simulate({ at: 0, play: true }) } }
                        RailBtn { objectName: "railPlates"; icon: "grid_3x3"; label: "Print layout"; hint: "The parts as they lie on the plates."
                            visible: !!Store.assembly && Store.printUi
                            active: Store.asmMode === "print" && ws.tool === "assembly"; onClicked: { if (ws.tool !== "assembly") ws.setTool("assembly"); Store.setAsmMode("print") } }
                        RailBtn { objectName: "railGame"; icon: "gamepad_2"; label: "Game asset"; hint: Store.hasDraft ? "Commit or discard the draft first." : "LODs at triangle budgets, UVs, baked maps and collision, for Godot, Unity or Unreal (built in Blender)."
                            visible: Store.gameDesign; enabled: !Store.hasDraft; onClicked: Store.openSheet("game") }
                        RailBtn { icon: "camera"; label: "Photo render"; hint: Store.hasDraft ? "Commit or discard the draft first." : "Render the current revision in Blender (an illustration)."
                            enabled: !Store.hasDraft; onClicked: Store.openSheet("render") }
                    }
                    // Document: how the part is looked at and dimensioned
                    RailGroup { id: gDoc; objectName: "railGroup-document"; on: modeBox.cur === gDoc
                        RailBtn { objectName: "railViews"; icon: "cuboid"; label: "Views"; keys: "W"; hint: "Front, side, top or the three-quarter view."
                            active: ws.tool === "views" && !ws.sim; enabled: !ws.sim; onClicked: ws.setTool("views") }
                        RailBtn { objectName: "railDims"; icon: "ruler"; toggle: true; label: Store.dims ? "Hide overall dimensions" : "Show overall dimensions"; active: Store.dims; enabled: !ws.sim; onClicked: Store.toggleDims() }
                        RailBtn { icon: "maximize_2"; label: Store.feature ? "Frame the selection" : "Frame the part"; keys: "F"; enabled: !ws.sim
                            onClicked: Store.frameSelection() }
                        RailBtn { icon: "camera"; label: "Photo render"; hint: Store.hasDraft ? "Commit or discard the draft first." : "Render the current revision in Blender (an illustration)."
                            enabled: !Store.hasDraft; onClicked: Store.openSheet("render") }
                    }
                }
                // the ribbon folded away: one button brings it back
                Item { visible: !ws.ribbonOn; width: 36; height: 9; Rectangle { x: 8; y: 4; width: 20; height: 1; color: Theme.rule } }
                RailBtn { objectName: "railRibbon"; visible: !ws.ribbonOn; icon: "panel_top"; label: "Show the tools"
                    hint: "The mode’s tools, labelled and grouped, at the head of the stage."; onClicked: ws.setRibbon(true) }
            }
            }
        }

        // ── the ribbon: the mode's tools with their labels, in groups, at the head of the stage ──
        // From the dock's left edge to the view cube; nothing on the stage is laid out under it but the head.
        ToolRibbon {
            id: ribbon; source: studio; arrive: 3; z: 6
            visible: ws.ribbonOn
            x: Theme.edge + ws.shift; y: Theme.paneTop
            maxWidth: Math.max(200, (cube.visible ? cube.x : ws.paneX) - Theme.gap - x)
            groups: ws.ribbonGroups; host: ws; modeKey: Store.mode
            onHideAsked: ws.setRibbon(false)
            opacity: ws.cueOn ? 0.45 : 1; Behavior on opacity { NumberAnimation { duration: Theme.cross } }
        }

        // ── options of the active tool: one capsule at the head of the stage, always in the same place ──
        Item {
            id: opts
            x: Theme.edge + 60 + ws.shift; y: ws.headY + 2; z: 5; visible: !ws.sim && !!Store.view && !sketch.busyHere
            readonly property real room: Math.max(160, capsule.maxWidth - capsule.lead - 6)
            readonly property bool any: ws.tool === "annotate" || ws.tool === "measure" || ws.tool === "section" || ws.tool === "analyze" || ws.tool === "views"
                                        || (ws.tool === "assembly" && !!Store.assembly) || Ws.want === "pattern"
            height: any ? capsule.height : 0
            ToolCapsule {
                id: capsule; objectName: "toolCapsule"; source: studio; visible: opts.any
                maxWidth: Math.max(200, ws.paneX - opts.x - Theme.gap - (cube.visible ? cube.width + Theme.gap : 0))
                title: Ws.want === "pattern" ? "Pattern" : ws.tool === "annotate" ? ({ fillet: "Fillet", chamfer: "Chamfer", hole: "Hole", shell: "Shell", part: "Part here", text: "Text" }[Ws.want] || "Annotate")
                     : ws.tool === "measure" ? "Measure" : ws.tool === "section" ? "Section" : ws.tool === "analyze" ? "Analyze" : ws.tool === "assembly" ? "Assembly" : ws.tool === "views" ? "Views" : ""
            HudBar { id: viewsBar; objectName: "viewsBar"; shown: ws.tool === "views"; maxWidth: opts.room; cut: true
                Seg { height: 28; model: [{ value: "front", text: "Front" }, { value: "side", text: "Side" }, { value: "top", text: "Top" }, { value: "iso", text: "Three-quarter" }]
                    value: Store.viewName; onPicked: function (v) { Store.setView(v) } }
            }
            HudBar { id: patternBar; objectName: "patternBar"; shown: Ws.want === "pattern" && ws.tool === "select"; maxWidth: opts.room; cut: true
                Txt { height: 28; verticalAlignment: Text.AlignVCenter; font.pixelSize: 13; tone: 2; wrapMode: Text.NoWrap
                    text: Store.feature ? "Set it under the feature’s line, in the tree" : "Select the feature to repeat, on the part or in the tree" }
            }
            HudBar { id: wantBar; objectName: "wantBar"; shown: ws.tool === "annotate" && !!Ws.want; maxWidth: opts.room; cut: true
                Txt { height: 28; verticalAlignment: Text.AlignVCenter; font.pixelSize: 13; wrapMode: Text.NoWrap
                    color: Store.selSay ? Theme.strong(Theme.amber) : Theme.ink2
                    text: Store.selSay ? Store.selSay : Store.selBusy > 0 ? "Reading the solid…"
                        : Ws.want === "fillet" || Ws.want === "chamfer" ? (Store.selItems.length ? F.plural(Store.selItems.length, "edge") + " picked · Shift-click adds · set it in the pane" : "Click an edge · Shift-click adds")
                        : Ws.want === "part" ? (Store.selItems.length ? "Choose the part in the sheet" : "Click a hole or a face")
                        : Store.selItems.length ? "Set it in the pane on the right" : "Click a flat face" }
                Btn { small: true; height: 28; text: "Clear"; visible: Store.selItems.length > 0; onClicked: Store.selClear() }
            }
            HudBar { id: annotateBar; objectName: "annotateBar"; shown: ws.tool === "annotate" && !Ws.want; maxWidth: opts.room; cut: true
                Seg { height: 28; model: [{ value: "face", text: "Face", tip: "G" }, { value: "edge", text: "Edge", tip: "R" }, { value: "point", text: "Point", tip: "P" },
                              { value: "brush", text: "Brush", tip: "B: paint a region on the surface" }, { value: "lasso", text: "Lasso", tip: "L: draw around what you see" }]
                    value: Store.selMode; onPicked: function (v) { Store.selMode = v } }
                HudSlider { visible: Store.selMode === "brush"; label: "Size"; unit: " mm"; decimals: 1; from: 0.5; to: 15; step: 0.5
                    value: Store.brushMm; onMoved: function (v) { Store.brushMm = v } }
                Rectangle { objectName: "annotateHint"; height: 28; width: Math.min(sh.implicitWidth + 20 + (sspin.visible ? 20 : 0), opts.room); radius: Theme.rSm
                    color: Store.selSay ? Theme.alpha(Theme.amber, 0.12) : Theme.alpha(Theme.plate1, 0.9); border.color: Store.selSay ? Theme.alpha(Theme.amber, 0.35) : Theme.rule
                    Behavior on color { Tint {} }
                    Spinner { id: sspin; x: 9; anchors.verticalCenter: parent.verticalCenter; size: 12; visible: Store.selBusy > 0; color: Theme.annotate }
                    Txt { id: sh; x: sspin.visible ? 28 : 10; width: parent.width - x - 10; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        color: Store.selSay ? Theme.strong(Theme.amber) : Theme.ink2
                        text: Store.selSay ? Store.selSay : Store.selBusy > 0 ? "Analysing on the solid…"
                            : Store.selMode === "brush" ? (ws.compact ? "Drag to paint" : "Drag to paint a region · Alt-drag orbits · Shift adds")
                            : Store.selMode === "lasso" ? (ws.compact ? "Drag around it" : "Draw around what you see · Alt-drag orbits · Shift adds")
                            : ws.compact ? "Click to pick" : "Click to pick a " + Store.selMode + " · Shift-click adds" } }
                Btn { small: true; height: 28; text: "Clear"; visible: Store.selItems.length > 0; onClicked: Store.selClear() }
            }

            HudBar { id: measureBar; objectName: "measureBar"; shown: ws.tool === "measure"; maxWidth: opts.room; cut: true
                Seg { height: 28; model: [{ value: "distance", text: "Distance" }, { value: "face", text: "Face" }, { value: "diameter", text: "Diameter" }]
                    value: Store.measureKind
                    onPicked: function (v) { Store.measureKind = v; Store.measureFrom = null } }
                Rectangle { objectName: "measureHint"; height: 28; width: Math.min(mh.implicitWidth + 20 + (mspin.visible ? 20 : 0), opts.room); radius: Theme.rSm
                    color: Store.measureSay ? Theme.alpha(Theme.amber, 0.12) : Theme.alpha(Theme.plate1, 0.9); border.color: Store.measureSay ? Theme.alpha(Theme.amber, 0.35) : Theme.rule
                    Behavior on color { Tint {} }
                    Spinner { id: mspin; x: 9; anchors.verticalCenter: parent.verticalCenter; size: 12; visible: Store.measureBusy > 0 }
                    Txt { id: mh; x: mspin.visible ? 28 : 10; width: parent.width - x - 10; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 2; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        color: Store.measureSay ? Theme.strong(Theme.amber) : Theme.ink2
                        text: Store.measureSay ? Store.measureSay : Store.measureBusy > 0 ? "Measuring on the solid…"
                            : Store.measureKind === "distance" ? (Store.measureFrom ? "Click the second point" : ws.compact ? "Click two points; they snap" : "Click two points. They snap to corners, midpoints and centres")
                            : Store.measureKind === "face" ? (ws.compact ? "Click a face: area and tilt" : "Click a face for its area and its tilt to the bed")
                            : ws.compact ? "Click a hole or round boss" : "Click the wall or rim of a hole or round boss" }
                    MouseArea { id: mhm; anchors.fill: parent; hoverEnabled: true }
                    Tip { show: mhm.containsMouse; text: "Values are computed from the part’s surface, tessellated at 0.05 mm; a hole diameter is exact when it comes from the CAD solid. Points snap to corners, edge midpoints and face centres when close." } }
                Btn { small: true; height: 28; text: "Clear"; visible: Store.measures.length > 0 || !!Store.measureFrom; onClicked: Store.clearMeasures() }
            }
            HudBar { id: sectionBar; objectName: "sectionBar"; shown: ws.tool === "section"; maxWidth: opts.room; cut: true
                readonly property var now: Store.sectionNow()
                Seg { height: 28; model: [{ value: "x", text: "X" }, { value: "y", text: "Y" }, { value: "z", text: "Z" }]
                    value: sectionBar.now ? sectionBar.now.axis : ""
                    onPicked: function (v) { Store.setSection(v, sectionBar.now && sectionBar.now.axis === v ? sectionBar.now.t : 0.5) } }
                HudSlider { label: "Position"; from: 0.02; to: 0.98; step: 0.01; percent: true; visible: !!sectionBar.now
                    value: sectionBar.now ? sectionBar.now.t : 0.5
                    onMoved: function (v) { Store.setSection(sectionBar.now ? sectionBar.now.axis : "y", v) } }
                Btn { small: true; height: 28; text: "Remove cut"; visible: !!sectionBar.now; onClicked: Store.setSection("", 0.5) }
            }
            HudBar { id: analyzeBar; objectName: "analyzeBar"; shown: ws.tool === "analyze"; maxWidth: opts.room; cut: true
                Seg { height: 28; visible: !ws.compact; model: Store.analysisMaps.slice(1); value: Store.analysisMap
                    onPicked: function (v) { Store.setAnalysis(v === Store.analysisMap ? "" : v) } }
                Pick { visible: ws.compact; width: 150; height: 28; model: Store.analysisMaps; value: Store.analysisMap; onPicked: function (v) { Store.setAnalysis(v) } }
                Btn { small: true; height: 28; text: "Clear map"; visible: !!Store.analysisMap && !ws.compact; onClicked: Store.setAnalysis("") }
                Btn { objectName: "massToggle"; small: true; height: 28; icon: "weight"; text: ws.compact ? "" : "Centre of mass"; active: Store.massOn
                    tip: (Store.massOn ? "Hide" : "Show") + " the centre of mass and the principal axes, with the mass and inertia (computed on the B-rep)"
                    onClicked: Store.massOn = !Store.massOn }
            }
            HudBar { id: asmBar; objectName: "asmBar"; shown: ws.tool === "assembly" && !!Store.assembly; maxWidth: opts.room; cut: true
                Seg { height: 28; visible: !ws.compact; model: ws.asmModes
                    value: Store.asmMode; onPicked: function (v) { Store.setAsmMode(v) } }
                Pick { visible: ws.compact; width: 150; height: 28; value: Store.asmMode; onPicked: function (v) { Store.setAsmMode(v) }
                    model: ws.asmModes.filter(function (m) { return !m.off }) }
                Rectangle { objectName: "asmDerivedNote"; visible: ws.asmDerived; height: 28; width: Math.min(an.implicitWidth + 20, opts.room); radius: Theme.rSm
                    color: Theme.alpha(Theme.plate1, 0.9); border.color: Theme.rule
                    Txt { id: an; x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 3; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        text: ws.compact ? "Placement not declared" : "Not assembled: the design does not say where each part goes" } }
                Btn { visible: ws.asmDerived; small: true; height: 28; icon: "sparkles"; text: ws.compact ? "Ask the agent" : "Ask the agent to add it"
                    tip: "Puts a request in the conversation for you to send: describe how the parts go together in the design."
                    onClicked: ws.askAssembly() }
                HudSlider { visible: Store.asmMode === "exploded"; label: "Spread"; from: 0; to: 1.6; step: 0.05; base: 1; percent: true
                    value: Store.explode; onMoved: function (v) { Store.setExplode(v) } }
                Repeater { model: Store.assembly && Store.asmMode !== "print" ? Store.assembly.joints.filter(function (j) { return j.kind !== "fixed" }) : []
                    HudSlider { required property var modelData
                        label: modelData.label; unit: modelData.kind === "slide" ? " mm" : "°"
                        objectName: "jointSlider_" + modelData.id
                        from: modelData.range[0]; to: modelData.range[1]; step: modelData.step > 0 ? modelData.step : 1; base: 0
                        value: Store.pose[modelData.id] || 0
                        onMoved: function (v) { Store.setPose(modelData.id, v) } } }
            }
            }
        }

        // ── top right of the stage: where you look from (the view cube) and what the part stands on (the chip) ──
        ViewCube { id: cube; source: studio; arrive: 4; z: 5
            visible: !ws.sim && !!Store.view && lay.freeR - lay.freeL > 300
            x: Math.round(ws.paneX - Theme.gap - width); y: Theme.paneTop
            opacity: ws.cueOn ? 0.45 : 1; Behavior on opacity { NumberAnimation { duration: Theme.cross } }
            onPicked: function (name) { Store.setView(name) } }
        ShadeChip { id: shade; source: studio; arrive: 4; z: 5; visible: cube.visible
            x: Math.round(cube.x + (cube.width - width) / 2); y: cube.y + cube.height + 8 }

        // ── under the part: the legend of the result shown on it ──
        ResultStrip { id: strip; source: studio; z: 5
            on: !!Store.analysisMap && !ws.mapBlocked && !ws.sim && !!Store.view
            map: Store.analysis; busy: Store.analysisBusy; pending: Store.analysisLabel(Store.analysisMap); check: Store.analysis ? Store.analysisCheck() : null
            width: Math.round(Math.max(300, Math.min(616, lay.freeR - lay.freeL - 4)))
            x: Math.round(Math.max(lay.freeL, Math.min(lay.freeR - width, (ws.col ? (lay.freeL + lay.freeR) / 2 : lay.mid) - width / 2)))
            y: Math.round((ws.col ? centre.height - Theme.edge : Math.min(centre.height - Theme.edge, Store.barY - Theme.gap)) - height) }

        // the same strip for a result of the later engines (strength, manufacturability, CNC, flat pattern, motion)
        LegendStrip { id: rstrip; source: studio; z: 5
            width: strip.width; x: strip.x
            y: Math.round((ws.col ? centre.height - Theme.edge : Math.min(centre.height - Theme.edge, Store.barY - Theme.gap)) - height) }
        // Document: the drawing's sheet takes the stage
        Loader { id: sheetPane; z: 4; active: Results.kind === "drawing" && Results.on && !ws.sim
            x: Math.round(lay.freeL - 28); y: ws.headY; width: Math.round(lay.freeR - x); height: Math.round(Math.min(centre.height - Theme.edge, Store.barY - Theme.gap) - y)
            sourceComponent: DrawingPane { } }

        // an agent is working on another design than this one: named, never jumped to once you are working here
        Rectangle {
            id: elsewhere; objectName: "agentElsewhere"; z: 6
            x: Math.round(lay.mid - width / 2); y: ws.headY + 4
            visible: !!Store.agentElsewhere && !ws.sim
            width: er.implicitWidth + 24; height: 34; radius: 17; color: Theme.glassSolid; border.color: Theme.rule2
            Row { id: er; x: 14; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                Rectangle { width: 6; height: 6; radius: 3; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter
                    SequentialAnimation on opacity { running: elsewhere.visible && !Theme.reduced; loops: Animation.Infinite
                        NumberAnimation { to: 0.35; duration: 700 } NumberAnimation { to: 1; duration: 700 } } }
                Txt { anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; font.pixelSize: 12
                    width: Math.min(implicitWidth, centre.width - 220); elide: Text.ElideRight
                    text: Store.agentElsewhere ? Store.agentElsewhere.by + " is working on " + Store.agentElsewhere.name
                                                 + (Store.agentElsewhere.title && Store.agentElsewhere.name.indexOf("“") !== 0 ? " in “" + Store.agentElsewhere.title + "”" : "") : "" }
                Btn { objectName: "agentElsewhereShow"; small: true; kind: "quiet"; text: "Show"; anchors.verticalCenter: parent.verticalCenter; onClicked: Store.showElsewhere() }
                Btn { small: true; kind: "quiet"; icon: "x"; tip: "Stay here"; anchors.verticalCenter: parent.verticalCenter; onClicked: Store.agentElsewhere = null } } }

        // ── the dock: legends, measurements, the selection and refinement. Its slot is in the right column, between
        //    the stage's pane and the pipeline: nothing of it stands over the stage. The pane above gives it the room
        //    (insp.room_); a panel takes what it needs, up to 300 px or 40 % of the column, and scrolls beyond that. ──
        Column {
            id: dock
            x: insp.x; width: insp.width; y: ws.colFoot - height; z: 7; spacing: 8; visible: !ws.sim && !ws.panesOff
            readonly property bool any: showMap || showMeasures || showSel || showRefine
            // what the column keeps for it above the pipeline (its own height, each panel at most `room`), gap included
            readonly property real reserve: any && height > 0 ? Math.round(height + Theme.gap) : 0
            readonly property bool folded: Ws.dockTouched && Ws.dockCollapsed
            readonly property bool showMap: false      // the map's legend is the strip under the part (ResultStrip), not a panel here
            readonly property bool showMeasures: Store.measures.length > 0
            readonly property bool showSel: ws.tool === "annotate" || Store.selItems.length > 0 || !!Store.annFocus
            // refinement: while it runs, and while the head carries refine changes (or the last run failed)
            readonly property bool showRefine: !!Store.refine && !Store.scrub && (Store.refine.state === "running"
                || (Store.refine.changes || []).length > 0 || Store.refine.state === "failed")
            readonly property bool open: (showMap || showMeasures || showSel || showRefine) && !folded
            readonly property real room: Math.max(120, Math.round(Math.min(300, (ws.colFoot - Theme.paneTop) * 0.4)))
            function flip() { var now = folded; Ws.dockTouched = true; Ws.dockCollapsed = !now }
            SelectionPanel { width: dock.width; visible: dock.showSel
                collapsed: dock.folded || ((dock.showMap || dock.showMeasures) && ws.tool !== "annotate" && !Store.annFocus)
                maxHeight: dock.room - (dock.showMap ? 44 : 0) - (dock.showMeasures ? 44 : 0); onToggled: dock.flip() }
            MeasurePanel { objectName: "measurePanel"; width: dock.width; visible: dock.showMeasures
                collapsed: dock.folded || (dock.showMap && ws.tool !== "measure")
                maxHeight: dock.room - (dock.showMap ? 44 : 0); onToggled: dock.flip() }
            RefinePanel { width: dock.width; visible: opacity > 0.01; opacity: dock.showRefine ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Motion.ui; easing.type: Easing.OutCubic } }
                // open in Design, where its changes are made; in the other stages it is its header, and the stage's pane
                // keeps the column. A click on its header always answers: it opens wherever it is (the pane above
                // gives it the room, insp.room_) and folds again, whatever the stage and whatever else the dock holds.
                readonly property bool byStage: dock.folded || dock.showMap || dock.showMeasures || dock.showSel || Store.stage !== "shape"
                collapsed: Ws.refineWant < 0 ? byStage : Ws.refineWant === 0
                maxHeight: dock.room - (dock.showMap ? 44 : 0) - (dock.showMeasures ? 44 : 0) - (dock.showSel ? 44 : 0)
                onToggled: Ws.refineWant = collapsed ? 1 : 0 }
        }

        // ── bottom left: what you are looking at ─────────────
        Column {
            id: status
            // above the view buttons; in a narrow window the bar reaches over here, so it stands above the bar instead
            // (there it starts right of the tool dock, which reaches down that far, not under it)
            readonly property bool overBar: !ws.col && ws.compact && width + Theme.edge + 14 + 8 > Store.barX
            x: overBar && Store.barY - 10 - height < rail.y + rail.height + 8 ? lay.freeL + 4 : Theme.edge + 14 + ws.shift
            y: Math.round(Math.min(status.foot, overBar ? Store.barY - 10 : centre.height) - height); z: 4;
            readonly property real foot: centre.height - Theme.edge - 6      // the foot of the stage: the size line stands on it
            // where it stands once no build plays (the bar is then taller): the camera frames a build over this
            readonly property real restY: Math.round(Math.min(status.foot, overBar ? Store.barRestY - 10 : centre.height) - height)
            spacing: 8; visible: !ws.sim && !!Store.shown
            // notices: the picture is not simply "the head revision"
            Rectangle { visible: !!Store.scrub; width: sn.implicitWidth + 16; height: 28; radius: Theme.rSm
                color: Theme.alpha(Theme.plate1, 0.95); border.color: Theme.alpha(Theme.blueprint, 0.4)
                Row { id: sn; x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                    Txt { mono: true; font.pixelSize: 12; color: Theme.blueprint; text: Store.scrub ? F.pad(Store.scrub.rev) : ""; anchors.verticalCenter: parent.verticalCenter }
                    Txt { font.pixelSize: 12; tone: 2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap
                        text: Store.scrub && Store.scrub.upto ? "Rolled back to " + (Store.featureById(Store.scrub.upto) || { label: Store.scrub.upto }).label + " · viewing only"
                              : Store.morphing ? "Playing the history · head is " + (Store.project ? F.pad(Store.project.head) : "") : "Viewing only · head is still " + (Store.project ? F.pad(Store.project.head) : "") }
                    Btn { objectName: "backToHead"; small: true; kind: "quiet"; text: Store.scrub && Store.scrub.upto ? "Show every feature" : "Back to head"; anchors.verticalCenter: parent.verticalCenter; onClicked: Store.endScrub() } } }
            Rectangle { visible: Store.hasDraft && !!Store.preview && !Store.scrub; width: b1.implicitWidth + 20; height: 26; radius: Theme.rSm
                color: Theme.alpha(Theme.blueprint, 0.14); border.color: Theme.alpha(Theme.blueprint, 0.3)
                Txt { id: b1; anchors.centerIn: parent; font.pixelSize: 12; color: Theme.strong(Theme.blueprint); wrapMode: Text.NoWrap
                    text: "Draft, not committed · blue lines are " + (Store.project ? F.pad(Store.project.head) : "") } }
            Rectangle { objectName: "compareChip"; visible: !!Store.compare; width: b2.implicitWidth + 20; height: 26; radius: Theme.rSm
                color: Theme.alpha(Theme.blueprint, 0.14); border.color: Theme.alpha(Theme.blueprint, 0.3)
                Row { id: b2; x: 10; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                    Txt { font.pixelSize: 12; color: Theme.strong(Theme.blueprint); wrapMode: Text.NoWrap; anchors.verticalCenter: parent.verticalCenter
                        text: !Store.compare || !Store.project ? ""
                            : vp.wipeOn ? "Comparing · " + F.pad(Store.project.head) + " (head) left, " + F.pad(Store.compare.rev) + " right · blue lines are " + F.pad(Store.compare.rev)
                            : "Comparing · solid is " + F.pad(Store.project.head) + " (head), blue lines are " + F.pad(Store.compare.rev) }
                    Btn { objectName: "compareDone"; small: true; kind: "quiet"; text: "Done"; tip: "Stop comparing (Esc)"
                        anchors.verticalCenter: parent.verticalCenter; onClicked: Store.endCompare() } } }
            Rectangle { visible: ws.mapBlocked; width: Math.min(mb.implicitWidth + 20, centre.width - 32); height: 26; radius: Theme.rSm
                color: Theme.alpha(Theme.amber, 0.12); border.color: Theme.alpha(Theme.amber, 0.3)
                Txt { id: mb; x: 10; width: parent.width - 20; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; color: Theme.strong(Theme.amber); wrapMode: Text.NoWrap; elide: Text.ElideRight
                    text: "The map describes " + (Store.project ? F.pad(Store.project.head) : "the head") + ". " + (Store.hasDraft ? "Commit or discard the draft to see it." : "Stop comparing to see it.") } }
            // the size line: W × D × H and the volume of what is on screen, and under it which arrangement that is.
            // While an agent's build streams in it is the size of what is built so far (the stage's own bounds, the
            // same numbers as the dimension lines on the part), and there is no volume yet.
            Column { id: ro; objectName: "readout"; spacing: 3; visible: !strip.on && !rstrip.on      // a result's legend takes the foot of the stage
                readonly property bool asm: !!Store.assembly && Store.asmMode !== "print"
                readonly property bool mass: !sofar && Store.massShown && !!Store.mass.total
                // a streamed stage carries its own bounds; a build-up playing here is measured by the view (the bounds of
                // what is drawn so far, which the dimension lines on the part use too)
                readonly property bool staged: !!vp.model && !!vp.model.stage && !!vp.model.bbox
                readonly property bool sofar: staged || (vp.revealing && build.running)
                readonly property var bb: staged ? vp.model.bbox : sofar ? [[vp.dimLo.x, vp.dimLo.y, vp.dimLo.z], [vp.dimHi.x, vp.dimHi.y, vp.dimHi.z]]
                                        : asm ? Store.assembly.bbox : (Store.shown ? Store.shown.bbox : null)
                Row { spacing: 7; height: 16
                    Tick { font.pixelSize: 12; tone: 1; value: ro.bb ? ro.bb[1][0] - ro.bb[0][0] : 0; anchors.verticalCenter: parent.verticalCenter }
                    Txt { text: "×"; tone: 1; mono: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                    Tick { font.pixelSize: 12; tone: 1; value: ro.bb ? ro.bb[1][1] - ro.bb[0][1] : 0; anchors.verticalCenter: parent.verticalCenter }
                    Txt { text: "×"; tone: 1; mono: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                    Tick { font.pixelSize: 12; tone: 1; value: ro.bb ? ro.bb[1][2] - ro.bb[0][2] : 0; unit: " mm"; anchors.verticalCenter: parent.verticalCenter }
                    Txt { visible: !ro.sofar; text: "·"; tone: 3; leftPadding: 4; rightPadding: 4; anchors.verticalCenter: parent.verticalCenter }
                    Tick { visible: !ro.sofar; font.pixelSize: 12; tone: 1; value: Store.shown ? Store.shown.volume_mm3 / 1000 : 0; unit: " cm³"; anchors.verticalCenter: parent.verticalCenter }
                    // the head's mass in its material (form/massprops.py): pressed, the centre of mass and the readout
                    Txt { visible: ro.mass; text: "·"; tone: 3; leftPadding: 4; rightPadding: 4; anchors.verticalCenter: parent.verticalCenter }
                    Tick { objectName: "readoutMass"; visible: ro.mass; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                        color: Store.massOn || rmm.containsMouse ? Theme.datum : Theme.ink
                        value: ro.mass ? Store.mass.total.mass_g : 0; decimals: ro.mass && Store.mass.total.mass_g < 100 ? 1 : 0; unit: " g"
                        MouseArea { id: rmm; anchors.fill: parent; anchors.margins: -4; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                            onClicked: Store.massOn = !Store.massOn }
                        Tip { show: rmm.containsMouse; text: (Store.massOn ? "Hide" : "Show") + " the centre of mass and inertia. " + (Store.mass ? Store.mass.headline : "") } } }
                Txt { objectName: "readoutNote"; font.pixelSize: 12; tone: 3; wrapMode: Text.NoWrap; visible: text !== ""
                    text: ro.sofar ? "as modelled so far"
                        : !Store.assembly ? (Store.plateWanted ? "on a " + ws.bed + " mm plate" : "")
                        : Store.asmMode === "assembled" ? "assembled" : Store.asmMode === "exploded" ? (Store.assembly.derived ? "as modelled, shown pulled apart" : "assembled size, shown exploded")
                        : (Store.assembly.derived || !Store.printUi ? "as modelled, " : "as printed, ") + F.plural(Store.assembly.parts.length, "part") } }
        }

        // mass and inertia, over the size line while the centre of mass is shown (the grams on the size line toggle it);
        // right of the tool dock when the dock reaches down that far
        MassReadout {
            visible: Store.massOn && Store.massShown && !ws.sim; source: studio; z: 4
            y: status.y - height - 40                        // over the floor scale, which stands just above the size line
            x: y < rail.y + rail.height + 8 ? rail.x + rail.width + 12 : status.x
        }

        // ── top centre, under the stages: the revisions, while History is the tool ──
        Glass {
            id: history; objectName: "historyCapsule"
            source: studio; z: 7
            visible: Store.timelineOpen && !!Store.project && !ws.sim
            width: Math.max(320, Math.min(760, ws.paneX - Theme.edge - 60 - ws.shift - 24)); height: 48; radius: 24
            x: Math.round(Math.max(Theme.edge + 60 + ws.shift, Math.min(lay.mid - width / 2, ws.paneX - 12 - width))); y: ws.headY + 2 + (opts.height > 0 ? opts.height + 8 : 0)
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: function (w) { w.accepted = true } }
            Tools.Timeline { id: tline; x: 8; width: parent.width - 16; height: 40; anchors.verticalCenter: parent.verticalCenter }
        }
        Tools.ContextMenu { anchors.fill: parent; z: 8 }
    }

    // ── the Overview of the design, over the stage and the pane; the conversation stays ──
    Overview {
        id: overview; source: studio; z: 9; on: Store.overview && !!Store.data
        x: Theme.edge + ws.shift; y: Theme.paneTop
        width: ws.width - Theme.edge - x; height: Math.round((ws.col ? ws.height - Theme.edge : Math.min(ws.height - Theme.edge, Store.barY - Theme.gap)) - y)
    }

    // ── the Bench, open: all four chapters at once, over the stage and the pane; the conversation stays ──
    BenchSheet {
        id: benchSheet; source: studio; z: 9; on: Store.benchOpen && !!Store.data
        x: overview.x; y: overview.y; width: overview.width; height: overview.height; from: insp.x - x
    }

    // the panes folded (a narrow window with the conversation open): one button where they stood
    Glass {
        id: panesBtn; objectName: "panesButton"; source: studio; z: 7
        visible: ws.panesOff; x: ws.width - Theme.edge - width; y: Theme.paneTop; width: 44; height: 44; radius: 22
        Rectangle { anchors.fill: parent; anchors.margins: 4; radius: height / 2; color: pbm.pressed ? Theme.washPress : pbm.containsMouse ? Theme.washHover : "transparent"; Behavior on color { Tint {} } }
        Icon { anchors.centerIn: parent; name: "panel_right"; size: 16; color: pbm.containsMouse ? Theme.ink : Theme.ink2 }
        MouseArea { id: pbm; anchors.fill: parent; hoverEnabled: true; onClicked: { if (Store.focusView) Store.focusView = false; else if (Store.paneFolded) Store.paneFolded = false; else Store.talkOpen = false } }
        Tip { show: pbm.containsMouse; below: true; text: Store.focusView ? "Leave Focus: bring the side columns back" : Store.paneFolded ? "Show the " + (Store.stage === "shape" ? "Program" : "stage's pane") : "Show the " + (Store.stage === "shape" ? "Program" : "stage's pane") + " (folds the conversation)"; keys: Store.focusView ? "Ctrl+." : "Ctrl+J" }
    }
    // the pane's tab: a handle on the middle of its outer edge folds it to its button, for a wider stage. It stands on
    // the edge's line, half on the pane and half on the stage, and is drawn over the pane (declared after it, below).
    // ── right: the Program, the stage's panel ────────────────
    Glass {
        id: insp
        objectName: "programPane"
        source: studio; arrive: 5
        width: Theme.paneW; radius: Theme.rPane; visible: !ws.panesOff && opacity > 0.01
        opacity: Store.benchOpen ? 0 : 1; Behavior on opacity { NumberAnimation { duration: Theme.exit } }
        x: ws.width - Theme.edge - width; y: Theme.paneTop
        // as tall as what it holds, down to the foot of the window or the legends' dock under it
        readonly property real room_: ws.colFoot - y - dock.reserve
        // In Design, with no feature open, that is the listing: the general parameters, colours and Explore are a scroll below it.
        readonly property real listing: panel.item && panel.item.paneHeight !== undefined && panel.item.paneHeight > 0 && !foot.on ? panel.item.paneHeight : -1
        height: Math.round(Math.max(120, Math.min(room_, stageHead.height + (listing > 0 ? listing + 8 : body.implicitHeight + 22) + foot.height + pipeRow.height)))
        Behavior on height { enabled: insp.settled; NumberAnimation { duration: Theme.move(Theme.cross); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut } }
        property bool settled: false
        Timer { interval: 700; running: true; onTriggered: insp.settled = true }
        readonly property int at: { for (var i = 0; i < Store.stages.length; i++) if (Store.stages[i].id === Store.mode) return i; return 0 }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: function (w) { w.accepted = true } }   // the pane is not the viewport
        // the stage's status in a sentence: stays put while the panel scrolls. The Program listing has its own header.
        Item {
            id: stageHead
            readonly property bool on: (Store.stage === "shape" && Store.hasDraft) || Store.stage === "fit"
            width: parent.width; height: on ? say.implicitHeight + 26 : 6; z: 2; clip: true
            readonly property var s: ws.stageSay(Store.stage)
            Rectangle { visible: stageHead.on; x: 18; y: 20; width: 6; height: 6; radius: 3; color: ws.noteColor(stageHead.s[1]) }
            Txt { id: say; visible: stageHead.on; x: 34; y: 13; width: parent.width - 52; text: stageHead.s[0]; tone: 2 }
            Rectangle { anchors.bottom: parent.bottom; x: 14; width: parent.width - 28; height: 1; color: Theme.rule; opacity: stageHead.on && scroll.contentY > 2 ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Motion.quick } } }
        }
        Flickable {
            id: scroll
            objectName: "inspector"
            anchors.top: stageHead.bottom; anchors.bottom: foot.top; anchors.left: parent.left; anchors.right: parent.right
            // while a toast is up, the last rows can still be scrolled clear of it
            contentHeight: body.implicitHeight + 16; clip: true; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { width: 6 }
            // there is more below: a quiet mark at the foot of the pane
            // (the rows under it fade out into the pane, so the mark never lies across a line of words)
            Fade { parent: scroll; z: 2; anchors.bottom: parent.bottom; x: 1; width: parent.width - 2; height: 30
                opacity: scroll.contentHeight > scroll.height + 4 && scroll.contentY < scroll.contentHeight - scroll.height - 4 ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } }
                c0: Theme.alpha(Theme.glassSolid, 0); c1: Theme.glassSolid; p1: 0.75 }
            Rectangle { parent: scroll; z: 3; anchors.bottom: parent.bottom; anchors.bottomMargin: 5; anchors.horizontalCenter: parent.horizontalCenter; width: 28; height: 4; radius: 2; color: Theme.alpha(Theme.lineBase, 0.22)
                opacity: scroll.contentHeight > scroll.height + 4 && scroll.contentY < 4 ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } } }
            Connections { target: Store; function onRevealInspector(y) { scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, y)) } }
            Column {
                id: body; x: Store.stage === "shape" || Store.stage === "document" ? 6 : 16; y: 0; width: parent.width - 2 * x; spacing: 14
                // the mode's chapter of the Bench (Check: studies, Make: routes, Document: documents), one row grammar;
                // under it the selected row, opened. The row that is the mode's own subject (the checks in Check,
                // the release in Make) opens as the mode's panel below.
                Bench { id: chap; x: 6 - body.x; width: insp.width - 12; visible: Store.stage === "prove" || Store.stage === "release" || Store.stage === "document"
                    chapter: Store.stage === "release" ? "make" : Store.stage === "document" ? "document" : "check" }
                BenchCard { id: opened; x: 6 - body.x; width: insp.width - 12
                    readonly property var pick: chap.visible ? Store.benchSelected(chap.chapter) : null
                    readonly property bool home: !pick || pick.id === Store.benchHome[chap.chapter]
                    e: home ? null : pick
                    // a long chapter: the opened row comes into view under the last rows of the list
                    readonly property string shownId: e ? e.id : ""
                    onShownIdChanged: if (shownId !== "") reveal.restart()
                    Timer { id: reveal; interval: 80       // once the card has its height
                        onTriggered: if (opened.e && opened.y + Math.min(opened.height, 200) > scroll.contentY + scroll.height)
                            scroll.contentY = Math.max(0, Math.min(scroll.contentHeight - scroll.height, opened.y - 104)) } }
                BenchRow { objectName: "studyBack"; x: 6 - body.x; width: insp.width - 12; visible: Store.stage === "fit"; chevron: true; selected: true
                    name: "Fit"; value: ws.d && ws.d.fit ? Math.round(ws.d.fit.yield * 100) + " %" : ""; evidence: ws.d && ws.d.fit ? "modelled" : ""
                    onClicked: Store.setStage("prove") }
                Loader { id: panel; width: parent.width; active: !!Store.data; visible: !chap.visible || opened.home
                    property int was: insp.at
                    source: ({ shape: "Shape.qml", fit: "Fit.qml", prove: "Prove.qml", release: "Release.qml", document: "Document.qml" })[Store.stage] || "Shape.qml"
                    // the new stage comes in from the side it lies on
                    onLoaded: { scroll.contentY = 0; slide.x = Motion.shift(insp.at >= was ? 18 : -18); was = insp.at; enter.restart() }
                    transform: Translate { id: slide }
                    ParallelAnimation { id: enter
                        NumberAnimation { target: panel; property: "opacity"; from: 0; to: 1; duration: Motion.ui; easing.type: Easing.OutCubic }
                        NumberAnimation { target: slide; property: "x"; to: 0; duration: Theme.move(Theme.cross); easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } } }
            }
        }
        // where the artifacts of this revision stand: one line at the foot of the pane, a dot for each step, a
        // sentence for whatever is not current, and Auto. (It was a card of its own under the pane.)
        Item {
            id: pipeRow; objectName: "pipelineCapsule"
            anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right; height: 42
            Rectangle { x: 14; width: parent.width - 28; height: 1; color: Theme.rule }
            Pipeline { id: pipe; flat: true; x: 8; y: 5; width: parent.width - 16; height: 34 }
        }
        // the open draft and its Commit stay in reach at the foot of the inspector, whatever the panel's length
        Item {
            id: foot
            anchors.bottom: pipeRow.top; anchors.left: parent.left; anchors.right: parent.right
            readonly property bool on: Store.hasDraft || !!Store.draftError
            height: on ? Math.min(draft.implicitHeight + 24, Math.round(insp.room_ * 0.46)) : 0
            Rectangle { x: 14; width: parent.width - 28; height: 1; color: Theme.rule; visible: foot.on }
            Flickable {
                anchors.fill: parent; anchors.topMargin: 12; anchors.bottomMargin: 12; clip: true; visible: foot.on
                contentHeight: draft.implicitHeight; boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { width: 6 }
                DraftCard { id: draft; x: 12; width: parent.width - 24 }
            }
        }
    }
    Rectangle {
        id: paneTab; objectName: "paneTab"; z: 8
        visible: insp.visible && !ws.sim; width: 16; height: 48; radius: 8
        x: Math.round(insp.x - width / 2); y: Math.round(insp.y + (insp.height - height) / 2)
        color: ptm.pressed ? Theme.plate4 : ptm.containsMouse ? Theme.plate3 : Theme.glassSolid; border.color: ptm.containsMouse ? Theme.rule2 : Theme.rule
        Behavior on color { Tint {} }
        opacity: insp.opacity
        Shadow { radius: parent.radius; spread: 10; drop: 3; strength: 0.5 }
        Icon { anchors.centerIn: parent; name: "chevron_right"; size: 12; color: ptm.containsMouse ? Theme.ink : Theme.ink3 }
        MouseArea { id: ptm; anchors.fill: parent; anchors.margins: -5; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Store.paneFolded = true }
        Tip { show: ptm.containsMouse; text: "Fold this pane away" }
    }
}
