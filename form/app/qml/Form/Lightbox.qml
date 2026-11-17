import QtQuick

// An image shown large over the window (a render the agent looked at, an attached photo). Click or Esc closes.
Item {
    id: lb
    anchors.fill: parent; z: 70
    readonly property bool open: !!Store.lightbox
    property var last: null
    onOpenChanged: if (open) last = Store.lightbox
    visible: bg.opacity > 0.001
    Rectangle { id: bg; anchors.fill: parent; color: Theme.alpha(Theme.well, 0.9); opacity: lb.open ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: lb.open ? Theme.base : Theme.exit } } }
    MouseArea { anchors.fill: parent; hoverEnabled: true; onClicked: Store.lightbox = null; onWheel: function (w) { w.accepted = true } }
    Item {
        anchors.fill: parent; anchors.margins: 56; anchors.bottomMargin: 84
        opacity: lb.open ? 1 : 0; scale: lb.open ? 1 : Theme.from(0.97)
        Behavior on opacity { NumberAnimation { duration: lb.open ? Theme.base : Theme.exit } }
        Behavior on scale { Glide { duration: lb.open ? Theme.base : Theme.exit } }
        Rectangle { anchors.centerIn: parent; width: im.paintedWidth + 2; height: im.paintedHeight + 2; radius: Theme.rMd; color: Theme.plate1; border.color: Theme.rule2
            visible: im.status === Image.Ready
            Shadow { radius: parent.radius; spread: 40; drop: 16 } }
        Image { id: im; anchors.fill: parent; fillMode: Image.PreserveAspectFit; asynchronous: true; mipmap: true; source: lb.last ? lb.last.url : "" }
        Spinner { anchors.centerIn: parent; visible: im.status === Image.Loading; size: 18 }
        Txt { anchors.centerIn: parent; visible: im.status === Image.Error; tone: 2; text: "This image is no longer on disk." }
    }
    Column { anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 26; spacing: 3; opacity: lb.open ? 1 : 0
        Txt { anchors.horizontalCenter: parent.horizontalCenter; font.weight: Theme.wMedium; text: lb.last ? lb.last.caption : "" }
        Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "fine"; text: lb.last && lb.last.note ? lb.last.note : "Click anywhere or press Esc to close" } }
    Btn { kind: "quiet"; icon: "x"; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 16; anchors.topMargin: 56; visible: lb.open; onClicked: Store.lightbox = null }
}
