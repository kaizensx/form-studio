// Measurement lines: drawn at the front of the depth range, so a dimension through the part stays readable.
VARYING vec3 wpos;
void MAIN()
{
    vec4 w = MODEL_MATRIX * vec4(VERTEX, 1.0);
    wpos = w.xyz;
    vec4 p = PROJECTION_MATRIX * (VIEW_MATRIX * w);
    p.z = (0.0005 + uOff.z) * p.w;        // uOff.z orders overlays among themselves (larger = further back)
    p.xy += uOff.xy * p.w;                    // uOff: a screen offset in clip units, to draw a line more than one pixel wide
    POSITION = p;
}
