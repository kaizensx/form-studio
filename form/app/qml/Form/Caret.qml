import QtQuick

// The caret of every text field: a thin lit line of the accent, as on a command line. It stands where the next
// letter goes, as tall as the line of text, and moves with the words; it is solid while you type or move it and
// blinks once the field has been still for a moment. A soft light lies around it; the line itself stays crisp.
//
//   TextArea { cursorDelegate: Caret {} }                              the field's own cursor (the field places and sizes it)
//   Caret { field: ta; x: ...; y: ...; height: 20; resting: true }     standing in an empty prompt the keyboard has left
//
// The blink is two steps a cycle (lit, dim), set by a timer and not animated: a field waiting for words redraws
// the window twice a second, not at the display's rate, and never while the window is not the active one.
// Reduce Motion: it stays lit.
Item {
    id: c
    property Item field: parent              // the TextInput, TextEdit or TextArea it belongs to
    property bool resting: false             // not the field's cursor: it only marks where the words will go
    readonly property bool lit: resting || (!!field && field.activeFocus)
    readonly property bool blinking: lit && !resting && !Theme.reduced && !!field && field.visible && Window.active
    property int beat: 0                     // 0 lit · 1 dim
    readonly property real level: beat === 0 ? 1 : 0.14
    width: 2; implicitHeight: 16
    visible: lit
    // whatever moves it or changes the words: lit at once, and still for a moment before it blinks again
    function hold() { beat = 0; if (blinking) tick.restart() }
    onXChanged: hold(); onYChanged: hold(); onBlinkingChanged: { beat = 0; if (blinking) tick.restart(); else tick.stop() }
    Connections { target: c.resting ? null : c.field; ignoreUnknownSignals: true
        function onTextChanged() { c.hold() } function onCursorPositionChanged() { c.hold() } function onPreeditTextChanged() { c.hold() } }
    Timer { id: tick; repeat: true; running: false
        interval: c.beat === 0 ? 580 : 460
        onTriggered: c.beat = (c.beat + 1) % 2 }
    Rectangle {
        id: mark; objectName: "caretMark"
        width: 2; height: c.height; radius: 1; color: Theme.datum
        opacity: c.resting ? 0.85 : c.level
        Glow { blur: 7; strength: 0.5; radius: 1 }
    }
}
