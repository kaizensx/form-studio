import QtQuick

// The tools of one mode in the dock. The four groups lie in the same place; the one whose mode is on is shown, and
// they cross-fade when the mode changes (IA.md, motion: 180 ms, ease-out). A group that is not on takes no clicks.
Column {
    id: g
    property bool on: false
    spacing: 2
    opacity: on ? 1 : 0; visible: opacity > 0.01; enabled: on
    Behavior on opacity { NumberAnimation { duration: Theme.reduced ? 0 : Theme.base; easing.type: Easing.OutCubic } }
}
