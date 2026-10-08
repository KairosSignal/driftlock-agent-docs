"""Optimistic filesystem-safe writes for already-authorized source documents."""
from __future__ import annotations
import fcntl
import os
import tempfile
from pathlib import Path
from .common import fail, sha, text_file, within

def change(project_root, relative, expected_sha, replacement, *, approve, allow_create=False):
    if not approve:
        fail("APPROVAL_REQUIRED", "Explicit approve is required")
    root = Path(project_root).resolve()
    target = within(root, relative, allow_missing=allow_create)
    if not target.exists() and not allow_create:
        fail("MISSING_AUTHORITY", f"Cannot create authority record: {relative}")
    if target.exists() and (not target.is_file() or target.is_symlink()):
        fail("UNSAFE_AUTHORITY", "Expected regular non-symlink file")
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.parent / ("." + target.name + ".driftlock-write.lock")
    if lock.is_symlink():
        fail("UNSAFE_LOCK", "Refuse symlink lock file")
    with lock.open("a+b") as fp:
        fcntl.flock(fp, fcntl.LOCK_EX)
        current = text_file(target) if target.exists() else ""
        digest = sha(current)
        if current == replacement:
            return {"path": str(target), "sha256": digest, "changed": False}
        if expected_sha != digest:
            fail("VERSION_CONFLICT", f"Expected {expected_sha}; actual {digest}")
        fd, temp = tempfile.mkstemp(prefix=".driftlock-update-", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as dest:
                dest.write(replacement)
                dest.flush()
                os.fsync(dest.fileno())
            os.replace(temp, target)
            try:
                folder_fd = os.open(target.parent, os.O_RDONLY)
                try: os.fsync(folder_fd)
                finally: os.close(folder_fd)
            except OSError: pass
        finally:
            if os.path.exists(temp): os.unlink(temp)
        return {"path": str(target), "sha256": sha(replacement), "changed": True}
