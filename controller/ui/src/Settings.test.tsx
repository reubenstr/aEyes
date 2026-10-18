// @vitest-environment jsdom
import { afterEach, describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import { Settings } from './Settings';
import type { ConfigDescription, Telemetry } from './types';

const config = (): ConfigDescription => ({
  saved: { system: { refresh_rate_hz: 15 } }, active: { system: { refresh_rate_hz: 15 } },
  defaults: { system: { refresh_rate_hz: 10 } }, revision: 'saved', active_revision: 'saved',
  pending_restart: false, source: null, restart_available: false,
  sections: { system: { label: 'System', description: 'Controls camera and command timing.' } },
  fields: { system: { refresh_rate_hz: {type:'integer',label:'refresh_rate_hz',description:'Sets the camera and command rate in hertz.',nullable:false} } },
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
  it('shows schema names and descriptions with independent editable, active, and default values', async () => {
    const data = config();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(data)));
    render(<Settings state={{...telemetry(),active_config:{system:{refresh_rate_hz:12}}}}/>);
    const input = await screen.findByRole('spinbutton', {
      name: 'refresh_rate_hz', description: data.fields.system.refresh_rate_hz.description,
    });
    expect(screen.getByRole('heading', {name: data.sections.system.label})).toBeTruthy();
    expect(screen.getByText(data.sections.system.description)).toBeTruthy();
    expect(screen.getByText(data.fields.system.refresh_rate_hz.description)).toBeTruthy();
    expect(screen.queryByText('Refresh rate hz')).toBeNull();
    expect((input as HTMLInputElement).value).toBe('15');
    expect(screen.getByText('Active').nextElementSibling?.textContent).toBe('12');
    expect(screen.getByText('Default').nextElementSibling?.textContent).toBe('10');
    fireEvent.change(input, {target:{value:'20'}});
    expect((input as HTMLInputElement).value).toBe('20');
    expect(screen.getByText('Active').nextElementSibling?.textContent).toBe('12');
    expect(screen.getByText('Default').nextElementSibling?.textContent).toBe('10');
  });

  it('keeps boolean, RGB, automatic, and text values readable and editable', async () => {
    const data = config();
    data.sections.eye_manager = {label:'Eye Manager',description:'Controls eye appearance.'};
    data.fields.eye_manager = {
      is_cat_eye: {type:'boolean',label:'is_cat_eye',description:'Enables the cat-eye shape.',nullable:false},
      pupil_color: {type:'rgb',label:'pupil_color',description:'Sets the pupil RGB color.',nullable:false},
      vein_seed: {type:'integer',label:'vein_seed',description:'Selects the vein pattern.',nullable:true},
    };
    data.saved.eye_manager = {is_cat_eye:false,pupil_color:[0,0,0],vein_seed:null};
    data.defaults.eye_manager = {is_cat_eye:false,pupil_color:[1,2,3],vein_seed:null};
    data.sections.publisher = {label:'Publisher',description:'Configures eye command broadcasts.'};
    data.fields.publisher = {socket_address:{type:'string',label:'socket_address',description:'Selects the broadcast address.',nullable:false}};
    data.saved.publisher = {socket_address:'*'};
    data.defaults.publisher = {socket_address:'*'};
    const fetcher = vi.fn().mockResolvedValue(response(data));
    vi.stubGlobal('fetch', fetcher);
    render(<Settings state={null}/>);
    const checkbox = await screen.findByRole('checkbox', {name:'is_cat_eye',description:'Enables the cat-eye shape.'});
    const field = (input: HTMLElement) => within(input.closest('.config-field') as HTMLElement);
    expect(field(checkbox).getByText('Default').nextElementSibling?.textContent).toBe('false');
    fireEvent.click(checkbox);
    const rgb = screen.getByRole('group', {name:'pupil_color',description:'Sets the pupil RGB color.'});
    expect(field(rgb).getByText('Default').nextElementSibling?.textContent).toBe('1, 2, 3');
    fireEvent.change(within(rgb).getByRole('spinbutton', {name:'pupil_color green'}), {target:{value:'32'}});
    const seed = screen.getByRole('spinbutton', {name:'vein_seed'});
    expect((seed as HTMLInputElement).placeholder).toBe('Auto');
    expect(field(seed).getByText('Default').nextElementSibling?.textContent).toBe('Auto');
    fireEvent.change(seed, {target:{value:'42'}});
    fireEvent.click(field(seed).getByRole('button', {name:'Auto'}));
    fireEvent.change(screen.getByRole('textbox', {name:'socket_address'}), {target:{value:'127.0.0.1'}});
    fireEvent.click(screen.getByText('Save', {exact:true}));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetcher.mock.calls[1][1].body).values).toEqual({
      ...data.saved, eye_manager:{is_cat_eye:true,pupil_color:[0,32,0],vein_seed:null},
      publisher:{socket_address:'127.0.0.1'},
    });
  });

  it('loads reset defaults into a draft and saves with the loaded revision', async () => {
    const data = config();
    const fetcher = vi.fn().mockResolvedValueOnce(response(data)).mockResolvedValueOnce(response({...data,saved:data.defaults,revision:'new',pending_restart:true}));
    vi.stubGlobal('fetch',fetcher);
    render(<Settings state={null}/>);
    const input = await screen.findByLabelText('refresh_rate_hz');
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
    const input=await screen.findByLabelText('refresh_rate_hz');
    fireEvent.change(input,{target:{value:'20'}}); fireEvent.click(screen.getByText('Save',{exact:true}));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect((input as HTMLInputElement).value).toBe('20');
  });
  it('allows simulation settings to be saved while service restart remains unavailable', async () => {
    const data = {...config(),source:'demo' as const};
    const fetcher = vi.fn().mockResolvedValueOnce(response(data)).mockResolvedValueOnce(response(data));
    vi.stubGlobal('fetch',fetcher);
    render(<Settings state={null}/>);
    const input = await screen.findByLabelText('refresh_rate_hz');
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
    await screen.findByLabelText('refresh_rate_hz'); fireEvent.click(screen.getByText('Save and restart'));
    await screen.findByText('Restart requested. Waiting for a new controller session…');
    expect(fetcher.mock.calls[2][0]).toBe('/api/controller/restart');
    rerender(<Settings state={{...before,session_id:'after',config_revision:'new'}}/>);
    expect(await screen.findByText('Controller restarted. Saved settings are now active.')).toBeTruthy();
  });
  it('clears active settings after silence and disables restart on a switch to the demo source', async () => {
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(response({...config(),source:'main',restart_available:true})));
    const before = telemetry();
    const { rerender } = render(<Settings state={before}/>);
    await screen.findByLabelText('refresh_rate_hz');
    expect(screen.getByText('Active').nextElementSibling?.textContent).toBe('15');
    rerender(<Settings state={{...before,controller:{...before.controller,status:'stale'}}}/>);
    expect(screen.getByText('Active').nextElementSibling?.textContent).toBe('—');
    expect(screen.getByText('No active application')).toBeTruthy();
    rerender(<Settings state={{...before,source:'demo',controller:{...before.controller,restart_available:false}}}/>);
    expect((screen.getByText('Save and restart') as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Restart main.py --demo in its terminal/)).toBeTruthy();
  });
});
