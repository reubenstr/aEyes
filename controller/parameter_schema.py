"""Pure configuration types and validation, safe to import without loading YAML."""
from __future__ import annotations

import math
import re
import types
from dataclasses import dataclass
from typing import get_type_hints, get_args, get_origin

@dataclass
class SystemParams:
    refresh_rate_hz: int


@dataclass
class PublisherParams:
    socket_port: int
    socket_address: str


@dataclass
class TrackerParams:
    base_max_distance: float
    depth_scale_factor: float
    embedding_weight: float
    min_hits_to_confirm: int
    min_hits_to_confirm_reacquiring_tracks: int
    max_missing_confirmed: int
    max_missing_tentative: int
    reid_window_frames: int
    reid_max_distance: float
    ema_alpha: float
    embedding_ema_keep: float
    static_window: int
    static_speed_thresh_mps: float
    mahalanobis_gate: float
    min_detection_confidence: float
    min_bbox_iou: float
    depth_grace_s: float
    coast_time_s: float


@dataclass
class KalmanParams:
    acceleration_noise: float
    measurement_std_lateral: float
    measurement_std_depth: float


@dataclass
class AssignerParams:
    assign_interval_s: float


@dataclass
class EyeManagerParams:
    color_in_rate: float
    color_out_rate: float
    blink_rate: float
    radius: float
    curvature: float
    iris_size: float
    pupil_size: float
    is_cat_eye: bool
    pupil_color: tuple[int, int, int]
    sclera_color: tuple[int, int, int]
    vein_color: tuple[int, int, int]
    vein_count: int
    vein_seed: int | None
    iris_accent_hue_offset: float
    iris_accent_lightness: float
    iris_accent_saturation: float
    iris_center_hue_offset: float
    iris_center_lightness: float
    iris_center_saturation: float
    iris_striation_hue_offset: float
    iris_striation_lightness: float
    iris_striation_saturation: float
    eyelid_near_distance_m: float
    eyelid_far_distance_m: float
    eyelid_near_openness: float
    eyelid_far_openness: float
    eyelid_neutral_openness: float
    eyelid_smoothing_rate: float


@dataclass
class Params:
    system: SystemParams
    publisher: PublisherParams
    tracker: TrackerParams
    kalman: KalmanParams
    assigner: AssignerParams
    eye_manager: EyeManagerParams


def _validate(p: Params) -> None:
    def check(cond: bool, msg: str) -> None:
        if not cond:
            raise ValueError(f"params.yaml: {msg}")

    check(1 <= p.system.refresh_rate_hz <= 60,
          f"system.refresh_rate_hz={p.system.refresh_rate_hz} must be in [1, 60]")

    check(1024 <= p.publisher.socket_port <= 65535,
          f"publisher.socket_port={p.publisher.socket_port} out of valid range [1024, 65535]")

    check(0.0 < p.tracker.base_max_distance <= 5.0,
          "tracker.base_max_distance must be in (0, 5]")
    check(0.0 <= p.tracker.embedding_weight <= 1.0,
          "tracker.embedding_weight must be in [0, 1]")
    check(0.0 < p.tracker.ema_alpha <= 1.0,
          "tracker.ema_alpha must be in (0, 1]")
    check(0.0 < p.tracker.embedding_ema_keep < 1.0,
          "tracker.embedding_ema_keep must be in (0, 1)")
    check(p.tracker.static_window >= 1,
          "tracker.static_window must be a positive integer")
    check(p.tracker.static_speed_thresh_mps > 0.0,
          "tracker.static_speed_thresh_mps must be positive")
    check(p.tracker.min_hits_to_confirm >= 1,
          "tracker.min_hits_to_confirm must be a positive integer")
    check(p.tracker.min_hits_to_confirm_reacquiring_tracks >= 1,
          "tracker.min_hits_to_confirm_reacquiring_tracks must be a positive integer")
    check(p.tracker.max_missing_confirmed >= 1,
          "tracker.max_missing_confirmed must be a positive integer")
    check(p.tracker.max_missing_tentative >= 1,
          "tracker.max_missing_tentative must be a positive integer")

    for name in ("acceleration_noise", "measurement_std_lateral", "measurement_std_depth"):
        value = getattr(p.kalman, name)
        check(math.isfinite(value) and value > 0.0, f"kalman.{name} must be finite and positive")
    check(math.isfinite(p.tracker.depth_scale_factor) and p.tracker.depth_scale_factor >= 0,
          "tracker.depth_scale_factor must be finite and nonnegative")
    check(math.isfinite(p.tracker.mahalanobis_gate) and p.tracker.mahalanobis_gate > 0,
          "tracker.mahalanobis_gate must be finite and positive")
    check(0 <= p.tracker.min_detection_confidence <= 1,
          "tracker.min_detection_confidence must be in [0, 1]")
    check(0 < p.tracker.min_bbox_iou <= 1, "tracker.min_bbox_iou must be in (0, 1]")
    for name in ("depth_grace_s", "coast_time_s"):
        value = getattr(p.tracker, name)
        check(math.isfinite(value) and value > 0, f"tracker.{name} must be finite and positive")
    check(p.tracker.reid_window_frames >= 1 and p.tracker.reid_max_distance > 0,
          "tracker re-ID window and distance must be positive")

    check(p.assigner.assign_interval_s > 0.0,
          "assigner.assign_interval_s must be positive")

    check(p.eye_manager.color_in_rate > 0.0,
          "eye_manager.color_in_rate must be positive")
    check(p.eye_manager.color_out_rate > 0.0,
          "eye_manager.color_out_rate must be positive")
    check(p.eye_manager.blink_rate > 0.0,
          "eye_manager.blink_rate must be positive")

    eye = p.eye_manager
    check(math.isfinite(eye.radius) and eye.radius > 0.0,
          "eye_manager.radius must be finite and positive")
    for name in (
        "curvature", "iris_size", "pupil_size",
        "iris_accent_lightness", "iris_accent_saturation",
        "iris_center_lightness", "iris_center_saturation",
        "iris_striation_lightness", "iris_striation_saturation",
        "eyelid_near_openness", "eyelid_far_openness", "eyelid_neutral_openness",
    ):
        check(0.0 <= getattr(eye, name) <= 1.0,
              f"eye_manager.{name} must be in [0, 1]")
    for name in ("iris_accent_hue_offset", "iris_center_hue_offset", "iris_striation_hue_offset"):
        check(math.isfinite(getattr(eye, name)), f"eye_manager.{name} must be finite")
    for name in ("pupil_color", "sclera_color", "vein_color"):
        rgb = getattr(eye, name)
        check(isinstance(rgb, (list, tuple)) and len(rgb) == 3
              and all(type(c) is int and 0 <= c <= 255 for c in rgb),
              f"eye_manager.{name} must contain three integers in [0, 255]")
    check(type(eye.is_cat_eye) is bool, "eye_manager.is_cat_eye must be a boolean")
    check(type(eye.vein_count) is int and 0 <= eye.vein_count <= 24,
          "eye_manager.vein_count must be an integer in [0, 24]")
    check(eye.vein_seed is None or type(eye.vein_seed) is int,
          "eye_manager.vein_seed must be an integer or null")
    check(math.isfinite(eye.eyelid_near_distance_m)
          and math.isfinite(eye.eyelid_far_distance_m)
          and 0.0 <= eye.eyelid_near_distance_m < eye.eyelid_far_distance_m,
          "eye_manager eyelid distances must satisfy 0 <= near < far and be finite")
    check(eye.eyelid_near_openness >= eye.eyelid_far_openness,
          "eye_manager.eyelid_near_openness must be >= eyelid_far_openness")
    check(math.isfinite(eye.eyelid_smoothing_rate) and eye.eyelid_smoothing_rate > 0.0,
          "eye_manager.eyelid_smoothing_rate must be finite and positive")


def _typed(value, annotation, path):
    if get_origin(annotation) is types.UnionType:
        if value is None and type(None) in get_args(annotation):
            return None
        return _typed(value, next(t for t in get_args(annotation) if t is not type(None)), path)
    if get_origin(annotation) is tuple:
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise ValueError(f"{path}: expected an RGB triplet")
        return tuple(_typed(v, int, path) for v in value)
    if annotation is float:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"{path}: expected a finite number")
        return float(value)
    if type(value) is not annotation:
        raise ValueError(f"{path}: expected {annotation.__name__}")
    return value


def parse_params(raw: dict, reserved_ports=()) -> Params:
    """Strictly parse JSON or YAML using the same validation as the live pipeline."""
    sections = get_type_hints(Params)
    if not isinstance(raw, dict) or set(raw) != set(sections):
        raise ValueError("Configuration must contain exactly: " + ", ".join(sections))
    parsed = {}
    for section, cls in sections.items():
        values = raw[section]
        annotations = get_type_hints(cls)
        if not isinstance(values, dict) or set(values) != set(annotations):
            raise ValueError(f"{section}: missing or unknown settings")
        parsed[section] = cls(**{key: _typed(values[key], kind, f"{section}.{key}")
                                 for key, kind in annotations.items()})
    p = Params(**parsed)
    _validate(p)
    if p.publisher.socket_port in reserved_ports:
        raise ValueError("publisher.socket_port conflicts with a monitoring port")
    if not re.fullmatch(r"[a-zA-Z0-9_.*:\[\]-]+", p.publisher.socket_address):
        raise ValueError("publisher.socket_address must be an IP address, hostname, or *")
    return p


def form_metadata() -> dict:
    """Types drive controls; server-side validation remains authoritative."""
    result = {}
    for section, cls in get_type_hints(Params).items():
        result[section] = {}
        for name, annotation in get_type_hints(cls).items():
            nullable = type(None) in get_args(annotation)
            kind = ("rgb" if get_origin(annotation) is tuple else
                    "boolean" if annotation is bool else "string" if annotation is str else
                    "integer" if annotation is int or nullable else "number")
            result[section][name] = {"type": kind, "nullable": nullable,
                                     "label": name.replace("_", " ").capitalize()}
    return result

