"""Content-addressed, hash-verified JSON artifacts; trained binaries are local-only."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .schema import canonical


class MissingArtifact(ValueError):
    pass


def write_immutable(path: Path, data: bytes) -> None:
    """Publish complete bytes exclusively; a competing publisher may only agree."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".writing-", dir=path.parent) as temporary:
        staged = Path(temporary) / path.name
        staged.write_bytes(data)
        try:
            os.link(staged, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise FileExistsError(f"Conflicting immutable artifact {path}") from None


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, kind: str, value: dict) -> str:
        data = canonical(value)
        key = hashlib.sha256(data).hexdigest()
        path = self._path(kind, key)
        try:
            write_immutable(path, data)
        except FileExistsError as exc:
            raise MissingArtifact(f"Corrupted artifact {kind}/{key}") from exc
        return key

    def _path(self, kind: str, key: str) -> Path:
        if (
            kind not in {"policies", "features", "rules", "models"}
            or not isinstance(key, str)
            or not re.fullmatch(r"[0-9a-f]{64}", key)
        ):
            raise MissingArtifact(f"Invalid artifact reference {kind}/{key}")
        return self.root / kind / f"{key}.json"

    def get(self, kind: str, key: str) -> dict:
        path = self._path(kind, key)
        if not path.is_file():
            raise MissingArtifact(f"Missing historical {kind} artifact {key}")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != key:
            raise MissingArtifact(f"Hash mismatch in historical {kind} artifact {key}")
        try:
            value = json.loads(data)
        except ValueError as exc:
            raise MissingArtifact(f"Invalid JSON in historical {kind} artifact {key}") from exc
        if not isinstance(value, dict):
            raise MissingArtifact(f"Historical {kind} artifact {key} must be an object")
        return value
