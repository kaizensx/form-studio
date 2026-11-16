// Sliced toolpaths: every vertex carries its line type's colour (type index in alpha) and its progress
// through the print (layer + fraction of the layer) in UV0.x.
VARYING vec3 tpWorld;
VARYING vec4 tpColor;
VARYING float tpProgress;
void MAIN()
{
    vec4 w = MODEL_MATRIX * vec4(VERTEX, 1.0);
    tpWorld = w.xyz;
    tpColor = COLOR;
    tpProgress = UV0.x;
    POSITION = PROJECTION_MATRIX * (VIEW_MATRIX * w);
}
