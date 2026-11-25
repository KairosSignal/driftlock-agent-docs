"""CLI integration for optional governance commands."""
from __future__ import annotations
import json
from .common import GovernanceError, response
from .registry import project_list, project_status
from .intake import propose, record
from .audit import context_check, task_check, plan_list, git_audit, doctor
from .problems import scan as problem_scan, transition as problem_transition, reconcile as problem_reconcile
from .plans import validate as plan_validate, transition as plan_transition
from .allocator import reserve as task_reserve, inspect as task_reservations
from .skill_install import status as skill_status
from .triage import triage as intake_triage

def configure(subs):
    def group(name, actions):
        parent = subs.add_parser(name)
        actions_parser = parent.add_subparsers(dest="action", required=True)
        for action in actions:
            cmd = actions_parser.add_parser(action)
            cmd.add_argument("project_root")
            cmd.add_argument("--project", default=None)
            cmd.add_argument("--format", choices=("json", "text"), default="text")
            if name == "portfolio":
                if action=="harvest":
                    cmd.add_argument("--limit",type=int,default=50)
                    cmd.add_argument("--task",default=None)
                if action=="preflight":
                    cmd.add_argument("--task",default=None)
                    cmd.add_argument("--query",default=None)
                if action in ("learn","promote","accept-scope"):
                    fields={
                        "learn":("cause","task","lesson","prevention","source","source-sha","expected-sha"),
                        "promote":("cause","level","evidence","expected-sha"),
                        "accept-scope":("id","evidence","expected-sha"),
                    }[action]
                    for field in fields:cmd.add_argument("--"+field,required=True)
                    cmd.add_argument("--approve",action="store_true")
                    if action=="learn":
                        cmd.add_argument("--start",type=int,required=True)
                        cmd.add_argument("--end",type=int,required=True)
                        cmd.add_argument("--tags",default=None)
                    if action=="promote":cmd.add_argument("--check",default=None)
                if action in ("lessons","advise"):
                    cmd.add_argument("--query", required=action=="advise", default=None)
                if action == "link":
                    for field in ("id","target","expected-sha"):
                        cmd.add_argument("--"+field, required=True)
                    cmd.add_argument("--approve", action="store_true")
                if action == "record-lesson":
                    for field in ("id","cause","task-ids","lesson","prevention","evidence","expected-sha"):
                        cmd.add_argument("--"+field, required=True)
                    cmd.add_argument("--approve", action="store_true")
            if name == "skill" and action == "status":
                cmd.add_argument("--installed", required=True)
            if name == "intake":
                cmd.add_argument("--kind", choices=("question","observation","problem","idea","research","plan","execution","switch"))
                cmd.add_argument("--text", required=True)
                if action == "record":
                    cmd.add_argument("--id", required=True)
                    cmd.add_argument("--source", required=True)
                    cmd.add_argument("--expected-sha", required=True)
                    cmd.add_argument("--approve", action="store_true")
            if name == "task":
                if action == "check":
                    cmd.add_argument("--id", default=None)
                elif action == "reserve":
                    cmd.add_argument("--expected-sha", required=True)
                    cmd.add_argument("--approve", action="store_true")
            if name == "plan":
                if action == "trace": cmd.add_argument("--path", required=True)
                if action == "transition":
                    cmd.add_argument("--id", required=True)
                    cmd.add_argument("--to", required=True)
                    cmd.add_argument("--evidence", default=None)
                    cmd.add_argument("--expected-sha", required=True)
                    cmd.add_argument("--approve", action="store_true")
            if name == "problem":
                if action == "candidates":
                    cmd.add_argument("--text", required=True)
                if action == "transition":
                    cmd.add_argument("--id", required=True)
                    cmd.add_argument("--to", required=True)
                    cmd.add_argument("--task", default=None)
                    cmd.add_argument("--evidence", default=None)
                    cmd.add_argument("--expected-sha", required=True)
                    cmd.add_argument("--approve", action="store_true")
    for key, actions in (("project", ("list","status")),
                         ("context", ("show","check")),
                         ("intake", ("propose","triage","record")),
                         ("task", ("check","reservations","reserve")),
                         ("plan", ("list","trace","validate","transition")),
                         ("problem", ("list","candidates","reconcile","transition")),
                         ("git", ("audit",)),
                         ("doctor", ("check",)),
                         ("skill", ("status",)),
                         ("portfolio", ("overview","backlog","dependencies","lessons","resources","record-lesson","link","advise","graph","sync","accept-scope","learn","harvest","promote","preflight","recommendations"))):
        group(key, actions)

def run(args, base_script):
    root = args.project_root
    p = args.project
    if args.command == "project":
        data = project_list(root) if args.action == "list" else project_status(root, p)
    elif args.command == "context":
        data = context_check(root, p)
        data["command"] = f"context.{args.action}"
        # Task-entry recall is additive; no alternate release decision or task switch.
        if args.action=="check" and data.get("task_id"):
            from .knowledge import preflight
            try:
                entry=preflight(root,p,data["task_id"])
                data["engineering_memory"]={k:v for k,v in entry.items() if k not in ("warnings","schema_version","command")}
                if data.get("status") in ("closed","rework_required","deployed_pending_close","deployed") or data.get("review_status")=="fail":
                    from .knowledge import harvest
                    try:
                        capture=harvest(root,entry["project_id"],3,data["task_id"])
                        data["engineering_memory"]["new_evidence_candidates"]=capture["candidates"]
                    except GovernanceError as exc:
                        data["engineering_memory"]["capture_warning"]=exc.code
                if entry.get("state")=="blocked":
                    data["state"]="blocked"
                    data.setdefault("governance_blocking",[]).append("approved_lesson_check_failed")
            except GovernanceError as exc:
                data["engineering_memory"]={"state":"review_required","code":exc.code,"reason":str(exc)}

    elif args.command == "intake":
        if args.action == "propose":
            data = propose(root, p, args.text, args.kind)
        elif args.action == "triage":
            data = intake_triage(root, p, args.text, args.kind)
        else:
            data = record(root, p, args.kind, args.text, args.id, args.expected_sha,
                          args.source, args.approve)
    elif args.command == "task":
        if args.action == "check":
            data = task_check(root, p, args.id)
        elif args.action == "reservations":
            data = task_reservations(root)
        else:
            data = task_reserve(root, p, args.expected_sha, approve=args.approve)
    elif args.command == "plan":
        if args.action == "validate":
            data = plan_validate(root, p)
        elif args.action == "transition":
            data = plan_transition(root, p, args.id, args.to, args.expected_sha,
                                   args.evidence, args.approve)
        else:
            data = plan_list(root, p, getattr(args, "path", None))
    elif args.command == "problem":
        if args.action == "list":
            data = problem_scan(root, p)
        elif args.action == "reconcile":
            data = problem_reconcile(root, p)
        elif args.action == "candidates":
            data = problem_scan(root, p, candidate=args.text)
        else:
            data = problem_transition(root, p, args.id, args.to, args.expected_sha,
                                     task_id=args.task, evidence=args.evidence,
                                     approved=args.approve)
    elif args.command == "git":
        data = git_audit(root, p)
    elif args.command == "doctor":
        data = doctor(root, p, base_script)
    elif args.command == "portfolio":
        from . import portfolio
        if args.action in ("graph","sync"):
            from . import relations
            data=getattr(relations,args.action)(root,p)
        elif args.action=="accept-scope":
            from .relations import accept_scope
            data=accept_scope(root,p,args.id,args.evidence,args.expected_sha,args.approve)
        elif args.action in ("learn","promote","harvest","preflight","recommendations"):
            from . import knowledge
            if args.action=="learn":
                data=knowledge.learn(root,p,args.cause,args.task,args.lesson,args.prevention,args.source,args.start,args.end,args.source_sha,args.expected_sha,args.approve,args.tags)
            elif args.action=="promote":
                data=knowledge.promote(root,p,args.cause,args.level,args.evidence,args.expected_sha,args.approve,args.check)
            elif args.action=="harvest":
                data=knowledge.harvest(root,p,args.limit,args.task)
            elif args.action=="preflight":
                data=knowledge.preflight(root,p,args.task,args.query)
            else:
                data=knowledge.recommendations(root,p)
        elif args.action == "link":
            data = portfolio.link_record(root,p,args.id,args.target,args.expected_sha,args.approve)
        elif args.action == "record-lesson":
            data = portfolio.record_lesson(root,p,args.id,args.cause,args.task_ids,args.lesson,args.prevention,args.evidence,args.expected_sha,args.approve)
        elif args.action in ("lessons","advise"):
            data = getattr(portfolio,args.action)(root,p,args.query)
        else:
            data = getattr(portfolio,args.action)(root,p)
    elif args.command == "skill":
        from pathlib import Path
        data = skill_status(Path(base_script).parent.parent, args.installed)
    else:
        raise ValueError("Unrecognized governance command")
    if args.format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"{data['command']}: {data.get('project_id','')}")
        print(json.dumps({key: val for key, val in data.items() if key not in ("command", "schema_version")},
                         ensure_ascii=False, indent=2))
    return (2 if data.get("state") == "blocked" or data.get("blocking") is True
            else 1 if data.get("state") == "review_required" else 0)
