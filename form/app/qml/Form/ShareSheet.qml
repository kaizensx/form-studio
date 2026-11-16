import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Share card: one 1600 × 900 image of the head revision, rendered by the engine (form/share.py).
// It states what FORM knows and how: computed size and volume, simulated print time and grams, the revision.
Column {
    id: sh
    property string title: "Share card"
    property int sheetWidth: 940
    spacing: 12; bottomPadding: 22

    property string picture: "model"         // model | photo
    property bool hasPhoto: false
    property int tick: 0
    readonly property string api: "/projects/" + Store.pid + "/share.png?picture=" + picture
    readonly property string src: Bridge.baseUrl + "/api" + api + "&v=" + (Store.project ? Store.project.head + "-" + Store.project.updated : "") + "-" + tick
    Component.onCompleted: Store.pget("/photo").then(function (r) { sh.hasPhoto = !!r.latest }, function () {})

    Rectangle { width: parent.width; height: Math.round(width * 9 / 16); radius: Theme.rMd; color: Theme.plate; border.color: Theme.rule; clip: true
        Image { id: img; anchors.fill: parent; anchors.margins: 1; source: sh.src; asynchronous: true; cache: false; fillMode: Image.PreserveAspectFit; smooth: true; mipmap: true
            opacity: status === Image.Ready ? 1 : 0; Behavior on opacity { NumberAnimation { duration: Theme.base } } }
        Column { anchors.centerIn: parent; spacing: 6; visible: img.status !== Image.Ready
            Txt { anchors.horizontalCenter: parent.horizontalCenter; tone: 2; text: img.status === Image.Error ? "The card could not be rendered." : "Rendering the card from the kernel geometry…" }
            Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "fine"; visible: img.status === Image.Error; text: "Regenerate the outputs, then try again." } } }

    Row { width: parent.width; spacing: 8
        Btn { kind: "primary"; icon: "copy"; text: "Copy image"; enabled: img.status === Image.Ready
            onClicked: { if (Bridge.copyImage(sh.api)) Store.toast("Card copied", "Paste it anywhere an image goes."); else Store.toast("Could not copy the image", "", true) } }
        Btn { icon: "download"; text: "Save PNG…"; enabled: img.status === Image.Ready
            onClicked: { dlg.currentFolder = Bridge.downloads(); dlg.currentFile = Bridge.downloads() + "/" + Store.pid + "_" + F.pad(Store.project.head) + "_card.png"; dlg.open() } }
        Item { width: 8; height: 1 }
        Seg { visible: sh.hasPhoto; anchors.verticalCenter: parent.verticalCenter
            model: [{ value: "model", text: "Kernel geometry" }, { value: "photo", text: "Blender render" }]
            value: sh.picture; onPicked: function (v) { sh.picture = v } }
    }
    Txt { kind: "fine"; width: parent.width
        text: "1600 × 900 PNG of " + (Store.project ? F.pad(Store.project.head) : "the head") + ". Size and volume are computed from the solid. Print time and grams are the slicer’s simulation and appear only while the slice is current. "
            + "Nothing on the card claims a print was made." + (sh.picture === "photo" ? " The Blender render is an illustration." : "")
            + (Store.hasDraft ? " Your open draft is not on the card." : "") }
    Txt { kind: "fine"; mono: true; tone: 4; width: parent.width; text: "form share " + Store.pid + " --out card.png" }

    FileDialog {
        id: dlg
        title: "Save the share card"; fileMode: FileDialog.SaveFile; nameFilters: ["PNG image (*.png)"]
        onAccepted: {
            if (Bridge.save(sh.api, selectedFile)) { Store.toast("Card saved", String(selectedFile).replace(/^.*\//, "")); Bridge.reveal(selectedFile) }
            else Store.toast("Could not save the file", "Check that the folder is writable.", true)
        }
    }
}
