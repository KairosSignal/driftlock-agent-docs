"""Project identity resolution and explicit, opt-in registry."""
from __future__ import annotations
import re
from pathlib import Path
from .common import read_json, within, fail, response

IDENT = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
PREFIX = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")

def load(root):
    root = Path(root).resolve()
    config = root / ".driftlock" / "projects.json"
    if not config.exists():
        return {
            "schema_version": 1,
            "mode": "single_project_fallback",
            "projects": [{
                "id": root.name.replace("_", "-").lower(),
                "name": root.name,
                "root": ".",
                "repository": None,
                "task_prefix": None,
                "tasks": "tasks",
                "planning": "planning",
                "handoff": "CURRENT_HANDOFF.md",
                "remote_policy": "remote_tracked",
                "intake": {},
            }],
        }
    if config.is_symlink():
        fail("UNSAFE_CONFIG", "Registry may not be a symlink")
    spec = read_json(config)
    if spec.get("schema_version") != 1:
        fail("REGISTRY_VERSION", "Unsupported registry schema")
    projects = spec.get("projects")
    if not isinstance(projects, list) or not projects:
        fail("REGISTRY_PROJECTS", "At least one project is required")
    ids, prefixes = set(), set()
    results = []
    for item in projects:
        if not isinstance(item, dict):
            fail("REGISTRY_PROJECT", "Project must be an object")
        ident = item.get("id")
        pref = item.get("task_prefix")
        if not isinstance(ident, str) or not IDENT.fullmatch(ident) or ident in ids:
            fail("REGISTRY_PROJECT_ID", f"Invalid or duplicate project id: {ident}")
        if pref is not None and (not isinstance(pref, str) or not PREFIX.fullmatch(pref) or pref in prefixes):
            fail("REGISTRY_PREFIX", f"Invalid or duplicate task prefix: {pref}")
        ids.add(ident)
        if pref:
            prefixes.add(pref)
        location = item.get("root", ".")
        if not isinstance(location, str):
            fail("REGISTRY_ROOT", "Project root must be a string")
        # Explicit sibling repositories are allowed; no implicit filesystem discovery.
        project_root = (root / location).resolve()
        if not project_root.is_dir() or project_root == Path("/"):
            fail("REGISTRY_ROOT", f"Project root missing/invalid: {location}")
        project = dict(item)
        project["_resolved_root"] = str(project_root)
        for field, default in (("tasks", "tasks"), ("planning", "planning"), ("handoff", "CURRENT_HANDOFF.md")):
            rel = project.get(field, default)
            if not isinstance(rel, str):
                fail("REGISTRY_PATH", f"Invalid {field}")
            within(project_root, rel, allow_missing=True)
            project.setdefault(field, default)
        # Fail closed: an unspecified policy must not silently waive upstream gates.
        policy = project.get("remote_policy", "remote_tracked")
        if policy not in ("local_only", "remote_tracked", "remote_publish_required"):
            fail("REMOTE_POLICY", f"Invalid remote policy: {policy}")
        project.setdefault("remote_policy", policy)
        if project.get("task_allocator") not in (None,"local_serialized"):
            fail("ALLOCATOR_POLICY", "Unknown task allocator policy")
        if "active_task" in project:
            if not isinstance(project["active_task"], str):
                fail("REGISTRY_ACTIVE_TASK", "Active task pointer must be a relative path")
            within(project_root, project["active_task"], allow_missing=True)
        intake = project.get("intake", {})
        if not isinstance(intake, dict):
            fail("REGISTRY_INTAKE", "Expected intake mapping")
        for kind, path in intake.items():
            if kind not in ("idea", "problem", "research") or not isinstance(path, str):
                fail("REGISTRY_INTAKE", "Unknown intake kind/path")
            within(project_root, path, allow_missing=True)
        project.setdefault("intake", {})
        results.append(project)
    return {"schema_version": 1, "mode": "registry", "projects": results}

def select(root, project_id=None):
    config = load(root)
    matches = [p for p in config["projects"] if project_id is None or p["id"] == project_id]
    if not matches or (project_id is None and len(matches) > 1):
        fail("PROJECT_SELECTION_REQUIRED", "Specify --project; available: " + ", ".join(p["id"] for p in config["projects"]))
    project = dict(matches[0])
    if "_resolved_root" not in project:
        project["_resolved_root"] = str((Path(root).resolve() / project["root"]).resolve())
    return project

def project_list(root):
    spec = load(root)
    results = []
    for p in spec["projects"]:
        root_path = p.get("_resolved_root") or str((Path(root).resolve() / p["root"]).resolve())
        results.append({
            "project_id": p["id"], "name": p.get("name", p["id"]),
            "root": root_path, "repository": p.get("repository"),
            "task_prefix": p.get("task_prefix"), "remote_policy": p.get("remote_policy"),
            "active_task": p.get("active_task"),
        })
    return response("project.list", mode=spec["mode"], projects=results)

def project_status(root, project_id):
    p = select(root, project_id)
    path = Path(p["_resolved_root"])
    return response("project.status", project_id=p["id"], root=str(path),
        repository=p.get("repository"), task_prefix=p.get("task_prefix"),
        remote_policy=p["remote_policy"],
        paths={key: {"path": str((path / p[key]).resolve()), "exists": (path / p[key]).exists()}
               for key in ("tasks", "planning", "handoff")},
        intake=p.get("intake", {}), active_task=p.get("active_task"))
