#version 440
// The room (Room.qml) in one pass: the wall that falls to a lit floor, the pool of key light and the vignette,
// worked out per pixel in floating point and dithered by under one 8-bit step before it is written. A gradient
// between two dark tones a few steps apart is otherwise drawn as visible bands on a display.
// Built into room.frag.qsb (see the note at the top of Room.qml); the .qsb is what the app loads.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float wall;          // 1: the wall is drawn (opaque); 0: only the pool and the vignette, over what is behind
    float poolA;         // the pool's strength in its middle (0: none)
    float vigA;          // the vignette's strength in the corners (0: none)
    vec2 size;           // the room in px
    vec2 poolC;          // the pool's centre in px
    vec2 poolR;          // its radii in px
    vec2 vigC;           // the vignette's centre in px
    float vigR;          // its radius in px
    float grain;         // the dither, in 8-bit steps (1: one step)
    vec4 room0; vec4 room1; vec4 room2; vec4 room3;
    vec4 key;
    vec4 vig;
};
float hash(vec2 p)
{
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
void main()
{
    vec2 p = qt_TexCoord0 * size;
    float t = qt_TexCoord0.y;
    // premultiplied throughout
    vec4 c = vec4(0.0);
    if (wall > 0.5) {
        vec3 w = t < 0.4 ? mix(room0.rgb, room1.rgb, t / 0.4)
               : t < 0.72 ? mix(room1.rgb, room2.rgb, (t - 0.4) / 0.32)
               : mix(room2.rgb, room3.rgb, (t - 0.72) / 0.28);
        c = vec4(w, 1.0);
    }
    if (poolA > 0.0) {
        float d = length((p - poolC) / max(poolR, vec2(1.0)));
        float a = d < 0.55 ? mix(1.0, 0.32, d / 0.55) : mix(0.32, 0.0, clamp((d - 0.55) / 0.45, 0.0, 1.0));
        a *= poolA;
        c = vec4(key.rgb * a, a) + c * (1.0 - a);
    }
    if (vigA > 0.0) {
        float d = length(p - vigC) / max(vigR, 1.0);
        float a = vigA * clamp((d - 0.38) / 0.62, 0.0, 1.0);
        c = vec4(vig.rgb * a, a) + c * (1.0 - a);
    }
    // the dither. Over a wall it is centred (two samples, triangular): the tone is kept exactly. As a layer over
    // something else it is one sample, only where the layer is not clear, and where the layer's own colour is too
    // dark to go under it (the black of the vignette) it is lifted to stay centred on what comes out.
    vec2 q = gl_FragCoord.xy;
    if (wall > 0.5) {
        c.rgb += (hash(q) + hash(q + vec2(37.0, 17.0)) - 1.0) * grain / 255.0;
    } else {
        float on = clamp(c.a * 127.5, 0.0, 1.0);
        c.rgb += on * grain * ((hash(q) - 0.5) / 255.0 + max(vec3(0.0), 0.5 / 255.0 - c.rgb));
    }
    fragColor = c * qt_Opacity;
}
