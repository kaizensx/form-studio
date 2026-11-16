import QtQuick
import QtQuick.Window
import Form
import FormNative

// FORM — the window. Claude on the left, the work in the middle.
Window {
    id: win
    property string startProject: ""
    property string startStage: ""
    property bool headless: false
    readonly property bool mac: Bridge.platform === "darwin"
    visible: true; color: Theme.plate
    title: Store.project ? Store.project.name + " — FORM" : "FORM"
    minimumWidth: 1120; minimumHeight: 700
    // on macOS the content runs under a transparent title bar, so the window buttons sit in our own bar
    flags: mac ? Qt.Window | Qt.ExpandedClientAreaHint | Qt.NoTitleBarBackgroundHint : Qt.Window
    Component.onCompleted: { Store.boot(startProject, startStage); Store.bootSetup(headless) }

    TopBar { id: top; width: parent.width; inset: win.mac && win.visibility !== Window.FullScreen ? 70 : 0; z: 10 }

    Talk {
        id: talk
        anchors.top: top.bottom; anchors.bottom: parent.bottom
        hero: Store.screen !== "work"
        readonly property bool shown: Store.screen !== "work" || Store.talkOpen
        width: hero ? 400 : 340
        x: shown ? 0 : -width
        Behavior on x { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
        Behavior on width { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
    }
    Item {
        id: stage
        anchors.top: top.bottom; anchors.bottom: parent.bottom; anchors.right: parent.right
        anchors.left: talk.right
        Loader { anchors.fill: parent; active: Store.screen === "home"; sourceComponent: Home {} }
        Loader { anchors.fill: parent; active: Store.screen === "work"; sourceComponent: Workspace {} }
        Column { anchors.centerIn: parent; visible: Store.screen === "boot"; spacing: 10
            Txt { text: "FORM"; font.weight: 700; font.letterSpacing: 6; font.pixelSize: 22; anchors.horizontalCenter: parent.horizontalCenter }
            Txt { kind: "fine"; text: "Starting the CAD kernel…"; anchors.horizontalCenter: parent.horizontalCenter } }
    }
    Loader { anchors.top: top.bottom; anchors.bottom: parent.bottom; width: parent.width; z: 30; active: Store.welcome; sourceComponent: Welcome {} }
    Toasts { anchors.right: parent.right; anchors.bottom: parent.bottom; anchors.margins: 18; z: 60 }
    SheetHost {}
    Palette {}

    Shortcut { sequences: ["Ctrl+K"]; onActivated: Store.paletteOpen = !Store.paletteOpen }
    Shortcut { sequence: "Escape"; onActivated: {
        if (Store.paletteOpen) Store.paletteOpen = false
        else if (Store.sheet) Store.openSheet(null)
        else if (Store.measuring) Store.setMeasuring(false)
        else if (Store.layers) Store.showLayers(false)
        else if (Store.feature) Store.select("") } }
    Shortcut { sequence: "Ctrl+1"; onActivated: if (Store.data) Store.setStage("brief") }
    Shortcut { sequence: "Ctrl+2"; onActivated: if (Store.data) Store.setStage("shape") }
    Shortcut { sequence: "Ctrl+3"; onActivated: if (Store.data) Store.setStage("fit") }
    Shortcut { sequence: "Ctrl+4"; onActivated: if (Store.data) Store.setStage("prove") }
    Shortcut { sequence: "Ctrl+5"; onActivated: if (Store.data) Store.setStage("release") }
    Shortcut { sequence: "Ctrl+Return"; onActivated: if (Store.hasDraft && !Store.draftError) Store.commit() }
    Shortcut { sequences: [StandardKey.New]; onActivated: Store.openSheet("new") }
    Shortcut { sequence: "Ctrl+J"; onActivated: Store.talkOpen = !Store.talkOpen }
    Shortcut { sequences: ["Ctrl+,"]; onActivated: Store.openSettings("general") }      // Settings (⌘, on macOS)
}
