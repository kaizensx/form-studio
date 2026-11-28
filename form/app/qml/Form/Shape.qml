import QtQuick
import "F.js" as F

// Stage 02 — Shape. Pick a feature on the model or here; its parameters and what follows from them.
Column {
    id: root
    width: parent ? parent.width : 0
    readonly property var f: Store.featureById(Store.feature)
    readonly property var params: Store.recipe ? Store.recipe.params : []
    function paramsOf(id) { return params.filter(function (p) { return p.feature === id }) }

    // a design written in OpenSCAD is a mesh: say what that rules out (CAD bridges)
    Note { visible: !!Store.recipe && !!Store.recipe.mesh; kind: "amber"; width: parent.width
        title: "Mesh design · OpenSCAD"
        text: Store.recipe && Store.recipe.mesh ? Store.recipe.notes.join("\n")
              + (Store.recipe.fixed_in_source.length ? "\nFixed in the source (no range comment): " + Store.recipe.fixed_in_source.join(", ") + "." : "") : "" }
    Item { width: 1; height: 8; visible: !!Store.recipe && !!Store.recipe.mesh }

    // ── the program: the features in build order, as a listing that runs ──
    // Each line has its place in the order, its name and its role. While a build plays (the stages an agent streams,
    // or the build-up of a new revision) the listing runs: the gutter lights down to the line being built, the lines
    // above it are ticked, the ones below wait. All of it follows the real build (Store.building, Store.revealing,
    // Store.builtIds, Store.stageLog); the listing counts nothing itself.
    readonly property real paneHeight: root.f || Store.treeLower === "source" ? -1 : program.listingHeight
    // what a line says of its feature: the values it is made of (its own parameters, as the head has them)
    function valueOf(id) {
        var vs = Store.head ? Store.head.values : null, ps = root.paramsOf(id), out = [], unit = ""
        for (var i = 0; vs && i < ps.length && out.length < 3; i++) { var v = vs[ps[i].key]; if (typeof v === "number") { out.push(String(Number(v.toFixed(2)))); unit = ps[i].unit || "" } }
        return out.length === 1 ? out[0] + (unit ? " " + unit : "") : out.join(" × ")
    }
    readonly property int headN: Store.project ? Store.project.head : 0
    onHeadNChanged: loadTree()
    Component.onCompleted: loadTree()
    Timer { id: passed; interval: 420; onTriggered: Store.hover("") }
    readonly property bool streaming: !!Store.building && Store.building.project === Store.pid
    readonly property bool running: streaming || Store.revealing.length > 0
    readonly property int stepAt: streaming ? Store.building.at : Store.buildAt
    readonly property int stepOf: streaming ? Store.building.of : Store.buildOf
    readonly property var builtNow: {
        if (!running) return []
        if (!streaming) return Store.builtIds
        var out = [], d = Store.building.draft
        for (var i = 0; i < Store.stageLog.length; i++) if (Store.stageLog[i].draft === d && Store.stageLog[i].feature !== Store.building.feature) out.push(Store.stageLog[i].feature)
        return out
    }
    // ── the tree by hand (form/modelling.py): roll back, suppress, reorder, rename, what a feature depends on ──
    // Each action is an edit of the design's code (one revision, the checks run again); the rollback bar only shows
    // the part as it stood after one feature, from the checkpoints, and saves nothing.
    readonly property string rollTo: Store.scrub && Store.scrub.upto ? Store.scrub.upto : ""
    readonly property int rollAt: {
        if (!rollTo || !Store.recipe) return -1
        var fs = Store.recipe.features
        for (var i = 0; i < fs.length; i++) if (fs[i].id === rollTo) return i
        return -1
    }
    property int _ask: 0
    property var tree: null                    // GET /tree: what each feature reads
    property string openId: ""                 // the line whose tool is open under it
    property string openWhat: ""               // "rename" | "pattern" | "deps"
    property int dragFrom: -1
    property int dragTo: -1
    property int rollDrag: -1
    function featureIds() { return Store.recipe ? Store.recipe.features.map(function (f) { return f.id }) : [] }
    function roll(fid) {
        var ids = featureIds()
        var ask = ++_ask
        if (!fid || fid === ids[ids.length - 1]) { if (rollTo) Store.endScrub(); return }
        var head = Store.project.head
        Store.pget("/rollback?feature=" + fid).then(function (v) {
            if (ask !== root._ask || !Store.viewer) return
            Store.scrub = { rev: head, view: v, upto: fid }
            Store.viewer.flagged = []; Store.viewer.setModel(v); Store.viewer.setGhost(null)
            Store.hover(fid); passed.restart()                     // the feature the bar passes lights once on the part
        }, function (e) { Store.fail(e) })
    }
    function treeOp(op) {
        if (rollTo) Store.endScrub()
        return Store.ensureConv().then(function (cid) {          // the revision card goes in the open conversation
            return Store.ppost("/tree", { ops: [op], expect_head: Store.project ? Store.project.head : null, conversation: cid })
        }).then(function (r) {
            Store.toast(r.said, "Written into the design's code as " + F.pad(r.head) + "; the checks run again.")
            if (r.job) Store.track(r.job)
            root.tree = null; root.openId = ""; root.openWhat = ""
            Store.refresh(true)
            Store._chatTick()
            return true
        }, function (e) { Store.fail(e); return false })
    }
    function loadTree() { Store.pget("/tree").then(function (t) { root.tree = t }, function () { root.tree = null }) }
    function treeRow(id) {
        var rs = tree ? tree.features : []
        for (var i = 0; i < rs.length; i++) if (rs[i].id === id) return rs[i]
        return null
    }
    function label(id) { var f = Store.featureById(id); return f ? f.label : id }
    function dependsText(id) {
        var r = treeRow(id)
        if (!r) return tree ? "Not read: open the tree again after the build." : "Reading the code…"
        var vals = r.reads.values || {}, out = []
        var ps = r.reads.params.map(function (k) { return k + (vals[k] !== undefined ? " = " + String(Number(Number(vals[k]).toFixed(3))) : "") })
        out.push(ps.length ? "Reads " + ps.join(", ") + "." : "Reads no parameters.")
        out.push(r.after ? "Starts from the solid " + root.label(r.after) + " leaves." : "Makes the first solid.")
        if (r.reads.features.length) out.push("Names " + r.reads.features.map(root.label).join(", ") + " (picked geometry or the feature it repeats).")
        if (r.reads.helpers.length) out.push("Calls " + r.reads.helpers.join(", ") + ".")
        if (r.used_by.length) out.push("Read by " + r.used_by.map(root.label).join(", ") + ".")
        return out.join(" ")
    }
    function rowAt(y) {                            // the index of the line under y (in the listing)
        for (var i = 0; i < rep.count; i++) { var it = rep.itemAt(i); if (it && y < it.y + it.height) return i }
        return rep.count - 1
    }
    function menuFor(i) {
        var fs = Store.recipe ? Store.recipe.features : [], f = fs[i]
        if (!f) return []
        var sup = !!f.suppressed
        return [{ text: "Roll back to here", icon: "history", run: function () { root.roll(f.id) } },
                { text: sup ? "Restore" : "Suppress", icon: sup ? "eye" : "eye_off", enabled: i > 0,
                  run: function () { root.treeOp({ op: sup ? "restore" : "suppress", feature: f.id }) } },
                { text: "Rename…", icon: "pencil", run: function () { root.openId = f.id; root.openWhat = "rename" } },
                { text: "Edit sketch…", icon: "pen_tool", visible: /^(extrude|cut|revolve)_/.test(f.id), enabled: /^(extrude|cut|revolve)_/.test(f.id) && !sup,
                  run: function () { Store.pget("/sketch?feature=" + f.id).then(function (r) {
                      Store.openSheet("handsketch", { mode: "edit", feature: f.id, sketch: r.sketch, values: r.values }) }, function (e) { Store.fail(e) }) } },
                { text: "Move up", icon: "chevron_up", enabled: i > 1, run: function () { root.treeOp({ op: "move", feature: f.id, before: fs[i - 1].id }) } },
                { text: "Move down", icon: "chevron_down", enabled: i > 0 && i < fs.length - 1, run: function () { root.treeOp({ op: "move", feature: f.id, after: fs[i + 1].id }) } },
                { sep: true },
                { text: "Pattern…", icon: "repeat", enabled: i > 0 && !sup, run: function () { root.openId = f.id; root.openWhat = "pattern" } },
                { text: "What it depends on", icon: "git_branch", run: function () { root.openId = f.id; root.openWhat = "deps"; root.loadTree() } },
                { text: "Compare versions…", icon: "git_compare", enabled: !!Store.project && Store.project.revisions.length > 1,
                  run: function () { var h = Store.project.head, rs = Store.project.revisions.map(function (r) { return r.n }).filter(function (n) { return n !== h })
                      Store.openSheet("compare", { a: rs[rs.length - 1], b: h, focus: f.id }) } }].filter(function (e) { return e.visible !== false })
    }
    PopMenu { id: rowMenu; objectName: "featureMenu"; property int at: -1
        // the entries of this line as it is now (a binding would keep the ones of the line it was last opened on
        // until the listing settles after a revision)
        function show(i, item, x, y) {
            at = i; model = root.menuFor(i); openAt(item, x, y)
            // placed again once the listing has laid out: a line that moved as the revision landed keeps its menu
            Qt.callLater(function () { var p = item.mapToItem(rowMenu.parent, x, y); rowMenu.x = Math.round(p.x); rowMenu.y = Math.round(p.y) })
        } }
    Connections { target: Store; function onPidChanged() { root.tree = null; root.openId = ""; root.openWhat = "" } }
    // the dock's Pattern: the selected feature's pattern panel opens under its line
    function wantPattern() {
        if (Ws.want !== "pattern" || !Store.feature || !Store.recipe) return
        var ids = Store.recipe.features.map(function (f) { return f.id })
        if (ids.indexOf(Store.feature) > 0) { root.openId = Store.feature; root.openWhat = "pattern" }
    }
    Connections { target: Ws; function onWantChanged() { root.wantPattern() } }
    Connections { target: Store; function onFeatureChanged() { root.wantPattern() } }

    Column {
        id: program; objectName: "program"
        readonly property real listingHeight: 40 + listing.height + 6      // the pane is this tall; what follows is a scroll away
        width: parent.width
        Item { width: parent.width; height: 40
            Txt { id: pt; x: 12; anchors.verticalCenter: parent.verticalCenter; text: "Tree"; font.weight: Theme.wSemi; font.pixelSize: 14; font.letterSpacing: -0.15 }
            Txt { anchors.left: pt.right; anchors.leftMargin: 8; anchors.baseline: pt.baseline; mono: true; font.pixelSize: 11; tone: 3; text: Store.recipe ? String(Store.recipe.features.length) : "" }
            // under the tree: the values of the open feature, or the design's source with that feature's lines lit
            Seg { objectName: "treeLower"; visible: !root.running && !!root.tree; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; implicitHeight: 26
                model: [{ value: "values", text: "Values" }, { value: "source", text: "Source", tip: "The design's code: every feature is a method. The open feature's lines are lit." }]
                value: Store.treeLower; onPicked: function (v) { Store.treeLower = v } }
            Row { objectName: "programRun"; visible: root.running; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 9
                Item { width: 14; height: 14; anchors.verticalCenter: parent.verticalCenter
                    Rectangle { anchors.centerIn: parent; width: 14; height: 14; radius: 7; color: Theme.alpha(Theme.datum, 0.22) }
                    Rectangle { anchors.centerIn: parent; width: 6; height: 6; radius: 3; color: Theme.datum } }
                Txt { anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; font.letterSpacing: 1.5; font.capitalization: Font.AllUppercase; color: Theme.datum; wrapMode: Text.NoWrap
                    text: root.stepOf > 1 ? root.stepAt + " of " + root.stepOf : "building" } } }
        Item {
            id: listing; width: parent.width; height: lines.implicitHeight
            // the gutter: the one drawn line of the pane, 39 px in: between the numbers and the marks, which stand
            // beside it and are never crossed by it. Lit from the top down to the middle of the line being built.
            Rectangle { x: 39; y: 4; width: 1; height: parent.height - 8; color: Theme.rule }
            // the line being built is raised: one pane of glass that glides from line to line
            Rectangle { id: nowBar; objectName: "programNow"; width: parent.width; height: 32; radius: 10; color: Theme.glass2
                y: pc.at ? pc.at.y : 0; opacity: root.running && pc.at ? 1 : 0; visible: opacity > 0.01
                Behavior on y { enabled: nowBar.opacity > 0.5; NumberAnimation { duration: Theme.move(220); easing.type: Easing.OutCubic } }
                Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                Rectangle { x: parent.radius; width: parent.width - 2 * parent.radius; height: 1; color: Qt.rgba(1, 1, 1, Theme.dark ? 0.1 : 0) } }
            Rectangle { id: pc; objectName: "programGutter"; x: 38.5; y: 0; width: 2; radius: 1
                property Item at: null                    // the row being built
                property real reach: root.running && at ? at.y + 16 : 0
                height: reach; visible: height > 0.5
                opacity: root.running ? 1 : 0
                Behavior on reach { NumberAnimation { duration: Theme.reduced ? 0 : 220; easing.type: Easing.OutCubic } }
                Behavior on opacity { NumberAnimation { duration: Theme.cross } }
                gradient: Gradient { GradientStop { position: 0; color: Theme.alpha(Theme.datum, 0.25) } GradientStop { position: 0.7; color: Theme.datum } }
                Glow { blur: 10; strength: 0.55 } }
            Column {
                id: lines; width: parent.width
                Repeater {
                    id: rep
                    model: Store.recipe ? Store.recipe.features : []
                    Item {
                        id: fr
                        required property var modelData
                        required property int index
                        objectName: "feature-" + modelData.id
                        readonly property bool sup: !!modelData.suppressed
                        readonly property bool later: root.rollAt >= 0 && index > root.rollAt     // after the rollback bar
                        readonly property bool tools: root.openId === modelData.id && !!root.openWhat
                        opacity: later ? 0.38 : 1
                        Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                        readonly property bool touched: root.paramsOf(modelData.id).some(function (p) { return Store.draftValues[p.key] !== undefined })
                        readonly property var out: Store.leftOut(modelData.id)       // left out of a partial build
                        // its step of a build is running in the viewport (Store.revealing, or the stage the agent streams)
                        readonly property bool arriving: Store.revealing.indexOf(modelData.id) >= 0 || (root.streaming && Store.building.feature === modelData.id)
                        readonly property bool built: root.running && !arriving && root.builtNow.indexOf(modelData.id) >= 0
                        readonly property bool todo: root.running && !arriving && !built
                        onArrivingChanged: if (arriving) pc.at = fr
                        onBuiltChanged: if (built && root.running) landed.restart()
                        readonly property real lineH: Math.max(32, why.visible ? why.implicitHeight + 30 : 0)
                        width: lines.width; height: lineH + (ex.visible ? ex.implicitHeight + 10 : 0)
                        readonly property bool picked: Store.feature === modelData.id && !root.running
                        readonly property var made: { var r = root.treeRow(modelData.id); return r && r.made ? r.made : null }
                        readonly property string val: root.valueOf(modelData.id)
                        Rectangle { width: parent.width; height: fr.lineH; radius: 10
                            color: fr.picked ? Theme.glass2 : fm.pressed ? Theme.washPress : fm.containsMouse && !fr.arriving ? Theme.washHover : "transparent"
                            Behavior on color { Tint {} } }
                        Item { objectName: "featureArriving"; width: 1; height: 1; opacity: fr.arriving ? 1 : 0 }       // what the tree and tests read
                        // its number in the build order
                        Txt { x: 0; y: (32 - height) / 2; width: 30; horizontalAlignment: Text.AlignRight; mono: true; font.pixelSize: 11; wrapMode: Text.NoWrap
                            text: (fr.index < 9 ? "0" : "") + (fr.index + 1); color: fr.arriving ? Theme.datum : fr.out ? Theme.amber : Theme.ink3; opacity: fr.todo ? 0.7 : 1
                            Behavior on color { Tint {} } }
                        // the mark, right of the gutter: ticked when built (the tick lands on a small spring and its
                        // light flares once), a pointer on the line being built
                        Item { x: 34; y: 0; width: 30; height: 32
                            Rectangle { id: flare; anchors.centerIn: parent; width: 6; height: 6; radius: 3; color: Theme.pass; opacity: 0
                                Glow { color: Theme.pass; blur: 9; strength: 0.9; on: flare.opacity > 0.01 } }
                            Icon { id: tick; anchors.centerIn: parent; name: "check"; size: 13; color: Theme.pass
                                opacity: fr.built ? 1 : 0; scale: fr.built ? 1 : Theme.from(0.3)
                                Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                                Behavior on scale { SpringAnimation { spring: 5.5; damping: 0.36; epsilon: 0.01 } } }
                            Icon { anchors.centerIn: parent; name: "play"; size: 10; color: Theme.datum
                                opacity: fr.arriving ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.fast } } }
                            SequentialAnimation { id: landed
                                NumberAnimation { target: flare; property: "opacity"; from: 0; to: Theme.reduced ? 0 : 0.9; duration: 90 }
                                NumberAnimation { target: flare; property: "opacity"; to: 0; duration: 360; easing.type: Easing.OutCubic } } }
                        Txt { id: nameTxt; x: 64; y: (32 - height) / 2; width: parent.width - 64 - kw.width - 22; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.pixelSize: 13; font.letterSpacing: -0.05
                            text: fr.modelData.label + (fr.touched ? "  ●" : ""); font.weight: fr.arriving ? Theme.wSemi : Theme.wMedium
                            font.strikeout: fr.sup
                            color: fr.touched ? Theme.datum : fr.out || fr.todo || fr.sup ? Theme.ink3 : fr.built ? Theme.ink2 : Theme.ink
                            Behavior on color { Tint {} } }
                        Txt { id: why; objectName: "leftOutReason"; kind: "fine"; visible: !!fr.out; tone: 2; x: 64; y: 28; width: parent.width - 78; wrapMode: Text.WordWrap
                            text: fr.out ? Store.leftOutReason(fr.out) : "" }
                        // its role, lettered in neutral mono; "building" on the line that runs
                        Txt { id: kw; objectName: "featureRole"; anchors.right: parent.right; anchors.rightMargin: 12; y: (32 - height) / 2; mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; font.letterSpacing: 1.0
                            readonly property bool word: fr.arriving || !!fr.out || fr.sup
                            font.capitalization: word ? Font.AllUppercase : Font.MixedCase; wrapMode: Text.NoWrap
                            // its value, and who made it (the role told less than the value)
                            text: fr.arriving ? "building" : fr.out ? "left out" : fr.sup ? "suppressed" : fr.val
                            visible: !(fm.containsMouse || more.hovered) || root.running
                            color: fr.arriving ? Theme.datum : fr.out ? Theme.amber : Theme.ink3; opacity: fr.built ? 0.6 : fr.todo ? 0.5 : 1 }
                        Icon { objectName: "featureAuthor"; visible: !!fr.made && kw.visible && !kw.word; anchors.right: kw.left; anchors.rightMargin: kw.text !== "" ? 7 : 0; y: (32 - height) / 2
                            readonly property bool you: !!fr.made && Store.who(fr.made.origin).indexOf("you") === 0
                            name: you ? "user" : "sparkles"; size: 12; color: Theme.ink3 }
                        MouseArea { id: fm; width: parent.width; height: fr.lineH; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton
                            onClicked: function (m) {
                                if (m.button === Qt.RightButton && !root.running) rowMenu.show(fr.index, fr, m.x, m.y)
                                else Store.select(fr.modelData.id) }
                            onEntered: Store.hover(fr.modelData.id); onExited: Store.hover("") }
                        // its tools: the line's menu (also on a right-click)
                        Btn { id: more; objectName: "featureMore-" + fr.modelData.id; small: true; kind: "quiet"; icon: "ellipsis"
                            anchors.right: parent.right; anchors.rightMargin: 4; y: (32 - height) / 2
                            visible: (fm.containsMouse || hovered || (rowMenu.opened && rowMenu.at === fr.index)) && !root.running
                            tip: "Roll back, suppress, rename, move, pattern"
                            onClicked: rowMenu.show(fr.index, more, 0, more.height + 4) }
                        // reorder by drag: press on the number and drag it to another line
                        MouseArea { objectName: "featureDrag-" + fr.modelData.id; x: 0; width: 34; height: fr.lineH; enabled: fr.index > 0 && !root.running
                            cursorShape: enabled ? Qt.SizeVerCursor : Qt.ArrowCursor; preventStealing: true
                            onPressed: { root.dragFrom = fr.index; root.dragTo = fr.index }
                            onPositionChanged: function (m) { if (pressed) root.dragTo = Math.max(1, root.rowAt(mapToItem(lines, m.x, m.y).y)) }
                            onReleased: {
                                var a = root.dragFrom, b = root.dragTo, fs = Store.recipe.features
                                root.dragFrom = -1; root.dragTo = -1
                                if (a < 1 || b < 1 || a === b) return
                                root.treeOp(b < a ? { op: "move", feature: fs[a].id, before: fs[b].id } : { op: "move", feature: fs[a].id, after: fs[b].id }) }
                            onCanceled: { root.dragFrom = -1; root.dragTo = -1 } }
                        Tip { show: fm.containsMouse && (!!fr.modelData.doc || !!fr.made) && !fr.out
                            text: (fr.modelData.doc || "") + (fr.made ? (fr.modelData.doc ? "\n" : "") + "Made by " + Store.who(fr.made.origin) + " in " + F.pad(fr.made.rev) + "." : "") }
                        // under the line: rename it, pattern it, or what it depends on
                        Column { id: ex; objectName: "featureTools"; x: 64; y: fr.lineH + 2; width: parent.width - 76; spacing: 6; visible: fr.tools && !root.running
                            Field { id: rn; objectName: "renameField"; width: parent.width; visible: root.openWhat === "rename"; text: fr.modelData.label
                                placeholder: "Name of this feature"
                                onVisibleChanged: if (visible) Qt.callLater(function () { rn.input.forceActiveFocus(); rn.input.selectAll() })
                                onAccepted: function (t) { if (t.trim() && t.trim() !== fr.modelData.label) root.treeOp({ op: "rename", feature: fr.modelData.id, label: t.trim() }); else { root.openId = ""; root.openWhat = "" } }
                                Keys.onEscapePressed: { root.openId = ""; root.openWhat = "" } }
                            Txt { objectName: "featureDepends"; width: parent.width; kind: "fine"; tone: 2; visible: root.openWhat === "deps"; text: root.dependsText(fr.modelData.id) }
                            ModelPanel { width: parent.width; visible: root.openWhat === "pattern"; kinds: root.openWhat === "pattern" ? ["pattern"] : []
                                of: fr.modelData.id; onDone: { root.openId = ""; root.openWhat = "" } }
                            Btn { small: true; kind: "quiet"; text: "Close"; visible: root.openWhat !== "pattern"; onClicked: { root.openId = ""; root.openWhat = "" } } }
                    }
                }
            }
            // where a dragged line would go
            Rectangle { objectName: "programDropLine"; visible: root.dragFrom >= 0 && root.dragTo >= 0 && root.dragTo !== root.dragFrom
                x: 30; width: parent.width - 36; height: 2; radius: 1; color: Theme.datum
                y: { var it = rep.itemAt(root.dragTo); return it ? (root.dragTo < root.dragFrom ? it.y - 1 : it.y + it.height - 1) : 0 } }
            // the rollback bar: drag it up the listing to see the part as it stood after that feature (from its
            // checkpoints, in milliseconds); nothing is saved. Below the last line it shows every feature.
            Item {
                id: rollBar; objectName: "rollBar"
                readonly property int at: root.rollDrag >= 0 ? root.rollDrag : root.rollAt >= 0 ? root.rollAt : rep.count - 1
                readonly property Item row: rep.count ? rep.itemAt(at) : null
                visible: rep.count > 1 && !root.running && !Store.hasDraft
                x: 4; width: parent.width - 8; height: 12
                y: row ? row.y + row.lineH - 6 : listing.height - 6
                Behavior on y { enabled: root.rollDrag < 0; NumberAnimation { duration: Theme.move(160); easing.type: Easing.OutCubic } }
                Rectangle { x: 28; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 28; height: 1.5
                    color: root.rollAt >= 0 || root.rollDrag >= 0 ? Theme.datum : Theme.alpha(Theme.datum, 0.35); opacity: grip.containsMouse || grip.pressed || root.rollAt >= 0 ? 1 : 0.55 }
                Rectangle { objectName: "rollGrip"; x: 22; anchors.verticalCenter: parent.verticalCenter; width: 22; height: 10; radius: 5
                    color: grip.pressed ? Theme.datum : Theme.glassSolid; border.color: Theme.datum
                    Rectangle { anchors.centerIn: parent; width: 8; height: 1.5; radius: 1; color: grip.pressed ? Theme.glassSolid : Theme.datum } }
                MouseArea { id: grip; x: 14; width: 40; height: parent.height + 8; y: -4; hoverEnabled: true; preventStealing: true
                    cursorShape: Qt.SizeVerCursor
                    onPositionChanged: function (m) {
                        if (!pressed) return
                        var i = root.rowAt(mapToItem(lines, m.x, m.y).y - 8)
                        if (i !== root.rollDrag) { root.rollDrag = i; root.roll(Store.recipe.features[i].id) } }
                    onReleased: root.rollDrag = -1
                    onCanceled: root.rollDrag = -1 }
                Tip { show: grip.containsMouse && !grip.pressed; text: root.rollAt >= 0 ? "Rolled back to " + root.label(root.rollTo) + ": drag down to the end to show every feature"
                                                                                       : "Drag up to see the part as it stood after any feature" }
            }
        }
        Item { width: 1; height: 6 }
        // the design's source, under the tree: the same thing the values and the handles change. Read from the head.
        Rectangle { id: src; objectName: "treeSource"; visible: Store.treeLower === "source" && !!root.tree && !!root.tree.source && !root.running
            x: 6; width: parent.width - 12; height: visible ? Math.min(264, src.rows.length * 16 + 16) : 0; radius: 10; color: Theme.glassWell; border.color: Theme.rule; clip: true
            readonly property var rows: root.tree && root.tree.source ? String(root.tree.source).replace(/\s+$/, "").split("\n") : []
            readonly property var lit: { var r = root.treeRow(Store.feature || root.rollTo); return r && r.lines ? r.lines : null }
            onLitChanged: if (lit && visible) sv.positionViewAtIndex(Math.max(0, lit[0] - 2), ListView.Beginning)
            onVisibleChanged: if (lit && visible) sv.positionViewAtIndex(Math.max(0, lit[0] - 2), ListView.Beginning)
            ListView { id: sv; anchors.fill: parent; anchors.margins: 8; clip: true; boundsBehavior: Flickable.StopAtBounds; model: src.rows
                delegate: Item { id: ln
                    required property string modelData
                    required property int index
                    readonly property bool on: !!src.lit && index + 1 >= src.lit[0] && index + 1 <= src.lit[1]
                    width: sv.width; height: 16
                    Rectangle { objectName: ln.on ? "treeSourceLit" : ""; visible: ln.on; anchors.fill: parent; color: Theme.alpha(Theme.datum, Theme.dark ? 0.14 : 0.1) }
                    Txt { width: 24; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 11; color: ln.on ? Theme.datum : Theme.ink3; wrapMode: Text.NoWrap; text: ln.index + 1 }
                    Txt { x: 34; width: parent.width - 34; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 11; tone: ln.on ? 1 : 2; wrapMode: Text.NoWrap; elide: Text.ElideRight; textFormat: Text.PlainText; text: ln.modelData } } } }
        Item { width: 1; height: src.visible ? 8 : 0 }
    }
    Column {
        visible: !root.f; x: 10; width: parent.width - 20
        Sec { title: "General"
            visible: gen.count > 0
            Item { width: parent.width; height: 1 }
            Column { width: parent.width; x: 0
                Repeater { id: gen
                    model: root.params.filter(function (p) { return p.group !== "brief" && !Store.featureById(p.feature) })
                    ParamRow { required property var modelData; p: modelData } } } }
        Appearance { }                                  // colours and materials (form/materials.py)
        Sec { title: "Explore"
            Txt { tone: 2; width: parent.width; text: "Build a grid of real candidates and rank them against objectives you weight." }
            Row { spacing: 6
                Btn { text: "Compare alternatives"; icon: "boxes"; enabled: !Store.hasDraft; onClicked: Store.openSheet("alternatives") }
                Btn { kind: "quiet"; text: "Variants"; icon: "layout_grid"; onClicked: Store.openSheet("variants") } } }
    }

    // one feature
    Column {
        visible: !!root.f; x: 10; width: parent.width - 20
        Item { width: parent.width; height: 34
            Btn { kind: "quiet"; small: true; icon: "x"; text: "Close"; tip: "Back to the design's general values"; x: -8; anchors.verticalCenter: parent.verticalCenter; onClicked: Store.select("") } }
        Row { spacing: 8
            Txt { kind: "h2"; text: root.f ? root.f.label : "" }
            Tag { text: root.f ? root.f.role : ""; anchors.verticalCenter: parent.verticalCenter } }
        Txt { tone: 2; width: parent.width; topPadding: 4 + lead; visible: text !== ""; text: root.f ? (root.f.doc || "") : "" }
        // its own parameters; a feature without any says what shapes it instead: values that follow from standards
        // (below), the design's general parameters and the features built before it (each one click away)
        Sec { id: drives; objectName: "featureDrives"
            readonly property int n: root.f ? root.paramsOf(root.f.id).length : 0
            readonly property var before: {
                var fs = Store.recipe ? Store.recipe.features : [], out = []
                for (var i = 0; root.f && i < fs.length && fs[i].id !== root.f.id; i++) out.push(fs[i])
                return out }
            readonly property int general: root.params.filter(function (p) { return p.group !== "brief" && !Store.featureById(p.feature) }).length
            readonly property int derived: root.f && Store.shown && Store.shown.derived ? Store.shown.derived.filter(function (x) { return x.feature === root.f.id }).length : 0
            title: n > 0 ? "Parameters" : "What shapes it"; note: n > 1 ? String(n) : ""
            Txt { objectName: "featureNoParams"; tone: 2; width: parent.width; visible: !!root.f && drives.n === 0
                text: {
                    var from = []
                    if (drives.derived) from.push("the values below")
                    if (drives.general) from.push("the design's general parameters")
                    if (drives.before.length) from.push("the features built before it")
                    return from.length ? "No settings of its own. Its size and place come from " + from.slice(0, -1).join(", ") + (from.length > 1 ? " and " : "") + from[from.length - 1] + "."
                                       : "No settings of its own. To change it, describe what you want in the conversation." } }
            Flow { width: parent.width; spacing: Theme.s1; visible: !!root.f && drives.n === 0 && (drives.before.length > 0 || drives.general > 0)
                Repeater { model: drives.n === 0 ? drives.before.slice(-3) : []
                    Btn { required property var modelData; small: true; kind: "quiet"; icon: "box"; text: modelData.label
                        tip: "Open " + modelData.label; onClicked: Store.select(modelData.id) } }
                Btn { visible: drives.general > 0; small: true; kind: "quiet"; icon: "sliders_horizontal"; text: "General parameters"
                    tip: "All features, with the design's general parameters"; onClicked: Store.select("") } }
            Column { width: parent.width
                Repeater { model: root.f ? root.paramsOf(root.f.id) : []
                    ParamRow { required property var modelData; p: modelData; prov: modelData.group === "brief" } } } }
        // design tools: the text a Label parameter puts on the part (project setting; empty = the project name)
        Sec { title: "Label text"; note: "used when Label is 1 or 2"
            visible: !!root.f && root.f.id === "mark" && root.paramsOf("mark").some(function (p) { return p.key === "label" })
            Field { id: markText; width: parent.width; placeholder: Store.project ? Store.project.name : ""
                text: Store.project && Store.project.mark_text ? Store.project.mark_text : ""
                onAccepted: function (t) {
                    if (!Store.project || t === (Store.project.mark_text || "")) return
                    Store.settings({ mark_text: t }).then(function () { Store.refresh(true); if (Store.hasDraft) Store.runPreview() }) } }
            Txt { kind: "fine"; width: parent.width
                text: "Press Enter to apply. Lettering uses Form Studio’s bundled font; the checks measure its stroke width against the nozzle. The revision stamp reads like “r04 a3f1”: revision, then a short hash of its values." } }
        Sec { title: drives.n > 0 ? "Follows from them" : "Values it uses"; note: "not editable"
            readonly property var rows: root.f && Store.shown ? Store.shown.derived.filter(function (x) { return x.feature === root.f.id }) : []
            visible: rows.length > 0
            Column { width: parent.width
                Repeater { model: parent.parent.rows
                    KV { required property var modelData; required property int index; first: index === 0
                        k: modelData.label; sub: modelData.formula || ""; value: F.fmt(modelData.value) + " " + modelData.unit; tag: modelData.interface ? "interface" : "" } } } }
    }
}
