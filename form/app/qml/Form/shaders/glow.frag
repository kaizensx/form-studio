#version 440
// The bloom around a lit thing (Glow.qml): the shape blurred, worked out per pixel instead of read from a blurred
// 8-bit texture, and dithered before it is written. The far tail of a bloom is a slow fall through the last few
// 8-bit steps, and from a texture it showed as rings.
// The profile is the blur it replaces (two Gaussians, measured against it): a tight core and a wide, faint skirt.
// Built into glow.frag.qsb (see the note at the top of Glow.qml); the .qsb is what the app loads.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float blur;          // the reach of the bloom, px
    float strength;
    float grain;         // the dither, in 8-bit steps (1: one step)
    vec2 size;           // this item in px
    vec2 half_;          // half the lit shape's size, px
    vec4 color;
};
float hash(vec2 p)
{
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
vec2 erf2(vec2 x)
{
    vec2 x2 = x * x;
    return sign(x) * sqrt(1.0 - exp(-x2 * (1.2732395 + 0.147 * x2) / (1.0 + 0.147 * x2)));
}
// a box of half-size h blurred by a Gaussian of deviation s, at p from its centre
float box(vec2 p, vec2 h, float s)
{
    vec2 e = 0.5 * (erf2((p + h) / (s * 1.4142136)) - erf2((p - h) / (s * 1.4142136)));
    return e.x * e.y;
}
void main()
{
    vec2 p = qt_TexCoord0 * size - size * 0.5;
    float a = 0.4412 * box(p, half_, 0.3315 * blur) + 0.5164 * box(p, half_, 0.9573 * blur);
    vec4 c = color * (a * strength);
    // the dither: a centred step of noise on each channel, never more than the channel itself (light cannot go
    // under nothing), so the mean is kept and the tail dies away with no edge
    vec2 q = gl_FragCoord.xy;
    float n = hash(q) + hash(q + vec2(37.0, 17.0)) - 1.0;
    c.rgb += n * min(c.rgb, vec3(grain / 255.0));
    fragColor = c * qt_Opacity;
}
