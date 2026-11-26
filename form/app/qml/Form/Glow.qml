import QtQuick
import QtQuick.Effects

// Light around a lit thing: the gutter of a running program, the segment being built, the caret. Put it inside the
// item that glows; it takes that item's shape (`radius`) and lays a soft bloom of `color` around it, which fades to
// nothing with no edge. The lit thing itself stays crisp: the bloom is under it.
//
//   Rectangle { width: 2; radius: 1; color: Theme.datum; Glow { blur: 10; strength: 0.6 } }
//
// `blur` is the reach of the bloom in px, as in a CSS box-shadow: 0 0 <blur>px. `strength` is how bright it is at the
// shape's edge; a wide shape needs more of it than a hairline for the same look (the gutter 0.55, the caret 0.85,
// the track 0.95: set against the mockups' pixels). The bloom is a blurred copy of the shape, kept as a texture: it
// is only drawn again when the shape changes size or colour, so a lit thing that stands still costs one textured
// quad. Animate `opacity` or `strength` for a pulse, never `blur`.
Item {
    id: gl
    property color color: Theme.datum
    property real blur: 12
    property real strength: 0.6
    property real radius: Math.min(width, height) / 2
    property real grow: 0                    // the bloom starts this far outside the shape (CSS spread)
    anchors.fill: parent; z: -1
    property bool on: true                   // false while the lit thing is not lit: then nothing is made at all
    // made only while it shows: a listing of thirteen lines, each with a flare that is dark nearly always, makes no
    // textures and no effects for them
    Loader { anchors.fill: parent; active: gl.on && gl.visible && gl.opacity > 0.001 && gl.strength > 0.001 && gl.width > 0 && gl.height > 0
        sourceComponent: Item {
            Rectangle { id: shape; x: -gl.grow; y: -gl.grow; width: gl.width + 2 * gl.grow; height: gl.height + 2 * gl.grow
                radius: gl.radius + gl.grow; color: gl.color; antialiasing: true; visible: false; layer.enabled: true; layer.smooth: true }
            MultiEffect { source: shape; x: shape.x; y: shape.y; width: shape.width; height: shape.height
                blurEnabled: true; blur: 1; blurMax: Math.max(2, Math.round(gl.blur * 3)); autoPaddingEnabled: true
                opacity: gl.strength } } }
}
