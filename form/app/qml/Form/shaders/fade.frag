#version 440
// A gradient that does not band (Fade.qml): up to four stops along a line or out from a centre, worked out per
// pixel and dithered by one 8-bit step before it is written. A slow fall between near tones, or a faint veil over
// a dark room, is otherwise drawn as visible bands.
// Built into fade.frag.qsb (see the note at the top of Fade.qml); the .qsb is what the app loads.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float kind;          // 0: down the item, 1: across it, 2: out from its centre (an ellipse that touches the edges)
    float under;         // the tone it mostly lies on, 0..1 (sets the size of a dark veil's dither; not the look)
    float grain;         // the dither, in 8-bit steps (1: one step)
    vec4 at;             // where the four stops are, 0..1, rising
    vec4 c0; vec4 c1; vec4 c2; vec4 c3;      // their colours (premultiplied, as Qt hands them over)
};
float hash(vec2 p)
{
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
float seg(float t, float a, float b) { return clamp((t - a) / max(b - a, 1e-5), 0.0, 1.0); }
void main()
{
    float t = kind < 0.5 ? qt_TexCoord0.y : kind < 1.5 ? qt_TexCoord0.x : length(qt_TexCoord0 * 2.0 - 1.0);
    vec4 c = mix(mix(mix(c0, c1, seg(t, at.x, at.y)), c2, seg(t, at.y, at.z)), c3, seg(t, at.z, at.w));
    // the dither, centred (two samples, triangular) so the mean is kept. A layer with light of its own takes it on
    // its colour, each channel by no more than itself. A dark veil cannot go under itself: there it is the cover
    // that is dithered, by what makes one 8-bit step on the tone underneath.
    vec2 q = gl_FragCoord.xy;
    float n = hash(q) + hash(q + vec2(37.0, 17.0)) - 1.0;
    float lit = clamp(max(c.r, max(c.g, c.b)) * 255.0, 0.0, 1.0);
    c.rgb += n * min(c.rgb, vec3(grain / 255.0));
    c.a += (1.0 - lit) * n * min(min(c.a, 1.0 - c.a), grain / (255.0 * max(under, 0.02)));
    fragColor = c * qt_Opacity;
}
