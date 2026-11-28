import QtQuick

// The shading chip under the view cube: what the part stands on. Today that is the studio floor or the build plate of
// a design made for printing, the floor's 10 mm grid and the overall dimensions; the shading modes of the 3D view will
// be listed here when they exist. A clay ball, the name of what is on, and a menu.
Glass {
    id: sc
    objectName: "shadeChip"
    height: 32; radius: 16; width: row.implicitWidth + 19
    readonly property bool plate: Store.stageMode === "plate"
    // a design made for printing shows the plate in Check and Make anyway; in Design and Document it is a choice
    readonly property bool plateChoice: Store.printUi && Store.mode !== "prove" && Store.mode !== "release"
    readonly property alias menu: menu
    Rectangle { anchors.fill: parent; anchors.margins: 3; radius: height / 2; color: sm.pressed ? Theme.washPress : sm.containsMouse || menu.opened ? Theme.washHover : "transparent"
        Behavior on color { Tint {} } }
    Row { id: row; x: 9; anchors.verticalCenter: parent.verticalCenter; spacing: 7
        // the clay ball: the part's own material under the key light
        Rectangle { width: 14; height: 14; radius: 7; anchors.verticalCenter: parent.verticalCenter
            gradient: Gradient { GradientStop { position: 0; color: "#f1ece2" } GradientStop { position: 0.7; color: "#a39d92" } GradientStop { position: 1; color: "#5e5a54" } } }
        Txt { objectName: "shadeName"; font.pixelSize: 12; tone: 2; text: sc.plate ? "Plate" : "Studio"; anchors.verticalCenter: parent.verticalCenter; wrapMode: Text.NoWrap }
        Icon { name: "chevron_down"; size: 12; color: Theme.ink3; anchors.verticalCenter: parent.verticalCenter } }
    MouseArea { id: sm; anchors.fill: parent; hoverEnabled: true; onClicked: menu.opened ? menu.close() : menu.open() }
    Tip { show: sm.containsMouse && !menu.opened; below: true; text: sc.plate ? "On the build plate" : "On the studio floor" }
    PopMenu { id: menu; y: parent.height + 8; x: parent.width - width; width: 252
        model: [
            { name: "showPlate", icon: "printer", text: "Build plate" + (Store.printing.available ? ": " + Store.printing.presets.machine.name : ""),
              checked: Store.showPlate || (Store.printUi && !sc.plateChoice), enabled: sc.plateChoice, run: function () { Store.showPlate = !Store.showPlate } },
            { name: "floorGrid", icon: "grid_3x3", text: "Floor grid, a line every 10 mm", checked: Store.floorGrid && !Store.plateWanted, enabled: !Store.plateWanted,
              run: function () { Store.floorGrid = !Store.floorGrid } },
            { sep: true },
            { name: "showDims", icon: "ruler", text: "Overall dimensions", checked: Store.dims, run: function () { Store.toggleDims() } }
        ].filter(function (e) { return e.name !== "showPlate" || Store.printUi }) }
}
