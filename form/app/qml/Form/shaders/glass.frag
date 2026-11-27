#version 440
// The last pass of a glass pane (Glass.qml): the blurred room behind it, kept in floating point until here, cut to
// the pane's rounded shape and dithered by about one 8-bit step before it is written. A blur of a dark room is a
// very slow gradient, and written straight to the screen it showed as contour lines inside every pane.
// Built into glass.frag.qsb (see the note at the top of Glass.qml); the .qsb is what the app loads.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float radius;        // the pane's corner radius, px
    float grain;         // the dither, in 8-bit steps (a little over one: the tint laid over it thins it)
    vec2 size;           // the pane in px
};
layout(binding = 1) uniform sampler2D source;
float hash(vec2 p)
{
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
void main()
{
    vec2 h = size * 0.5;
    vec2 p = qt_TexCoord0 * size - h;
    float r = min(radius, min(h.x, h.y));
    vec2 d = abs(p) - h + r;
    float sd = length(max(d, 0.0)) + min(max(d.x, d.y), 0.0) - r;
    float a = clamp(0.5 - sd / max(fwidth(sd), 1e-4), 0.0, 1.0);
    vec4 c = texture(source, qt_TexCoord0);
    vec2 q = gl_FragCoord.xy;
    c.rgb += (hash(q) + hash(q + vec2(37.0, 17.0)) - 1.0) * grain / 255.0;
    fragColor = c * (a * qt_Opacity);
}
