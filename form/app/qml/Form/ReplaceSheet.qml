import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// Home › Replace a broken part (form/replace.py). A photo of the part with a card, coin or ruler beside it; what it
// does and where it broke. Start sends one message through the normal chat: the agent estimates sizes from the photo's
// scale, asks you for the sizes that decide the fit (ask_measurement), then designs the replacement. The four steps are
// shown here and above the conversation while it happens (ReplaceSteps.qml).
Column {
    id: rs
    objectName: "replaceSheet"
    property string title: "Replace a broken part"
    property string note: "A photo, your measurements, a new part"
    property int sheetWidth: Theme.sheetM
    property string reference: "card"
    property bool starting: false
    readonly property var photos: Store.chatAttach.filter(function (a) { return a.kind === "image" })
    readonly property bool can: photos.length > 0 && Store.chatReady && !starting
    spacing: 14

    function start() {
        if (!can) return
        starting = true
        Store.post("/replace/brief", { name: name.text, what: what.text, broke: broke.text, reference: reference, coin: coin.text,
                                      purpose: Store.newPurposeEffective }).then(function (r) {
            rs.starting = false
            Store.replaceConv = Store.convId
            Store.openSheet(null)
            Store.startDesign(r.message)
        }, function (e) { rs.starting = false; Store.fail(e) })
    }
    function accept() { start() }

    FileDialog { id: pick; title: "A photo of the broken part"; fileMode: FileDialog.OpenFiles
        nameFilters: ["Photos (*.png *.jpg *.jpeg *.webp *.heic *.bmp)"]
        onAccepted: Store.attachFiles(selectedFiles) }

    property Component footer: Row { spacing: 8
        Btn { kind: "quiet"; text: "Cancel"; onClicked: Store.openSheet(null) }
        Btn { objectName: "replaceStart"; kind: "primary"; icon: "sparkles"; text: "Design the replacement"; enabled: rs.can
            busy: rs.starting; busyText: "Starting…"; onClicked: rs.start() } }

    // the four steps, the first one filled in as soon as there is a photo
    ReplaceSteps { width: parent.width; done: rs.photos.length ? 1 : 0; active: rs.photos.length ? -1 : 0 }

    // ── 1. the photo ──
    Rectangle { objectName: "replacePhotoWell"; width: parent.width; height: 188; radius: Theme.rMd; color: Theme.well; clip: true
        border.color: pm.containsMouse ? Theme.rule3 : Theme.rule2
        Behavior on border.color { Tint {} }
        Row { anchors.centerIn: parent; spacing: 10; visible: rs.photos.length > 0
            Repeater { model: rs.photos.slice(0, 3)
                Image { required property var modelData; width: 150; height: 150; fillMode: Image.PreserveAspectCrop; asynchronous: true
                    source: Store.attachmentUrl(modelData.file || modelData.name)
                    Rectangle { anchors.fill: parent; color: "transparent"; border.color: Theme.rule2; radius: Theme.rSm } } } }
        Column { anchors.centerIn: parent; spacing: 8; visible: rs.photos.length === 0
            Icon { name: "camera"; size: 26; color: Theme.ink3; anchors.horizontalCenter: parent.horizontalCenter }
            Txt { anchors.horizontalCenter: parent.horizontalCenter; text: "Add a photo of the broken part" ; font.weight: Theme.wSemi }
            Txt { anchors.horizontalCenter: parent.horizontalCenter; kind: "fine"; tone: 3
                text: "Straight from above, with a bank card, a coin or a ruler beside it" } }
        MouseArea { id: pm; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: Store.ask(pick) } }
    Row { spacing: 8; visible: rs.photos.length > 0
        Btn { small: true; kind: "quiet"; icon: "plus"; text: "Another photo"; onClicked: Store.ask(pick) }
        Txt { kind: "fine"; tone: 3; anchors.verticalCenter: parent.verticalCenter; text: F.plural(rs.photos.length, "photo") + " attached" } }

    // ── what gives the scale ──
    Column { width: parent.width; spacing: 6
        Txt { kind: "fine"; text: "What is beside it in the photo, for the scale" }
        Seg { objectName: "replaceReference"; value: rs.reference; onPicked: function (v) { rs.reference = v }
            model: [{ value: "card", text: "Bank card", tip: "85.60 × 53.98 mm" }, { value: "coin", text: "A coin" },
                    { value: "ruler", text: "A ruler" }, { value: "none", text: "Nothing", tip: "Then the agent asks you for one size first" }] }
        Field { id: coin; visible: rs.reference === "coin"; width: parent.width; placeholder: "Which coin, e.g. 1 euro" } }

    // ── about the part ──
    Column { width: parent.width; spacing: 6
        Txt { kind: "fine"; text: "What it is" }
        Field { id: name; objectName: "replaceName"; width: parent.width; placeholder: "e.g. Shelf clip" } }
    Column { width: parent.width; spacing: 6
        Txt { kind: "fine"; text: "What it does, what it attaches to" }
        Field { id: what; width: parent.width; placeholder: "e.g. holds a glass shelf on a 5 mm pin" } }
    Column { width: parent.width; spacing: 6
        Txt { kind: "fine"; text: "Where it broke" }
        Field { id: broke; width: parent.width; placeholder: "e.g. the hook snapped at its root" } }

    Note { visible: !Store.chatReady && !!Store.studio; kind: "amber"; title: "No agent is connected"
        text: "The replacement is designed by an agent. Connect one in Settings › Agents & models." }
    Txt { kind: "fine"; width: parent.width
        text: "Sizes read off a photo are estimates and stay assumed. The agent asks you to measure the ones that decide the fit, and only those are marked measured." }
}
