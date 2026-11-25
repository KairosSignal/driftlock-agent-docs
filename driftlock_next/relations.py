"""Rebuild explicit relationships from authoritative records, never invent completion."""
from collections import Counter, defaultdict
from pathlib import Path
import re
import json
from .common import fail, frontmatter, response, sha, text_file, within
from .portfolio import inventory, links, ID, INTAKE, record_view, verified_terminal
from .problems import rows as problem_rows
from .registry import select
from .atomic import change

def graph(root,project=None):
    ps,records,captures,warnings=inventory(root,project)
    nodes={i:record_view(r) for i,r in records.items()}
    paths={r["path"]:i for i,r in records.items()}
    project_by_id={p["id"]:p for p in ps}
    for i,items in captures.items():
        if len(items)==1:
            item=items[0]
            nodes[i]={"id":i,"kind":item["kind"],"project":item["project"],"path":item["path"]}
    edges=[]
    keys=set()
    def add(a,b,relation,source):
        if a not in nodes or b not in nodes:
            warnings.append({"code":"UNRESOLVED_RELATION","from":a,"to":b,"field":relation})
            return
        if a==b:return
        key=(a,b,relation)
        if key in keys:return
        keys.add(key);edges.append({"from":a,"to":b,"relation":relation,"source":source})
    def values(m,key):
        try:return links(m.get(key))
        except ValueError:
            warnings.append({"code":"INVALID_RELATION","field":key})
            return []
    for i,r in records.items():
        m=r["meta"]
        for field,rel in (("intake_ids","implements_intake"),("weekly_report_idea_id","references_intake"),
                          ("depends_on","depends_on"),("related_tasks","related_task"),("related_to","related_record"),
                          ("rework_of","rework_of"),("parent","parent"),("supersedes","supersedes")):
            for x in values(m,field):add(i,x,rel,r["path"]+"#"+field)
        for field in ("plan","plan_id_ref"):
            v=m.get(field)
            if not isinstance(v,str):continue
            base=project_by_id.get(r["project"],{}).get("_resolved_root")
            if v in nodes and nodes[v]["kind"]=="plan":add(i,v,"implements_plan",r["path"]+"#"+field)
            elif base and v.endswith(".md"):
                try: path=str(within(base,v))
                except Exception:continue
                if path in paths and nodes[paths[path]]["kind"]=="plan":add(i,paths[path],"implements_plan",r["path"]+"#"+field)
    for i,items in captures.items():
        if len(items)!=1:continue
        for target in items[0]["bound"]:
            add(target,i,"implements_intake",items[0]["path"]+"#Linked-Record")
    seen=set()
    for p in ps:
        base=Path(p.get("_resolved_root") or root).resolve()
        rel=p.get("intake",{}).get("problem")
        if rel:
            f=within(base,rel,allow_missing=True)
            if f.exists() and f not in seen:
                seen.add(f)
                rr=problem_rows(text_file(f))
                counts=Counter(x["id"] for x in rr)
                for x in rr:
                    i=x["id"]
                    if counts[i]!=1 or i in nodes:
                        warnings.append({"code":"AMBIGUOUS_PROBLEM","id":i});continue
                    nodes[i]={"id":i,"kind":"problem","project":p["id"],"path":str(f),"status":x["status"],"description":x["description"][:200]}
                    for t in re.findall(r"(?<![A-Za-z0-9-])(?:[A-Z]{2,5}-)?TASK-\d+[A-Z0-9]*(?:-[A-Z0-9]+)*",x["task"]):
                        add(t,i,"addresses_problem",str(f)+"#"+i)
        folder=within(base,"reports",allow_missing=True)
        if not folder.is_dir():continue
        for f in sorted(folder.glob("*.md")):
            if f in seen or f.is_symlink() or not f.is_file():continue
            seen.add(f)
            m=frontmatter(text_file(f))
            targets=values(m,"task_ids")+values(m,"task_id")+values(m,"plan_id")
            # Explicit record IDs only. A title or filename match is not a verified relation.
            if not targets:continue
            i="report:"+str(f)
            owners={records[t]["project"] for t in targets if t in records and records[t]["project"]}
            nodes[i]={"id":i,"kind":"report","project":next(iter(owners)) if len(owners)==1 else None,"path":str(f),
                      "declared_verdict":m.get("verdict"),"status":m.get("review_status")}
            for target in targets:add(i,target,"evidence_for",str(f)+"#frontmatter")
    for i,record in records.items():
        for target in values(record["meta"],"problem_ids"):
            if target in nodes and nodes[target]["kind"]=="problem":
                add(i,target,"addresses_problem",record["path"]+"#problem_ids")
    if project and project not in ("governance","company"):
        seeds={i for i,n in nodes.items() if n.get("project")==project}
        edges=[e for e in edges if e["from"] in seeds or e["to"] in seeds]
        keep=seeds|{e[k] for e in edges for k in ("from","to")}
        nodes={i:n for i,n in nodes.items() if i in keep}
    return response("portfolio.graph",project_id=project or "all",nodes=list(nodes.values()),edges=edges,
                    counts=dict(Counter(e["relation"] for e in edges)),warnings=warnings,write_performed=False,
                    authority="exact structured associations only; evidence_for does not certify PASS")

def _scope(root,project,ident):
    ps,records,captures,_=inventory(root,project)
    if len(captures.get(ident,[]))!=1:fail("INTAKE_IDENTITY","Expected unique intake")
    item=captures[ident][0]
    g=graph(root)
    tasks,plans,unresolved=_linked_scope(records,g,ident)
    return item,records,tasks,plans,unresolved

def _linked_scope(records,g,ident):
    ids=sorted({e["from"] for e in g["edges"] if e["to"]==ident and e["relation"]=="implements_intake" and e["from"] in records})
    # A linked plan may explicitly designate the implementation tasks.
    plans={i for i in ids if records[i]["kind"]=="plan"}
    tasks={i for i in ids if records[i]["kind"]=="task"}
    for e in g["edges"]:
        if e["relation"]=="implements_plan" and e["to"] in plans and e["from"] in records and records[e["from"]]["kind"]=="task":
            tasks.add(e["from"])
        if e["relation"]=="related_task" and e["from"] in plans and e["to"] in records and records[e["to"]]["kind"]=="task":
            tasks.add(e["to"])
    unresolved=[e for e in g["warnings"] if e.get("code")=="UNRESOLVED_RELATION" and (e.get("from") in plans|tasks or e.get("to")==ident)]
    return sorted(tasks),sorted(plans),unresolved

def _receipt(item):
    body=text_file(item["path"])
    ms=list(INTAKE.finditer(body))
    for j,m in enumerate(ms):
        if m[1]!=item["id"]:continue
        block=body[m.end():ms[j+1].start() if j+1<len(ms) else len(body)]
        head=block.split("\n> ",1)[0]
        hits=re.findall(r"^Completion-Receipt: (.+)$",head,re.M)
        if not hits:return None
        try:r=json.loads(hits[-1])
        except ValueError:return None
        return r if isinstance(r,dict) else None
    return None

def _validate_scope(root,item,records,tasks,plans,unresolved,receipt):
    if not receipt or not tasks or unresolved or receipt.get("tasks")!=tasks or receipt.get("plans")!=plans:
        return False
    if any(records[i]["status"]!="implemented" for i in plans):return False
    if receipt.get("capture_sha")!=sha(item["text"]):return False
    evidence=receipt.get("evidence")
    if not isinstance(evidence,dict) or set(evidence)!=set(tasks):return False
    from .problems import _verify_resolution_claim
    from .common import git
    for i in tasks+plans:
        r=records[i]
        if r["kind"]=="task" and not verified_terminal(r):return False
        if not r["project"]:return False
        try:
            p=select(root,r["project"])
            base=Path(p["_resolved_root"])
            rel=str(Path(r["path"]).relative_to(base))
            committed=git(base,"show","HEAD:"+rel,check=False)
            if committed.returncode or committed.stdout!=text_file(r["path"]):return False
        except Exception:return False
        if r["kind"]=="plan":continue
        spec=evidence[i]
        if not isinstance(spec,dict) or spec.get("candidate")!=r["meta"].get("candidate_commit"):return False
        try:
            path=_verify_resolution_claim(base,i,spec.get("path"),r["meta"])
            if sha(text_file(within(base,path)))!=spec.get("sha256"):return False
        except Exception:return False
    return True

def accept_scope(root,project,ident,evidence_json,expected_sha,approved):
    """Owner attests full original scope; require exact closed task evidence and CAS."""
    if not approved:fail("APPROVAL_REQUIRED","Explicit full-scope acceptance required")
    p=select(root,project)
    item,records,tasks,plans,unresolved=_scope(root,project,ident)
    if p["id"]!=item["project"]:fail("INTAKE_OWNER","Select intake owner")
    path=Path(item["path"]);body=text_file(path)
    if sha(body)!=expected_sha:fail("VERSION_CONFLICT","Intake changed")
    try: ev=json.loads(evidence_json)
    except ValueError:fail("SCOPE_EVIDENCE","Expected object of task ID to review path")
    if not isinstance(ev,dict) or set(ev)!=set(tasks):fail("SCOPE_EVIDENCE","Supply every bound task, no extra")
    evidence={}
    for task,rel in ev.items():
        r=records[task];owner=select(root,r["project"])
        f=within(owner["_resolved_root"],rel)
        evidence[task]={"path":rel,"sha256":sha(text_file(f)),"candidate":r["meta"].get("candidate_commit")}
    receipt={"capture_sha":sha(item["text"]),"tasks":tasks,"plans":plans,"evidence":evidence}
    if not _validate_scope(root,item,records,tasks,plans,unresolved,receipt):
        fail("SCOPE_NOT_VERIFIED","Require full scope, all closed PASS tasks, implemented plans and exact committed attestations")
    m=next(m for m in INTAKE.finditer(body) if m[1]==ident)
    head_end=body.find("\n> ",m.end())
    if head_end<0:fail("INTAKE_FORMAT","Original quote missing")
    head=body[m.end():head_end]
    prior=re.findall(r"^Completion-Receipt: (.+)$",head,re.M)
    if prior:
        try: previous=json.loads(prior[-1])
        except ValueError:fail("RECEIPT_FORMAT","Existing receipt malformed; do not overwrite")
        if {k:v for k,v in previous.items() if k!="supersedes_sha"}==receipt:
            return response("portfolio.accept-scope",id=ident,changed=False)
        receipt["supersedes_sha"]=sha(prior[-1])
    # Append a new receipt in the original header, preserving prior evidence.
    out=body[:head_end]+"\nCompletion-Receipt: "+json.dumps(receipt,ensure_ascii=False,separators=(",",":"))+"\n"+body[head_end:]
    result=change(p["_resolved_root"],str(path.relative_to(p["_resolved_root"])),expected_sha,out,approve=True)
    return response("portfolio.accept-scope",project_id=p["id"],id=ident,**result)

def sync(root,project=None):
    """Read-time synchronization from exact associations; no duplicate status authority."""
    from .portfolio import backlog
    b=backlog(root,project);g=graph(root,project);all_graph=g if not project or project in ("governance","company") else graph(root)
    _,records,captures,_=inventory(root,project)
    idx=defaultdict(list)
    for e in g["edges"]:
        if e["relation"] in ("implements_intake","references_intake"):
            idx[e["to"]].append(e)
    items=[]
    # Include shared inbox entries with exact links even when base backlog did not show them.
    rows={r["id"]:r for r in b["items"]}
    for ident,edges in idx.items():
        if ident not in rows and len(captures.get(ident,[]))==1:
            c=captures[ident][0]
            rows[ident]={"id":ident,"kind":c["kind"],"state":"link_review_required","source":c["path"],
                         "linked":[],"candidate_links":[],"text_excerpt":c["text"][:240]}
    for ident,row in rows.items():
        item=captures[ident][0]
        rcp=_receipt(item)
        exact=[e for e in idx[ident] if e["relation"]=="implements_intake"]
        references=[e for e in idx[ident] if e["relation"]=="references_intake"]
        ts,pl,un=_linked_scope(records,all_graph,ident)
        if rcp:
            row["state"]="completed" if _validate_scope(root,item,records,ts,pl,un,rcp) else "completion_evidence_stale"
        elif ts:
            states=[records[i]["status"] for i in ts]
            if un: row["state"]="linked_scope_unresolved"
            elif all(verified_terminal(records[i]) for i in ts) and all(records[i]["status"]=="implemented" for i in pl):
                row["state"]="closure_review_required"
            elif any(records[i]["status"] in ("deployed","deployed_pending_close","deployed_production_verified") and records[i]["review"]!="pass" for i in ts):
                row["state"]="deployed_review_pending"
            elif any(x in ("deployed","deployed_pending_close","deployed_production_verified") for x in states):
                row["state"]="deployed_acceptance_pending"
            elif any(x in ("in_progress","ready_for_review","rework_required","blocked","accepted","accepted_pending_integration","integrated","integrated_pending_deploy") for x in states):
                row["state"]="work_linked"
            else:row["state"]="linked_planning"
        row["scope_tasks"]=ts
        row["scope_plans"]=pl
        row["scope_warnings"]=un
        row["exact_links"]=exact
        row["reference_only_links"]=references
        items.append(row)
    return response("portfolio.sync",project_id=project or "all",items=items,
                    counts=dict(Counter(x["state"] for x in items)),warnings=b["warnings"]+g["warnings"],
                    write_performed=False,authority="live derived view; completion requires explicit scope receipt and committed evidence")
