import QtQuick

// The Bench: every study, route and document that can be asked of the open design, as a listing in the Program's
// style. Each line: its state mark in the gutter, its name, its headline in mono with the evidence it rests on, and
// its state lettered on the right (CURRENT · R03, STALE · R02, NEVER RUN, FAILED, RUNNING). The engine decides every
// state from keys (form/studies.py); this pane only shows it. A line that is not current runs on click (or from its
// run mark); a current one opens what it made. Cyan is where you are: the line running, or the map on the part.
//   groups   which groups this stage lists: ["study"] in Review, ["route", "document"] in Make
Column {
    id: root
    objectName: "bench"
    width: parent ? parent.width : 0
    property var groups: ["study"]
    readonly property var b: Store.bench && Store.bench.project === Store.pid ? Store.bench : null
    readonly property var rows: b ? b.entries.filter(function (e) { return root.groups.indexOf(e.group) >= 0 }) : []
    readonly property var na: rows.filter(function (e) { return e.state === "n/a" })
    property bool showNa: false
    function stateColor(s) { return s === "current" ? Theme.pass : s === "stale" ? Theme.amber : s === "failed" ? Theme.signal : s === "running" ? Theme.datum : Theme.ink3 }
    function stateText(e) {
        var r = e.rev !== null && e.rev !== undefined ? " · r" + (e.rev < 10 ? "0" : "") + e.rev : ""
        if (e.by === "person") return e.state === "current" ? "released" + r : e.state === "stale" ? "superseded" + r : "not released"
        return e.state === "current" ? "current" + r : e.state === "stale" ? "stale" + r : e.state === "never" ? "never run"
             : e.state === "unavailable" ? "needs" : e.state === "n/a" ? "n/a" : e.state
    }
    function here(e) { return e.state === "running" || (e.app && e.app.indexOf("map.") === 0 && Store.analysisMap === e.app.slice(4)) }
    function act(e) {
        if (e.state === "running" || e.state === "n/a") return
        if (e.state === "current" && e.by === "engine") Store.openStudy(e); else Store.runStudy(e.id)
    }

    Repeater {
        model: root.groups
        Column {
            id: grp
            required property string modelData
            readonly property var lines: root.rows.filter(function (e) { return e.group === grp.modelData && (e.state !== "n/a" || root.showNa) })
            readonly property int cur: lines.filter(function (e) { return e.state === "current" }).length
            width: root.width
            visible: lines.length > 0
            Item { width: parent.width; height: 40
                Txt { id: gt; x: 12; anchors.verticalCenter: parent.verticalCenter; font.weight: Theme.wSemi; font.pixelSize: 14; font.letterSpacing: -0.15
                    text: ({ study: "Studies", route: "Routes", document: "Documents" })[grp.modelData] || grp.modelData }
                Txt { anchors.left: gt.right; anchors.leftMargin: 8; anchors.baseline: gt.baseline; mono: true; font.pixelSize: 11; tone: 3; text: String(grp.lines.length) }
                Txt { objectName: "benchCount-" + grp.modelData; anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 3
                    text: grp.cur + " of " + grp.lines.length + " current" } }
            Item {
                width: parent.width; height: col.implicitHeight
                // the gutter: the one drawn line, between the marks and the names (the Program's own)
                Rectangle { x: 23; y: 4; width: 1; height: parent.height - 8; color: Theme.rule }
                Column {
                    id: col; width: parent.width
                    Repeater {
                        // a count, not the array: a reload of the Bench updates the lines in place (the pointer
                        // keeps its line and the run mark), it does not make them again
                        model: grp.lines.length
                        Item {
                            id: row
                            required property int index
                            readonly property var e: grp.lines[index] || ({ id: "", label: "", state: "never", doc: "" })
                            readonly property bool lit: root.here(e)
                            objectName: "bench-" + e.id
                            width: col.width; height: Math.max(36, words.implicitHeight + 14)
                            Rectangle { anchors.fill: parent; radius: 10
                                color: row.lit ? Theme.glass2 : rm.pressed ? Theme.washPress : rm.containsMouse ? Theme.washHover : "transparent"
                                Behavior on color { Tint {} } }
                            // the state mark, on the gutter: filled when there is a result, a ring when there is none
                            Item { x: 14; y: 0; width: 20; height: 34
                                Rectangle { objectName: "benchDot"; anchors.centerIn: parent; width: 8; height: 8; radius: 4
                                    color: row.e.state === "never" || row.e.state === "unavailable" || row.e.state === "n/a" ? Theme.glassSolid : root.stateColor(row.e.state)
                                    border.width: row.e.state === "never" || row.e.state === "unavailable" || row.e.state === "n/a" ? 1.5 : 0
                                    border.color: root.stateColor(row.e.state)
                                    Glow { color: Theme.datum; blur: 8; strength: 0.8; on: row.e.state === "running" } }
                                SequentialAnimation on opacity { running: row.e.state === "running" && !Theme.reduced; loops: Animation.Infinite
                                    NumberAnimation { to: 0.45; duration: 620; easing.type: Easing.InOutSine }
                                    NumberAnimation { to: 1; duration: 620; easing.type: Easing.InOutSine } } }
                            Column {
                                id: words; x: 40; y: 8; width: parent.width - 40 - 12; spacing: 2
                                Txt { width: parent.width - role.width - 10; elide: Text.ElideRight; wrapMode: Text.NoWrap; font.pixelSize: 13; font.letterSpacing: -0.05
                                    font.weight: row.lit ? Theme.wSemi : Theme.wMedium; text: row.e.label
                                    color: row.lit ? Theme.datum : row.e.state === "n/a" ? Theme.ink3 : Theme.ink }
                                // the headline in mono, with the class of evidence it rests on; why, when it cannot run
                                Txt { objectName: "benchHeadline"; width: parent.width; visible: text !== ""; mono: true; font.pixelSize: 11; tone: 3; elide: Text.ElideRight; wrapMode: Text.Wrap; maximumLineCount: 2
                                    text: row.e.state === "unavailable" || row.e.state === "n/a" ? (row.e.why || "")
                                        : row.e.state === "failed" ? ((row.e.error && row.e.error.message) || "failed")
                                        : row.e.headline ? row.e.headline + (row.e.evidence ? "  ·  " + row.e.evidence.replace(/-/g, "-\u2060") : "") : ""   // a word joiner: "B-rep" never breaks at its hyphen
                                    color: row.e.state === "failed" ? Theme.signal : Theme.ink3
                                    opacity: row.e.state === "stale" ? 0.75 : 1 } }
                            // the state, lettered in neutral mono; the run mark takes its place under the pointer
                            Txt { id: role; objectName: "benchState"; anchors.right: parent.right; anchors.rightMargin: 12; y: (34 - height) / 2; mono: true; font.pixelSize: 10; font.weight: Theme.wMedium
                                font.letterSpacing: 1.0; font.capitalization: Font.AllUppercase; wrapMode: Text.NoWrap
                                text: root.stateText(row.e); color: row.e.state === "running" ? Theme.datum : row.e.state === "stale" ? Theme.amber : row.e.state === "failed" ? Theme.signal : Theme.ink3
                                opacity: go.visible ? 0 : 1 }
                            Item { id: go; objectName: "benchRun"; anchors.right: parent.right; anchors.rightMargin: 8; y: 5; width: 24; height: 24
                                visible: rm.containsMouse && row.e.state !== "running" && row.e.state !== "n/a" && row.e.state !== "unavailable"
                                Rectangle { anchors.fill: parent; radius: 7; color: gm.containsMouse ? Theme.plate4 : Theme.plate3 }
                                Icon { anchors.centerIn: parent; size: 12; color: Theme.ink
                                    name: row.e.by === "agent" ? "sparkles" : row.e.by === "person" ? "arrow_right" : row.e.state === "current" ? "rotate_ccw" : "play" }
                                MouseArea { id: gm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: Store.runStudy(row.e.id, row.e.state === "current") } }
                            MouseArea { id: rm; anchors.fill: parent; z: -1; hoverEnabled: true
                                cursorShape: row.e.state === "n/a" || row.e.state === "running" ? Qt.ArrowCursor : Qt.PointingHandCursor
                                onClicked: root.act(row.e) }
                            Tip { show: rm.containsMouse && !go.visible; text: row.e.doc + (row.e.note ? "\n" + row.e.note : "")
                                + (row.e.by === "agent" ? "\nYour agent does this: it looks, then records it." : row.e.by === "person" ? "\nOnly you can do this." : "") }
                            Tip { show: gm.containsMouse; text: row.e.by === "agent" ? "Ask your agent" : row.e.by === "person" ? "Go to the release" : row.e.state === "current" ? "Run again" : "Run" }
                        }
                    }
                }
            }
            Item { width: 1; height: 6 }
        }
    }
    // what does not apply to this design: one quiet line, open on click
    Item { width: parent.width; height: root.na.length ? 30 : 0; visible: root.na.length > 0
        Txt { objectName: "benchNa"; x: 40; anchors.verticalCenter: parent.verticalCenter; font.pixelSize: 12; tone: 3
            text: (root.showNa ? "Hide " : "") + root.na.length + " that do not apply to this design" }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.showNa = !root.showNa } }
    Item { width: 1; height: 4 }
}
