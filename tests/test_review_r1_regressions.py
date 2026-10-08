"""Adversarial regressions from the independent 2026-10-08 Sol review."""
import builtins
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

BASE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE))
from driftlock_next.common import GovernanceError,sha
from driftlock_next.problems import transition as problem_transition
from driftlock_next.plans import transition as plan_transition,validate as plan_validate
from driftlock_next.audit import context_check,doctor,task_check,plan_list
from driftlock_next.allocator import reserve,inspect
from driftlock_next.skill_install import status as install_status

class IndependentReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=pathlib.Path(self.tmp.name)/"company"
        self.root.mkdir()
        self.git("init","-q")
        self.git("config","user.name","Review Fixture")
        self.git("config","user.email","review@example.test")
        self.put(".driftlock/projects.json",json.dumps({"schema_version":1,"projects":[
          {"id":"governance","remote_policy":"local_only","task_prefix":"GOV",
           "task_allocator":"local_serialized",
           "intake":{"problem":"current/PROBLEM_REGISTER.md"}},
          {"id":"amazon_agent","task_prefix":"AMZ","remote_policy":"local_only",
           "active_task":"tasks/task184.md"},
          {"id":"brand_intelligence","task_prefix":"BI","remote_policy":"local_only"}]}))
        self.put("CURRENT_HANDOFF.md","---\ntask_path: tasks/task184.md\n---\n")
        self.put("tasks/task184.md","---\ntask_id: TASK-184\ncurrent_project: amazon_agent\nstatus: planned\nreview_status: not_started\nmerge_allowed: false\ndeploy_allowed: false\ncandidate_state: none\n---\n")
        self.put("tasks/task200.md","---\ntask_id: TASK-200\ncurrent_project: amazon_agent\nstatus: closed\nreview_status: pass\ncandidate_commit: "+("a"*40)+"\n---\n")
        self.put("planning/brand.md","---\nplan_id: PLAN-BI-001\nproject_id: brand_intelligence\nstatus: parked\ndepends_on: []\nsupersedes: []\n---\n")
        self.put("planning/gov.md","---\nplan_id: PLAN-GOV-001\nproject_id: governance\nstatus: approved\ndepends_on: []\nsupersedes: []\n---\n")
        self.put("current/PROBLEM_REGISTER.md",
          "# register\n| ID | state | description | task | gate |\n| --- | --- | --- | --- | --- |\n"
          "| PROBLEM-003 | in_task | Navigation wrong | TASK-200 Gate 3 | acceptance check |\n")
        self.put("reports/accepted.md","---\ntask_id: TASK-200\nverdict: PASS\nreview_status: accepted\ncandidate_commit: "+("a"*40)+"\n---\n# Independent review\n")
        self.git("add",".")
        self.git("commit","-qm","baseline")
    def tearDown(self): self.tmp.cleanup()
    def git(self,*args):
        p=subprocess.run(["git","-C",str(self.root),*args],text=True,capture_output=True)
        if p.returncode:raise AssertionError(p.stderr)
        return p.stdout
    def put(self,relative,body):
        p=self.root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
        return p
    def test_f1_only_exact_committed_structured_review(self):
        source=self.root/"current/PROBLEM_REGISTER.md"
        checks=[
          ("TASK-200\nVerdict: FAIL\nThe PASS criterion was not met","RESOLUTION_NOT_VERIFIED"),
          ("TASK-200\nnot verified and not accepted","RESOLUTION_NOT_VERIFIED"),
          ("TASK-2000\nVerdict: PASS","RESOLUTION_NOT_VERIFIED"),
        ]
        for i,(body,_) in enumerate(checks):
            dest=self.put(f"reports/rejected-{i}.md",body)
            self.git("add",str(dest.relative_to(self.root)))
            self.git("commit","-qm","negative fixture")
            with self.subTest(i=i),self.assertRaises(GovernanceError):
                problem_transition(self.root,"governance","PROBLEM-003","resolved",
                      sha(source.read_text()),"TASK-200",f"reports/rejected-{i}.md",True)
        accepted=problem_transition(self.root,"governance","PROBLEM-003","resolved",
                    sha(source.read_text()),"TASK-200","reports/accepted.md",True)
        self.assertEqual(accepted["current"],"resolved")
        self.assertIn("TASK-200 Gate 3",source.read_text())
    def test_f2_doctor_does_not_execute_arbitrary_handoff(self):
        p=self.put("tools/handoff.py","from pathlib import Path\nPath('DANGER').write_text('x')\n")
        data=doctor(self.root,"governance")
        self.assertEqual(data["checks"]["existing_handoff"]["status"],"not_executed")
        self.assertFalse((self.root/"DANGER").exists())
    def test_f3_plan_and_task_ownership(self):
        result=context_check(self.root,"brand_intelligence")
        self.assertEqual(result["state"],"unconfigured")
        self.assertEqual(context_check(self.root,"amazon_agent")["task_id"],"TASK-184")
        self.assertEqual(plan_list(self.root,"amazon_agent")["count"],0)
        plan=self.root/"planning/brand.md"
        for who in ("amazon_agent","governance"):
            with self.subTest(who=who),self.assertRaises(GovernanceError):
                plan_transition(self.root,who,"PLAN-BI-001","draft",sha(plan.read_text()),None,True)
        self.assertEqual(plan_transition(self.root,"brand_intelligence","PLAN-BI-001","draft",
                            sha(plan.read_text()),None,True)["status"],"draft")
    def test_f4_permissions_fail_closed_even_when_git_snapshot_ok(self):
        from driftlock_next import audit
        p=self.root/"tasks/task184.md"
        p.write_text(p.read_text().replace("review_status: not_started","review_status: fail")
                     .replace("merge_allowed: false","merge_allowed: true")
                     .replace("deploy_allowed: false","deploy_allowed: true")
                     .replace("candidate_state: none","candidate_state: superseded"))
        with patch.object(audit,"git_snapshot",return_value={"state":"ok","blocking":[]}):
            result=context_check(self.root,"amazon_agent")
        self.assertEqual(result["state"],"blocked")
        self.assertIn("failed_review_release_permissions",result["governance_blocking"])
    def test_f4_new_contract_closed_review_pending_blocks(self):
        self.put("tasks/new.md","---\ntask_id: GOV-TASK-00001\ncurrent_project: governance\n"
                 "task_contract_version: 2\nstatus: closed\nreview_status: pending\n---\n")
        self.assertTrue(task_check(self.root,"governance")["blocking"])
    def test_f5_preserve_gate_and_other_task_context(self):
        doc=self.root/"current/PROBLEM_REGISTER.md"
        result=problem_transition(self.root,"governance","PROBLEM-003","in_task",
                    sha(doc.read_text()),"TASK-200",None,True)
        self.assertFalse(" (ref)" in doc.read_text())
        self.assertIn("TASK-200 Gate 3",doc.read_text())
    def test_f6_scan_existing_id_in_another_worktree(self):
        sibling=self.root.parent/"sibling"
        self.git("worktree","add","-qb","work/review",str(sibling))
        p=sibling/"tasks/extra.md";p.write_text("---\ntask_id: GOV-TASK-00001\ncurrent_project: governance\n---\n")
        result=reserve(self.root,"governance",sha(""),True)
        self.assertEqual(result["task_id"],"GOV-TASK-00002")
    def test_f7_symlink_parent_directory_is_rejected(self):
        shared=pathlib.Path(self.git("rev-parse","--git-common-dir").strip())
        if not shared.is_absolute():shared=self.root/shared
        base=shared/"driftlock-governance"
        external=self.root.parent/"outside";external.mkdir()
        if base.exists():self.skipTest("ledger dir exists")
        base.symlink_to(external,target_is_directory=True)
        with self.assertRaises(GovernanceError) as problem:
            reserve(self.root,"governance",sha(""),True)
        self.assertEqual(problem.exception.code,"UNSAFE_LEDGER_DIR")
        self.assertEqual(list(external.iterdir()),[])
    def test_f8_superseded_plan_requires_real_successor(self):
        f=self.root/"planning/gov.md"
        with self.assertRaises(GovernanceError) as bad:
            plan_transition(self.root,"governance","PLAN-GOV-001","superseded",
                             sha(f.read_text()),"ADR:approved replacement",True)
        self.assertEqual(bad.exception.code,"PLAN_GRAPH_INVALID_AFTER_TRANSITION")
        self.assertEqual(plan_validate(self.root,"governance")["state"],"ok")
    def test_f9_portable_import_when_fcntl_absent(self):
        original=builtins.__import__
        def blocked(name,*args,**kwargs):
            if name=="fcntl":raise ModuleNotFoundError("No module named fcntl")
            return original(name,*args,**kwargs)
        with patch("builtins.__import__",side_effect=blocked):
            import driftlock_next.cli
            import driftlock_next.atomic
            import driftlock_next.intake
            import driftlock_next.allocator
    def test_f10_incomplete_install_cannot_match(self):
        destination=self.root/"partial"
        self.put("partial/SKILL.md",(BASE/"SKILL.md").read_text())
        self.put("partial/scripts/driftlock.py",(BASE/"scripts/driftlock.py").read_text())
        answer=install_status(BASE,destination)
        self.assertFalse(answer["installed_matches_source"])
        self.assertTrue(any(x.startswith("driftlock_next/") for x in answer["missing"]))
    def test_medium_invalid_metadata_reports_guarded_error(self):
        f=self.put("planning/invalid.md","---\nplan_id: PLAN-GOV-002\nproject_id: governance\nstatus: draft\ndepends_on: true\n---\n")
        with self.assertRaises(GovernanceError) as err:plan_validate(self.root,"governance")
        self.assertEqual(err.exception.code,"INVALID_PLAN_LINKS")

if __name__=="__main__":unittest.main()

class BranchOnlyReservationTests(IndependentReviewRegressions):
    def test_branch_not_checked_out_still_reserves_unique_id(self):
        original=self.git("branch","--show-current").strip()
        self.git("checkout","-qb","work/abandoned-task")
        f=self.put("tasks/other-branch.md","---\ntask_id: GOV-TASK-00003\ncurrent_project: governance\n---\n")
        self.git("add","tasks/other-branch.md")
        self.git("commit","-qm","unmerged historical task")
        self.git("checkout","-q",original)
        allocation=reserve(self.root,"governance",sha(""),True)
        self.assertEqual(allocation["task_id"],"GOV-TASK-00004")

class LegacyTaskIdentityTests(IndependentReviewRegressions):
    def test_legacy_task_ids_remain_readable_without_auto_renaming(self):
        for i, ident in enumerate(("TASK-025A","TASK-158-C1","TASK-DOCS-2026-07-25")):
            self.put(f"tasks/legacy-{i}.md",
                     "---\ntask_id: "+ident+"\ncurrent_project: amazon_agent\nstatus: closed\nreview_status: not_started\n---\n")
        result=task_check(self.root,"governance")
        self.assertFalse(result["blocking"], result["contradictory_statuses"])
        self.assertTrue(any(w["code"]=="LEGACY_ID_FORMAT" for w in result["review_warnings"]))

class ReviewClosureGuardTests(IndependentReviewRegressions):
    def test_accepted_candidate_missing_sha_is_blocked(self):
        from driftlock_next import audit
        self.put("tasks/task184.md","---\ntask_id: TASK-184\ncurrent_project: amazon_agent\n"
                 "task_contract_version: 2\nstatus: accepted_pending_integration\n"
                 "review_status: pass\ncandidate_state: frozen\ncandidate_commit: null\n"
                 "merge_allowed: false\ndeploy_allowed: false\n---\n")
        with patch.object(audit,"git_snapshot",return_value={"state":"ok","blocking":[]}):
            r=context_check(self.root,"amazon_agent")
        self.assertEqual(r["state"],"blocked")
        self.assertIn("accepted_candidate_commit_missing",r["governance_blocking"])

class TrustBoundaryTests(IndependentReviewRegressions):
    def test_doctor_never_executes_supplied_external_script(self):
        external=self.put("unsafe_checker.py","from pathlib import Path\nPath('WRITTEN').write_text('bad')\n")
        with self.assertRaises(GovernanceError) as seen:
            doctor(self.root,"governance",external)
        self.assertEqual(seen.exception.code,"UNTRUSTED_CHECKER")
        self.assertFalse((self.root/"WRITTEN").exists())
