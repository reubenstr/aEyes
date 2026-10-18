"""Validated configuration persistence independent of the running pipeline."""

from dataclasses import asdict
from pathlib import Path
import os
import tempfile
from threading import RLock

import yaml

from parameter_schema import parse_params, form_metadata, section_metadata
from .contracts import revision

ROOT = Path(__file__).resolve().parents[1]


class ConflictError(ValueError):
    pass


class ConfigStore:
    def __init__(
        self,
        path=ROOT / "params.yaml",
        defaults=ROOT / "params.defaults.yaml",
        reserved_ports=(8080, 9101),
    ):
        self.path, self.defaults = Path(path), Path(defaults)
        self.reserved_ports = reserved_ports
        self.lock = RLock()

    def read(self, path=None):
        with (path or self.path).open() as handle:
            return asdict(parse_params(yaml.safe_load(handle), self.reserved_ports))

    def describe(self, active=None):
        with self.lock:
            saved = self.read()
            return {
                "saved": saved,
                "defaults": self.read(self.defaults),
                "active": active,
                "revision": revision(saved),
                "active_revision": revision(active) if active else None,
                "pending_restart": active is None
                or revision(active) != revision(saved),
                "fields": form_metadata(),
                "sections": section_metadata(),
            }

    def save(self, values, expected_revision):
        validated = asdict(parse_params(values, self.reserved_ports))
        with self.lock:
            current = self.read()
            if revision(current) != expected_revision:
                raise ConflictError("Settings changed. Reload before saving.")
            original = self.path.read_bytes()
            self._replace(self.path.with_suffix(".yaml.bak"), original)
            self._replace(
                self.path, yaml.safe_dump(validated, sort_keys=False).encode()
            )
            return revision(validated)

    def _replace(self, target, contents):
        fd, temp = tempfile.mkstemp(prefix=".aeyes-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, self.path.stat().st_mode & 0o777)
            os.replace(temp, target)
            directory = os.open(target.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
