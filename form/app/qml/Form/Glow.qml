import QtQuick

// Light around a lit thing: the gutter of a running program, the segment being built, the caret. Put it inside the
// item that glows; it takes that item's shape (`radius`) and lays a soft bloom of `color` around it, which fades to
// nothing with no edge. The lit thing itself stays crisp: the bloom is under it.
//
//   Rectangle { width: 2; radius: 1; color: Theme.datum; Glow { blur: 10; strength: 0.6 } }
//
// `blur` is the reach of the bloom in px, as in a CSS box-shadow: 0 0 <blur>px. `strength` is how bright it is at the
// shape's edge; a wide shape needs more of it than a hairline for the same look (the gutter 0.55, the caret 0.85,
// the track 0.95: set against the mockups' pixels). The bloom is worked out per pixel by a shader (shaders/glow.frag)
// and dithered, so its far tail dies away with no rings; nothing is blurred and no texture is kept. The dither is
// fixed to the pixels: a lit thing that stands still is never redrawn for it. Animate `opacity` or `strength` for a
// pulse. After changing glow.frag, build it again:
//   pyside6-qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o shaders/glow.frag.qsb shaders/glow.frag
// A software renderer has no shaders: there a lit thing has no bloom.
Item {
    id: gl
    property color color: Theme.datum
    property real blur: 12
    property real strength: 0.6
    property real radius: Math.min(width, height) / 2
    property real grow: 0                    // the bloom starts this far outside the shape (CSS spread)
    anchors.fill: parent; z: -1
    property bool on: true                   // false while the lit thing is not lit: then nothing is drawn at all
    // one item, shown only while lit: dark, it has nothing in the scene and costs nothing
    ShaderEffect {
        visible: gl.on && gl.opacity > 0.001 && gl.strength > 0.001 && gl.width > 0 && gl.height > 0 && GraphicsInfo.api !== GraphicsInfo.Software
        readonly property real m: Math.ceil(gl.blur * 3) + gl.grow
        x: -m; y: -m; width: gl.width + 2 * m; height: gl.height + 2 * m
        fragmentShader: "shaders/glow.frag.qsb"
        property real blur: Math.max(0.5, gl.blur)
        property real strength: gl.strength
        property real grain: 1
        property size size: Qt.size(width, height)
        property point half_: Qt.point(gl.width / 2 + gl.grow, gl.height / 2 + gl.grow)
        property color color: gl.color
    }
}
