"""Read-only multi-project governance inspections, no implicit repair."""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path
from .common import fail, frontmatter, git, git_safe_env, response, text_file, within
from .registry import select, project_list
from .ownership import visible, require_owner, owner

VALID_POLICIES = ("local_only", "remote_tracked", "remote_publish_required")
TASK_ID = re.compile(r"^(?:(?:IC|AMZ|INT|BI|KB|GOV)-)?TASK-[0-9]+[A-Z0-9]*(?:-[A-Z0-9]+)*$")
NAMED_TASK = re.compile(r"^((?:(?:IC|AMZ|INT|BI|KB|GOV)-)?TASK-\d+(?:-[A-Z])?(?:-R\d+)?)")

def task_lifecycle_blockers(meta):
    """Hard gates for versioned TASKs; never infer acceptance from Git alone."""
    if meta.get("task_contract_version") not in ("2",2):
        return []
    status=meta.get("status")
    review=meta.get("review_status")
    candidate=meta.get("candidate_state")
    sha=meta.get("candidate_commit")
    merge=meta.get("merge_allowed") is True
    deploy=meta.get("deploy_allowed") is True
    early={"planned","in_progress","ready_for_review","rework_required"}
    accepted={"accepted","accepted_pending_integration","integrated",
              "integrated_pending_deploy","deployed","deployed_pending_close","closed"}
    problems=[]
    if status in early and (merge or deploy):
        problems.append("pre_acceptance_release_permission")
    if status in accepted and review!="pass":
        problems.append("accepted_without_review_pass")
    if status=="ready_for_review" and review in ("pass","fail"):
        problems.append("ready_review_verdict_conflict")
    if status in early and candidate in ("superseded","rejected"):
        problems.append("active_task_has_invalid_candidate")
    if status in accepted and candidate in ("superseded","rejected","none"):
        problems.append("accepted_candidate_invalid")
    if status in accepted and (not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{40}",sha)):
        problems.append("accepted_candidate_commit_missing")
    if deploy and meta.get("release_gates_open") not in (None,"none","null","[]",""):
        problems.append("deploy_permission_while_gates_open")
    ident=meta.get("task_id")
    if isinstance(ident,str):
        m=re.fullmatch(r"(.+)-R([1-9][0-9]*)",ident)
        if m:
            index=int(m.group(2))
            predecessor=m.group(1) if index==1 else f"{m.group(1)}-R{index-1}"
            if meta.get("rework_of")!=predecessor:
                problems.append("rework_predecessor_mismatch")
    return sorted(set(problems))

def git_snapshot(repo, policy="local_only", expected_branch=None, candidate=None,
                 head_policy="exact"):
    repo = Path(repo)
    if not (repo / ".git").exists():
        return {"state": "unavailable", "reason": "no local Git checkout", "blocking": []}
    actual = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    status = git(repo, "status", "--porcelain=v1", "--untracked-files=normal").stdout
    upstream = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}", check=False)
    upstream_name = upstream.stdout.strip() if upstream.returncode == 0 else None
    problems, infos = [], []
    if actual == "HEAD":
        problems.append("detached_head")
    if expected_branch and expected_branch != actual:
        problems.append("unexpected_branch")
    if status:
        problems.append("dirty_worktree")
    if head_policy not in ("exact","contains_candidate"):
        problems.append("candidate_head_policy_invalid")
    if candidate not in (None, "", "not_set", "none", "null"):
        if not isinstance(candidate, str) or not re.fullmatch(r"[0-9a-fA-F]{40}",candidate):
            return {"state":"blocked","blocking":["invalid_candidate_commit_type_or_sha"],
                    "remote_policy":policy,"head":head,"branch":actual}
        ref = git(repo, "rev-parse", "--verify", candidate, check=False)
        if ref.returncode or git(repo, "cat-file", "-e", candidate + "^{commit}", check=False).returncode:
            problems.append("candidate_missing")
        elif head_policy == "exact" and ref.stdout.strip() != head:
            problems.append("candidate_head_mismatch")
        elif head_policy == "contains_candidate" and git(repo, "merge-base", "--is-ancestor", candidate, head, check=False).returncode:
            problems.append("candidate_not_ancestor")
    ahead = behind = None
    if not upstream_name:
        if policy == "local_only":
            infos.append("upstream_not_required_local_only")
        else:
            problems.append("upstream_missing")
    else:
        counts = git(repo, "rev-list", "--left-right", "--count", upstream_name + "...HEAD", check=False)
        if counts.returncode == 0:
            try:
                behind, ahead = map(int, counts.stdout.strip().split())
            except (ValueError, TypeError):
                problems.append("upstream_comparison_failed")
            else:
                if behind:
                    if policy == "local_only":
                        infos.append("local_only_branch_behind_upstream")
                    else:
                        problems.append("upstream_behind")
                if ahead:
                    if policy == "remote_publish_required":
                        problems.append("unpublished_commits")
                    elif policy == "remote_tracked":
                        problems.append("upstream_not_synchronized")
                    else:
                        infos.append("local_commits_not_pushed")
        else:
            problems.append("upstream_comparison_failed")
    if policy == "remote_publish_required" and not upstream_name:
        problems.append("publication_unverified")
    return {"state": "blocked" if problems else "ok", "branch": actual, "head": head,
            "clean": not bool(status), "upstream": upstream_name, "ahead": ahead,
            "behind": behind, "remote_policy": policy, "blocking": sorted(set(problems)),
            "information": infos}

def tasks_for(project):
    root = Path(project["_resolved_root"])
    folder = within(root, project.get("tasks", "tasks"), allow_missing=True)
    if not folder.exists():
        return []
    if not folder.is_dir():
        fail("TASK_ROOT", "Task directory must be a directory")
    return sorted(
        f for f in folder.glob("*.md") if f.is_file() and not f.is_symlink()
        and visible(frontmatter(text_file(f)),project,"task",project.get("_registry_project_count"))
    )

def task_check(root, project_id=None, task_id=None):
    p = select(root, project_id)
    files = tasks_for(p)
    by_id, incomplete, bad_states, rework_refs = {}, [], [], []
    review_warnings, rework_chain_issues = [], []
    records = []
    for file in files:
        meta = frontmatter(text_file(file))
        ident = meta.get("task_id")
        if "task_id" in meta and not isinstance(ident,str):
            if meta.get("task_contract_version") in ("2",2):
                bad_states.append({"task_id":str(ident),"code":"INVALID_NEW_TASK_ID_TYPE"})
            else:
                review_warnings.append({"file":file.name,"code":"LEGACY_TASK_ID_TYPE"})
        if not ident:
            # Legacy filenames are not authoritative IDs.
            incomplete.append(file.name)
            ident = None
        if ident:
            if not isinstance(ident,str):
                fail("INVALID_TASK_ID_TYPE", f"{file.name}: task_id must be text")
            if not TASK_ID.fullmatch(ident):
                if meta.get("task_contract_version") in ("2",2):
                    bad_states.append({"task_id":ident,"code":"INVALID_NEW_TASK_ID"})
                else:
                    review_warnings.append({"task_id":ident,"code":"LEGACY_ID_FORMAT",
                                            "file":file.name})
            by_id.setdefault(ident, []).append(file.name)
            state=meta.get("status")
            review=meta.get("review_status")
            for code in task_lifecycle_blockers(meta):
                bad_states.append({"task_id":ident,"code":code})
            if state in ("accepted","accepted_pending_integration","integrated","integrated_pending_deploy",
                         "deployed","deployed_pending_close","closed"):
                if review=="fail":
                    bad_states.append({"task_id":ident,"status":state,"review":review})
                elif review=="not_started":
                    finding={"task_id":ident,"code":"REVIEW_METADATA_NOT_STARTED_IN_ACCEPTED_STATE",
                             "status":state,"needs_reconciliation":True}
                    if meta.get("task_contract_version")=="2":
                        bad_states.append(finding)
                    else:
                        review_warnings.append(finding)
            if meta.get("task_contract_version") in ("2",2):
                if state in ("closed","accepted","accepted_pending_integration","integrated") and review != "pass":
                    bad_states.append({"task_id":ident,"code":"REVIEW_NOT_ACCEPTED","status":state,"review":review})
                if state in ("ready_for_review", "rework_required") and (
                    meta.get("merge_allowed") is True or meta.get("deploy_allowed") is True):
                    bad_states.append({"task_id":ident,"code":"UNAUTHORIZED_RELEASE_PERMISSION"})
                if state=="closed" and meta.get("candidate_state") in ("superseded","rejected","none"):
                    bad_states.append({"task_id":ident,"code":"CLOSED_INVALID_CANDIDATE"})
            if state=="rework_required" and review=="pass":
                bad_states.append({"task_id":ident,"status":state,"review":review})
            if state=="ready_for_review" and review=="pass":
                review_warnings.append({"task_id":ident,"code":"READY_BUT_REVIEW_ALREADY_PASSED"})
            rework_match = re.fullmatch(r"(.+)-R([1-9][0-9]*)", ident)
            if rework_match and not meta.get("rework_of"):
                rework_chain_issues.append({"task_id":ident,"code":"MISSING_REWORK_PREDECESSOR"})
            matching = rework_match
            if matching and int(matching.group(2)) > 1 and meta.get("rework_of"):
                needed=f"{matching.group(1)}-R{int(matching.group(2))-1}"
                if meta["rework_of"]!=needed:
                    finding={"task_id":ident,"code":"REWORK_PREDECESSOR_MISMATCH",
                             "expected":needed,"actual":meta["rework_of"]}
                    rework_chain_issues.append(finding)
                    if meta.get("task_contract_version") in ("2",2):
                        bad_states.append(finding)
            if meta.get("rework_of"):
                rework_refs.append((ident, meta["rework_of"]))
        records.append((ident, file, meta))
    duplicates = {key: value for key, value in by_id.items() if len(value) > 1}
    broken_rework = [{"task": ident, "missing_predecessor": parent}
                     for ident, parent in rework_refs if parent not in by_id]
    filtered = [
        {"task_id": ident, "path": str(file.relative_to(Path(p["_resolved_root"]))),
         "status": meta.get("status", "unknown"), "review_status": meta.get("review_status", "unknown"),
         "project_id": meta.get("current_project", p["id"]), "parent": meta.get("parent"),
         "rework_of": meta.get("rework_of"), "candidate_commit": meta.get("candidate_commit")}
        for ident, file, meta in records if task_id is None or ident == task_id
    ]
    if task_id and not filtered:
        fail("TASK_NOT_FOUND", f"No such task: {task_id}")
    return response("task.check", project_id=p["id"], scanned_files=len(files), visible=filtered if task_id else filtered[-15:],
        explicit_task_ids=len(records) - len(incomplete), duplicate_ids=duplicates,
        legacy_missing_task_id={"count": len(incomplete), "samples": incomplete[:8]},
        broken_rework=broken_rework, contradictory_statuses=bad_states,
        review_warnings=review_warnings,rework_chain_issues=rework_chain_issues,
        blocking=bool(duplicates or broken_rework or bad_states or
                      any(t["code"]=="MISSING_REWORK_PREDECESSOR" and
                          any(m.get("task_contract_version") in ("2",2) for x,f,m in records if x==t["task_id"])
                          for t in rework_chain_issues)))

def current_rework_issues(project, meta):
    """Check the full predecessor identity, existence and ownership of live TASK."""
    ident=meta.get("task_id")
    if not isinstance(ident,str):
        return []
    match=re.fullmatch(r"(.+)-R([1-9][0-9]*)",ident)
    if not match:
        return []
    index=int(match.group(2))
    required=match.group(1) if index==1 else f"{match.group(1)}-R{index-1}"
    if meta.get("rework_of")!=required:
        return ["rework_predecessor_mismatch"]
    from .ownership import owner
    own=owner(meta,"task")
    parents=[]
    for file in tasks_for(project):
        other=frontmatter(text_file(file))
        if other.get("task_id")==required:
            parents.append(other)
    if not parents:
        return ["rework_predecessor_missing"]
    if len(parents)!=1:
        return ["rework_predecessor_ambiguous"]
    parent_owner=owner(parents[0],"task")
    if own and parent_owner and own!=parent_owner:
        return ["rework_predecessor_owner_mismatch"]
    if (meta.get("task_contract_version") in ("2",2) and
        (own is None or parent_owner is None)):
        return ["rework_predecessor_owner_unverified"]
    return []


def context_check(root, project_id=None):
    p = select(root, project_id)
    pr = Path(p["_resolved_root"])
    direct_task = p.get("active_task")
    card = within(pr, p.get("handoff", "CURRENT_HANDOFF.md"), allow_missing=True)
    # Other projects must never inherit governance's global CURRENT_HANDOFF.
    if not direct_task and p["id"] not in ("governance","company") and p.get("_registry_project_count",1)>1:
        return response("context.check",project_id=p["id"],state="unconfigured",
                        reason="no_project_specific_task_pointer",execution_context_changed=False)
    if not card.exists() and not direct_task:
        return response("context.check", project_id=p["id"], state="unconfigured", reason="handoff_missing",
                        execution_context_changed=False)
    meta = frontmatter(text_file(card)) if card.exists() else {}
    task_path = direct_task or meta.get("task_path")
    if not task_path:
        return response("context.check", project_id=p["id"], state="unconfigured", reason="handoff_task_path_missing",
                        execution_context_changed=False)
    task_file = within(pr, task_path, allow_missing=True)
    if not task_file.exists():
        return response("context.check", project_id=p["id"], state="blocked", reason="referenced_task_missing",
                        task_path=task_path, execution_context_changed=False)
    task_meta = frontmatter(text_file(task_file))
    if not isinstance(task_meta.get("task_id"),str):
        fail("INVALID_TASK_ID_TYPE","Current task needs a textual task ID")
    require_owner(task_meta,p,"task")
    candidate = task_meta.get("candidate_commit")
    checkout = task_meta.get("repository_path") or task_meta.get("worktree") or str(pr)
    if not isinstance(checkout, str):
        checkout = str(pr)
    from .ownership import canonical
    from .registry import load as load_registry
    owner_id=canonical(task_meta.get("current_project"))
    spec=load_registry(root)
    owners=[item for item in spec["projects"] if item["id"]==owner_id]
    if p["id"] in ("governance","company") and owner_id not in ("governance","company"):
        if owner_id is None and p.get("_registry_project_count",1)==1:
            inherited_policy=p.get("remote_policy","remote_tracked")
        elif len(owners)==1:
            inherited_policy=owners[0]["remote_policy"]
        else:
            fail("TASK_OWNER_UNRESOLVED","Cannot downgrade release policy for unregistered task owner")
    else:
        inherited_policy=p.get("remote_policy","remote_tracked")
    # Explicit task policy may make the gate stricter, never weaker.
    order={"local_only":0,"remote_tracked":1,"remote_publish_required":2}
    claimed=task_meta.get("remote_policy")
    if claimed is not None and claimed not in VALID_POLICIES:
        fail("REMOTE_POLICY",f"Unrecognized task policy {claimed}")
    policy=max((inherited_policy, claimed or inherited_policy),key=lambda x:order[x])
    original_declares_policy=bool(claimed or
                                  (Path(root)/".driftlock"/"projects.json").exists())
    if not original_declares_policy:
        policy="remote_tracked"
    snapshot = git_snapshot(checkout, policy=policy, expected_branch=task_meta.get("branch"),
                            candidate=candidate, head_policy=task_meta.get("candidate_head_policy", "exact"))
    cautions = []
    if not original_declares_policy:
        cautions.append("remote_policy_not_declared; existing handoff contract remains authoritative")
    lifecycle_blocking=[]
    if task_meta.get("merge_allowed") is True and task_meta.get("review_status") != "pass":
        lifecycle_blocking.append("merge_permission_conflicts_with_review")
    if task_meta.get("deploy_allowed") is True and task_meta.get("review_status") != "pass":
        lifecycle_blocking.append("deploy_permission_conflicts_with_review")
    if task_meta.get("candidate_state") in ("superseded","rejected") and (
        task_meta.get("merge_allowed") is True or task_meta.get("deploy_allowed") is True):
        lifecycle_blocking.append("superseded_candidate_permissions")
    if task_meta.get("review_status")=="fail" and (
        task_meta.get("merge_allowed") is True or task_meta.get("deploy_allowed") is True):
        lifecycle_blocking.append("failed_review_release_permissions")
    if task_meta.get("task_contract_version") in ("2",2):
        if task_meta.get("status")=="closed" and task_meta.get("review_status")!="pass":
            lifecycle_blocking.append("closed_without_review_pass")
        if task_meta.get("status") in ("accepted","accepted_pending_integration",
                                      "integrated","integrated_pending_deploy","closed"):
            if task_meta.get("candidate_state") in ("frozen","active") and not task_meta.get("candidate_commit"):
                lifecycle_blocking.append("accepted_candidate_commit_missing")
            if task_meta.get("candidate_state") in ("superseded","rejected"):
                lifecycle_blocking.append("accepted_candidate_invalid")
    if not isinstance(task_meta.get("task_id"),str):
        lifecycle_blocking.append("task_id_missing_or_invalid")
    lifecycle_blocking.extend(task_lifecycle_blockers(task_meta))
    lifecycle_blocking.extend(current_rework_issues(p,task_meta))
    lifecycle_blocking=sorted(set(lifecycle_blocking))
    return response("context.check", project_id=p["id"], task_id=task_meta.get("task_id"),
        task_path=task_path, status=task_meta.get("status"), review_status=task_meta.get("review_status"),
        permissions={"merge_allowed": task_meta.get("merge_allowed"), "deploy_allowed": task_meta.get("deploy_allowed")},
        git=snapshot,cautions=cautions, governance_blocking=lifecycle_blocking,
        state="blocked" if lifecycle_blocking or snapshot["state"]!="ok" else "ok",
        active_pointer_source="registry.active_task" if direct_task else "existing_handoff",
        execution_context_changed=False)

def plan_list(root, project_id=None, plan=None):
    p = select(root, project_id)
    pr = Path(p["_resolved_root"])
    folder = within(pr, p.get("planning", "planning"), allow_missing=True)
    if not folder.exists():
        return response("plan.list", project_id=p["id"], state="not_configured", plans=[])
    files = sorted(folder.rglob("*.md"))
    current = folder / "CURRENT_ROADMAP.md"
    records = []
    for f in files[:500]:
        if f.is_symlink() or not f.is_file():
            continue
        if not visible(frontmatter(text_file(f)),p,"plan",p.get("_registry_project_count")):
            continue
        relative = str(f.relative_to(pr))
        if plan and plan not in (relative, f.name):
            continue
        content = text_file(f)
        meta = frontmatter(content)
        title = next((line.removeprefix("# ").strip() for line in content.splitlines() if line.startswith("# ")), f.stem)
        status = meta.get("status") or "unknown_legacy"
        supersedes = meta.get("supersedes")
        records.append({"path": relative, "title": title[:140], "status": status,
                        "plan_id": meta.get("plan_id"), "supersedes": supersedes})
    if plan and not records:
        fail("PLAN_NOT_FOUND", f"Unknown plan: {plan}")
    result = response("plan.list" if not plan else "plan.trace", project_id=p["id"],
        current_roadmap_exists=current.exists(), plans=records, count=len(records),
        caveat="Unknown legacy status is not automatically inferred as active authority")
    if plan:
        from .plans import unpack
        all_plans = [(f,frontmatter(text_file(f))) for f in sorted(folder.rglob("*.md"))
                     if f.is_file() and not f.is_symlink()
                     and visible(frontmatter(text_file(f)),p,"plan",p.get("_registry_project_count"))]
        target_meta=frontmatter(text_file(pr/records[0]["path"]))
        target_id=target_meta.get("plan_id")
        depends_on=unpack(target_meta.get("depends_on"))
        supersedes=unpack(target_meta.get("supersedes"))
        consumers=[]
        replacements=[]
        if target_id:
            for f,meta in all_plans:
                if target_id in unpack(meta.get("depends_on")):
                    consumers.append(meta.get("plan_id") or str(f.relative_to(pr)))
                if target_id in unpack(meta.get("supersedes")):
                    replacements.append(meta.get("plan_id") or str(f.relative_to(pr)))
        result["trace"]={"plan_id":target_id,"depends_on":depends_on,"supersedes":supersedes,
            "consumers":consumers,"superseded_by":replacements}
    return result

def git_audit(root, project_id=None):
    """Read-only branch/worktree inventory with local integration evidence."""
    p = select(root, project_id)
    checkout = Path(p["_resolved_root"])
    out = git(checkout, "worktree", "list", "--porcelain", check=False)
    if out.returncode:
        return response("git.audit", project_id=p["id"], state="no_git_repository")
    worktrees = []
    for block in out.stdout.strip().split("\n\n"):
        if not block:continue
        entry={}
        for line in block.splitlines():
            if line.startswith("worktree "):entry["path"]=line[9:]
            elif line.startswith("HEAD "):entry["head"]=line[5:]
            elif line.startswith("branch "):entry["branch"]=line[7:].removeprefix("refs/heads/")
            elif line=="detached":entry["detached"]=True
            elif line=="locked":entry["locked"]=True
            elif line.startswith("prunable"):entry["prunable"]=True
        if entry:worktrees.append(entry)
    refs=git(checkout,"for-each-ref","--format=%(refname:short)|%(objectname:short)|%(upstream:short)",
             "refs/heads").stdout.strip().splitlines()
    names=[{"name":c[0],"head":c[1],"upstream":c[2] or None}
           for line in refs if len(c:=line.split("|",2))==3]
    branches={w["branch"] for w in worktrees if w.get("branch")}
    base = "master" if any(b["name"]=="master" for b in names) else (
           "main" if any(b["name"]=="main" for b in names) else None)
    results=[]
    for b in names[:180]:
        name=b["name"]
        item=dict(b, checked_out=name in branches,
                  branch_role="mainline" if name==base else "task_branch")
        if base and name!=base:
            merged=git(checkout,"merge-base","--is-ancestor",name,base,check=False).returncode==0
            count=git(checkout,"rev-list","--count",base+".."+name,check=False)
            item["merged_into_local_mainline"]=merged
            item["unique_commit_count"]=int(count.stdout.strip()) if count.returncode==0 and count.stdout.strip().isdigit() else None
            item["risk"]="worktree_active" if name in branches else (
                "unique_unmerged_work" if not merged else "local_merged_candidate")
        else:
            item["risk"]="mainline_or_unknown_base"
        if b["upstream"]:
            counts=git(checkout,"rev-list","--left-right","--count",b["upstream"]+"..."+name,check=False)
            if counts.returncode==0:
                try:
                    behind,ahead=map(int,counts.stdout.split())
                    item["remote_divergence"]={"ahead":ahead,"behind":behind}
                except ValueError:
                    item["remote_divergence"]="unavailable"
        else:
            item["remote_divergence"]="no_upstream_not_necessarily_error"
        results.append(item)
    local_only=[b["name"] for b in names if not b["upstream"]]
    return response("git.audit",project_id=p["id"],remote_policy=p["remote_policy"],
        local_base=base,worktree_count=len(worktrees),worktrees=worktrees[:200],
        branch_count=len(names),branches=results,truncated_branches=len(names)>180,
        local_no_upstream_count=len(local_only),
        protected_branches=sorted(branches),cleanup_performed=False,read_only=True,
        caveat="A local merge is not a remote publication. Inspect unique commits, worktree occupancy and task authority before cleanup.")

def doctor(root, project_id=None, script=None):
    p = select(root, project_id)
    checks = {"project": {"id": p["id"], "remote_policy": p["remote_policy"]}}
    checks["context"] = context_check(root, p["id"])
    tasks = task_check(root, p["id"])
    checks["tasks"] = {key: tasks[key] for key in ("scanned_files", "explicit_task_ids",
        "legacy_missing_task_id", "duplicate_ids", "broken_rework", "contradictory_statuses",
        "review_warnings","rework_chain_issues","blocking")}
    plans = plan_list(root, p["id"])
    from .plans import validate as validate_plans
    planning_check = validate_plans(root, p["id"])
    checks["planning"] = {
        "count": plans.get("count", 0), "current_roadmap_exists": plans.get("current_roadmap_exists"),
        "formal_plans": planning_check["formal_plans"],
        "legacy_unknown": planning_check["legacy_unknown_status"],
        "issues": planning_check["issues"],
    }
    from .problems import scan as scan_problems
    try:
        problems = scan_problems(root,p["id"])
        checks["problems"] = {"count":problems["count"],"authority":"existing_problem_register"}
    except Exception as exc:
        from .common import GovernanceError
        if not isinstance(exc,GovernanceError): raise
        checks["problems"] = {"status":"unavailable","reason":exc.code,"blocking":True}
    checks["existing_handoff"] = {
        "status":"not_executed",
        "reason":"Read-only doctor never executes project-provided scripts; run the authority guard separately",
    }
    if script:
        # Caller-provided checkers must not bypass the read-only contract.
        trusted=(Path(__file__).resolve().parents[1]/"scripts"/"driftlock.py").resolve()
        if Path(script).resolve()!=trusted:
            fail("UNTRUSTED_CHECKER", "doctor may only invoke this Skill's own read-only checker")
        try:
            process = subprocess.run([sys.executable, str(script), "check", str(p["_resolved_root"]), "--format", "json"],
                                     text=True, capture_output=True, timeout=30, check=False,
                                     env=git_safe_env())
        except (OSError, subprocess.TimeoutExpired) as exc:
            checks["documents"]={"status":"unavailable","error":str(exc),"blocking":True}
            process = None
        if process is not None:
            try:
                payload = json.loads(process.stdout)
                if not isinstance(payload,dict) or payload.get("command")!="check" or payload.get("schema_version")!=2:
                    raise ValueError("Missing expected Driftlock document-check schema")
                results=payload.get("results")
                errors=payload.get("blocking_errors")
                valid_states={"CURRENT","STALE","UNVERIFIED","REVIEW_REQUIRED","SUPERSEDED","ARCHIVED"}
                if (not isinstance(results,list) or not isinstance(errors,list)
                        or any(not isinstance(x,dict) or x.get("state") not in valid_states for x in results)
                        or any(not isinstance(x,dict) for x in errors)):
                    raise ValueError("Malformed document-check results or errors")
                attention_states={"STALE","UNVERIFIED","REVIEW_REQUIRED"}
                attention=any(item["state"] in attention_states for item in results)
                if process.returncode in (0,1) and bool(process.returncode)!=attention:
                    raise ValueError("Document-check exit code disagrees with document states")
                if process.returncode not in (0,1) or errors:
                    checks["documents"]={"exit_code":process.returncode,"blocking":True,
                                         "blocking_errors":errors}
                else:
                    checks["documents"]={"exit_code":process.returncode,"blocking":False,
                       "results":[r for r in payload.get("results",[]) if r.get("state")!="CURRENT"],
                       "blocking_errors":[]}
            except (ValueError,TypeError) as exc:
                checks["documents"] = {"exit_code": process.returncode,"error":str(exc), "blocking":True}
    is_blocked = (
        checks["context"].get("state") == "blocked"
        or checks["tasks"].get("blocking") is True
        or bool(checks["planning"].get("issues"))
        or checks.get("documents", {}).get("blocking") is True
        or checks.get("problems", {}).get("blocking") is True
        or checks["context"].get("state") == "unavailable"
    )
    attention=(
        any(x.get("state") in ("STALE","UNVERIFIED","REVIEW_REQUIRED") for x in
            checks.get("documents",{}).get("results",[]))
        or checks["context"].get("state")=="unconfigured"
        or bool(checks["tasks"].get("review_warnings"))
        or checks["planning"].get("legacy_unknown",0)>0
        or (checks["existing_handoff"].get("status")=="not_executed" and
            (Path(p["_resolved_root"])/"tools"/"handoff.py").is_file())
    )
    return response("doctor", project_id=p["id"], checks=checks,
        state="blocked" if is_blocked else "review_required" if attention else "ok", read_only=True,
        scope="Diagnostic reports do not replace existing Company Control handoff authority")
