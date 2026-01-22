#version 150 core
in vec2 position;
out vec2 v_uv;

void main() {
    v_uv = (position + 1.0) * 0.5;
    gl_Position = vec4(position, 0.0, 1.0);
}
