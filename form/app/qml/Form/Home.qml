import QtQuick
import QtQuick.Controls
import FormNative
import "F.js" as F

// Home: your designs as live objects. The prompt is on the left, in the Claude column.
Item {
    id: home
    readonly property var projects: Store.studio ? Store.studio.projects.filter(function (p) { return !p.error }).sort(function (a, b) { return b.updated - a.updated }) : []
    // newest Blender render of each project's current geometry, shown on hover (form/photo.py)
    property var photos: ({})
    function loadPhotos() { Store.get("/photos").then(function (r) { home.photos = r.latest }, function () {}) }
    Component.onCompleted: loadPhotos()
    Connections { target: Store; function onStudioChanged() { home.loadPhotos() } }
    function recipeTitle(id) {
        if (!Store.studio) return ""
        if (String(id).indexOf("src:") === 0) return "Designed by an agent"
        for (var i = 0; i < Store.studio.recipes.length; i++) if (Store.studio.recipes[i].id === id) return Store.studio.recipes[i].title
        return id
    }
    Flickable {
        anchors.fill: parent; contentHeight: col.implicitHeight + 60; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        Column {
            id: col; x: 32; y: 28; width: parent.width - 64; spacing: 18
            Item { width: parent.width; height: 34
                Column { spacing: 2
                    Txt { kind: "h2"; text: "Your designs" }
                    Txt { kind: "fine"; width: Math.min(implicitWidth, col.width - 330); elide: Text.ElideMiddle; wrapMode: Text.NoWrap
                        text: home.projects.length ? F.plural(home.projects.length, "project") + " in " + Bridge.dataDirShort : "Nothing here yet" } }
                Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                    Btn { kind: "quiet"; icon: "folder_open"; text: "Open folder"; onClicked: Bridge.openDataFolder() }
                    Btn { icon: "plus"; text: "New from a recipe"; onClicked: Store.openSheet("new") } } }
            Note { visible: !!Store.fatal; kind: "red"; title: Store.fatal ? Store.fatal.message : ""; text: Store.fatal ? (Store.fatal.hint || "") : "" }
            Grid {
                id: grid; width: parent.width
                columns: Math.max(1, Math.floor((width + 16) / 316)); spacing: 16
                readonly property real cw: (width - (columns - 1) * 16) / columns
                Repeater {
                    model: home.projects
                    Rectangle {
                        id: card
                        required property var modelData
                        required property int index
                        width: grid.cw; height: grid.cw * 0.74 + 62; radius: Theme.rLg
                        color: Theme.plate1; border.color: cm.containsMouse ? Theme.rule2 : Theme.rule; clip: true
                        opacity: 0
                        transform: Translate { id: ctr; y: 10 }
                        Component.onCompleted: ap.start()
                        SequentialAnimation { id: ap; PauseAnimation { duration: 60 + Math.min(card.index, 8) * 60 }
                            ParallelAnimation { NumberAnimation { target: card; property: "opacity"; to: 1; duration: 380; easing.type: Easing.OutCubic }
                                NumberAnimation { target: ctr; property: "y"; to: 0; duration: 380; easing.type: Easing.OutCubic } } }
                        MiniView { x: 1; y: 1; width: parent.width - 2; height: parent.height - 62; projectId: card.modelData.id; turning: cm.containsMouse }
                        Item {
                            readonly property var ph: home.photos[card.modelData.id] || null
                            x: 1; y: 1; width: parent.width - 2; height: parent.height - 62; clip: true
                            visible: !!ph; opacity: cm.containsMouse && pim.status === Image.Ready ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
                            Image { id: pim; anchors.fill: parent; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 640
                                source: parent.ph ? Bridge.baseUrl + "/api/projects/" + card.modelData.id + "/photo/" + parent.ph.key + ".png" : "" }
                            Rectangle { x: 8; anchors.bottom: parent.bottom; anchors.bottomMargin: 8; width: pl.implicitWidth + 12; height: 20; radius: Theme.rSm
                                color: Theme.alpha(Theme.plate, 0.78)
                                Txt { id: pl; anchors.centerIn: parent; font.pixelSize: 10; tone: 2; text: "Blender render · illustration" } }
                        }
                        Rectangle { y: parent.height - 62; width: parent.width; height: 1; color: Theme.rule }
                        Column { x: 14; y: parent.height - 50; width: parent.width - 28 - rv.width - 8; spacing: 2
                            Txt { text: card.modelData.name; font.weight: 600; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                            Txt { kind: "fine"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                                text: home.recipeTitle(card.modelData.recipe) + " · " + F.ago(card.modelData.updated) } }
                        Column { id: rv; anchors.right: parent.right; anchors.rightMargin: 14; y: parent.height - 50; spacing: 4
                            Txt { mono: true; font.pixelSize: 12; text: F.pad(card.modelData.head); anchors.right: parent.right; tone: 2 }
                            Tag { visible: card.modelData.approved_rev === card.modelData.head; text: "released"; kind: "PASS"; anchors.right: parent.right } }
                        MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Store.open(card.modelData.id) }
                    }
                }
            }
            Rectangle { visible: home.projects.length === 0 && !!Store.studio; width: parent.width; height: 220; radius: Theme.rLg; color: Theme.plate1; border.color: Theme.rule
                Column { anchors.centerIn: parent; spacing: 8
                    Icon { name: "cuboid"; size: 28; color: Theme.ink4; anchors.horizontalCenter: parent.horizontalCenter }
                    Txt { text: "Describe a part to Claude on the left, or start from a recipe."; tone: 2 } } }
        }
    }
}
