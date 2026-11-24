// A game asset's LOD (GameSheet): uMode 0 shaded with its baked maps (base colour; roughness and metallic from the
// ORM map's G and B, occlusion from its R; the tangent-space normal map when uNrmOn; the emissive map added as light),
// 1 a UV checker (8 x 8 squares over 0..1, tinted by u and v so a flipped or rotated island shows), 2 one baked map as
// it is stored (uShow; shown so the screen pixel is the texel value). Without baked maps the part is clay. Scene space
// is Y-up: the ambient bounce comes from the floor, as in clay.frag.
//
// The normal map is Blender's tangent-space bake (OpenGL convention: green is +v, UVs v up, as the LOD's UVs are).
// The mesh carries no tangents, so the frame is rebuilt per pixel from the screen derivatives of the world position
// and the UVs (a cotangent frame); the determinant's sign keeps it right whichever way the screen's y runs.
vec3 mappedNormal(vec3 n, vec2 uv)
{
    vec3 p = VAR_WORLD_POSITION;
    vec3 dp1 = dFdx(p);
    vec3 dp2 = dFdy(p);
    vec2 duv1 = dFdx(uv);
    vec2 duv2 = dFdy(uv);
    vec3 dp2perp = cross(dp2, n);
    vec3 dp1perp = cross(n, dp1);
    vec3 t = dp2perp * duv1.x + dp1perp * duv2.x;
    vec3 b = dp2perp * duv1.y + dp1perp * duv2.y;
    float m = max(dot(t, t), dot(b, b));
    if (m < 1e-24)
        return n;                                        // no UV change across the pixel: nothing to map
    float s = dot(dp1, dp2perp) < 0.0 ? -1.0 : 1.0;
    t *= s * inversesqrt(m);
    b *= s * inversesqrt(m);
    vec3 tn = texture(uNormal, uv).rgb * 2.0 - 1.0;
    return normalize(t * tn.x + b * tn.y + n * tn.z);
}

void MAIN()
{
    vec2 uv = UV0;
    vec3 n = normalize(NORMAL);
    if (uMode > 1.5) {                                   // one map, unlit
        vec3 t = texture(uShow, uv).rgb;
        BASE_COLOR = vec4(0.0, 0.0, 0.0, 1.0);
        ROUGHNESS = 1.0;
        METALNESS = 0.0;
        SPECULAR_AMOUNT = 0.0;
        EMISSIVE_COLOR = pow(t, vec3(2.2));
        return;
    }
    float down = clamp(-n.y, 0.0, 1.0);
    if (uMode > 0.5) {                                   // the UV checker
        vec2 c = floor(fract(uv) * 8.0);
        float k = mod(c.x + c.y, 2.0);
        vec3 tint = vec3(0.35 + 0.55 * fract(uv.x), 0.45, 0.35 + 0.55 * fract(uv.y));
        vec3 col = mix(vec3(0.92), tint, k);
        BASE_COLOR = vec4(col, 1.0);
        ROUGHNESS = 0.8;
        METALNESS = 0.0;
        EMISSIVE_COLOR = col * (0.08 + 0.3 * down * down);
        return;
    }
    if (uHasNrm > 0.5 && uNrmOn > 0.5) {
        n = mappedNormal(n, uv);
        NORMAL = n;
        down = clamp(-n.y, 0.0, 1.0);
    }
    vec3 base = uColor.rgb;
    float rough = 0.84;
    float metal = 0.0;
    float ao = 1.0;
    if (uHasTex > 0.5)
        base = pow(texture(uBase, uv).rgb, vec3(2.2));
    if (uHasOrm > 0.5) {
        vec3 orm = texture(uOrm, uv).rgb;
        ao = orm.r;
        rough = orm.g;
        metal = orm.b;
    }
    vec3 glow = uHasEmi > 0.5 ? pow(texture(uEmissive, uv).rgb, vec3(2.2)) : vec3(0.0);
    BASE_COLOR = vec4(base, 1.0);
    ROUGHNESS = clamp(rough, 0.04, 1.0);
    METALNESS = metal;
    EMISSIVE_COLOR = base * ao * (0.06 + 0.34 * down * down) * (1.0 - 0.7 * metal) + glow;
}
