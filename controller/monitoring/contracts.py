"""Shared, dependency-light monitoring contracts."""

from dataclasses import asdict
import hashlib
import json

SCHEMA_VERSION = 1
ENDPOINT = "tcp://127.0.0.1:9101"
STALE_SECONDS = 1.0


def revision(values: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            values, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def capture_key(message) -> str:
    # Original SDK timestamp, not separately translated Python monotonic times.
    micros = round(message.getTimestamp().total_seconds() * 1_000_000)
    return f"{message.getSequenceNum()}-{micros}"


def geometry() -> dict:
    from config import CAMERA_CONFIG, EYE_CONFIGS

    return {
        "camera": asdict(CAMERA_CONFIG),
        "eyes": [asdict(e) for e in EYE_CONFIGS],
        "coordinates": "X forward, Y left, Z up; meters; positions relative to camera",
    }
