"""Optional LOCAL serialized task-ID reservations; never creates a TASK."""
from __future__ import annotations
import fcntl
import json
import os
import re
import tempfile
from pathlib import Path
from .common import fail, sha, text_file, response, git
from .registry import select
from .audit import tasks_for
from .common import frontmatter

def reservation_file(root):
    """Worktrees in the same repository share one allocation ledger."""
    base=Path(root).resolve()
    result=git(base,"rev-parse","--git-common-dir",check=False)
    if result.returncode:
        fail("ALLOCATOR_NOT_GIT","A Company Control Git checkout is required")
    common=Path(result.stdout.strip())
    if not common.is_absolute():
        common=(base/common).resolve()
    else:
        common=common.resolve()
    if not common.is_dir():
        fail("ALLOCATOR_GIT_DIR","Cannot locate shared Git metadata")
    return common/"driftlock-governance"/"task-id-reservations.json"

def inspect(root):
    path=reservation_file(root)
    if path.is_symlink():
        fail("UNSAFE_ALLOCATOR","Symlinked allocation ledger")
    body=text_file(path) if path.exists() else ""
    if body:
        try:
            state=json.loads(body)
        except ValueError:
            fail("ALLOCATOR_CORRUPTED","Invalid JSON in allocation ledger")
        if not isinstance(state,dict) or not isinstance(state.get("reservations"),list):
            fail("ALLOCATOR_CORRUPTED","Malformed allocation ledger")
    else:
        state={"schema_version":1,"reservations":[]}
    return response("task.reservations",path=str(path),sha256=sha(body),
                    count=len(state["reservations"]),reservations=state["reservations"][-25:],
                    scope="shared_git_worktrees_on_this_host",
                    warning="This ledger is local Git metadata; back it up independently. Separate clones cannot coordinate offline.")


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
    path=reservation_file(root)
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
            caveat="Shared across worktrees of this local repository only; separate clones need central reconciliation. Back up the Git metadata ledger.")
