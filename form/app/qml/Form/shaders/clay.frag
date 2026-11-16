// The part: matte clay, cut by the section plane. Back faces are the cut and read as solid datum colour.
void MAIN()
{
    if (uClip > 0.5 && dot(VAR_WORLD_POSITION, uClipN) > uClipD)
        discard;
    BASE_COLOR = vec4(uColor.rgb, 1.0);
    ROUGHNESS = 0.84;
    METALNESS = 0.0;
    EMISSIVE_COLOR = uGlow.rgb;
    if (!gl_FrontFacing) {
        BASE_COLOR = vec4(0.0, 0.0, 0.0, 1.0);
        EMISSIVE_COLOR = vec3(0.36, 0.56, 0.49);
        ROUGHNESS = 1.0;
    }
}
