import json
import tempfile
import unittest
import subprocess
from pathlib import Path
from driftlock_next import knowledge as k, relations as r, portfolio
from driftlock_next.common import sha, GovernanceError

class KnowledgeRelationsTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        for d in (".driftlock","tasks","planning","reports","current"):
            (self.root/d).mkdir()
        (self.root/".driftlock/projects.json").write_text(json.dumps({"schema_version":1,"projects":[
            {"id":"governance","task_prefix":"GOV","intake":{"idea":"planning/IDEA_INBOX.md","problem":"current/PROBLEM_REGISTER.md"}},
            {"id":"amazon_agent","task_prefix":"AMZ","active_task":"tasks/AMZ-TASK-00001.md","remote_policy":"local_only"}]}))
        self.inbox=self.root/"planning/IDEA_INBOX.md"
        self.inbox.write_text("<!-- driftlock-intake:IDEA-X:"+("a"*64)+" -->\n### IDEA IDEA-X\n\nSource: chat\nStatus: captured_unverified\n\n> improve performance\n")
        self.problem=self.root/"current/PROBLEM_REGISTER.md"
        self.problem.write_text("| PROBLEM-001 | in_task | timeout | AMZ-TASK-00001 |\n")
        self.task()
    def task(self,ident="AMZ-TASK-00001",status="in_progress",review="pending",extra=""):
        p=self.root/"tasks"/(ident+".md")
        p.write_text(f"---\ntask_id: {ident}\ncurrent_project: amazon_agent\ntitle: Fix performance timeout\nstatus: {status}\nreview_status: {review}\n{extra}\n---\n\n## Root cause\nUnbounded queries wait too long.\n## Remediation\nBound query duration.\n")
        return p
    def learn(self,task="AMZ-TASK-00001",expected=None,**kw):
        p=self.root/"tasks"/(task+".md")
        args=dict(cause="query-timeout",task=task,lesson="Unbounded queries wait",prevention="Bound query duration",
                  source=str(p.relative_to(self.root)),start=len(p.read_text().splitlines())-3,end=len(p.read_text().splitlines())-2,
                  source_sha=sha(p.read_text()),expected_sha=expected or sha(""),approved=True,tags="performance")
        args.update(kw)
        return k.learn(self.root,"amazon_agent",**args)
    def test_canonical_dedup_append_and_source_cas(self):
        first=self.learn()
        path=Path(first["path"])
        previous=path.read_text()
        same=self.learn(expected=first["sha256"])
        self.assertTrue(same["replay"]);self.assertEqual(previous,path.read_text())
        self.task("AMZ-TASK-00002")
        with self.assertRaises(GovernanceError):
            self.learn("AMZ-TASK-00002",source_sha="0"*64,expected=first["sha256"])
        second=self.learn("AMZ-TASK-00002",expected=first["sha256"])
        self.assertEqual(first["lesson_id"],second["lesson_id"])
        self.assertEqual(second["observations"],2)
        self.assertEqual(len(list(path.parent.glob("*.md"))),1)
        self.assertEqual(k.recommendations(self.root,"amazon_agent")["items"][0]["recommendation"],"consider_promotion")
        with self.assertRaises(GovernanceError):
            self.learn("AMZ-TASK-00002",expected=second["sha256"],lesson="Different interpretation")
    def test_report_requires_explicit_binding_and_no_foreign_sources(self):
        f=self.root/"reports/r.md";f.write_text("# Root cause\nSlow queries\n")
        with self.assertRaises(GovernanceError):
            self.learn(source="reports/r.md",source_sha=sha(f.read_text()),start=1,end=2)
        f.write_text("---\ntask_id: AMZ-TASK-00001\n---\n# Root cause\nSlow queries\n")
        self.assertEqual(self.learn(source="reports/r.md",source_sha=sha(f.read_text()),start=4,end=5)["observations"],1)
    def test_harvest_and_incremental_skip(self):
        d=k.harvest(self.root,"amazon_agent")
        c=next(x for x in d["candidates"] if "Unbounded queries" in x["excerpt"])
        self.learn(source=c["source"],start=c["start"],end=c["end"],source_sha=c["source_sha"])
        d2=k.harvest(self.root,"amazon_agent")
        self.assertFalse(any(x["source"]==c["source"] and x["start"]==c["start"] and x["end"]==c["end"] for x in d2["candidates"]))
    def test_promotion_rules_stale_evidence_and_recall(self):
        first=self.learn();p=Path(first["path"]);m=k._header(p.read_text());event=k._events(m)[0]["id"]
        with self.assertRaises(GovernanceError):
            k.promote(self.root,"amazon_agent","query-timeout","L3",event,first["sha256"],True)
        with self.assertRaises(GovernanceError):
            k.promote(self.root,"amazon_agent","query-timeout","L2",event,first["sha256"],False)
        prev=first
        for level in ("L2","L3","L4"):
            prev=k.promote(self.root,"amazon_agent","query-timeout",level,event,prev["sha256"],True,"explicit_task_scope" if level=="L4" else None)
        data=k.preflight(self.root,"amazon_agent")
        self.assertEqual(data["state"],"blocked")
        self.assertEqual(data["lessons"][0]["effective_level"],"L4")
        self.task(extra="scope: performance")
        data=k.preflight(self.root,"amazon_agent")
        self.assertEqual(data["state"],"advisory")
        self.assertTrue(data["lessons"][0]["stale_promotion"])
    def test_graph_structured_not_semantic_and_sync(self):
        self.task(extra="intake_ids: [IDEA-X]")
        (self.root/"reports/e.md").write_text("---\ntask_id: AMZ-TASK-00001\nverdict: FAIL\n---\n# Findings\n")
        g=r.graph(self.root)
        self.assertIn("implements_intake",g["counts"])
        self.assertIn("addresses_problem",g["counts"])
        self.assertIn("evidence_for",g["counts"])
        data=r.sync(self.root)
        self.assertEqual(data["items"][0]["state"],"work_linked")
        self.assertFalse(data["write_performed"])
    def test_scope_receipt_verified_and_stale(self):
        candidate="a"*40
        self.task(status="closed",review="pass",extra=f"intake_ids: [IDEA-X]\ntask_contract_version: 2\ncandidate_commit: {candidate}\ncandidate_state: frozen")
        f=self.root/"reports/attest.md"
        f.write_text(f"---\ntask_id: AMZ-TASK-00001\nverdict: PASS\nreview_status: accepted\ncandidate_commit: {candidate}\n---\n# Independent review\n")
        def git(*args):
            subprocess.run(["git","-C",str(self.root),*args],check=True,capture_output=True)
        git("init","-q");git("config","user.name","Test");git("config","user.email","test@example.invalid");git("add",".");git("commit","-qm","fixture")
        self.assertEqual(r.sync(self.root)["items"][0]["state"],"closure_review_required")
        ev=json.dumps({"AMZ-TASK-00001":"reports/attest.md"})
        with self.assertRaises(GovernanceError):
            r.accept_scope(self.root,"governance","IDEA-X",ev,sha(self.inbox.read_text()),False)
        r.accept_scope(self.root,"governance","IDEA-X",ev,sha(self.inbox.read_text()),True)
        self.assertEqual(r.sync(self.root)["items"][0]["state"],"completed")
        f.write_text(f.read_text()+"Uncommitted change\n")
        self.assertEqual(r.sync(self.root)["items"][0]["state"],"completion_evidence_stale")
    def test_cannot_close_partial_or_unreviewed(self):
        self.task(status="deployed_pending_close",extra="intake_ids: [IDEA-X]")
        (self.root/"reports/attest.md").write_text("not review")
        with self.assertRaises(GovernanceError):
            r.accept_scope(self.root,"governance","IDEA-X",json.dumps({"AMZ-TASK-00001":"reports/attest.md"}),sha(self.inbox.read_text()),True)
        self.assertNotIn("Completion-Receipt",self.inbox.read_text())

    def test_open_rework_prevents_scope_completion(self):
        c="a"*40
        self.task(status="closed",review="pass",extra=f"intake_ids: [IDEA-X]\ntask_contract_version: 2\ncandidate_commit: {c}\ncandidate_state: frozen")
        self.task("AMZ-TASK-00001-R1",extra="rework_of: AMZ-TASK-00001")
        d=r.sync(self.root)["items"][0]
        self.assertEqual(d["scope_tasks"],["AMZ-TASK-00001","AMZ-TASK-00001-R1"])
        self.assertNotEqual(d["state"],"closure_review_required")
        with self.assertRaises(GovernanceError):
            r.accept_scope(self.root,"governance","IDEA-X",json.dumps({"AMZ-TASK-00001":"reports/attest.md"}),sha(self.inbox.read_text()),True)
    def test_unlinked_legacy_rework_requires_review(self):
        self.task(extra="intake_ids: [IDEA-X]")
        self.task("AMZ-TASK-00001-R2")
        d=r.sync(self.root)["items"][0]
        self.assertEqual(d["state"],"linked_scope_unresolved")

    def test_malformed_linked_plan_prevents_completion(self):
        self.task(extra="intake_ids: [IDEA-X]")
        (self.root/"planning/p.md").write_text("---\nplan_id: AMZ-PLAN-X\nproject_id: amazon_agent\nstatus: implemented\nintake_ids: [IDEA-X]\nrelated_tasks: [broken\n---\n# plan\n")
        d=r.sync(self.root)["items"][0]
        self.assertEqual(d["state"],"linked_scope_unresolved")
        self.assertIn("INVALID_RELATION",[x["code"] for x in d["scope_warnings"]])
    def test_promotion_interpretation_and_exact_tag_scope(self):
        first=self.learn(tags="api");path=Path(first["path"])
        event=k._events(k._header(path.read_text()))[0]["id"]
        last=first
        for level in ("L2","L3","L4"):
            last=k.promote(self.root,"amazon_agent","query-timeout",level,event,last["sha256"],True,"explicit_task_scope" if level=="L4" else None)
        self.task("AMZ-TASK-00002",extra="tags: [capital]")
        d=k.preflight(self.root,"amazon_agent","AMZ-TASK-00002","capital")
        self.assertEqual(d["state"],"advisory");self.assertEqual(d["checks"],[])
        self.task("AMZ-TASK-00002",extra="tags: [api]")
        d=k.preflight(self.root,"amazon_agent","AMZ-TASK-00002")
        self.assertEqual(d["state"],"blocked")
        original=path.read_text()
        path.write_text(original.replace("prevention: Bound query duration","prevention: Unapproved replacement"))
        d=k.preflight(self.root,"amazon_agent","AMZ-TASK-00002")
        self.assertEqual(d["state"],"advisory")
        self.assertTrue(d["lessons"][0]["stale_promotion"])
        path.write_text(original.replace('tags: ["api"]','tags: ["api", "capital"]'))
        self.task("AMZ-TASK-00002",extra="tags: [capital]")
        d=k.preflight(self.root,"amazon_agent","AMZ-TASK-00002")
        self.assertEqual(d["state"],"advisory")
    def test_failed_predecessor_closed_by_exact_accepted_repair(self):
        candidate="a"*40
        self.task(status="rework_required",review="fail",extra="intake_ids: [IDEA-X]")
        self.task("AMZ-TASK-00001-R1",status="closed",review="pass",extra=f"rework_of: AMZ-TASK-00001\ntask_contract_version: 2\ncandidate_commit: {candidate}\ncandidate_state: frozen")
        f=self.root/"reports/attest.md"
        f.write_text(f"---\ntask_id: AMZ-TASK-00001-R1\nverdict: PASS\nreview_status: accepted\ncandidate_commit: {candidate}\n---\n# Independent review\n")
        def git(*args):subprocess.run(["git","-C",str(self.root),*args],check=True,capture_output=True)
        git("init","-q");git("config","user.name","Test");git("config","user.email","test@example.invalid");git("add",".");git("commit","-qm","fixture")
        self.assertEqual(r.sync(self.root)["items"][0]["state"],"closure_review_required")
        r.accept_scope(self.root,"governance","IDEA-X",json.dumps({"AMZ-TASK-00001-R1":"reports/attest.md"}),sha(self.inbox.read_text()),True)
        self.assertEqual(r.sync(self.root)["items"][0]["state"],"completed")
        self.task("AMZ-TASK-00001-R2",extra="rework_of: AMZ-TASK-00001-R1")
        self.assertEqual(r.sync(self.root)["items"][0]["state"],"completion_evidence_stale")

    def test_direct_plan_references_fail_closed(self):
        for extra in ("plan: [broken","plan_id_ref: MISSING-PLAN","plan: planning/missing.md"):
            with self.subTest(extra=extra):
                self.task(extra="intake_ids: [IDEA-X]\n"+extra)
                d=r.sync(self.root)["items"][0]
                self.assertEqual(d["state"],"linked_scope_unresolved")
                self.assertTrue(any(x["field"] in ("plan","plan_id_ref") for x in d["scope_warnings"]))
    def test_numbered_and_legacy_repair_edges(self):
        self.task(extra="intake_ids: [IDEA-X]")
        self.task("AMZ-TASK-00002",extra="rework_of: AMZ-TASK-00001")
        d=r.sync(self.root)["items"][0]
        self.assertEqual(d["scope_tasks"],["AMZ-TASK-00001","AMZ-TASK-00002"])
        self.task(extra="intake_ids: [IDEA-X]\nrework_of: AMZ-TASK-00002")
        d=r.sync(self.root)["items"][0]
        self.assertEqual(d["state"],"linked_scope_unresolved")
        self.assertTrue(any(x["code"]=="CYCLIC_REWORK_SCOPE" for x in d["scope_warnings"]))

    def test_plain_markdown_repair_cannot_disappear_from_scope(self):
        self.task(extra="intake_ids: [IDEA-X]")
        (self.root/"tasks/AMZ-TASK-00001-R1-repair.md").write_text("# AMZ-TASK-00001-R1\nStatus: deferred, not implemented.\n")
        d=r.sync(self.root)["items"][0]
        self.assertEqual(d["state"],"linked_scope_unresolved")
        self.assertTrue(any(x["code"]=="UNSTRUCTURED_TASK_RECORD" for x in d["scope_warnings"]))
