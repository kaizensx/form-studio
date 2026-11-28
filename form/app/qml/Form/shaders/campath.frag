// CNC toolpaths, coloured by operation. Nothing after uNow (seconds) is drawn; the last uTail seconds are at full
// strength and what was cut before them is quieter, so the eye finds the tool. Rapids are faint. Scrubbing moves
// uNow, never the buffer.
VARYING vec4 cpColor;
VARYING vec2 cpT;
void MAIN()
{
    if (cpT.x > uNow)
        discard;
    float recent = 1.0 - smoothstep(0.0, uTail, uNow - cpT.x);
    float a = cpT.y > 0.5 ? 0.22 : mix(uPast, 1.0, recent);
    FRAGCOLOR = vec4(cpColor.rgb * a, a);
}
