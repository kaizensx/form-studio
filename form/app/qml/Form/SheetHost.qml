import QtQuick
import QtQuick.Controls

// Modal sheets (new design, alternatives, photo measuring…). One at a time, centred, Esc closes.
Item {
    id: host
    anchors.fill: parent; z: 40
    visible: !!Store.sheet
    readonly property var files: ({ "new": "NewSheet.qml", alternatives: "Alternatives.qml", photo: "PhotoSheet.qml", ring: "RingSheet.qml", setup: "SetupSheet.qml", update: "UpdateSheet.qml" })
    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.5); opacity: host.visible ? 1 : 0; Behavior on opacity { NumberAnimation { duration: 160 } }
        MouseArea { anchors.fill: parent; onClicked: Store.openSheet(null); onWheel: function (w) { w.accepted = true } } }
    Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(parent.width - 80, ld.item && ld.item.sheetWidth ? ld.item.sheetWidth : 760)
        height: Math.min(parent.height - 80, (ld.item ? ld.item.implicitHeight : 200) + 64)
        radius: Theme.rLg; color: Theme.plate2; border.color: Theme.rule2
        scale: host.visible ? 1 : 0.97; Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        MouseArea { anchors.fill: parent }
        Txt { x: 22; y: 18; kind: "h3"; text: ld.item && ld.item.title ? ld.item.title : "" }
        Btn { kind: "quiet"; icon: "x"; anchors.right: parent.right; anchors.rightMargin: 10; y: 12; onClicked: Store.openSheet(null) }
        Flickable { x: 22; y: 54; width: parent.width - 44; height: parent.height - 64; clip: true; contentHeight: ld.item ? ld.item.implicitHeight : 0; boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { width: 6 }
            Loader { id: ld; width: parent.width; active: !!Store.sheet; source: Store.sheet ? (host.files[Store.sheet.kind] || "") : "" } }
    }
}
