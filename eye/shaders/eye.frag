#version 150 core

in vec2 v_uv;
out vec4 fragColor;

uniform float iTime;
uniform vec2  iResolution;

uniform float blink;       // 0..1
uniform float pupilSize;   // ~0.1..1.0
uniform float rAmp;        // zoom control

uniform sampler2D iChannel0;   // bound to unit 0

float gTime;
float flareUp;

// ===== Performance knobs (still Pi-friendly) =====
#define NOISE_SIZE 256.0
#define STEPS      88
#define TSTART     13.5
#define TMAX       37.0
#define STEP_MIN   0.16
#define STEP_REL   0.010

// ===== Look knobs (cheap brightness control) =====
#define FIRE_GAIN   1.65   // <— boost flame density
#define BASE_GAIN   1.25   // <— boost base “pupil haze” contribution
#define EXPOSURE    2.85   // <— final exposure boost
#define PUPIL_MIX  1  // <— less aggressive pupil darkening (0..1)

float LinearStep(float a, float b, float x)
{
    return clamp((x - a) / (b - a), 0.0, 1.0);
}

float Noise(in vec3 x)
{
    vec3 p = floor(x);
    vec3 f = fract(x);
    f = f*f*(3.0 - 2.0*f);

    vec2 uv = (p.xy + vec2(37.0, 17.0) * p.z) + f.xy;
    vec2 tuv = fract((uv + 0.5) / NOISE_SIZE);

    vec2 rg = textureLod(iChannel0, tuv, 0.0).yx;
    return mix(rg.x, rg.y, f.z);
}

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

float DE_Fire(vec3 p)
{
    p *= vec3(1.0, 1.0, 1.5);
    float len = length(p);

    float ax = atan(p.y, p.x) * 7.0;
    float ay = atan(p.y, p.z) * 7.0;

    vec3 shape = vec3(len * 0.5 - gTime * 1.15, ax, ay) * 1.8;

    float turb = Noise(p * 0.30) - 0.55 * Noise(p * 1.10);
    shape += 2.2 * turb;

    float f = Noise(shape) * 5.5;

    f += (LinearStep(7.3, 8.3 + flareUp, len) *
          LinearStep(12.0 + flareUp * 2.0, 8.0, len)) * 2.6;

    p *= vec3(0.75, 1.2, 1.0);
    len = length(p);
    f = mix(f, 0.0, LinearStep(12.2 + flareUp, 15.8 + flareUp, len));

    return f;
}

vec3 FlameColour(float f)
{
    f = f*f*(3.0 - 2.0*f);
    return min(vec3(f + 0.8, f*f*1.4 + 0.05, f*f*f*0.6) * f, 1.0);
}

vec4 Raymarch(vec3 ro, vec3 rd, out float pupilAcc)
{
    float sum = 0.0;
    float t = TSTART;
    pupilAcc = 0.0;

    for (int i = 0; i < STEPS; i++)
    {
        if (t > TMAX) break;

        vec3 pos = ro + t * rd;

        float dP = DE_Pupil(pos);

        // pupil accumulation (dark mask)
        pupilAcc += LinearStep(0.03 + Noise(pos * 3.0 + gTime) * 0.22, 0.0, dP) * 0.16;

        // Base “smoke” + fire, boosted
        sum += LinearStep(1.25, 0.0, dP) * (0.012 * BASE_GAIN);
        sum += max(DE_Fire(pos), 0.0) * (0.00145 * FIRE_GAIN);

        t += max(STEP_MIN, t * STEP_REL);
    }

    float dens = clamp(sum*sum*sum, 0.0, 1.0);
    return vec4(0.0, 0.0, 0.0, dens);
}

float BlinkMask(vec2 p, float b)
{
    float y = abs(p.y);
    float curve = 0.15 * p.x * p.x;
    float thresh = mix(1.0, 0.02, clamp(b, 0.0, 1.0));
    float lid = smoothstep(thresh - 0.03, thresh + 0.03, y + curve);
    return 1.0 - lid;
}

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

    float fov = 0.65 * max(0.25, rAmp);
    vec3 rd = normalize(p.x * cu + p.y * cv + fov * cw);

    float pupilAcc;
    vec4 rm = Raymarch(origin, rd, pupilAcc);

    vec3 col = vec3(0.0);
    col += FlameColour(rm.w);

    // less aggressive pupil darkening
    col = mix(col, vec3(0.0), clamp(pupilAcc, 0.0, 1.0) * PUPIL_MIX);

    col *= BlinkMask(p, blink);

    // exposure + mild contrast (cheap)
    col *= EXPOSURE;
    col = sqrt(max(col, 0.0));
    col = min(mix(vec3(length(col)), col, 1.20), 1.0);
    col += col * 0.20;

    fragColor = vec4(clamp(col, 0.0, 1.0), 1.0);
}
