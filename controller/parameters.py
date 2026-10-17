"""
Loads controller/params.yaml at import time and exposes all parameters
with attribute-style access and full type-checker support.

Usage:
    from parameters import params

    rate = params.system.refresh_rate_hz
    port = params.publisher.socket_port
"""

from __future__ import annotations
import math
import os
from dataclasses import dataclass
import yaml


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


@dataclass
class KalmanParams:
    process_noise: float
    measurement_noise_xy: float
    measurement_noise_z: float


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

    check(p.kalman.process_noise > 0.0,
          "kalman.process_noise must be positive")
    check(p.kalman.measurement_noise_xy > 0.0,
          "kalman.measurement_noise_xy must be positive")
    check(p.kalman.measurement_noise_z > 0.0,
          "kalman.measurement_noise_z must be positive")

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


def _load() -> Params:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "params.yaml")
    with open(path) as f:
        raw = yaml.safe_load(f)
    if not raw:
        raise ValueError(f"params.yaml at {path} is empty or invalid")

    p = Params(
        system=SystemParams(**raw["system"]),
        publisher=PublisherParams(**raw["publisher"]),
        tracker=TrackerParams(**raw["tracker"]),
        kalman=KalmanParams(**raw["kalman"]),
        assigner=AssignerParams(**raw["assigner"]),
        eye_manager=EyeManagerParams(**raw["eye_manager"]),
    )
    _validate(p)
    return p


params = _load()
