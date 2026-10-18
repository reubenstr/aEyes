// @vitest-environment jsdom
import { afterEach, describe, it, expect, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from './App';
import { useTelemetry } from './useTelemetry';
import type { Telemetry } from './types';

vi.mock('./useTelemetry', () => ({ useTelemetry: vi.fn() }));
vi.mock('./Scene', () => ({ Scene: () => <div>Spatial scene</div> }));

const state = (): Telemetry => ({
  schema_version: 1, source: 'demo', session_id: 'simulation', timestamp: 10,
  geometry: { camera: { x: 0, y: 0, z: 0, horizontal_fov: 127, vertical_fov: 79.5 }, eyes: [], coordinates: '' },
  faces: [{ id: 42, visible: true, status: 'confirmed', is_static: false, position: { x: 2, y: 0, z: 0 },
    confidence: 1, depth_age_s: 0, observation_age_s: 0, velocity: [0, 0, 0], hits: 30, missing_frames: 0 }],
  eyes: [{ eye_id: 1, face_id: 42, iris_color: [100, 150, 200], target_iris_color: [100, 150, 200],
    yaw: 12.3, pitch: 4.5, eye_lid: 1 }], crops: {}, system: null,
  eye_health: [{ eye_id: 1, address: '192.168.5.101', status: 'reachable' }],
  timing: { capture_fps: 0, publish_hz: 15, dropped_snapshots: 0 },
  controller: { status: 'running', age_s: 0, service: 'unknown', restart_available: false, restarting: false, restart_error: null },
  camera: { available: false, status: 'unavailable', age_s: null, video_age_s: null, capture_key: null },
});

afterEach(() => { cleanup(); vi.clearAllMocks(); history.replaceState({}, '', '/'); });

describe('application dashboard', () => {
  it('opens system resources separately and returns to the overview with browser back', async () => {
    vi.mocked(useTelemetry).mockReturnValue({ state: state(), connected: true });
    render(<App />);
    expect(screen.queryByRole('heading', {name:'System Resources | Raspberry Pi'})).toBeNull();
    fireEvent.click(screen.getByRole('link', {name:'System'}));
    expect(location.pathname).toBe('/system');
    expect(screen.getByRole('heading', {name:'System Resources | Raspberry Pi'})).toBeTruthy();
    expect(screen.queryByRole('article', {name:'Eye 01'})).toBeNull();
    expect(screen.getByRole('link', {name:'System'}).getAttribute('aria-current')).toBe('page');
    act(() => history.back());
    await waitFor(() => expect(screen.getByRole('article', {name:'Eye 01'})).toBeTruthy());
    expect(location.pathname).toBe('/');
    expect(screen.queryByRole('heading', {name:'System Resources | Raspberry Pi'})).toBeNull();
  });

  it('loads the system page directly without mounting overview panels', () => {
    history.replaceState({}, '', '/system');
    vi.mocked(useTelemetry).mockReturnValue({ state: state(), connected: true });
    render(<App />);
    expect(screen.getByRole('heading', {name:'System Resources | Raspberry Pi'})).toBeTruthy();
    expect(screen.queryByRole('complementary', {name:'Eyes 1 to 3'})).toBeNull();
    expect(screen.getByText('AEYES / SIMULATION')).toBeTruthy();
  });

  it('waits for an application without showing generated data or requesting camera images', () => {
    vi.mocked(useTelemetry).mockReturnValue({ state: null, connected: true });
    render(<App />);
    expect(screen.getByText('AEYES / WAITING')).toBeTruthy();
    expect(screen.getByText('Waiting for main.py (live or --demo) to publish data.')).toBeTruthy();
    expect(document.querySelector('img')).toBeNull();
    expect(screen.getByText('Waiting for application telemetry.')).toBeTruthy();
  });

  it('shows simulation tracking and actual reachability with explicit camera placeholders', () => {
    vi.mocked(useTelemetry).mockReturnValue({ state: state(), connected: true });
    render(<App />);
    expect(screen.getByText('AEYES / SIMULATION')).toBeTruthy();
    expect(screen.getAllByText('No camera in this source').length).toBeGreaterThan(0);
    expect(screen.getByText('online')).toBeTruthy();
    expect(screen.getByText('confirmed')).toBeTruthy();
    expect(document.querySelector('img')).toBeNull();
    const card = screen.getByText('online').closest('article')!;
    expect(within(card).getByText('Face #42')).toBeTruthy();
    expect(within(card).getByText('12.3')).toBeTruthy();
    expect(within(screen.getByRole('complementary', {name:'Eyes 1 to 3'})).getAllByRole('article').map(card => card.getAttribute('aria-label')))
      .toEqual(['Eye 01', 'Eye 02', 'Eye 03']);
    expect(within(screen.getByRole('complementary', {name:'Eyes 4 to 6'})).getAllByRole('article').map(card => card.getAttribute('aria-label')))
      .toEqual(['Eye 04', 'Eye 05', 'Eye 06']);
    const camera = screen.getByRole('region', {name:'Camera'});
    expect(within(camera).getByText('SIMULATION / NO CAMERA')).toBeTruthy();
    expect(within(camera).getByText('Not available')).toBeTruthy();
    expect(screen.getByRole('columnheader', {name:'Eyes'})).toBeTruthy();
  });

  it('hides assignments, positions, commands, and rates when application telemetry is stale', () => {
    const data = state();
    vi.mocked(useTelemetry).mockReturnValue({ state: data, connected: true });
    const { rerender } = render(<App />);
    expect(screen.getByText('confirmed')).toBeTruthy();
    vi.mocked(useTelemetry).mockReturnValue({ state: { ...data, controller: { ...data.controller, status: 'stale' } }, connected: true });
    rerender(<App />);
    expect(screen.queryByText('#42')).toBeNull();
    expect(screen.queryByText('confirmed')).toBeNull();
    expect(screen.queryByText('12.3')).toBeNull();
    expect(screen.queryByText('15.0')).toBeNull();
    expect(screen.getByText('online')).toBeTruthy();
    expect(screen.getByText(/Application telemetry stopped/)).toBeTruthy();
  });
});
