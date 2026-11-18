import QtQuick
import QtQuick.Dialogs
import FormNative
import "F.js" as F

// A turntable of the head revision (form/animate.py export): the part turning once, rendered headless from the
// kernel's mesh, as an MP4 (when ffmpeg is installed), a PNG sequence, an animated WebP or a GIF. The preview plays
// the real file once it is made; Save… copies it anywhere.
Column {
    id: tt
    objectName: "turntableSheet"
    property string title: "Turntable"
    property string note: Store.project ? Store.project.name + " · " + F.pad(Store.project.head) : ""
    property int sheetWidth: Theme.sheetM
    property string fmt: "webp"
    property int frames: 36
    property real elevation: 24
    property var out: null
    property bool making: false
    readonly property string fileName: out ? String(out.file).replace(/^.*[\/\\]/, "") : ""
    spacing: 14

    function make() {
        if (making) return
        making = true; out = null
        Store.ppost("/turntable", { fmt: fmt, frames: frames, elevation: elevation }).then(function (r) {
            tt.making = false; tt.out = r
        }, function (e) { tt.making = false; Store.fail(e) })
    }
    function accept() { if (out) save(); else make() }
    function save() {
        dlg.currentFolder = Bridge.downloads()
        dlg.currentFile = Bridge.downloads() + "/" + Store.pid + "-turntable." + (fmt === "png" ? "zip" : fmt)
        Store.ask(dlg)
    }
    FileDialog { id: dlg; title: "Save the turntable"; fileMode: FileDialog.SaveFile
        nameFilters: [tt.fmt === "png" ? "PNG frames (*.zip)" : tt.fmt.toUpperCase() + " (*." + tt.fmt + ")", "All files (*)"]
        onAccepted: { if (Bridge.save("/projects/" + Store.pid + "/file/motion/" + tt.fileName, selectedFile)) Store.toast("Turntable saved", String(selectedFile).replace(/^.*\//, ""))
                      else Store.toast("Could not save the file", "Check that the folder is writable.", true) } }

    property Component footer: Row { spacing: 8
        Btn { kind: "quiet"; text: "Close"; onClicked: Store.openSheet(null) }
        Btn { objectName: "turntableMake"; kind: tt.out ? "quiet" : "primary"; icon: "film"; text: tt.out ? "Make again" : "Make turntable"
            busy: tt.making; busyText: "Rendering " + tt.frames + " frames…"; onClicked: tt.make() }
        Btn { objectName: "turntableSave"; kind: "primary"; icon: "download"; text: "Save…"; visible: !!tt.out; onClicked: tt.save() } }

    Seg { objectName: "turntableFormat"
        model: [{ value: "mp4", text: "MP4", off: !Bridge.hasFfmpeg, tip: "Needs ffmpeg installed" }, { value: "png", text: "PNG frames" },
                { value: "webp", text: "WebP" }, { value: "gif", text: "GIF" }]
        value: tt.fmt; onPicked: function (v) { tt.fmt = v; tt.out = null } }
    Row { width: parent.width; spacing: 12
        Column { width: (parent.width - 12) / 2; spacing: 4
            Txt { kind: "fine"; text: "Frames (one turn)" }
            Seg { model: [24, 36, 72, 120]; value: tt.frames; onPicked: function (v) { tt.frames = v; tt.out = null } } }
        Column { width: (parent.width - 12) / 2; spacing: 4
            Txt { kind: "fine"; text: "Camera height" }
            Seg { model: [{ value: 10, text: "Low" }, { value: 24, text: "Eye" }, { value: 45, text: "High" }]
                value: tt.elevation; onPicked: function (v) { tt.elevation = v; tt.out = null } } } }

    Rectangle { width: parent.width; height: Math.round(width * 0.75); radius: Theme.rMd; color: Theme.well; clip: true
        border.color: Theme.rule2
        Spinner { anchors.centerIn: parent; size: 28; visible: tt.making }
        Txt { anchors.centerIn: parent; kind: "fine"; tone: 3; visible: !tt.making && !tt.out; text: "The part turns once, rendered from the CAD model." }
        AnimatedImage { id: anim; anchors.fill: parent; anchors.margins: 1; fillMode: Image.PreserveAspectFit; asynchronous: true
            visible: !!tt.out; playing: visible
            source: tt.out ? Store.file("motion/" + (tt.out.fmt === "gif" || tt.out.fmt === "webp" ? tt.fileName : String(tt.out.still).replace(/^.*[\/\\]/, ""))) : ""
            opacity: status === Image.Ready ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Theme.base } } } }
    Txt { objectName: "turntableInfo"; kind: "fine"; tone: 2; width: parent.width; visible: !!tt.out
        text: tt.out ? tt.out.frames + " frames · " + F.fmt(tt.out.seconds, 1) + " s at " + tt.out.fps + " fps · " + tt.out.size.join(" × ") + " px · "
                       + F.fmt(tt.out.bytes / 1048576, 1) + " MB" + (tt.out.fmt === "png" ? " · a .zip of numbered PNGs" : tt.out.fmt === "mp4" ? " · H.264" : "") : "" }
    Txt { kind: "fine"; width: parent.width
        text: "Rendered by Form Studio from the kernel's mesh of this revision, not a photo." + (Bridge.hasFfmpeg ? "" : " MP4 needs ffmpeg (brew install ffmpeg).") }
}
