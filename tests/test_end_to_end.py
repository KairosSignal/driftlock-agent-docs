"""Regression contracts for real lifecycle operations and legacy registry adapters."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from driftlock_next.common import GovernanceError, sha
from driftlock_next.problems import scan, transition as problem_transition, reconcile
from driftlock_next.plans import validate, transition as plan_transition
from driftlock_next.allocator import reserve
from driftlock_next.audit import git_audit, doctor
from driftlock_next.registry import load
CLI = BASE/"scripts"/"driftlock.py"

class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        def write(rel,content):
            path=self.root/rel
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(content)
            return path
        self.write=write
        self.git("init","-q")
        self.git("config","user.email","test@example.com")
        self.git("config","user.name","Test")
        write(".driftlock/projects.json",json.dumps({"schema_version":1,"projects":[{
           "id":"company","root":".","task_prefix":"GOV",
           "task_allocator":"local_serialized","tasks":"tasks","planning":"planning",
           "remote_policy":"local_only",
           "intake":{"problem":"current/PROBLEM_REGISTER.md",
                     "idea":"planning/IDEA_INBOX.md"}}]}))
        self.problem_text = (
            "# Existing Problem Register\n\n"
            "| ID | Status | Description | Task | Next step |\n"
            "|----|----|----|----|----|\n"
            "| PROBLEM-001 | confirmed | Price chart shows a wrong axis | no task | verify behavior |\n"
            "| PROBLEM-002 | in_task | Sidebar loses selection after navigation | TASK-200 | smoke evidence pending |\n")
        write("current/PROBLEM_REGISTER.md",self.problem_text)
        write("tasks/task-200.md","---\ntask_id: TASK-200\nstatus: closed\nreview_status: pass\n---\n")
        write("tasks/task-201.md","---\ntask_id: TASK-201\nstatus: in_progress\nreview_status: pending\n---\n")
        write("planning/alpha.md","---\nplan_id: PLAN-A01\nstatus: draft\nproject_id: company\n---\n# Alpha\n")
        write("planning/beta.md","---\nplan_id: PLAN-B01\nstatus: draft\ndepends_on: [\"PLAN-A01\"]\nproject_id: company\n---\n# Beta\n")
        self.git("add",".")
        self.git("commit","-qm","fixture")
    def tearDown(self):self.temp.cleanup()
    def git(self,*args):
        proc=subprocess.run(["git","-C",str(self.root),*args],capture_output=True,text=True)
        if proc.returncode: raise AssertionError(proc.stderr)
        return proc.stdout
    def test_existing_problem_parser_and_candidate_suggestions(self):
        data=scan(self.root,"company")
        self.assertEqual(data["count"],2)
        candidates=scan(self.root,"company",candidate="Price chart shows a wrong axis")
        self.assertEqual(candidates["candidates"][0]["id"],"PROBLEM-001")
        self.assertEqual(candidates["decision"].split(";")[0],"advisory_only")
    def test_problem_link_and_terminal_evidence(self):
        file=self.root/"current/PROBLEM_REGISTER.md"
        r=problem_transition(self.root,"company","PROBLEM-001","in_task",sha(file.read_text()),
                             task_id="TASK-201",approved=True)
        self.assertTrue(r["changed"])
        self.assertIn("TASK-201",file.read_text())
        with self.assertRaises(GovernanceError) as bad:
            problem_transition(self.root,"company","PROBLEM-001","resolved",sha(file.read_text()),
                               task_id="TASK-201",evidence="review:PASS:201",approved=True)
        self.assertEqual(bad.exception.code,"TASK_NOT_CLOSED")
        self.assertIn("in_task",file.read_text())
    def test_problem_closed_only_with_verified_evidence(self):
        file=self.root/"current/PROBLEM_REGISTER.md"
        with self.assertRaises(GovernanceError) as bad:
            problem_transition(self.root,"company","PROBLEM-002","resolved",sha(file.read_text()),
                               task_id="TASK-200",approved=True)
        self.assertEqual(bad.exception.code,"OUTCOME_EVIDENCE_REQUIRED")
        before=file.read_text()
        with self.assertRaises(GovernanceError):
            problem_transition(self.root,"company","PROBLEM-002","resolved","wronghash",
                               task_id="TASK-200",evidence="report/accepted-smoke.md",approved=True)
        self.assertEqual(file.read_text(),before)
        result=problem_transition(self.root,"company","PROBLEM-002","resolved",sha(before),
                                  task_id="TASK-200",evidence="report/accepted-smoke.md",approved=True)
        self.assertEqual(result["current"],"resolved")
        self.assertIn("Evidence: report/accepted-smoke.md",file.read_text())
        self.assertEqual(file.read_text().count("PROBLEM-002"),1)
    def test_problem_reconcile_is_read_only_and_finds_pending_close(self):
        original=self.git("status","--porcelain")
        data=reconcile(self.root,"company")
        self.assertEqual(data["linked_problems"],1)
        self.assertTrue(any(e["code"]=="TASK_CLOSED_PROBLEM_NEEDS_VERIFICATION" for e in data["issues"]))
        self.assertEqual(original,self.git("status","--porcelain"))
    def test_problem_unapproved_and_illegal_states(self):
        file=self.root/"current/PROBLEM_REGISTER.md"
        digest=sha(file.read_text())
        with self.assertRaises(GovernanceError) as bad:
            problem_transition(self.root,"company","PROBLEM-001","resolved",digest,task_id="TASK-200",
                               evidence="report/accept.md",approved=True)
        self.assertEqual(bad.exception.code,"ILLEGAL_PROBLEM_TRANSITION")
        with self.assertRaises(GovernanceError) as bad:
            problem_transition(self.root,"company","PROBLEM-001","in_task",digest,task_id="TASK-201",approved=False)
        self.assertEqual(bad.exception.code,"APPROVAL_REQUIRED")
    def test_plan_dependency_and_valid_transition(self):
        result=validate(self.root,"company")
        self.assertEqual(result["state"],"ok")
        self.assertEqual(result["formal_plans"],2)
        path=self.root/"planning/alpha.md"
        r=plan_transition(self.root,"company","PLAN-A01","under_review",sha(path.read_text()),None,True)
        self.assertEqual(r["status"],"under_review")
        r=plan_transition(self.root,"company","PLAN-A01","approved",sha(path.read_text()),
                          "ADR-001-approved-by-user",True)
        self.assertEqual(r["status"],"approved")
        self.assertIn("last_decision_evidence",path.read_text())
    def test_plan_unsafe_transition_and_cyclic_refs(self):
        path=self.root/"planning/alpha.md"
        with self.assertRaises(GovernanceError) as bad:
            plan_transition(self.root,"company","PLAN-A01","implemented",sha(path.read_text()),"report/pass",True)
        self.assertEqual(bad.exception.code,"ILLEGAL_PLAN_TRANSITION")
        path.write_text(path.read_text().replace("status: draft","status: draft\ndepends_on: [\"PLAN-B01\"]"))
        found=validate(self.root,"company")
        self.assertEqual(found["state"],"blocked")
        self.assertIn("PLAN_CYCLE",[e["code"] for e in found["issues"]])
    def test_allocator_serial_reservation_and_task_independent(self):
        reserve_path=self.root/".driftlock/task-id-reservations.json"
        a=reserve(self.root,"company",sha(""),True)
        self.assertEqual(a["task_id"],"GOV-TASK-00001")
        self.assertFalse(a["task_created"])
        with self.assertRaises(GovernanceError) as bad:
            reserve(self.root,"company",sha(""),True)
        self.assertEqual(bad.exception.code,"VERSION_CONFLICT")
        b=reserve(self.root,"company",sha(reserve_path.read_text()),True)
        self.assertEqual(b["task_id"],"GOV-TASK-00002")
        self.assertFalse((self.root/"tasks/GOV-TASK-00001.md").exists())
    def test_allocator_off_by_default_and_approval(self):
        cfg=self.root/".driftlock/projects.json"
        data=json.loads(cfg.read_text())
        data["projects"][0].pop("task_allocator")
        cfg.write_text(json.dumps(data))
        with self.assertRaises(GovernanceError) as bad:
            reserve(self.root,"company",sha(""),True)
        self.assertEqual(bad.exception.code,"ALLOCATOR_NOT_CONFIGURED")
    def test_branch_audit_counts_unique_unmerged_and_protects_active(self):
        self.git("branch","-m","master")
        self.git("checkout","-qb","work/unmerged")
        self.write("extra.txt","candidate")
        self.git("add","extra.txt")
        self.git("commit","-qm","feature")
        d=git_audit(self.root,"company")
        branch=next(x for x in d["branches"] if x["name"]=="work/unmerged")
        self.assertTrue(branch["checked_out"])
        self.assertEqual(branch["unique_commit_count"],1)
        self.assertFalse(branch["merged_into_local_mainline"])
        self.assertEqual(branch["risk"],"worktree_active")
        self.assertFalse(d["cleanup_performed"])
    def test_doctor_integrates_plan_and_problem_authorities(self):
        r=doctor(self.root,"company")
        self.assertEqual(r["checks"]["planning"]["formal_plans"],2)
        self.assertEqual(r["checks"]["problems"]["count"],2)
    def test_cli_exposes_new_actions_and_disallows_unapproved_writes(self):
        commands=[
           ["problem","candidates","--text","Price chart wrong"],
           ["problem","reconcile"],
           ["plan","validate"],
           ["git","audit"]
        ]
        for args in commands:
            cmd=[sys.executable,str(CLI),args[0],args[1],str(self.root),
                 "--project","company","--format","json",*args[2:]]
            proc=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            self.assertIn("schema_version",json.loads(proc.stdout))
        refused=subprocess.run([sys.executable,str(CLI),"task","reserve",str(self.root),
                    "--project","company","--format","json","--expected-sha",sha("")],
                    capture_output=True,text=True)
        self.assertEqual(refused.returncode,2)
        self.assertEqual(json.loads(refused.stdout)["error"]["code"],"APPROVAL_REQUIRED")

if __name__=="__main__":
    unittest.main()

class RealFormatAdoption(EndToEnd):
    def test_intake_problem_record_uses_existing_table_not_detached_block(self):
        from driftlock_next.intake import record
        path=self.root/"current/PROBLEM_REGISTER.md"
        before=path.read_text()
        result=record(self.root,"company","problem","用户发现图表按钮被遮挡",
                      "PROBLEM-023",sha(before),"chat://feedback/23",True)
        self.assertTrue(result["persisted"])
        content=path.read_text()
        self.assertIn("| PROBLEM-023 | needs_revalidation |",content)
        self.assertEqual(scan(self.root,"company")["count"],3)
        self.assertEqual(content.count("PROBLEM-023"),1)
        again=record(self.root,"company","problem","用户发现图表按钮被遮挡",
                      "PROBLEM-023",sha(before),"chat://feedback/23",True)
        self.assertTrue(again["replay"])
        with self.assertRaises(GovernanceError) as failure:
            record(self.root,"company","problem","同一编号另一条缺陷",
                   "PROBLEM-023",sha(content),"chat://feedback/24",True)
        self.assertEqual(failure.exception.code,"PROBLEM_ID_CONFLICT")
    def test_plan_trace_includes_dependency_consumers(self):
        from driftlock_next.audit import plan_list
        result=plan_list(self.root,"company","alpha.md")
        self.assertEqual(result["trace"]["plan_id"],"PLAN-A01")
        self.assertEqual(result["trace"]["consumers"],["PLAN-B01"])
    def test_skill_status_detects_old_install_without_mutating_it(self):
        from driftlock_next.skill_install import status
        installed=self.root/"old-skill"
        self.write("old-skill/SKILL.md","old")
        self.write("old-skill/scripts/driftlock.py","old")
        report=status(BASE,installed)
        self.assertFalse(report["installed_matches_source"])
        self.assertFalse(report["installation_changed"])
        self.assertEqual((installed/"SKILL.md").read_text(),"old")
    def test_plan_update_replaces_evidence_not_duplicates(self):
        f=self.root/"planning/alpha.md"
        plan_transition(self.root,"company","PLAN-A01","under_review",sha(f.read_text()),None,True)
        plan_transition(self.root,"company","PLAN-A01","approved",sha(f.read_text()),"ADR-001 approved",True)
        plan_transition(self.root,"company","PLAN-A01","active_planning",sha(f.read_text()),
                        "decision/active.md",True)
        self.assertEqual(f.read_text().count("last_decision_evidence:"),1)
