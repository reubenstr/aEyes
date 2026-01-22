#version 150 core

in vec2 v_uv;
out vec4 fragColor;

uniform float iTime;
uniform vec2  iResolution;
uniform float rAmp;
uniform float blink;
uniform float pupilSize;

const mat2 m = mat2( 0.80,  0.60, -0.60,  0.80 );

float hash1( float n ) { return fract(sin(n)*43758.5453); }

float noise( in vec2 x )
{
    vec2 i = floor(x);
    vec2 f = fract(x);
    f = f*f*(3.0-2.0*f);

    float n = i.x + i.y*57.0;

    return mix(mix( hash1(n+ 0.0), hash1(n+ 1.0),f.x),
               mix( hash1(n+57.0), hash1(n+58.0),f.x),f.y);
}

float fbm( vec2 p )
{
    float f = 0.0;
    f += 0.50000*noise( p ); p = m*p*2.02;
    f += 0.25000*noise( p ); p = m*p*2.03;
    f += 0.12500*noise( p ); p = m*p*2.01;
    f += 0.06250*noise( p ); p = m*p*2.04;
    f += 0.03125*noise( p );
    return f/0.984375;
}

float length2( vec2 p )
{
    vec2 q = p*p*p*p;
    return pow( q.x + q.y, 1.0/4.0 );
}

// A soft eyelid mask: when blink->1, visible opening narrows to a line.
float eyelidMask(vec2 p, float blinkAmt)
{
    float closed   = smoothstep(0.0, 1.0, blinkAmt);
    float openness = mix(1.0, 0.02, closed);

    float top = 0.52 * openness;
    float bot = 0.42 * openness;

    // p.x is expected to be normalized so edges are at |x|=1
    float x = p.x; //clamp(abs(p.x), 0.0, 1.0);
    float x2 = x*x;

    // Make edges hit 0 at x=1 (corners exactly at screen edges)
    float topEdge = top * (1.0 - x2);
    float botEdge = bot * (1.0 - x2);

    // Optional: slightly different shaping for upper/lower lids
    // topEdge = top * (1.0 - pow(x, 2.2));
    // botEdge = bot * (1.0 - pow(x, 1.8));

    float inside = 1.0;
    inside *= smoothstep(topEdge + 0.010, topEdge - 0.010, p.y);
    inside *= smoothstep(-botEdge - 0.010, -botEdge + 0.010, p.y);

    return inside;
}

void mainImage( out vec4 outColor, in vec2 fragCoord )
{
    vec2 p = (2.0*fragCoord - iResolution.xy) / iResolution.y;

    // Apply eyelid opening (blink)
    float lid = eyelidMask(p, blink);

    // If fully closed, draw a subtle lash/crease line instead of pure white
    if (lid < 0.02) {
        float crease = exp(-abs(p.y) * 180.0) * exp(-abs(p.x) * 3.0);
        vec3 lash = vec3(0.04, 0.03, 0.03) * (0.35 + 0.65 * crease);
        outColor = vec4(lash, 1.0);
        return;
    }

    // polar coordinates
    float r = length( p );
    float a = atan( p.y, p.x );

    // animate (controlled from Python)
    //r *= 1.0 + rAmp * clamp(1.0 - r, 0.0, 1.0) * sin(4.0 * iTime);
    r *= 1.0 + rAmp * clamp(1.0 - r, 0.0, 1.0);


    // iris (blue-green)
    vec3 col = vec3( 0.0, 0.3, 0.4 );
    float f = fbm( 5.0*p );
    col = mix( col, vec3(0.2,0.5,0.4), f );

    // yellow towards center
    col = mix( col, vec3(0.9,0.6,0.2), 1.0 - smoothstep(0.2,0.6,r) );

    // darkening
    f = smoothstep( 0.4, 0.9, fbm( vec2(15.0*a,10.0*r) ) );
    col *= 1.0 - 0.5*f;

    // distort
    a += 0.05*fbm( 20.0*p + vec2(iTime, iTime) );

    // cornea
    f = smoothstep( 0.3, 1.0, fbm( vec2(20.0*a,6.0*r) ) );
    col = mix( col, vec3(1.0,1.0,1.0), f );

    // edges
    col *= 1.0 - 0.25*smoothstep( 0.6,0.8,r );

    // highlight
    f = 1.0 - smoothstep(
        0.0, 0.6,
        length2( mat2(0.6,0.8,-0.8,0.6) * (p - vec2(0.3,0.5)) * vec2(1.0,2.0) )
    );
    // col += vec3(1.0,0.9,0.9)*f*0.985;

    // shadow
    col *= vec3(0.8 + 0.2*cos(r*a));

    // pupil
    f = 1.0 - smoothstep( 0.2 * pupilSize, 0.25 * pupilSize, r );
    col = mix( col, vec3(0.0), f );

    // crop
    f = smoothstep( 0.79, 0.82, r );
    col = mix( col, vec3(1.0), f );

    // vignetting
    vec2 q = fragCoord / iResolution.xy;
    col *= 0.5 + 0.5*pow(16.0*q.x*q.y*(1.0-q.x)*(1.0-q.y),0.1);

    // Apply eyelid mask + a little lid shadow as it closes
    float lidShadow = mix(0.0, 0.35, smoothstep(0.2, 0.9, blink));
    col *= mix(1.0 - lidShadow, 1.0, lid);

    outColor = vec4( col * lid, 1.0 );
}

void main() {
    vec2 fragCoord = v_uv * iResolution;
    mainImage(fragColor, fragCoord);
}
