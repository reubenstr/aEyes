#version 150 core

/*
    Original shader sourced from: https://www.shadertoy.com/view/lsfGRr
    By: Beautypi

    Heavily modified with color, pupil, motion additions and controls, etc.
*/

in vec2 v_uv;
out vec4 fragColor;

uniform float iTime;
uniform vec2 iResolution;
uniform float radius;
uniform vec3 irisColor;
uniform vec3 striationColor;
uniform float eyeLidPosition;
uniform bool isCatEye;

// Rotation applied at each fbm octave to avoid axis-aligned artifacts
const mat2 FBM_ROT = mat2(0.80, 0.60, -0.60, 0.80);

float hash1(float n)
{
    return fract(sin(n) * 43758.5453);
}

// Value noise with smooth (C1) interpolation
float noise(vec2 x)
{
    vec2 i = floor(x);
    vec2 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);

    float n = i.x + i.y * 57.0;
    return mix(mix(hash1(n +  0.0), hash1(n +  1.0), f.x),
               mix(hash1(n + 57.0), hash1(n + 58.0), f.x), f.y);
}

// Fractal Brownian Motion — 5 octaves, normalized to [0, 1]
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

// Eyelid mask: 1 = fully open, 0 = fully closed.
// The open region is a parabolic band — wide at center, pinched at corners.
float eyelidMask(vec2 p, float blinkAmt)
{
    if (blinkAmt >= 1.0) return 1.0;

    float edge = blinkAmt * (1.0 - p.x * p.x);

    return smoothstep(edge + 0.01, edge - 0.01, p.y)
         * smoothstep(-edge - 0.01, -edge + 0.01, p.y);
}

void main()
{
    vec2 fragCoord = v_uv * iResolution;

    // Normalized coords: y-corrected, centered, [-1, 1] range
    vec2 p = (2.0 * fragCoord - iResolution.xy) / iResolution.y;
    float r = length(p) * (1.0 + radius * clamp(1.0 - length(p), 0.0, 1.0));
    float a = atan(p.y, p.x);

    // Iris base color
    vec3 col = mix(irisColor, vec3(0.2, 0.5, 0.4), fbm(5.0 * p));

    // Iris limbal darkening
    float ikx = isCatEye ? 1.2 : 2.0;
    vec2 iu = abs(p / vec2(isCatEye ? 0.7 : 1.0, 1.0));
    float ir = pow(pow(iu.x, ikx) + pow(iu.y, 2.0), 1.0 / ikx);
    col = mix(col, vec3(0.1), 1.0 - smoothstep(0.22, 0.65, ir));

    // Striation distortion (slow time-based drift)
    a += 0.05 * fbm(20.0 * p + vec2(iTime, iTime * 0.7));

    // Striation splotching
    float splotch = smoothstep(0.4, 0.9, fbm(vec2(15.0 * a, 10.0 * r)));
    col *= 1.0 - 0.5 * splotch;

    // Striation fibers
    float striation = smoothstep(0.3, 1.0, fbm(vec2(20.0 * a, 6.0 * r)));
    col = mix(col, striationColor, striation);

    // Edge darkening
    col *= 1.0 - 0.25 * smoothstep(0.6, 0.8, r);

    // Radial/angular shadow variation
    col *= vec3(0.8 + 0.2 * cos(r * a));

    // Pupil
    float center = smoothstep(0.0, 0.4, 1.0 - r);
    float pupilDilate = mix(1.0, 0.6, center * radius);

    float kx = isCatEye ? 1.0 : 2.0;
    vec2 u = abs(p / vec2(isCatEye ? 0.5 : 1.0, 1.0));
    float pr = pow(pow(u.x, kx) + pow(u.y, 2.0), 1.0 / kx);
    float pupil = 1.0 - smoothstep(0.20 * pupilDilate, 0.25 * pupilDilate, pr);
    col = mix(col, vec3(0.0), pupil);

    // Sclera border: crops iris to a soft circle
    float blur = 3.0 * fwidth(r);
    col = mix(col, vec3(0.0), smoothstep(0.8 - blur, 0.8 + blur, r));

    // Vignette
    vec2 q = fragCoord / iResolution.xy;
    float vignette = pow(16.0 * q.x * q.y * (1.0 - q.x) * (1.0 - q.y), 0.1);
    col *= 0.5 + 0.5 * vignette;

    // Eyelid mask + cast shadow as it closes
    float lid = eyelidMask(p, eyeLidPosition);
    float lidShadow = mix(0.0, 0.35, smoothstep(0.2, 0.9, eyeLidPosition));
    col *= mix(1.0 - lidShadow, 1.0, lid);

    fragColor = vec4(col * lid, 1.0);
}
