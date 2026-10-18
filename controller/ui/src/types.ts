export type Vec3 = { x: number; y: number; z: number };
export type RGB = [number, number, number];
export type ApplicationSource = 'main' | 'demo';
export type Geometry = {
  camera: Vec3 & { horizontal_fov: number; vertical_fov: number };
  eyes: { eye_id: number; position: Vec3; pitch_pivot_offset: Vec3 }[];
  coordinates: string;
};
export type Face = {
  id: number; status: string; visible: boolean; is_static: boolean;
  position: Vec3; confidence: number; depth_age_s: number; observation_age_s: number;
  velocity: number[]; hits: number; missing_frames: number;
};
export type Eye = {
  eye_id: number; face_id: number | null; iris_color: RGB; target_iris_color: RGB;
  yaw: number; pitch: number; eye_lid: number;
};
export type Telemetry = {
  schema_version: number; session_id?: string; timestamp?: number; source: ApplicationSource | null;
  geometry: Geometry; faces: Face[]; eyes: Eye[]; crops: Record<string, string>;
  active_config?: ConfigValues | null;
  config_revision?: string | null;
  timing?: { capture_fps: number; publish_hz: number; dropped_snapshots: number } | null;
  eye_health: { eye_id: number; address: string; status: string }[];
  controller: { status: string; age_s: number | null; service: string; restart_available: boolean;
    restarting: boolean; restart_error: string | null };
  camera: { available: boolean; status: string; age_s: number | null; video_age_s: number | null; capture_key: string | null };
  system: null | { cpu_percent: number; ram_used_bytes: number; ram_total_bytes: number;
    ram_percent: number; temperature_c: number | null; uptime_s: number;
    process: null | { pid: number; cpu_percent: number; rss_bytes: number } };
};
export type ConfigValue = number | string | boolean | null | number[];
export type ConfigValues = Record<string, Record<string, ConfigValue>>;
export type ConfigDescription = {
  saved: ConfigValues; active: ConfigValues | null; defaults: ConfigValues;
  revision: string; active_revision: string | null; pending_restart: boolean;
  sections: Record<string, { label: string; description: string }>;
  fields: Record<string, Record<string, { type: string; label: string; description: string; nullable: boolean }>>;
  geometry: Geometry; source: ApplicationSource | null; restart_available: boolean;
};
