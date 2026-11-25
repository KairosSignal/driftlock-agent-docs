import tempfile
import unittest
from pathlib import Path
import json
from driftlock_next import portfolio
from driftlock_next.common import sha, GovernanceError

class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for d in (".driftlock","planning","tasks","reports"):
            (self.root/d).mkdir()
        self.config={"schema_version":1,"projects":[
            {"id":"governance","root":".","intake":{"idea":"planning/IDEA_INBOX.md"},"task_prefix":"GOV"},
            {"id":"amazon_agent","root":".","task_prefix":"AMZ"}]}
        (self.root/".driftlock/projects.json").write_text(json.dumps(self.config))
        self.inbox=self.root/"planning/IDEA_INBOX.md"
        self.inbox.write_text("<!-- driftlock-intake:IDEA-X:"+("a"*64)+" -->\n### IDEA IDEA-X\n\nSource: chat\nStatus: captured_unverified\n\n> AMZ-TASK-00001 should be considered.\n")
    def task(self,id,status="planned",extra="",owner="amazon_agent"):
        p=self.root/"tasks"/(id+".md")
        p.write_text(f"---\ntask_id: {id}\ncurrent_project: {owner}\nstatus: {status}\nreview_status: pending\n{extra}\n---\n\nbody\n")
        return p
    def test_backlog_link_and_read_only(self):
        self.task("AMZ-TASK-00001","deployed_pending_close")
        original=self.inbox.read_text()
        data=portfolio.backlog(self.root)
        self.assertEqual(data["items"][0]["state"],"link_review_required")
        self.assertEqual(self.inbox.read_text(),original)
        with self.assertRaises(GovernanceError):
            portfolio.link_record(self.root,"governance","IDEA-X","AMZ-TASK-00001",sha(original),False)
        portfolio.link_record(self.root,"governance","IDEA-X","AMZ-TASK-00001",sha(original),True)
        self.assertEqual(portfolio.backlog(self.root)["items"][0]["state"],"deployed_review_pending")
        with self.assertRaises(GovernanceError):
            portfolio.link_record(self.root,"governance","IDEA-X","AMZ-TASK-00001",sha(original),True)
        self.assertIn("> AMZ-TASK-00001 should be considered.",self.inbox.read_text())
    def test_explicit_links_and_duplicate_record(self):
        self.task("AMZ-TASK-00001",extra="intake_ids: [IDEA-X]")
        self.assertEqual(portfolio.backlog(self.root)["items"][0]["state"],"linked_planning")
        (self.root/"tasks/copy.md").write_text((self.root/"tasks/AMZ-TASK-00001.md").read_text())
        d=portfolio.backlog(self.root)
        self.assertEqual(d["items"][0]["state"],"unlinked")
        self.assertIn("DUPLICATE_RECORD_ID",[w["code"] for w in d["warnings"]])
    def test_cycles_missing_dependencies_and_rework(self):
        self.task("AMZ-TASK-00001",extra="depends_on: [AMZ-TASK-00002]")
        self.task("AMZ-TASK-00002",extra="depends_on: [AMZ-TASK-00001, AMZ-TASK-00999]")
        self.task("AMZ-TASK-00001-R1",extra="rework_of: AMZ-TASK-00001")
        d=portfolio.dependencies(self.root)
        self.assertEqual(set(d["cycle_or_dependents"]),{"AMZ-TASK-00001","AMZ-TASK-00002"})
        self.assertEqual(d["missing"][0]["dependency"],"AMZ-TASK-00999")
        self.assertEqual(portfolio.lessons(self.root)["rework_families"][0]["rework_count"],1)
    def test_lesson_capture_ownership_and_search(self):
        self.task("AMZ-TASK-00001")
        args=("LESSON-X","db-timeout","AMZ-TASK-00001","Repeated timeout","Bound query duration","task log",sha(""))
        with self.assertRaises(GovernanceError):
            portfolio.record_lesson(self.root,"governance",*args,True)
        portfolio.record_lesson(self.root,"amazon_agent",*args,True)
        d=portfolio.lessons(self.root,"amazon_agent","timeout")
        self.assertEqual(len(d["lessons"]),1)
        self.assertEqual(d["lessons"][0]["status"],"captured_unverified")
        with self.assertRaises(GovernanceError):
            portfolio.record_lesson(self.root,"amazon_agent",*args,True)
    def test_resource_coverage_and_duplicate_scope(self):
        extra="resource_scope: run-001\ntoken_usage: 100\nduration_seconds: 5\ncost_amount: 1.25\ncost_currency: USD"
        self.task("AMZ-TASK-00001",extra=extra)
        self.task("AMZ-TASK-00002",extra=extra)
        self.task("AMZ-TASK-00003",extra=extra.replace("run-001","run-003").replace("USD","CNY"))
        d=portfolio.resources(self.root)
        self.assertEqual(d["totals"]["amazon_agent"]["costs"],{"CNY":"1.25"})
        self.assertEqual(len(d["measurements"]),1)
    def test_overview_no_invented_progress(self):
        self.task("AMZ-TASK-00001","blocked")
        d=portfolio.overview(self.root)
        self.assertEqual(d["projects"][1]["counts"],{"blocked":1})
        self.assertFalse(d["write_performed"])

    def test_parallel_collision_and_bad_dependency(self):
        self.task("AMZ-TASK-00001","in_progress","parallel_resources: [web-release]\ndepends_on: [BAD")
        self.task("AMZ-TASK-00002","in_progress","parallel_resources: [web-release]")
        d=portfolio.dependencies(self.root)
        self.assertEqual(d["resource_conflicts"][0]["resource"],"web-release")
        self.assertIn("invalid_dependency_metadata",d["tasks"][0]["unresolved"])
    def test_advice_finds_lessons_without_writes(self):
        self.task("AMZ-TASK-00001")
        portfolio.record_lesson(self.root,"amazon_agent","LESSON-X","db-timeout","AMZ-TASK-00001","Repeated timeout","Bound query duration","task log",sha(""),True)
        d=portfolio.advise(self.root,"amazon_agent","timeout")
        self.assertEqual(d["lessons"][0]["lesson_id"],"LESSON-X")
        self.assertFalse(d["write_performed"])
    def test_closed_task_never_auto_closes_intake(self):
        self.task("AMZ-TASK-00001","closed","intake_ids: [IDEA-X]\ntask_contract_version: 2\ncandidate_commit: "+"a"*40+"\ncandidate_state: frozen")
        p=self.root/"tasks/AMZ-TASK-00001.md"
        p.write_text(p.read_text().replace("review_status: pending","review_status: pass"))
        self.assertEqual(portfolio.backlog(self.root)["items"][0]["state"],"closure_review_required")
        self.assertIn("Status: captured_unverified",self.inbox.read_text())
