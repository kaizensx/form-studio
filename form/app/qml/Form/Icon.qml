import QtQuick

Text {
    property string name: "dot"
    property int size: 15
    text: Icons.map[name] || ""
    font.family: Theme.icons
    font.pixelSize: size
    color: Theme.ink2
    width: size; height: size
    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter
}
