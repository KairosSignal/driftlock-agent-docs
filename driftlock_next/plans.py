"""Explicit Plan lifecycle, trace graph, and authorized status changes."""
from __future__ import annotations
import json
import re
from pathlib import Path
from .atomic import change
from .common import fail, frontmatter, response, text_file, within
from .registry import select
from .locks import exclusive, pinned_directory
from .ownership import visible, require_owner

STATES = {"draft","under_review","approved","active_planning","implemented","parked","superseded","rejected"}
NEXT = {
 "draft": {"under_review","parked","rejected"},
 "under_review": {"draft","approved","parked","rejected"},
 "approved": {"active_planning","parked","superseded"},
 "active_planning": {"implemented","parked","superseded"},
 "parked": {"draft","under_review"},
 "implemented": {"superseded"},
 "rejected": set(),
 "superseded": set(),
}
IDENT = re.compile(r"^[A-Z][A-Z0-9_-]{2,79}$")

def unpack(value):
    if value is None or value == "":
        return []
    if not isinstance(value,str):
        fail("INVALID_PLAN_LINKS", "Plan links must be text or a JSON string array")
    if value in ("[]","null"):
        return []
    if value.startswith("["):
        try:
            parsed = json.loads(value)
        except ValueError:
            fail("INVALID_PLAN_LINKS", "Expected a JSON array of plan IDs")
        if not isinstance(parsed,list) or any(not isinstance(x,str) for x in parsed):
            fail("INVALID_PLAN_LINKS","Expected array of strings")
        return parsed
    return [v.strip() for v in value.split(",") if v.strip()]

def plan_entries(p):
    base = Path(p["_resolved_root"])
    folder = within(base, p.get("planning","planning"),allow_missing=True)
    if not folder.exists():
        return []
    return [(f,frontmatter(text_file(f))) for f in sorted(folder.rglob("*.md"))
            if f.is_file() and not f.is_symlink()
            and visible(frontmatter(text_file(f)),p,"plan",p.get("_registry_project_count"))]

def validate(root, project=None, proposed=None):
    p = select(root,project)
    entries = plan_entries(p)
    if proposed:
        entries=[(f, dict(proposed) if str(f)==proposed["_path"] else meta)
                 for f,meta in entries]
    named, legacy, problems = {}, [], []
    for f,meta in entries:
        ident = meta.get("plan_id")
        if not ident:
            legacy.append(f.relative_to(p["_resolved_root"]).as_posix())
            continue
        if not isinstance(ident,str) or not IDENT.fullmatch(ident):
            problems.append({"code":"INVALID_PLAN_ID","file":str(f),"id":ident})
            continue
        if ident in named:
            problems.append({"code":"DUPLICATE_PLAN_ID","id":ident,
                            "paths":[str(named[ident][0]),str(f)]})
            continue
        named[ident] = (f,meta)
    graph = {}
    for ident,(f,meta) in named.items():
        status = meta.get("status")
        if status not in STATES:
            problems.append({"code":"INVALID_PLAN_STATUS","id":ident,"status":status})
        deps = unpack(meta.get("depends_on"))
        previous = unpack(meta.get("supersedes"))
        for link in deps + previous:
            if link not in named:
                problems.append({"code":"PLAN_LINK_NOT_FOUND","id":ident,"target":link})
            if link == ident:
                problems.append({"code":"PLAN_SELF_REFERENCE","id":ident})
        graph[ident] = [x for x in deps+previous if x in named]
        if status == "superseded" and not any(ident in unpack(other[1].get("supersedes")) for other in named.values()):
            problems.append({"code":"SUPERSEDED_WITHOUT_SUCCESSOR","id":ident})
    visiting, visited, cycles = set(), set(), []
    def visit(node, trail):
        if node in visiting:
            cycles.append(trail[trail.index(node):]+[node]);return
        if node in visited:return
        visiting.add(node)
        for dependency in graph.get(node,[]):
            visit(dependency,trail+[dependency])
        visiting.remove(node);visited.add(node)
    for ident in sorted(named):
        if ident not in visited:visit(ident,[ident])
    for c in cycles:
        problems.append({"code":"PLAN_CYCLE","path":c})
    return response("plan.validate", project_id=p["id"], formal_plans=len(named),
        legacy_unknown_status=len(legacy), legacy_samples=legacy[:8],
        issues=problems, state="blocked" if problems else "ok")

def _transition_locked(root, project, plan_id, status, expected_sha, evidence, approve):
    if status not in STATES:
        fail("PLAN_STATE",f"Unknown state: {status}")
    p=select(root,project)
    matches=[(f,meta) for f,meta in plan_entries(p) if meta.get("plan_id")==plan_id]
    if len(matches)!=1:
        fail("PLAN_ID_AMBIGUOUS",f"Expected one authoritative Plan {plan_id}; found {len(matches)}")
    path,meta=matches[0]
    require_owner(meta,p,"plan")
    # Company-wide read access is not cross-project write permission.
    from .ownership import owner
    if p["id"] in ("governance","company") and (
            owner(meta,"plan") not in ("governance","company") and
            (p.get("_registry_project_count",1)>1 or owner(meta,"plan") is not None)):
        fail("PROJECT_OWNER_MISMATCH","Use the owning project for PLAN transition")
    prior=meta.get("status")
    if prior not in STATES:
        fail("LEGACY_PLAN", "Legacy plan has no governed status; migrate explicitly")
    if status!=prior and status not in NEXT[prior]:
        fail("ILLEGAL_PLAN_TRANSITION",f"{prior} -> {status}")
    if status in ("approved","implemented","superseded") and (not evidence or len(evidence.strip())<8):
        fail("PLAN_EVIDENCE", "Decision or completion evidence reference required")
    content=text_file(path)
    if not content.startswith("---\n"):
        fail("PLAN_NO_FRONTMATTER","Cannot mutate legacy plan without YAML front matter")
    boundary=content.find("\n---",4)
    if boundary<0:fail("PLAN_BAD_FRONTMATTER","Unclosed metadata")
    head=content[4:boundary]
    status_re=re.compile(r"(?m)^status:[ \t]*.*$")
    hits=status_re.findall(head)
    if len(hits)!=1:fail("PLAN_STATUS_FIELD","Exactly one top-level status field required")
    updated_head=status_re.sub("status: "+status,head,count=1)
    if evidence:
        if "\n" in evidence or "\r" in evidence or len(evidence)>512:
            fail("PLAN_EVIDENCE","Use a short single-line evidence reference")
        evidence_line="last_decision_evidence: "+json.dumps(evidence,ensure_ascii=False)
        metadata_pattern=re.compile(r"(?m)^last_decision_evidence:[ \\t]*.*$")
        if len(metadata_pattern.findall(updated_head))>1:
            fail("PLAN_EVIDENCE_FIELD","Duplicate evidence fields")
        if metadata_pattern.search(updated_head):
            updated_head=metadata_pattern.sub(lambda _: evidence_line,updated_head)
        else:
            updated_head+="\n"+evidence_line
    replacement=content[:4]+updated_head+content[boundary:]
    proposed_meta=frontmatter(replacement)
    proposed_meta["_path"]=str(path)
    baseline=validate(root,project)
    preview=validate(root,project,proposed_meta)
    # Never write a PLAN into a known inconsistent graph, including a
    # "no-op" status change or an existing unresolved illegal successor.
    if baseline["issues"]:
        fail("PLAN_GRAPH_UNHEALTHY", f"Current Plan graph needs reconciliation: {baseline['issues']}")
    if preview["issues"]:
        fail("PLAN_GRAPH_INVALID_AFTER_TRANSITION", f"Proposed update violates Plan graph: {preview['issues']}")
    relative=path.relative_to(p["_resolved_root"]).as_posix()
    result=change(p["_resolved_root"],relative,expected_sha,replacement,approve=approve)
    return response("plan.transition",project_id=p["id"],plan_id=plan_id,
        previous=prior,status=status,**result,task_created=False,execution_context_changed=False)


def transition(root, project, plan_id, status, expected_sha, evidence, approve):
    """Serialize validation and modification against all cooperative PLAN writers."""
    if not approve:
        fail("APPROVAL_REQUIRED","PLAN changes must be explicitly authorized")
    p=select(root,project)
    folder=within(Path(p["_resolved_root"]),p.get("planning","planning"),allow_missing=False)
    if not folder.is_dir() or folder.is_symlink():
        fail("PLAN_ROOT_UNSAFE","Planning root must be a real directory")
    guard=folder/".driftlock-plan-graph.lock"
    with pinned_directory(folder,Path(p["_resolved_root"])) as dir_fd:
        with exclusive(guard,dir_fd=dir_fd):
            return _transition_locked(root,project,plan_id,status,expected_sha,evidence,approve)
