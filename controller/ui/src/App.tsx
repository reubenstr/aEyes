import { lazy, Suspense, useEffect, useState } from "react";
import { Settings } from "./Settings";
import { useTelemetry } from "./useTelemetry";
import type { Eye, Telemetry } from "./types";

const Scene = lazy(() => import("./Scene").then((m) => ({ default: m.Scene })));
const rgb = (c: number[] = [115, 115, 115]) => `rgb(${c.join(",")})`;
const number = (value: number | null | undefined, digits = 1) =>
  value == null ? "—" : value.toFixed(digits);
const memory = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GB`;

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
  useEffect(() => {
    const timer = setInterval(() => {
      if (state?.camera.status !== "streaming") setRetry((v) => v + 1);
    }, 3000);
    return () => clearInterval(timer);
  }, [state?.camera.status]);
  return (
    <section className="panel camera-panel">
      <div className="panel-title">
        <h2>Camera View | OAK-D W</h2>
        <span
          className={`pill ${state?.camera.status === "streaming" ? "good" : ""}`}
        >
          <Dot good={state?.camera.status === "streaming"} />
          {state?.camera.status ?? "Connecting"}
        </span>
      </div>
      <div className="camera-image">
        <img
          src={`/api/camera.mjpeg?session=${state?.session_id ?? ""}&retry=${retry}`}
          alt="Live camera with detected face bounding boxes"
          onError={() => setTimeout(() => setRetry((v) => v + 1), 1500)}
        />
        {state?.camera.status !== "streaming" && (
          <div className="camera-placeholder">
            <Logo />
            <span>
              {state
                ? "Waiting for fresh camera frames"
                : "Connecting to controller"}
            </span>
          </div>
        )}
        <span className="camera-overlay">
          {state?.demo ? "SYNTHETIC PREVIEW" : "RGB / 640 × 360"}
        </span>
      </div>
      <div className="camera-meta">
        <span>
          <i className="dot accent" />
          {state?.faces.filter((f) => f.visible).length ?? 0} tracked faces
        </span>
        <span>{number(state?.timing?.capture_fps)} fps</span>
        <span>
          {state?.camera.age_s == null
            ? "—"
            : `${Math.round(state.camera.age_s * 1000)} ms capture age`}
        </span>
      </div>
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
  const [failed, setFailed] = useState("");
  return (
    <article
      className="eye-card"
      style={{ "--eye-color": rgb(eye?.iris_color) } as React.CSSProperties}
    >
      <div className="eye-card-heading">
        <span>
          Eye <b>{String(id).padStart(2, "0")}</b>
        </span>
        <span
          className="reachability"
          title={`${health?.address ?? ""} · Application and motor health unknown`}
        >
          <Dot good={health?.status === "reachable"} />
          {state?.demo ? "Simulated" : (health?.status ?? "unknown")}
        </span>
      </div>
      <div className="eye-preview">
        <div
          className="eye-shape"
          style={{
            transform: `scaleY(${Math.max(0.08, eye?.eye_lid ?? 0.85)})`,
          }}
        >
          <div className="iris">
            <div className="pupil" />
          </div>
        </div>
        <span
          className="eye-target"
          style={{ background: rgb(eye?.target_iris_color) }}
          title="Target iris color"
        />
      </div>
      <div className="assignment">
        <span className="eyebrow">ASSIGNED FACE</span>
        <strong>{assigned ? `#${eye?.face_id}` : "Unassigned"}</strong>
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
            {assigned ? "No fresh face crop" : "Waiting for a face"}
          </div>
        )}
        <span>{url && failed !== url ? "Live crop" : "—"}</span>
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
  const [page, setPage] = useState(
    location.pathname === "/settings" ? "settings" : "dashboard",
  );
  useEffect(() => {
    const pop = () =>
      setPage(location.pathname === "/settings" ? "settings" : "dashboard");
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);
  const navigate = (next: string) => {
    history.pushState({}, "", next === "settings" ? "/settings" : "/");
    setPage(next);
  };
  const live = connected && state?.controller.status === "running";
  return (
    <div className="app">
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
          <button
            className={page === "dashboard" ? "selected" : ""}
            onClick={() => navigate("dashboard")}
          >
            Overview
          </button>
          <button
            className={page === "settings" ? "selected" : ""}
            onClick={() => navigate("settings")}
          >
            Settings
          </button>
        </nav>
        <span className={`connection ${connected ? "" : "disconnected"}`}>
          <Dot good={connected} />
          {connected ? "Connected" : "Reconnecting"}
        </span>
      </header>
      <main>
        <div className="page-heading">
          <h1>{page === "dashboard" ? "System Overview" : "Settings"}</h1>
          <span className="device-badge">
            {state?.demo ? "DEMO ENVIRONMENT" : "AEYES / CONTROLLER"}
          </span>
        </div>
        {!connected && (
          <div className="notice warning" role="status">
            Backend connection unavailable. Displayed values may be stale;
            reconnecting automatically.
          </div>
        )}
        {page === "settings" ? (
          <Settings state={state} />
        ) : (
          <>
            <div className="status-strip">
              <span>
                <Dot good={!!live} />
                Controller{" "}
                <b>
                  {state?.controller.restarting
                    ? "Restarting"
                    : (state?.controller.status ?? "Connecting")}
                </b>
              </span>
              <span>
                <Dot good={state?.camera.status === "streaming"} />
                Camera <b>{state?.camera.status ?? "Waiting"}</b>
              </span>
              <span>
                Eyes reachable{" "}
                <b>
                  {state?.eye_health.filter((e) => e.status === "reachable")
                    .length ?? 0}{" "}
                  / 6
                </b>
              </span>
              <span>
                Publication <b>{number(state?.timing?.publish_hz)} Hz</b>
              </span>
              <span>
                Telemetry age{" "}
                <b>
                  {state?.controller.age_s == null
                    ? "—"
                    : `${Math.round(state.controller.age_s * 1000)} ms`}
                </b>
              </span>
            </div>
            <div className={`visual-grid ${!live ? "stale" : ""}`}>
              <Camera state={state} />
              <Suspense
                fallback={
                  <section className="panel scene-panel settings-loading">
                    Loading spatial view…
                  </section>
                }
              >
                <Scene
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
            </div>
            <section className="panel array-panel">
              <div className="panel-title">
                <h2>Eye Assignments</h2>
              </div>
              <div className={`eyes-grid ${!live ? "stale" : ""}`}>
                {Array.from({ length: 6 }, (_, i) => (
                  <EyeCard
                    key={i + 1}
                    id={i + 1}
                    eye={state?.eyes.find((e) => e.eye_id === i + 1)}
                    state={state}
                  />
                ))}
              </div>
            </section>
            <section className="panel faces-panel">
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
                      <th>Assigned eyes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {state?.faces.map((face) => (
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
                          {state.eyes
                            .filter((e) => e.face_id === face.id)
                            .map((e) => `E${e.eye_id}`)
                            .join(", ") || "—"}
                        </td>
                      </tr>
                    ))}
                    {!state?.faces.length && (
                      <tr>
                        <td colSpan={7} className="empty-table">
                          No tracked faces. New tracks appear after
                          confirmation.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>
            <System state={state} />
          </>
        )}
      </main>
    </div>
  );
}
