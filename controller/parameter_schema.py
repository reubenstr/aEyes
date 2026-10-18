"""Pure configuration types and validation, safe to import without loading YAML."""
from __future__ import annotations

import math
import re
import types
from dataclasses import dataclass, field, fields
from typing import get_type_hints, get_args, get_origin


def _described(description: str):
    return field(metadata={"description": description})


@dataclass
class SystemParams:
    refresh_rate_hz: int = _described(
        "Sets the camera frame-rate limit and controller command publication rate in hertz.")


@dataclass
class PublisherParams:
    socket_port: int = _described(
        "Sets the ZMQ port used to broadcast commands, which must match the port on every eye unit.")
    socket_address: str = _described(
        "Selects the local address used to broadcast eye commands, with * binding to all interfaces.")


@dataclass
class TrackerParams:
    base_max_distance: float = _described(
        "Sets the base distance in meters allowed between a predicted track and a matching detection.")
    depth_scale_factor: float = _described(
        "Expands the matching distance by this many meters per meter of forward depth beyond one meter.")
    embedding_weight: float = _described(
        "Weights optional appearance embeddings when ranking matches that pass the spatial gates.")
    min_hits_to_confirm: int = _described(
        "Sets the consecutive matched 3D observations required before a new face track becomes public.")
    min_hits_to_confirm_reacquiring_tracks: int = _described(
        "Sets the consecutive matched 3D observations required before a lost face track becomes public again.")
    max_missing_confirmed: int = _described(
        "Sets the confirmed-track missing timeout in nominal frames, converted to seconds using refresh_rate_hz.")
    max_missing_tentative: int = _described(
        "Sets the unconfirmed-track missing timeout in nominal frames, converted to seconds using refresh_rate_hz.")
    reid_window_frames: int = _described(
        "Sets how long lost tracks remain available for identity recovery, in nominal frames converted to seconds using refresh_rate_hz.")
    reid_max_distance: float = _described(
        "Sets the maximum distance in meters for matching a detection to a predicted lost track.")
    ema_alpha: float = _described(
        "Controls output-position smoothing, with lower values producing smoother but slower responses.")
    embedding_ema_keep: float = _described(
        "Sets the fraction of the existing appearance embedding retained when an optional new embedding arrives.")
    static_window: int = _described(
        "Sets the uninterrupted stillness window before excluding a face from eye assignment, in nominal frames converted to seconds using refresh_rate_hz.")
    static_speed_thresh_mps: float = _described(
        "Sets the maximum tracked speed in meters per second for a face to count as still.")
    mahalanobis_gate: float = _described(
        "Limits the squared uncertainty-adjusted distance allowed between a predicted track and a matching 3D detection.")
    min_detection_confidence: float = _described(
        "Rejects detections whose confidence is below this threshold from zero to one.")
    min_bbox_iou: float = _described(
        "Sets the minimum image-box intersection over union needed to keep a track matched during a brief depth failure.")
    depth_grace_s: float = _described(
        "Sets how many seconds image-box matches can preserve identity after the last valid 3D observation.")
    coast_time_s: float = _described(
        "Caps how many seconds public track positions are extrapolated beyond the last valid 3D observation.")


@dataclass
class KalmanParams:
    acceleration_noise: float = _described(
        "Sets motion-model uncertainty in square meters per cubic second, with higher values allowing faster velocity changes.")
    measurement_std_lateral: float = _described(
        "Sets the assumed left-right and vertical measurement standard deviation in meters.")
    measurement_std_depth: float = _described(
        "Sets the assumed forward-depth measurement standard deviation in meters.")


@dataclass
class AssignerParams:
    assign_interval_s: float = _described(
        "Sets the minimum seconds between assigning extra eyes to faces that already have an eye.")


@dataclass
class EyeManagerParams:
    color_in_rate: float = _described(
        "Controls how quickly eye colors transition to an assigned face's palette, with higher values fading faster.")
    color_out_rate: float = _described(
        "Controls how quickly eye colors return to the neutral palette after losing a face, with higher values fading faster.")
    blink_rate: float = _described(
        "Sets the speed of the blink triggered by a new face assignment in complete blinks per second.")
    radius: float = _described(
        "Sets the outer rendered eye radius in shader coordinates independently of iris and pupil size.")
    curvature: float = _described(
        "Controls the rendered eye's surface distortion from zero to one.")
    iris_size: float = _described(
        "Controls the rendered iris size from zero to one.")
    pupil_size: float = _described(
        "Controls the pupil size relative to the iris from zero to one.")
    is_cat_eye: bool = _described(
        "Enables the renderer's cat-eye shape.")
    pupil_color: tuple[int, int, int] = _described(
        "Sets the pupil color as red, green, and blue channels from 0 to 255.")
    sclera_color: tuple[int, int, int] = _described(
        "Sets the eye-white color as red, green, and blue channels from 0 to 255.")
    vein_color: tuple[int, int, int] = _described(
        "Sets the vein color as red, green, and blue channels from 0 to 255.")
    vein_count: int = _described(
        "Sets the number of primary veins from 0 to 24, with zero hiding all veins and branches.")
    vein_seed: int | None = _described(
        "Sets the vein-pattern seed, with Auto using each eye's ID and an integer sharing one pattern across eyes.")
    iris_accent_hue_offset: float = _described(
        "Shifts the iris accent hue relative to the assigned face's base hue, measured in turns around the color wheel.")
    iris_accent_lightness: float = _described(
        "Sets the iris accent lightness from zero for black to one for white.")
    iris_accent_saturation: float = _described(
        "Sets the iris accent saturation from zero for gray to one for full color.")
    iris_center_hue_offset: float = _described(
        "Shifts the iris center hue relative to the assigned face's base hue, measured in turns around the color wheel.")
    iris_center_lightness: float = _described(
        "Sets the iris center lightness from zero for black to one for white.")
    iris_center_saturation: float = _described(
        "Sets the iris center saturation from zero for gray to one for full color.")
    iris_striation_hue_offset: float = _described(
        "Shifts the iris streak hue relative to the assigned face's base hue, measured in turns around the color wheel.")
    iris_striation_lightness: float = _described(
        "Sets the iris streak lightness from zero for black to one for white.")
    iris_striation_saturation: float = _described(
        "Sets the iris streak saturation from zero for gray to one for full color.")
    eyelid_near_distance_m: float = _described(
        "Sets the target distance in meters at or below which an eye uses the near eyelid opening.")
    eyelid_far_distance_m: float = _described(
        "Sets the target distance in meters at or beyond which an eye uses the far eyelid opening.")
    eyelid_near_openness: float = _described(
        "Sets the eyelid opening for nearby targets from zero for closed to one for fully open.")
    eyelid_far_openness: float = _described(
        "Sets the eyelid opening for distant targets from zero for closed to one for fully open.")
    eyelid_neutral_openness: float = _described(
        "Sets the resting eyelid opening when no face is assigned, from zero for closed to one for fully open.")
    eyelid_smoothing_rate: float = _described(
        "Controls how quickly resting eyelids follow distance changes, with higher values responding faster.")


@dataclass
class Params:
    system: SystemParams = field(metadata={
        "label": "System",
        "description": "Controls the timing shared by camera capture, tracking, and eye command publication.",
    })
    publisher: PublisherParams = field(metadata={
        "label": "Publisher",
        "description": "Configures ZMQ command broadcasts to the eye units, whose network settings must be updated separately to match.",
    })
    tracker: TrackerParams = field(metadata={
        "label": "Tracker",
        "description": "Controls how face detections become stable tracks, retain their identities, and recover after missing observations.",
    })
    kalman: KalmanParams = field(metadata={
        "label": "Kalman",
        "description": "Balances motion prediction against measurement uncertainty when estimating each face's 3D position and velocity.",
    })
    assigner: AssignerParams = field(metadata={
        "label": "Assigner",
        "description": "Controls how quickly additional eyes are allocated after visible faces receive initial coverage.",
    })
    eye_manager: EyeManagerParams = field(metadata={
        "label": "Eye Manager",
        "description": "Controls eye appearance, face-based color palettes, assignment blinks, and eyelid opening by target distance.",
    })


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
    """Describe parameter controls and purpose without loading configuration values."""
    result = {}
    for section, cls in get_type_hints(Params).items():
        result[section] = {}
        annotations = get_type_hints(cls)
        for parameter in fields(cls):
            name = parameter.name
            annotation = annotations[name]
            nullable = type(None) in get_args(annotation)
            kind = ("rgb" if get_origin(annotation) is tuple else
                    "boolean" if annotation is bool else "string" if annotation is str else
                    "integer" if annotation is int or nullable else "number")
            result[section][name] = {"type": kind, "nullable": nullable,
                                     "label": name,
                                     "description": parameter.metadata["description"]}
    return result


def section_metadata() -> dict:
    """Describe every settings section for API consumers."""
    return {section.name: dict(section.metadata) for section in fields(Params)}
