import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { Trails, toBase } from "./data";
import type { RGB, Telemetry, Vec3 } from "./types";

const vector = (p: Vec3) => new THREE.Vector3(p.x, p.y, p.z);
const color = (rgb: RGB) => new THREE.Color(`rgb(${rgb.join(",")})`);

function label(text: string, faceColor?: RGB) {
  const canvas = document.createElement("canvas");
  canvas.width = 192;
  canvas.height = 128;
  const c = canvas.getContext("2d")!;
  if (faceColor) {
    const [r, g, b] = faceColor;
    const ink = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.35
      ? "#f5f5f5" : "#111111";
    c.fillStyle = `rgb(${faceColor.join(",")})`;
    c.beginPath();
    c.ellipse(96, 54, 29, 36, 0, 0, Math.PI * 2);
    c.fill();
    c.fillStyle = ink;
    c.beginPath();
    c.arc(85, 49, 3, 0, Math.PI * 2);
    c.fill();
    c.beginPath();
    c.arc(107, 49, 3, 0, Math.PI * 2);
    c.fill();
    c.fillRect(84, 65, 24, 4);
  }
  c.fillStyle = "#eeeeee";
  c.font = "500 24px monospace";
  c.textAlign = "center";
  c.fillText(text, 96, faceColor ? 119 : 74);
  const texture = new THREE.CanvasTexture(canvas);
  // Canvas colors are sRGB; treating them as linear lifts the midtones.
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthTest: false,
      fog: false,
      toneMapped: false,
    }),
  );
  sprite.scale.set(0.38, 0.25, 1);
  return sprite;
}

function dispose(object: THREE.Object3D) {
  object.traverse((o) => {
    const mesh = o as THREE.Mesh;
    mesh.geometry?.dispose();
    const materials = mesh.material
      ? Array.isArray(mesh.material)
        ? mesh.material
        : [mesh.material]
      : [];
    for (const material of materials) {
      (material as THREE.SpriteMaterial).map?.dispose();
      material.dispose();
    }
  });
}

export function Scene({ state }: { state: Telemetry | null }) {
  const host = useRef<HTMLDivElement>(null),
    latest = useRef(state);
  const [error, setError] = useState(""),
    [showTrails, setShowTrails] = useState(true);
  const trailsVisible = useRef(showTrails),
    reset = useRef<() => void>(() => {});
  latest.current = state;
  trailsVisible.current = showTrails;
  useEffect(() => {
    const element = host.current!;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setError("3D view needs WebGL. Camera and telemetry remain available.");
      return;
    }
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    element.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog("#242424", 12, 24);
    const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 40);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.minDistance = 0.8;
    controls.maxDistance = 12;
    reset.current = () => {
      camera.position.set(3.65, -3, 2.025);
      controls.target.set(1.1, 0, 0);
      controls.update();
    };
    reset.current();
    const grid = new THREE.GridHelper(10, 40, "#484848", "#323232");
    grid.rotation.x = Math.PI / 2;
    grid.position.set(2, 0, -0.65);
    scene.add(grid);
    const axes = new THREE.AxesHelper(0.32);
    axes.position.set(0, 0, -0.64);
    scene.add(axes);
    const dynamic = new THREE.Group();
    scene.add(dynamic);
    const trails = new Trails();
    let lastTimestamp: number | undefined;
    let lastVisibility = true;
    let lastStatus: string | undefined;
    function line(a: THREE.Vector3[], tint: THREE.Color | string, opacity = 1) {
      const g = new THREE.BufferGeometry().setFromPoints(a);
      if (a.length > 2) {
        const c = new THREE.Color(tint),
          colors: number[] = [];
        a.forEach((_, i) => {
          const fade = 0.12 + (0.88 * i) / a.length;
          colors.push(c.r * fade, c.g * fade, c.b * fade);
        });
        g.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
      }
      dynamic.add(
        new THREE.Line(
          g,
          new THREE.LineBasicMaterial({
            color: a.length > 2 ? "#ffffff" : tint,
            vertexColors: a.length > 2,
            transparent: true,
            opacity,
            fog: false,
          }),
        ),
      );
    }
    function update(s: Telemetry | null) {
      for (const child of [...dynamic.children]) {
        dynamic.remove(child);
        dispose(child);
      }
      if (!s || s.controller.status !== "running") {
        trails.points.clear();
        trails.capture = undefined;
        return;
      }
      trails.update(s);
      const cameraPosition = vector(s.geometry.camera);
      const cameraIcon = new THREE.Mesh(
        new THREE.BoxGeometry(0.055, 0.11, 0.07),
        new THREE.MeshBasicMaterial({ color: "#aaaaaa" }),
      );
      cameraIcon.position.copy(cameraPosition);
      dynamic.add(cameraIcon);
      const depth = 3,
        w =
          Math.tan(
            THREE.MathUtils.degToRad(s.geometry.camera.horizontal_fov / 2),
          ) * depth;
      const h =
        Math.tan(THREE.MathUtils.degToRad(s.geometry.camera.vertical_fov / 2)) *
        depth;
      const corners = [
        [depth, w, h],
        [depth, -w, h],
        [depth, -w, -h],
        [depth, w, -h],
      ].map((p) =>
        new THREE.Vector3(...(p as [number, number, number])).add(
          cameraPosition,
        ),
      );
      for (let i = 0; i < 4; i++) {
        line([cameraPosition, corners[i]], "#555555", 0.23);
        line([corners[i], corners[(i + 1) % 4]], "#555555", 0.23);
      }
      for (const cfg of s.geometry.eyes) {
        const eye = s.eyes.find((e) => e.eye_id === cfg.eye_id);
        const yaw = THREE.MathUtils.degToRad(eye?.yaw ?? 0),
          pitch = THREE.MathUtils.degToRad(eye?.pitch ?? 0);
        const pivot = vector(cfg.pitch_pivot_offset)
          .applyAxisAngle(new THREE.Vector3(0, 0, 1), yaw)
          .add(vector(cfg.position));
        const direction = new THREE.Vector3(
          Math.cos(pitch) * Math.cos(yaw),
          Math.cos(pitch) * Math.sin(yaw),
          Math.sin(pitch),
        );
        line([vector(cfg.position), pivot], "#666666");
        const group = new THREE.Group();
        group.position.copy(pivot);
        // Keep local Y upright as the eye turns, so eyelids close vertically.
        const horizontal = new THREE.Vector3(-Math.sin(yaw), Math.cos(yaw), 0);
        const up = new THREE.Vector3().crossVectors(direction, horizontal);
        group.quaternion.setFromRotationMatrix(
          new THREE.Matrix4().makeBasis(horizontal, up, direction),
        );
        const radius = 0.065,
          opening = THREE.MathUtils.clamp(eye?.eye_lid ?? 0.85, 0, 1);
        const sclera = new THREE.Mesh(
          new THREE.CircleGeometry(radius, 32),
          new THREE.MeshBasicMaterial({
            color: "#dddddd",
            side: THREE.DoubleSide,
          }),
        );
        group.add(sclera);
        const iris = new THREE.Mesh(
          new THREE.CircleGeometry(0.033, 24),
          new THREE.MeshBasicMaterial({
            color: eye ? color(eye.iris_color) : "#666666",
            side: THREE.DoubleSide,
          }),
        );
        iris.position.z = 0.001;
        group.add(iris);
        const pupil = new THREE.Mesh(
          new THREE.CircleGeometry(0.015, 16),
          new THREE.MeshBasicMaterial({
            color: "#151515",
            side: THREE.DoubleSide,
          }),
        );
        pupil.position.z = 0.002;
        group.add(pupil);
        // Cover the fixed eye with curved lids; the iris and pupil stay circular.
        if (opening < 1) {
          for (const upper of [true, false]) {
            const lid = new THREE.Shape();
            lid.absarc(0, 0, radius, Math.PI, upper ? 0 : 2 * Math.PI, upper);
            lid.absellipse(0, 0, radius, radius * opening, 0, upper ? Math.PI : -Math.PI, !upper);
            lid.closePath();
            const overlay = new THREE.Mesh(
              new THREE.ShapeGeometry(lid, 32),
              new THREE.MeshBasicMaterial({ color: "#353535", side: THREE.DoubleSide }),
            );
            overlay.position.z = 0.003;
            group.add(overlay);
            const edge = new THREE.EllipseCurve(
              0, 0, radius, radius * opening, 0, upper ? Math.PI : -Math.PI, !upper,
            );
            group.add(new THREE.Line(
              new THREE.BufferGeometry().setFromPoints(edge.getPoints(32).map(
                (p) => new THREE.Vector3(p.x, p.y, 0.004),
              )),
              new THREE.LineBasicMaterial({ color: "#1b1b1b" }),
            ));
          }
        }
        dynamic.add(group);
        const name = label(`E${cfg.eye_id}`);
        name.position.copy(pivot).add(new THREE.Vector3(0, 0, -0.12));
        dynamic.add(name);
        line(
          [pivot, pivot.clone().addScaledVector(direction, 0.32)],
          "#999999",
          0.8,
        );
        const face = s.faces.find((f) => f.id === eye?.face_id && f.visible);
        if (face && eye)
          line(
            [pivot, vector(toBase(face.position, s.geometry))],
            color(eye.target_iris_color),
            0.75,
          );
      }
      for (const face of s.faces.filter((f) => f.visible)) {
        const tint =
          s.eyes.find((e) => e.face_id === face.id)?.target_iris_color ??
          ([180, 180, 180] as RGB);
        const sprite = label(
          `#${face.id}${face.is_static ? " · static" : ""}`,
          tint,
        );
        sprite.position.copy(vector(toBase(face.position, s.geometry)));
        dynamic.add(sprite);
        const points = trails.points.get(face.id);
        if (trailsVisible.current && points && points.length > 1)
          line(points.map(vector), color(tint), 0.85);
      }
    }
    const resize = new ResizeObserver(() => {
      const { width, height } = element.getBoundingClientRect();
      camera.aspect = width / Math.max(height, 1);
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    });
    resize.observe(element);
    let frame = 0;
    function animate() {
      frame = requestAnimationFrame(animate);
      const s = latest.current;
      if (
        (s?.timestamp !== lastTimestamp ||
          trailsVisible.current !== lastVisibility ||
          s?.controller.status !== lastStatus)
      ) {
        update(s);
        lastTimestamp = s?.timestamp;
        lastVisibility = trailsVisible.current;
        lastStatus = s?.controller.status;
      }
      controls.update();
      renderer.render(scene, camera);
    }
    animate();
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      controls.dispose();
      dispose(scene);
      renderer.dispose();
      element.replaceChildren();
    };
  }, []);
  return (
    <section className="panel scene-panel">
      <div className="panel-title">
        <h2>Spatial View</h2>
        <div className="scene-tools">
          <button
            className={showTrails ? "active subtle" : "subtle"}
            onClick={() => setShowTrails(!showTrails)}
          >
            Trails
          </button>
          <button className="subtle" onClick={() => reset.current()}>
            Reset view
          </button>
        </div>
      </div>
      <div
        ref={host}
        className="scene-canvas"
        role="img"
        aria-label="3D eye positions, face trajectories and assignment lines"
      />
      {error && <div className="scene-error">{error}</div>}
      <div className="scene-legend">
        <span>
          <i className="dot accent" />
          Assigned gaze
        </span>
        <span>Drag to orbit · Scroll to zoom</span>
        <span>X forward / Y left / Z up · m</span>
      </div>
    </section>
  );
}
