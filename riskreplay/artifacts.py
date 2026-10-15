"""Content-addressed, hash-verified JSON artifacts; trained binaries are local-only."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .schema import canonical


class MissingArtifact(ValueError):
    pass


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, kind: str, value: dict) -> str:
        data = canonical(value)
        key = hashlib.sha256(data).hexdigest()
        path = self._path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                raise MissingArtifact(f"Corrupted artifact {kind}/{key}")
        else:
            with path.open("xb") as handle:
                handle.write(data)
        return key

    def _path(self, kind: str, key: str) -> Path:
        if kind not in {"policies", "features", "rules", "models"} or not re.fullmatch(
            r"[0-9a-f]{64}", key
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
        return json.loads(data)
