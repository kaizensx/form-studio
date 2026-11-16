// Sliced toolpaths. Nothing above the nozzle is drawn; the layer being printed is bright, the ones below dimmed.
// uGhost > 0.5 draws the opposite: only what is still to come, faintly. Scrubbing changes uNow, never the buffer.
VARYING vec3 tpWorld;
VARYING vec4 tpColor;
VARYING float tpProgress;
void MAIN()
{
    int ti = int(tpColor.a + 0.5);
    if (ti < 16 && uShow[ti - (ti / 4) * 4][ti / 4] < 0.5)
        discard;
    bool ahead = tpProgress > uNow;
    if (uGhost > 0.5) {
        if (!ahead)
            discard;
        FRAGCOLOR = vec4(uGhostColor.rgb * uGhostColor.a, uGhostColor.a);
    } else {
        if (ahead)
            discard;
        float below = floor(uNow) - floor(tpProgress);            // 0 on the layer being printed
        if (uOnly > 0.5 && below > 0.5)
            discard;
        vec3 n = cross(dFdx(tpWorld), dFdy(tpWorld));
        float len = length(n);
        n = len > 1e-12 ? n / len : vec3(0.0, 1.0, 0.0);
        vec3 v = normalize(CAMERA_POSITION - tpWorld);
        if (dot(n, v) < 0.0)
            n = -n;
        float key = max(dot(n, normalize(vec3(0.42, 0.80, 0.43))), 0.0);
        float fill = max(dot(n, normalize(vec3(-0.6, 0.35, -0.72))), 0.0);
        float lit = mix(1.0, 0.34 + 0.62 * key + 0.16 * fill, uShade);
        vec3 c = tpColor.rgb * lit;
        if (below > 0.5)
            c = mix(uPlate.rgb, c, uDim);
        FRAGCOLOR = vec4(c, 1.0);
    }
}
