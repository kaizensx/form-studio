VARYING vec3 wpos;
void MAIN()
{
    vec4 w = MODEL_MATRIX * vec4(VERTEX, 1.0);
    wpos = w.xyz;
    vec4 v = VIEW_MATRIX * w;
    v.xyz *= 0.9985;                       // a hair closer to the eye, so a line wins over the face it lies on
    POSITION = PROJECTION_MATRIX * v;
}
