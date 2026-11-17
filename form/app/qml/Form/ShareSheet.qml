import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Share card: one 1600 × 900 image of the head revision, rendered by the engine (form/share.py).
// It states what FORM knows and how: computed size and volume, simulated print time and grams, the revision.
Column {
    id: sh
    property string title: "Share card"
    property string note: "1600 × 900 PNG of " + (Store.project ? F.pad(Store.project.head) : "the head")
    property int sheetWidth: Theme.sheetXl
    spacing: 14

    property string picture: "model"         // model | photo
    property bool hasPhoto: false
    property int tick: 0
    readonly property string api: "/projects/" + Store.pid + "/share.png?picture=" + picture
    readonly property string src: Bridge.baseUrl + "/api" + api + "&v=" + (Store.project ? Store.project.head + "-" + Store.project.updated : "") + "-" + tick
    readonly property bool ready: img.status === Image.Ready
    // the card keeps its 16:9 shape and shrinks with a short window, so the actions never scroll away
    readonly property real room: (Window.height > 0 ? Window.height : 900) - 88 - 58 - 60 - 28 - (hasPhoto ? 40 : 0) - foot.implicitHeight - 2 * spacing
    readonly property int cardH: Math.round(Math.max(240, Math.min(width * 9 / 16, room)))
    Component.onCompleted: Store.pget("/photo").then(function (r) { sh.hasPhoto = !!r.latest }, function () {})

    function copy() {
        if (!ready) return
        if (Bridge.copyImage(sh.api)) Store.toast("Card copied", "Paste it anywhere an image goes."); else Store.toast("Could not copy the image", "", true)
    }
    function savePng() { dlg.currentFolder = Bridge.downloads(); dlg.currentFile = Bridge.downloads() + "/" + Store.pid + "_" + F.pad(Store.project.head) + "_card.png"; Store.ask(dlg) }
    function accept() { copy() }

    property Component footerLeft: Row { spacing: 8
        Txt { kind: "fine"; mono: true; tone: 4; anchors.verticalCenter: parent.verticalCenter; text: "form share " + Store.pid + " --out card.png" }
        Btn { small: true; kind: "quiet"; icon: "copy"; tip: "Copy the command"; anchors.verticalCenter: parent.verticalCenter
            onClicked: { Bridge.copy("form share " + Store.pid + " --out card.png"); Store.toast("Copied the command") } } }
    property Component footer: Row { spacing: 8
        Btn { icon: "download"; text: "Save PNG…"; enabled: sh.ready; onClicked: sh.savePng() }
        Btn { kind: "primary"; icon: "copy"; text: "Copy image"; enabled: sh.ready; keys: "Return"; onClicked: sh.copy() } }

    // which picture is on the card (only when a render exists)
    Item { visible: sh.hasPhoto; width: parent.width; height: 26
        Txt { kind: "cap"; text: "Picture"; anchors.verticalCenter: parent.verticalCenter }
        Seg { anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
            model: [{ value: "model", text: "Kernel geometry" }, { value: "photo", text: "Blender render" }]
            value: sh.picture; onPicked: function (v) { sh.picture = v } } }

    Rectangle { width: Math.round(sh.cardH * 16 / 9); height: sh.cardH; anchors.horizontalCenter: parent.horizontalCenter
        radius: Theme.rMd; color: Theme.plate; border.color: Theme.rule; clip: true
        Image { id: img; anchors.fill: parent; anchors.margins: 1; source: sh.src; asynchronous: true; cache: false; fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true
            opacity: status === Image.Ready ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } } }
        Column { anchors.centerIn: parent; spacing: 8; visible: img.status !== Image.Ready
            Spinner { visible: img.status !== Image.Error; anchors.horizontalCenter: parent.horizontalCenter; size: 18 }
            Icon { visible: img.status === Image.Error; name: "circle_alert"; size: 22; color: Theme.signal; anchors.horizontalCenter: parent.horizontalCenter }
            Txt { anchors.horizontalCenter: parent.horizontalCenter; tone: 2; text: img.status === Image.Error ? "The card could not be rendered." : "Rendering the card from the kernel geometry…" }
            Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "fine"; visible: img.status === Image.Error; text: "Regenerate the outputs, then try again." }
            Btn { visible: img.status === Image.Error; small: true; icon: "refresh_cw"; text: "Try again"; anchors.horizontalCenter: parent.horizontalCenter; onClicked: sh.tick++ } } }

    Txt { id: foot; kind: "fine"; width: parent.width
        text: "1600 × 900 PNG of " + (Store.project ? F.pad(Store.project.head) : "the head") + ". Size and volume are computed from the solid. Print time and grams are the slicer’s simulation and appear only while the slice is current. "
            + "Nothing on the card claims a print was made." + (sh.picture === "photo" ? " The Blender render is an illustration." : "")
            + (Store.hasDraft ? " Your open draft is not on the card." : "") }

    FileDialog {
        id: dlg
        title: "Save the share card"; fileMode: FileDialog.SaveFile; nameFilters: ["PNG image (*.png)"]
        onAccepted: {
            if (Bridge.save(sh.api, selectedFile)) { Store.toast("Card saved", String(selectedFile).replace(/^.*\//, "")); Bridge.reveal(selectedFile) }
            else Store.toast("Could not save the file", "Check that the folder is writable.", true)
        }
    }
}
