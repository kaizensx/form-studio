import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Home: your designs as live objects. The prompt is the hero, on the left in the agent column.
// A card opens on click; right-click (or the ⋯ button) renames, duplicates, exports or moves it to the trash.
Item {
    id: home
    property string filter: "all"             // all | released | open
    property string order: "recent"           // recent | name
    property string renaming: ""
    property string confirming: ""
    property var menuFor: null
    readonly property var everything: Store.studio ? Store.studio.projects.filter(function (p) { return !p.error }) : []
    readonly property var broken: Store.studio ? Store.studio.projects.filter(function (p) { return !!p.error }) : []
    readonly property var projects: {
        var l = everything.filter(function (p) { return home.filter === "all" || (home.filter === "released") === (p.approved_rev === p.head) })
        return l.sort(function (a, b) { return home.order === "name" ? String(a.name).localeCompare(String(b.name)) : b.updated - a.updated })
    }
    readonly property int released: everything.filter(function (p) { return p.approved_rev === p.head }).length
    // newest Blender render of each project's current geometry (form/photo.py)
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
    function menu(p) {
        return [
            { icon: "arrow_up_right", text: "Open", run: function () { Store.open(p.id) } },
            { sep: true },
            { icon: "pencil", text: "Rename", run: function () { home.confirming = ""; home.renaming = p.id } },
            { icon: "copy_plus", text: "Duplicate", run: function () { Store.duplicateProject(p.id) } },
            { icon: "package", text: "Export .formproj…", run: function () { saveDlg.pid = p.id; saveDlg.currentFile = Bridge.downloads() + "/" + p.id + ".formproj"; Store.ask(saveDlg) } },
            { sep: true },
            { icon: "trash_2", text: "Move to trash…", danger: true, run: function () { home.renaming = ""; home.confirming = p.id } }
        ]
    }
    FileDialog { id: saveDlg; property string pid: ""; title: "Export the design"; fileMode: FileDialog.SaveFile; nameFilters: ["FORM projects (*.formproj)"]
        onAccepted: { if (Bridge.save("/projects/" + pid + "/archive", selectedFile)) Store.toast("Exported", "The whole history is in the file. Outputs are rebuilt where it is opened.")
                      else Store.toast("Could not write that file", "Choose another place.", true) } }
    PopMenu { id: pm; model: home.menuFor ? home.menu(home.menuFor) : [] }
    function openMenu(p, item, x, y) { menuFor = p; pm.parent = item; pm.openAt(item, x, y) }

    Flickable {
        id: flick
        anchors.fill: parent; contentHeight: col.implicitHeight + 72; clip: true; boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { width: 6 }
        Column {
            id: col; x: 36; y: 30; width: parent.width - 72; spacing: 22
            // ── header: what is here, and how to look at it ──
            Item { width: parent.width; height: 34; visible: home.everything.length > 0
                Row { spacing: 12; anchors.verticalCenter: parent.verticalCenter
                    Txt { kind: "h3"; text: "Designs"; font.letterSpacing: -0.2 }
                    Txt { mono: true; tone: 3; font.pixelSize: 12; text: home.everything.length; anchors.baseline: parent.children[0].baseline } }
                Row { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 8
                    Seg { visible: home.everything.length > 6; anchors.verticalCenter: parent.verticalCenter; value: home.filter; onPicked: function (v) { home.filter = v }
                        model: [{ value: "all", text: "All" }, { value: "open", text: "In progress" }, { value: "released", text: "Released" }] }
                    Btn { visible: home.everything.length > 6; kind: "quiet"; icon: "arrow_up_down"; text: home.order === "recent" ? "Last changed" : "Name"; tip: "Sort order"
                        onClicked: home.order = home.order === "recent" ? "name" : "recent" }
                    Rectangle { visible: home.everything.length > 6; width: 1; height: 16; color: Theme.rule2; anchors.verticalCenter: parent.verticalCenter }
                    Btn { kind: "quiet"; icon: "folder_open"; tip: "Open the projects folder: " + Bridge.dataDirShort; onClicked: Bridge.openDataFolder() }
                    Btn { icon: "plus"; text: "New design"; keys: "Ctrl+N"; tip: "From a recipe or a brief"; onClicked: Store.openSheet("new") } } }
            Note { visible: !!Store.fatal; kind: "red"; title: Store.fatal ? Store.fatal.message : ""; text: Store.fatal ? (Store.fatal.hint || "") : "" }
            Note { visible: home.broken.length > 0; kind: "amber"; title: F.plural(home.broken.length, "folder") + " could not be read"
                text: home.broken.map(function (p) { return p.id }).join(", ") + ". Nothing was changed; open the projects folder to look." }
            Grid {
                id: grid; width: parent.width
                columns: Math.max(1, Math.floor((width + 18) / 318)); spacing: 18
                readonly property real cw: Math.floor((width - (columns - 1) * 18) / columns)
                Repeater {
                    model: home.projects
                    Item {
                        id: card
                        required property var modelData
                        required property int index
                        readonly property var p: modelData
                        objectName: "projectCard"
                        readonly property string title: p.name
                        readonly property bool hot: cm.containsMouse || more.hovered || (pm.opened && home.menuFor === p)
                        readonly property bool editing: home.renaming === p.id
                        readonly property bool asking: home.confirming === p.id
                        readonly property var ph: home.photos[p.id] || null
                        readonly property int foot: 64
                        width: grid.cw; height: Math.round(grid.cw * 0.7) + foot
                        opacity: 0
                        Component.onCompleted: appear.start()
                        SequentialAnimation { id: appear; PauseAnimation { duration: 40 + Math.min(card.index, 9) * Theme.stagger }
                            ParallelAnimation { Glide { target: card; property: "opacity"; to: 1; duration: Theme.slow }
                                Glide { target: rise; property: "y"; from: Theme.shift(12); to: 0; duration: Theme.slow } } }
                        transform: Translate { id: rise; y: 0 }
                        Rectangle {
                            id: face
                            width: parent.width; height: parent.height; radius: Theme.rLg
                            y: card.hot && !cm.pressed ? Theme.shift(-3) : 0
                            scale: cm.pressed ? Theme.from(0.985) : 1
                            color: Theme.plate1; border.color: card.asking ? Theme.alpha(Theme.signal, 0.5) : card.hot ? Theme.rule3 : Theme.rule
                            Behavior on y { Glide { duration: Theme.base } }
                            Behavior on scale { Glide { duration: Theme.press } }
                            Behavior on border.color { Tint {} }
                            Shadow { radius: parent.radius; spread: 26; drop: 12; opacity: card.hot ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } } }
                            // the part on its plate
                            Item { id: stage; x: 1; y: 1; width: parent.width - 2; height: parent.height - card.foot - 1; clip: true
                                MiniView { anchors.fill: parent; projectId: card.p.id; turning: card.hot && !card.asking } }
                            // a render of this revision, if one was made: a small proof in the corner, large on click
                            Rectangle { visible: !!card.ph && pim.status === Image.Ready; anchors.right: stage.right; anchors.bottom: stage.bottom; anchors.margins: 10
                                width: 58; height: 44; radius: Theme.rSm; color: Theme.plate; border.color: phm.containsMouse ? Theme.rule3 : Theme.rule2; clip: true; z: 2
                                scale: phm.containsMouse ? 1.06 : 1; Behavior on scale { Glide { duration: Theme.fast } }
                                Image { id: pim; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectCrop; asynchronous: true; sourceSize.width: 160
                                    source: card.ph ? Bridge.baseUrl + "/api/projects/" + card.p.id + "/photo/" + card.ph.key + ".png" : "" }
                                MouseArea { id: phm; anchors.fill: parent; hoverEnabled: true
                                    onClicked: Store.showImage(Bridge.baseUrl + "/api/projects/" + card.p.id + "/photo/" + card.ph.key + ".png", card.p.name, "Blender render · an illustration, not evidence") }
                                Tip { show: phm.containsMouse; text: "Blender render of this revision · illustration" } }
                            Rectangle { y: parent.height - card.foot; x: 1; width: parent.width - 2; height: 1; color: Theme.rule }
                            // name, kind, last change — revision and status on the right
                            Column { visible: !card.editing && !card.asking; x: 16; y: parent.height - card.foot + 13; width: parent.width - 32 - side.width - 10; spacing: 3
                                Txt { text: card.p.name; font.weight: Theme.wSemi; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                                Txt { kind: "fine"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap
                                    text: home.recipeTitle(card.p.recipe) + "  ·  " + F.ago(card.p.updated) } }
                            Column { id: side; visible: !card.editing && !card.asking; anchors.right: parent.right; anchors.rightMargin: 16; y: parent.height - card.foot + 13; spacing: 5
                                Txt { mono: true; font.pixelSize: 12; text: F.pad(card.p.head); anchors.right: parent.right; tone: 2 }
                                Tag { anchors.right: parent.right; visible: !!card.p.approved_rev
                                    text: card.p.approved_rev === card.p.head ? "released" : card.p.approved_rev ? F.pad(card.p.approved_rev) + " released" : ""
                                    kind: card.p.approved_rev === card.p.head ? "PASS" : card.p.approved_rev ? "WARN" : "" } }
                            MouseArea { id: cm; anchors.fill: parent; hoverEnabled: true; acceptedButtons: Qt.LeftButton | Qt.RightButton; enabled: !card.editing && !card.asking
                                onClicked: function (e) {
                                    if (e.button === Qt.RightButton) home.openMenu(card.p, card, e.x, e.y)
                                    else Store.open(card.p.id) } }
                            Btn { id: more; objectName: "cardMore"; kind: "quiet"; icon: "ellipsis"; tip: "Rename, duplicate, export, delete"; x: parent.width - width - 8; y: 8; z: 3
                                opacity: card.hot && !card.asking && !card.editing ? 1 : 0; visible: opacity > 0
                                Behavior on opacity { NumberAnimation { duration: Theme.fast } }
                                onClicked: home.openMenu(card.p, card, more.x, more.y + more.height + 4) }
                            // rename in place
                            Field { id: rf; visible: card.editing; x: 12; y: parent.height - card.foot + 18; width: parent.width - 24
                                onVisibleChanged: if (visible) { text = card.p.name; input.forceActiveFocus(); input.selectAll() }
                                onAccepted: function (t) { if (!card.editing) return; home.renaming = ""; if (t.trim() && t.trim() !== card.p.name) Store.renameProject(card.p.id, t.trim()) }
                                Keys.onEscapePressed: home.renaming = ""
                                Connections { target: rf.input; function onActiveFocusChanged() { if (!rf.input.activeFocus && card.editing) home.renaming = "" } } }
                            // move to trash?
                            Rectangle { visible: card.asking; x: 1; y: 1; width: parent.width - 2; height: parent.height - card.foot - 1; radius: Theme.rLg - 1; color: Theme.alpha(Theme.plate, 0.72) }
                            Item { visible: card.asking; x: 16; y: parent.height - card.foot; width: parent.width - 32; height: card.foot
                                Column { anchors.verticalCenter: parent.verticalCenter; width: parent.width - acts.width - 10; spacing: 2
                                    Txt { text: "Move to the trash?"; font.weight: Theme.wMedium; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
                                    Txt { kind: "fine"; text: card.p.name + " · kept in .trash"; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap } }
                                Row { id: acts; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; spacing: 6
                                    Btn { small: true; kind: "quiet"; text: "Keep"; onClicked: home.confirming = "" }
                                    Btn { small: true; kind: "danger"; text: "Move to trash"; onClicked: { home.confirming = ""; Store.deleteProject(card.p.id) } } } }
                        }
                    }
                }
            }
            Txt { visible: home.everything.length > 0 && home.projects.length === 0; tone: 3; text: home.filter === "released" ? "Nothing is released yet. A design is released from its Release stage." : "Every design here is released." }

            // ── a clean install: no examples are created; this is the whole of Home until the first design ──
            Item { visible: home.everything.length === 0 && !!Store.studio; width: parent.width; height: Math.max(460, home.height - 110)
                Column { anchors.centerIn: parent; anchors.verticalCenterOffset: -10; spacing: 26; width: Math.min(520, parent.width - 48)
                    // an empty build plate with its datum: where the first part will sit
                    Item { id: plate; width: 340; height: 150; anchors.horizontalCenter: parent.horizontalCenter
                        opacity: 0; Component.onCompleted: pin.start()
                        ParallelAnimation { id: pin; Glide { target: plate; property: "opacity"; to: 1; duration: Theme.slow } Glide { target: plate; property: "scale"; from: Theme.from(0.96); to: 1; duration: Theme.slow } }
                        Rectangle { width: 240; height: 240; radius: Theme.rLg; color: Theme.plate2; border.color: Theme.rule3
                            // a square plate seen from above and to the side: x' = x − 0.5·y + 110, y' = 0.55·y + 9
                            transform: Matrix4x4 { matrix: Qt.matrix4x4(1, -0.5, 0, 110, 0, 0.55, 0, 9, 0, 0, 1, 0, 0, 0, 0, 1) }
                            Repeater { model: 7; Rectangle { required property int index; x: (index + 1) * parent.width / 8; width: 1; height: parent.height; color: Theme.rule2 } }
                            Repeater { model: 7; Rectangle { required property int index; y: (index + 1) * parent.height / 8; height: 1; width: parent.width; color: Theme.rule2 } }
                            // the datum: origin corner, two axes
                            Rectangle { x: 18; y: parent.height - 20; width: 72; height: 3; radius: 1; color: Theme.datum }
                            Rectangle { x: 18; y: parent.height - 90; width: 3; height: 72; radius: 1; color: Theme.datum }
                            Rectangle { x: 12; y: parent.height - 26; width: 14; height: 14; radius: 7; color: Theme.plate2; border.width: 3; border.color: Theme.datum } } }
                    Column { width: parent.width; spacing: 10
                        Txt { kind: "h2"; text: "An empty plate"; anchors.horizontalCenter: parent.horizontalCenter }
                        Txt { tone: 2; width: parent.width; horizontalAlignment: Text.AlignHCenter; lineHeight: 1.4; font.pixelSize: Theme.tLead - 1
                            text: "Tell the agent on the left what you need: what it holds, where it goes, what you measured. It builds the part in a real CAD kernel and shows its work." } }
                    Row { spacing: 8; anchors.horizontalCenter: parent.horizontalCenter
                        Btn { large: true; icon: "file_text"; text: "Start from a brief"; onClicked: Store.openSheet("new", { tab: "brief" }) }
                        Btn { large: true; icon: "sliders_horizontal"; text: "Start from a recipe"; onClicked: Store.openSheet("new") }
                        Btn { large: true; kind: "quiet"; icon: "box"; text: "Open an example"; onClicked: Store.openSheet("new", { examples: true }) } }
                    Txt { kind: "fine"; tone: 4; width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideMiddle; wrapMode: Text.NoWrap
                        text: "Designs are saved in " + Bridge.dataDirShort } } }
        }
    }
}
