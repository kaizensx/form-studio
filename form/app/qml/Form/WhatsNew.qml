import QtQuick
import FormNative

// What's New: the running version's section of the CHANGELOG shipped with the app (form/whatsnew.py). Opens by
// itself once after an update; Help → What's New opens it any time. Nothing is fetched from the network.
Column {
    id: wn
    objectName: "whatsNew"
    property string title: "What’s new"
    property string note: "Form Studio " + (n ? n.version : Bridge.version)
    property int sheetWidth: Theme.sheetM
    readonly property var n: Store.whatsNew
    readonly property var hl: n ? n.highlights || [] : []
    property bool full: hl.length === 0
    function accept() { Store.closeWhatsNew() }
    property Component footerLeft: Row { spacing: 4
        Btn { kind: "quiet"; icon: "scroll_text"; text: wn.full ? "Highlights" : "All the notes"; visible: wn.hl.length > 0; onClicked: wn.full = !wn.full }
        Btn { kind: "quiet"; icon: "external_link"; text: "Every release"; onClicked: Bridge.openLink("https://github.com/kaizensx/form-studio/releases") } }
    property Component footer: Row { spacing: 8
        Btn { objectName: "whatsNewDone"; kind: "primary"; text: "Continue"; keys: "Return"; onClicked: Store.closeWhatsNew() } }
    spacing: 18

    // the version, large, on a quiet band that catches the light
    Rectangle {
        id: band
        width: parent.width; height: 112; radius: Theme.rLg; color: Theme.glass; border.color: Theme.dark ? Theme.glassEdge : Theme.rule; clip: true
        // a datum grid that fades in from the left, behind the number
        Repeater { model: 14
            Rectangle { required property int index; x: band.width - 18 - index * 22; y: 0; width: 1; height: band.height
                color: Theme.alpha(Theme.datum, Math.max(0, 0.085 - 0.006 * index)) } }
        Repeater { model: 5
            Rectangle { required property int index; x: band.width * 0.42; y: 18 + index * 22; width: band.width * 0.58; height: 1
                gradient: Gradient { orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Theme.alpha(Theme.datum, 0) } GradientStop { position: 0.4; color: Theme.alpha(Theme.datum, 0.06) } GradientStop { position: 1; color: Theme.alpha(Theme.datum, 0.06) } } } }
        Column { x: 22; anchors.verticalCenter: parent.verticalCenter; spacing: 4
            Txt { kind: "cap"; text: "New in this version"; color: Theme.datum }
            Txt { id: vtxt; font.pixelSize: 40; font.weight: Theme.wSemi; font.letterSpacing: -1.6; text: wn.n ? wn.n.version : Bridge.version
                opacity: 0; Component.onCompleted: vin.start()
                SequentialAnimation { id: vin; PauseAnimation { duration: 60 }
                    ParallelAnimation { Glide { target: vtr; property: "y"; from: Theme.shift(8); to: 0; duration: Theme.slow }
                        NumberAnimation { target: vtxt; property: "opacity"; to: 1; duration: Theme.slow } } }
                transform: Translate { id: vtr } } } }

    // the bold-led lines of the section, one card each, arriving a beat apart
    Column {
        id: list
        visible: !wn.full
        width: parent.width; spacing: 8
        Repeater { model: wn.hl
            Rectangle {
                id: row
                required property var modelData
                required property int index
                width: list.width; height: rc.implicitHeight + 24; radius: Theme.rMd
                color: hm.containsMouse ? Theme.glass2 : Theme.glass; border.color: Theme.dark ? Theme.glassEdge : Theme.rule
                Behavior on color { Tint {} }
                opacity: 0; Component.onCompleted: arrive.start()
                SequentialAnimation { id: arrive; PauseAnimation { duration: 120 + row.index * Theme.stagger }
                    ParallelAnimation { Glide { target: row; property: "opacity"; to: 1; duration: Theme.slow }
                        Glide { target: rtr; property: "y"; from: Theme.shift(8); to: 0; duration: Theme.slow } } }
                transform: Translate { id: rtr }
                Rectangle { x: 14; y: 15; width: 22; height: 22; radius: 7; color: Theme.alpha(Theme.datum, 0.14)
                    Txt { anchors.centerIn: parent; mono: true; font.pixelSize: 11; text: row.index + 1; color: Theme.datum } }
                Column { id: rc; x: 48; y: 12; width: parent.width - 62; spacing: 3
                    Row { spacing: 8; width: parent.width
                        Txt { text: row.modelData.title; font.weight: Theme.wSemi; wrapMode: Text.Wrap; width: Math.min(implicitWidth, parent.width - (grp.visible ? grp.width + 8 : 0)) }
                        Tag { id: grp; visible: !!row.modelData.group; text: row.modelData.group; kind: "x"; tint: Theme.ink3; anchors.verticalCenter: parent.children[0].verticalCenter } }
                    Md { visible: !!row.modelData.text; source: row.modelData.text; width: parent.width; color: Theme.ink2 } }
                MouseArea { id: hm; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.NoButton }
            }
        }
    }
    Md { visible: wn.full; width: parent.width; source: wn.n ? wn.n.markdown : "" }
    Txt { visible: !!wn.n && !wn.n.found; tone: 3; width: parent.width
        text: "This copy of Form Studio has no notes for " + (wn.n ? wn.n.version : "") + ". Every release is described on GitHub." }
}
