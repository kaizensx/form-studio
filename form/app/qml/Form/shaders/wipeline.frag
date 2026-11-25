// The model's edges, like line.frag, also cut at Compare's wipe line (uWipe: its x in render pixels, below zero = off;
// uWipeSide > 0 keeps what is left of it).
VARYING vec3 wpos;
void MAIN()
{
    if (uClip > 0.5 && dot(wpos, uClipN) > uClipD)
        discard;
    if (uWipe >= 0.0 && (FRAGCOORD.x - uWipe) * uWipeSide > 0.0)
        discard;
    FRAGCOLOR = vec4(uColor.rgb * uColor.a, uColor.a);
}
