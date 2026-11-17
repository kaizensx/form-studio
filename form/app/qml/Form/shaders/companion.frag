// What the part holds (a reference outline, not printed): blueprint colour that fades out between two heights
// above the plate, so a tall device ends in a soft break a little above the part instead of leaving the view.
VARYING vec3 wpos;
void MAIN()
{
    float a = uColor.a * (1.0 - smoothstep(uFade0, uFade1, wpos.y));
    if (a < 0.004)
        discard;
    FRAGCOLOR = vec4(uColor.rgb * a, a);
}
