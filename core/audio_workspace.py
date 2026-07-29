import fcntl
import logging
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

_PREFIX = "podcast-bot-audio-"
_LOCK_PREFIX = f".{_PREFIX}"
_LOCK_SUFFIX = ".lock"


def _workspace_for_lock(lock_path: Path) -> Path:
    return lock_path.with_name(lock_path.name.removeprefix(".").removesuffix(_LOCK_SUFFIX))


def _lock_for_workspace(workspace: Path) -> Path:
    return workspace.with_name(f".{workspace.name}{_LOCK_SUFFIX}")


def _try_lock(lock_path: Path):
    lock_file = lock_path.open("a+")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    return lock_file


def cleanup_stale_audio_workspaces() -> None:
    """Remove workspaces left by processes that no longer hold their lock."""
    temp_root = Path(tempfile.gettempdir())
    removed = 0

    for workspace in temp_root.glob(f"{_PREFIX}*"):
        if not workspace.is_dir():
            continue
        lock_path = _lock_for_workspace(workspace)
        lock_file = _try_lock(lock_path)
        if lock_file is None:
            continue
        try:
            shutil.rmtree(workspace)
            lock_path.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            logger.warning("Failed to remove stale audio workspace %s: %s", workspace, exc)
        finally:
            lock_file.close()

    for lock_path in temp_root.glob(f"{_LOCK_PREFIX}*{_LOCK_SUFFIX}"):
        workspace = _workspace_for_lock(lock_path)
        if workspace.exists():
            continue
        lock_file = _try_lock(lock_path)
        if lock_file is None:
            continue
        try:
            lock_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove orphaned audio workspace lock %s: %s", lock_path, exc)
        finally:
            lock_file.close()

    if removed:
        logger.info("Removed %d stale audio workspace(s)", removed)


@contextmanager
def audio_workspace() -> Generator[Path]:
    """Create a locked workspace and remove all of its files on exit."""
    temp_root = Path(tempfile.gettempdir())
    raw_lock = tempfile.NamedTemporaryFile(prefix=_LOCK_PREFIX, suffix=_LOCK_SUFFIX, dir=temp_root, delete=False)
    lock_path = Path(raw_lock.name)
    workspace = _workspace_for_lock(lock_path)

    try:
        fcntl.flock(raw_lock, fcntl.LOCK_EX)
        workspace.mkdir(mode=0o700)
        yield workspace
    finally:
        try:
            shutil.rmtree(workspace)
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("Failed to remove audio workspace %s: %s", workspace, exc)
        fcntl.flock(raw_lock, fcntl.LOCK_UN)
        raw_lock.close()
        try:
            lock_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove audio workspace lock %s: %s", lock_path, exc)
