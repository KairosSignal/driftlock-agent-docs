"""Evidence-linked engineering memory. No model calls, background jobs or implicit authority."""
from collections import defaultdict
from pathlib import Path
import hashlib
import json
import re
from .common import fail, frontmatter, response, sha, text_file, within
from .atomic import change
from .registry import select
from .portfolio import inventory, ID, links, record_view

LEVELS=("L1","L2","L3","L4")
# Fixed, non-executable checks; a lesson never contains executable code.
CHECKS={"lifecycle_consistency","declared_dependency_consistency","explicit_task_scope"}
def _project(root,project):
    return select(root,project)
def _folder(p):
    return within(p["_resolved_root"],"reports/lessons",allow_missing=True)
def _header(body):
    if not body.startswith("---\n") or "\n---\n" not in body[4:]:
        fail("LESSON_FORMAT","Expected complete lesson frontmatter")
    head=body[4:body.index("\n---\n",4)]
    keys=[x.split(":",1)[0] for x in head.splitlines() if ":" in x]
    if len(set(keys))!=len(keys):fail("LESSON_FORMAT","Duplicate lesson field")
    return frontmatter(body)
def _events(meta):
    try: e=json.loads(meta.get("evidence_events") or "[]")
    except (ValueError,TypeError): fail("LESSON_FORMAT","Malformed evidence events")
    if not isinstance(e,list) or any(not isinstance(x,dict) or not isinstance(x.get("id"),str) for x in e):
        fail("LESSON_FORMAT","Malformed evidence events")
    if len({x["id"] for x in e})!=len(e):fail("LESSON_FORMAT","Duplicate evidence event")
    return e
def _line(value,name,limit=1500):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or any(ord(c)<32 for c in value):
        fail("LESSON_FIELD","Invalid "+name)
    # Legacy Markdown scalar parser strips wrapping quotes.
    if value.startswith(("'",'"')) or value.endswith(("'",'"')):
        fail("LESSON_FIELD","Do not wrap "+name+" in quotes")
    return value.strip()
def _canonical_id(project,cause):
    return "LESSON-"+hashlib.sha256((project+"\0"+cause).encode()).hexdigest()[:24]
def _existing(p,cause):
    folder=_folder(p)
    hits=[]
    if folder.exists():
        if not folder.is_dir():fail("LESSON_DIRECTORY","Not a directory")
        for f in sorted(folder.glob("*.md")):
            if f.is_symlink() or not f.is_file():continue
            m=_header(text_file(f))
            if m.get("project_id")==p["id"] and m.get("root_cause_key")==cause:
                hits.append((f,m))
    if len(hits)>1:fail("AMBIGUOUS_CAUSE","Existing duplicate cause needs explicit reconciliation")
    return hits[0] if hits else (None,{})
def _render(meta, prior=None):
    tail=prior[prior.index("\n---\n",4)+5:] if prior else "\n# Engineering lesson\n\nEvidence observations are append-only; promotion is separately approved.\n"
    return "---\n"+"\n".join(f"{k}: {str(v).lower() if isinstance(v,bool) else v}" for k,v in meta.items() if v is not None)+"\n---\n"+tail
def _source(p,record,relative,start,end,expected):
    base=Path(p["_resolved_root"])
    path=within(base,relative)
    if path.suffix!=".md":fail("LESSON_SOURCE","Expected a Markdown evidence source")
    rel=path.relative_to(base)
    # Only the exact task or a report under the configured project root.
    if path!=Path(record["path"]) and (not rel.parts or rel.parts[0]!="reports" or len(rel.parts)>1 and rel.parts[1]=="lessons"):
        fail("LESSON_SOURCE","Source must be exact task or its report, not an arbitrary file")
    body=text_file(path)
    digest=sha(body)
    if digest!=expected:fail("SOURCE_CHANGED","Evidence source SHA changed")
    if path!=Path(record["path"]):
        m=frontmatter(body)
        try: ids=links(m.get("task_ids"))+[m.get("task_id")]
        except ValueError:fail("LESSON_SOURCE","Malformed report task association")
        if record["id"] not in ids:fail("LESSON_SOURCE","Report lacks explicit exact task binding")
    lines=body.splitlines()
    if not 1<=start<=end<=len(lines) or end-start>40:
        fail("LESSON_LINES","Select 1–41 existing source lines")
    excerpt="\n".join(lines[start-1:end])
    if not excerpt.strip() or len(excerpt)>6000:fail("LESSON_LINES","Empty or excessive evidence excerpt")
    return {"source":str(rel),"sha256":digest,"start":start,"end":end,"excerpt":excerpt}

def learn(root,project,cause,task,lesson,prevention,source,start,end,source_sha,expected_sha,approved,tags=None):
    """Add one exact-source observation to a canonical cause, dedup by source/range/task."""
    if not approved:fail("APPROVAL_REQUIRED","Explicit lesson capture approval required")
    p=_project(root,project)
    if not ID.fullmatch(cause):fail("LESSON_ID","Invalid root cause key")
    _,records,_,_=inventory(root,project)
    r=records.get(task)
    if not r or r["kind"]!="task" or r["project"]!=p["id"]:fail("LESSON_TASKS","Require unique owned task")
    lesson=_line(lesson,"lesson");prevention=_line(prevention,"prevention")
    try: taglist=links(tags)
    except ValueError:fail("LESSON_TAGS","Use simple stable tags")
    ev=_source(p,r,source,start,end,source_sha)
    ev["task_id"]=task
    ev["id"]=sha(json.dumps([task,ev["source"],ev["sha256"],start,end],ensure_ascii=False))
    ev["lesson"]=lesson;ev["prevention"]=prevention
    path,old=_existing(p,cause)
    prior=None
    if path:
        body=text_file(path); prior=body; actual=sha(body)
        if actual!=expected_sha:fail("VERSION_CONFLICT","Lesson changed")
        if old.get("lesson")!=lesson or old.get("prevention")!=prevention:
            fail("CAUSE_CONTENT_CONFLICT","Existing cause has different interpretation; reconcile, do not silently overwrite")
        events=_events(old)
        if any(e["id"]==ev["id"] for e in events):
            return response("portfolio.learn",project_id=p["id"],lesson_id=old["lesson_id"],replay=True,sha256=actual,changed=False)
        # Old level remains, but new observations do not inherit verification.
        meta=dict(old);rel=str(path.relative_to(p["_resolved_root"]))
    else:
        if expected_sha!=sha(""):fail("VERSION_CONFLICT","New lesson expected empty SHA")
        ident=_canonical_id(p["id"],cause)
        rel="reports/lessons/"+ident+".md"
        if within(p["_resolved_root"],rel,allow_missing=True).exists():fail("LESSON_ID_CONFLICT","Canonical ID already exists")
        meta={"lesson_id":ident,"project_id":p["id"],"root_cause_key":cause,"lesson":lesson,"prevention":prevention,
              "status":"captured_unverified","level":"L1","evidence":"See evidence_events"}
        events=[]
    meta["task_ids"]=json.dumps(sorted(set(links(meta.get("task_ids"))+[task])))
    meta["tags"]=json.dumps(sorted(set(links(meta.get("tags"))+taglist)))
    meta["evidence_events"]=json.dumps(events+[ev],ensure_ascii=False,separators=(",",":"))
    out=_render(meta,prior)
    if len(out.encode())>512_000:fail("LESSON_CAPACITY","Lesson needs explicit archival review")
    result=change(p["_resolved_root"],rel,expected_sha,out,approve=True,allow_create=True)
    return response("portfolio.learn",project_id=p["id"],lesson_id=meta["lesson_id"],replay=False,observations=len(events)+1,**result)

def _interpretation(meta):
    return sha(json.dumps([meta.get("root_cause_key"),meta.get("lesson"),meta.get("prevention")],ensure_ascii=False,separators=(",",":")))

def _rule_scope(meta):
    return sha(json.dumps([sorted(links(meta.get("tags"))),sorted(links(meta.get("task_ids")))],separators=(",",":")))

def promote(root,project,cause,level,evidence,expected_sha,approved,check=None):
    """Explicit one-level promotion, never inferred from recurrence or test counts."""
    if not approved:fail("APPROVAL_REQUIRED","Explicit promotion approval required")
    p=_project(root,project)
    path,m=_existing(p,cause)
    if not path:fail("LESSON_MISSING","Cause not found")
    body=text_file(path)
    if sha(body)!=expected_sha:fail("VERSION_CONFLICT","Lesson changed")
    old=m.get("level") or "L1"
    if old not in LEVELS or level not in LEVELS or LEVELS.index(level)!=LEVELS.index(old)+1:
        fail("LESSON_LEVEL","Only next-level promotion allowed")
    events=_events(m)
    # Explicit human decision references one captured event; not arbitrary prose.
    if not any(e["id"]==evidence for e in events):fail("PROMOTION_EVIDENCE","Reference exact captured evidence event ID")
    ev=next(e for e in events if e["id"]==evidence)
    if ev.get("lesson")!=m.get("lesson") or ev.get("prevention")!=m.get("prevention"):
        fail("PROMOTION_INTERPRETATION","Captured interpretation differs from current lesson")
    _,records,_,_=inventory(root,project)
    r=records.get(ev["task_id"])
    if not r or r["project"]!=p["id"]:fail("PROMOTION_EVIDENCE","Task source no longer uniquely owned")
    _source(p,r,ev["source"],ev["start"],ev["end"],ev["sha256"])
    if level=="L4" and check not in CHECKS:fail("UNKNOWN_CHECK","Only supported deterministic check IDs")
    if level!="L4" and check:fail("UNKNOWN_CHECK","Check allowed only for L4")
    try: decisions=json.loads(m.get("promotions") or "[]")
    except (ValueError,TypeError):fail("LESSON_FORMAT","Malformed promotions")
    if not isinstance(decisions,list):fail("LESSON_FORMAT","Malformed promotions")
    m["level"]=level
    m["status"]="operator_verified" if level=="L2" else "approved_rule"
    m["promotions"]=json.dumps(decisions+[{"from":old,"to":level,"evidence_event":evidence,"check":check,"interpretation_sha":_interpretation(m),"scope_sha":_rule_scope(m) if level in ("L3","L4") else None}],separators=(",",":"))
    if check:m["check_id"]=check
    result=change(p["_resolved_root"],str(path.relative_to(p["_resolved_root"])),expected_sha,_render(m,body),approve=True)
    return response("portfolio.promote",project_id=p["id"],lesson_id=m["lesson_id"],level=level,**result)

def harvest(root,project=None,limit=50,task=None):
    """Generate evidence candidates from headings/explicit task metadata, never assert a cause."""
    if not 1<=limit<=200:fail("HARVEST_LIMIT","Limit 1–200")
    ps,records,_,warnings=inventory(root,project)
    known={p["id"]:{**p,"_resolved_root":p.get("_resolved_root") or str(Path(root).resolve())} for p in ps}
    out=[]
    headings=re.compile(r"^#{1,5}\s+.*(?:root.cause|lessons?|failure|retrospective|findings?|remediation|evidence|根因|教训|经验|失败|返修|复盘|审核发现|事件事实|流程违规)",re.I)
    captured=set()
    from .portfolio import lessons
    for item in lessons(root,project)["lessons"]:
        for ev in _events(_header(text_file(item["path"]))):
            captured.add((ev.get("task_id"),ev.get("source"),ev.get("sha256"),ev.get("start"),ev.get("end")))
    def extract(r,path):
        p=known.get(r["project"])
        if not p:return
        rel=str(path.relative_to(p["_resolved_root"]))
        text=text_file(path);digest=sha(text);lines=text.splitlines()
        sections=[]
        for i,line in enumerate(lines):
            if headings.search(line):
                end=next((j for j in range(i+1,min(i+13,len(lines))) if lines[j].startswith("#")),min(i+13,len(lines)))
                sections.append((i+1,end))
        for start,end in sections:
            if (r["id"],rel,digest,start,end) in captured:continue
            snippet="\n".join(lines[start-1:end])[:1600]
            if any(line.strip() and not line.lstrip().startswith("#") for line in lines[start:end]):out.append({"task_id":r["id"],"project":r["project"],"source":rel,"source_sha":digest,
                                            "start":start,"end":end,"excerpt":snippet,"state":"needs_semantic_review"})
    eligible={i:r for i,r in records.items() if r["kind"]=="task" and r["project"] in known and
              (not project or project in ("governance","company") or r["project"]==project) and (not task or i==task)}
    if task and task not in eligible:fail("HARVEST_TASK","Expected unique owned task")
    for r in sorted(eligible.values(),key=lambda x:x["path"],reverse=True):
        if len(out)>=limit:break
        extract(r,Path(r["path"]))
    visited=set()
    for p in ps:
        if len(out)>=limit:break
        base=Path(p.get("_resolved_root") or root)
        folder=within(base,"reports",allow_missing=True)
        if not folder.is_dir():continue
        for f in sorted(folder.glob("*.md"),reverse=True):
            if len(out)>=limit:break
            if f in visited or f.is_symlink() or not f.is_file():continue
            visited.add(f)
            m=frontmatter(text_file(f))
            try: ids=links(m.get("task_ids"))+[m.get("task_id")]
            except ValueError:continue
            for ident in dict.fromkeys(ids):
                if ident in eligible and Path(known[eligible[ident]["project"]]["_resolved_root"])==base:
                    extract(eligible[ident],f)
    return response("portfolio.harvest",project_id=project or "all",candidates=out[:limit],warnings=warnings,
                    write_performed=False,authority="source snippets only; current AI reviews meaning before approved learn")

def preflight(root,project,task=None,query=None):
    """Bounded relevant lessons for the task entrypoint; L4 only runs built-in checks."""
    from .portfolio import lessons, dependencies
    from .audit import task_lifecycle_blockers
    p=_project(root,project)
    _,records,_,warnings=inventory(root,project)
    if task is None:
        active=p.get("active_task")
        if active:
            path=str(within(p["_resolved_root"],active,allow_missing=True))
            task=next((i for i,r in records.items() if r["path"]==path),None)
    r=records.get(task)
    if not r or r["kind"]!="task" or r["project"]!=p["id"]:
        return response("portfolio.preflight",project_id=p["id"],state="review_required",reason="task_not_uniquely_owned",
                        warnings=warnings,lessons=[],checks=[],write_performed=False)
    m=r["meta"]
    text=" ".join(str(x or "") for x in (query,r["title"],Path(r["path"]).stem,m.get("root_cause_key"),m.get("module"),m.get("tags"))).casefold()
    def terms(text):
        result=set(re.findall(r"[a-z0-9]{3,}",text))
        for word in re.findall(r"[\u4e00-\u9fff]+",text):
            result.update(word[i:i+2] for i in range(len(word)-1))
        return result
    tokens=terms(text)
    base=re.sub(r"-R[1-9][0-9]*$","",task)
    all_lessons=lessons(root,p["id"])["lessons"]
    applicable=[]
    for item in all_lessons:
        # Owner-only recall, except explicitly approved shared rules in governance.
        lm=_header(text_file(item["path"]))
        if lm.get("project_id")!=p["id"]:continue
        cause=lm["root_cause_key"]
        try: tags=links(lm.get("tags"))
        except ValueError:continue
        exact=task in item["task_ids"] or any(re.sub(r"-R[1-9][0-9]*$","",i)==base for i in item["task_ids"])
        match_tags=[tag for tag in tags+[cause] if tag.casefold() in text]
        # Only structured metadata may scope a mandatory rule; prose is advisory.
        declared=set()
        for field in ("tags","root_cause_key","module"):
            try:declared.update(x.casefold() for x in links(m.get(field)))
            except ValueError:pass
        exact_tags=[tag for tag in tags+[cause] if tag.casefold() in declared]
        content=" ".join(str(lm.get(k) or "") for k in ("lesson","prevention","root_cause_key")).casefold()
        words=terms(content)
        overlap=tokens&words
        semantic=bool(overlap and (len(overlap)>=2 or query and query.casefold() in content))
        if not (exact or match_tags or exact_tags or semantic):continue
        if lm.get("status")=="retired":continue
        level=lm.get("level") or "L1"
        if level not in LEVELS:level="L1"
        check=lm.get("check_id") if level=="L4" else None
        # Never trust a level field alone: require recorded promotion sequence,
        # exact source hashes and evidence ownership; invalid/stale rules stay advisory.
        valid=False
        if level!="L1":
            try:
                ds=json.loads(lm.get("promotions") or "[]")
                es={x["id"]:x for x in _events(lm)}
                required=LEVELS.index(level)
                valid=isinstance(ds,list) and len(ds)==required and all(
                    d.get("from")==LEVELS[i] and d.get("to")==LEVELS[i+1] and d.get("evidence_event") in es and d.get("interpretation_sha")==_interpretation(lm)
                    for i,d in enumerate(ds))
                if valid:
                    for d in ds:
                        ev=es[d["evidence_event"]]; er=records.get(ev["task_id"])
                        if not er or er["project"]!=p["id"] or ev.get("lesson")!=lm.get("lesson") or ev.get("prevention")!=lm.get("prevention"):valid=False;break
                        _source(p,er,ev["source"],ev["start"],ev["end"],ev["sha256"])
                if valid and level in ("L3","L4") and ds[-1].get("scope_sha")!=_rule_scope(lm):valid=False
                if check and (check not in CHECKS or ds[-1].get("check")!=check):valid=False
            except Exception:valid=False
        applicable.append({"lesson_id":item["lesson_id"],"cause":cause,"lesson":item["lesson"],"prevention":item["prevention"],
                           "level":level,"effective_level":level if valid or level=="L1" else "L1",
                           "stale_promotion":level!="L1" and not valid,"source":item["path"],"exact_task_family":exact,
                           "tags":match_tags,"explicit_tags":exact_tags,"score":100*int(exact)+20*len(match_tags)+len(overlap),"check":check if valid else None})
    applicable.sort(key=lambda x:(-LEVELS.index(x["effective_level"]),-x["score"],x["lesson_id"]))
    checks=[]
    for a in applicable:
        check=a["check"]
        # Fuzzy matching alone cannot enforce a rule. Must be explicit task family or exact tag.
        if not check or not (a["exact_task_family"] or a["explicit_tags"]):continue
        if check=="lifecycle_consistency":
            blockers=task_lifecycle_blockers(m)
        elif check=="declared_dependency_consistency":
            d=dependencies(root,p["id"]); row=next((x for x in d["tasks"] if x["id"]==task),None)
            blockers=row["unresolved"] if row else []
        elif check=="explicit_task_scope":
            # Only require a declared scope, no permission or arbitrary executable code.
            blockers=[] if m.get("allowed_paths") or m.get("scope") else ["declared_scope_missing"]
        else:continue
        checks.append({"lesson_id":a["lesson_id"],"check":check,"violations":blockers})
    rules=[{"lesson_id":a["lesson_id"],"prevention":a["prevention"]} for a in applicable if a["effective_level"] in ("L3","L4") and (a["exact_task_family"] or a["explicit_tags"])]
    return response("portfolio.preflight",project_id=p["id"],task_id=task,
                    state="blocked" if any(c["violations"] for c in checks) else "advisory",
                    lessons=applicable[:8],applicable_count=len(applicable),checks=checks,required_rules=rules,
                    warnings=warnings,write_performed=False,
                    authority="no authorization inferred; existing release guards remain authoritative")

def recommendations(root,project=None):
    """Escalation candidates by distinct linked tasks; never promote automatically."""
    from .portfolio import lessons
    d=lessons(root,project)
    output=[]
    for item in d["lessons"]:
        m=_header(text_file(item["path"]));events=_events(m)
        tasks={x.get("task_id") for x in events if x.get("task_id")}
        level=m.get("level") or "L1"
        if level not in LEVELS or m.get("status")=="retired":continue
        next_level=LEVELS[LEVELS.index(level)+1] if level!="L4" else None
        output.append({"lesson_id":item["lesson_id"],"root_cause_key":item["root_cause_key"],"level":level,
                       "distinct_evidence_tasks":len(tasks),"observations":len(events),"next_level":next_level,
                       "recommendation":"consider_promotion" if len(tasks)>=2 and next_level else "keep_and_verify",
                       "path":item["path"],"sha256":sha(text_file(item["path"]))})
    return response("portfolio.recommendations",project_id=project or "all",items=output,write_performed=False,
                    authority="repeat count is a signal, not verification or promotion authority")
