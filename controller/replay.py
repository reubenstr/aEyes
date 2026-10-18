"""Replay JSONL captures without camera/network/motor access.

Each line contains timestamp and detections (the format produced by main --record).
Optional truth: [{"id": "person-a", "position": {"x": 2, "y": 0, "z": 0}}]
provides independent identity/position labels for evaluation. Unlabelled recordings
report diagnostics only; identity and accuracy metrics remain null.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from config import CAMERA_CONFIG, EYE_CONFIGS
from conversions import Conversions
from data_types import Detection, Position3D
from face_tracker import FaceTracker


def _direction(yaw: float, pitch: float):
    yaw, pitch = math.radians(yaw), math.radians(pitch)
    return np.array([math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch)])


def evaluate(frames, tracker: FaceTracker | None = None, match_distance: float = 1.0) -> dict:
    if not math.isfinite(match_distance) or match_distance <= 0:
        raise ValueError("match_distance must be finite and positive")
    tracker = tracker or FaceTracker()
    conversions = Conversions(EYE_CONFIGS, CAMERA_CONFIG)
    identities = {}
    position_errors, angle_errors, reacquisition_delays = [], [], []
    counts = dict(frames=0, positioned_detections=0, depthless_detections=0, labelled_frames=0)
    switches = fragments = 0
    first_time = previous_time = None
    max_gap = 0.
    for frame in frames:
        timestamp = float(frame['timestamp'])
        if not math.isfinite(timestamp) or (previous_time is not None and timestamp <= previous_time):
            raise ValueError("Replay timestamps must be finite and strictly increasing")
        if first_time is None:
            first_time = timestamp
        if previous_time is not None:
            max_gap = max(max_gap, timestamp - previous_time)
        previous_time = timestamp
        detections = []
        for raw in frame['detections']:
            item = dict(raw)
            item['position'] = Position3D(**item['position']) if item['position'] is not None else None
            if item.get('bbox') is not None:
                item['bbox'] = tuple(item['bbox'])
            detections.append(Detection(**item))
        output = tracker.update(detections, timestamp=timestamp)
        counts['frames'] += 1
        counts['positioned_detections'] += sum(d.position is not None and d.depth_quality > 0 for d in detections)
        counts['depthless_detections'] += sum(d.position is None or d.depth_quality <= 0 for d in detections)
        if 'truth' not in frame:
            continue
        counts['labelled_frames'] += 1
        truth = [(str(item['id']), Position3D(**item['position'])) for item in frame['truth']]
        if len({identity for identity, _ in truth}) != len(truth):
            raise ValueError("Truth identities must be unique within a frame")
        tracks = list(output.items())
        penalty = len(truth) + len(tracks) + 1.
        costs = np.full((len(truth), len(tracks) + len(truth)), penalty)
        for i, (_, position) in enumerate(truth):
            if not all(math.isfinite(v) for v in (position.x, position.y, position.z)):
                raise ValueError("Truth positions must be finite")
            for j, (_, track) in enumerate(tracks):
                distance = math.dist((position.x, position.y, position.z),
                                     (track.position.x, track.position.y, track.position.z))
                costs[i, j] = distance / match_distance if distance <= match_distance else math.inf
        rows, columns = linear_sum_assignment(costs)
        matches = {int(i): int(j) for i, j in zip(rows, columns) if j < len(tracks)}
        for i, (identity, position) in enumerate(truth):
            state = identities.setdefault(identity, {'last_id': None, 'gap': None})
            if i not in matches:
                if state['last_id'] is not None and state['gap'] is None:
                    state['gap'] = timestamp
                continue
            tid, tracked = tracks[matches[i]]
            if state['last_id'] is not None and state['last_id'] != tid:
                switches += 1
            if state['gap'] is not None:
                fragments += 1
                reacquisition_delays.append(timestamp - state['gap'])
            state.update(last_id=tid, gap=None)
            position_errors.append(costs[i, matches[i]] * match_distance)
            for eye in EYE_CONFIGS:
                ideal = conversions.get_pitch_yaw(eye.eye_id, position)
                if any(abs(angle) > 45 for angle in ideal):
                    continue  # This eye cannot reach the ground-truth direction.
                estimated = conversions.get_pitch_yaw(eye.eye_id, tracked.position)
                commanded = tuple(max(-45., min(45., angle)) for angle in estimated)
                dot = float(_direction(*ideal) @ _direction(*commanded))
                angle_errors.append(math.degrees(math.acos(max(-1., min(1., dot)))))
    labelled = counts['labelled_frames'] > 0
    return {**counts, 'duration_s': 0. if first_time is None else previous_time - first_time,
            'max_frame_gap_s': max_gap, 'track_ids_created': tracker._next_id,
            'id_switches': switches if labelled else None,
            'fragmentations': fragments if labelled else None,
            'mean_reacquisition_delay_s': float(np.mean(reacquisition_delays)) if reacquisition_delays else None,
            'mean_position_error_m': float(np.mean(position_errors)) if position_errors else None,
            'mean_target_angle_error_deg': float(np.mean(angle_errors)) if angle_errors else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recording', type=Path)
    parser.add_argument('--match-distance', type=float, default=1.0)
    args = parser.parse_args()
    with args.recording.open() as source:
        metrics = evaluate((json.loads(line) for line in source if line.strip()), match_distance=args.match_distance)
    print(json.dumps(metrics, indent=2))


if __name__ == '__main__':
    main()
