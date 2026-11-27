#version 440
// A picture that falls away to nothing all round (Veil.qml): the layer it is given, times a soft ellipse, dithered
// by one 8-bit step before it is written. A dark floor fading into a dark room is a slow fall through a few 8-bit
// steps, and undithered that shows as rings around the part.
// Built into veil.frag.qsb (see the note at the top of Veil.qml); the .qsb is what the app loads.
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float full;          // the picture is whole out to this share of the ellipse's radius
    float grain;         // the dither, in 8-bit steps (1: one step)
    vec2 size;           // this item in px
    vec2 centre;         // the ellipse's centre, px
    vec2 radii;          // its radii, px
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
    float d = length((qt_TexCoord0 * size - centre) / max(radii, vec2(1.0)));
    float m = smoothstep(0.0, 1.0, clamp((1.0 - d) / max(1.0 - full, 1e-4), 0.0, 1.0));
    vec4 c = texture(source, qt_TexCoord0) * m;
    vec2 q = gl_FragCoord.xy;
    float n = hash(q) + hash(q + vec2(37.0, 17.0)) - 1.0;
    c.rgb += n * min(c.rgb, vec3(grain / 255.0)) * step(m, 0.999);
    fragColor = c * qt_Opacity;
}
