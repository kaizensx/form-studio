pragma Singleton
import QtQuick

// What the workspace remembers about itself while the app runs: the active viewport tool, which inspector sections
// are folded, whether the legend dock is collapsed. Interface state only; nothing here describes the design.
QtObject {
    id: w
    // select | measure | section | analyze | assembly | history. One at a time; its options show next to the rail.
    property string tool: "select"
    property bool dockCollapsed: false      // the legend / measurement dock, folded to its header by the user
    property bool dockTouched: false        // the user has folded or opened it; until then a narrow viewport folds it
    property bool tipWarm: false            // a rail tooltip was just showing: the next one appears at once
    property var folds: ({})                // section key → open
    function isOpen(key, byDefault) { return folds[key] === undefined ? !!byDefault : folds[key] }
    function setOpen(key, on) { var f = Object.assign({}, folds); f[key] = !!on; folds = f }
}
