import QtQuick
import QtQuick.Controls

// A popover: menus, pickers, the conversation switcher. It grows from where it was opened (`origin`), leaves faster
// than it came, sits one plate above everything and carries a shadow. Esc or a press outside closes it.
//   Pop { id: p; origin: Popup.TopLeft; y: anchor.height + 6; width: 240; Column { ... } }
Popup {
    id: pop
    property int origin: Popup.TopLeft
    property bool instant: false             // opened from the keyboard: no animation
    padding: 6; margins: 8
    transformOrigin: origin
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
    background: Rectangle { color: Theme.plate3; radius: Theme.rMd + 2; border.color: Theme.rule2
        Shadow { radius: parent.radius; spread: 20; drop: 8 } }
    enter: Transition { enabled: !pop.instant
        Glide { property: "opacity"; from: 0; to: 1; duration: Theme.pop }
        Glide { property: "scale"; from: Theme.from(0.96); to: 1; duration: Theme.pop } }
    exit: Transition { enabled: !pop.instant
        NumberAnimation { property: "opacity"; to: 0; duration: Theme.exit }
        NumberAnimation { property: "scale"; to: Theme.from(0.98); duration: Theme.exit } }
}
