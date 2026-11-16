// Edges and drawing lines: flat colour, cut by the same section plane as the part.
VARYING vec3 wpos;
void MAIN()
{
    if (uClip > 0.5 && dot(wpos, uClipN) > uClipD)
        discard;
    FRAGCOLOR = vec4(uColor.rgb * uColor.a, uColor.a);
}
