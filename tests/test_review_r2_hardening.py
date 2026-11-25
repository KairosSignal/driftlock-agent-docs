"""Real filesystem and isolated negative cases for R2's failed gates."""
from __future__ import annotations
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from driftlock_next.common import GovernanceError,sha
from driftlock_next.atomic import change
from driftlock_next.audit import context_check,doctor,task_check,git_snapshot
from driftlock_next.plans import transition as plan_transition
from driftlock_next.problems import transition as problem_transition

class IsolatedR2(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=pathlib.Path(self.tmp.name)/"test-repository"
        self.root.mkdir()
        self.git("init","-q")
        self.git("config","user.name","R2")
        self.git("config","user.email","r2@example.invalid")
        self.write(".driftlock/projects.json",json.dumps({"schema_version":1,"projects":[
            {"id":"governance","remote_policy":"local_only","intake":{"problem":"current/PROBLEM_REGISTER.md"}},
            {"id":"amazon_agent","remote_policy":"local_only","active_task":"tasks/task.md"}]}))
        self.write("CURRENT_HANDOFF.md","---\ntask_path: tasks/task.md\n---\n")
        self.write("tasks/task.md","---\ntask_id: TASK-200\ncurrent_project: amazon_agent\n"
                   "status: closed\nreview_status: pass\ncandidate_commit: "+("a"*40)+"\n---\n")
        self.write("current/PROBLEM_REGISTER.md",
           "| ID | State | Description | TASK | Gate |\n| --- | --- | --- | --- | --- |\n"
           "| PROBLEM-001 | in_task | Bad badge | TASK-200 Gate 3 | smoke pending |\n")
        self.write("reports/review.md","---\ntask_id: TASK-200\nverdict: PASS\n"
                   "review_status: accepted\ncandidate_commit: "+("a"*40)+"\n---\n"
                   "# Review outcome\n")
        self.write("planning/primary.md","---\nplan_id: PLAN-GOV-001\nproject_id: governance\n"
                   "status: approved\ndepends_on: []\nsupersedes: []\n---\n")
        self.git("add",".")
        self.git("commit","-qm","baseline")
    def tearDown(self):self.tmp.cleanup()
    def git(self,*parts):
        p=subprocess.run(["git","-C",str(self.root),*parts],text=True,capture_output=True)
        if p.returncode:raise AssertionError(p.stderr)
        return p.stdout
    def write(self,name,body):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
        return p
    def problem_close(self):
        board=self.root/"current/PROBLEM_REGISTER.md"
        return problem_transition(self.root,"governance","PROBLEM-001","resolved",
                    sha(board.read_text()),"TASK-200","reports/review.md",True)

    def test_final_fail_sentence_blocks_structured_pass(self):
        report=self.root/"reports/review.md"
        report.write_text(report.read_text()+"\n**Final Verdict**: FAIL\n")
        self.git("add","reports/review.md");self.git("commit","-qm","conflicting review")
        with self.assertRaises(GovernanceError) as caught:self.problem_close()
        self.assertEqual(caught.exception.code,"RESOLUTION_CONTRADICTORY_REPORT")

    def test_not_verified_sentence_blocks_structured_pass(self):
        report=self.root/"reports/review.md"
        report.write_text(report.read_text()+"\nThis candidate was not independently verified.\n")
        self.git("add","reports/review.md");self.git("commit","-qm","negative review")
        with self.assertRaises(GovernanceError) as caught:self.problem_close()
        self.assertEqual(caught.exception.code,"RESOLUTION_CONTRADICTORY_REPORT")

    def test_fail_closed_on_wrong_doctor_checker_payload(self):
        from driftlock_next import audit
        script=ROOT/"scripts/driftlock.py"
        samples=['{"blocking_errors":[]}', '{"schema_version":2,"command":"check","results":[true],"blocking_errors":[]}',
                 '{"schema_version":2,"command":"check","results":[],"blocking_errors":"ok"}']
        original=audit.subprocess.run
        for candidate in samples:
            def stub(argv,*args,**kwargs):
                if isinstance(argv,list) and argv[:2]==[sys.executable,str(script)]:
                    return SimpleNamespace(stdout=candidate,stderr="",returncode=1)
                return original(argv,*args,**kwargs)
            with self.subTest(candidate=candidate),patch.object(audit.subprocess,"run",side_effect=stub):
                report=doctor(self.root,"governance",script)
            self.assertEqual(report["state"],"blocked")
            self.assertTrue(report["checks"]["documents"]["blocking"])

    def test_aggregated_policy_follows_actual_task_owner(self):
        from driftlock_next import audit
        cfg=self.root/".driftlock/projects.json"
        spec=json.loads(cfg.read_text())
        spec["projects"][1]["remote_policy"]="remote_publish_required"
        cfg.write_text(json.dumps(spec))
        policies=[]
        def snapshot(repo,**kwargs):
            policies.append(kwargs["policy"])
            return {"state":"blocked" if kwargs["policy"]=="remote_publish_required" else "ok"}
        with patch.object(audit,"git_snapshot",side_effect=snapshot):
            report=context_check(self.root,"governance")
        self.assertEqual(policies,["remote_publish_required"])
        self.assertEqual(report["state"],"blocked")

    def test_invalid_head_policy_blocks_even_if_no_candidate(self):
        from driftlock_next import audit
        result=git_snapshot(self.root,policy="local_only",head_policy="ignored")
        self.assertEqual(result["state"],"blocked")
        self.assertIn("candidate_head_policy_invalid",result["blocking"])

    def test_boolean_candidate_fails_structured_not_traceback(self):
        meta=self.root/"tasks/task.md"
        meta.write_text(meta.read_text().replace("candidate_commit: "+"a"*40,"candidate_commit: true"))
        output=context_check(self.root,"amazon_agent")
        self.assertEqual(output["state"],"blocked")
        self.assertIn("invalid_candidate_commit_type_or_sha",output["git"]["blocking"])

    def test_empty_new_task_id_does_not_become_legacy(self):
        self.write("tasks/bad.md","---\ntask_id: false\ncurrent_project: amazon_agent\n"
                              "task_contract_version: 2\nstatus: closed\nreview_status: pass\n---\n")
        report=task_check(self.root,"amazon_agent")
        self.assertTrue(report["blocking"])

    @unittest.skipIf(os.name=="nt","POSIX anchored inode checks")
    def test_lock_hardlink_and_symlink_rejected_without_writing(self):
        source=self.root/"planning/primary.md"
        before=source.read_text()
        lock=source.parent/("."+source.name+".driftlock-write.lock")
        lock.write_text("")
        hard=self.root/"second-lock-hardlink"
        os.link(lock,hard)
        with self.assertRaises(GovernanceError):
            change(self.root,"planning/primary.md",sha(before),"new",approve=True)
        self.assertEqual(source.read_text(),before)
        hard.unlink();lock.unlink()
        outside=self.root.parent/"external-lock"
        outside.write_text("safe")
        lock.symlink_to(outside)
        with self.assertRaises(GovernanceError):
            change(self.root,"planning/primary.md",sha(before),"new",approve=True)
        self.assertEqual(outside.read_text(),"safe")
        self.assertEqual(source.read_text(),before)

    def test_plan_graph_lock_serializes_competing_updates(self):
        f=self.root/"planning/primary.md"
        digest=sha(f.read_text())
        def attempt(status):
            try:
                plan_transition(self.root,"governance","PLAN-GOV-001",status,digest,None,True)
                return "success"
            except GovernanceError as ex:
                return ex.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(attempt,("active_planning","parked")))
        self.assertEqual(results.count("success"),1)
        self.assertEqual(len(results),2)
        self.assertIn("status: "+("parked" if f.read_text().find("status: parked")!=-1 else "active_planning"),f.read_text())

if __name__=="__main__":unittest.main()
