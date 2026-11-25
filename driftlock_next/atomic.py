"""Optimistic filesystem-safe writes for already-authorized source documents."""
from __future__ import annotations
import os
import tempfile
from pathlib import Path
from .common import fail, sha, text_file, within
from .locks import exclusive, pinned_directory, anchored_read_text, anchored_replace_text

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
    guard = target.parent / ("." + target.name + ".driftlock-write.lock")
    if guard.is_symlink():
        fail("UNSAFE_LOCK", "Refuse symlink lock file")
    with pinned_directory(target.parent,root) as dir_fd:
        with exclusive(guard,dir_fd=dir_fd):
            current=(anchored_read_text(dir_fd,target.name) if dir_fd is not None
                     else text_file(target) if target.exists() else "")
            digest=sha(current)
            if current==replacement:
                return {"path":str(target),"sha256":digest,"changed":False}
            if expected_sha!=digest:
                fail("VERSION_CONFLICT",f"Expected {expected_sha}; actual {digest}")
            if dir_fd is not None:
                anchored_replace_text(dir_fd,target.name,replacement)
            else:
                # Non-POSIX compatibility branch; Windows requires separate
                # platform-security verification before multiuser release.
                fd,temp=tempfile.mkstemp(prefix=".driftlock-update-",dir=target.parent)
                try:
                    with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as out:
                        out.write(replacement);out.flush();os.fsync(out.fileno())
                    os.replace(temp,target)
                finally:
                    if os.path.exists(temp):os.unlink(temp)
            return {"path":str(target),"sha256":sha(replacement),"changed":True}
