"""An interrupted writer cannot publish partial bytes or replace a competing artifact."""

import hashlib
import os
from pathlib import Path

import pytest

from riskreplay.artifacts import ArtifactStore, MissingArtifact
from riskreplay.modeling import ModelingError, _write_artifact
from riskreplay.storage import write_json


@pytest.fixture(params=["json", "joblib"])
def artifact_writer(request, tmp_path):
    if request.param == "json":
        store = ArtifactStore(tmp_path)
        return lambda: store.put("models", {"owned": "recovery fixture"}), ".json", MissingArtifact
    return (
        lambda: _write_artifact(tmp_path, {"owned": "recovery fixture"}),
        ".joblib",
        ModelingError,
    )


def test_interrupted_artifact_write_is_retryable(artifact_writer, tmp_path, monkeypatch):
    write, suffix, _ = artifact_writer
    real_open = Path.open

    class InterruptedWrite:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def write(self, data):
            self.handle.write(data[:2])
            self.handle.flush()
            raise OSError("injected interrupted write")

    def interrupt(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        return InterruptedWrite(handle) if "w" in mode or "x" in mode else handle

    with monkeypatch.context() as failure:
        failure.setattr(Path, "open", interrupt)
        with pytest.raises(OSError, match="injected interrupted write"):
            write()

    assert list((tmp_path / "models").iterdir()) == []
    key = write()
    path = tmp_path / "models" / (key + suffix)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == key
    assert write() == key
    assert list(path.parent.iterdir()) == [path]


def test_interrupted_latest_write_preserves_previous_pointer(tmp_path, monkeypatch):
    pointer = tmp_path / "latest.json"
    write_json(pointer, {"run_id": "old-run"})
    before = pointer.read_bytes()
    write_text = Path.write_text

    def interrupted(path, text, *args, **kwargs):
        write_text(path, text[:2], *args, **kwargs)
        raise OSError("injected pointer interruption")

    with monkeypatch.context() as failure:
        failure.setattr(Path, "write_text", interrupted)
        with pytest.raises(OSError, match="injected pointer interruption"):
            write_json(pointer, {"run_id": "new-run"})

    assert pointer.read_bytes() == before
    assert list(tmp_path.iterdir()) == [pointer]
    write_json(pointer, {"run_id": "new-run"})
    assert '"new-run"' in pointer.read_text()


@pytest.mark.parametrize("conflicting", [False, True])
def test_competing_artifact_publication_preserves_existing_bytes(
    artifact_writer, tmp_path, monkeypatch, conflicting
):
    write, suffix, error = artifact_writer
    link = os.link
    published = []

    def competing_writer(source, target, *args, **kwargs):
        # Another publisher wins after our staging write, before our exclusive publish.
        data = b"conflicting immutable content" if conflicting else Path(source).read_bytes()
        Path(target).write_bytes(data)
        published.append((Path(target), data))
        return link(source, target, *args, **kwargs)

    with monkeypatch.context() as race:
        race.setattr(os, "link", competing_writer)
        if conflicting:
            with pytest.raises(error):
                write()
        else:
            key = write()
            assert (tmp_path / "models" / (key + suffix)).is_file()

    assert len(published) == 1
    path, data = published[0]
    assert path.read_bytes() == data
    assert list(path.parent.iterdir()) == [path]
