"""Strict Problem closure attestation protocol; no markdown verdict parser."""
import unittest
from driftlock_next.common import GovernanceError
from test_review_r4_regressions import R4Gates

class R5AttestationTests(unittest.TestCase):
    setUp=R4Gates.setUp
    tearDown=R4Gates.tearDown
    git=R4Gates.git
    write=R4Gates.write
    problem_close=R4Gates.problem_close
    _committed_review=R4Gates._committed_review

    def test_markdown_emphasis_unicode_and_split_negative_all_denied(self):
        examples=(
            "## FINAL verdict\n\n_FAIL_",
            "## FINAL verdict\n\n__FAIL__",
            "## FINAL verdict\n\n**FAIL**",
            "Final verdict — FAIL",
            "Final review status: FAIL",
            "Review outcome: not approved",
            "Review outcome\n\nFAIL",
            "审核：未通过",
            "验收失败",
            "Rejected as unsafe",
            "# Outcome\n\nPENDING",
            "Final decision: Unknown",
            "The reviewer found historical failures, now PASS",
            "Unrelated body prose without a machine outcome",
            "| status | value |\n|---|---|\n| verdict | PASS |",
        )
        for body in examples:
            with self.subTest(body=body):
                self._committed_review("\n"+body+"\n")
                before=(self.root/"current/PROBLEM_REGISTER.md").read_bytes()
                with self.assertRaises(GovernanceError) as caught:
                    self.problem_close()
                self.assertEqual(caught.exception.code,"RESOLUTION_CONTRADICTORY_REPORT")
                self.assertEqual((self.root/"current/PROBLEM_REGISTER.md").read_bytes(),before)
                cleaned=(
                    "---\ntask_id: TASK-200\nverdict: PASS\nreview_status: accepted\n"
                    "candidate_commit: "+("a"*40)+"\n---\n# Review outcome\n")
                (self.root/"reports/review.md").write_text(cleaned)
                self.git("add","reports/review.md")
                self.git("commit","-qm","restore bounded attestation")

    def test_clean_positive_attestation_closes_problem(self):
        self.assertEqual(self.problem_close()["current"],"resolved")

    def test_unknown_metadata_field_requires_protocol_update(self):
        report=self.root/"reports/review.md"
        report.write_text(report.read_text().replace("verdict: PASS",
                           "notes: This is a rich report\nverdict: PASS"))
        self.git("add","reports/review.md")
        self.git("commit","-qm","unknown metadata")
        with self.assertRaises(GovernanceError) as error:
            self.problem_close()
        self.assertEqual(error.exception.code,"RESOLUTION_REPORT_STRUCTURE")

    def test_canonical_attestation_heading_is_accepted(self):
        report=self.root/"reports/review.md"
        report.write_text(report.read_text().replace("# Review outcome",
                                                  "# Independent acceptance attestation"))
        self.git("add","reports/review.md")
        self.git("commit","-qm","valid attestation title")
        self.assertEqual(self.problem_close()["current"],"resolved")

if __name__=="__main__":unittest.main()
