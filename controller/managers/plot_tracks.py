"""
visualize_tracks.py
--------------------
Real-time animated 3D plot of face tracks and eye assignments.
The tracker and eye manager are stepped once per animation frame
so that wall-clock time drives the rate-limiter correctly.
"""

import math
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.animation as animation

from face_tracker import FaceTracker
from eye_assignment import EyeAssignmentManager
from eye_manager import EyeManager
from data_types import Detection, EyeConfig, Position3D


# ---------------------------------------------------------------------------
# Eye layout
# ---------------------------------------------------------------------------

EYE_CONFIGS = [
    EyeConfig(eye_id=0, x=-0.2, y=0.0, z=0.5),
    EyeConfig(eye_id=1, x=-0.1, y=0.0, z=0.5),
    EyeConfig(eye_id=2, x= 0.0, y=0.0, z=0.5),
    EyeConfig(eye_id=3, x= 0.1, y=0.0, z=0.5),
    EyeConfig(eye_id=4, x= 0.2, y=0.0, z=0.5),
    EyeConfig(eye_id=5, x= 0.3, y=0.0, z=0.5),
]

NUM_EYES = len(EYE_CONFIGS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_mpl_color(color) -> tuple[float, float, float]:
    """Normalise a Color(r,g,b) from 0-255 to the 0.0-1.0 range matplotlib expects."""
    return (color.red / 255.0, color.green / 255.0, color.blue / 255.0)


# ---------------------------------------------------------------------------
# Simulated detections
# ---------------------------------------------------------------------------

def get_detections(frame: int) -> list[Detection]:
    """Return the set of Detection objects for a given frame number."""
    t = frame * 0.05

    face_a = Detection(position=Position3D(
        x=0.1 + 0.02 * math.sin(t),
        y=0.0 + 0.01 * math.cos(t),
        z=0.5 + 0.05 * math.sin(t * 0.5),
    ))
    face_b = Detection(position=Position3D(
        x=-0.3 + 0.03 * math.cos(t),
        y=0.05,
        z=0.8 + 0.1 * math.sin(t * 0.3),
    ))
    face_c = Detection(position=Position3D(
        x=-0.4 + 0.01 * frame,
        y=0.0,
        z=0.5 + 0.005 * frame,
    ))
    face_d = Detection(position=Position3D(
        x=0.4 - 0.01 * frame,
        y=0.0,
        z=0.8 - 0.005 * frame,
    ))
    face_new = Detection(position=Position3D(
        x=-0.4 + 0.02 * math.sin(t * 1.5),
        y=0.1  + 0.01 * math.cos(t * 1.2),
        z=0.6  + 0.03 * math.sin(t * 0.8),
    ))

    if frame < 10:
        return [face_a, face_b, face_c, face_d]
    elif frame < 20:
        return [face_b, face_c, face_d]
    elif frame < 30:
        return [face_b, face_c, face_d, face_new]
    elif frame < 40:
        return [face_b, face_d, face_new]
    elif frame < 50:
        return [face_b]
    else:
        return []


# ---------------------------------------------------------------------------
# Animated plot
# ---------------------------------------------------------------------------

def run(num_frames: int = 500, interval_ms: int = 50):
    tracker = FaceTracker(
        base_max_distance=0.4,
        depth_scale_factor=0.15,
        min_hits_to_confirm=3,
        max_missing_confirmed=15,
        reid_window_frames=30,
        ema_alpha=0.4,
    )
    eye_assignment_manager = EyeAssignmentManager(
        eye_configs=EYE_CONFIGS,
        assign_interval_s=1.0,
    )
    eye_mgr = EyeManager(eye_configs=EYE_CONFIGS)

    track_history: dict[int, dict[str, list[float]]] = {}

    # ---------------------------------------------------------------------------
    # Figure layout
    # ---------------------------------------------------------------------------
    fig = plt.figure(figsize=(10, 8))

    ax = fig.add_axes([0.05, 0.20, 0.90, 0.70], projection='3d')
    ax.set_xlabel('X (m)')
    ax.set_ylabel('Y (m)')
    ax.set_zlabel('Z (m)')
    ax.set_xlim(-0.5, 0.5)
    ax.set_ylim(-0.5, 0.5)
    ax.set_zlim(-0.5, 1.0)
    ax.set_box_aspect([1, 1, 1])

    ax_eyes = fig.add_axes([0.05, 0.05, 0.90, 0.15])
    ax_eyes.set_xlim(0, NUM_EYES)
    ax_eyes.set_ylim(0, 1)
    ax_eyes.axis('off')

    # Pre-create eye icon artists
    eye_circles:    list[mpatches.Circle] = []
    eye_id_texts:   list[plt.Text]        = []
    face_id_texts:  list[plt.Text]        = []

    CIRCLE_RADIUS = 0.28
    CIRCLE_Y      = 0.55
    LABEL_Y       = 0.08

    for i in range(NUM_EYES):
        cx = i + 0.5
        circle = mpatches.Circle(
            (cx, CIRCLE_Y), CIRCLE_RADIUS,
            color=(0.5, 0.5, 0.5),
            ec='white', linewidth=1.5,
            transform=ax_eyes.transData, zorder=2,
        )
        ax_eyes.add_patch(circle)
        eye_circles.append(circle)

        eye_id_texts.append(ax_eyes.text(
            cx, CIRCLE_Y, str(i),
            ha='center', va='center',
            fontsize=9, fontweight='bold', color='white', zorder=3,
        ))
        face_id_texts.append(ax_eyes.text(
            cx, LABEL_Y, 'x',
            ha='center', va='center',
            fontsize=8, color='grey', zorder=3,
        ))

    artists: dict[str, dict] = {
        'lines':       {},
        'points':      {},
        'face_labels': {},
        'eye_labels':  {},
    }

    def animate(frame):
        dets          = get_detections(frame)
        tracked_faces = tracker.update(dets)
        assignments   = eye_assignment_manager.update(tracked_faces)
        eye_states    = eye_mgr.update(assignments)

        # Build face_id → [eye_ids]
        face_to_eyes: dict[int, list[int]] = {}
        for eye_id, face_id in assignments.items():
            if face_id is not None:
                face_to_eyes.setdefault(face_id, []).append(eye_id)

        # Update eye icon strip
        for i, eye_id in enumerate(sorted(eye_states)):
            state     = eye_states[eye_id]
            mpl_color = _to_mpl_color(state.iris_color)
            eye_circles[i].set_color(mpl_color)

            label = str(state.face_id) if state.face_id is not None else 'x'
            face_id_texts[i].set_text(label)

            brightness = 0.299 * mpl_color[0] + 0.587 * mpl_color[1] + 0.114 * mpl_color[2]
            text_color = 'black' if brightness > 0.55 else 'white'
            eye_id_texts[i].set_color(text_color)
            face_id_texts[i].set_color(text_color)

        # Rebuild 3D artists
        for group in artists.values():
            for artist in group.values():
                artist.remove()
            group.clear()

        for track_id, pos in tracked_faces.items():
            if track_id not in track_history:
                track_history[track_id] = {'x': [], 'y': [], 'z': []}
            track_history[track_id]['x'].append(pos.x)
            track_history[track_id]['y'].append(pos.y)
            track_history[track_id]['z'].append(pos.z)

            hist = track_history[track_id]
            rx = hist['x'][-300:]
            ry = hist['y'][-300:]
            rz = hist['z'][-300:]

            artists['lines'][track_id] = ax.plot(
                rx, ry, rz, color='black', alpha=0.4)[0]
            artists['points'][track_id] = ax.scatter(
                pos.x, pos.y, pos.z, color='black', s=100, marker='o')
            artists['face_labels'][track_id] = ax.text(
                pos.x, pos.y, pos.z, f'ID {track_id}',
                fontsize=8, color='black', ha='center', va='bottom')

            if track_id in face_to_eyes:
                eye_label = 'Eyes: ' + ','.join(map(str, face_to_eyes[track_id]))
                artists['eye_labels'][track_id] = ax.text(
                    pos.x, pos.y, pos.z - 0.1, eye_label,
                    fontsize=6, color='black', ha='center', va='top')

        ax.set_title(f'Face Tracking + Eye Assignment  —  frame {frame}')
        return (
            list(eye_circles)
            + eye_id_texts
            + face_id_texts
            + [a for group in artists.values() for a in group.values()]
        )

    ani = animation.FuncAnimation(
        fig, animate,
        frames=num_frames if num_frames > 0 else None,
        interval=interval_ms,
        blit=False,
        repeat=False,
    )

    plt.show()
    return ani


if __name__ == "__main__":
    run(num_frames=500, interval_ms=250)