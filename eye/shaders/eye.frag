#version 150 core

/*
    Original shader sourced from: https://www.shadertoy.com/view/lsfGRr
    By: Beautypi

    Heavily modified with color, pupil, motion additions and controls, etc.
*/

in vec2 v_uv;
out vec4 fragColor;

uniform float iTime;
uniform vec2  iResolution;
uniform float radius;
uniform vec3 irisColor;   
uniform vec3 corneaColor;   
uniform float eyeLidPosition; 
uniform bool isCatEye;


const mat2 m = mat2( 0.80,  0.60, -0.60,  0.80 );

float hash1( float n ) 
{ 
    return fract(sin(n)*43758.5453);
}

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
    float openness = mix(0.0, 0.8, blinkAmt);

    //float top = 0.52 * openness;
    //float bot = 0.42 * openness;
    float top = openness;
    float bot =  openness;

    float cornerExtent = 1.0; // >1 pushes corners outward

    // p.x is expected to be normalized so edges are at |x|=1
    float x = p.x / cornerExtent; //clamp(abs(p.x), 0.0, 1.0);
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
    vec2 p = (2.0 *fragCoord - iResolution.xy) / iResolution.y;
    float r = length(p) * (1.0 + radius * clamp(1.0 - length(p), 0.0, 1.0));
    float a = atan( p.y, p.x );    
 
    // iris color
    vec3 col = irisColor;
    float f = fbm( 5.0*p );
    col = mix( col, vec3(0.2,0.5,0.4), f );

    // shade around iris, scales with cat eye
    vec2 irisScale = vec2(isCatEye ? 0.7 : 1.0, 1.0);
    vec2 iu = abs(p / irisScale);
    float ikx = isCatEye ? 1.2 : 2.0; // softer than pupil
    float iky = 2.0;
    float ir = pow(pow(iu.x, ikx) + pow(iu.y, iky), 1.0 / ikx);
    float irisShade = 1.0 - smoothstep(0.22, 0.65, ir);
    col = mix(col, vec3(0.1,0.1,0.1), irisShade);

    // cornea splotching
    f = smoothstep( 0.4, 0.9, fbm( vec2(15.0*a,10.0*r) ) );
    col *= 1.0 - 0.5*f;

    // cornea distorion (motion)
    a += 0.05*fbm( 20.0*p + vec2(iTime, iTime) );

    // cornea
    f = smoothstep( 0.3, 1.0, fbm( vec2(20.0*a,6.0*r) ) );
    col = mix( col, corneaColor, f );

    // darkening outer edges
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
    float center = smoothstep(0.0, 0.4, 1.0 - r);
    float pupilDilate = mix(1.0, 0.6, center * radius);

    vec2 pupilScale = vec2(isCatEye ? 0.5 : 1.0, 1.0);
    vec2 u = abs(p / pupilScale);
    float kx = isCatEye ? 1.0 : 2.0; 
    float ky = 2.0;
    float pr = pow(pow(u.x, kx) + pow(u.y, ky), 1.0 / kx); 
    float inner = 0.2  * pupilDilate;
    float outer = 0.25 * pupilDilate;
    f = 1.0 - smoothstep(inner, outer, pr);
    col = mix(col, vec3(0.0), f);

    // crop to circle with edge blur (sclera color)
    float edge = 0.8;
    float blur = 3.0 * fwidth(r); 
    f = smoothstep(edge - blur, edge + blur, r);
    //vec3 scleraColor = vec3(0.8, 0.8, 0.8);
    vec3 scleraColor = vec3(0.0, 0.0, 0.0);
    col = mix(col, scleraColor, f);

    // vignetting
    vec2 q = fragCoord / iResolution.xy;
    col *= 0.5 + 0.5*pow(16.0*q.x*q.y*(1.0-q.x)*(1.0-q.y),0.1);

    // Apply eyelid mask + a little lid shadow as it closes
    float lid = eyelidMask(p, eyeLidPosition);
    float lidShadow = mix(0.0, 0.35, smoothstep(0.2, 0.9, eyeLidPosition));
    col *= mix(1.0 - lidShadow, 1.0, lid);

    outColor = vec4( col * lid, 1.0 );
}

void main() {
    vec2 fragCoord = v_uv * iResolution;
    mainImage(fragColor, fragCoord);
}
