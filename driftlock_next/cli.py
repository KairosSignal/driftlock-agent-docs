"""CLI integration for optional governance commands."""
from __future__ import annotations
import json
from .common import GovernanceError, response
from .registry import project_list, project_status
from .intake import propose, record
from .audit import context_check, task_check, plan_list, git_audit, doctor

def configure(subs):
    def group(name, actions):
        parent = subs.add_parser(name)
        actions_parser = parent.add_subparsers(dest="action", required=True)
        for action in actions:
            cmd = actions_parser.add_parser(action)
            cmd.add_argument("project_root")
            cmd.add_argument("--project", default=None)
            cmd.add_argument("--format", choices=("json", "text"), default="text")
            if name == "intake":
                cmd.add_argument("--kind", choices=("question","observation","problem","idea","research","plan","execution","switch"))
                cmd.add_argument("--text", required=True)
                if action == "record":
                    cmd.add_argument("--id", required=True)
                    cmd.add_argument("--source", required=True)
                    cmd.add_argument("--expected-sha", required=True)
                    cmd.add_argument("--approve", action="store_true")
            if name == "task" and action == "check":
                cmd.add_argument("--id", default=None)
            if name == "plan" and action == "trace":
                cmd.add_argument("--path", required=True)
    for key, actions in (("project", ("list","status")),
                         ("context", ("show","check")),
                         ("intake", ("propose","record")),
                         ("task", ("check",)),
                         ("plan", ("list","trace")),
                         ("git", ("audit",)),
                         ("doctor", ("check",))):
        group(key, actions)

def run(args, base_script):
    root = args.project_root
    p = args.project
    if args.command == "project":
        data = project_list(root) if args.action == "list" else project_status(root, p)
    elif args.command == "context":
        data = context_check(root, p)
        data["command"] = f"context.{args.action}"
    elif args.command == "intake":
        if args.action == "propose":
            data = propose(root, p, args.text, args.kind)
        else:
            data = record(root, p, args.kind, args.text, args.id, args.expected_sha,
                          args.source, args.approve)
    elif args.command == "task":
        data = task_check(root, p, args.id)
    elif args.command == "plan":
        data = plan_list(root, p, getattr(args, "path", None))
    elif args.command == "git":
        data = git_audit(root, p)
    elif args.command == "doctor":
        data = doctor(root, p, base_script)
    else:
        raise ValueError("Unrecognized governance command")
    if args.format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"{data['command']}: {data.get('project_id','')}")
        print(json.dumps({key: val for key, val in data.items() if key not in ("command", "schema_version")},
                         ensure_ascii=False, indent=2))
    return 2 if data.get("state") == "blocked" or data.get("blocking") is True else 0
