"""Read-only comparison of a complete, installable Skill runtime manifest."""
from __future__ import annotations
from pathlib import Path
from .common import fail, git, response, sha

def _manifest(root):
    root=Path(root)
    collected=[]
    mandatory=("SKILL.md","scripts/driftlock.py")
    for rel in mandatory:
        if not (root/rel).is_file():
            fail("SKILL_SOURCE_MISSING",f"Missing {rel}")
        collected.append(rel)
    for folder, glob in (("driftlock_next","*.py"),("references","*.md"),
                          ("agents","*.yaml")):
        directory=root/folder
        if directory.is_dir():
            for f in sorted(directory.rglob(glob)):
                if f.is_file():
                    collected.append(str(f.relative_to(root)))
    return sorted(set(collected))

def status(source, installed):
    source=Path(source).resolve()
    installed=Path(installed).resolve()
    required=_manifest(source)
    files=[]
    for name in required:
        a=source/name
        b=installed/name
        if a.is_symlink():
            fail("SKILL_SOURCE_UNSAFE",f"Symlink in source: {name}")
        digest=sha(a.read_bytes())
        actual=sha(b.read_bytes()) if b.is_file() and not b.is_symlink() else None
        files.append({"name":name,"source_sha256":digest,"installed_sha256":actual,
                      "matches":actual==digest})
    extra=sorted(set(_manifest(installed))-set(required)) if (
        (installed/"SKILL.md").is_file() and (installed/"scripts/driftlock.py").is_file()) else []
    src_commit=git(source,"rev-parse","--short","HEAD",check=False)
    dst_commit=git(installed,"rev-parse","--short","HEAD",check=False)
    return response("skill.status",source=str(source),installed=str(installed),
        files=files,required_count=len(required),
        missing=[x["name"] for x in files if x["installed_sha256"] is None],
        mismatched=[x["name"] for x in files if x["installed_sha256"] is not None and not x["matches"]],
        unexpected=extra,
        installed_matches_source=all(x["matches"] for x in files) and not extra,
        source_commit=src_commit.stdout.strip() if src_commit.returncode==0 else None,
        installed_commit=dst_commit.stdout.strip() if dst_commit.returncode==0 else None,
        installation_changed=False,
        note="Full runtime/modules/contracts manifest; no installation, pushing or cleanup.")
