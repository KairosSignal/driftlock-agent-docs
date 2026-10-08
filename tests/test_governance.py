"""Safety and compatibility regression tests for optional governance features."""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "scripts" / "driftlock.py"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from driftlock_next.audit import git_snapshot, task_check
from driftlock_next.common import GovernanceError, sha
from driftlock_next.intake import propose, record
from driftlock_next.registry import load, select

class GovernanceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        self.write("PROJECT_MAP.md", "# Project\n")
        self.write("tasks/TASK-171-R8-success.md", "---\ntask_id: TASK-171-R8\nstatus: accepted_pending_integration\nreview_status: pass\nrework_of: TASK-171-R7\n---\n")
        self.write("tasks/TASK-171-R7-old.md", "---\ntask_id: TASK-171-R7\nstatus: rework_required\nreview_status: fail\n---\n")
        self.write("tasks/TASK-042F2C-long-form.md", "# Historic legacy task\n")
        self.write("tasks/TASK-042F2D-next.md", "# Historic legacy task\n")
        self.write("planning/older.md", "# Old plan\n")
        self.write("CURRENT_HANDOFF.md", "---\nhandoff_schema: 1\ntask_path: tasks/TASK-171-R8-success.md\n---\n")
        self.write(".driftlock/projects.json", json.dumps({
            "schema_version": 1, "projects": [
                {"id": "company", "name": "Company Control", "root": ".", "task_prefix": "GOV",
                 "tasks": "tasks", "planning": "planning", "remote_policy": "local_only",
                 "handoff": "CURRENT_HANDOFF.md",
                 "intake": {"problem": "current/PROBLEM_REGISTER.md", "idea": "planning/IDEA_INBOX.md"}}
            ]}, ensure_ascii=False))
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        p = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        if p.returncode:
            raise AssertionError(p.stderr)
        return p.stdout

    def write(self, name, content):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def call(self, *args):
        return subprocess.run([sys.executable, str(CLI), *args, str(self.root), "--format", "json"],
                              capture_output=True, text=True)

    def test_multi_project_selection_and_unique_prefixes(self):
        p = load(self.root)
        self.assertEqual(p["projects"][0]["id"], "company")
        self.assertEqual(select(self.root, "company")["task_prefix"], "GOV")
        config = self.root / ".driftlock" / "projects.json"
        data = json.loads(config.read_text())
        data["projects"].append({"id": "amazon", "root": ".", "task_prefix": "GOV"})
        config.write_text(json.dumps(data))
        with self.assertRaises(GovernanceError) as ctx:
            load(self.root)
        self.assertEqual(ctx.exception.code, "REGISTRY_PREFIX")

    def test_registry_rejects_unsafe_paths(self):
        p = self.root / ".driftlock" / "projects.json"
        data = json.loads(p.read_text())
        data["projects"][0]["intake"]["problem"] = "../../outside.md"
        p.write_text(json.dumps(data))
        with self.assertRaises(GovernanceError):
            load(self.root)

    def test_propose_does_not_mutate_execution_or_repository(self):
        before = self.git("status", "--porcelain")
        result = propose(self.root, "company", "这个价格曲线不对", "observation")
        self.assertFalse(result["persisted"])
        self.assertFalse(result["execution_context_changed"])
        self.assertEqual(before, self.git("status", "--porcelain"))

    def test_propose_unknown_intent_refuses_guess(self):
        data = propose(self.root, "company", "先看看是不是这个原因")
        self.assertEqual(data["category"], "needs_clarification")
        self.assertIsNone(data["candidate_intake"])

    def test_record_requires_explicit_approval(self):
        with self.assertRaises(GovernanceError) as ctx:
            record(self.root, "company", "problem", "bug", "PROB-0001", sha(""), "chat", False)
        self.assertEqual(ctx.exception.code, "INTAKE_APPROVAL_REQUIRED")
        self.assertFalse((self.root / "current" / "PROBLEM_REGISTER.md").exists())

    def test_record_version_conflict_and_exact_replay(self):
        with self.assertRaises(GovernanceError) as ctx:
            record(self.root, "company", "idea", "加一个品牌库", "IDEA-0001", "bad", "chat", True)
        self.assertEqual(ctx.exception.code, "INTAKE_VERSION_CONFLICT")
        r = record(self.root, "company", "idea", "加一个品牌库", "IDEA-0001", sha(""), "chat", True)
        self.assertTrue(r["persisted"])
        self.assertFalse(r["replay"])
        rerun = record(self.root, "company", "idea", "加一个品牌库", "IDEA-0001", sha(""), "chat", True)
        self.assertTrue(rerun["replay"])
        with self.assertRaises(GovernanceError) as ctx:
            record(self.root, "company", "idea", "另一项想法", "IDEA-0001", sha(""), "chat", True)
        self.assertEqual(ctx.exception.code, "INTAKE_ID_CONFLICT")
        self.assertIn("加一个品牌库", (self.root / "planning/IDEA_INBOX.md").read_text())

    def test_record_cannot_write_unmapped_task(self):
        with self.assertRaises(GovernanceError) as ctx:
            record(self.root, "company", "task", "现在开工", "TASK-999", sha(""), "chat", True)
        self.assertEqual(ctx.exception.code, "INTAKE_KIND")

    def test_record_preserves_source_as_unverified(self):
        r = record(self.root, "company", "problem", "用户说有 BUG", "P-001", sha(""), "chat:1", True)
        content = Path(r["path"]).read_text()
        self.assertIn("captured_unverified", content)
        self.assertIn("> 用户说有 BUG", content)
        self.assertFalse(r["task_created"])

    def test_explicit_local_only_and_remote_strictness(self):
        local = git_snapshot(self.root, policy="local_only")
        self.assertEqual(local["state"], "ok")
        self.assertIn("upstream_not_required_local_only", local["information"])
        remote = git_snapshot(self.root, policy="remote_tracked")
        self.assertEqual(remote["state"], "blocked")
        self.assertIn("upstream_missing", remote["blocking"])

    def test_git_candidate_branch_and_dirty_worktree(self):
        wrong = git_snapshot(self.root, policy="local_only", expected_branch="work/missing",
                             candidate="0"*40)
        self.assertIn("unexpected_branch", wrong["blocking"])
        self.assertIn("candidate_missing", wrong["blocking"])
        self.write("dirty.txt", "dirty")
        self.assertIn("dirty_worktree", git_snapshot(self.root)["blocking"])

    def test_legacy_tasknames_do_not_fabricate_duplicate_ids(self):
        data = task_check(self.root, "company")
        self.assertEqual(data["duplicate_ids"], {})
        self.assertEqual(data["legacy_missing_task_id"]["count"], 2)
        self.assertFalse(data["blocking"])

    def test_cli_commands_and_read_only_check(self):
        for args in (("project", "list"), ("project", "status", "--project", "company"),
                     ("context", "check", "--project", "company"),
                     ("task", "check", "--project", "company"),
                     ("plan", "list", "--project", "company"),
                     ("git", "audit", "--project", "company"),
                     ("intake", "propose", "--project", "company", "--kind", "idea", "--text", "想法")):
            cmd = [sys.executable, str(CLI), args[0], args[1], str(self.root),
                   "--format", "json", *args[2:]]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("schema_version", json.loads(result.stdout))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_cli_no_registry_fallback_without_writes(self):
        (self.root / ".driftlock" / "projects.json").unlink()
        proc = self.call("project", "list")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["mode"], "single_project_fallback")

    def test_symlinked_intake_blocked(self):
        p = self.root / "planning/IDEA_INBOX.md"
        external = self.root / "planning/other.md"
        external.write_text("untouched")
        p.symlink_to(external)
        with self.assertRaises(GovernanceError):
            record(self.root, "company", "idea", "hi", "IDEA-123", sha(""), "chat", True)
        self.assertEqual(external.read_text(), "untouched")

if __name__ == "__main__":
    unittest.main()

class MultiProjectRoutingTests(GovernanceCase):
    def test_simultaneous_project_contexts_without_switching_global_handoff(self):
        config_path = self.root / ".driftlock" / "projects.json"
        config = json.loads(config_path.read_text())
        config["projects"].append({
            "id": "intelligence", "root": ".", "task_prefix": "INT",
            "repository": "KairosSignal/amazon-agent", "remote_policy": "local_only",
            "active_task": "tasks/TASK-171-R8-success.md",
        })
        config_path.write_text(json.dumps(config))
        from driftlock_next.audit import context_check
        first = context_check(self.root, "company")
        second = context_check(self.root, "intelligence")
        self.assertEqual(first["task_id"], "TASK-171-R8")
        self.assertEqual(second["task_id"], "TASK-171-R8")
        self.assertEqual(second["active_pointer_source"], "registry.active_task")
        self.assertEqual((self.root/"CURRENT_HANDOFF.md").read_text().split("task_path: ")[1].splitlines()[0],
                         "tasks/TASK-171-R8-success.md")

    def test_active_task_rejects_path_escape(self):
        config_path = self.root / ".driftlock" / "projects.json"
        config = json.loads(config_path.read_text())
        config["projects"][0]["active_task"] = "../../private-task.md"
        config_path.write_text(json.dumps(config))
        with self.assertRaises(GovernanceError):
            load(self.root)

class DoctorAuthorityTests(GovernanceCase):
    def test_existing_handoff_block_propagates_to_doctor_exit(self):
        from driftlock_next.audit import doctor
        script = self.write("tools/handoff.py", "import sys\nprint('handoff: CONFLICT')\nsys.exit(2)\n")
        result = doctor(self.root, "company")
        self.assertEqual(result["state"], "blocked")
        self.assertEqual(result["checks"]["existing_handoff"]["exit_code"], 2)
        proc = subprocess.run([sys.executable, str(CLI), "doctor", "check",
                               str(self.root), "--project", "company", "--format", "json"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["state"], "blocked")
