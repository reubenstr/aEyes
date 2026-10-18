// @vitest-environment jsdom
import { afterEach, describe, it, expect, vi } from 'vitest';
import { act, cleanup, renderHook } from '@testing-library/react';
import { useTelemetry } from './useTelemetry';

class Socket {
  static sockets: Socket[]=[];
  onmessage?: (event: {data:string})=>void;
  onclose?: ()=>void;
  onerror?: ()=>void;
  constructor() { Socket.sockets.push(this); }
  close() { this.onclose?.(); }
}
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); Socket.sockets=[]; });
describe('telemetry connection', () => {
  it('accepts snapshots, reconnects after closure, and cancels retries on unmount', () => {
    vi.useFakeTimers(); vi.stubGlobal('WebSocket',Socket);
    const {result,unmount}=renderHook(useTelemetry);
    act(()=>Socket.sockets[0].onmessage?.({data:JSON.stringify({schema_version:1,faces:[],eyes:[],geometry:{},controller:{},camera:{}})}));
    expect(result.current.connected).toBe(true);
    act(()=>Socket.sockets[0].close()); expect(result.current.connected).toBe(false);
    expect(result.current.state).toBeNull();
    act(()=>vi.advanceTimersByTime(500)); expect(Socket.sockets.length).toBe(2);
    unmount(); act(()=>vi.advanceTimersByTime(20000)); expect(Socket.sockets.length).toBe(2);
  });
});
