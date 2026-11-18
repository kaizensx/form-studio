pragma Singleton
import QtQuick
import FormNative

// FORM — a metrology bench at night.
// Graphite build plate, one pale-mint datum colour, clay for the part itself.
// Colour is evidence: datum = settled, blueprint = draft/compare, amber = review, signal = fail.
QtObject {
    // surfaces, lowest to highest
    readonly property color well: "#0a0c0e"        // inset: inputs receive content
    readonly property color plate: "#0e1113"       // the bench
    readonly property color plate1: "#13171a"      // panels resting on the bench
    readonly property color plate2: "#191e22"      // raised: cards
    readonly property color plate3: "#21282d"      // highest: menus, buttons
    readonly property color plate4: "#2a3238"
    // ink
    readonly property color ink: "#e8edeb"
    readonly property color ink2: "#a8b2af"
    readonly property color ink3: "#717b78"
    readonly property color ink4: "#49524f"
    readonly property color rule: Qt.rgba(1, 1, 1, 0.07)
    readonly property color rule2: Qt.rgba(1, 1, 1, 0.12)
    readonly property color rule3: Qt.rgba(1, 1, 1, 0.2)          // emphasis: a hovered or raised edge
    // interaction washes laid over any plate
    readonly property color washHover: Qt.rgba(1, 1, 1, 0.055)
    readonly property color washPress: Qt.rgba(1, 1, 1, 0.1)
    readonly property color washOn: Qt.rgba(1, 1, 1, 0.085)
    readonly property color scrim: Qt.rgba(0.016, 0.022, 0.027, 0.62) // behind sheets and the lightbox
    readonly property color shade: Qt.rgba(0, 0, 0, 0.5)              // drop shadow under floating layers
    // meaning
    readonly property color datum: "#b9e8d7"
    readonly property color datumInk: "#0d1a16"
    readonly property color blueprint: "#86a8ff"
    readonly property color amber: "#e9b860"
    readonly property color signal: "#ff6f51"
    readonly property color pass: "#86d9ad"
    readonly property color annotate: "#c7b2ff"                 // selections and annotations on the part
    readonly property color clay: "#d8d3c8"
    readonly property color datumHi: "#cdf2e4"                  // primary button, hovered
    readonly property color focus: Qt.rgba(0.725, 0.91, 0.843, 0.6)   // keyboard focus ring (datum)

    readonly property string sans: "Instrument Sans"
    readonly property string mono: "Geist Mono"
    readonly property string icons: "lucide"

    // type scale (ratio ~1.2 from 13)
    readonly property int tCap: 10
    readonly property int tFine: 11
    readonly property int tBody: 13
    readonly property int tLead: 15
    readonly property int tH3: 18
    readonly property int tH2: 22
    readonly property int tH1: 30
    readonly property int tHero: 44

    readonly property int rXs: 4
    readonly property int rSm: 6
    readonly property int rMd: 9
    readonly property int rLg: 14
    readonly property int rXl: 18          // sheets. Nested radii are concentric: inner = outer - padding

    // sheet widths: pick one, do not invent a fifth
    readonly property int sheetS: 480      // a question, a notice
    readonly property int sheetM: 640      // a form
    readonly property int sheetL: 840      // settings, lists with detail
    readonly property int sheetXl: 1080    // a canvas beside controls (render, variants, share)

    // weights (Instrument Sans is variable)
    readonly property int wBody: 420
    readonly property int wMedium: 520
    readonly property int wSemi: 620
    readonly property int wBold: 700

    // control heights
    readonly property int hSm: 24
    readonly property int hMd: 28
    readonly property int hLg: 34

    // spacing: 4px base
    readonly property int s1: 4
    readonly property int s2: 8
    readonly property int s3: 12
    readonly property int s4: 16
    readonly property int s5: 20
    readonly property int s6: 24
    readonly property int s8: 32

    // motion
    readonly property int fast: 120
    readonly property int base: 180
    readonly property int slow: 320
    // the workspace: tool options and inspector sections, cross-fades of the part, the camera, assembly parts travelling
    readonly property int ui: 170
    readonly property int cross: 240
    readonly property int camera: 420
    readonly property int part: 300
    readonly property var easeOut: [0.23, 1, 0.32, 1, 1, 1]
    readonly property var easeMove: [0.77, 0, 0.175, 1, 1, 1]
    readonly property var easeDrawer: [0.32, 0.72, 0, 1, 1, 1]    // panels that slide (the agent column)
    // Motion tokens. Use them as: NumberAnimation { duration: Theme.pop; easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.easeOut }
    //   press 110  a control answering a press        pop 150    menus, popovers, tooltips
    //   fast 120   hover and colour                    base 180   sheets, toasts
    //   exit 110   anything leaving (faster than it came)        slow 320   first-run and entrance moments
    //   stagger 45 between items of an entrance cascade
    // `reduced` is read once at start (OS "reduce motion", or FORM_REDUCED_MOTION=1). When set, movement and scale are
    // dropped (Theme.move(ms) returns 0, Theme.shift(px) returns 0) and only opacity/colour still animate.
    readonly property bool reduced: Bridge.reducedMotion
    readonly property int press: 110
    readonly property int pop: 150
    readonly property int exit: 110
    readonly property int stagger: 45
    //   screen 380 one screen handing over to the next (Home -> workspace -> designing)
    //   panel 300  the panels of a screen arriving after it, `stagger` apart
    //   rise 8     how far a message or row rises as it arrives
    readonly property int screen: 380
    readonly property int panel: 300
    readonly property int rise: 8
    readonly property var easeSpring: [0.2, 0.9, 0.25, 1.04, 1, 1]  // arrival with the faintest settle, for a pass
    function move(ms) { return reduced ? 0 : ms }
    function shift(px) { return reduced ? 0 : px }
    function from(scale) { return reduced ? 1 : scale }

    // tooltips: the moment the last one closed, so the next one opens without a delay (see Tip.qml)
    property real tipSeen: 0
    readonly property bool mac: Bridge.platform === "darwin"
    // "Ctrl+Shift+O" → ["⇧", "⌘", "O"] on macOS, ["Ctrl", "Shift", "O"] elsewhere. Shortcuts are written the Qt way everywhere.
    function keyCaps(seq) {
        var parts = String(seq).split("+"), out = []
        var glyph = { Ctrl: "⌘", Shift: "⇧", Alt: "⌥", Meta: "⌃", Return: "↵", Enter: "↵", Esc: "esc", Escape: "esc", Up: "↑", Down: "↓", Left: "←", Right: "→", Backspace: "⌫", Delete: "⌦", Tab: "⇥", Space: "space" }
        var order = { "⌃": 0, "⌥": 1, "⇧": 2, "⌘": 3 }
        for (var i = 0; i < parts.length; i++) {
            var k = parts[i]
            if (mac) out.push(glyph[k] || k)
            else out.push(k === "Return" || k === "Enter" ? "Enter" : k === "Escape" ? "Esc" : k)
        }
        if (mac) out.sort(function (a, b) { return (order[a] === undefined ? 9 : order[a]) - (order[b] === undefined ? 9 : order[b]) })
        return out
    }
    function keyText(seq) { return keyCaps(seq).join(mac ? "" : "+") }

    function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }
    // how a number is known → colour
    function evidence(kind) {
        switch (kind) {
        case "measured": case "physical": case "calibrated": case "PASS": return pass
        case "specified": case "computed": case "interface": case "geometry": return datum
        case "assumed": case "photo": case "WARN": case "simulated": case "modelled": case "model": return amber
        case "FAIL": case "resized": case "moved": case "added": case "removed": return signal
        case "trimmed": case "draft": return blueprint
        }
        return ink2
    }
}
