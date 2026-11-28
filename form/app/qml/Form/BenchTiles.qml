import QtQuick
import "F.js" as F
import "BenchTiles.js" as BT

// The Bench sheet as tiles (the list's other look): each chapter (Design, Check, Make, Document) is a band, tiled in
// Analysis, Manufacturing and Documents. A tile is an icon and a short name, one plain sentence of what you get, our
// state dot with its number and evidence word (or the state in words), and Run. A click selects it: the sheet's foot
// opens it with the exact request, as in the list. Everything about state is the engine's entry (form/studies.py).
Column {
    id: bt
    objectName: "benchTiles"
    property string find: ""
    property string only: ""
    readonly property var b: Store.bench && Store.bench.project === Store.pid ? Store.bench : null
    readonly property int cols: Math.max(2, Math.floor((width + gap) / (186 + gap)))
    readonly property int gap: 10
    readonly property real tw: Math.floor((width - (cols - 1) * gap) / cols)
    function keep(e) {
        if (e.state === "n/a" && only !== "needs") return false
        if (only !== "" && Store.benchClass(e) !== only) return false
        if (find !== "") { var q = find.toLowerCase(); if ((e.label + " " + e.doc + " " + e.id + " " + BT.info(e).say).toLowerCase().indexOf(q) < 0) return false }
        return true
    }
    function bands() {
        var es = b ? b.entries.filter(keep) : [], out = []
        ;["design", "check", "make", "document"].forEach(function (ch) {
            var mine = es.filter(function (e) { return Store.benchChapter(e) === ch })
            if (!mine.length) return
            var groups = BT.ORDER.map(function (g) { return { name: g, entries: mine.filter(function (e) { return BT.info(e).group === g }) } })
                                  .filter(function (g) { return g.entries.length > 0 })
            out.push({ chapter: ch, count: mine.length, groups: groups })
        })
        return out
    }
    readonly property var model: (b, find, only, bands())
    spacing: 18

    Repeater { model: bt.model
        Column { id: band; required property var modelData; objectName: "tilesBand-" + modelData.chapter; width: bt.width; spacing: 8
            Item { width: parent.width; height: 24
                Txt { id: bn; anchors.verticalCenter: parent.verticalCenter; font.weight: Theme.wSemi; font.pixelSize: 14
                    text: ({ design: "Design", check: "Check", make: "Make", document: "Document" })[band.modelData.chapter] }
                Txt { anchors.left: bn.right; anchors.leftMargin: 9; anchors.baseline: bn.baseline; kind: "fine"; tone: 3
                    text: ({ design: "shape it", check: "prove it", make: "produce it", document: "hand it over" })[band.modelData.chapter] }
                Txt { anchors.right: parent.right; anchors.baseline: bn.baseline; mono: true; font.pixelSize: 11; tone: 3; text: String(band.modelData.count) } }
            Repeater { model: band.modelData.groups
                Column { id: grp; required property var modelData; width: band.width; spacing: 6
                    Txt { kind: "cap"; text: grp.modelData.name; visible: band.modelData.groups.length > 1 || grp.modelData.name !== "Analysis" }
                    Flow { width: parent.width; spacing: bt.gap
                        Repeater { model: grp.modelData.entries
                            BenchTile { required property var modelData; e: modelData; width: bt.tw } } } } } } }
    Txt { visible: bt.model.length === 0; tone: 3; text: "Nothing matches." }

    component BenchTile: Rectangle {
        id: tile
        property var e: null
        readonly property var i: BT.info(e)
        readonly property bool off: e.state === "unavailable" || e.state === "n/a"
        readonly property bool sel: Store.benchSheetSel === e.id
        readonly property string dk: Store.benchDot(e)
        readonly property color dc: dk === "ok" ? Theme.pass : dk === "warn" || dk === "stale" ? Theme.amber : dk === "fail" ? Theme.signal : dk === "live" ? Theme.datum : Theme.ink3
        readonly property bool ring: dk === "none" || dk === "stale"
        readonly property string word: Store.benchWord(e)
        objectName: "tile-" + e.id
        height: 146; radius: 14
        color: sel ? Theme.glass2 : tm.pressed ? Theme.washPress : tm.containsMouse ? Theme.washHover : Theme.alpha(Theme.lineBase, Theme.dark ? 0.035 : 0.03)
        border.color: sel ? Theme.rule3 : Theme.rule
        Behavior on color { Tint {} }
        MouseArea { id: tm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Store.benchSheetSel = tile.e.id }
        Item { x: 12; y: 12; width: parent.width - 24; height: 26; opacity: tile.off ? 0.55 : 1
            Rectangle { width: 26; height: 26; radius: 8; color: Theme.alpha(Theme.lineBase, Theme.dark ? 0.07 : 0.06)
                Icon { anchors.centerIn: parent; name: tile.i.icon; size: 14; color: Theme.ink } }
            Txt { objectName: "tileName"; x: 36; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 36 - 14; font.weight: Theme.wSemi; elide: Text.ElideRight; wrapMode: Text.NoWrap; text: tile.i.short }
            Rectangle { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: 7; height: 7; radius: 3.5
                color: tile.ring ? "transparent" : tile.dc; border.width: tile.ring ? 1.5 : 0; border.color: tile.dc } }
        Txt { objectName: "tileSay"; x: 12; y: 46; width: parent.width - 24; kind: "fine"; tone: 2; maximumLineCount: 3; elide: Text.ElideRight; text: tile.i.say; opacity: tile.off ? 0.7 : 1 }
        // the foot: the number and how it is known, or the state in words; and Run
        Item { x: 12; y: parent.height - 34; width: parent.width - 24; height: 24
            Row { anchors.verticalCenter: parent.verticalCenter; spacing: 7; width: parent.width - run.width - 8; clip: true
                Txt { objectName: "tileValue"; visible: tile.word === "" && !!tile.e.headline; mono: true; font.pixelSize: 11; tone: 1; wrapMode: Text.NoWrap; elide: Text.ElideRight
                    width: Math.min(implicitWidth, parent.width - ev.width - 7); text: tile.e.headline || "" }
                Ev { id: ev; visible: tile.word === "" && text !== ""; text: Store.evWord(tile.e.evidence) }
                Txt { objectName: "tileState"; visible: tile.word !== ""; font.pixelSize: 11; wrapMode: Text.NoWrap; elide: Text.ElideRight; width: Math.min(implicitWidth, parent.width)
                    color: tile.e.state === "stale" ? Theme.amber : tile.e.state === "failed" ? Theme.signal : tile.e.state === "running" ? Theme.datum : Theme.ink3; text: tile.word } }
            Btn { id: run; objectName: "tileRun-" + tile.e.id; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; small: true; height: 24
                visible: !tile.off && tile.e.state !== "running"; kind: tile.e.state === "current" ? "quiet" : "default"
                icon: tile.e.by === "agent" ? "sparkles" : tile.e.by === "person" ? "arrow_right" : tile.e.state === "current" ? "rotate_ccw" : "play"
                text: tile.e.by === "agent" ? "Ask" : tile.e.by === "person" ? "Go" : tile.e.state === "current" ? "" : "Run"
                tip: tile.e.by === "agent" ? "Ask your agent" : tile.e.by === "person" ? "Go to the release" : tile.e.state === "current" ? "Run again" : "Run"
                onClicked: { var x = tile.e; if (x.by !== "engine") Store.benchOpen = false; Store.runStudy(x.id, x.state === "current") } } }
        Tip { show: tm.containsMouse && !run.hovered; text: tile.e.label + (tile.off && tile.e.why ? ". Needs: " + tile.e.why : "") }
    }
}
