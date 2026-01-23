#version 150 core

in vec2 position;  
out vec2 v_uv;

uniform float rotation;  

const float DEG2RAD = 3.14159265358979323846 / 180.0;

void main() {
    float r = rotation * DEG2RAD;

    mat2 rot = mat2(
        cos(r), -sin(r),
        sin(r),  cos(r)
    );
    vec2 pos = rot * position;

    gl_Position = vec4(pos, 0.0, 1.0);    
    v_uv = position * 0.5 + 0.5;
}
