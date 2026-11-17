import QtQuick
import Qt.labs.platform as P
import FormNative

// The native menu bar (macOS shows it at the top of the screen). Every item calls the same Store action as its button
// or palette command. Items whose key belongs to the 3D view (F, 1–5, M, X …) name the key in their text instead of
// claiming it, so typing in a field never triggers them.
P.MenuBar {
    id: mb
    signal fullScreen()
    readonly property bool work: Store.screen === "work"
    P.Menu { title: "File"
        P.MenuItem { text: "New Design…"; shortcut: StandardKey.New; onTriggered: Store.openSheet("new") }
        P.MenuItem { text: "New Design from a Brief…"; onTriggered: Store.openSheet("new", { tab: "brief" }) }
        P.MenuItem { text: "New Conversation"; shortcut: "Ctrl+Shift+O"; onTriggered: { Store.newChat(); Store.talkOpen = true } }
        P.MenuSeparator {}
        P.MenuItem { text: "All Designs"; shortcut: "Ctrl+Shift+H"; onTriggered: Store.home() }
        P.MenuItem { text: "Open the Projects Folder"; onTriggered: Bridge.openDataFolder() }
        P.MenuSeparator {}
        P.MenuItem { text: "Import a Reference Part…"; enabled: mb.work; onTriggered: Store.askImportPart() }
        P.MenuItem { text: "Share Card…"; enabled: mb.work; onTriggered: Store.openSheet("share") }
        P.MenuItem { text: "Render in Blender…"; enabled: mb.work; onTriggered: Store.openSheet("render") }
        P.MenuSeparator {}
        P.MenuItem { text: "Settings…"; role: P.MenuItem.PreferencesRole; shortcut: "Ctrl+,"; onTriggered: Store.openSettings("general") }
        P.MenuItem { text: "About FORM"; role: P.MenuItem.AboutRole; onTriggered: Store.openSheet("about") }
    }
    P.Menu { title: "Edit"
        P.MenuItem { text: "Commit the Draft"; shortcut: "Ctrl+Return"; enabled: Store.hasDraft && !Store.draftError; onTriggered: Store.commit() }
        P.MenuItem { text: "Discard the Draft"; enabled: Store.hasDraft; onTriggered: Store.discard() }
        P.MenuSeparator {}
        P.MenuItem { text: "Search and Commands…"; shortcut: "Ctrl+K"; onTriggered: Store.paletteOpen = !Store.paletteOpen }
    }
    P.Menu { title: "View"
        P.MenuItem { text: Store.talkOpen ? "Hide the Conversation" : "Show the Conversation"; shortcut: "Ctrl+J"; enabled: mb.work; onTriggered: Store.talkOpen = !Store.talkOpen }
        P.MenuItem { text: Store.timelineOpen ? "Hide the Revision Timeline" : "Show the Revision Timeline"; enabled: mb.work
            onTriggered: { Store.timelineOpen = !Store.timelineOpen; if (!Store.timelineOpen) Store.endScrub() } }
        P.MenuSeparator {}
        P.MenuItem { text: "Brief"; shortcut: "Ctrl+1"; enabled: mb.work; onTriggered: Store.setStage("brief") }
        P.MenuItem { text: "Shape"; shortcut: "Ctrl+2"; enabled: mb.work; onTriggered: Store.setStage("shape") }
        P.MenuItem { text: "Fit"; shortcut: "Ctrl+3"; enabled: mb.work; onTriggered: Store.setStage("fit") }
        P.MenuItem { text: "Prove"; shortcut: "Ctrl+4"; enabled: mb.work; onTriggered: Store.setStage("prove") }
        P.MenuItem { text: "Release"; shortcut: "Ctrl+5"; enabled: mb.work; onTriggered: Store.setStage("release") }
        P.MenuSeparator {}
        P.MenuItem { text: "Frame the Selection  (F)"; enabled: mb.work; onTriggered: Store.frameSelection() }
        P.MenuItem { text: "Reset the View  (.)"; enabled: mb.work; onTriggered: Store.resetView() }
        P.MenuItem { text: "Section Cut  (X)"; enabled: mb.work; onTriggered: Store.toggleSection() }
        P.MenuItem { text: (Store.dims ? "Hide" : "Show") + " Overall Dimensions"; enabled: mb.work; onTriggered: Store.toggleDims() }
        P.MenuSeparator {}
        P.MenuItem { text: "Enter Full Screen"; shortcut: "Ctrl+Meta+F"; onTriggered: mb.fullScreen() }
    }
    P.Menu { title: "Design"
        P.MenuItem { text: "Regenerate Everything"; enabled: mb.work; onTriggered: Store.run() }
        P.MenuItem { text: "Compare Alternatives…"; enabled: mb.work; onTriggered: Store.openSheet("alternatives") }
        P.MenuItem { text: "Variants Board…"; enabled: mb.work; onTriggered: Store.openSheet("variants") }
        P.MenuSeparator {}
        P.MenuItem { text: "Measure  (M)"; enabled: mb.work; checkable: true; checked: Store.measuring; onTriggered: Store.setMeasuring(!Store.measuring) }
        P.Menu { title: "Analysis Map"
            P.MenuItem { text: "None"; enabled: mb.work; onTriggered: Store.setAnalysis("") }
            P.MenuItem { text: "Thickness"; enabled: mb.work; onTriggered: Store.setAnalysis("thickness") }
            P.MenuItem { text: "Overhang"; enabled: mb.work; onTriggered: Store.setAnalysis("overhang") }
            P.MenuItem { text: "Section"; enabled: mb.work; onTriggered: Store.setAnalysis("section") }
            P.MenuItem { text: "Features"; enabled: mb.work; onTriggered: Store.setAnalysis("features") } }
        P.MenuItem { text: "Find a Print Orientation"; enabled: mb.work; onTriggered: { Store.setStage("prove"); Store.findOrientation() } }
        P.MenuItem { text: "Simulate the Print"; enabled: mb.work; onTriggered: Store.simulate() }
        P.MenuSeparator {}
        P.MenuItem { text: "Ask for a Design Review"; enabled: mb.work && Store.canAskReview; onTriggered: Store.askReview() }
        P.MenuItem { text: "Choose Slicer…"; onTriggered: Store.openSheet("slicer") }
    }
    P.Menu { title: "Window"
        P.MenuItem { text: "Software: Install or Check…"; onTriggered: Store.openSetup() }
        P.MenuItem { text: "Run the First-time Setup Again"; onTriggered: { Store.setOnboardStep(0); Store.checkSoftware(); Store.welcome = true } }
    }
    P.Menu { title: "Help"
        P.MenuItem { text: "Keyboard Shortcuts"; onTriggered: Store.openSheet("shortcuts") }
        P.MenuItem { text: "FORM on GitHub"; onTriggered: Bridge.openLink("https://github.com/kaizensx/form-studio") }
        P.MenuItem { text: "Report a Problem"; onTriggered: Bridge.openLink("https://github.com/kaizensx/form-studio/issues") }
        P.MenuItem { text: "Check for Updates…"; onTriggered: Store.checkUpdates(true).then(function (u) {
            if (u && u.available) { Store.updateHidden = false; Store.openSheet("update") }
            else if (u && !u.enabled) Store.toast("Update checks are off", "[updates] check = false or FORM_NO_UPDATE_CHECK=1")
            else if (u && u.latest) Store.toast("FORM " + u.current + " is up to date")
            else Store.toast("Could not reach GitHub", "Nothing changed. Try again later.") }) }
    }
}
