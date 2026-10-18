import type { Geometry, Telemetry, Vec3 } from './types';

export function decodeTelemetry(raw: string): Telemetry {
  const value = JSON.parse(raw);
  if (value.schema_version !== 1 || !Array.isArray(value.faces) || !Array.isArray(value.eyes)
      || !value.controller || !value.camera || !value.geometry) throw new Error('Unsupported telemetry');
  return value;
}

export async function api<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
  const body = await response.json();
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail));
  return body as T;
}

export const reconnectDelay = (attempt: number) => Math.min(10000, 500 * 2 ** Math.min(attempt, 5));
export const toBase = (p: Vec3, geometry: Geometry): Vec3 => ({
  x: p.x + geometry.camera.x, y: p.y + geometry.camera.y, z: p.z + geometry.camera.z,
});

export class Trails {
  session?: string;
  capture?: string | number | null;
  points = new Map<number, Vec3[]>();
  update(state: Telemetry) {
    if (state.session_id !== this.session || state.controller.status !== 'running') {
      this.points.clear(); this.capture = undefined; this.session = state.session_id;
    }
    if (state.controller.status !== 'running') return;
    const visible = state.faces.filter(f => f.visible);
    for (const id of this.points.keys()) if (!visible.some(f => f.id === id)) this.points.delete(id);
    const capture = state.camera.capture_key ?? state.timestamp;
    if (capture == null || capture === this.capture) return;
    this.capture = capture;
    for (const face of visible) {
      const history = this.points.get(face.id) ?? [];
      history.push(toBase(face.position, state.geometry));
      this.points.set(face.id, history.slice(-300));
    }
  }
}
