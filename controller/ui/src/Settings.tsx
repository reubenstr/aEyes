import { useEffect, useState } from 'react';
import { api } from './data';
import type { ConfigDescription, ConfigValues, ConfigValue, Telemetry } from './types';

const clone = <T,>(v: T): T => structuredClone(v);
const format = (v: ConfigValue | undefined) => v === undefined ? '—' : v === null ? 'Auto' : Array.isArray(v) ? v.join(', ') : String(v);
const labels: Record<string, string> = { system: 'System', publisher: 'Publisher', tracker: 'Tracker', kalman: 'Kalman', assigner: 'Assigner', eye_manager: 'Eye Manager' };

export function Settings({ state }: { state: Telemetry | null }) {
  const [config, setConfig] = useState<ConfigDescription | null>(null);
  const [draft, setDraft] = useState<ConfigValues | null>(null);
  const [error, setError] = useState(''), [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [waiting, setWaiting] = useState<{ session?: string; revision: string; started: number } | null>(null);
  useEffect(() => {
    let mounted = true;
    api<ConfigDescription>('/api/config').then(v => { if (mounted) { setConfig(v); setDraft(clone(v.saved)); } }).catch(e => { if (mounted) setError(e.message); });
    return () => { mounted = false; };
  }, []);
  useEffect(() => {
    if (!waiting) return;
    if (state?.controller.restart_error) { setError(state.controller.restart_error); setWaiting(null); return; }
    if (state?.controller.status === 'running' && state.session_id !== waiting.session && state.config_revision === waiting.revision) {
      setWaiting(null); setMessage('Controller restarted. Saved settings are now active.');
      api<ConfigDescription>('/api/config').then(setConfig).catch(e => setError(e.message));
    }
    const timer = setTimeout(() => { setError('Restart has not produced fresh telemetry. Check the controller service log; saved settings are retained.'); setWaiting(null); }, Math.max(0, 30000 - (Date.now() - waiting.started)));
    return () => clearTimeout(timer);
  }, [state, waiting]);
  if (!config || !draft) return <section className="panel settings-loading">{error || 'Loading controller settings…'}</section>;
  const dirty = JSON.stringify(draft) !== JSON.stringify(config.saved);
  const invalid = Object.values(draft).some(section => Object.values(section).some(v =>
    typeof v === 'number' ? !Number.isFinite(v) : Array.isArray(v) && v.some(n => !Number.isFinite(n))));
  const pending = state?.config_revision ? state.config_revision !== config.revision : config.pending_restart;
  const disabled = config.demo || busy || Boolean(waiting);
  const update = (section: string, name: string, value: ConfigValue) => setDraft({ ...draft, [section]: { ...draft[section], [name]: value } });
  async function save(restart: boolean) {
    if (!config || !draft) return;
    setBusy(true); setError(''); setMessage('');
    try {
      const saved = await api<ConfigDescription>('/api/config', { method: 'PUT', body: JSON.stringify({ values: draft, revision: config.revision }) });
      setConfig(saved); setDraft(clone(saved.saved)); setMessage('Settings saved. A controller restart is required.');
      if (restart) {
        await api('/api/controller/restart', { method: 'POST', body: JSON.stringify({ revision: saved.revision }) });
        setWaiting({ session: state?.session_id, revision: saved.revision, started: Date.now() });
        setMessage('Restart requested. Waiting for a new controller session…');
      }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="settings">
    <section className="panel settings-intro"><div><h2>Controller Configuration</h2><p>Changes are validated and saved to params.yaml. Restart the controller to apply them.</p></div>
      <span className={`pill ${pending ? 'warning' : 'good'}`}>{pending ? 'Restart pending' : 'Settings active'}</span></section>
    {config.demo && <div className="notice">Demo mode · Settings are available to explore. Saving and service restarts are disabled.</div>}
    {error && <div className="notice error" role="alert">{error} <button className="subtle" onClick={() => window.location.reload()}>Reload settings</button></div>}
    {message && <div className="notice" role="status">{message}</div>}
    <div className="settings-actions"><span>{dirty ? 'Unsaved changes' : 'Saved configuration'}{waiting ? ' · Restarting…' : ''}</span><div>
      <button disabled={busy || !!waiting} onClick={() => { setDraft(clone(config.defaults)); setMessage('Defaults loaded into the form. Save to persist them.'); }}>Reset to defaults</button>
      <button disabled={!dirty || disabled} onClick={() => { setDraft(clone(config.saved)); setError(''); }}>Discard changes</button>
      <button disabled={disabled || invalid || !dirty} onClick={() => save(false)}>Save</button>
      <button className="primary" disabled={disabled || invalid || !config.restart_available} onClick={() => save(true)}>{busy ? 'Saving…' : waiting ? 'Restarting…' : 'Save and restart'}</button>
    </div></div>
    {!config.restart_available && !config.demo && <p className="muted">Restart from this screen requires the installed systemd integration. For manual development, restart main.py in its terminal after saving.</p>}
    {Object.entries(config.fields).map(([section, fields]) => <section className="panel config-section" key={section}>
      <div className="config-heading"><h2>{labels[section] ?? section}</h2>
        {section === 'publisher' && <p>Eye-side networking must be updated separately when publisher settings change.</p>}</div>
      <div className="config-fields">{Object.entries(fields).map(([name, metadata]) => {
        const value = draft[section][name], id = `${section}-${name}`;
        const active = config.active?.[section]?.[name];
        return <div className="config-field" key={name}><div><label htmlFor={id}>{metadata.label}</label><code>{name}</code><small>Active: {format(active)}</small></div>
          {metadata.type === 'boolean' ? <input id={id} type="checkbox" checked={Boolean(value)} disabled={disabled} onChange={e => update(section, name, e.target.checked)} />
            : metadata.type === 'rgb' ? <div className="rgb-input"><span className="swatch" style={{ background: `rgb(${(value as number[]).join(',')})` }} />{(value as number[]).map((channel, i) => <input key={i} aria-label={`${metadata.label} ${['red','green','blue'][i]}`} type="number" min="0" max="255" step="1" value={Number.isFinite(channel) ? channel : ''} disabled={disabled} onChange={e => { const rgb = [...value as number[]]; rgb[i] = e.target.value === '' ? NaN : Number(e.target.value); update(section, name, rgb); }} />)}</div>
            : <div className="value-input"><input id={id} type={metadata.type === 'string' ? 'text' : 'number'} step={metadata.type === 'integer' ? '1' : 'any'} value={value === null || (typeof value === 'number' && !Number.isFinite(value)) ? '' : String(value)} placeholder={metadata.nullable ? 'Auto' : ''} disabled={disabled} onChange={e => update(section, name, metadata.type === 'string' ? e.target.value : e.target.value === '' ? metadata.nullable ? null : NaN : Number(e.target.value))} />{metadata.nullable && <button className="subtle" disabled={disabled} onClick={() => update(section, name, null)}>Auto</button>}</div>}
        </div>;
      })}</div></section>)}
    <section className="panel geometry-settings"><h2>Geometry</h2><p>Read only. Positions, camera mounting and pivot offsets come from config.py. All values are meters.</p><div className="table-wrap"><table><thead><tr><th>Eye</th><th>X</th><th>Y</th><th>Z</th><th>Pitch pivot offset</th></tr></thead><tbody>{config.geometry.eyes.map(eye => <tr key={eye.eye_id}><td>E{eye.eye_id}</td><td>{eye.position.x.toFixed(4)}</td><td>{eye.position.y.toFixed(4)}</td><td>{eye.position.z.toFixed(4)}</td><td>{Object.values(eye.pitch_pivot_offset).join(' / ')}</td></tr>)}</tbody></table></div><p>Camera: {config.geometry.camera.x}, {config.geometry.camera.y}, {config.geometry.camera.z} · FOV {config.geometry.camera.horizontal_fov}° × {config.geometry.camera.vertical_fov}°</p></section>
  </div>;
}
