"""Existing markdown Problem Register adapter: no parallel record store."""
from __future__ import annotations
import re
from pathlib import Path
from difflib import SequenceMatcher
from .atomic import change
from .common import fail, frontmatter, response, text_file, within
from .registry import select
from .ownership import require_owner
from .audit import tasks_for

PROBLEM_STATES = {"needs_revalidation", "confirmed", "planned", "in_task", "resolved", "obsolete", "parked"}
END_STATES = {"resolved", "obsolete", "parked"}
RULES = {
 "needs_revalidation": {"confirmed", "obsolete", "parked"},
 "confirmed": {"planned", "in_task", "obsolete", "parked"},
 "planned": {"in_task", "parked", "confirmed"},
 "in_task": {"resolved", "obsolete", "parked", "confirmed"},
 "parked": {"confirmed", "needs_revalidation"},
 "resolved": {"needs_revalidation"},
 "obsolete": {"needs_revalidation"},
}
TOKEN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
ID = re.compile(r"^PROBLEM-\d{3,}$")

def rows(contents):
    data = []
    for lineno, line in enumerate(contents.splitlines(keepends=True)):
        if not line.lstrip().startswith("|") or not re.search(r"\bPROBLEM-\d+\b", line):
            continue
        cols = [col.strip() for col in line.strip().strip("|").split("|")]
        if len(cols) < 3:
            continue
        ident = re.search(r"\bPROBLEM-\d+\b", cols[0])
        if ident is None:
            continue
        data.append({"id": ident.group(), "status": cols[1].strip(chr(96)+" "),
                    "description": cols[2], "task": cols[3] if len(cols)>3 else "",
                    "columns": cols, "line": line, "line_number": lineno})
    return data

def problem_path(root, project):
    p = select(root, project)
    rel = (p.get("intake") or {}).get("problem", "current/PROBLEM_REGISTER.md")
    path = within(p["_resolved_root"], rel, allow_missing=True)
    if not path.exists():
        fail("PROBLEM_REGISTER_MISSING", "No existing authoritative Problem Register")
    return p, rel, path

def scan(root, project=None, candidate=None):
    p, rel, path = problem_path(root, project)
    entries = rows(text_file(path))
    if candidate:
        phrase = candidate.casefold()
        words = set(TOKEN.findall(phrase))
        scored = []
        for e in entries:
            existing = e["description"].casefold()
            overlap = len(words.intersection(TOKEN.findall(existing))) / max(1, len(words))
            ratio = SequenceMatcher(a=phrase[:320], b=existing[:320], autojunk=False).ratio()
            score = round(max(overlap, ratio), 3)
            if score >= .15:
                scored.append({"id":e["id"], "score":score,
                               "state":e["status"],"description":e["description"][:180]})
        scored.sort(key=lambda e: -e["score"])
        return response("problem.candidates", project_id=p["id"],
            candidates=scored[:12], counts=len(entries),
            decision="advisory_only; operator must confirm identity")
    return response("problem.list", project_id=p["id"],
        count=len(entries), problems=[{"id":e["id"],"status":e["status"],
            "description":e["description"][:140], "task":e["task"]} for e in entries[:250]])

def reconcile(root, project=None):
    """Join current Problem Register rows to formal TASK statuses without writing."""
    p, _, path = problem_path(root, project)
    task_map = {}
    for task in tasks_for(p):
        meta = frontmatter(text_file(task))
        if meta.get("task_id"):
            task_map[meta["task_id"]] = meta
    issues, linked = [], 0
    for row in rows(text_file(path)):
        links = re.findall(r"(?<![A-Za-z0-9-])(?:[A-Z]{2,4}-)?TASK-\d+(?:-[A-Z])?(?:-R\d+)?", row["task"])
        if not links:
            if row["status"] == "in_task":
                issues.append({"problem_id":row["id"],"code":"IN_TASK_WITHOUT_TASK_POINTER"})
            continue
        linked += 1
        located = [(identifier,task_map.get(identifier)) for identifier in links]
        if not any(meta for _,meta in located):
            issues.append({"problem_id":row["id"],"code":"TASK_POINTER_NOT_VERIFIED",
                           "links":links,"severity":"review"})
            continue
        for ident, meta in located:
            if not meta:continue
            status=meta.get("status")
            if row["status"] == "resolved" and status not in ("closed","deployed_production_verified"):
                issues.append({"problem_id":row["id"],"code":"PROBLEM_CLOSED_TASK_NOT_CLOSED",
                               "task_id":ident,"task_status":status,"severity":"review"})
            if row["status"]=="in_task" and status=="closed":
                issues.append({"problem_id":row["id"],"code":"TASK_CLOSED_PROBLEM_NEEDS_VERIFICATION",
                               "task_id":ident,"severity":"review"})
    return response("problem.reconcile",project_id=p["id"],problems_scanned=len(rows(text_file(path))),
        linked_problems=linked,issues=issues,write_performed=False,
        caveat="Only confirmed task closure plus verification evidence can authorize problem resolution")

def task_metadata(project, task_id):
    matches = [(frontmatter(text_file(path)),path) for path in tasks_for(project)
               if frontmatter(text_file(path)).get("task_id")==task_id]
    if len(matches)!=1:
        fail("TASK_ID_NOT_UNIQUE",f"Cannot prove a unique authoritative TASK {task_id}: {len(matches)}")
    return matches[0]

def _verify_resolution_claim(root, linked_task_id, evidence, task_meta):
    """Only an exact, committed, structured PASS for the correct candidate."""
    from .common import git
    if not evidence or not isinstance(evidence, str):
        fail("RESOLUTION_EVIDENCE_REQUIRED", "A tracked Review report is required")
    path = within(root, evidence, allow_missing=False)
    if not path.is_file() or path.suffix.lower() not in (".md", ".json"):
        fail("RESOLUTION_EVIDENCE_FORMAT", "Evidence must be a trusted review report")
    rel = str(path.relative_to(Path(root)))
    # A loose positive word or an untracked, edited report must never close a defect.
    result = git(root, "ls-files", "--error-unmatch", "--", rel, check=False)
    if result.returncode:
        fail("UNTRACKED_EVIDENCE", "Review evidence is not in the Git index")
    committed = git(root, "show", "HEAD:" + rel, check=False)
    if committed.returncode or committed.stdout != text_file(path):
        fail("UNCOMMITTED_EVIDENCE", "Review evidence differs from HEAD")
    body = text_file(path)
    fields = frontmatter(body)
    # Exact, unambiguous verdict and task fields are required; never infer via prose.
    if fields.get("task_id") != linked_task_id:
        fail("RESOLUTION_TASK_MISMATCH", "Review report task_id is not exact")
    if fields.get("verdict") != "PASS":
        fail("RESOLUTION_NOT_VERIFIED", "Review verdict must be exactly PASS")
    if task_meta.get("review_status") != "pass":
        fail("TASK_REVIEW_NOT_PASSED", "TASK review_status is not pass")
    candidate = task_meta.get("candidate_commit")
    if not isinstance(candidate, str) or not re.fullmatch(r"[a-f0-9]{40}", candidate):
        fail("TASK_CANDIDATE_MISSING", "Closure requires an exact candidate SHA")
    if fields.get("candidate_commit") != candidate:
        fail("RESOLUTION_CANDIDATE_MISMATCH", "Review candidate SHA differs from TASK")
    if fields.get("review_status") != "accepted":
        fail("RESOLUTION_NOT_ACCEPTED", "Review must be independently accepted")
    return rel


def transition(root, project, problem_id, next_state, expected_sha,
               task_id=None, evidence=None, approved=False):
    if not ID.fullmatch(problem_id):
        fail("PROBLEM_ID", "Expected PROBLEM-nnn")
    if next_state not in PROBLEM_STATES:
        fail("PROBLEM_STATE", "Unknown problem state")
    p, rel, path = problem_path(root, project)
    if p["id"] not in ("governance","company") and p.get("_registry_project_count",1)>1:
        fail("PROBLEM_AUTHORITY_NOT_SCOPED", "Shared Company Control register requires governance scope")
    content = text_file(path)
    candidates = [r for r in rows(content) if r["id"] == problem_id]
    if len(candidates) != 1:
        fail("PROBLEM_ID_AMBIGUOUS", f"Expected one matching row, found {len(candidates)}")
    row = candidates[0]
    if row["status"] not in RULES:
        fail("LEGACY_PROBLEM_STATE", f"Unknown current state: {row['status']}")
    if row["status"] != next_state and next_state not in RULES[row["status"]]:
        fail("ILLEGAL_PROBLEM_TRANSITION", f"{row['status']} -> {next_state}")
    if next_state == "in_task" and not task_id and not row["task"].strip(chr(96)+" "):
        fail("TASK_ID_REQUIRED", "Existing authoritative task ID needed")
    if task_id:
        # Do not silently substitute an unrelated accepted TASK for the TASK
        # which actually owns the user-reported defect.
        prior_links = re.findall(
            r"(?<![A-Za-z0-9-])(?:[A-Z]{2,5}-)?TASK-\d+(?:-[A-Z])?(?:-R\d+)?",
            row["task"],
        )
        if row["status"] == "in_task" and prior_links and task_id not in prior_links:
            fail("PROBLEM_TASK_MISMATCH","Linked TASK does not match the existing problem owner")
        meta, _ = task_metadata(p, task_id)
        if next_state == "resolved":
            if meta.get("status") != "closed":
                fail("TASK_NOT_CLOSED", "Closed task needed before resolution")
            _verify_resolution_claim(p["_resolved_root"], task_id, evidence, meta)
    if next_state in END_STATES and (not evidence or len(evidence.strip()) < 8):
        fail("OUTCOME_EVIDENCE_REQUIRED", "Terminal state requires evidence reference")
    if next_state == "resolved" and not task_id:
        fail("TASK_ID_REQUIRED", "Resolution needs linked closed task and verification evidence")
    cols = list(row["columns"])
    cols[1] = next_state
    if task_id:
        if len(cols) < 4:
            fail("PROBLEM_SCHEMA", "Problem register needs task linkage column")
        # Existing Gate/scope/secondary linkage is authoritative.  Do not
        # rewrite it just because the caller repeats the same task ID.
        original_links = re.findall(r"(?<![A-Za-z0-9-])(?:[A-Z]{2,5}-)?TASK-\d+(?:-[A-Z])?(?:-R\d+)?", cols[3])
        if original_links and task_id not in original_links:
            fail("PROBLEM_TASK_REASSIGNMENT_REQUIRES_SEPARATE_REVIEW", "Do not replace an existing task linkage")
        if not original_links:
            cols[3] = task_id
    if evidence:
        if len(cols) < 5:
            fail("PROBLEM_SCHEMA", "Problem register needs followup column")
        if "|" in evidence or "\n" in evidence or "\r" in evidence:
            fail("PROBLEM_EVIDENCE", "Evidence must be one line")
        cols[4] = (cols[4] + " ; " if cols[4] else "") + "Evidence: " + evidence.strip()
    new_line = "| " + " | ".join(cols) + " |\n"
    if row["line"] not in content or content.count(row["line"]) != 1:
        fail("PROBLEM_AMBIGUOUS_LINE", "Source line not unique")
    updated = content.replace(row["line"], new_line, 1)
    result = change(p["_resolved_root"], rel, expected_sha, updated, approve=approved)
    return response("problem.transition", project_id=p["id"], problem_id=problem_id,
        previous=row["status"], current=next_state, task_id=task_id,
        **result, task_created=False, execution_context_changed=False)


def capture(root, project, problem_id, observation, source, expected_sha, approved=False):
    """Add a raw, unverified observation as ONE table row in an existing register."""
    from .common import sha
    if not ID.fullmatch(problem_id):
        fail("PROBLEM_ID", "Use a stable PROBLEM-### ID allocated in the existing register")
    if len(observation.strip())>2400 or not observation.strip():
        fail("OBSERVATION_LENGTH","Provide 1..2400 characters")
    if any(ch in source for ch in ("|","\n","\r")) or len(source)>160:
        fail("SOURCE_FORMAT","Source reference must be one line")
    p, rel, path=problem_path(root,project)
    content=text_file(path)
    entries=rows(content)
    if not entries:fail("PROBLEM_TABLE_MISSING","No problem table found")
    matching=[e for e in entries if e["id"]==problem_id]
    phrase=" ".join(observation.strip().split()).replace("|","/").replace(chr(96),"'")
    tag="capture:"+sha(observation.strip()+"\x00"+source)[:16]
    if matching:
        prior=matching[0]
        if len(matching)==1 and tag in prior["line"] and phrase in prior["line"]:
            return response("problem.capture",project_id=p["id"],problem_id=problem_id,
                persisted=True,replay=True,path=str(path),sha256=sha(content),task_created=False)
        fail("PROBLEM_ID_CONFLICT","Problem ID already exists with different evidence")
    # Do not insert next to arbitrary markdown headings: append immediately after the final
    # known problem row, preserving everything else.
    last=entries[-1]
    cols=last["columns"]
    if len(cols)!=5:
        fail("PROBLEM_SCHEMA","Expected five columns in current problem register")
    next_step=f"Source: {source}; {tag}; needs validation"
    newline="| "+ " | ".join([problem_id,"needs_revalidation",phrase,"未建立",next_step])+" |\n"
    tail=last["line"]
    if content.count(tail)!=1:fail("PROBLEM_TABLE_AMBIGUOUS","Cannot safely locate insertion point")
    new_content=content.replace(tail,tail+newline,1)
    result=change(p["_resolved_root"],rel,expected_sha,new_content,approve=approved)
    return response("problem.capture",project_id=p["id"],problem_id=problem_id,
        persisted=True,replay=False,**result,task_created=False,execution_context_changed=False)
