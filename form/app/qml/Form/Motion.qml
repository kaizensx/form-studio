pragma Singleton
import QtQuick

// Motion for the workspace, in one place. Movement is short and eases out; the camera is the only thing allowed
// longer. With reduced motion (the system setting, or FORM_REDUCED_MOTION=1) things stop moving: positions and
// scales jump, and only short opacity and colour changes remain, because they explain a change without travelling.
QtObject {
    readonly property bool reduced: typeof formReducedMotion !== "undefined" && !!formReducedMotion
    readonly property int quick: 110                       // hover, press
    readonly property int ui: 170                          // tool options, chips, inspector sections
    readonly property int slow: 240                        // cross-fades of the part
    readonly property int camera: reduced ? 0 : 420
    readonly property int part: reduced ? 0 : 300          // parts of an assembly travelling
    readonly property int stagger: reduced ? 0 : 36
    readonly property var out: [0.23, 1, 0.32, 1, 1, 1]    // strong ease-out: things arriving, answering a click
    readonly property var inOut: [0.77, 0, 0.175, 1, 1, 1] // something already on screen travelling
    function move(ms) { return reduced ? 0 : ms }          // duration for anything that changes position or scale
    function shift(px) { return reduced ? 0 : px }         // distance an arriving thing travels
}
