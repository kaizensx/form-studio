// CNC toolpaths (form/app/resultgeo.py PathGeometry): every vertex carries its operation's colour and, in UV0,
// the seconds at its segment's end and 1 for a rapid.
VARYING vec4 cpColor;
VARYING vec2 cpT;
void MAIN()
{
    cpColor = COLOR;
    cpT = UV0;
    vec4 v = VIEW_MATRIX * (MODEL_MATRIX * vec4(VERTEX, 1.0));
    v.xyz *= 0.9985;                       // a hair closer to the eye, so a path wins over the stock it cut
    vec4 p = PROJECTION_MATRIX * v;
    p.xy += uOff.xy * p.w;                    // a fraction of a pixel aside: four passes read as a line two pixels wide
    POSITION = p;
}
