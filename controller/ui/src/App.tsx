import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";
import { Settings } from "./Settings";
import { EyePreview } from "./EyePreview";
import { useTelemetry } from "./useTelemetry";
import type { Eye, Telemetry } from "./types";

const Scene = lazy(() => import("./Scene").then((m) => ({ default: m.Scene })));
const number = (value: number | null | undefined, digits = 1) =>
  value == null ? "—" : value.toFixed(digits);
const memory = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`;
const pages = [
  { id: "dashboard", path: "/", label: "Overview" },
  { id: "system", path: "/system", label: "System" },
  { id: "settings", path: "/settings", label: "Settings" },
] as const;
type Page = typeof pages[number]["id"];
const currentPage = (): Page => pages.find((page) => page.path === location.pathname)?.id ?? "dashboard";

function Logo() {
  return (
    <svg width="34" height="28" viewBox="0 0 34 28" aria-hidden="true">
      <path
        d="M2 14Q17-5 32 14Q17 33 2 14Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <circle cx="17" cy="14" r="6" fill="currentColor" />
      <circle cx="19" cy="12" r="2" fill="#171717" />
    </svg>
  );
}
function Dot({ good }: { good: boolean }) {
  return <i className={`dot ${good ? "green" : "gray"}`} />;
}

function Camera({ state }: { state: Telemetry | null }) {
  const [retry, setRetry] = useState(0);
  const [width, setWidth] = useState<number | null>(null);
  const [resizing, setResizing] = useState(false);
  const panelRef = useRef<HTMLElement>(null);
  const drag = useRef<{ pointerId: number; x: number; y: number; width: number } | null>(null);
  const available = state?.controller.status === "running" && state.camera.available;
  const streaming = available && state?.camera.status === "streaming";
  const simulation = state?.source === "demo" && state.controller.status === "running";
  useEffect(() => {
    if (!available || streaming) return;
    const timer = setInterval(() => setRetry((v) => v + 1), 3000);
    return () => clearInterval(timer);
  }, [available, streaming]);
  const resize = (nextWidth: number) => {
    const panel = panelRef.current!;
    const stage = panel.parentElement!;
    const bounds = panel.getBoundingClientRect();
    const stageBounds = stage.getBoundingClientRect();
    const style = getComputedStyle(stage);
    let left = stageBounds.left + (parseFloat(style.paddingLeft) || 0);
    let maxWidth = bounds.right - left;
    if (window.innerWidth > 1000) {
      const eyes = stage.querySelector(".eye-column");
      if (eyes) left = eyes.getBoundingClientRect().right + (parseFloat(style.columnGap) || 0);
      const image = panel.querySelector(".camera-image")!.getBoundingClientRect();
      const maxHeight = stageBounds.bottom - (parseFloat(style.paddingBottom) || 0) - bounds.top;
      const heightLimit = (maxHeight - (bounds.height - image.height)) * 16 / 9
        + bounds.width - image.width;
      maxWidth = Math.min(bounds.right - left, heightLimit);
    }
    maxWidth = Math.max(1, maxWidth);
    setWidth(Math.min(maxWidth, Math.max(Math.min(280, maxWidth), nextWidth)));
  };
  const startResize = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0 || drag.current) return;
    event.preventDefault();
    event.currentTarget.focus();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      pointerId: event.pointerId, x: event.clientX, y: event.clientY,
      width: panelRef.current!.getBoundingClientRect().width,
    };
    setResizing(true);
  };
  const moveResize = (event: PointerEvent<HTMLButtonElement>) => {
    const start = drag.current;
    if (!start || start.pointerId !== event.pointerId) return;
    const horizontal = start.x - event.clientX;
    const vertical = (event.clientY - start.y) * 16 / 9;
    resize(start.width + (Math.abs(horizontal) >= Math.abs(vertical) ? horizontal : vertical));
  };
  const stopResize = (event: PointerEvent<HTMLButtonElement>) => {
    if (drag.current?.pointerId !== event.pointerId) return;
    drag.current = null;
    setResizing(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };
  return (
    <section
      ref={panelRef}
      className={`panel camera-panel${resizing ? " is-resizing" : ""}`}
      style={width === null ? undefined : { width }}
      aria-label="Camera"
    >
      <div className="camera-image">
        {available && <img
          src={`/api/camera.mjpeg?session=${state?.session_id ?? ""}&retry=${retry}`}
          alt="Live camera with detected face bounding boxes"
          onError={() => setTimeout(() => setRetry((v) => v + 1), 1500)}
        />}
        {!streaming && (
          <div className="camera-placeholder">
            <Logo />
            <span>
              {simulation ? "No camera in this source"
                : available ? "Waiting for fresh camera frames"
                : "Waiting for main.py (live or --demo)"}
            </span>
          </div>
        )}
        <div className="camera-badges">
          <span className="camera-overlay">
            {simulation ? "SIMULATION / NO CAMERA" : available ? "RGB / 640 × 360" : "NO CAMERA FEED"}
          </span>
          <span className={`pill ${streaming ? "good" : ""}`}>
            <Dot good={!!streaming} />
            {simulation ? "Not available" : (state?.camera.status ?? "Waiting")}
          </span>
        </div>
      </div>
      <div className="camera-meta">
        <span>
          <i className="dot accent" />
          {state?.faces.filter((f) => f.visible).length ?? 0} tracked faces
        </span>
        <span>{number(available ? state?.timing?.capture_fps : null)} fps</span>
        <span>
          {state?.camera.age_s == null
            ? "—"
            : `${Math.round(state.camera.age_s * 1000)} ms capture age`}
        </span>
      </div>
      <button
        type="button"
        className="camera-resize-handle"
        aria-label="Resize camera preview"
        title="Drag left or down to enlarge. Use arrow keys to resize, or double-click to reset."
        onPointerDown={startResize}
        onPointerMove={moveResize}
        onPointerUp={stopResize}
        onPointerCancel={stopResize}
        onLostPointerCapture={stopResize}
        onDoubleClick={() => setWidth(null)}
        onKeyDown={(event) => {
          const direction = { ArrowLeft: 1, ArrowDown: 1, ArrowRight: -1, ArrowUp: -1 }[event.key];
          if (direction) {
            event.preventDefault();
            resize(panelRef.current!.getBoundingClientRect().width + direction * 32);
          } else if (event.key === "Home") {
            event.preventDefault();
            setWidth(null);
          }
        }}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M7 11v6h6M11 7h6v6M7 17 17 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </section>
  );
}

function EyeCard({
  eye,
  id,
  state,
}: {
  eye?: Eye;
  id: number;
  state: Telemetry | null;
}) {
  const health = state?.eye_health.find((e) => e.eye_id === id);
  const assigned = eye?.face_id != null;
  const url = assigned ? state?.crops[String(eye?.face_id)] : undefined;
  const opening = Math.max(0, Math.min(1, eye?.eye_lid ?? 0.85));
  const [failed, setFailed] = useState("");
  return (
    <article className="eye-card" aria-label={`Eye ${String(id).padStart(2, "0")}`}>
      <div className="eye-identity">
        <span>
          Eye <b>{String(id).padStart(2, "0")}</b>
        </span>
        <span
          className="reachability"
          title={`${health?.address ?? ""} · Application and motor health unknown`}
        >
          <Dot good={health?.status === "reachable"} />
          {health?.status === "reachable" ? "online"
            : health?.status === "unreachable" ? "offline"
            : (health?.status ?? "unknown")}
        </span>
        <span className="assignment" title={assigned ? `Face #${eye?.face_id}` : "No face assigned"}>
          {assigned ? `Face #${eye?.face_id}` : "Face —"}
        </span>
      </div>
      <div className="eye-angles" title="Commanded motor targets in degrees">
        <div>
          <span>YAW</span>
          <strong>
            {number(eye?.yaw)}
            <small>°</small>
          </strong>
        </div>
        <div>
          <span>PITCH</span>
          <strong>
            {number(eye?.pitch)}
            <small>°</small>
          </strong>
        </div>
        <div>
          <span>LID</span>
          <strong>
            {eye ? Math.round(eye.eye_lid * 100) : "—"}
            <small>%</small>
          </strong>
        </div>
      </div>
      <div className="eye-preview">
        <EyePreview opening={opening} irisColor={eye?.iris_color} />
      </div>
      <div className="face-crop">
        {url && failed !== url ? (
          <img
            src={url}
            alt={`Face ${eye?.face_id} assigned to eye ${id}`}
            onError={() => setFailed(url)}
          />
        ) : (
          <div className="crop-placeholder">
            {state?.source === "demo" && state.controller.status === "running"
              ? "No camera in this source"
              : assigned ? "No fresh face crop" : "Waiting for a face"}
          </div>
        )}
      </div>
    </article>
  );
}

function System({ state }: { state: Telemetry | null }) {
  const system = state?.system;
  return (
    <section className="panel system-panel">
      <div className="panel-title">
        <h2>System Resources | Raspberry Pi</h2>
      </div>
      <div className="resource-grid">
        <div className="resource">
          <span>CPU USAGE</span>
          <strong>
            {number(system?.cpu_percent, 0)}
            <small>%</small>
          </strong>
          <div className="meter">
            <i style={{ width: `${system?.cpu_percent ?? 0}%` }} />
          </div>
          <small>Across all cores</small>
        </div>
        <div className="resource">
          <span>MEMORY</span>
          <strong>
            {system ? memory(system.ram_used_bytes) : "—"}
            <small>
              {system ? ` / ${memory(system.ram_total_bytes)}` : ""}
            </small>
          </strong>
          <div className="meter">
            <i style={{ width: `${system?.ram_percent ?? 0}%` }} />
          </div>
          <small>{number(system?.ram_percent, 0)}% in use</small>
        </div>
        <div className="resource">
          <span>TEMPERATURE</span>
          <strong>
            {number(system?.temperature_c, 0)}
            <small>°C</small>
          </strong>
          <small>CPU sensor</small>
        </div>
        <div className="resource">
          <span>UPTIME</span>
          <strong>
            {system
              ? `${Math.floor(system.uptime_s / 3600)}h ${Math.floor((system.uptime_s % 3600) / 60)}m`
              : "—"}
          </strong>
          <small>
            {system?.process
              ? `Pipeline: ${system.process.cpu_percent.toFixed(0)}% CPU · ${(system.process.rss_bytes / 1024 ** 2).toFixed(0)} MB`
              : "Pipeline process unavailable"}
          </small>
        </div>
      </div>
    </section>
  );
}

export default function App() {
  const { state, connected } = useTelemetry();
  const [page, setPage] = useState<Page>(currentPage);
  const [controlsHost, setControlsHost] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    const pop = () => setPage(currentPage());
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  const navigate = (next: Page) => {
    history.pushState({}, "", pages.find((page) => page.id === next)!.path);
    setPage(next);
  };
  const live = connected && state?.controller.status === "running";
  const faces = live ? state?.faces ?? [] : [];
  const status = (
    <div className={`status-strip ${page === "dashboard" ? "panel" : page === "system" ? "panel system-info" : ""}`}>
      <span>
        Publication <b>{number(live ? state?.timing?.publish_hz : null)} Hz</b>
      </span>
      <span>
        Telemetry age{" "}
        <b>
          {state?.controller.age_s == null
            ? "—"
            : `${Math.round(state.controller.age_s * 1000)} ms`}
        </b>
      </span>
      <span className="device-badge">
        {live ? state?.source === "demo" ? "SIMULATION" : "LIVE CAMERA" : "WAITING"}
      </span>
    </div>
  );
  return (
    <div className={`app ${page === "dashboard" ? "app-overview" : ""}`}>
      <header className="topbar">
        <a
          href="/"
          className="brand"
          onClick={(e) => {
            e.preventDefault();
            navigate("dashboard");
          }}
        >
          <Logo />
          <span>
            aEyes
          </span>
        </a>
        <nav aria-label="Main navigation">
          {pages.map((item) => (
            <a
              key={item.id}
              href={item.path}
              className={page === item.id ? "selected" : ""}
              aria-current={page === item.id ? "page" : undefined}
              onClick={(event) => {
                if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                event.preventDefault();
                navigate(item.id);
              }}
            >
              {item.label}
            </a>
          ))}
        </nav>
        <span className={`connection ${connected ? "" : "disconnected"}`}>
          <Dot good={connected} />
          {connected ? "Connected" : "Reconnecting"}
        </span>
      </header>
      <main className={page === "dashboard" ? "overview-main" : undefined}>
        {page === "system" && status}
        {!connected && page !== "dashboard" && (
          <div className="notice warning" role="status">
            Backend connection unavailable. Reconnecting automatically.
          </div>
        )}
        {page === "settings" ? (
          <Settings state={state} />
        ) : page === "system" ? (
          <System state={state} />
        ) : (
          <div className="overview-stage">
            <div className="overview-top">
              {status}
              <div className="panel plot-controls" ref={setControlsHost} />
              {(!connected || !live) && (
                <div className={`notice overview-notice ${!connected ? "warning" : ""}`} role="status">
                  {!connected ? "Backend connection unavailable. Reconnecting automatically." : <>
                    {state?.controller.status === "stale" ? "Application telemetry stopped. " : ""}
                    Waiting for main.py (live or --demo) to publish data.
                  </>}
                </div>
              )}
            </div>
            <Suspense
              fallback={
                <section className="scene-panel scene-background settings-loading">
                  Loading spatial view…
                </section>
              }
            >
              <Scene
                background
                controlsContainer={controlsHost}
                state={
                  live
                    ? state
                    : state
                      ? {
                          ...state,
                          controller: {
                            ...state.controller,
                            status: "stale",
                          },
                        }
                      : null
                }
              />
            </Suspense>
            <aside className="eye-column" aria-label="Eyes 1 to 6">
              {[1, 2, 3, 4, 5, 6].map((id) => (
                <EyeCard
                  key={id}
                  id={id}
                  eye={live ? state?.eyes.find((e) => e.eye_id === id) : undefined}
                  state={state}
                />
              ))}
            </aside>
            <Camera state={live ? state : null} />
            <section className="panel faces-panel overview-tracking">
              <div className="panel-title">
                <h2>Tracking</h2>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Face</th>
                      <th>State</th>
                      <th>Position X / Y / Z (m)</th>
                      <th>Confidence</th>
                      <th>Depth age</th>
                      <th>Classification</th>
                      <th>Eyes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {faces.map((face) => (
                      <tr key={face.id}>
                        <td>#{face.id}</td>
                        <td>
                          <span className="pill">{face.status}</span>
                        </td>
                        <td className="numeric">
                          {[face.position.x, face.position.y, face.position.z]
                            .map((v) => v.toFixed(2))
                            .join(" / ")}
                        </td>
                        <td>{Math.round(face.confidence * 100)}%</td>
                        <td>{Math.round(face.depth_age_s * 1000)} ms</td>
                        <td>{face.is_static ? "Static" : "Dynamic"}</td>
                        <td>
                          {state?.eyes
                            .filter((e) => e.face_id === face.id)
                            .map((e) => `E${e.eye_id}`)
                            .join(", ") || "—"}
                        </td>
                      </tr>
                    ))}
                    {!faces.length && (
                      <tr>
                        <td colSpan={7} className="empty-table">
                          {live ? "No tracked faces. New tracks appear after confirmation."
                            : "Waiting for application telemetry."}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
}
