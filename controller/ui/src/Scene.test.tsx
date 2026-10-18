// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { Scene } from './Scene';

vi.mock('three', async (original) => ({
  ...await original<typeof import('three')>(),
  WebGLRenderer: vi.fn(function () { throw new Error('WebGL unavailable'); }),
}));

afterEach(cleanup);

it('keeps the controls interactive in a separate overlay and removes them on unmount', () => {
  const controls = document.createElement('div');
  document.body.appendChild(controls);
  try {
    const view = render(<Scene state={null} background controlsContainer={controls} />);
    const trails = within(controls).getByRole('button', {name:'Trails'});
    expect(trails.classList.contains('active')).toBe(true);
    fireEvent.click(trails);
    expect(trails.classList.contains('active')).toBe(false);
    expect(within(controls).getByRole('button', {name:'Reset view'})).toBeTruthy();
    expect(view.container.querySelector('button')).toBeNull();
    expect(screen.getByText('3D view needs WebGL. Camera and telemetry remain available.')).toBeTruthy();
    view.unmount();
    expect(controls.children.length).toBe(0);
  } finally {
    controls.remove();
  }
});
