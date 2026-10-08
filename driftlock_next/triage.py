"""Prepare grounded, read-only evidence for the current AI; no model calls."""
from __future__ import annotations
from pathlib import Path
from .common import fail, response
from .registry import select
from .audit import context_check, plan_list
from .intake import propose
from .problems import scan

KINDS = {"question","observation","problem","idea","research","plan","execution","switch"}

def triage(root, project=None, text=None, kind=None):
    """Never classify user language as fact. Expose references for the operator."""
    p=select(root,project)
    if not text or not text.strip() or len(text)>4000:
        fail("INTAKE_TEXT","Expected non-empty input up to 4000 characters")
    if kind is not None and kind not in KINDS:
        fail("INTAKE_KIND","Unsupported suggested kind")
    interpretation=propose(root,p["id"],text,kind)
    try:
        ctx=context_check(root,p["id"])
    except Exception as exc:
        from .common import GovernanceError
        if not isinstance(exc,GovernanceError):raise
        ctx={"state":"unavailable","code":exc.code}
    candidates=[]
    problem_authority=None
    try:
        matches=scan(root,p["id"],candidate=text)
        candidates=matches["candidates"][:8]
        problem_authority=str((Path(p["_resolved_root"]) /
                               p.get("intake",{}).get("problem","current/PROBLEM_REGISTER.md")).resolve())
    except Exception as exc:
        from .common import GovernanceError
        if not isinstance(exc,GovernanceError):raise
        problem_authority={"unavailable":exc.code}
    plan=plan_list(root,p["id"])
    plans=plan.get("plans",[])
    formal=[entry for entry in plans if entry.get("plan_id")]
    legacy=[entry for entry in plans if not entry.get("plan_id")]
    return response(
        "intake.triage",project_id=p["id"],user_text=text.strip(),
        suggested_kind=interpretation["category"],semantic_decision="ai_or_user_must_validate",
        current_execution={"task_id":ctx.get("task_id"),"task_path":ctx.get("task_path"),
                           "state":ctx.get("state"),"git_check":ctx.get("git",{}).get("state")},
        possible_related_problems=candidates,
        problem_register=problem_authority,
        plan_inventory={"count":plan.get("count",0),
                        "examples":(formal[:8]+legacy[:4]),
                        "warning":"Formal plans retain their recorded state; titles are navigation hints, not semantic duplicates"},
        allowed_without_user_confirmation=["answer","inspect","propose_categorization"],
        prohibited_without_explicit_authorization=[
            "switch_task","create_task","merge_duplicates","close_problem",
            "approve_plan","merge_git","push_git","deploy"],
        execution_context_changed=False,persisted=False,task_created=False,
        next_action="Use only grounded source records. If user's intent to persist or act is ambiguous, clarify.")
