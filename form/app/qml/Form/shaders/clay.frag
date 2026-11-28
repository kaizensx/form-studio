// The part: matte clay, cut by the section plane. Back faces are the cut and read as solid datum colour.
// With an analysis map on (uMap → 1) the base colour comes from the mesh's vertex colours instead of uColor.
// uRim lights the silhouette of a selected or hovered feature (black = none). It is never added to a map:
// analysis colours are shown as the engine computed them. Compare cuts it at a vertical line on screen (uWipe).
void MAIN()
{
    if (uClip > 0.5 && dot(VAR_WORLD_POSITION, uClipN) > uClipD)
        discard;
    // Compare's wipe line (uWipe: its x in render pixels, below zero = off): this side keeps what is left of it
    // (uWipeSide > 0) or right of it
    if (uWipe >= 0.0 && (FRAGCOORD.x - uWipe) * uWipeSide > 0.0)
        discard;
    BASE_COLOR = vec4(mix(uColor.rgb, VAR_COLOR.rgb, uMap), 1.0);
    ROUGHNESS = 0.76;
    METALNESS = 0.0;
    vec3 n = normalize(NORMAL);
    float edge = 1.0 - clamp(abs(dot(n, normalize(VIEW_VECTOR))), 0.0, 1.0);
    // studio ambient, as a white room gives it: a little from everywhere, more from the floor that bounces the key
    // back up. The lights all come from above, so without it a face that looks down (the view from below) is black.
    // Scene space is Y-up: n.y = -1 faces the floor.
    float down = clamp(-n.y, 0.0, 1.0);
    vec3 ambient = BASE_COLOR.rgb * (0.06 + 0.34 * down * down);
    // a soft sheen at grazing angles, as a studio's walls give a satin surface (never on an analysis map)
    vec3 sheen = BASE_COLOR.rgb * 0.05 * pow(edge, 3.0) * (1.0 - uMap);
    EMISSIVE_COLOR = ambient + sheen + uGlow.rgb + uRim.rgb * pow(edge, 2.6) * (1.0 - uMap);
    // a ghost (uGhost → 1: a sketch is open on the part): the clay thinned to a veil, firmer where the surface turns
    // away from the eye, so the silhouette still reads. The material blends it after a depth pass of its own
    // (Viewport.qml), so only the nearest surface is drawn; its own light is halved, so no face burns out.
    if (uGhost > 0.0) {
        BASE_COLOR.a = mix(1.0, 0.2 + 0.4 * pow(edge, 1.6), uGhost);
        EMISSIVE_COLOR *= mix(1.0, 0.5, uGhost);
    }
    if (!gl_FrontFacing) {
        BASE_COLOR = vec4(0.0, 0.0, 0.0, 1.0);
        EMISSIVE_COLOR = vec3(0.36, 0.56, 0.49);
        ROUGHNESS = 1.0;
    }
}
// The lit colour is dithered before it is written (uDither: how many 8-bit steps): a smooth face lit across a few
// steps is otherwise drawn as bands. The noise is fixed to the pixels, so a still view is not redrawn for it. The
// colour here is linear and the step is one of the display's, so it is scaled by the display curve's slope at this
// tone; it is centred (two samples, triangular), so the tone is kept.
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
    // how far one display step is in linear light at this tone: the display's gamma, and in the dark room the
    // filmic curve before it (uFilmic), which flattens the bright tones
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
