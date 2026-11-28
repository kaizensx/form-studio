import QtQuick

// One row of the Bench (direction I, decision 4): the same grammar for a feature, a study, a route and a document.
//   a state dot · a name · a number · the word that says how the number is known
// state: "ok" | "warn" | "fail" | "none" (not run: a ring) | "live". A row that cannot run is `dim` and says why in
// place of the number (`need`). The selected row is on raised glass with its evidence word lit.
//
// A row that has something to say before it is run opens in place (140 ms, the list above does not move): what you
// get, what you give, what it needs, the exact request that Run sends, and the button. A row with none of these is a
// plain button. While the pointer is on a row, the feature it is about (`lights`) is lit on the part.
Item {
    id: br
    property string state: "none"
    property string name: ""
    property string value: ""
    property string evidence: ""
    property string need: ""             // why a row that cannot run cannot (shown in place of the number)
    property bool dim: false
    property bool selected: false
    property bool chevron: false         // the row leads back: a ‹ in the gutter
    property string gets: ""             // You get
    property string gives: ""            // You give
    property string needs: ""            // Needs (an engine, another app, a release…)
    property string request: ""          // the exact request Run makes: an engine call or what is put to the agent
    property string action: ""           // the button's word; empty: no button
    property bool busy: false
    property string lights: ""           // a feature id: lit on the part while the pointer is on the row
    property bool open: false
    readonly property bool opens: gets !== "" || gives !== "" || needs !== "" || request !== ""
    signal clicked()                     // a plain row was clicked
    signal run()                         // the opened row's button
    width: parent ? parent.width : 0
    height: 32 + detail.height
    readonly property color dot: state === "ok" ? Theme.pass : state === "warn" ? Theme.amber : state === "fail" ? Theme.signal : state === "live" ? Theme.datum : Theme.ink3
    Rectangle { width: parent.width; height: br.height; radius: 10; visible: br.open; color: Theme.alpha(Theme.lineBase, Theme.dark ? 0.05 : 0.04) }
    Rectangle { width: parent.width; height: 32; radius: 10
        color: br.selected || br.open ? Theme.glass2 : bm.pressed ? Theme.washPress : bm.containsMouse ? Theme.washHover : "transparent"
        Behavior on color { Tint {} } }
    Item { x: 28; width: 22; height: 32; opacity: br.dim ? 0.5 : 1
        Icon { visible: br.chevron; anchors.centerIn: parent; name: "chevron_left"; size: 13; color: Theme.ink3 }
        Rectangle { visible: !br.chevron; anchors.centerIn: parent; width: 6; height: 6; radius: 3
            color: br.state === "none" ? "transparent" : br.dot; border.width: br.state === "none" ? 1 : 0; border.color: Theme.ink3 } }
    Txt { id: nm; x: 58; y: (32 - height) / 2; text: br.name; font.weight: br.selected || br.open ? Theme.wSemi : Theme.wMedium; opacity: br.dim ? 0.5 : 1
        width: Math.max(40, tail.x - x - 8); elide: Text.ElideRight; wrapMode: Text.NoWrap }
    Row { id: tail; anchors.right: parent.right; anchors.rightMargin: 10; y: (32 - height) / 2; spacing: 9
        Txt { visible: text !== ""; mono: true; font.pixelSize: 11; font.weight: Theme.wMedium; tone: 2; text: br.need !== "" ? "" : br.value; opacity: br.dim ? 0.5 : 1; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap }
        Ev { visible: text !== ""; text: br.need !== "" ? "" : br.evidence; lit: br.selected || br.open; anchors.verticalCenter: parent.verticalCenter }
        Txt { objectName: "rowNeed"; visible: text !== ""; font.pixelSize: 11; tone: 3; text: br.need; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap } }
    MouseArea { id: bm; width: parent.width; height: 32; hoverEnabled: true
        onClicked: { if (br.opens) br.open = !br.open; else br.clicked() }
        onContainsMouseChanged: if (br.lights !== "" && Store.viewer) Store.viewer.hovered = containsMouse ? br.lights : (Store.viewer.hovered === br.lights ? "" : Store.viewer.hovered) }

    // the row, opened in place
    Item { id: detail; y: 32; width: parent.width; clip: true
        height: br.open ? dcol.implicitHeight + 16 : 0
        Behavior on height { NumberAnimation { duration: Theme.move(Theme.rowOpen); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeMode } }
        opacity: br.open ? 1 : 0; visible: height > 0.5
        Behavior on opacity { NumberAnimation { duration: Theme.rowOpen } }
        Column { id: dcol; objectName: "rowDetail"; x: 58; y: 6; width: parent.width - 58 - 12; spacing: 7
            Repeater { model: [["You get", br.gets], ["You give", br.gives], ["Needs", br.needs]].filter(function (r) { return r[1] !== "" })
                Item { required property var modelData; width: dcol.width; height: Math.max(16, dv.implicitHeight)
                    Txt { kind: "fine"; tone: 3; text: modelData[0]; width: 58; wrapMode: Text.NoWrap }
                    Txt { id: dv; x: 62; width: parent.width - 62; kind: "fine"; tone: 2; text: modelData[1] } } }
            Rectangle { visible: br.request !== ""; width: dcol.width; height: rq.implicitHeight + 14; radius: 8; color: Theme.glassWell
                Txt { id: rq; objectName: "rowRequest"; x: 9; y: 7; width: parent.width - 18; mono: true; font.pixelSize: 11; tone: 2; text: br.request; wrapMode: Text.WrapAnywhere } }
            Btn { objectName: "rowRun"; visible: br.action !== ""; small: true; kind: "primary"; text: br.action; enabled: !br.dim; busy: br.busy; onClicked: br.run() } } }
}
