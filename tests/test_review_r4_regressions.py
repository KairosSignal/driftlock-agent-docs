"""R4 fixed-SHA findings: negative report tokens and unified lineage gates."""
import pathlib
import sys
import unittest
from unittest.mock import patch

HERE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
from driftlock_next.audit import context_check,task_check
from driftlock_next.common import GovernanceError
from test_review_r2_hardening import IsolatedR2

class R4Gates(unittest.TestCase):
    setUp=IsolatedR2.setUp
    tearDown=IsolatedR2.tearDown
    git=IsolatedR2.git
    write=IsolatedR2.write
    problem_close=IsolatedR2.problem_close

    def _committed_review(self,suffix):
        p=self.root/"reports/review.md"
        p.write_text(p.read_text()+suffix)
        self.git("add","reports/review.md")
        self.git("commit","-qm","independent report fixture")

    def test_negative_body_variants_never_close_problem(self):
        negatives=(
            "Final review status: FAIL",
            "Final verdict — FAIL",
            "## FINAL verdict\n\nFAIL",
            "The candidate was not independently\nverified.",
            "Verdict: REJECTED",
            "Outcome: BLOCKED",
            "本次审核未通过",
            "Review was FAILED",
            "Verdict: PASS; final: FAIL",
            "R2 failed; latest PASS metadata",
        )
        for body in negatives:
            with self.subTest(body=body):
                # A committed report remains an authentic source but may still
                # be contradictory; commit+task match alone is not sufficient.
                self._committed_review("\n"+body+"\n")
                board=self.root/"current/PROBLEM_REGISTER.md"
                baseline=board.read_bytes()
                with self.assertRaises(GovernanceError) as error:
                    self.problem_close()
                self.assertEqual(error.exception.code,"RESOLUTION_CONTRADICTORY_REPORT")
                self.assertEqual(board.read_bytes(),baseline)
                # Restore the review to a clean outcome before next variant.
                self.git("show","HEAD:reports/review.md")
                source=(
                    "---\ntask_id: TASK-200\nverdict: PASS\nreview_status: accepted\n"
                    "candidate_commit: "+("a"*40)+"\n---\n# Review outcome\n")
                (self.root/"reports/review.md").write_text(source)
                self.git("add","reports/review.md")
                self.git("commit","-qm","reset clean acceptance report")

    def test_positive_acceptance_closes(self):
        self.assertEqual(self.problem_close()["current"],"resolved")

    def _rework(self,child_id,parent_id,parent_owner):
        self.write("tasks/task.md","---\ntask_id: "+child_id+"\n"
                   "current_project: amazon_agent\ntask_contract_version: 2\n"
                   "status: in_progress\nreview_status: pending\n"
                   "rework_of: "+parent_id+"\nmerge_allowed: false\n"
                   "deploy_allowed: false\n---\n")
        if parent_owner:
            self.write("tasks/predecessor.md","---\ntask_id: "+parent_id+"\n"
                       "current_project: "+parent_owner+"\nstatus: rework_required\n---\n")

    def test_owner_mismatch_is_hard_in_both_readers(self):
        from driftlock_next import audit
        self._rework("AMZ-TASK-00001-R1","AMZ-TASK-00001","intelligence")
        scan=task_check(self.root,"governance")
        self.assertTrue(scan["blocking"])
        self.assertTrue(any(c["code"]=="rework_predecessor_owner_mismatch"
                            for c in scan["contradictory_statuses"]))
        with patch.object(audit,"git_snapshot",return_value={"state":"ok"}):
            current=context_check(self.root,"governance")
        self.assertEqual(current["state"],"blocked")
        self.assertIn("rework_predecessor_owner_mismatch",current["governance_blocking"])

    def test_unique_same_owner_is_clear_in_both_readers(self):
        from driftlock_next import audit
        self._rework("AMZ-TASK-00001-R1","AMZ-TASK-00001","amazon_agent")
        scanned=task_check(self.root,"governance")
        self.assertFalse(scanned["blocking"],scanned["contradictory_statuses"])
        with patch.object(audit,"git_snapshot",return_value={"state":"ok"}):
            current=context_check(self.root,"governance")
        self.assertEqual(current["state"],"ok")

    def test_correct_name_missing_r10_parent_blocks_both(self):
        from driftlock_next import audit
        self._rework("AMZ-TASK-00001-R10","AMZ-TASK-00001-R9",None)
        scan=task_check(self.root,"governance")
        self.assertTrue(scan["blocking"])
        with patch.object(audit,"git_snapshot",return_value={"state":"ok"}):
            current=context_check(self.root,"governance")
        self.assertEqual(current["state"],"blocked")
        self.assertIn("rework_predecessor_missing",current["governance_blocking"])

    def test_legacy_undeclared_predecessor_remains_warning_only(self):
        from driftlock_next import audit
        self.write("tasks/task.md","---\ntask_id: TASK-171-R7\n"
                   "current_project: amazon_agent\nstatus: rework_required\nreview_status: fail\n---\n")
        scan=task_check(self.root,"governance")
        self.assertFalse(scan["blocking"])
        self.assertTrue(any(w["code"]=="rework_predecessor_mismatch"
                            for w in scan["review_warnings"]))
        with patch.object(audit,"git_snapshot",return_value={"state":"ok"}):
            current=context_check(self.root,"governance")
        self.assertEqual(current["state"],"ok")
        self.assertIn("rework_predecessor_mismatch",current["cautions"])

if __name__=="__main__":unittest.main()
