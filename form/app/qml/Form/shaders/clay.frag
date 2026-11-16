// The part: matte clay, cut by the section plane. Back faces are the cut and read as solid datum colour.
// With an analysis map on (uMap → 1) the base colour comes from the mesh's vertex colours instead of uColor.
void MAIN()
{
    if (uClip > 0.5 && dot(VAR_WORLD_POSITION, uClipN) > uClipD)
        discard;
    BASE_COLOR = vec4(mix(uColor.rgb, VAR_COLOR.rgb, uMap), 1.0);
    ROUGHNESS = 0.84;
    METALNESS = 0.0;
    EMISSIVE_COLOR = uGlow.rgb;
    if (!gl_FrontFacing) {
        BASE_COLOR = vec4(0.0, 0.0, 0.0, 1.0);
        EMISSIVE_COLOR = vec3(0.36, 0.56, 0.49);
        ROUGHNESS = 1.0;
    }
}
