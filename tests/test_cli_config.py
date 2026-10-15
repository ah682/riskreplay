"""Server configuration must not prevent independent offline CLI workflows."""

from __future__ import annotations

import pytest

from riskreplay.cli import main


def test_help_ignores_invalid_server_port_environment(monkeypatch, capsys):
    monkeypatch.setenv("RISKREPLAY_PORT", "not-a-number")
    with pytest.raises(SystemExit) as error:
        main(["--help"])
    assert error.value.code == 0
    assert "Inspect historical risk decisions" in capsys.readouterr().out


def test_offline_command_ignores_invalid_server_port_environment(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("RISKREPLAY_PORT", "not-a-number")
    with pytest.raises(SystemExit) as error:
        main(["--data-dir", str(tmp_path), "replay", "unknown"])
    assert error.value.code == 2
    assert "No dataset selected" in capsys.readouterr().err


@pytest.mark.parametrize("port", ["not-a-number", "0", "-1", "65536"])
def test_serve_rejects_invalid_port_environment_actionably(monkeypatch, capsys, port):
    monkeypatch.setenv("RISKREPLAY_PORT", port)
    with pytest.raises(SystemExit) as error:
        main(["serve"])
    assert error.value.code == 2
    message = capsys.readouterr().err
    assert "port" in message.lower()
    assert "1" in message and "65535" in message
    assert "Traceback" not in message


@pytest.mark.parametrize("port", ["not-a-number", "0", "-1", "65536"])
def test_serve_rejects_invalid_explicit_port_actionably(monkeypatch, capsys, port):
    monkeypatch.delenv("RISKREPLAY_PORT", raising=False)
    with pytest.raises(SystemExit) as error:
        main(["serve", "--port", port])
    assert error.value.code == 2
    message = capsys.readouterr().err
    assert "port" in message.lower()
    assert "1" in message and "65535" in message


@pytest.mark.parametrize("port", [1, 65535])
def test_explicit_valid_port_overrides_invalid_environment(monkeypatch, tmp_path, port):
    monkeypatch.setenv("RISKREPLAY_PORT", "not-a-number")
    started = []

    # The only substituted boundary is starting a blocking network listener.
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: started.append(kwargs))
    main(["--data-dir", str(tmp_path), "serve", "--port", str(port)])
    assert started == [{"host": "127.0.0.1", "port": port, "log_level": "warning"}]


def test_reset_rejects_symlinked_ownership_marker_and_preserves_unrelated_files(tmp_path, capsys):
    root = tmp_path / "unowned"
    root.mkdir()
    note = root / "unrelated-note.txt"
    note.write_text("keep me")
    borrowed_marker = tmp_path / "borrowed-marker"
    borrowed_marker.touch()
    (root / ".riskreplay-owned").symlink_to(borrowed_marker)
    with pytest.raises(SystemExit) as error:
        main(["--data-dir", str(root), "reset", "--yes"])
    assert error.value.code == 2
    assert "Refusing reset" in capsys.readouterr().err
    assert note.read_text() == "keep me"
    assert borrowed_marker.exists()
