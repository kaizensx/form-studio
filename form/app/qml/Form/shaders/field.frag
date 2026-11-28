// A result field on the part. The colour is looked up per pixel from the interpolated value, so the scale is
// continuous (no bands per triangle) and switching the scale costs nothing.
//   uScale 0: one hue. Clay, then the accent, then white at the peak: the part lights where it works.
//   uScale 1: a conventional many-colour scale (Turbo), for people who read results in other tools all day.
// Singular zones (fAux.x) are not a result: they are drawn as hatched clay, never in the scale.
// "A result develops": uDevelop runs 0..1 and the map comes up from the peak outward (fUV.y is the distance from it);
// what the front has not reached yet is still clay. uMix cross-fades the whole map (Reduce Motion, leaving).
// uGlow lights the hot end as emission, so the peak glows in the dark room (and a bloom pass picks it up).
VARYING vec2 fUV;
VARYING vec2 fAux;

vec3 toLinear(vec3 c) { return pow(max(c, vec3(0.0)), vec3(2.2)); }
vec3 rampMany(float x)
{
    vec3 r = vec3(0.13572138, 0.09140261, 0.10667330)
        + x * (vec3(4.61539260, 2.19418839, 12.64194608)
        + x * (vec3(-42.66032258, 4.84296658, -60.58204836)
        + x * (vec3(132.13108234, -14.18503333, 110.36276771)
        + x * (vec3(-152.94239396, 4.27729857, -89.90310912)
        + x * vec3(59.28637943, 2.82956604, 27.34824973)))));
    return toLinear(clamp(r, 0.0, 1.0));
}
vec3 rampHue(float x)
{
    return x < 0.6 ? mix(uLow.rgb, uMid.rgb, smoothstep(0.0, 1.0, x / 0.6))
                   : mix(uMid.rgb, uHigh.rgb, smoothstep(0.0, 1.0, (x - 0.6) / 0.4));
}
void MAIN()
{
    if (uClip > 0.5 && dot(VAR_WORLD_POSITION, uClipN) > uClipD)
        discard;
    float v = clamp(fUV.x, 0.0, 1.0);
    vec3 c = uScale > 0.5 ? rampMany(v) : rampHue(v);
    float heat = uScale > 0.5 ? 0.0 : smoothstep(0.45, 1.0, v);
    if (fAux.x > 0.5) {                                  // left out of the verdict: hatched, in the part's own clay
        float h = step(0.5, fract((FRAGCOORD.x + FRAGCOORD.y) / 9.0));
        c = uLow.rgb * mix(0.52, 0.86, h);
        heat = 0.0;
    }
    // the developing front: a soft edge 6 % of the reach wide, lit for a moment as it passes
    float front = uDevelop * 1.08;
    float todo = uDevelop >= 1.0 ? 0.0 : smoothstep(front - 0.06, front, fUV.y);
    float rim = uDevelop >= 1.0 ? 0.0 : (1.0 - abs(fUV.y - (front - 0.03)) / 0.03);
    rim = clamp(rim, 0.0, 1.0) * (1.0 - uDevelop);
    float k = (1.0 - todo) * uMix;
    BASE_COLOR = vec4(mix(uLow.rgb, c, k), 1.0);
    ROUGHNESS = 0.76;
    METALNESS = 0.0;
    vec3 n = normalize(NORMAL);
    float down = clamp(-n.y, 0.0, 1.0);
    vec3 ambient = BASE_COLOR.rgb * (0.06 + 0.34 * down * down);
    EMISSIVE_COLOR = ambient + c * heat * heat * uGlow * k + uMid.rgb * rim * 0.55 * uMix;
    if (!gl_FrontFacing) {
        BASE_COLOR = vec4(0.0, 0.0, 0.0, 1.0);
        EMISSIVE_COLOR = vec3(0.36, 0.56, 0.49);
        ROUGHNESS = 1.0;
    }
}
// dithered before it is written, as the clay is (clay.frag): a smooth scale over a large face is otherwise bands
float pixelHash(vec2 p)
{
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
void POST_PROCESS()
{
    COLOR_SUM = vec4(DIFFUSE.rgb + SPECULAR + EMISSIVE, DIFFUSE.a);
    vec3 x = max(COLOR_SUM.rgb, vec3(1e-4));
    vec3 step1 = 2.2 * pow(x, vec3(0.545));
    if (uFilmic > 0.5) {
        vec3 num = x * (x + 0.0245786) - 0.000090537;
        vec3 den = x * (0.983729 * x + 0.432951) + 0.238081;
        vec3 f = num / den;
        vec3 df = ((2.0 * x + 0.0245786) * den - num * (1.967458 * x + 0.432951)) / (den * den);
        step1 = min(2.2 * pow(max(f, vec3(1e-4)), vec3(0.545)) / max(df, vec3(0.03)), vec3(12.0));
    }
    float n = pixelHash(gl_FragCoord.xy) + pixelHash(gl_FragCoord.xy + vec2(37.0, 17.0)) - 1.0;
    COLOR_SUM.rgb += n * uDither / 255.0 * step1;
}
