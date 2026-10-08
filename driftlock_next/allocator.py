"""Optional LOCAL serialized task-ID reservations; never creates a TASK."""
from __future__ import annotations
import fcntl
import json
import os
import re
import tempfile
from pathlib import Path
from .common import fail, sha, text_file, response
from .registry import select
from .audit import tasks_for
from .common import frontmatter

def reserve(root, project_id, expected_sha, approve=False):
    p=select(root,project_id)
    config=p.get("task_allocator")
    if config!="local_serialized":
        fail("ALLOCATOR_NOT_CONFIGURED","Allocator must be explicitly enabled by Company Control")
    prefix=p.get("task_prefix")
    if not prefix:
        fail("TASK_PREFIX_MISSING","Project has no reserved prefix")
    if not approve:
        fail("APPROVAL_REQUIRED","Reservation needs explicit approval")
    base=Path(root).resolve()
    path=base/".driftlock"/"task-id-reservations.json"
    if path.exists() and path.is_symlink():
        fail("UNSAFE_ALLOCATOR", "Symlinked allocator state")
    path.parent.mkdir(parents=True,exist_ok=True)
    lock=path.parent/".task-id-reservations.lock"
    if lock.is_symlink():fail("UNSAFE_LOCK","Symlinked allocator lock")
    with lock.open("a+b") as fd:
        fcntl.flock(fd,fcntl.LOCK_EX)
        original=text_file(path) if path.exists() else ""
        if sha(original)!=expected_sha:
            fail("VERSION_CONFLICT","Allocator snapshot changed, retry with current SHA")
        state=json.loads(original) if original else {"schema_version":1,"reservations":[]}
        if state.get("schema_version")!=1 or not isinstance(state.get("reservations"),list):
            fail("ALLOCATOR_CORRUPTED","Invalid reservation state")
        existing={r.get("task_id") for r in state["reservations"] if isinstance(r,dict)}
        for task in tasks_for(p):
            m=frontmatter(text_file(task))
            if m.get("task_id"):existing.add(m["task_id"])
        pat=re.compile(r"^"+re.escape(prefix)+r"-TASK-(\d+)$")
        nums=[int(m.group(1)) for x in existing if isinstance(x,str) if (m:=pat.fullmatch(x))]
        next_number=max(nums,default=0)+1
        task_id=f"{prefix}-TASK-{next_number:05d}"
        state["reservations"].append({"task_id":task_id,"project_id":p["id"],"status":"reserved_not_authorized"})
        content=json.dumps(state,ensure_ascii=False,indent=2)+"\n"
        name=None
        try:
            fp, name=tempfile.mkstemp(prefix=".driftlock-reservations-",dir=path.parent)
            with os.fdopen(fp,"w",encoding="utf-8") as out:
                out.write(content);out.flush();os.fsync(out.fileno())
            os.replace(name,path)
        finally:
            if name and os.path.exists(name):os.unlink(name)
        return response("task.reserve",project_id=p["id"],task_id=task_id,
            record_path=str(path),sha256=sha(content),state="reserved_not_authorized",
            task_created=False,execution_authorized=False,
            caveat="Only serialized for one shared filesystem; never merge offline allocations without reconciliation")
