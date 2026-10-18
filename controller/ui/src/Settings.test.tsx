// @vitest-environment jsdom
import { afterEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { Settings } from './Settings';
import type { ConfigDescription, Telemetry } from './types';

const config = (): ConfigDescription => ({
  saved: { system: { refresh_rate_hz: 15 } }, active: { system: { refresh_rate_hz: 15 } },
  defaults: { system: { refresh_rate_hz: 10 } }, revision: 'saved', active_revision: 'saved',
  pending_restart: false, source: null, restart_available: false,
  fields: { system: { refresh_rate_hz: {type:'integer',label:'Refresh rate hz',nullable:false} } },
  geometry: { camera: {x:.04375,y:0,z:0,horizontal_fov:127,vertical_fov:79.5}, eyes:[], coordinates:'' },
});
const telemetry = (): Telemetry => ({
  schema_version: 1, source: 'main', session_id: 'before', config_revision: 'saved',
  active_config: {system:{refresh_rate_hz:15}}, geometry: config().geometry,
  faces: [], eyes: [], crops: {}, eye_health: [], system: null,
  controller: {status:'running',age_s:0,service:'unknown',restart_available:true,restarting:false,restart_error:null},
  camera: {available:true,status:'streaming',age_s:0,video_age_s:0,capture_key:'one'},
});
const response = (body: unknown, ok = true) => ({ ok, json: async () => body });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('settings workflow', () => {
  it('loads reset defaults into a draft and saves with the loaded revision', async () => {
    const data = config();
    const fetcher = vi.fn().mockResolvedValueOnce(response(data)).mockResolvedValueOnce(response({...data,saved:data.defaults,revision:'new',pending_restart:true}));
    vi.stubGlobal('fetch',fetcher);
    render(<Settings state={null}/>);
    const input = await screen.findByLabelText('Refresh rate hz');
    expect((input as HTMLInputElement).value).toBe('15');
    fireEvent.click(screen.getByText('Reset to defaults'));
    expect((input as HTMLInputElement).value).toBe('10');
    expect(fetcher).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('Save', {exact:true}));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({values:data.defaults,revision:'saved'});
    expect(await screen.findByText('No active application')).toBeTruthy();
  });
  it('surfaces stale revisions and preserves the edited form', async () => {
    const fetcher=vi.fn().mockResolvedValueOnce(response(config())).mockResolvedValueOnce(response({detail:'Settings changed. Reload before saving.'},false));
    vi.stubGlobal('fetch',fetcher); render(<Settings state={null}/>);
    const input=await screen.findByLabelText('Refresh rate hz');
    fireEvent.change(input,{target:{value:'20'}}); fireEvent.click(screen.getByText('Save',{exact:true}));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect((input as HTMLInputElement).value).toBe('20');
  });
  it('allows simulation settings to be saved while service restart remains unavailable', async () => {
    const data = {...config(),source:'demo' as const};
    const fetcher = vi.fn().mockResolvedValueOnce(response(data)).mockResolvedValueOnce(response(data));
    vi.stubGlobal('fetch',fetcher);
    render(<Settings state={null}/>);
    const input = await screen.findByLabelText('Refresh rate hz');
    fireEvent.change(input,{target:{value:'20'}});
    expect((screen.getByText('Save',{exact:true}) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByText('Save and restart') as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByText('Save',{exact:true}));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(fetcher.mock.calls[1][0]).toBe('/api/config');
    expect(screen.getByText(/Restart main.py --demo in its terminal/)).toBeTruthy();
  });
  it('waits for a new session reporting the saved revision before confirming restart', async () => {
    const initial={...config(),restart_available:true};
    const saved={...initial,revision:'new',pending_restart:true};
    const fetcher=vi.fn().mockResolvedValueOnce(response(initial)).mockResolvedValueOnce(response(saved))
      .mockResolvedValueOnce(response({status:'restarting'})).mockResolvedValueOnce(response({...saved,pending_restart:false,active_revision:'new'}));
    vi.stubGlobal('fetch',fetcher);
    const before=telemetry();
    const {rerender}=render(<Settings state={before}/>);
    await screen.findByLabelText('Refresh rate hz'); fireEvent.click(screen.getByText('Save and restart'));
    await screen.findByText('Restart requested. Waiting for a new controller session…');
    expect(fetcher.mock.calls[2][0]).toBe('/api/controller/restart');
    rerender(<Settings state={{...before,session_id:'after',config_revision:'new'}}/>);
    expect(await screen.findByText('Controller restarted. Saved settings are now active.')).toBeTruthy();
  });
  it('clears active settings after silence and disables restart on a switch to the demo source', async () => {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({...config(),source:'main',restart_available:true})));
    const before = telemetry();
    const { rerender } = render(<Settings state={before}/>);
    await screen.findByLabelText('Refresh rate hz');
    expect(screen.getByText('Active: 15')).toBeTruthy();
    rerender(<Settings state={{...before,controller:{...before.controller,status:'stale'}}}/>);
    expect(screen.getByText('Active: —')).toBeTruthy();
    expect(screen.getByText('No active application')).toBeTruthy();
    rerender(<Settings state={{...before,source:'demo',controller:{...before.controller,restart_available:false}}}/>);
    expect((screen.getByText('Save and restart') as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Restart main.py --demo in its terminal/)).toBeTruthy();
  });
});
