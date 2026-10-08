"""Shared safe readers. No network, credentials or background work."""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
from pathlib import Path

class GovernanceError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

def fail(code, message):
    raise GovernanceError(code, message)

def within(base, rel, *, allow_missing=False):
    base = Path(base).resolve()
    if not isinstance(rel, str) or not rel or "\x00" in rel:
        fail("INVALID_PATH", "A non-empty relative path is required")
    raw = Path(rel)
    if raw.is_absolute() or "\\" in rel or ".." in raw.parts:
        fail("INVALID_PATH", "Path must be relative and cannot escape its root")
    candidate = base / raw
    if any(part.is_symlink() for part in [candidate, *candidate.parents] if part.is_relative_to(base)):
        fail("SYMLINK_NOT_ALLOWED", "Symlink inside governed path")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base):
        fail("PATH_OUTSIDE_ROOT", f"Path escapes root: {rel}")
    if not allow_missing and not resolved.exists():
        fail("MISSING_PATH", f"Missing path: {rel}")
    return resolved

def text_file(path, limit=4_194_304):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        fail("UNSAFE_FILE", f"Not a regular file: {path}")
    if path.stat().st_size > limit:
        fail("FILE_TOO_LARGE", f"File too large: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail("FILE_READ_ERROR", str(exc))

def read_json(path):
    try:
        data = json.loads(text_file(path, limit=1_048_576))
    except ValueError as exc:
        fail("INVALID_JSON", str(exc))
    if not isinstance(data, dict):
        fail("INVALID_CONFIG", "Expected JSON object")
    return data

def git(repo, *args, check=True):
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True,
            text=True, timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail("GIT_UNAVAILABLE", str(exc))
    if check and result.returncode:
        fail("GIT_ERROR", (result.stderr or result.stdout).strip()[:800])
    return result

def sha(content):
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()

def frontmatter(body):
    """Extract conservative top-level YAML scalars without executing YAML tags."""
    if not body.startswith("---\n"):
        # Older company tasks legitimately have no front matter.
        content = body[:9000]
    else:
        end = body.find("\n---", 4)
        if end < 0:
            fail("INVALID_FRONTMATTER", "Unclosed front matter")
        content = body[4:end]
    data = {}
    for line in content.splitlines():
        match = re.match(r"^([a-zA-Z_][a-zA-Z_0-9-]*):[ \t]*(.*)$", line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip().strip('"').strip("'")
        if value in ("null", "~"):
            data[key] = None
        elif value in ("true", "false"):
            data[key] = value == "true"
        else:
            data[key] = value
    return data

def response(command, **kwargs):
    return {"schema_version": 1, "command": command, **kwargs}
