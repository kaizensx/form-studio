import QtQuick

Text {
    id: ic
    property string name: "dot"
    property int size: 15
    // "loader_circle" is drawn as the animated mark (Spinner), held upright if a caller still rotates the icon
    readonly property bool loading: name === "loader_circle"
    text: loading ? "" : (Icons.map[name] || "")
    font.family: Theme.icons
    font.pixelSize: size
    color: Theme.ink2
    width: size; height: size
    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
    Loader { active: ic.loading; anchors.centerIn: parent; rotation: -ic.rotation
        sourceComponent: Spinner { size: ic.size; color: ic.color } }
}
