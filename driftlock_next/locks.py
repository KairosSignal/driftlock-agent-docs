"""Advisory lock without importing platform-specific modules during CLI startup."""
from contextlib import contextmanager
from pathlib import Path
import os

@contextmanager
def exclusive(path):
    path = Path(path)
    # Avoid following a replaced lock symlink on POSIX.
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            # Windows byte-range locks apply to an actual byte; reserve byte zero.
            with os.fdopen(fd, "r+b", closefd=False) as io:
                io.seek(0)
                if not io.read(1):
                    io.seek(0); io.write(b"\x00"); io.flush()
                io.seek(0)
            import time
            for attempt in range(200):
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if attempt == 199: raise
                    time.sleep(.05)
            try: yield
            finally:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
            try: yield
            finally: fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)

def checked_private_directory(path, anchor):
    """Reject symlink parent paths and paths escaping a trusted Git common-dir."""
    path = Path(path)
    anchor = Path(anchor).resolve()
    if not path.is_relative_to(anchor):
        from .common import fail
        fail("UNSAFE_LEDGER_DIR", "Directory escapes Git common dir")
    current = anchor
    from .common import fail
    for part in path.relative_to(anchor).parts:
        current = current / part
        if current.is_symlink():
            fail("UNSAFE_LEDGER_DIR", f"Symlink in ledger directory: {current}")
        if not current.exists():
            current.mkdir(mode=0o700)
        if not current.is_dir() or current.is_symlink():
            fail("UNSAFE_LEDGER_DIR", f"Not a real directory: {current}")
    return path
