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
    ROUGHNESS = 0.68;
    METALNESS = 0.0;
    vec3 n = normalize(NORMAL);
    float edge = 1.0 - clamp(abs(dot(n, normalize(VIEW_VECTOR))), 0.0, 1.0);
    // studio ambient, as a white room gives it: a little from everywhere, more from the floor that bounces the key
    // back up. The lights all come from above, so without it a face that looks down (the view from below) is black.
    // Scene space is Y-up: n.y = -1 faces the floor.
    float down = clamp(-n.y, 0.0, 1.0);
    vec3 ambient = BASE_COLOR.rgb * (0.06 + 0.34 * down * down);
    // a soft sheen at grazing angles, as a studio's walls give a satin surface (never on an analysis map)
    vec3 sheen = BASE_COLOR.rgb * 0.07 * pow(edge, 3.0) * (1.0 - uMap);
    EMISSIVE_COLOR = ambient + sheen + uGlow.rgb + uRim.rgb * pow(edge, 2.6) * (1.0 - uMap);
    if (!gl_FrontFacing) {
        BASE_COLOR = vec4(0.0, 0.0, 0.0, 1.0);
        EMISSIVE_COLOR = vec3(0.36, 0.56, 0.49);
        ROUGHNESS = 1.0;
    }
}
