import QtQuick
import QtQuick.Controls
import "F.js" as F

// The Bench, open (direction I, decision 5): the pane widened into all four chapters at once, over the stage. No tabs:
// every study, route and document of the open design is on one sheet, each with its state; a row that cannot run is
// dimmed and says what it needs. Filters by state, a find field ("/"), and the selected row opened at the foot with
// the exact request Run makes. A sheet is for reading, so its glass is denser than a pane's (80 % plate).
// Ctrl+B, the button in the top right or Esc close it.
Glass {
    id: bs
    objectName: "benchSheet"
    property bool on: false
    readonly property var b: Store.bench && Store.bench.project === Store.pid ? Store.bench : null
    readonly property var es: b ? b.entries : []
    function count(k) { return es.filter(function (e) { return k === "" ? e.state !== "n/a" : Store.benchClass(e) === k }).length }
    readonly property var sel: Store.benchSheetSel ? Store.benchEntry(Store.benchSheetSel) : null
    readonly property int cols: width >= 980 ? 4 : width >= 560 ? 2 : 1
    property string only: ""
    // list: the four columns of rows | tiles: the chapters tiled Analysis / Manufacturing / Documents (BenchTiles.qml)
    property string look: "list"
    onLookChanged: fl.contentY = 0
    radius: Theme.rPane
    opacity: on ? 1 : 0; visible: opacity > 0.01
    Behavior on opacity { NumberAnimation { duration: bs.on ? Theme.base : Theme.exit; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode } }
    // it opens from the pane: the sheet's left edge travels from the pane's to the stage's
    property real from: 0
    property real slide: on ? 0 : Theme.shift(Math.min(from, 220))
    Behavior on slide { NumberAnimation { duration: Theme.move(bs.on ? Theme.benchOpen : Theme.exit); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode } }
    transform: Translate { x: bs.slide }
    Rectangle { anchors.fill: parent; radius: bs.radius; color: Theme.alpha(Theme.plate1, bs.blurred ? 0.8 : 0.9) }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; hoverEnabled: true; onWheel: function (w) { w.accepted = true } }
    onOnChanged: { if (on) { Store.loadBench(); only = ""; Store.benchFind = ""; finder.text = ""; bs.forceActiveFocus() } }
    Keys.onEscapePressed: Store.benchOpen = false
    Shortcut { sequence: "/"; enabled: bs.on && !finder.input.activeFocus; onActivated: finder.input.forceActiveFocus() }

    Item { id: head; x: 28; y: 22; width: parent.width - 56; height: 40
        Txt { id: nm; kind: "h2"; text: "Bench"; anchors.verticalCenter: parent.verticalCenter }
        Txt { id: meta; visible: bs.width >= 700; anchors.left: nm.right; anchors.leftMargin: 14; anchors.baseline: nm.baseline; mono: true; font.pixelSize: 12; tone: 3; wrapMode: Text.NoWrap
            text: Store.project ? Store.project.name + " · " + F.pad(Store.project.head) : "" }
        Seg { id: filt; objectName: "benchFilter"; visible: bs.cols >= 2; anchors.left: meta.visible ? meta.right : nm.right; anchors.leftMargin: 24; anchors.verticalCenter: parent.verticalCenter
            model: [{ value: "", text: "All " + bs.count("") }, { value: "current", text: "Current " + bs.count("current") }, { value: "stale", text: "Stale " + bs.count("stale") },
                    { value: "never", text: "Not run " + bs.count("never") }, { value: "needs", text: (bs.cols >= 4 ? "Needs something " : "Needs ") + bs.count("needs") }]
            value: bs.only; onPicked: function (v) { bs.only = v } }
        Btn { id: close; objectName: "benchClose"; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; kind: "quiet"; small: true; icon: "x"; tip: "Close the Bench"; keys: "Ctrl+B"
            onClicked: Store.benchOpen = false }
        Seg { id: lookSeg; objectName: "benchLook"; anchors.right: close.left; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; implicitHeight: 28
            model: [{ value: "list", text: "List", tip: "Four columns of rows" }, { value: "tiles", text: "Tiles", tip: "Each chapter tiled: Analysis, Manufacturing, Documents" }]
            value: bs.look; onPicked: function (v) { bs.look = v } }
        Field { id: finder; objectName: "benchFind"; visible: bs.cols >= 4; anchors.right: lookSeg.left; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; width: 220; height: 32
            placeholder: "Find a job   /"; onEdited: function (t) { Store.benchFind = t }
            // Esc (Main.qml) clears the find first, then closes the sheet
            Connections { target: Store; function onBenchFindChanged() { if (finder.text !== Store.benchFind) finder.text = Store.benchFind } } } }

    Flickable { id: fl; x: 20; y: 76; width: parent.width - 40; height: parent.height - y - foot.height - legend.height - 22 - 20
        contentHeight: (bs.look === "tiles" ? tiles.implicitHeight : grid.implicitHeight) + 8; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        BenchTiles { id: tiles; visible: bs.look === "tiles"; x: 8; width: parent.width - 24; find: Store.benchFind; only: bs.only }
        Grid { id: grid; visible: bs.look === "list"; columns: bs.cols; columnSpacing: 14; rowSpacing: 10; width: parent.width - 8
            readonly property real cw: Math.floor((width - (bs.cols - 1) * columnSpacing) / bs.cols)
            Repeater { model: ["design", "check", "make", "document"]
                Bench { required property string modelData; required property int index
                    objectName: "benchCol-" + modelData; chapter: modelData; sheet: true; width: grid.cw; find: Store.benchFind; only: bs.only
                    opacity: bs.on ? 1 : 0
                    Behavior on opacity { SequentialAnimation { PauseAnimation { duration: Theme.move(100 + index * 20) } NumberAnimation { duration: Theme.move(120) } } } } } } }

    // what the marks mean, once
    Row { id: legend; x: 28; anchors.bottom: foot.top; anchors.bottomMargin: 12; height: visible ? 20 : 0; spacing: 18; visible: bs.cols >= 2 && bs.height >= 520      // a short sheet keeps its rows
        Repeater { model: [["ok", "current for " + (bs.b ? F.pad(bs.b.head) : "the head")], ["stale", "stale: describes an older revision"], ["none", "not run"], ["dim", "dimmed: says what it needs"]]
            Row { required property var modelData; spacing: 7; opacity: modelData[0] === "dim" ? 0.6 : 1
                Rectangle { width: 6; height: 6; radius: 3; anchors.verticalCenter: parent.verticalCenter
                    color: modelData[0] === "ok" ? Theme.pass : "transparent"; border.width: modelData[0] === "ok" ? 0 : 1; border.color: modelData[0] === "stale" ? Theme.amber : Theme.ink3 }
                Txt { kind: "fine"; tone: 3; text: modelData[1]; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap } } } }

    // the selected row, opened: the exact request, and the buttons
    Rectangle { id: foot; objectName: "benchFoot"; x: 28; width: parent.width - 56; anchors.bottom: parent.bottom; anchors.bottomMargin: 22
        height: bs.sel ? Math.max(84, fc.implicitHeight + 28) : 0; visible: !!bs.sel; radius: 14; color: Theme.alpha(Theme.lineBase, Theme.dark ? 0.045 : 0.035); border.color: Theme.rule
        readonly property bool off: !!bs.sel && (bs.sel.state === "unavailable" || bs.sel.state === "n/a")
        Column { id: fc; x: 16; y: 14; width: parent.width - 32 - fb.width - 16; spacing: 6
            Item { width: parent.width; height: 16
                Txt { id: fl1; mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; font.letterSpacing: 1.0; font.capitalization: Font.AllUppercase; tone: 2; text: bs.sel ? bs.sel.label : ""; wrapMode: Text.NoWrap }
                Txt { anchors.left: fl1.right; anchors.leftMargin: 12; anchors.baseline: fl1.baseline; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.NoWrap
                    text: !bs.sel ? "" : [Store.benchSays(bs.sel), bs.sel.by === "agent" ? "uses your agent" : bs.sel.by === "person" ? "only you" : "", bs.sel.heavy ? "takes minutes" : "",
                                          bs.sel.headline && bs.sel.state !== "never" ? bs.sel.headline + " " + bs.sel.evidence : ""].filter(function (x) { return x !== "" }).join(" · ") } }
            Txt { width: parent.width; tone: 2; text: bs.sel ? (foot.off ? "Needs: " + (bs.sel.why || "") + ". " : "") + (bs.sel.doc || "") : "" }
            Txt { objectName: "benchFootRequest"; visible: text !== ""; width: parent.width; mono: true; font.pixelSize: 11; tone: 3; wrapMode: Text.WrapAnywhere
                text: bs.sel && !foot.off ? Store.benchRequest(bs.sel).split("\n")[0] : "" } }
        Row { id: fb; anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter; spacing: 8
            Btn { objectName: "benchFootRun"; kind: "primary"; visible: !!bs.sel && !foot.off && bs.sel.state !== "running"
                text: !bs.sel ? "" : bs.sel.by === "agent" ? "Ask your agent" : bs.sel.by === "person" ? "Go to the release" : bs.sel.state === "current" ? "Run again" : "Run"
                onClicked: { var e = bs.sel; if (e.by !== "engine") Store.benchOpen = false; Store.runStudy(e.id, e.state === "current") } }
            Btn { kind: "quiet"; visible: !!bs.sel && bs.sel.state === "running"; busy: true; text: "Running…"; enabled: false }
            Btn { objectName: "benchFootOpen"; visible: !!bs.sel; text: "Open in " + (bs.sel ? ({ design: "Design", check: "Check", make: "Make", document: "Document" })[Store.benchChapter(bs.sel)] : "")
                onClicked: { var e = bs.sel, ch = Store.benchChapter(e); Store.benchOpen = false; Store.setStage(Store.benchModeOf(ch)); if (ch !== "design") Store.benchPick(ch, e); else Store.openStudy(e) } } } }
}
