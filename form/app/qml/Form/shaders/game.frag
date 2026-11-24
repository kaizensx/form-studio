// A game asset's LOD (GameSheet): uMode 0 shaded with its baked maps (base colour; roughness and metallic from the
// ORM map's G and B, occlusion from its R), 1 a UV checker (8 x 8 squares over 0..1, tinted by u and v so a flipped
// or rotated island shows), 2 one baked map as it is stored (uShow; shown so the screen pixel is the texel value).
// Without baked maps the part is clay. Scene space is Y-up: the ambient bounce comes from the floor, as in clay.frag.
void MAIN()
{
    vec2 uv = UV0;
    vec3 n = normalize(NORMAL);
    float down = clamp(-n.y, 0.0, 1.0);
    if (uMode > 1.5) {                                   // one map, unlit
        vec3 t = texture(uShow, uv).rgb;
        BASE_COLOR = vec4(0.0, 0.0, 0.0, 1.0);
        ROUGHNESS = 1.0;
        METALNESS = 0.0;
        SPECULAR_AMOUNT = 0.0;
        EMISSIVE_COLOR = pow(t, vec3(2.2));
        return;
    }
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
    BASE_COLOR = vec4(base, 1.0);
    ROUGHNESS = clamp(rough, 0.04, 1.0);
    METALNESS = metal;
    EMISSIVE_COLOR = base * ao * (0.06 + 0.34 * down * down) * (1.0 - 0.7 * metal);
}
