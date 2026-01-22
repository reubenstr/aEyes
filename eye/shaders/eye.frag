#version 150 core

in vec2 v_uv;
out vec4 fragColor;

uniform float iTime;
uniform vec2  iResolution;

// Piglet controls
uniform float blink;       // 0..1
uniform float pupilSize;   // ~0.1..1.0
uniform float rAmp;        // zoom control

#define TAU 6.28318530718

float gTime;
float flareUp;

// ======================================================
// Utility
float LinearStep(float a, float b, float x)
{
    return clamp((x - a) / (b - a), 0.0, 1.0);
}

// ======================================================
// Hash + procedural value noise (NO TEXTURES)

float hash1(float n)
{
    return fract(sin(n) * 43758.5453123);
}

float hash3(vec3 p)
{
    return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453123);
}

float Noise(vec3 x)
{
    vec3 p = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);

    float n000 = hash3(p + vec3(0,0,0));
    float n100 = hash3(p + vec3(1,0,0));
    float n010 = hash3(p + vec3(0,1,0));
    float n110 = hash3(p + vec3(1,1,0));
    float n001 = hash3(p + vec3(0,0,1));
    float n101 = hash3(p + vec3(1,0,1));
    float n011 = hash3(p + vec3(0,1,1));
    float n111 = hash3(p + vec3(1,1,1));

    float nx00 = mix(n000, n100, f.x);
    float nx10 = mix(n010, n110, f.x);
    float nx01 = mix(n001, n101, f.x);
    float nx11 = mix(n011, n111, f.x);

    float nxy0 = mix(nx00, nx10, f.y);
    float nxy1 = mix(nx01, nx11, f.y);

    return mix(nxy0, nxy1, f.z);
}

// ======================================================
// Pupil shape

float PupilShape(vec3 p, float r)
{
    p.xz = abs(p.xz) + 0.25;
    return length(p) - r;
}

float DE_Pupil(vec3 p)
{
    p *= vec3(1.2, 0.155, 1.0);
    p += vec3(0.0, 0.0, 4.0);

    float r = 0.78 * clamp(pupilSize, 0.05, 2.0);
    float d = PupilShape(p, r);

    return d * max(1.0, abs(p.y * 2.5));
}

// ======================================================
// Volumetric fire

float DE_Fire(vec3 p)
{
    p *= vec3(1.0, 1.0, 1.5);
    float len = length(p);

    float ax = atan(p.y, p.x) * 10.0;
    float ay = atan(p.y, p.z) * 10.0;

    vec3 shape = vec3(len * 0.5 - gTime * 1.2, ax, ay) * 2.0;

    shape += 2.5 * (
        Noise(p * 0.25) -
        Noise(p * 0.5) * 0.5 +
        Noise(p * 2.0) * 0.25
    );

    float f = Noise(shape) * 6.0;

    f += (LinearStep(7.3, 8.3 + flareUp, len) *
          LinearStep(12.0 + flareUp * 2.0, 8.0, len)) * 3.0;

    p *= vec3(0.75, 1.2, 1.0);
    len = length(p);
    f = mix(f, 0.0, LinearStep(12.5 + flareUp, 16.5 + flareUp, len));

    return f;
}

// ======================================================
vec3 FlameColour(float f)
{
    f = f * f * (3.0 - 2.0 * f);
    return min(vec3(f + 0.8, f * f * 1.4 + 0.05, f * f * f * 0.6) * f, 1.0);
}

// ======================================================
// Raymarch

vec4 Raymarch(vec3 ro, vec3 rd, out float pupilAcc)
{
    float sum = 0.0;
    float t = 14.0;
    pupilAcc = 0.0;

    for (int i = 0; i < 190; i++)
    {
        if (t > 37.0) break;

        vec3 pos = ro + t * rd;

        float dP = DE_Pupil(pos);

        pupilAcc += LinearStep(
            0.02 + Noise(pos * 4.0 + gTime) * 0.3,
            0.0,
            dP
        ) * 0.17;

        sum += LinearStep(1.3, 0.0, dP) * 0.014;
        sum += max(DE_Fire(pos), 0.0) * 0.00162;

        t += max(0.1, t * 0.0057);
    }

    return vec4(0.0, 0.0, 0.0, clamp(sum * sum * sum, 0.0, 1.0));
}

// ======================================================
// Blink mask

float BlinkMask(vec2 p, float b)
{
    float y = abs(p.y);
    float curve = 0.15 * p.x * p.x;
    float thresh = mix(1.0, 0.02, clamp(b, 0.0, 1.0));
    float lid = smoothstep(thresh - 0.03, thresh + 0.03, y + curve);
    return 1.0 - lid;
}

// ======================================================
void main()
{
    gTime   = iTime + 44.29;
    flareUp = max(sin(gTime * 0.75 + 3.5), 0.0);

    vec2 uv = gl_FragCoord.xy / iResolution.xy;
    vec2 p  = -1.0 + 2.0 * uv;
    p.x *= iResolution.x / iResolution.y;

    vec3 origin = vec3(0.0, -10.0, -20.0);
    vec3 target = vec3(0.0);

    vec3 cw = normalize(target - origin);
    vec3 cp = vec3(0.0, 1.0, 0.0);
    vec3 cu = normalize(cross(cw, cp));
    vec3 cv = cross(cu, cw);

    float fov = max(0.2, rAmp);
    vec3 rd = normalize(p.x * cu + p.y * cv + fov * cw);

    float pupilAcc;
    vec4 rm = Raymarch(origin, rd, pupilAcc);

    vec3 col = vec3(0.0);
    col += FlameColour(rm.w);
    col = mix(col, vec3(0.0), clamp(pupilAcc, 0.0, 1.0));

    col *= BlinkMask(p, blink);

    col = sqrt(col);
    col = min(mix(vec3(length(col)), col, 1.22), 1.0);
    col += col * 0.3;

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
