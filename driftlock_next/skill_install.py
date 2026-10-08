"""Read-only source-versus-installation guard."""
from __future__ import annotations
from pathlib import Path
import re
from .common import fail, git, response, sha, text_file

def status(source, installed):
    source=Path(source).resolve()
    installed=Path(installed).resolve()
    targets=("SKILL.md","scripts/driftlock.py")
    files=[]
    for name in targets:
        a=source/name
        b=installed/name
        if not a.is_file() or a.is_symlink():
            fail("SKILL_SOURCE_MISSING","Missing valid source "+name)
        expected=sha(text_file(a))
        actual=sha(text_file(b)) if b.is_file() and not b.is_symlink() else None
        files.append({"name":name,"source_sha256":expected,"installed_sha256":actual,
                      "matches":actual==expected})
    old=git(installed,"rev-parse","--short","HEAD",check=False) if (installed/".git").exists() else None
    new=git(source,"rev-parse","--short","HEAD",check=False) if (source/".git").exists() else None
    return response("skill.status",source=str(source),installed=str(installed),
        files=files,installed_matches_source=all(x["matches"] for x in files),
        source_commit=new.stdout.strip() if new and new.returncode==0 else None,
        installed_commit=old.stdout.strip() if old and old.returncode==0 else None,
        installation_changed=False,
        note="Source and installed copies remain separate; this command never installs or pushes")
