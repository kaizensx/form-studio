import QtQuick
import QtQuick.Controls

// A popover: menus, pickers, the conversation switcher. It grows from where it was opened (`origin`), leaves faster
// than it came and is a pane of glass over the room (Glass.qml), made only while it is open. Esc or a press outside closes it.
//   Pop { id: p; origin: Popup.TopLeft; y: anchor.height + 6; width: 240; Column { ... } }
Popup {
    id: pop
    property int origin: Popup.TopLeft
    property bool instant: false             // opened from the keyboard: no animation
    padding: 6; margins: 8
    transformOrigin: origin
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    property real radius: Theme.rMd + 3
    background: Item {
        Loader { id: bg; anchors.fill: parent; active: pop.visible
            sourceComponent: Glass { source: Store.backdrop; radius: pop.radius; shadow: false
                Shadow { radius: pop.radius; spread: 22; drop: 10 }
                // a menu is read at a glance: a denser tint than a pane of the workspace
                Rectangle { anchors.fill: parent; radius: pop.radius; color: Theme.alpha(Theme.plate3, blurred ? 0.74 : 0.9) } } }
        function place() { if (bg.item) bg.item.place() } }
    onOpened: background.place()
    enter: Transition { enabled: !pop.instant
        Glide { property: "opacity"; from: 0; to: 1; duration: Theme.pop }
        Glide { property: "scale"; from: Theme.from(0.96); to: 1; duration: Theme.pop } }
    // while it fades out it takes no clicks: a press meant for what lies under it (often the control that opens it,
    // when the popover had to move up to fit the window) must not pick a row of a menu that is already closing
    onAboutToHide: pop.enabled = false
    onAboutToShow: pop.enabled = true
    exit: Transition { enabled: !pop.instant
        NumberAnimation { property: "opacity"; to: 0; duration: Theme.exit }
        NumberAnimation { property: "scale"; to: Theme.from(0.98); duration: Theme.exit } }
}
