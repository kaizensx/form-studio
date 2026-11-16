import QtQuick

Column {
    id: tc
    spacing: 8; width: 340
    Repeater {
        model: Store.toasts
        Rectangle {
            id: t
            required property var modelData
            width: tc.width; height: tcol.implicitHeight + 20; radius: Theme.rMd
            color: Theme.plate3; border.color: modelData.bad ? Theme.alpha(Theme.signal, 0.5) : Theme.rule2
            Column { id: tcol; x: 12; y: 10; width: parent.width - 24; spacing: 2
                Txt { text: t.modelData.msg; width: parent.width; font.weight: 600; color: t.modelData.bad ? "#ffc4b6" : Theme.ink }
                Txt { kind: "fine"; visible: t.modelData.hint !== ""; text: t.modelData.hint; width: parent.width; color: Theme.ink2 } }
            Timer { running: true; interval: t.modelData.bad ? 7000 : 3400; onTriggered: Store.dropToast(t.modelData.id) }
            NumberAnimation on opacity { from: 0; to: 1; duration: 200 }
            transform: Translate { id: tt; NumberAnimation on y { from: 8; to: 0; duration: 220; easing.type: Easing.OutCubic } }
            MouseArea { anchors.fill: parent; onClicked: Store.dropToast(t.modelData.id) }
        }
    }
}
