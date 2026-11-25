"""Non-interrupting conversation intake: proposal by default; bounded opt-in write."""
from __future__ import annotations
import os
import re
import tempfile
from pathlib import Path
from .common import fail, sha, within, response, text_file
from .registry import select
from .atomic import change

def propose(root, project, text, kind=None):
    if not text or not text.strip() or len(text) > 4000:
        fail("INTAKE_TEXT", "Provide 1..4000 characters")
    valid = {"question", "observation", "problem", "idea", "research", "plan", "execution", "switch"}
    if kind is not None and kind not in valid:
        fail("INTAKE_KIND", f"Invalid kind: {kind}")
    # Deliberately conservative: semantic classification belongs to the calling AI.
    # Unknown intent must never mutate execution state.
    category = kind or "needs_clarification"
    p = select(root, project)
    return response("intake.propose", project_id=p["id"], category=category,
        normalized_text=text.strip(), interpretation="operator_provided" if kind else "unclassified",
        candidate_intake=(p.get("intake") or {}).get(category),
        execution_context_changed=False, task_created=False, persisted=False,
        requires_authorization=category in ("execution", "switch"),
        suggested_action="discuss_or_confirm" if category == "needs_clarification" else
                         "review_authoritative_record_before_write")

def record(root, project, kind, text, record_id, expected_sha, source, approved):
    if not approved:
        fail("INTAKE_APPROVAL_REQUIRED", "Use --approve for explicit authorized persistence")
    if kind not in ("idea", "problem", "research"):
        fail("INTAKE_KIND", "Only idea/problem/research can be recorded")
    if not text or not text.strip() or len(text) > 4000:
        fail("INTAKE_TEXT", "Provide 1..4000 characters")
    if not source or len(source) > 500 or "\n" in source or "\r" in source or not record_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,79}", record_id):
        fail("INTAKE_IDENTITY", "Supply a stable id and source")
    p = select(root, project)
    path = (p.get("intake") or {}).get(kind)
    if not path:
        fail("INTAKE_NOT_CONFIGURED", "No authoritative intake file for this kind; not writing")
    project_root = Path(p["_resolved_root"])
    target = within(project_root, path, allow_missing=True)
    if target.exists() and (target.is_symlink() or not target.is_file()):
        fail("UNSAFE_INTAKE_FILE", "Refuse to write non-regular/symlink target")
    preexisting = text_file(target) if target.exists() else ""
    if kind == "problem" and target.exists() and "PROBLEM-" in preexisting and "|" in preexisting:
        from .problems import capture
        return capture(root, project, record_id, text, source, expected_sha, approved)
    before_tag_prefix = f"<!-- driftlock-intake:{record_id}:"
    before_tag = before_tag_prefix + sha(kind + "\x00" + text.strip() + "\x00" + source) + " -->"
    if before_tag_prefix in preexisting:
        if before_tag not in preexisting:
            fail("INTAKE_ID_CONFLICT", "Record ID is already bound to different content")
        return response("intake.record", record_id=record_id, project_id=p["id"],
            persisted=True, replay=True, path=str(target), sha256=sha(preexisting),
            execution_context_changed=False, task_created=False)
    if expected_sha != sha(preexisting):
        fail("INTAKE_VERSION_CONFLICT", f"Expected {expected_sha}, actual {sha(preexisting)}")
    payload_hash = sha(kind + "\x00" + text.strip() + "\x00" + source)
    id_prefix = f"<!-- driftlock-intake:{record_id}:"
    tag = id_prefix + payload_hash + " -->"
    clean = text.strip().replace("\r", "").replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    quoted = "\n".join("> " + line for line in clean.split("\n"))
    block = f"\n{tag}\n### {kind.upper()} {record_id}\n\nSource: {source}\nStatus: captured_unverified\n\n{quoted}\n"
    content = preexisting + ("" if not preexisting or preexisting.endswith("\n") else "\n") + block
    result = change(project_root, path, expected_sha, content,
                    approve=approved, allow_create=True)
    return response("intake.record", record_id=record_id, project_id=p["id"], persisted=True,
        replay=False, path=str(target), sha256=result["sha256"],
        execution_context_changed=False, task_created=False,
        driftlock_verification_required=True)
