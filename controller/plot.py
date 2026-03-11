import math
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.animation as animation

from face_tracker import FaceTracker
from eye_manager import EyeManager
from data_types import CameraConfig, Detection, EyeConfig, Position3D
from config import EYE_CONFIGS, CAMERA_CONFIG


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_mpl_color(color) -> tuple[float, float, float]:
    """Normalise a Color(r,g,b) from 0-255 to the 0.0-1.0 range matplotlib expects."""
    return (color.red / 255.0, color.green / 255.0, color.blue / 255.0)


def _draw_camera_frustum(ax, camera_config: CameraConfig, depth: float = 3.0):
    """Draw the camera's FOV as a wireframe pyramid."""
    cx, cy, cz = camera_config.x, camera_config.y, camera_config.z
    half_h = math.radians(camera_config.horizontal_fov / 2.0)
    half_v = math.radians(camera_config.vertical_fov / 2.0)
    # Far-plane half-extents (system: +X forward, +Y left, +Z up)
    fy = depth * math.tan(half_h)
    fz = depth * math.tan(half_v)
    corners = [
        (cx + depth, cy + fy, cz + fz),
        (cx + depth, cy - fy, cz + fz),
        (cx + depth, cy - fy, cz - fz),
        (cx + depth, cy + fy, cz - fz),
    ]
    for corner in corners:
        ax.plot([cx, corner[0]], [cy, corner[1]], [cz, corner[2]],
                color='blue', linewidth=0.5, alpha=0.3)
    # Far-plane rectangle
    for i in range(4):
        c1, c2 = corners[i], corners[(i + 1) % 4]
        ax.plot([c1[0], c2[0]], [c1[1], c2[1]], [c1[2], c2[2]],
                color='blue', linewidth=0.5, alpha=0.3)


def _draw_eye_cylinders(ax, eye_configs: list[EyeConfig], radius: float = 0.025):
    theta  = np.linspace(0, 2 * np.pi, 60)
 
    y_ring = radius * np.cos(theta)
    z_ring = radius * np.sin(theta)

    for cfg in eye_configs:
        # Yaw pivot (static — always at the eye mount position)
        ax.plot(
            np.full_like(theta, cfg.position.x),
            cfg.position.y + y_ring,
            cfg.position.z + z_ring,
            color='black', linewidth=1.0,
        )

# ---------------------------------------------------------------------------
# Simulated detections
# ---------------------------------------------------------------------------

def get_detections(frame: int) -> list[Detection]:
    """Return the set of Detection objects for a given frame number.

    All positions stay within: x[1, 3], y[-2.0, 2.0], z[-1.0, 1.0].
    """
    t = frame * 0.05

    face_a = Detection(position=Position3D(
        x=1.5 + 0.3 * math.sin(t),
        y=0.0 + 0.4 * math.cos(t),
        z=0.0 + 0.3 * math.sin(t * 0.5),
    ))
    face_b = Detection(position=Position3D(
        x=2.2 + 0.4 * math.cos(t * 0.7),
        y=0.8 + 0.5 * math.sin(t * 0.9),
        z=-0.3 + 0.4 * math.sin(t * 0.3),
    ))
    face_c = Detection(position=Position3D(
        x=1.2 + 0.15 * math.sin(t * 1.3),
        y=-1.0 + 0.5 * math.cos(t * 0.6),
        z=0.5 + 0.3 * math.sin(t * 0.4),
    ))
    face_d = Detection(position=Position3D(
        x=2.7 + 0.25 * math.sin(t * 0.8),
        y=0.0 + 0.6 * math.cos(t * 1.1),
        z=-0.5 + 0.3 * math.sin(t * 0.7),
    ))
    face_e = Detection(position=Position3D(
        x=1.8 + 0.3 * math.sin(t * 1.5),
        y=-0.5 + 0.4 * math.cos(t * 1.2),
        z=0.2 + 0.3 * math.sin(t * 0.8),
    ))

    if frame < 10:
        return [face_a, face_b, face_c, face_d]
    elif frame < 20:
        return [face_b, face_c, face_d]
    elif frame < 30:
        return [face_b, face_c, face_d, face_e]
    elif frame < 40:
        return [face_b, face_d, face_e]
    elif frame < 100:
        return [face_b, face_a]
    elif frame < 130:
       return [face_b] 
    else:
        return [face_b, face_a]


# ---------------------------------------------------------------------------
# Animated plot
# ---------------------------------------------------------------------------

def run(num_frames: int = 500, interval_ms: int = 50):
    tracker = FaceTracker()
    eye_mgr = EyeManager(eye_configs=EYE_CONFIGS, camera_config=CAMERA_CONFIG)

    track_history: dict[int, dict[str, list[float]]] = {}

    # ---------------------------------------------------------------------------
    # Figure layout
    # ---------------------------------------------------------------------------
    fig = plt.figure(figsize=(10, 8))

    ax = fig.add_axes([0.05, 0.20, 0.90, 0.70], projection='3d')
    ax.set_xlabel('X (m)')
    ax.set_ylabel('Y (m)')
    ax.set_zlabel('Z (m)')
    ax.set_xlim(-0.5, 3.1)
    ax.set_ylim(-2.1, 2.1)
    ax.set_zlim(-1.1, 1.1)
    ax.set_box_aspect([4, 5, 3])  # proportional to axis ranges for 1:1:1 scaling
    base_cylinder_radius = 0.025
    _draw_eye_cylinders(ax, EYE_CONFIGS, radius=base_cylinder_radius)
    _draw_camera_frustum(ax, CAMERA_CONFIG)

    ax_eyes = fig.add_axes([0.05, 0.05, 0.90, 0.15])
    ax_eyes.set_xlim(0,  len(EYE_CONFIGS))
    ax_eyes.set_ylim(0, 1)
    ax_eyes.axis('off')

    # Pre-create eye icon artists
    eye_circles:    list[mpatches.Ellipse] = []
    eye_id_texts:   list[plt.Text]         = []
    face_id_texts:  list[plt.Text]         = []
    yaw_texts:      list[plt.Text]         = []
    pitch_texts:    list[plt.Text]         = []

    CIRCLE_RADIUS = 0.25
    CIRCLE_Y      = 0.60
    FACE_ID_Y     = 0.32
    YAW_Y         = 0.18
    PITCH_Y       = 0.05

    for i in range( len(EYE_CONFIGS)):
        cx = i + 0.5
        circle = mpatches.Ellipse(
            (cx, CIRCLE_Y), CIRCLE_RADIUS * 2, CIRCLE_RADIUS * 2,
            color=(0.5, 0.5, 0.5),
            ec='white', linewidth=1.5,
            transform=ax_eyes.transData, zorder=2,
        )
        ax_eyes.add_patch(circle)
        eye_circles.append(circle)

        eye_id_texts.append(ax_eyes.text(
            cx, CIRCLE_Y, 'Eye ID: ' + str(i),
            ha='center', va='center',
            fontsize=9, fontweight='bold', color='white', zorder=3,
        ))
        face_id_texts.append(ax_eyes.text(
            cx, FACE_ID_Y, 'x',
            ha='center', va='center',
            fontsize=8, color='black', zorder=3,
        ))
        yaw_texts.append(ax_eyes.text(
            cx, YAW_Y, 'Y:--',
            ha='center', va='center',
            fontsize=7, color='black', zorder=3,
        ))
        pitch_texts.append(ax_eyes.text(
            cx, PITCH_Y, 'P:--',
            ha='center', va='center',
            fontsize=7, color='black', zorder=3,
        ))

    eye_cfg_by_id = {cfg.eye_id: cfg for cfg in EYE_CONFIGS}

    theta_ring = np.linspace(0, 2 * np.pi, 60)

    artists: dict[str, dict] = {
        'lines':          {},
        'points':         {},
        'face_labels':    {},
        'eye_labels':     {},
        'assignment_lines':{},
        'gimbal_arms':    {},
        'eye_cylinders':  {},
    }

    def animate(frame):
        dets          = get_detections(frame)
        tracked_faces = tracker.update(dets)        
        eye_states    = eye_mgr.update(tracked_faces)

        # Build face_id → [eye_ids]
        face_to_eyes: dict[int, list[int]] = {}
        for eye_id, state in eye_states.items():
            if state.face_id is not None:
                face_to_eyes.setdefault(state.face_id, []).append(eye_id)

        # Update eye icon strip
        for i, eye_id in enumerate(sorted(eye_states)):
            state     = eye_states[eye_id]
            mpl_color = _to_mpl_color(state.iris_color)
            eye_circles[i].set_color(mpl_color)
            eye_circles[i].set_height(CIRCLE_RADIUS * 2 * state.eye_lid)

            label = 'Face ID:' + str(state.face_id) if state.face_id is not None else 'x'
            face_id_texts[i].set_text(label)

            brightness = 0.299 * mpl_color[0] + 0.587 * mpl_color[1] + 0.114 * mpl_color[2]
            text_color = 'black' if brightness > 0.55 else 'white'
            eye_id_texts[i].set_color(text_color)

            if state.face_id is not None:
                yaw_texts[i].set_text(f'Y:{state.yaw:+.1f}°')
                pitch_texts[i].set_text(f'P:{state.pitch:+.1f}°')
                yaw_texts[i].set_color('black')
                pitch_texts[i].set_color('black')
            else:
                yaw_texts[i].set_text('Y:--')
                pitch_texts[i].set_text('P:--')
                yaw_texts[i].set_color('grey')
                pitch_texts[i].set_color('grey')

        # Rebuild 3D artists
        for group in artists.values():
            for artist in group.values():
                artist.remove()
            group.clear()

        # Draw animated gimbal arms and pitch pivot cylinders.
        # The arm extends from the yaw pivot (cfg.position) and rotates with yaw.
        # The pitch pivot ring is oriented perpendicular to the look direction (yaw + pitch).
        eye_cylinder_radius = 0.05
        for eye_id, state in eye_states.items():
            cfg     = eye_cfg_by_id[eye_id]
            yaw_r   = math.radians(state.yaw)
            pitch_r = math.radians(state.pitch)

            # Rotate the arm offset by yaw around Z to get the pitch pivot world position
            ox, oy, oz = cfg.pitch_pivot_offset.x, cfg.pitch_pivot_offset.y, cfg.pitch_pivot_offset.z
            pp_x = cfg.position.x + ox * math.cos(yaw_r) - oy * math.sin(yaw_r)
            pp_y = cfg.position.y + ox * math.sin(yaw_r) + oy * math.cos(yaw_r)
            pp_z = cfg.position.z + oz

            # Arm line: yaw pivot → pitch pivot
            artists['gimbal_arms'][eye_id] = ax.plot(
                [cfg.position.x, pp_x],
                [cfg.position.y, pp_y],
                [cfg.position.z, pp_z],
                color='black', linewidth=1.5,
            )[0]

            # Eye cylinder ring — perpendicular to the look direction (yaw + pitch).
            # Look direction (ring normal):
            #   dx = cos(pitch) * cos(yaw),  dy = cos(pitch) * sin(yaw),  dz = sin(pitch)
            # u = pitch axis (horizontal, perpendicular to arm): [-sin(yaw), cos(yaw), 0]
            # v = cross(look, u) = [-sin(pitch)*cos(yaw), -sin(pitch)*sin(yaw), cos(pitch)]
            cp, sp = math.cos(pitch_r), math.sin(pitch_r)
            cy, sy = math.cos(yaw_r),   math.sin(yaw_r)
            ux, uy, uz =  -sy,       cy,       0.0
            vx, vy, vz =  -sp * cy, -sp * sy,  cp
            ring_x = pp_x + eye_cylinder_radius * (np.cos(theta_ring) * ux + np.sin(theta_ring) * vx)
            ring_y = pp_y + eye_cylinder_radius * (np.cos(theta_ring) * uy + np.sin(theta_ring) * vy)
            ring_z = pp_z + eye_cylinder_radius * (np.cos(theta_ring) * uz + np.sin(theta_ring) * vz)
            artists['eye_cylinders'][eye_id] = ax.plot(
                ring_x, ring_y, ring_z,
                color='black', linewidth=1.0,
            )[0]

            # Assignment line — projects along the eye cylinder normal (always perpendicular to the ring).
            if state.face_id is not None and state.face_id in tracked_faces:
                fp = tracked_faces[state.face_id]
                ray_len = math.sqrt((fp.x - pp_x)**2 + (fp.y - pp_y)**2 + (fp.z - pp_z)**2)
                look_x = cp * cy
                look_y = cp * sy
                look_z = sp
                mpl_color = _to_mpl_color(state.iris_color)
                artists['assignment_lines'][eye_id] = ax.plot(
                    [pp_x, pp_x + ray_len * look_x],
                    [pp_y, pp_y + ray_len * look_y],
                    [pp_z, pp_z + ray_len * look_z],
                    color=mpl_color, linewidth=1.5, alpha=0.6,
                )[0]

        TRAIL_LEN = 300
        TRAIL_SEGMENTS = 6  # number of fade segments

        for track_id, pos in tracked_faces.items():
            if track_id not in track_history:
                track_history[track_id] = {'x': [], 'y': [], 'z': []}
            track_history[track_id]['x'].append(pos.x)
            track_history[track_id]['y'].append(pos.y)
            track_history[track_id]['z'].append(pos.z)

            hist = track_history[track_id]
            rx = hist['x'][-TRAIL_LEN:]
            ry = hist['y'][-TRAIL_LEN:]
            rz = hist['z'][-TRAIL_LEN:]
            n = len(rx)

            # Draw trail as segments with fading alpha (oldest → most transparent)
            seg_size = max(1, n // TRAIL_SEGMENTS)
            for seg_i in range(0, n - 1, seg_size):
                seg_end = min(seg_i + seg_size + 1, n)
                alpha = 0.1 + 0.5 * (seg_i / max(n - 1, 1))
                artists['lines'][(track_id, seg_i)] = ax.plot(
                    rx[seg_i:seg_end], ry[seg_i:seg_end], rz[seg_i:seg_end],
                    color='black', alpha=alpha, linewidth=1.0)[0]
            artists['points'][track_id] = ax.scatter(
                pos.x, pos.y, pos.z, color='black', s=100, marker='o')
            artists['face_labels'][track_id] = ax.text(
                pos.x, pos.y, pos.z + 0.06, f'ID {track_id}',
                fontsize=8, color='black', ha='center', va='bottom')

            if track_id in face_to_eyes:
                eye_label = 'Eyes: ' + ','.join(map(str, face_to_eyes[track_id]))
                artists['eye_labels'][track_id] = ax.text(
                    pos.x, pos.y, pos.z - 0.1, eye_label,
                    fontsize=8, color='black', ha='center', va='top')

        ax.set_title(f'aEyes — Face Tracking + Eye Assignment — frame {frame}')
        return (
            list(eye_circles)
            + eye_id_texts
            + face_id_texts
            + yaw_texts
            + pitch_texts
            + [a for group in artists.values() for a in group.values()]
        )

    ani = animation.FuncAnimation(
        fig, animate,
        frames=num_frames if num_frames > 0 else None,
        interval=interval_ms,
        blit=False,
        repeat=False,
    )

    paused = [False]
    pause_text = fig.text(0.5, 0.97, '', ha='center', va='top', fontsize=9, color='red')

    def on_key(event):
        if event.key != ' ':
            return
        if paused[0]:
            ani.resume()
            paused[0] = False
            pause_text.set_text('')
        else:
            ani.pause()
            paused[0] = True
            pause_text.set_text('PAUSED — zoom/rotate freely, press Space to resume')
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect('key_press_event', on_key)

    plt.show()
    return ani


if __name__ == "__main__":
    run(num_frames=500, interval_ms=150)