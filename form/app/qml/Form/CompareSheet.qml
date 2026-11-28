import QtQuick
import QtQuick.Controls
import "F.js" as F
import "Py.js" as Py

// What changed between two revisions (the reference's "Versions", in our grammar). Three ways to look, one record:
//   One model     the newer revision, with the features that changed or were added lit, and the older one's edges as
//                 blueprint ghosts (a removed feature is only its ghost)
//   Side by side  both revisions, each in its own 3D view, the two cameras turned and zoomed together
//   Script        the design source as a line diff, coloured as Python
// Beside them: the dimensions that changed (old → new), and the volume, size and body count of both solids from the
// geometric diff (form/geomdiff.py, booleans on the B-rep: computed). Everything is the engine's: GET /compare (read
// from both revisions, no build), /view of each, /geomdiff. Opened from a revision card (TalkChange), the Overview's
// revisions and a feature's line in the tree. Props: { a, b, focus } (b: the head when not given).
Column {
    id: cs
    objectName: "compareSheet"
    readonly property var props: Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
    readonly property int head: Store.project ? Store.project.head : 1
    property int a: props.a !== undefined ? props.a : Math.max(1, head - 1)
    property int b: props.b !== undefined ? props.b : head
    readonly property string focusId: props.focus || ""
    property string title: "What changed"
    property string note: F.pad(a) + " → " + F.pad(b) + (b === head ? " (head)" : "")
    property int sheetWidth: Theme.sheetXl
    property int sheetHeight: Math.max(420, Math.min(640, (cs.Window.height || 800) - 250))
    property var tabs: [{ value: "one", text: "One model" }, { value: "side", text: "Side by side" }, { value: "script", text: "Script" }]
    property string tab: props.tab || "one"

    property var cmp: null                 // GET /compare
    property var viewA: null
    property var viewB: null
    property var geo: null                 // GET /geomdiff
    property bool geoBusy: false
    property string geoError: ""
    property string error: ""
    property string lit: focusId            // the feature under the pointer in the list: lit on the model
    readonly property var revs: Store.project && Store.project.revisions ? Store.project.revisions.map(function (r) { return r.n }) : []
    readonly property var changedIds: !cmp ? [] : cmp.features.filter(function (f) { return f.state === "changed" || f.state === "added" || f.state === "restored" }).map(function (f) { return f.id })
    readonly property int nChanged: !cmp ? 0 : cmp.features.filter(function (f) { return f.state !== "same" }).length
    property int _ask: 0

    function load() {
        var ask = ++_ask, A = a, B = b
        cmp = null; viewA = null; viewB = null; geo = null; geoError = ""; error = ""; geoBusy = true
        Store.pget("/compare?a=" + A + "&b=" + B).then(function (r) { if (ask === cs._ask) cs.cmp = r }, function (e) { if (ask === cs._ask) cs.error = e.message || "Could not read the two revisions." })
        Store.pget("/view?rev=" + A).then(function (v) { if (ask === cs._ask) { cs.viewA = v; cs.place() } }, function () {})
        Store.pget("/view?rev=" + B).then(function (v) { if (ask === cs._ask) { cs.viewB = v; cs.place() } }, function () {})
        Store.pget("/geomdiff?a=" + A + "&b=" + B).then(function (g) { if (ask === cs._ask) { cs.geo = g; cs.geoBusy = false } },
            function (e) { if (ask === cs._ask) { cs.geoBusy = false; cs.geoError = e.message || "The kernel could not compare the solids." } })
    }
    function step(which, d) {             // the older or the newer revision, one along the history
        var i = revs.indexOf(which === "a" ? a : b), j = i + d
        while (j >= 0 && j < revs.length && revs[j] === (which === "a" ? b : a)) j += d
        if (j < 0 || j >= revs.length) return
        if (which === "a") a = revs[j]; else b = revs[j]
        load()
    }
    // the part framed closer than the stage frames it: a sheet has no panes to leave room for
    function frameIn(v) { v.setView("iso", false); v.dist *= 0.7 }
    // the ghost: only the older revision's edges (its solid is not drawn)
    function edgesOnly(v) { return v ? { edges: v.edges, mesh: [] } : null }
    function place() {
        var one = viewLoader.item
        if (!one) return
        if (cs.tab === "one" && one.vp) {
            if (viewB && one.vp.model !== viewB) { one.vp.setModel(viewB); frameIn(one.vp) }
            one.vp.setGhost(edgesOnly(viewA))
            one.vp.flagged = changedIds
        } else if (cs.tab === "side" && one.leftView) {
            if (viewA && one.leftView.model !== viewA) { one.leftView.setModel(viewA); frameIn(one.leftView) }
            if (viewB && one.rightView.model !== viewB) { one.rightView.setModel(viewB); frameIn(one.rightView) }
            one.rightView.flagged = changedIds
        }
    }
    onChangedIdsChanged: place()
    onTabChanged: Qt.callLater(place)
    Component.onCompleted: load()
    function accept() { Store.openSheet(null) }

    property Component footerLeft: Row { spacing: 4
        Btn { objectName: "compareShowA"; kind: "quiet"; small: true; icon: "box"; text: "Show " + F.pad(cs.a) + " on the stage"
            tip: "Close this and draw " + F.pad(cs.a) + " beside the head on the stage, with a wipe between them"
            onClicked: { var n = cs.a; Store.openSheet(null); if (Store.stage !== "shape") Store.setStage("shape"); if (n !== cs.head) Store.compareWith(n) } }
        Btn { objectName: "compareShowB"; kind: "quiet"; small: true; icon: "box"; text: "Show " + F.pad(cs.b) + " on the stage"; visible: cs.b !== cs.head
            onClicked: { var n = cs.b; Store.openSheet(null); if (Store.stage !== "shape") Store.setStage("shape"); Store.compareWith(n) } } }
    property Component footer: Row { spacing: 8
        Btn { objectName: "compareDoneBtn"; kind: "primary"; text: "Done"; keys: "Esc"; onClicked: Store.openSheet(null) } }

    // ── the two revisions: each can step along the history ──
    Item { id: picks; width: parent.width; height: 34
        Row { spacing: 10; anchors.verticalCenter: parent.verticalCenter
            Repeater { model: ["a", "b"]
                Row { required property string modelData; spacing: 2
                    readonly property int n: modelData === "a" ? cs.a : cs.b
                    readonly property var rv: { var rs = Store.project ? Store.project.revisions : []; for (var i = 0; i < rs.length; i++) if (rs[i].n === n) return rs[i]; return null }
                    Btn { small: true; kind: "quiet"; icon: "chevron_left"; tip: "An earlier revision"; onClicked: cs.step(modelData, -1); objectName: "compareStep-" + modelData + "-prev" }
                    Rectangle { width: rl.implicitWidth + 18; height: 26; radius: Theme.rSm; anchors.verticalCenter: parent.verticalCenter
                        color: Theme.alpha(Theme.blueprint, modelData === "a" ? 0.1 : 0.16)
                        Txt { id: rl; objectName: "compareRev-" + modelData; anchors.centerIn: parent; mono: true; font.pixelSize: 12; font.weight: Theme.wMedium; wrapMode: Text.NoWrap
                            color: Theme.strong(Theme.blueprint); text: F.pad(parent.parent.n) + (parent.parent.n === cs.head ? " head" : "") } }
                    Btn { small: true; kind: "quiet"; icon: "chevron_right"; tip: "A later revision"; onClicked: cs.step(modelData, 1); objectName: "compareStep-" + modelData + "-next" }
                    Txt { anchors.verticalCenter: parent.verticalCenter; kind: "fine"; tone: 3; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        width: Math.min(implicitWidth, (cs.width - 420) / 2)
                        text: rv ? (rv.summary || rv.note || "") + " · " + Store.who(rv.origin) : "" } } } }
        Txt { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; kind: "fine"; tone: 3; wrapMode: Text.NoWrap
            text: cs.cmp ? F.plural(cs.cmp.params.length, "value") + ", " + F.plural(cs.nChanged, "feature") + (cs.cmp.script.same ? ", same code" : ", " + cs.cmp.script.added + " lines added, " + cs.cmp.script.removed + " removed") : "" } }
    Item { width: 1; height: 10 }

    Item { id: body; width: parent.width; height: cs.sheetHeight - picks.height - 34
        readonly property real sideW: Math.max(260, Math.min(340, width * 0.32))
        // ── the views, or the script ──
        Rectangle { id: stage; width: parent.width - body.sideW - 20; height: parent.height; radius: Theme.rLg; clip: true
            color: cs.tab === "script" ? Theme.glassWell : Theme.plate; border.color: Theme.rule
            Loader { id: viewLoader; anchors.fill: parent; anchors.margins: cs.tab === "script" ? 0 : 1
                sourceComponent: cs.tab === "one" ? oneView : cs.tab === "side" ? sideView : scriptView
                onLoaded: Qt.callLater(cs.place) }
            Txt { visible: cs.error !== ""; anchors.centerIn: parent; width: parent.width - 60; horizontalAlignment: Text.AlignHCenter; color: Theme.signal; text: cs.error } }

        // ── what changed, in numbers ──
        Flickable { id: side; objectName: "compareSide"; x: parent.width - body.sideW; width: body.sideW; height: parent.height
            contentHeight: sc.implicitHeight + 8; clip: true; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { width: 6 }
            Column { id: sc; width: parent.width - 10; spacing: 6
                Txt { kind: "cap"; text: "Dimensions" }
                Txt { visible: !!cs.cmp && cs.cmp.params.length === 0; kind: "fine"; tone: 2; width: parent.width; text: "No value changed." }
                Repeater { model: cs.cmp ? cs.cmp.params : []
                    Item { required property var modelData; objectName: "compareParam-" + modelData.key; width: sc.width; height: 22
                        Txt { width: parent.width - pv.implicitWidth - 10; elide: Text.ElideRight; wrapMode: Text.NoWrap; tone: 2; text: modelData.label; anchors.verticalCenter: parent.verticalCenter }
                        Txt { id: pv; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 12; wrapMode: Text.NoWrap
                            text: (modelData.from === null ? "new" : F.trim(modelData.from)) + " → " + (modelData.to === null ? "gone" : F.trim(modelData.to)) + (modelData.unit ? " " + modelData.unit : "") } } }
                Item { width: 1; height: 8 }
                Item { width: sc.width; height: 18
                    Txt { kind: "cap"; text: "The solid" }
                    Ev { anchors.right: parent.right; text: cs.geo ? "computed" : ""; lit: true } }
                Row { visible: cs.geoBusy; spacing: 8
                    Spinner { width: 12; height: 12; anchors.verticalCenter: parent.verticalCenter }
                    Txt { kind: "fine"; tone: 2; text: "Comparing the solids in the kernel…" } }
                Txt { visible: cs.geoError !== ""; width: sc.width; kind: "fine"; color: Theme.amber; text: cs.geoError }
                Repeater { model: !cs.geo ? [] : (function () {
                        var g = cs.geo, rows = []
                        function size(bb) { return bb ? [bb[1][0] - bb[0][0], bb[1][1] - bb[0][1], bb[1][2] - bb[0][2]] : null }
                        var sa = size(g.bbox_a), sb = size(g.bbox_b)
                        rows.push({ id: "volume", k: "Volume", v: F.fmt(g.volume_a_mm3 / 1000, 2) + " → " + F.fmt(g.volume_b_mm3 / 1000, 2) + " cm³",
                                    d: (g.net_mm3 >= 0 ? "+" : "−") + F.fmt(Math.abs(g.net_mm3) / 1000, 2) + " cm³" })
                        if (sa && sb) rows.push({ id: "size", k: "Size", v: sb.map(function (x) { return F.trim(x, 1) }).join(" × ") + " mm",
                                    d: [0, 1, 2].map(function (i) { var dd = sb[i] - sa[i]; return Math.abs(dd) < 0.005 ? "0" : (dd > 0 ? "+" : "−") + F.trim(Math.abs(dd), 2) }).join(" / ") })
                        if (g.solids_a !== undefined) rows.push({ id: "bodies", k: "Bodies", v: g.solids_a + " → " + g.solids_b, d: g.solids_b === g.solids_a ? "same" : (g.solids_b > g.solids_a ? "+" : "−") + Math.abs(g.solids_b - g.solids_a) })
                        rows.push({ id: "added", k: "Added", v: F.fmt(g.added.volume_mm3, 1) + " mm³", d: F.plural(g.added.regions, "region") })
                        rows.push({ id: "removed", k: "Removed", v: F.fmt(g.removed.volume_mm3, 1) + " mm³", d: F.plural(g.removed.regions, "region") })
                        return rows })()
                    Column { required property var modelData; objectName: "compareSolid-" + modelData.id; width: sc.width; spacing: 0
                        Item { width: parent.width; height: 20
                            Txt { tone: 2; text: modelData.k; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap }
                            Txt { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 12; wrapMode: Text.NoWrap; text: modelData.v } }
                        Txt { anchors.right: parent.right; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap; text: modelData.d } } }
                Item { width: 1; height: 8 }
                Txt { kind: "cap"; text: "Features" }
                Repeater { model: cs.cmp ? cs.cmp.features : []
                    Item { id: fr; required property var modelData; objectName: "compareFeature-" + modelData.id
                        width: sc.width; height: Math.max(26, fn.implicitHeight + (fw.visible ? fw.implicitHeight + 2 : 0) + 8)
                        readonly property color c: modelData.state === "added" || modelData.state === "restored" ? Theme.pass : modelData.state === "removed" || modelData.state === "suppressed" ? Theme.signal
                            : modelData.state === "changed" ? Theme.datum : Theme.ink3
                        Rectangle { anchors.fill: parent; anchors.leftMargin: -6; radius: 8; color: fm.containsMouse || cs.lit === modelData.id ? Theme.washHover : "transparent" }
                        Rectangle { x: 0; y: 10; width: 7; height: 7; radius: 3.5; color: fr.modelData.state === "same" ? "transparent" : fr.c; border.width: 1.5; border.color: fr.c
                            opacity: fr.modelData.state === "removed" ? 0.75 : 1 }
                        Txt { id: fn; x: 16; y: 4; width: parent.width - 16 - fs.implicitWidth - 8; elide: Text.ElideRight; wrapMode: Text.NoWrap
                            text: fr.modelData.label; tone: fr.modelData.state === "same" ? 3 : 1; font.strikeout: fr.modelData.state === "removed" }
                        Txt { id: fs; anchors.right: parent.right; y: 4; kind: "fine"; wrapMode: Text.NoWrap; color: fr.modelData.state === "same" ? Theme.ink3 : fr.c; text: fr.modelData.state }
                        Txt { id: fw; visible: fr.modelData.why !== "" && fr.modelData.state !== "same"; x: 16; y: fn.y + fn.implicitHeight + 1; width: parent.width - 16; kind: "fine"; tone: 3; text: fr.modelData.why }
                        MouseArea { id: fm; anchors.fill: parent; hoverEnabled: true
                            onContainsMouseChanged: cs.lit = containsMouse ? fr.modelData.id : (cs.lit === fr.modelData.id ? "" : cs.lit) } } }
                Item { width: 1; height: 4 }
                Txt { width: sc.width; kind: "fine"; tone: 3
                    text: cs.cmp ? "Features " + cs.cmp.evidence.features + ". The solid's numbers are booleans on both B-reps." : "" } } } }

    // ── one model: the newer solid, what changed lit, the older edges as ghosts ──
    Component { id: oneView
        Item { property alias vp: one
            Viewport { id: one; objectName: "compareOne"; anchors.fill: parent; showDims: false; showCompanions: false; floorGrid: false
                hovered: cs.lit }
            Row { x: 14; y: 12; spacing: 14
                Repeater { model: [["lit", Theme.datum, "changed or added in " + F.pad(cs.b)], ["ghost", Theme.blueprint, F.pad(cs.a) + " as edges: what was removed is only a ghost"]]
                    Row { required property var modelData; spacing: 7
                        Rectangle { width: modelData[0] === "lit" ? 8 : 14; height: modelData[0] === "lit" ? 8 : 2; radius: modelData[0] === "lit" ? 4 : 1; color: modelData[1]; anchors.verticalCenter: parent.verticalCenter }
                        Txt { kind: "fine"; tone: 2; text: modelData[2]; wrapMode: Text.NoWrap } } } }
            Txt { visible: !cs.viewB; anchors.centerIn: parent; kind: "fine"; tone: 3; text: "Reading " + F.pad(cs.b) + "…" } } }

    // ── side by side: one camera for both ──
    Component { id: sideView
        Item { id: sv
            property alias leftView: va
            property alias rightView: vb
            property bool syncing: false
            function sync(from, to) {
                if (syncing) return
                syncing = true
                to.tween = false; to.az = from.az; to.el = from.el; to.dist = from.dist; to.target = from.target
                syncing = false
            }
            Viewport { id: va; objectName: "compareLeft"; width: parent.width / 2 - 0.5; height: parent.height; showDims: false; showCompanions: false; floorGrid: false
                hovered: cs.lit
                Connections { function onAzChanged() { sv.sync(va, vb) } function onElChanged() { sv.sync(va, vb) } function onDistChanged() { sv.sync(va, vb) } function onTargetChanged() { sv.sync(va, vb) } } }
            Rectangle { x: parent.width / 2 - 0.5; width: 1; height: parent.height; color: Theme.rule2 }
            Viewport { id: vb; objectName: "compareRight"; x: parent.width / 2 + 0.5; width: parent.width / 2 - 0.5; height: parent.height; showDims: false; showCompanions: false; floorGrid: false
                hovered: cs.lit
                Connections { function onAzChanged() { sv.sync(vb, va) } function onElChanged() { sv.sync(vb, va) } function onDistChanged() { sv.sync(vb, va) } function onTargetChanged() { sv.sync(vb, va) } } }
            Repeater { model: [[cs.a, 0], [cs.b, 1]]
                Rectangle { required property var modelData; x: modelData[1] ? sv.width / 2 + 14 : 14; y: 12; height: 24; width: lt.implicitWidth + 16; radius: Theme.rSm
                    color: Theme.alpha(Theme.plate1, 0.8); border.color: Theme.rule
                    Txt { id: lt; objectName: "compareSideLabel"; anchors.centerIn: parent; mono: true; font.pixelSize: 12; wrapMode: Text.NoWrap
                        text: F.pad(parent.modelData[0]) + (parent.modelData[0] === cs.head ? " · head" : "") } } }
            Txt { anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 10; kind: "fine"; tone: 3; wrapMode: Text.NoWrap
                text: "One camera: turn or zoom either view" } } }

    // ── the script: the design source as a line diff, coloured as Python ──
    Component { id: scriptView
        Item {
            Txt { visible: !!cs.cmp && cs.cmp.script.same; anchors.centerIn: parent; tone: 2; text: "The code is the same: only values changed." }
            ListView { id: lv; objectName: "compareScript"; anchors.fill: parent; anchors.margins: 10; clip: true; boundsBehavior: Flickable.StopAtBounds
                model: cs.cmp ? cs.cmp.script.rows : []
                ScrollBar.vertical: ScrollBar { width: 6 }
                delegate: Item { id: ln
                    required property var modelData
                    readonly property bool gap: modelData.t === "gap"
                    width: lv.width - 8; height: gap ? 22 : 18
                    Rectangle { anchors.fill: parent; visible: !ln.gap && ln.modelData.t !== "ctx"; objectName: "scriptRow-" + ln.modelData.t
                        color: ln.modelData.t === "add" ? Theme.alpha(Theme.pass, Theme.dark ? 0.13 : 0.11) : Theme.alpha(Theme.signal, Theme.dark ? 0.13 : 0.09) }
                    Rectangle { visible: ln.gap; anchors.verticalCenter: parent.verticalCenter; width: parent.width; height: 1; color: Theme.rule }
                    Txt { visible: !ln.gap; width: 30; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap
                        text: ln.modelData.a !== null ? ln.modelData.a : "" }
                    Txt { visible: !ln.gap; x: 34; width: 30; horizontalAlignment: Text.AlignRight; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap
                        text: ln.modelData.b !== null ? ln.modelData.b : "" }
                    Txt { visible: !ln.gap; x: 70; width: 12; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 12; wrapMode: Text.NoWrap
                        color: ln.modelData.t === "add" ? Theme.pass : Theme.signal; text: ln.modelData.t === "add" ? "+" : ln.modelData.t === "del" ? "−" : "" }
                    Txt { visible: !ln.gap; x: 86; width: parent.width - 86; anchors.verticalCenter: parent.verticalCenter; mono: true; font.pixelSize: 12; wrapMode: Text.NoWrap; elide: Text.ElideRight
                        textFormat: Text.StyledText; text: Py.colour(ln.modelData.text, Theme.dark) } } } } }
}
