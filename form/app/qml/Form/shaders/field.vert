// A result field on the part (form/app/resultgeo.py): UV0 = (value on the legend's 0..1, distance from the peak 0..1),
// UV1 = (1 in a singular zone, status). The tangent carries the displacement (or a mode shape) in millimetres:
// uDeform times it is the deformed shape, so the toggle and a swinging mode move a uniform and never the buffer.
VARYING vec2 fUV;
VARYING vec2 fAux;
void MAIN()
{
    fUV = UV0;
    fAux = UV1;
    VERTEX += TANGENT * uDeform;
}
