"""Load and validate controller/params.yaml once at startup."""
from pathlib import Path
import yaml

# Re-export the existing parameter types for compatibility.
from parameter_schema import (SystemParams, PublisherParams, TrackerParams, KalmanParams,
                              AssignerParams, EyeManagerParams, Params, parse_params, _validate)


def _load() -> Params:
    with Path(__file__).with_name("params.yaml").open() as handle:
        return parse_params(yaml.safe_load(handle))


params = _load()
