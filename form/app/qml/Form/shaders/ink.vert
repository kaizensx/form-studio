// The profile of a sketch on the part: lines in the scene's own depth, so the part hides what is behind it.
// Each is moved toward the eye along the view axis only (uOff.z hairs), which wins over the face it lies on and
// leaves its place on screen alone in an orthographic view. uOff.xy is a screen offset in clip units (InkLine.qml).
VARYING vec3 wpos;
void MAIN()
{
    vec4 w = MODEL_MATRIX * vec4(VERTEX, 1.0);
    wpos = w.xyz;
    vec4 v = VIEW_MATRIX * w;
    // (an orthographic view, PROJECTION_MATRIX[3][3] = 1: the same small step at any distance; the eye may stand far back)
    v.z += uOff.z * mix(0.0015 * abs(v.z) + 0.02, 0.05, PROJECTION_MATRIX[3][3]);
    vec4 p = PROJECTION_MATRIX * v;
    p.xy += uOff.xy * p.w;
    POSITION = p;
}
