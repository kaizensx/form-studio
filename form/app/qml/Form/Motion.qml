pragma Singleton
import QtQuick

// The workspace's names for the motion tokens. The tokens themselves live in Theme.qml (one set for the whole app);
// this file only keeps the names the viewport and inspector were written with. New code should use Theme directly.
QtObject {
    readonly property bool reduced: Theme.reduced
    readonly property int quick: Theme.press                // hover, press
    readonly property int ui: Theme.ui                      // tool options, chips, inspector sections
    readonly property int slow: Theme.cross                 // cross-fades of the part
    readonly property int camera: Theme.move(Theme.camera)
    readonly property int part: Theme.move(Theme.part)      // parts of an assembly travelling
    readonly property int stagger: Theme.move(Theme.stagger)
    readonly property var out: Theme.easeOut                // strong ease-out: things arriving, answering a click
    readonly property var inOut: Theme.easeMove             // something already on screen travelling
    function move(ms) { return Theme.move(ms) }             // duration for anything that changes position or scale
    function shift(px) { return Theme.shift(px) }           // distance an arriving thing travels
}
