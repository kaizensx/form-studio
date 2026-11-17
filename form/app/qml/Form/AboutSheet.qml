import QtQuick
import FormNative

// About FORM: the version you run, what it is built from, and the licences of what ships inside it.
Column {
    id: ab
    property string title: "About FORM"
    property int sheetWidth: Theme.sheetM
    property string shown: ""                // which licence text is unfolded
    readonly property var env: Store.studio ? Store.studio.env : null
    spacing: 18
    property Component footerLeft: Row { spacing: 4
        Btn { kind: "quiet"; icon: "external_link"; text: "Source"; onClicked: Bridge.openLink("https://github.com/kaizensx/form-studio") }
        Btn { kind: "quiet"; icon: "scroll_text"; text: "Changelog"; onClicked: Bridge.openLink("https://github.com/kaizensx/form-studio/blob/main/CHANGELOG.md") }
        Btn { kind: "quiet"; icon: "circle_alert"; text: "Report a problem"; onClicked: Bridge.openLink("https://github.com/kaizensx/form-studio/issues") } }
    property Component footer: Row { spacing: 8
        Btn { text: "Check for updates"; icon: "refresh_cw"; onClicked: { Store.openSheet(null); Store.checkUpdates(true).then(function (u) {
            if (u && u.available) { Store.updateHidden = false; Store.openSheet("update") }
            else if (u && !u.enabled) Store.toast("Update checks are off", "[updates] check = false or FORM_NO_UPDATE_CHECK=1")
            else if (u && u.latest) Store.toast("FORM " + u.current + " is up to date")
            else Store.toast("Could not reach GitHub", "Nothing changed. Try again later.") }) } } }

    Row { spacing: 16
        Rectangle { width: 56; height: 56; radius: Theme.rLg; color: Theme.plate; border.color: Theme.rule2
            // the mark: a datum triangle on the plate
            Rectangle { anchors.centerIn: parent; width: 22; height: 22; radius: 5; color: "transparent"; border.width: 2; border.color: Theme.datum; rotation: 45 }
            Rectangle { anchors.centerIn: parent; width: 5; height: 5; radius: 3; color: Theme.datum } }
        Column { spacing: 3; anchors.verticalCenter: parent.verticalCenter
            Row { spacing: 10
                Txt { text: "FORM"; font.weight: Theme.wBold; font.letterSpacing: 3; font.pixelSize: 18 }
                Txt { mono: true; tone: 2; text: Bridge.version; anchors.baseline: parent.children[0].baseline } }
            Txt { tone: 2; text: "An agent designs printable parts with a real CAD kernel, a real slicer and an honest record of what is known." } } }

    Column { width: parent.width
        KV { first: true; k: "CAD kernel"; value: ab.env && ab.env.kernel ? String(ab.env.kernel) : "starting…" }
        KV { k: "Slicer"; value: Store.slicer.available ? (Store.slicer.label || "") + (Store.slicer.version ? " " + Store.slicer.version : "") : "none found" }
        KV { k: "Interface"; value: "Qt " + Bridge.qtVersion + " · Python " + Bridge.pythonVersion }
        KV { k: "Projects folder"; value: Bridge.dataDirShort.length > 46 ? "…" + Bridge.dataDirShort.slice(-45) : Bridge.dataDirShort
            Btn { small: true; kind: "quiet"; icon: "folder_open"; tip: "Open the folder"; onClicked: Bridge.openDataFolder() } } }

    Sec { title: "Licences"; note: "what ships inside the app"
        Column { width: parent.width
            Repeater {
                model: [
                    { id: "FORM", name: "FORM", what: "This program", lic: "MIT" },
                    { id: "InstrumentSans", name: "Instrument Sans", what: "Interface typeface", lic: "SIL OFL 1.1" },
                    { id: "GeistMono", name: "Geist Mono", what: "Numbers and code", lic: "SIL OFL 1.1" },
                    { id: "lucide", name: "Lucide", what: "Icons", lic: "ISC" },
                    { id: "", name: "Qt and PySide6", what: "Interface toolkit", lic: "LGPL-3.0", url: "https://doc.qt.io/qtforpython-6/licenses.html" },
                    { id: "", name: "build123d", what: "Modelling library", lic: "Apache-2.0", url: "https://github.com/gumyr/build123d" },
                    { id: "", name: "Open CASCADE Technology", what: "Geometry kernel", lic: "LGPL-2.1 with exception", url: "https://dev.opencascade.org/resources/licensing" },
                    { id: "", name: "NumPy, Pillow, pypdfium2, MCP SDK", what: "Numerics, images, PDFs, agent protocol", lic: "their own open licences", url: "https://github.com/kaizensx/form-studio/blob/main/pyproject.toml" }
                ]
                Column {
                    id: lr
                    required property var modelData
                    required property int index
                    width: parent.width
                    KV { first: lr.index === 0; k: lr.modelData.name; sub: lr.modelData.what
                        Txt { kind: "fine"; tone: 2; text: lr.modelData.lic; anchors.verticalCenter: parent.verticalCenter }
                        Btn { small: true; kind: "quiet"; visible: lr.modelData.id !== ""; text: ab.shown === lr.modelData.id ? "Hide" : "Read"; anchors.verticalCenter: parent.verticalCenter
                            onClicked: ab.shown = ab.shown === lr.modelData.id ? "" : lr.modelData.id }
                        Btn { small: true; kind: "quiet"; visible: !!lr.modelData.url; icon: "external_link"; tip: "Open its licence page"; anchors.verticalCenter: parent.verticalCenter
                            onClicked: Bridge.openLink(lr.modelData.url) } }
                    Rectangle { visible: lr.modelData.id !== "" && ab.shown === lr.modelData.id; width: parent.width; height: visible ? 180 : 0; radius: Theme.rSm; color: Theme.well; border.color: Theme.rule; clip: true
                        Flickable { anchors.fill: parent; anchors.margins: 10; contentHeight: lt.implicitHeight; clip: true; boundsBehavior: Flickable.StopAtBounds
                            Txt { id: lt; width: parent.width; mono: true; font.pixelSize: 11; tone: 2
                                text: parent.parent.parent.visible ? Bridge.licence(lr.modelData.id) : "" } } }
                    Item { visible: lr.modelData.id !== "" && ab.shown === lr.modelData.id; width: 1; height: 8 }
                }
            }
        }
    }
    Txt { kind: "fine"; width: parent.width
        text: "FORM runs on this computer. It sends nothing anywhere on its own; an agent you connect uses your own account with its provider." }
}
