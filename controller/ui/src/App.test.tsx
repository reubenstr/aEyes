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
    expect(screen.getByText('SIMULATION')).toBeTruthy();
  });

  it('waits for an application without showing generated data or requesting camera images', () => {
    vi.mocked(useTelemetry).mockReturnValue({ state: null, connected: true });
    render(<App />);
    expect(screen.getByText('WAITING')).toBeTruthy();
    expect(screen.getByText('Waiting for main.py (live or --demo) to publish data.')).toBeTruthy();
    expect(document.querySelector('img')).toBeNull();
    expect(screen.getByText('Waiting for application telemetry.')).toBeTruthy();
  });

  it('shows simulation tracking and actual reachability with explicit camera placeholders', () => {
    vi.mocked(useTelemetry).mockReturnValue({ state: state(), connected: true });
    render(<App />);
    expect(screen.getByText('SIMULATION')).toBeTruthy();
    expect(screen.getAllByText('No camera in this source').length).toBeGreaterThan(0);
    expect(screen.getByText('online')).toBeTruthy();
    expect(screen.getByText('confirmed')).toBeTruthy();
    expect(document.querySelector('img')).toBeNull();
    const card = screen.getByText('online').closest('article')!;
    expect(within(card).getByText('Face #42')).toBeTruthy();
    expect(within(card).getByText('12.3')).toBeTruthy();
    expect(within(screen.getByRole('complementary', {name:'Eyes 1 to 6'})).getAllByRole('article').map(card => card.getAttribute('aria-label')))
      .toEqual(['Eye 01', 'Eye 02', 'Eye 03', 'Eye 04', 'Eye 05', 'Eye 06']);
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

describe('assigned face thumbnails', () => {
  const first = '/api/faces/42/crop.jpg?session=live-one&capture=a';
  const setup = () => {
    let data: Telemetry = {
      ...state(), source: 'main', session_id: 'live-one', crops: {'42': first},
      camera: {available: true, status: 'streaming', age_s: 0, video_age_s: 0, capture_key: 'a'},
    };
    vi.mocked(useTelemetry).mockReturnValue({state: data, connected: true});
    const {rerender} = render(<App />);
    const card = screen.getByRole('article', {name: 'Eye 01'});
    const image = (url: string) => Array.from(card.querySelectorAll<HTMLImageElement>('.face-crop img'))
      .find(element => element.getAttribute('src') === url)!;
    const update = (changes: Partial<Telemetry>, connected = true) => {
      data = {...data, ...changes};
      vi.mocked(useTelemetry).mockReturnValue({state: data, connected});
      rerender(<App />);
    };
    const visible = () => within(card).queryByRole('img', {name: /Face .* assigned to eye 1/});
    return {card, data, image, update, visible};
  };

  it('keeps the last loaded image until its replacement loads, including failed refreshes', () => {
    const {card, image, update, visible} = setup();
    const original = image(first);
    expect(visible()).toBeNull();
    fireEvent.load(original);
    expect(visible()).toBe(original);

    const failed = '/api/faces/42/crop.jpg?session=live-one&capture=b';
    update({crops: {'42': failed}});
    expect(visible()).toBe(original);
    expect(image(failed).style.display).toBe('none');
    fireEvent.error(image(failed));
    expect(visible()).toBe(original);
    expect(within(card).queryByText('Waiting for a face image')).toBeNull();

    const next = '/api/faces/42/crop.jpg?session=live-one&capture=c';
    update({crops: {'42': next}});
    const pending = image(next);
    expect(visible()).toBe(original);
    fireEvent.load(pending);
    expect(visible()).toBe(pending);
    expect(card.querySelectorAll('.face-crop img').length).toBe(1);
  });

  it('holds the photo through missing crop updates and stale live video while assigned', () => {
    const {data, image, update, visible} = setup();
    const original = image(first);
    fireEvent.load(original);
    update({crops: {}, camera: {...data.camera, status: 'stale', video_age_s: 10}});
    expect(visible()).toBe(original);
  });

  it('finishes an in-flight image while newer crop URLs arrive', () => {
    const {image, update, visible} = setup();
    const original = image(first);
    update({crops: {'42': '/api/faces/42/crop.jpg?session=live-one&capture=b'}});
    const latest = '/api/faces/42/crop.jpg?session=live-one&capture=c';
    update({crops: {'42': latest}});
    expect(image(first)).toBe(original);
    fireEvent.load(original);
    expect(visible()).toBe(original);
    const pending = image(latest);
    expect(pending.style.display).toBe('none');
    fireEvent.load(pending);
    expect(visible()).toBe(pending);
  });

  it('clears the old person on reassignment or release and ignores late loads', () => {
    const {card, data, image, update, visible} = setup();
    const original = image(first);
    fireEvent.load(original);
    const pending = '/api/faces/42/crop.jpg?session=live-one&capture=late';
    update({crops: {'42': pending}});
    const late = image(pending);
    const reassigned = data.eyes.map(eye => ({...eye, face_id: 43}));
    update({eyes: reassigned, crops: {}});
    expect(visible()).toBeNull();
    fireEvent.load(late);
    expect(visible()).toBeNull();

    const next = '/api/faces/43/crop.jpg?session=live-one&capture=d';
    update({crops: {'43': next}});
    fireEvent.load(image(next));
    expect(visible()?.getAttribute('alt')).toBe('Face 43 assigned to eye 1');
    update({eyes: data.eyes.map(eye => ({...eye, face_id: null}))});
    expect(card.querySelector('.face-crop img')).toBeNull();
    update({eyes: reassigned, crops: {}});
    expect(visible()).toBeNull();
  });

  it('clears retained images when the controller session changes', () => {
    const {image, update, visible} = setup();
    fireEvent.load(image(first));
    update({session_id: 'live-two', crops: {}});
    expect(visible()).toBeNull();
    const next = '/api/faces/42/crop.jpg?session=live-two&capture=a';
    update({crops: {'42': next}});
    const pending = image(next);
    fireEvent.load(pending);
    expect(visible()).toBe(pending);
  });

  it.each(['stale', 'disconnected'])('clears retained images when telemetry is %s', status => {
    const {data, image, update, visible} = setup();
    fireEvent.load(image(first));
    update({controller: {...data.controller, status: status === 'stale' ? 'stale' : 'running'}},
      status !== 'disconnected');
    expect(visible()).toBeNull();
  });
});

describe('camera preview resizing', () => {
  const setup = () => {
    vi.mocked(useTelemetry).mockReturnValue({ state: state(), connected: true });
    render(<App />);
    const panel = screen.getByRole('region', {name: 'Camera'});
    const handle = within(panel).getByRole('button', {name: 'Resize camera preview'});
    const rectangle = (x: number, y: number, width: number, height: number): DOMRect => ({
      x, y, width, height, left: x, top: y, right: x + width, bottom: y + height, toJSON: () => ({}),
    });
    const panelWidth = () => parseFloat(panel.style.width) || 432;
    vi.spyOn(panel, 'getBoundingClientRect').mockImplementation(() =>
      rectangle(1004 - panelWidth(), 100, panelWidth(), (panelWidth() - 18) * 9 / 16 + 48));
    vi.spyOn(panel.parentElement!, 'getBoundingClientRect').mockReturnValue(rectangle(0, 84, 1024, 816));
    vi.spyOn(screen.getByRole('complementary', {name: 'Eyes 1 to 6'}), 'getBoundingClientRect')
      .mockReturnValue(rectangle(20, 200, 360, 600));
    vi.spyOn(panel.querySelector('.camera-image')!, 'getBoundingClientRect').mockImplementation(() =>
      rectangle(1013 - panelWidth(), 109, panelWidth() - 18, (panelWidth() - 18) * 9 / 16));
    handle.setPointerCapture = vi.fn();
    handle.hasPointerCapture = vi.fn(() => true);
    handle.releasePointerCapture = vi.fn();
    const pointer = (type: string, x: number, y = 400, pointerId = 1, button = 0) => {
      fireEvent(handle, Object.assign(new MouseEvent(type, {
        bubbles: true, clientX: x, clientY: y, button,
      }), { pointerId }));
    };
    return { panel, handle, pointer };
  };

  it('grows leftward and downward, captures the pointer, and stops when released', () => {
    const { panel, handle, pointer } = setup();
    pointer('pointerdown', 572);
    expect(handle.setPointerCapture).toHaveBeenCalledWith(1);
    pointer('pointermove', 472);
    expect(panel.style.width).toBe('532px');
    pointer('pointermove', 572, 490);
    expect(panel.style.width).toBe('592px');
    pointer('pointerup', 572, 490);
    expect(handle.releasePointerCapture).toHaveBeenCalledWith(1);
    pointer('pointermove', 900);
    expect(panel.style.width).toBe('592px');
  });

  it('limits the width to the available space and keeps a usable minimum', () => {
    const { panel, pointer } = setup();
    pointer('pointerdown', 572);
    pointer('pointermove', -1000);
    expect(panel.style.width).toBe('624px');
    pointer('pointermove', 1500);
    expect(panel.style.width).toBe('280px');
    pointer('pointercancel', 1500);
    pointer('pointermove', 300);
    expect(panel.style.width).toBe('280px');
    expect(panel.classList.contains('is-resizing')).toBe(false);
  });

  it('ignores secondary buttons and other pointers, and handles lost capture', () => {
    const { panel, pointer } = setup();
    pointer('pointerdown', 572, 400, 1, 2);
    pointer('pointermove', 472);
    expect(panel.style.width).toBe('');
    pointer('pointerdown', 572);
    pointer('pointermove', 472, 400, 2);
    expect(panel.style.width).toBe('');
    pointer('lostpointercapture', 572);
    pointer('pointermove', 472);
    expect(panel.style.width).toBe('');
    expect(panel.classList.contains('is-resizing')).toBe(false);
  });

  it('supports keyboard resizing and resetting to the default size', () => {
    const { panel, handle } = setup();
    fireEvent.keyDown(handle, {key: 'ArrowLeft'});
    expect(panel.style.width).toBe('464px');
    fireEvent.keyDown(handle, {key: 'ArrowUp'});
    expect(panel.style.width).toBe('432px');
    fireEvent.doubleClick(handle);
    expect(panel.style.width).toBe('');
    fireEvent.keyDown(handle, {key: 'ArrowDown'});
    fireEvent.keyDown(handle, {key: 'Home'});
    expect(panel.style.width).toBe('');
  });
});
