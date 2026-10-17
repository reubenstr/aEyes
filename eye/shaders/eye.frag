#version 300 es

/*
    Original shader sourced from: https://www.shadertoy.com/view/lsfGRr
    By: Beautypi

    Heavily modified by adding colors, veins, eyelids, and controls.
*/

precision highp float;
precision highp int;

in vec2 v_uv;
out vec4 fragColor;

uniform float iTime;
uniform vec2 iResolution;

uniform float rotation;
uniform float curved;
uniform float radius;
uniform float eyeLidPosition;

uniform bool isCatEye;
uniform float irisSize;
uniform float pupilSize;

uniform float numVeins;
uniform float veinSeed;

uniform vec3 irisColor;
uniform vec3 irisAccentColor;
uniform vec3 irisCenterColor;
uniform vec3 striationColor;
uniform vec3 pupilColor;
uniform vec3 scleraColor;
uniform vec3 veinColor;

const mat2 FBM_ROT = mat2(0.80, 0.60, -0.60, 0.80);
const int MAX_VEINS = 24;
const int MAX_FORKS = 3;
const int VEIN_KNOTS = 8;
const float PI = 3.14159265358979323846;
const float TAU = 6.28318530717958647692;
const float IRIS_MIN = 0.20;
const float IRIS_MAX = 0.70;
const float IRIS_EDGE_SOFT = 0.02;
const float PUPIL_MIN = 0.15;
const float PUPIL_MAX = 0.85;
const float PUPIL_DILATE = 0.25;
const float IRIS_REF_PUPIL = 0.25;
const float IRIS_REF_EDGE = 0.80;
const float IRIS_ACCENT_SCALE = 5.0;
const float IRIS_CENTER_INNER = 0.20;
const float IRIS_CENTER_OUTER = 0.60;
const float IRIS_SHADOW_ANGULAR = 15.0;
const float IRIS_SHADOW_RADIAL = 10.0;
const float IRIS_SHADOW_STRENGTH = 0.50;
const float IRIS_DISTORT = 0.05;
const float IRIS_DISTORT_SCALE = 20.0;
const float IRIS_EDGE_DARKEN = 0.25;
const float STRIATION_ANGULAR = 20.0;
const float STRIATION_RADIAL = 6.0;
const float SCLERA_BLOTCH = 0.15;
const float SCLERA_BLOTCH_SCALE = 8.0;
const float RIM_SHADE = 0.3;
const float RIM_SHADE_WIDTH = 0.1;
const float RIM_BLUR = 0.004;
const float LID_SOFT = 0.01;
const float VEIN_STRENGTH = 0.30;
const float VEIN_WIDTH = 0.0055;
const float VEIN_FEATHER = 0.0065;
const float VEIN_STEP = 0.026;
const float VEIN_STEP_FINE = 0.015;
const float VEIN_FADE = 0.35;
const float VEIN_FORK_BIAS = 0.0035;
const float VEIN_REACH = 0.120;
const float VEIN_INNER_REACH = 0.18;

float hash1(float n)
{
    return fract(sin(n) * 43758.5453);
}

float hash2(vec2 c)
{
    return fract(sin(dot(c, vec2(12.9898, 78.233))) * 43758.5453);
}

float vhash(float index, float salt)
{
    return hash2(vec2(index * 0.7548776 + veinSeed * 37.0, salt));
}

float irisEdge()
{
    return mix(IRIS_MIN, IRIS_MAX, clamp(irisSize, 0.0, 1.0));
}

float irisMetric(vec2 q)
{
    float kx = isCatEye ? 1.2 : 2.0;
    vec2 u = abs(q / vec2(isCatEye ? 0.7 : 1.0, 1.0));
    return pow(pow(u.x, kx) + pow(u.y, 2.0), 1.0 / kx);
}

float wrapAngle(float d)
{
    return d - TAU * floor(d / TAU + 0.5);
}

float veinAngle(float k, float slot, float count, float interleave)
{
    float sector = TAU / count;
    float jitter = vhash(k * 7.0 + 1.0, 91.0) - 0.5;
    return -PI + sector * (slot + 0.5 + 0.9 * jitter + interleave);
}

void mainVeinShape(float k, out float tInner, out float halfWidth, out float strength)
{
    tInner = VEIN_INNER_REACH + 0.04 * vhash(k, 12.0);
    halfWidth = VEIN_WIDTH * (0.75 + 0.45 * vhash(k, 34.0));
    strength = 0.75 + 0.25 * vhash(k, 45.0);
}

float veinCenter(float k, float stepSize, float damping, float bias, float u)
{
    float pos = u * float(VEIN_KNOTS - 1);
    int j = clamp(int(floor(pos)), 0, VEIN_KNOTS - 2);
    float f = pos - float(j);
    int i0 = max(j - 1, 0);
    int i3 = min(j + 2, VEIN_KNOTS - 1);

    float p0 = 0.0;
    float p1 = 0.0;
    float p2 = 0.0;
    float p3 = 0.0;

    float offset = 0.0;
    for (int i = VEIN_KNOTS - 1; i >= 0; i--)
    {
        if (i == i0) p0 = offset;
        if (i == j) p1 = offset;
        if (i == j + 1) p2 = offset;
        if (i == i3) p3 = offset;

        offset = offset * damping + bias
               + (vhash(k * float(VEIN_KNOTS) + float(i), 56.0) - 0.5) * stepSize;
    }

    return 0.5 * (2.0 * p1
                + (-p0 + p2) * f
                + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * f * f
                + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * f * f * f);
}

float veinStrand(float k, float lateral, float t, float tInner, float tOuter,
                 float halfWidth, float strength, float stepSize,
                 float damping, float bias, float start, float fadeOuterTip)
{
    if (tOuter <= tInner || t < tInner || t > tOuter) return 0.0;

    float u = (t - tInner) / (tOuter - tInner);
    float center = start + veinCenter(k, stepSize, damping, bias, u);
    float width = halfWidth * (0.30 + 0.70 * u);

    float s = 1.0 - smoothstep(width, width + VEIN_FEATHER, abs(lateral - center));
    s *= smoothstep(0.0, VEIN_FADE, u);
    s *= mix(1.0, 1.0 - smoothstep(0.85, 1.0, u), fadeOuterTip);
    return s * strength;
}

float veins(float t, float r, float a)
{
    if (t < VEIN_INNER_REACH || t > 1.05) return 0.0;

    if (numVeins < 1.0) return 0.0;

    float nLong = clamp(floor(numVeins), 1.0, float(MAX_VEINS));
    float nFine = min(floor(nLong * 1.5), float(MAX_VEINS));
    float cover = 0.0;

    for (int i = 0; i < MAX_VEINS; i++)
    {
        float k = float(i);
        if (k >= nLong) break;

        float lateral = wrapAngle(a - veinAngle(k, k, nLong, 0.0)) * r;
        if (abs(lateral) > VEIN_REACH) continue;

        float tInner, halfWidth, strength;
        mainVeinShape(k, tInner, halfWidth, strength);
        cover = max(cover, veinStrand(k, lateral, t, tInner, 1.0, halfWidth,
                                      strength, VEIN_STEP, 0.9, 0.0, 0.0, 0.0));
    }

    for (int i = 0; i < MAX_VEINS; i++)
    {
        float slot = float(i);
        if (slot >= nFine) break;

        float k = nLong + slot;
        float lateral = wrapAngle(a - veinAngle(k, slot, nFine, 0.5)) * r;
        if (abs(lateral) > VEIN_REACH) continue;

        float tInner = max(VEIN_INNER_REACH, 0.40 + 0.25 * vhash(k, 12.0));
        float tOuter = 0.80 + 0.20 * vhash(k, 23.0);
        cover = max(cover, veinStrand(k, lateral, t, tInner, tOuter,
                                      VEIN_WIDTH * 0.6,
                                      0.55 * (0.75 + 0.25 * vhash(k, 45.0)),
                                      VEIN_STEP_FINE, 0.9, 0.0, 0.0, 1.0));
    }

    float group = floor(nLong / float(MAX_FORKS));
    for (int b = 0; b < MAX_FORKS; b++)
    {
        if (group < 1.0) break;

        float k = nLong + nFine + float(b);
        float parent = float(b) * group + floor(vhash(k, 78.0) * group);

        float lateral = wrapAngle(a - veinAngle(parent, parent, nLong, 0.0)) * r;
        if (abs(lateral) > VEIN_REACH * 2.5) continue;

        float parentInner, parentWidth, parentStrength;
        mainVeinShape(parent, parentInner, parentWidth, parentStrength);

        float uFork = (4.0 + floor(vhash(k, 89.0) * 3.0)) / float(VEIN_KNOTS - 1);
        float tOuter = parentInner + (1.0 - parentInner) * uFork;
        float tInner = VEIN_INNER_REACH + 0.20 + 0.10 * vhash(k, 12.0);
        float start = veinCenter(parent, VEIN_STEP, 0.9, 0.0, uFork);
        float dir = vhash(k, 91.0) < 0.5 ? -1.0 : 1.0;

        cover = max(cover, veinStrand(k, lateral, t, tInner, tOuter,
                                      parentWidth * 0.7, parentStrength * 0.85,
                                      VEIN_STEP_FINE, 1.0, dir * VEIN_FORK_BIAS,
                                      start, 0.0));
    }

    return cover * VEIN_STRENGTH;
}

float noise(vec2 x)
{
    vec2 i = floor(x);
    vec2 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);

    float n = i.x + i.y * 57.0;
    return mix(mix(hash1(n +  0.0), hash1(n +  1.0), f.x),
               mix(hash1(n + 57.0), hash1(n + 58.0), f.x), f.y);
}

float fbm(vec2 p)
{
    float f = 0.0;
    f += 0.50000 * noise(p); p = FBM_ROT * p * 2.02;
    f += 0.25000 * noise(p); p = FBM_ROT * p * 2.03;
    f += 0.12500 * noise(p); p = FBM_ROT * p * 2.01;
    f += 0.06250 * noise(p); p = FBM_ROT * p * 2.04;
    f += 0.03125 * noise(p);
    return f / 0.984375;
}

float eyelidMask(vec2 w, float blinkAmt)
{
    if (blinkAmt >= 1.0) return 1.0;
    if (blinkAmt <= 0.0) return 0.0;

    float span = radius + LID_SOFT;
    float x = clamp(w.x / span, -1.0, 1.0);
    float aperture = blinkAmt * span * sqrt(1.0 - x * x);

    return 1.0 - smoothstep(aperture - LID_SOFT, aperture + LID_SOFT, abs(w.y));
}

void main()
{
    vec2 fragCoord = v_uv * iResolution;

    vec2 p = (2.0 * fragCoord - iResolution.xy) / iResolution.y;

    float _r = rotation * (3.14159265358979323846 / 180.0);
    p = mat2(cos(_r), sin(_r), -sin(_r), cos(_r)) * p;
    float r = length(p) * (1.0 + curved * clamp(1.0 - length(p), 0.0, 1.0));

    vec2 pCurved = p * (r / max(length(p), 1e-4));
    float lid = eyelidMask(pCurved, eyeLidPosition);
    float coverage = 1.0 - smoothstep(radius - RIM_BLUR, radius + RIM_BLUR, r);
    if (r >= radius + RIM_BLUR)
    {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }
    if (lid <= 0.0)
    {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    float a = atan(p.y, p.x);

    float ir = irisMetric(pCurved);
    float edge = irisEdge();

    float center = smoothstep(0.0, 0.4, 1.0 - r);
    float dilation = clamp(pupilSize - PUPIL_DILATE * center * curved, 0.0, 1.0);
    float pupilRadius = edge * mix(PUPIL_MIN, PUPIL_MAX, dilation);

    vec2 pRef = pCurved * (IRIS_REF_EDGE / max(edge, 1e-4));
    float irisT = clamp((ir - pupilRadius) / max(edge - pupilRadius, 1e-4), 0.0, 1.0);
    float rRef = mix(IRIS_REF_PUPIL, IRIS_REF_EDGE, irisT);

    vec3 col = mix(irisColor, irisAccentColor, fbm(IRIS_ACCENT_SCALE * pRef));
    col = mix(col, irisCenterColor,
              1.0 - smoothstep(IRIS_CENTER_INNER, IRIS_CENTER_OUTER, rRef));

    float veinA = a;

    float shadow = smoothstep(0.4, 0.9, fbm(vec2(IRIS_SHADOW_ANGULAR * a,
                                                 IRIS_SHADOW_RADIAL * rRef)));
    col *= 1.0 - IRIS_SHADOW_STRENGTH * shadow;

    a += IRIS_DISTORT * fbm(IRIS_DISTORT_SCALE * pRef + vec2(iTime, iTime * 0.7));

    float striation = smoothstep(0.3, 1.0, fbm(vec2(STRIATION_ANGULAR * a,
                                                    STRIATION_RADIAL * rRef)));
    col = mix(col, striationColor, striation);

    col *= 1.0 - IRIS_EDGE_DARKEN * smoothstep(0.6, 0.8, rRef);

    col *= vec3(0.90 + 0.10 * cos(r * a));

    vec3 sclera = scleraColor * (1.0 - SCLERA_BLOTCH
                                 + SCLERA_BLOTCH * fbm(SCLERA_BLOTCH_SCALE * p));
    float rimMetric = irisMetric(pCurved * (radius / max(r, 1e-4)));
    float veinT = (ir - edge) / max(rimMetric - edge, 1e-4);
    sclera = mix(sclera, veinColor, veins(veinT, r, veinA));
    float scleraMix = smoothstep(edge - IRIS_EDGE_SOFT, edge + IRIS_EDGE_SOFT, ir);
    col = mix(col, sclera, scleraMix);

    float kx = isCatEye ? 1.0 : 2.0;
    vec2 u = abs(pCurved / vec2(isCatEye ? 0.5 : 1.0, 1.0));
    float pr = pow(pow(u.x, kx) + pow(u.y, 2.0), 1.0 / kx);
    float pupil = 1.0 - smoothstep(0.8 * pupilRadius, pupilRadius, pr);
    col = mix(col, pupilColor, pupil);

    col *= 1.0 - RIM_SHADE * smoothstep(radius - RIM_SHADE_WIDTH, radius, r);

    vec2 q = fragCoord / iResolution.xy;
    float vignette = pow(16.0 * q.x * q.y * (1.0 - q.x) * (1.0 - q.y), 0.1);
    col *= 0.5 + 0.5 * vignette;

    float lidShadow = mix(0.0, 0.35, smoothstep(0.2, 0.9, eyeLidPosition));
    col *= mix(1.0 - lidShadow, 1.0, lid);

    fragColor = vec4(col * lid * coverage, 1.0);
}
