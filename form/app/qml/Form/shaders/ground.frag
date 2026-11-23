// The bench under the plate: matte, catches the part's shadow, and fades into the background colour with distance
// from the plate so there is a horizon instead of an edge.
void MAIN()
{
    float d = length(VAR_WORLD_POSITION.xz);
    float k = smoothstep(uFade * 0.35, uFade, d);
    BASE_COLOR = vec4(mix(uColor.rgb, uFar.rgb, k), 1.0);
    ROUGHNESS = 1.0;
    METALNESS = 0.0;
    SPECULAR_AMOUNT = 0.0;
    // far away the bench is the background itself: no light on it, its colour is emitted
    EMISSIVE_COLOR = uFar.rgb * k;
    BASE_COLOR.rgb *= (1.0 - k);
    // seen from below (the camera under the bench) it is a translucent ground: its own tone, unlit, thinning out
    // with distance, so the part above it reads through and the view never turns into a black slab
    if (!gl_FrontFacing) {
        BASE_COLOR = vec4(0.0, 0.0, 0.0, uBelowAlpha * (1.0 - k));
        EMISSIVE_COLOR = uColor.rgb;
    }
}
