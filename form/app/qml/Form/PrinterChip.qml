import QtQuick

// What a design made for printing will print on; opens the printer picker. It sits in the top bar in every stage, and
// only while Store.printUi (printing is on and the open design is for printing): a 3D model never names a printer.
Item {
    id: pc
    objectName: "printerChip"
    property bool roomy: false                  // room for the filament too
    width: row.implicitWidth + 22; height: 26
    visible: Store.printUi
    Rectangle { anchors.fill: parent; radius: height / 2; color: cm.pressed ? Theme.washPress : cm.containsMouse ? Theme.washHover : "transparent"
        Behavior on color { Tint {} } }
    Row { id: row; x: 11; spacing: 7; anchors.verticalCenter: parent.verticalCenter
        Icon { name: "printer"; size: 13; anchors.verticalCenter: parent.verticalCenter; color: Store.printing.available ? Theme.ink3 : Theme.amber }
        Txt { kind: "fine"; anchors.verticalCenter: parent.verticalCenter; color: Theme.ink2
            width: Math.min(implicitWidth, 200); elide: Text.ElideRight; wrapMode: Text.NoWrap
            text: Store.printing.available ? Store.printing.presets.machine.name : "No slicer" }
        Txt { kind: "fine"; tone: 3; anchors.verticalCenter: parent.verticalCenter; visible: Store.printing.available && pc.roomy
            width: Math.min(implicitWidth, 130); elide: Text.ElideRight; wrapMode: Text.NoWrap
            text: Store.printing.available ? Store.printing.presets.filament.name : "" } }
    MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Store.openSheet("printer") }
    Tip { show: cm.containsMouse
        text: Store.printing.available ? (Store.printing.label || "Slicer") + (Store.printing.version ? " " + Store.printing.version : "") + " · " + Store.printing.presets.machine.name + " · " + Store.printing.presets.filament.name + " · " + Store.printing.presets.process.name + ". Click to choose the printer."
            : "No slicer was found. Click to see which Form Studio can use." }
}
