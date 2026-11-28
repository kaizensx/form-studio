import QtQuick
import "F.js" as F

// A chapter of the Bench, docked in the pane: the studies in Check, the routes in Make, the documents in Document
// (and the design's own entries in the Bench sheet). One row grammar (BenchRow): state, name, number, how it is known.
// The engine decides every state from keys (form/studies.py) and says which chapter an entry is in; this only shows it.
// A click selects a row: what it opens is drawn under the list (BenchCard). A current map also goes onto the part.
Column {
    id: root
    objectName: "bench"
    width: parent ? parent.width : 0
    property string chapter: "check"
    property bool sheet: false               // the Bench sheet's column: two-line rows, its own header
    property string find: ""
    property string only: ""                 // "" | current | stale | never | needs
    readonly property var b: Store.bench && Store.bench.project === Store.pid ? Store.bench : null
    readonly property var mine: b ? b.entries.filter(function (e) { return Store.benchChapter(e) === root.chapter }) : []
    readonly property var na: mine.filter(function (e) { return e.state === "n/a" })
    readonly property var lines: mine.filter(function (e) {
        if (e.state === "n/a" && !(root.showNa || root.only === "needs")) return false
        if (root.only !== "" && Store.benchClass(e) !== root.only) return false
        if (root.find !== "") { var q = root.find.toLowerCase(); if ((e.label + " " + e.doc + " " + e.id).toLowerCase().indexOf(q) < 0) return false }
        return true })
    readonly property int cur: mine.filter(function (e) { return e.state === "current" }).length
    readonly property string sel: Store.benchSel[chapter] || ""
    property bool showNa: false

    Item { width: parent.width; height: 40
        Txt { id: gt; x: 12; anchors.verticalCenter: parent.verticalCenter; font.weight: Theme.wSemi; font.pixelSize: 14; font.letterSpacing: -0.15
            text: ({ design: "Design", check: "Check", make: "Make", document: "Document" })[root.chapter] }
        Txt { visible: root.sheet; anchors.left: gt.right; anchors.leftMargin: 9; anchors.baseline: gt.baseline; kind: "fine"; tone: 3
            text: ({ design: "shape it", check: "prove it", make: "produce it", document: "hand it over" })[root.chapter] }
        Txt { visible: !root.sheet; anchors.left: gt.right; anchors.leftMargin: 8; anchors.baseline: gt.baseline; mono: true; font.pixelSize: 11; tone: 3; text: String(root.mine.length - root.na.length) }
        Txt { objectName: "benchCount-" + root.chapter; anchors.right: parent.right; anchors.rightMargin: 12; anchors.baseline: gt.baseline; mono: root.sheet; font.pixelSize: root.sheet ? 11 : 12; tone: 3
            text: root.sheet ? root.cur + " of " + (root.mine.length - root.na.length)
                : (root.b ? F.pad(root.b.head) + " · " : "") + root.cur + " current" } }
    Repeater {
        // a count, not the array: a reload of the Bench updates the rows in place (the pointer keeps its row)
        model: root.lines.length
        BenchRow {
            required property int index
            readonly property var e: root.lines[index] || ({ id: "", label: "", state: "never", doc: "", by: "engine" })
            readonly property bool off: e.state === "unavailable" || e.state === "n/a"
            objectName: (root.sheet ? "sheet-" : "bench-") + e.id
            gutter: root.sheet ? 4 : 28
            name: e.label; sub: root.sheet ? Store.benchSub(e) : ""
            state: Store.benchDot(e); dim: off
            value: e.headline || ""; evidence: Store.evWord(e.evidence)
            word: Store.benchWord(e); wordColor: e.state === "stale" ? Theme.amber : e.state === "failed" ? Theme.signal : e.state === "running" ? Theme.datum : Theme.ink3
            selected: root.sheet ? Store.benchSheetSel === e.id : (root.sel === e.id || (!!e.app && e.app.indexOf("map.") === 0 && Store.analysisMap === e.app.slice(4)))
            lights: Store.benchLights(e)
            runIcon: off || e.state === "running" ? "" : e.by === "agent" ? "sparkles" : e.by === "person" ? "arrow_right" : e.state === "current" ? "rotate_ccw" : "play"
            runTip: e.by === "agent" ? "Ask your agent" : e.by === "person" ? "Go to the release" : e.state === "current" ? "Run again" : "Run"
            tip: off && !root.sheet ? (e.why || "") : ""
            onClicked: { if (root.sheet) Store.benchSheetSel = e.id; else Store.benchPick(root.chapter, e) }
            onRun: Store.runStudy(e.id, e.state === "current")
        }
    }
    // what does not apply to this design: one quiet line, open on click
    Item { width: parent.width; height: root.na.length && root.only === "" && root.find === "" ? 30 : 0; visible: height > 0
        Txt { objectName: "benchNa"; x: root.sheet ? 34 : 58; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 3
            text: (root.showNa ? "Hide " : "") + root.na.length + " that do not apply to this design" }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.showNa = !root.showNa } }
}
