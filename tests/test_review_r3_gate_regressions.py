"""Narrow negative tests for independent Sol R3 H1/H2/H3 + document-state gap."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from driftlock_next.common import GovernanceError,git as guarded_git,sha
from driftlock_next.audit import context_check,doctor
from driftlock_next.problems import transition as problem_transition
from test_review_r2_hardening import IsolatedR2

class R3FocusedTests(unittest.TestCase):
    # Share the fixture but do not inherit its test methods.
    setUp=IsolatedR2.setUp
    tearDown=IsolatedR2.tearDown
    git=IsolatedR2.git
    write=IsolatedR2.write
    problem_close=IsolatedR2.problem_close

    def test_multiline_final_fail_report_blocks_closure(self):
        report=self.root/"reports/review.md"
        report.write_text(report.read_text()+"\n## FINAL verdict\n\nFAIL\n")
        self.git("add","reports/review.md")
        self.git("commit","-qm","negative reviewer")
        with self.assertRaises(GovernanceError) as err:self.problem_close()
        self.assertEqual(err.exception.code,"RESOLUTION_CONTRADICTORY_REPORT")

    def test_multiline_negative_verification_blocks_closure(self):
        report=self.root/"reports/review.md"
        report.write_text(report.read_text()+"\nThis candidate was not independently\nverified.\n")
        self.git("add","reports/review.md")
        self.git("commit","-qm","unverified reviewer")
        with self.assertRaises(GovernanceError) as err:self.problem_close()
        self.assertEqual(err.exception.code,"RESOLUTION_CONTRADICTORY_REPORT")

    def test_r1_predecessor_missing_blocks_live_context(self):
        from driftlock_next import audit
        self.write("tasks/task.md","---\ntask_id: AMZ-TASK-00001-R1\n"
                   "current_project: amazon_agent\ntask_contract_version: 2\n"
                   "status: in_progress\nreview_status: pending\n"
                   "rework_of: AMZ-TASK-00001\nmerge_allowed: false\n"
                   "deploy_allowed: false\n---\n")
        with patch.object(audit,"git_snapshot",return_value={"state":"ok"}):
            result=context_check(self.root,"amazon_agent")
        self.assertEqual(result["state"],"blocked")
        self.assertIn("rework_predecessor_missing",result["governance_blocking"])

    def test_r10_predecessor_missing_blocks_live_context(self):
        from driftlock_next import audit
        self.write("tasks/task.md","---\ntask_id: AMZ-TASK-00001-R10\n"
                   "current_project: amazon_agent\ntask_contract_version: 2\n"
                   "status: in_progress\nreview_status: pending\n"
                   "rework_of: AMZ-TASK-00001-R9\nmerge_allowed: false\n"
                   "deploy_allowed: false\n---\n")
        with patch.object(audit,"git_snapshot",return_value={"state":"ok"}):
            result=context_check(self.root,"amazon_agent")
        self.assertEqual(result["state"],"blocked")
        self.assertIn("rework_predecessor_missing",result["governance_blocking"])

    def test_existing_unique_same_project_predecessor_is_ok(self):
        from driftlock_next import audit
        self.write("tasks/task.md","---\ntask_id: AMZ-TASK-00001-R1\n"
                   "current_project: amazon_agent\ntask_contract_version: 2\n"
                   "status: in_progress\nreview_status: pending\n"
                   "rework_of: AMZ-TASK-00001\nmerge_allowed: false\n"
                   "deploy_allowed: false\n---\n")
        self.write("tasks/predecessor.md","---\ntask_id: AMZ-TASK-00001\n"
                   "current_project: amazon_agent\nstatus: rework_required\n---\n")
        with patch.object(audit,"git_snapshot",return_value={"state":"ok"}):
            result=context_check(self.root,"amazon_agent")
        self.assertEqual(result["state"],"ok",result["governance_blocking"])

    def test_wrong_predecessor_project_is_rejected(self):
        from driftlock_next import audit
        self.write("tasks/task.md","---\ntask_id: AMZ-TASK-00001-R1\n"
                   "current_project: amazon_agent\ntask_contract_version: 2\n"
                   "status: in_progress\nreview_status: pending\n"
                   "rework_of: AMZ-TASK-00001\n---\n")
        self.write("tasks/predecessor.md","---\ntask_id: AMZ-TASK-00001\n"
                   "current_project: intelligence\nstatus: rework_required\n---\n")
        with patch.object(audit,"git_snapshot",return_value={"state":"ok"}):
            result=context_check(self.root,"amazon_agent")
        self.assertEqual(result["state"],"blocked")

    def test_malformed_document_state_is_not_doctor_ok(self):
        from driftlock_next import audit
        original=audit.subprocess.run
        script=ROOT/"scripts/driftlock.py"
        for data in (
            {"schema_version":2,"command":"check","results":[{"state":"BLOCKED"}],"blocking_errors":[]},
            {"schema_version":2,"command":"check","results":[{"state":"CURRENT"}],"blocking_errors":[]},
        ):
            def wrapped(argv,*args,**kwargs):
                if isinstance(argv,list) and argv[:2]==[sys.executable,str(script)]:
                    return SimpleNamespace(stdout=json.dumps(data),stderr="",returncode=1)
                return original(argv,*args,**kwargs)
            with self.subTest(data=data),patch.object(audit.subprocess,"run",side_effect=wrapped):
                got=doctor(self.root,"governance",script)
            self.assertEqual(got["state"],"blocked")
            self.assertTrue(got["checks"]["documents"]["blocking"])

    def test_git_readers_disable_config_driven_fsmonitor(self):
        from driftlock_next import common
        calls=[]
        def fake(cmd,**kwargs):
            calls.append((cmd,kwargs))
            return SimpleNamespace(returncode=0,stdout="",stderr="")
        with patch.object(common.subprocess,"run",side_effect=fake):
            guarded_git(self.root,"status","--porcelain",check=False)
        cmd,opts=calls[0]
        self.assertIn("--no-optional-locks",cmd)
        self.assertIn("core.fsmonitor=false",cmd)
        self.assertEqual(opts["env"]["GIT_OPTIONAL_LOCKS"],"0")
        self.assertEqual(opts["env"]["GIT_CONFIG_KEY_0"],"core.fsmonitor")
        self.assertEqual(opts["env"]["GIT_CONFIG_VALUE_0"],"false")

    def test_legacy_checker_git_reader_uses_same_security_options(self):
        filename=ROOT/"scripts/driftlock.py"
        spec=importlib.util.spec_from_file_location("r3_driftlock_legacy",filename)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        seen=[]
        def stub(cmd,**kwargs):
            seen.append((cmd,kwargs))
            return SimpleNamespace(returncode=0,stdout="",stderr="")
        with patch.object(module.subprocess,"run",side_effect=stub):
            module.run_git(self.root,"status","--porcelain")
        cmd,args=seen[0]
        self.assertIn("core.fsmonitor=false",cmd)
        self.assertIn("--no-optional-locks",cmd)
        self.assertEqual(args["env"]["GIT_OPTIONAL_LOCKS"],"0")
        self.assertEqual(args["env"]["GIT_CONFIG_VALUE_0"],"false")

    def test_doctor_child_inherits_safe_git_configuration(self):
        from driftlock_next import audit
        source=audit.subprocess.run
        script=ROOT/"scripts/driftlock.py"
        seen=[]
        data={"schema_version":2,"command":"check","blocking_errors":[],
              "results":[{"state":"UNVERIFIED"}]}
        def stub(cmd,*args,**kwargs):
            if isinstance(cmd,list) and cmd[:2]==[sys.executable,str(script)]:
                seen.append(kwargs.get("env"))
                return SimpleNamespace(returncode=1,stdout=json.dumps(data),stderr="")
            return source(cmd,*args,**kwargs)
        with patch.object(audit.subprocess,"run",side_effect=stub):
            result=doctor(self.root,"governance",script)
        self.assertEqual(result["checks"]["documents"]["exit_code"],1)
        self.assertFalse(result["checks"]["documents"]["blocking"])
        self.assertEqual(seen[0]["GIT_OPTIONAL_LOCKS"],"0")
        self.assertEqual(seen[0]["GIT_CONFIG_VALUE_0"],"false")

if __name__=="__main__":unittest.main()
