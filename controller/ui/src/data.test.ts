import { describe, it, expect } from 'vitest';
import { decodeTelemetry, reconnectDelay, toBase, Trails } from './data';
import type { Telemetry } from './types';

export const sample = (): Telemetry => ({
  schema_version: 1, session_id: 'one', demo: true,
  geometry: { camera: { x: .04375, y: 0, z: 0, horizontal_fov: 127, vertical_fov: 79.5 }, eyes: [], coordinates: '' },
  faces: [{ id: 0, visible: true, status: 'confirmed', is_static: false, position: {x:2,y:0,z:0},
    confidence: .9, depth_age_s:0, observation_age_s:0, velocity:[0,0,0], hits:30, missing_frames:0 }],
  eyes: [], crops: {}, eye_health: [], system: null,
  controller: { status:'running', age_s:0, service:'unknown', restart_available:false, restarting:false, restart_error:null },
  camera: { status:'streaming', age_s:0, video_age_s:0, capture_key:'1-1000000' },
});

describe('telemetry and geometry', () => {
  it('rejects incompatible telemetry', () => {
    expect(decodeTelemetry(JSON.stringify(sample())).faces[0].id).toBe(0);
    expect(() => decodeTelemetry('{"schema_version":2}')).toThrow();
  });
  it('caps reconnect backoff', () => {
    expect(reconnectDelay(0)).toBe(500); expect(reconnectDelay(100)).toBe(10000);
  });
  it('translates camera positions once and preserves project axes', () => {
    expect(toBase({x:2,y:-.3,z:.1},sample().geometry)).toEqual({x:2.04375,y:-.3,z:.1});
  });
  it('deduplicates captures, caps history, and clears restarted identities', () => {
    const store = new Trails(), state = sample();
    store.update(state); store.update(state); expect(store.points.get(0)?.length).toBe(1);
    for (let i=0;i<400;i++) { state.camera.capture_key=String(i); store.update(state); }
    expect(store.points.get(0)?.length).toBe(300);
    state.session_id='two'; store.update(state); expect(store.points.get(0)?.length).toBe(1);
    state.faces=[]; store.update(state); expect(store.points.size).toBe(0);
  });
});
