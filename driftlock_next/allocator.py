"""Optional LOCAL serialized task-ID reservations; never creates a TASK."""
from __future__ import annotations
import json
import os
import re
import tempfile
from pathlib import Path
from .common import fail, sha, text_file, response, git, frontmatter
from .locks import exclusive, checked_private_directory
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


def existing_task_ids_across_worktrees(root, prefix):
    """Scan all registered local worktrees under the shared repository."""
    info=git(root,"worktree","list","--porcelain")
    trees=[]
    for line in info.stdout.splitlines():
        if line.startswith("worktree "):
            trees.append(Path(line[9:]))
    if not trees:
        fail("ALLOCATOR_WORKTREES_MISSING","No registered worktrees")
    all_ids=set()
    for tree in trees:
        if not tree.is_dir():
            fail("ALLOCATOR_WORKTREE_MISSING", f"Cannot inspect {tree}")
        # The source of truth is every checkout's actual tasks folder,
        # not merely the branch currently doing the allocation.
        folder=tree/"tasks"
        if not folder.exists():continue
        if folder.is_symlink() or not folder.is_dir():
            fail("ALLOCATOR_TASK_FOLDER_UNSAFE", f"Unsafe task folder {folder}")
        for doc in folder.glob("*.md"):
            if doc.is_symlink() or not doc.is_file():
                fail("ALLOCATOR_TASK_FILE_UNSAFE",f"Unexpected task file {doc}")
            meta=frontmatter(text_file(doc))
            ident=meta.get("task_id")
            if ident is not None:
                if not isinstance(ident,str):
                    fail("ALLOCATOR_TASK_ID_INVALID","Non-string task ID")
                if ident.startswith(prefix+"-TASK-"):
                    all_ids.add(ident)
    return all_ids

def existing_task_ids_in_local_branches(root, prefix):
    """Include TASKs committed to branches not currently checked out."""
    refs=git(root,"for-each-ref","--format=%(refname)","refs/heads").stdout.splitlines()
    results=set()
    # Bound each argv batch; grep all refs without network calls.
    for start in range(0,len(refs),24):
        batch=refs[start:start+24]
        if not batch:continue
        found=git(root,"grep","-h","-E","^task_id:[[:space:]]+",
                  *batch,"--","tasks/*.md",check=False)
        if found.returncode not in (0,1):
            fail("ALLOCATOR_REF_SCAN_FAILED","Cannot safely inspect local task branches")
        if found.returncode==0:
            for line in found.stdout.splitlines():
                match=re.match(r"^task_id:\s*([A-Za-z0-9-]+)",line)
                if match and match.group(1).startswith(prefix+"-TASK-"):
                    results.add(match.group(1))
    return results


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
    checked_private_directory(path.parent, path.parent.parent)
    lock=path.parent/".task-id-reservations.lock"
    if lock.is_symlink():fail("UNSAFE_LOCK","Symlinked allocator lock")
    with exclusive(lock):
        original=text_file(path) if path.exists() else ""
        if sha(original)!=expected_sha:
            fail("VERSION_CONFLICT","Allocator snapshot changed, retry with current SHA")
        state=json.loads(original) if original else {"schema_version":1,"reservations":[]}
        if state.get("schema_version")!=1 or not isinstance(state.get("reservations"),list):
            fail("ALLOCATOR_CORRUPTED","Invalid reservation state")
        existing={r.get("task_id") for r in state["reservations"] if isinstance(r,dict)}
        # Must include formal TASKs existing in *any* checked-out worktree.
        existing.update(existing_task_ids_across_worktrees(root,prefix))
        existing.update(existing_task_ids_in_local_branches(root,prefix))
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
