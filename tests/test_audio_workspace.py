import fcntl
from pathlib import Path
from unittest.mock import patch

from core.audio_workspace import audio_workspace, cleanup_stale_audio_workspaces


def test_workspace_removes_all_files_on_exit(tmp_path):
    with patch("core.audio_workspace.tempfile.gettempdir", return_value=str(tmp_path)):
        with audio_workspace() as workspace:
            (workspace / "source.audio").write_bytes(b"audio")
            (workspace / "chunk.mp3").write_bytes(b"chunk")
            assert workspace.exists()

    assert not list(tmp_path.iterdir())


def test_cleanup_removes_stale_workspace_but_not_unrelated_files(tmp_path):
    stale = tmp_path / "podcast-bot-audio-stale"
    stale.mkdir()
    (stale / "source.audio").write_bytes(b"audio")
    unrelated = tmp_path / "other-app.audio"
    unrelated.write_bytes(b"keep")

    with patch("core.audio_workspace.tempfile.gettempdir", return_value=str(tmp_path)):
        cleanup_stale_audio_workspaces()

    assert not stale.exists()
    assert unrelated.read_bytes() == b"keep"


def test_cleanup_preserves_locked_workspace(tmp_path):
    with patch("core.audio_workspace.tempfile.gettempdir", return_value=str(tmp_path)):
        with audio_workspace() as workspace:
            cleanup_stale_audio_workspaces()
            assert workspace.exists()


def test_cleanup_removes_orphaned_lock(tmp_path):
    lock_path = tmp_path / ".podcast-bot-audio-orphan.lock"
    lock_path.touch()

    with patch("core.audio_workspace.tempfile.gettempdir", return_value=str(tmp_path)):
        cleanup_stale_audio_workspaces()

    assert not lock_path.exists()


def test_cleanup_preserves_lock_held_by_another_owner(tmp_path):
    lock_path = tmp_path / ".podcast-bot-audio-active.lock"
    workspace = Path(tmp_path / "podcast-bot-audio-active")
    workspace.mkdir()
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with patch("core.audio_workspace.tempfile.gettempdir", return_value=str(tmp_path)):
            cleanup_stale_audio_workspaces()
        assert workspace.exists()
