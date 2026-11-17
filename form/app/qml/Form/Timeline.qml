import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Revision timeline: one tick per revision, hover for a live thumbnail, drag to scrub, play to morph through them.
// Scrubbing only looks (the engine's /view?rev=); "Branch from here" checks that revision out.
// It is the history row of the workspace's bottom strip, above the pipeline (which is "now"). The picture
// cross-fades through the viewport's own swap (Store.fadeTo); the "viewing only" notice is drawn by the workspace.
Item {
    id: tl
    objectName: "timeline"
    property bool narrow: width < 620
    readonly property var revs: Store.revList
    readonly property int headRev: Store.project ? Store.project.head : 0
    readonly property int current: Store.scrub ? Store.scrub.rev : headRev
    readonly property var released: Store.project ? Store.project.approvals.map(function (a) { return a.rev }) : []
    readonly property int hover: Store.tlHover   // index into revs under the pointer
    property bool exporting: false
    function rev(i) { return i >= 0 && i < revs.length ? revs[i] : null }
    function indexOf(n) { for (var i = 0; i < revs.length; i++) if (revs[i].n === n) return i; return -1 }
    implicitHeight: 40

    Btn { id: play; objectName: "timelinePlay"; x: 8; anchors.verticalCenter: parent.verticalCenter; small: true; kind: "quiet"
        icon: Store.morphing ? "pause" : "play"; enabled: tl.revs.length > 1
        tip: tl.revs.length > 1 ? "Play through every revision" : "There is only one revision"
        onClicked: Store.playMorph() }

    Item {
        id: track
        objectName: "timelineTrack"
        anchors.left: play.right; anchors.leftMargin: 10; anchors.right: side.left; anchors.rightMargin: 14     // the ticks get what the text leaves
        height: parent.height
        readonly property real gap: tl.revs.length > 1 ? Math.min(46, Math.max(3, (width - 28) / (tl.revs.length - 1))) : 0
        function tickX(i) { return 14 + i * gap }
        function at(mx) { return gap > 0 ? Math.max(0, Math.min(tl.revs.length - 1, Math.round((mx - 14) / gap))) : 0 }
        Rectangle { x: 14; y: Math.round(parent.height / 2); width: Math.max(0, track.tickX(tl.revs.length - 1) - 14); height: 1; color: Theme.rule2 }
        // where the view is now
        Rectangle {
            readonly property int i: tl.indexOf(tl.current)
            visible: i >= 0; x: track.tickX(i) - 9; y: 7; width: 18; height: parent.height - 14; radius: Theme.rXs
            color: Theme.alpha(Store.scrub ? Theme.blueprint : Theme.datum, 0.14); border.color: Theme.alpha(Store.scrub ? Theme.blueprint : Theme.datum, 0.45)
            Behavior on x { enabled: !tm.pressed; NumberAnimation { duration: Motion.move(Motion.ui); easing.type: Easing.BezierSpline; easing.bezierCurve: Motion.out } }
        }
        Repeater {
            model: tl.revs
            Item {
                id: tick
                required property var modelData
                required property int index
                readonly property bool isHead: modelData.n === tl.headRev
                readonly property bool agent: (modelData.origin || "").indexOf("agent") === 0
                x: track.tickX(index) - 1; width: 2; height: track.height
                Rectangle { anchors.horizontalCenter: parent.horizontalCenter; anchors.verticalCenter: parent.verticalCenter
                    width: 2; height: tick.isHead ? 18 : tl.hover === tick.index ? 16 : 12; radius: 1
                    color: tick.isHead ? Theme.datum : tl.hover === tick.index ? Theme.ink : Theme.ink3 }
                // made by an agent: a ring above the tick (shape, not colour)
                Rectangle { visible: tick.agent; anchors.horizontalCenter: parent.horizontalCenter; y: 5; width: 5; height: 5; radius: 2.5
                    color: "transparent"; border.color: Theme.ink2 }
                // released: settled evidence
                Rectangle { visible: tl.released.indexOf(tick.modelData.n) >= 0; anchors.horizontalCenter: parent.horizontalCenter; y: parent.height - 9
                    width: 4; height: 4; radius: 2; color: Theme.pass }
            }
        }
        MouseArea {
            id: tm
            anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
            onPositionChanged: function (e) {
                var i = track.at(e.x); Store.tlHover = i
                if (pressed && tl.rev(i) && tl.rev(i).n !== tl.current) { Store.stopMorph(); Store.showRev(tl.rev(i).n, false) }
            }
            onPressed: function (e) { var i = track.at(e.x); Store.tlHover = i; Store.stopMorph(); if (tl.rev(i) && tl.rev(i).n !== tl.current) Store.showRev(tl.rev(i).n, true) }
            onExited: Store.tlHover = -1
        }
    }

    Row {
        id: side; anchors.right: parent.right; anchors.rightMargin: 8; anchors.verticalCenter: parent.verticalCenter; spacing: 4
        readonly property var r: tl.rev(tl.hover >= 0 ? tl.hover : tl.indexOf(tl.current))
        Txt { mono: true; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter; text: side.r ? F.pad(side.r.n) : ""
            color: side.r && side.r.n === tl.headRev ? Theme.datum : Theme.ink }
        Txt { font.pixelSize: 12; tone: 2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; visible: !tl.narrow
            text: side.r ? "by " + Store.who(side.r.origin) + " · " + F.ago(side.r.ts) : "" }
        Txt { font.pixelSize: 12; tone: 3; anchors.verticalCenter: parent.verticalCenter; width: Math.min(implicitWidth, Math.max(60, tl.width * 0.14)); elide: Text.ElideRight; wrapMode: Text.NoWrap
            visible: !tl.narrow; text: side.r ? (side.r.summary || side.r.note || "") : "" }
        Item { width: 6; height: 1 }
        Btn { small: true; kind: Store.scrub ? "default" : "quiet"; icon: "git_branch"; text: tl.narrow ? "" : "Branch from here"; anchors.verticalCenter: parent.verticalCenter
            enabled: !!Store.scrub && !Store.hasDraft && !Store.morphing
            tip: Store.hasDraft ? "Commit or discard the draft first" : "Branch from here: make this revision the head. Nothing is deleted; later revisions stay."
            onClicked: Store.branchFrom(Store.scrub.rev) }
        Btn { small: true; kind: "quiet"; icon: tl.exporting ? "loader_circle" : "film"; anchors.verticalCenter: parent.verticalCenter
            enabled: !tl.exporting && tl.revs.length > 1; tip: tl.exporting ? "Rendering every revision…" : "Export the history as a GIF or animated WebP"
            onClicked: { dlg.currentFolder = Bridge.downloads(); dlg.currentFile = Bridge.downloads() + "/" + Store.pid + "_history.gif"; Store.ask(dlg) } }
        Btn { small: true; kind: "quiet"; icon: "x"; anchors.verticalCenter: parent.verticalCenter; tip: "Close the timeline"
            onClicked: { Store.timelineOpen = false; Store.endScrub() } }
    }

    // ── hover card: that revision's real geometry, turning ──
    Rectangle {
        id: card
        readonly property var r: tl.rev(tl.hover)
        visible: tl.visible && !!r && r.n !== tl.current       // the revision on screen needs no preview (and the card would cover its notice)
        width: 204; height: 196; radius: Theme.rMd; color: Theme.plate2; border.color: Theme.rule2; z: 3
        x: Math.max(0, Math.min(tl.width - width, track.x + track.tickX(Math.max(0, tl.hover)) - width / 2))
        y: -height - 14
        onRChanged: mini.show(r ? r.n : 0)
        Rectangle { x: 6; y: 6; width: parent.width - 12; height: 118; radius: Theme.rSm; color: Theme.plate; clip: true
            Viewport {
                id: mini; anchors.fill: parent; lite: true; interactive: false; showDims: false; showCompanions: false; spin: card.visible; selected: "-"
                property int want: 0
                property bool ready: false
                opacity: ready ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Motion.ui } }
                function show(n) {
                    want = n
                    if (!n) return
                    ready = false
                    Store.loadRev(n).then(function (v) {
                        if (mini.want !== n) return
                        var c = Object.assign({}, v); c.companions = []; c.assembly = null
                        mini.setModel(c); mini.setView("iso", false); mini.dist *= 0.56; mini.ready = true
                    }, function () {})
                }
            } }
        Column { x: 10; y: 130; width: parent.width - 20; spacing: 2
            Row { spacing: 6
                Txt { mono: true; font.pixelSize: 12; text: card.r ? F.pad(card.r.n) : ""; color: card.r && card.r.n === tl.headRev ? Theme.datum : Theme.ink }
                Txt { font.pixelSize: 12; tone: 2; text: card.r ? "by " + Store.who(card.r.origin) : "" }
                Tag { visible: !!card.r && card.r.n === tl.headRev; text: "head"; kind: "interface"; anchors.verticalCenter: parent.verticalCenter }
                Tag { visible: !!card.r && tl.released.indexOf(card.r.n) >= 0; text: "released"; kind: "PASS"; anchors.verticalCenter: parent.verticalCenter } }
            Txt { kind: "fine"; width: parent.width; maximumLineCount: 2; elide: Text.ElideRight
                text: card.r ? F.ago(card.r.ts) + " · " + (card.r.summary || card.r.note || "") : "" } }
    }

    FileDialog {
        id: dlg
        title: "Export the revision history"; fileMode: FileDialog.SaveFile
        nameFilters: ["GIF (*.gif)", "Animated WebP (*.webp)"]
        onAccepted: {
            var target = selectedFile, webp = /\.webp$/i.test(String(target))
            tl.exporting = true
            Store.ppost("/history_export", { format: webp ? "webp" : "gif" }).then(function (r) {
                tl.exporting = false
                if (Bridge.save("/projects/" + Store.pid + "/file/share/" + r.name, target)) {
                    Store.toast("History exported", F.plural(r.revisions.length, "revision") + ", " + Math.round(r.bytes / 1024) + " kB"
                        + (r.skipped.length ? " · " + r.skipped.length + " did not build and were left out" : ""))
                    Bridge.reveal(target)
                } else Store.toast("Could not save the file", "Check that the folder is writable.", true)
            }, function (e) { tl.exporting = false; Store.fail(e) })
        }
    }
}
