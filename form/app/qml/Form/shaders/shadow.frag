#version 440
// The soft shadow under a floating layer (Shadow.qml): one smooth falloff around a rounded rectangle, worked out
// per pixel from its distance to the shape and dithered before it is written. Drawn as a few rings it showed as
// steps, and a slow fall between dark tones shows as 8-bit bands even when it is smooth.
// Built into shadow.frag.qsb (see the note at the top of Shadow.qml); the .qsb is what the app loads.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float radius;        // the corner radius of the shape
    float spread;        // how far the shadow reaches, px
    float drop;          // how far its outer edge has fallen, px
    float alpha;         // its strength at the shape's edge
    float under;         // the tone it mostly falls on, 0..1 (sets the size of the dither; not the look)
    float grain;         // the dither, in 8-bit steps (1: one step)
    vec2 size;           // this item in px: the shape and `pad` around it
    vec2 pad;
};
float hash(vec2 p)
{
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
float sd(vec2 p, vec2 h, float r)
{
    vec2 d = abs(p) - h + r;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0) - r;
}
void main()
{
    vec2 h = size * 0.5 - pad;
    vec2 p = qt_TexCoord0 * size - size * 0.5;
    float r = min(radius, min(h.x, h.y));
    // well inside the shape there is no shadow at all (the layer over it may be glass)
    if (all(lessThan(abs(p), h - r - 3.0))) { fragColor = vec4(0.0); return; }
    // the contour through this pixel: the shape grown by g and fallen by drop * g / spread
    float g = sd(p, h, r);
    for (int i = 0; i < 4; ++i)
        g = sd(p - vec2(0.0, drop * clamp(g / spread + 0.0714, 0.0, 1.1)), h, r);
    float t = clamp(1.0714 - g / spread, 0.0, 1.0);
    float a = alpha * t * t * smoothstep(-1.5, -0.5, g);
    // the dither: black cannot go under itself, so it is the cover that is dithered, by what makes one 8-bit step
    // on the tone underneath, centred (two samples, triangular): the mean is kept exactly
    vec2 q = gl_FragCoord.xy;
    float n = hash(q) + hash(q + vec2(37.0, 17.0)) - 1.0;
    a += n * min(min(a, 1.0 - a), grain / (255.0 * max(under, 0.02)));
    fragColor = vec4(0.0, 0.0, 0.0, a) * qt_Opacity;
}
