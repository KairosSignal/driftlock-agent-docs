"""Advisory lock without importing platform-specific modules during CLI startup."""
from contextlib import contextmanager
from pathlib import Path
import os

@contextmanager
def exclusive(path, *, dir_fd=None):
    path=Path(path)
    flags=os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW",0)
    fd=_verified_file(dir_fd,path.name,flags) if dir_fd is not None else os.open(path,flags,0o600)
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
            if dir_fd is not None:
                import stat
                from .common import fail
                now=os.stat(path.name, dir_fd=dir_fd, follow_symlinks=False)
                own=os.fstat(fd)
                if (now.st_dev,now.st_ino)!=(own.st_dev,own.st_ino) or not stat.S_ISREG(now.st_mode):
                    fail("LOCK_INODE_CHANGED","Lock path was replaced before ownership established")
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

@contextmanager
def pinned_directory(directory, anchor):
    """Anchor POSIX mutations to a non-following directory fd, not path strings."""
    directory=Path(directory)
    anchor=Path(anchor).resolve()
    if not directory.is_relative_to(anchor):
        from .common import fail
        fail("UNSAFE_MUTATION_ROOT","Mutation destination outside pinned anchor")
    if os.name == "nt":
        # Windows has no Python openat(dir_fd) support; use native NTFS ACLs
        # and exclusive locking. This is not a claim of POSIX-level pinning.
        yield None
        return
    from .common import fail
    flags=os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fds=[]
    try:
        first=os.open(anchor,flags)
        fds.append(first)
        for part in directory.relative_to(anchor).parts:
            descriptor=os.open(part,flags,dir_fd=fds[-1])
            fds.append(descriptor)
        yield fds[-1]
    except (OSError,ValueError) as exc:
        fail("UNSAFE_MUTATION_ROOT",f"Cannot pin directory: {exc}")
    finally:
        for fd in reversed(fds):
            os.close(fd)

def _verified_file(fd,name,flags):
    import stat
    from .common import fail
    opts=flags|getattr(os,"O_NOFOLLOW",0)
    descriptor=os.open(name,opts,0o600,dir_fd=fd)
    try:
        meta=os.fstat(descriptor)
        current=os.stat(name,dir_fd=fd,follow_symlinks=False)
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink!=1 or (
           meta.st_ino,meta.st_dev)!=(current.st_ino,current.st_dev):
            fail("UNSAFE_FILE_INODE","Unexpected lock/content file identity")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise

def anchored_read_text(fd,name,limit=4194304):
    from .common import fail
    try:
        desc=_verified_file(fd,name,os.O_RDONLY)
    except FileNotFoundError:
        return ""
    try:
        data=bytearray()
        while len(data)<=limit:
            part=os.read(desc,min(65536,limit+1-len(data)))
            if not part:break
            data.extend(part)
        if len(data)>limit:fail("FILE_TOO_LARGE","Governed file exceeds allowed size")
        return bytes(data).decode("utf-8")
    finally:
        os.close(desc)

def anchored_replace_text(fd,name,text):
    from .common import fail
    import secrets
    scratch=".driftlock-atomic-"+secrets.token_hex(12)
    desc=_verified_file(fd,scratch,os.O_WRONLY|os.O_CREAT|os.O_EXCL)
    try:
        payload=text.encode("utf-8")
        with os.fdopen(desc,"wb") as out:
            out.write(payload);out.flush();os.fsync(out.fileno())
        desc=-1
        os.replace(scratch,name,src_dir_fd=fd,dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        if desc>=0:os.close(desc)
        try:os.unlink(scratch,dir_fd=fd)
        except FileNotFoundError:pass
