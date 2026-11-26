// The studio floor under the part: matte, catches the part's shadow, and fades into the background colour with
// distance so there is a horizon instead of an edge. Where the studio light falls (around uCentre) it is a tone
// lighter, and it carries a faint drafting grid: a line every 10 mm, a firmer one every 50 mm. The grid is drawn
// from the floor's own millimetres, so it is a true scale; it thins out as the lines get too close to tell apart.
float gridLine(vec2 p, float step)
{
    vec2 q = p / step;
    vec2 w = max(fwidth(q), vec2(1e-5));
    vec2 a = abs(fract(q - 0.5) - 0.5) / w;
    float line = 1.0 - min(min(a.x, a.y), 1.0);
    // lines closer than about three pixels are left out instead of turning into a grey film
    float thin = 1.0 - smoothstep(0.18, 0.42, max(w.x, w.y));
    return line * thin;
}
// a fixed value 0..1 per pixel (the dither below)
float pixelHash(vec2 p)
{
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
void MAIN()
{
    float d = length(VAR_WORLD_POSITION.xz);
    float k = smoothstep(uFade * 0.35, uFade, d);
    float pool = 1.0 - smoothstep(0.0, uPoolR, length(VAR_WORLD_POSITION.xz - uCentre));
    vec3 base = mix(uColor.rgb, uPool.rgb, pool * pool);
    float g = max(gridLine(VAR_WORLD_POSITION.xz, 10.0) * 0.55, gridLine(VAR_WORLD_POSITION.xz, 50.0));
    // the grid belongs to the lit floor: strongest in the pool, gone well before the horizon
    g *= uGrid.a * (0.35 + 0.65 * pool) * (1.0 - smoothstep(uFade * 0.2, uFade * 0.7, d));
    base = mix(base, uGrid.rgb, g);
    // the part stands on the floor: the floor is a little darker under and just around its footprint (the bounds
    // of what is drawn), falling off softly, as light is shut out where something rests on a surface
    vec2 q = abs(VAR_WORLD_POSITION.xz - uBoxC) - uBoxH;
    float away = length(max(q, vec2(0.0))) + min(max(q.x, q.y), 0.0);
    base *= 1.0 - uContact * (1.0 - smoothstep(-uSoft * 0.35, uSoft, away));
    BASE_COLOR = vec4(mix(base, uFar.rgb, k), 1.0);
    ROUGHNESS = 1.0;
    METALNESS = 0.0;
    SPECULAR_AMOUNT = 0.0;
    // far away the bench is the background itself: no light on it, its colour is emitted
    // uLift: how much of the floor's own tone is shown as it is, whatever the lights do (by day the floor is paper,
    // and lit paper under a filmic curve turns grey); the rest still takes the light, the shadow and the occlusion
    EMISSIVE_COLOR = uFar.rgb * k + base * uLift * (1.0 - k);
    BASE_COLOR.rgb *= (1.0 - k) * (1.0 - uLift);
    // the floor is a slow gradient between tones a few 8-bit steps apart: undithered it shows as bands. About one
    // step of noise, fixed to the pixels (a still view is not redrawn for it), is added before the colour is
    // written. The colour here is linear and the step is one of the display's, so it is scaled by the display
    // curve's slope at this tone (uDither: how many steps; the filmic curve of the dark room needs more).
    vec3 tone = max(uFar.rgb * k + base * (1.0 - k), vec3(1e-4));
    float n = pixelHash(gl_FragCoord.xy) + pixelHash(gl_FragCoord.xy + vec2(37.0, 17.0)) - 1.0;
    EMISSIVE_COLOR += n * uDither / 255.0 * 2.2 * pow(tone, vec3(0.545));
    // seen from below (the camera under the bench) it is a translucent ground: its own tone, unlit, thinning out
    // with distance, so the part above it reads through and the view never turns into a black slab
    if (!gl_FrontFacing) {
        BASE_COLOR = vec4(0.0, 0.0, 0.0, uBelowAlpha * (1.0 - k));
        // uBelowEmit: by night the ground's tone is added whole (it is dark); by day it is weighted like its alpha,
        // or a pale ground over a pale background would burn out to white under the linear curve
        EMISSIVE_COLOR = uColor.rgb * uBelowEmit;
    }
}
