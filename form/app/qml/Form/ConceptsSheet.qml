import QtQuick
import QtQuick.Controls
import "F.js" as F

// Concepts: the agent's genuinely different answers to one idea, each a real design built in the kernel, side by
// side and turning. Pick one to continue with it in the workspace, or say in words what to mix ("the base of A, the
// hook of C") and the agent builds the mix as one more concept. Sizes and volumes are computed from each solid.
//   Store.openSheet("concepts", { group: "<gid>" })
Item {
    id: cs
    objectName: "conceptsSheet"
    readonly property var props: Store.sheet && Store.sheet.props ? Store.sheet.props : ({})
    readonly property var listed: { var l = Store.concepts; for (var i = 0; i < l.length; i++) if (l[i].id === props.group) return l[i]; return l.length ? l[0] : null }
    property var board: null                 // GET /concepts/<gid>: the members with their computed numbers
    readonly property var g: board && listed && board.id === listed.id && board.members.length >= listed.members.length ? board : listed
    function loadBoard() { if (listed) Store.get("/concepts/" + listed.id).then(function (r) { cs.board = r }, function () {}) }
    onListedChanged: loadBoard()
    Component.onCompleted: loadBoard()
    readonly property var members: g ? g.members.filter(function (m) { return !m.error }) : []
    readonly property var failed: g ? g.members.filter(function (m) { return !!m.error }) : []
    property string title: g ? g.name : "Concepts"
    property string note: g ? F.plural(members.length, "concept") + ", each built as real CAD. Pick one to keep designing it." : ""
    property int sheetWidth: Math.max(Theme.sheetXl, Math.min(1320, members.length * 300 + 60))
    implicitHeight: col.implicitHeight
    property string hot: ""
    property bool keep: false
    function accept() { if (mix.text.trim()) Store.mixConcepts(g.id, mix.text) }

    property Component footerLeft: Component { Row { spacing: 8
        Check { checked: cs.keep; onToggled: function (c) { cs.keep = c }; anchors.verticalCenter: parent.verticalCenter }
        Txt { kind: "fine"; tone: 2; anchors.verticalCenter: parent.verticalCenter; text: "Keep the other concepts as designs"
            MouseArea { anchors.fill: parent; onClicked: cs.keep = !cs.keep } }
        Txt { kind: "fine"; tone: 4; anchors.verticalCenter: parent.verticalCenter; visible: !cs.keep; text: "(otherwise they go to .trash, recoverable)" } } }
    // none of them, for now or for good: close without a pick
    property Component footer: Component { Row { spacing: 8
        Btn { objectName: "conceptsNotNow"; kind: "quiet"; text: "Not now"; tip: "Close; the concepts wait on Home"; onClicked: Store.sheet = null }
        Btn { objectName: "conceptsKeepAll"; icon: "copy_plus"; text: "Keep all"; tip: "Every concept becomes a design of its own"
            enabled: !!cs.g; onClicked: run(function () { return Store.dismissConcepts(cs.g.id, "all") }) }
        Btn { objectName: "conceptsDiscardAll"; kind: "danger"; icon: "trash_2"; text: "Discard all"; tip: "Move every concept to .trash (recoverable)"
            enabled: !!cs.g; onClicked: run(function () { return Store.dismissConcepts(cs.g.id, "none") }) } } }

    Column {
        id: col; width: parent.width; spacing: 18
        Row {
            id: cards; spacing: 14; width: parent.width
            readonly property real cw: Math.floor((width - (cs.members.length - 1) * spacing) / Math.max(1, cs.members.length))
            Repeater { model: cs.members
                Rectangle {
                    id: c; objectName: "conceptCard"; required property var modelData; required property int index
                    readonly property bool on: cs.hot === modelData.project
                    width: cards.cw; height: 440; radius: Theme.rLg + 2
                    color: on || ch.hovered ? Theme.glass2 : Theme.glass; border.color: on ? Theme.alpha(Theme.datum, 0.7) : "transparent"
                    Behavior on border.color { Tint {} }
                    opacity: 0; Component.onCompleted: cIn.start()
                    SequentialAnimation { id: cIn; PauseAnimation { duration: 60 + c.index * 90 }
                        ParallelAnimation { Glide { target: c; property: "opacity"; to: 1; duration: Theme.slow } Glide { target: ctr; property: "y"; from: Theme.shift(16); to: 0; duration: 420 } } }
                    transform: Translate { id: ctr }
                    HoverHandler { id: ch; onHoveredChanged: if (hovered) cs.hot = c.modelData.project }
                    Item { x: 1; y: 1; width: parent.width - 2; height: 240; clip: true
                        MiniView { anchors.fill: parent; projectId: c.modelData.project; turning: true } }
                    Rectangle { x: 14; y: 14; width: 30; height: 30; radius: 15; color: c.on ? Theme.datum : Theme.alpha(Theme.plate, 0.9); border.color: c.on ? Theme.datum : Theme.rule2
                        Txt { anchors.centerIn: parent; text: c.modelData.letter; font.weight: Theme.wBold; color: c.on ? Theme.datumInk : Theme.ink } }
                    Rectangle { y: 241; x: 1; width: parent.width - 2; height: 1; color: Theme.rule }
                    Column { x: 16; y: 256; width: parent.width - 32; spacing: 6
                        Txt { text: c.modelData.title; font.weight: Theme.wSemi; font.pixelSize: Theme.tLead; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                        Txt { kind: "fine"; tone: 2; width: parent.width; text: c.modelData.rationale; maximumLineCount: 3; elide: Text.ElideRight; lineHeight: 1.35 }
                        Item { width: 1; height: 2 }
                        Row { spacing: 14; visible: !!c.modelData.numbers
                            Column { spacing: 1
                                Txt { kind: "cap"; text: "Size" }
                                Txt { mono: true; font.pixelSize: 12; text: c.modelData.numbers && c.modelData.numbers.size_mm ? c.modelData.numbers.size_mm.map(function (v) { return F.fmt(v, 0) }).join(" × ") + " mm" : "—" } }
                            Column { spacing: 1
                                Txt { kind: "cap"; text: "Volume" }
                                Txt { mono: true; font.pixelSize: 12; text: c.modelData.numbers && c.modelData.numbers.volume_cm3 !== undefined ? F.fmt(c.modelData.numbers.volume_cm3, 1) + " cm³" : "—" } }
                            Column { spacing: 1; objectName: "conceptMass"
                                Txt { kind: "cap"; text: "Mass" }
                                Txt { mono: true; font.pixelSize: 12; text: c.modelData.numbers && c.modelData.numbers.mass_g !== undefined ? F.fmt(c.modelData.numbers.mass_g, c.modelData.numbers.mass_g < 100 ? 1 : 0) + " g" : "—" } } }
                        // the material the mass is for, and how it is known: chosen, or assumed when the concept has none
                        Row { spacing: 8; visible: !!c.modelData.numbers; width: parent.width
                            readonly property var mat: c.modelData.numbers ? c.modelData.numbers.material : null
                            readonly property bool assumed: !!mat && String(mat.why || "").indexOf("assumed") === 0
                            Tag { id: ctag; text: "computed"; kind: "x"; tint: Theme.datum; anchors.verticalCenter: parent.verticalCenter }
                            Tag { visible: parent.assumed; text: "assumed"; kind: "x"; tint: Theme.amber; anchors.verticalCenter: parent.verticalCenter }
                            Txt { kind: "fine"; tone: 2; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap; elide: Text.ElideRight
                                width: parent.width - ctag.width - (parent.assumed ? 70 : 0) - 16
                                text: parent.mat ? "in " + parent.mat.label + (parent.mat.density_kg_m3 ? " · " + F.fmt(parent.mat.density_kg_m3, 0) + " kg/m³" : "") + (parent.mat.kind === "filament" ? ", solid" : "")
                                    : "no material: no mass" } } }
                    Btn { objectName: "conceptPick"; anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 14
                        kind: c.on ? "primary" : "default"; icon: "check"; text: "Continue with " + c.modelData.letter
                        onClicked: run(function () { return Store.pickConcept(cs.g.id, c.modelData.project, cs.keep) }) }
                    MouseArea { anchors.fill: parent; z: -1; onDoubleClicked: Store.pickConcept(cs.g.id, c.modelData.project, cs.keep) }
                } } }
        Note { visible: cs.failed.length > 0; width: parent.width; kind: "amber"; title: F.plural(cs.failed.length, "concept") + " did not build"
            text: cs.failed.map(function (m) { return m.letter + " " + m.title + ": " + m.error }).join("\n") }
        // a mix, in words
        Rectangle { width: parent.width; height: 56; radius: Theme.rLg; color: Theme.glass; border.color: mix.input.activeFocus ? Theme.alpha(Theme.datum, 0.5) : "transparent"
            Icon { x: 16; name: "merge"; size: 16; color: Theme.datum; anchors.verticalCenter: parent.verticalCenter }
            Field { id: mix; objectName: "conceptMix"; bare: true; x: 42; width: parent.width - 42 - mixGo.width - 24; anchors.verticalCenter: parent.verticalCenter
                placeholder: "Or mix them in words: the base of A with the hook of C, 10 mm taller"
                onAccepted: function (t) { if (t.trim()) Store.mixConcepts(cs.g.id, t) } }
            Btn { id: mixGo; objectName: "conceptMixSend"; anchors.right: parent.right; anchors.rightMargin: 10; anchors.verticalCenter: parent.verticalCenter
                icon: "sparkles"; text: "Ask for the mix"; enabled: mix.text.trim() !== "" && Store.chatReady && !Store.chatBusy
                tip: Store.chatBusy ? "The agent is still answering" : "The agent builds the mix as one more concept here"
                onClicked: Store.mixConcepts(cs.g.id, mix.text) } }
    }
}
