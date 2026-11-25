"""Read-only lifecycle projections; explicit links and evidence, never implicit authority."""
from collections import Counter, defaultdict
from pathlib import Path
import json
import re
from .common import fail, frontmatter, response, text_file, within
from .registry import load
from .ownership import owner
from .audit import TASK_ID, task_lifecycle_blockers

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
INTAKE = re.compile(r"^<!-- driftlock-intake:([A-Za-z0-9._-]+):[0-9a-f]{64} -->\n### (IDEA|RESEARCH) ([A-Za-z0-9._-]+)\n", re.M)
TERMINAL = {"closed"}
DEPLOYED = {"deployed", "deployed_pending_close", "deployed_production_verified"}
READY = {"accepted", "accepted_pending_integration", "integrated", "integrated_pending_deploy"}
ACTIVE = {"in_progress", "ready_for_review", "rework_required", "blocked"}
PLAN_END = {"implemented"}

def links(value):
    if value in (None, "", "[]", "null"):
        return []
    if not isinstance(value, str):
        raise ValueError("links must be text")
    if value.startswith("["):
        try:
            result = json.loads(value)
        except ValueError:
            # Existing legacy YAML flow sequences use bare IDs.
            result = [x.strip().strip("'\"") for x in value[1:-1].split(",")] if value.endswith("]") else None
    else:
        result = [x.strip() for x in value.split(",")]
    if not isinstance(result, list) or any(not isinstance(x,str) or not ID.fullmatch(x) for x in result):
        raise ValueError("invalid link IDs")
    return list(dict.fromkeys(result))

def inventory(root, project=None):
    root = Path(root).resolve()
    projects = load(root)["projects"]
    known = {p["id"] for p in projects}
    if project and project not in known:
        fail("PROJECT_SELECTION_REQUIRED", "Unknown project")
    records, captures, warnings = {}, {}, []
    visited = set()
    visited_intake = set()
    for p in projects:
        base = Path(p.get("_resolved_root") or root).resolve()
        for kind, directory in (("task", p["tasks"]), ("plan", p["planning"])):
            folder = within(base, directory, allow_missing=True)
            if not folder.exists():
                continue
            if not folder.is_dir():
                fail("RECORD_ROOT", "Expected directory")
            files = folder.glob("*.md") if kind == "task" else folder.rglob("*.md")
            for f in sorted(files):
                if f in visited or f.is_symlink() or not f.is_file():
                    continue
                visited.add(f)
                try:
                    within(base, str(f.relative_to(base)))
                    body = text_file(f)
                    m = frontmatter(body)
                except Exception as exc:
                    warnings.append({"code":"UNREADABLE_RECORD", "path":str(f), "detail":str(exc)[:200]})
                    continue
                ident = m.get(kind+"_id")
                if not ident:
                    # A plain Markdown ticket is evidence of unresolved identity,
                    # not permission to infer its owner, status or completion.
                    match=re.match(r"^((?:(?:IC|AMZ|INT|BI|KB|GOV)-)?TASK-\d+(?:-[A-Z](?=-|$))?(?:-R\d+)?)(?=-|$)",f.stem) if kind=="task" else None
                    if match:
                        warnings.append({"code":"UNSTRUCTURED_TASK_RECORD","id":match.group(1),"path":str(f)})
                    continue
                if not isinstance(ident,str) or not ID.fullmatch(ident) or (kind=="task" and not TASK_ID.fullmatch(ident)):
                    warnings.append({"code":"INVALID_ID", "path":str(f)})
                    continue
                own = owner(m, kind) or (p["id"] if len(projects)==1 else None)
                r = {"id":ident,"kind":kind,"project":own,"path":str(f),"status":m.get("status"),"review":m.get("review_status"),"title":m.get("title"),"meta":m,"body":body}
                records.setdefault(ident,[]).append(r)
        for kind, rel in p.get("intake",{}).items():
            if kind not in ("idea","research"):
                continue
            f = within(base,rel,allow_missing=True)
            if not f.exists() or f in visited_intake:
                continue
            visited_intake.add(f)
            body = text_file(f)
            matches = list(INTAKE.finditer(body))
            for i, match in enumerate(matches):
                if match[1]!=match[3] or match[2].lower()!=kind:
                    warnings.append({"code":"INVALID_INTAKE_ID","path":str(f)})
                    continue
                end = matches[i+1].start() if i+1<len(matches) else len(body)
                block = body[match.end():end].split("\n## ",1)[0]
                # Only quoted original text is searchable; reconciliation summaries are not authority.
                quoted = "\n".join(line[2:] for line in block.splitlines() if line.startswith("> "))
                header=block.split("\n> ",1)[0]
                bound=re.findall(r"^Linked-Record: ([A-Za-z0-9._-]+)$",header,re.M)
                captures.setdefault(match[1],[]).append({"id":match[1],"kind":kind,"project":p["id"],"path":str(f),"text":quoted,"bound":bound})
    unique = {}
    for ident, variants in records.items():
        if len(variants)!=1:
            # Preserve explicit scope references from every ambiguous variant,
            # without admitting any of them as an authoritative record.
            scope_refs=[]
            for r in variants:
                for field in ("intake_ids","related_tasks","rework_of","plan","plan_id_ref"):
                    raw=r["meta"].get(field)
                    if not raw:continue
                    if field in ("plan","plan_id_ref") and isinstance(raw,str) and raw.endswith(".md"):
                        refs=[raw]
                    else:
                        try:refs=links(raw)
                        except ValueError:refs=[]
                    for target in refs:
                        scope_refs.append({"field":field,"target":target,"project":r["project"],"path":r["path"]})
            warnings.append({"code":"DUPLICATE_RECORD_ID","id":ident,"paths":[r["path"] for r in variants],"scope_refs":scope_refs})
        else:
            unique[ident] = variants[0]
    for ident, variants in captures.items():
        if len(variants)!=1:
            warnings.append({"code":"DUPLICATE_INTAKE_ID","id":ident})
    return projects, unique, captures, warnings

def metadata_links(r,key,warnings):
    try:
        return links(r["meta"].get(key))
    except ValueError:
        warnings.append({"code":"INVALID_LINKS","id":r["id"],"field":key})
        return []

def record_view(r):
    return {k:r[k] for k in ("id","kind","project","path","status","review","title")}

def verified_terminal(r):
    # This is a projection of declared lifecycle, not an independent acceptance check.
    return (r["kind"]=="task" and r["status"] in TERMINAL and r["review"]=="pass"
            and not task_lifecycle_blockers(r["meta"])
            and r["meta"].get("task_contract_version") in ("2",2))

def backlog(root, project=None):
    _, records, captures, warnings = inventory(root,project)
    explicit = defaultdict(list)
    for r in records.values():
        for ident in metadata_links(r,"intake_ids",warnings):
            if ident not in captures or len(captures[ident])!=1:
                warnings.append({"code":"UNRESOLVED_INTAKE_LINK","id":r["id"],"intake_id":ident})
            else:
                explicit[ident].append(r)
    items = []
    for ident, variants in sorted(captures.items()):
        if len(variants)!=1:
            continue
        item = variants[0]
        related = list(explicit.get(ident,[]))
        for target in item["bound"]:
            if target not in records:
                warnings.append({"code":"UNRESOLVED_RECORD_LINK","id":ident,"target":target})
            elif records[target] not in related:
                related.append(records[target])
        if project and project not in ("governance","company") and item["project"]!=project and not any(r["project"]==project for r in related):
            continue
        # A mention in quoted text/body is a candidate, never a binding.
        candidates = [r["id"] for r in records.values() if r not in related and
                      (re.search(r"(?<![A-Za-z0-9_-])"+re.escape(r["id"])+r"(?![A-Za-z0-9_-])",item["text"])
                       or re.search(r"(?<![A-Za-z0-9_-])"+re.escape(ident)+r"(?![A-Za-z0-9_-])",r["body"]))]
        tasks = [r for r in related if r["kind"]=="task"]
        plans = [r for r in related if r["kind"]=="plan"]
        if any(r["status"] in DEPLOYED and r["review"]!="pass" for r in tasks):
            state = "deployed_review_pending"
        elif tasks and all(verified_terminal(r) for r in tasks) and all(r["status"] in PLAN_END for r in plans):
            state = "closure_review_required"
        elif any(r["status"] in DEPLOYED for r in tasks):
            state = "deployed_acceptance_pending"
        elif any(r["status"] in ACTIVE or r["status"] in READY for r in tasks):
            state = "work_linked"
        elif related:
            state = "linked_planning"
        elif candidates:
            state = "link_review_required"
        else:
            state = "unlinked"
        items.append({"id":ident,"kind":item["kind"],"state":state,"source":item["path"],
                      "linked":[record_view(r) for r in related],"candidate_links":sorted(candidates),
                      "text_excerpt":item["text"][:240]})
    return response("portfolio.backlog",project_id=project or "all",items=items,counts=dict(Counter(x["state"] for x in items)),
                    warnings=warnings,write_performed=False,authority="advisory; no automatic closure or inferred link")

def dependencies(root,project=None):
    _, records, _, warnings = inventory(root,project)
    edges, missing = {}, []
    invalid=set()
    for r in records.values():
        before=len(warnings)
        deps = metadata_links(r,"depends_on",warnings)
        if len(warnings)!=before:invalid.add(r["id"])
        edges[r["id"]]=deps
        for d in deps:
            if d not in records:
                missing.append({"id":r["id"],"dependency":d})
    # Iterative traversal, no recursion depth dependence; return cycles as unresolved nodes.
    from collections import deque
    indegree={k:sum(d in records for d in v) for k,v in edges.items()}
    rev=defaultdict(list)
    for k, ds in edges.items():
        for d in ds:
            if d in records: rev[d].append(k)
    q=deque(sorted(k for k,v in indegree.items() if v==0))
    while q:
        for child in rev[q.popleft()]:
            indegree[child]-=1
            if indegree[child]==0:q.append(child)
    unresolved={k for k,v in indegree.items() if v>0}
    out=[]
    for r in records.values():
        if r["kind"]!="task" or (project and project not in ("governance","company") and r["project"]!=project):
            continue
        if r["status"] in TERMINAL|DEPLOYED:
            continue
        blockers=[]
        for d in edges[r["id"]]:
            dep=records.get(d)
            if not dep or not (verified_terminal(dep) or (dep["kind"]=="plan" and dep["status"] in PLAN_END)):
                blockers.append(d)
        if r["id"] in unresolved: blockers.append("cycle_or_cycle_dependent")
        if r["id"] in invalid: blockers.append("invalid_dependency_metadata")
        if not r["project"]: blockers.append("unknown_owner")
        blockers.extend(task_lifecycle_blockers(r["meta"]))
        out.append({**record_view(r),"dependencies":edges[r["id"]],"unresolved":blockers,
                    "dependency_state":"blocked_or_unknown" if blockers else "no_declared_dependency_blocker"})
    claims=defaultdict(list)
    for r in records.values():
        if r["kind"]!="task" or r["status"] not in ("in_progress","ready_for_review"):continue
        for resource in metadata_links(r,"parallel_resources",warnings):
            claims[resource].append(r)
    collisions=[{"resource":resource,"tasks":[record_view(r) for r in rs]} for resource,rs in sorted(claims.items())
                if len(rs)>1 and (not project or project in ("governance","company") or any(r["project"]==project for r in rs))]
    return response("portfolio.dependencies",project_id=project or "all",tasks=out,missing=missing,resource_conflicts=collisions,
                    cycle_or_dependents=sorted(unresolved),warnings=warnings,
                    authority="advisory only; absence of declared dependencies does not authorize parallel work",write_performed=False)

def lessons(root, project=None, query=None):
    projects, records, _, warnings = inventory(root,project)
    groups=defaultdict(list)
    explicit=defaultdict(list)
    for r in records.values():
        if r["kind"]!="task" or (project and project not in ("governance","company") and r["project"]!=project):
            continue
        # An Rn name is a repeat repair signal, not proof of a common root cause.
        base=re.sub(r"-R[1-9][0-9]*$","",r["id"])
        groups[(r["project"],base)].append(r)
        cause=r["meta"].get("root_cause_key")
        if isinstance(cause,str) and ID.fullmatch(cause):
            explicit[(r["project"],cause)].append(r)
    repeated=[{"project":p,"task_family":base,"attempts":[record_view(r) for r in sorted(rs,key=lambda r:r["id"])],
               "rework_count":sum(r["id"]!=base for r in rs),"interpretation":"review root cause; common task family alone does not prove recurrence"}
              for (p,base),rs in groups.items() if any(r["id"]!=base for r in rs)]
    repeated.sort(key=lambda x:(-x["rework_count"],x["task_family"]))
    evidence=[]
    visited=set()
    for p in projects:
        if project and project not in ("governance","company") and p["id"]!=project:continue
        base=Path(p.get("_resolved_root") or root)
        folder=within(base,"reports/lessons",allow_missing=True)
        if not folder.exists():continue
        if not folder.is_dir():fail("LESSON_DIRECTORY","Expected lesson directory")
        for path in sorted(folder.glob("*.md")):
            if path in visited:continue
            visited.add(path)
            if path.is_symlink() or not path.is_file():continue
            try:
                within(base,str(path.relative_to(base)))
                m=frontmatter(text_file(path))
                if not ID.fullmatch(str(m.get("lesson_id",""))) or not ID.fullmatch(str(m.get("root_cause_key",""))):
                    raise ValueError("invalid lesson identity")
                ids=links(m.get("task_ids"))
                if not ids or any(i not in records or records[i]["project"]!=m.get("project_id") for i in ids):
                    raise ValueError("missing or foreign task source")
                if project and project not in ("governance","company") and m.get("project_id")!=project:continue
                evidence.append({k:m.get(k) for k in ("lesson_id","project_id","root_cause_key","lesson","prevention","evidence","status")}|{"task_ids":ids,"path":str(path)})
            except Exception as exc:
                warnings.append({"code":"INVALID_LESSON","path":str(path),"detail":str(exc)[:200]})
    for item in evidence:
        key=(item["project_id"],item["root_cause_key"])
        known={r["id"] for r in explicit[key]}
        explicit[key].extend(records[i] for i in item["task_ids"] if i not in known)
    causes=[{"project":p,"root_cause_key":c,"tasks":[record_view(r) for r in rs],
             "lesson_ids":[item["lesson_id"] for item in evidence if (item["project_id"],item["root_cause_key"])==(p,c)],
             "interpretation":"operator-recorded cause; evidence still needs verification"} for (p,c),rs in explicit.items()]
    if query:
        q=query.casefold()
        evidence=[x for x in evidence if q in json.dumps(x,ensure_ascii=False).casefold()]
        causes=[x for x in causes if q in json.dumps(x,ensure_ascii=False).casefold()]
        repeated=[x for x in repeated if q in json.dumps(x,ensure_ascii=False).casefold()]
    return response("portfolio.lessons",project_id=project or "all",rework_families=repeated,root_causes=causes,
                    lessons=evidence,warnings=warnings,write_performed=False,authority="recorded lessons and recurrence signals; not independent verification")

def record_lesson(root,project,ident,cause,task_ids,lesson,prevention,evidence,expected_sha,approved):
    from .atomic import change
    from .registry import select
    if not approved:fail("APPROVAL_REQUIRED","Explicit lesson capture approval required")
    p=select(root,project)
    if not ID.fullmatch(ident) or not ID.fullmatch(cause):fail("LESSON_ID","Invalid lesson or root-cause ID")
    _,records,_,_=inventory(root,project)
    try: ids=links(task_ids)
    except ValueError:fail("LESSON_TASKS","Invalid task IDs")
    if not ids or any(i not in records or records[i]["kind"]!="task" or records[i]["project"]!=p["id"] for i in ids):
        fail("LESSON_TASKS","Require unique existing task records owned by selected project")
    # JSON strings are valid scalar YAML; restricted to one line to avoid metadata injection.
    for val in (lesson,prevention,evidence):
        if not isinstance(val,str) or not val.strip() or len(val)>2000 or any(ord(c)<32 for c in val):
            fail("LESSON_TEXT","Require single-line, nonempty lesson/prevention/evidence <=2000 characters")
    rel="reports/lessons/"+ident+".md"
    target=within(p["_resolved_root"],rel,allow_missing=True)
    if target.exists():
        fail("LESSON_EXISTS","Preserve existing lesson; record revision under new ID")
    # Avoid ambiguous quotes/backslashes in the legacy conservative scalar parser.
    values={"lesson_id":ident,"project_id":p["id"],"root_cause_key":cause,"task_ids":json.dumps(ids),
            "lesson":lesson,"prevention":prevention,"evidence":evidence,"status":"captured_unverified"}
    if any(v.startswith(("'",'"')) or v.endswith(("'",'"')) for k,v in values.items() if k in ("lesson","prevention","evidence")):
        fail("LESSON_TEXT","Do not wrap text in quotes")
    content="---\n"+"\n".join(f"{k}: {v}" for k,v in values.items())+"\n---\n\n# Engineering lesson\n\nCaptured evidence and proposed prevention; not a verified root cause or authorization.\n"
    result=change(p["_resolved_root"],rel,expected_sha,content,approve=True,allow_create=True)
    return response("portfolio.record-lesson",project_id=p["id"],lesson_id=ident,**result,execution_context_changed=False)

def resources(root,project=None):
    from decimal import Decimal, InvalidOperation
    _,records,_,warnings=inventory(root,project)
    rows=[]
    totals=defaultdict(lambda:{"tokens":0,"duration_seconds":Decimal(0),"costs":defaultdict(Decimal),"recorded":0,"token_records":0,"duration_records":0})
    seen=set()
    def number(value,integer=False):
        if value is None:return None
        try:n=Decimal(str(value))
        except InvalidOperation:raise ValueError("invalid number")
        if not n.is_finite() or n<0 or n>Decimal("1000000000000000") or (integer and n!=n.to_integral_value()):raise ValueError("invalid number")
        return n
    for r in records.values():
        if r["kind"]!="task" or (project and project not in ("governance","company") and r["project"]!=project):continue
        m=r["meta"]
        if not any(m.get(k) is not None for k in ("token_usage","duration_seconds","cost_amount")):continue
        try:
            # Explicit unique measurement ID prevents double counting repeated snapshots/rework.
            scope=m.get("resource_scope")
            if not r["project"] or not isinstance(scope,str) or not ID.fullmatch(scope):raise ValueError("missing owner or unique resource_scope")
            tok=number(m.get("token_usage"),True)
            dur=number(m.get("duration_seconds"))
            cost=number(m.get("cost_amount"))
            curr=m.get("cost_currency")
            if cost is not None and (not isinstance(curr,str) or not re.fullmatch(r"[A-Z]{3}",curr)):raise ValueError("missing currency")
        except ValueError as exc:
            warnings.append({"code":"INVALID_RESOURCE","id":r["id"],"detail":str(exc)});continue
        rows.append({"id":r["id"],"project":r["project"],"resource_scope":scope,
                     "tokens":int(tok) if tok is not None else None,"duration_seconds":str(dur) if dur is not None else None,
                     "cost_amount":str(cost) if cost is not None else None,"currency":curr})
    scopes=Counter(x["resource_scope"] for x in rows)
    accepted=[]
    for x in rows:
        if scopes[x["resource_scope"]]!=1:
            warnings.append({"code":"DUPLICATE_RESOURCE_SCOPE","id":x["id"],"scope":x["resource_scope"]});continue
        a=totals[x["project"] or "unknown"];a["recorded"]+=1
        if x["tokens"] is not None:a["tokens"]+=x["tokens"];a["token_records"]+=1
        if x["duration_seconds"] is not None:a["duration_seconds"]+=Decimal(x["duration_seconds"]);a["duration_records"]+=1
        if x["cost_amount"] is not None:a["costs"][x["currency"]]+=Decimal(x["cost_amount"])
        accepted.append(x)
    summary={p:{"recorded":v["recorded"],"tokens":v["tokens"] if v["token_records"] else None,"duration_seconds":str(v["duration_seconds"]) if v["duration_records"] else None,"token_records":v["token_records"],"duration_records":v["duration_records"],
                "costs":{c:str(n) for c,n in v["costs"].items()}} for p,v in totals.items()}
    return response("portfolio.resources",project_id=project or "all",measurements=accepted,totals=summary,
                    coverage="explicit task measurements only; missing values unknown; durations are summed effort, not elapsed wall time",
                    warnings=warnings,write_performed=False)

def overview(root,project=None):
    ps, records, _, warnings=inventory(root,project)
    counts=defaultdict(Counter)
    for r in records.values():
        if r["kind"]=="task": counts[r["project"] or "unknown"][str(r["status"] or "unknown")]+=1
    result=[]
    for p in ps:
        if project and project not in ("governance","company") and p["id"]!=project:continue
        active=p.get("active_task")
        r=next((r for r in records.values() if r["project"]==p["id"] and r["path"]==str(Path(p.get("_resolved_root") or root)/active)),None) if active else None
        result.append({"project":p["id"],"active_task":record_view(r) if r else None,
                       "active_pointer":active,"counts":dict(counts[p["id"]]),
                       "active_lifecycle_warnings":task_lifecycle_blockers(r["meta"]) if r else []})
    if counts.get("unknown"):warnings.append({"code":"UNKNOWN_OWNER","count":sum(counts["unknown"].values())})
    return response("portfolio.overview",project_id=project or "all",projects=result,warnings=warnings,write_performed=False,
                    authority="document-derived status, not live service health; no invented percent complete")

def link_record(root,project,ident,target,expected_sha,approved):
    """Add explicit association in existing intake; do not change original capture or task."""
    from .atomic import change
    from .registry import select
    from .common import sha
    if not approved:fail("APPROVAL_REQUIRED","Explicit link approval required")
    p=select(root,project)
    _,records,captures,_=inventory(root,project)
    if len(captures.get(ident,[]))!=1 or target not in records:
        fail("LINK_IDENTITY","Require unique existing intake and target record")
    item=captures[ident][0]
    if item["project"]!=p["id"]:
        fail("LINK_OWNER","Select authoritative intake owner")
    if not records[target]["project"]:
        fail("LINK_OWNER","Target owner unknown")
    if p["id"] not in ("governance","company") and records[target]["project"]!=p["id"]:
        fail("LINK_OWNER","Foreign target")
    rel=p["intake"][item["kind"]]
    path=within(p["_resolved_root"],rel)
    text=text_file(path)
    if sha(text)!=expected_sha:fail("VERSION_CONFLICT","Intake changed")
    if target in item["bound"]:
        return response("portfolio.link",project_id=p["id"],id=ident,target=target,changed=False,sha256=expected_sha)
    match=next((m for m in INTAKE.finditer(text) if m[1]==ident and m[3]==ident),None)
    if not match:fail("LINK_IDENTITY","Capture marker changed")
    # Insert before quoted payload, after identity heading; keep original marker/hash unchanged.
    end=match.end()
    out=text[:end]+f"Linked-Record: {target}\n"+text[end:]
    result=change(p["_resolved_root"],rel,expected_sha,out,approve=True)
    return response("portfolio.link",project_id=p["id"],id=ident,target=target,**result,execution_context_changed=False)

def advise(root,project=None,query=None):
    """Find related prior work and recorded lessons, before new work is authorized."""
    from difflib import SequenceMatcher
    if not query or not query.strip() or len(query)>4000:
        fail("ADVICE_QUERY","Provide a nonempty query up to 4000 characters")
    q=query.strip().casefold()
    _,records,captures,warnings=inventory(root,project)
    def score(text):
        t=text.casefold()[:1200]
        if q in t:return 1.0
        return round(SequenceMatcher(None,q[:320],t[:320],autojunk=False).ratio(),3)
    candidates=[]
    for r in records.values():
        if project and project not in ("governance","company") and r["project"]!=project:continue
        t=" ".join(str(x or "") for x in (r["id"],r["title"],r["meta"].get("root_cause_key"),Path(r["path"]).stem))
        s=score(t)
        if s>=.25:candidates.append({**record_view(r),"similarity":s})
    for ident,variants in captures.items():
        if len(variants)!=1:continue
        item=variants[0]
        # The company inbox is a shared source; search is advisory, not ownership assignment.
        if project and item["project"] not in (project,"governance","company"):continue
        s=score(item["text"])
        if s>=.25:candidates.append({"id":ident,"kind":item["kind"],"path":item["path"],"similarity":s,"excerpt":item["text"][:200]})
    prior=lessons(root,project)
    applicable=[]
    for item in prior["lessons"]:
        s=score(" ".join(str(item.get(k) or "") for k in ("root_cause_key","lesson","prevention")))
        if s>=.25:applicable.append({**item,"similarity":s})
    return response("portfolio.advise",project_id=project or "all",query=query,
                    candidates=sorted(candidates,key=lambda r:(-r["similarity"],r["id"]))[:20],
                    lessons=sorted(applicable,key=lambda r:(-r["similarity"],r["lesson_id"]))[:20],
                    warnings=warnings,write_performed=False,
                    authority="similarity is navigation only; AI/operator verifies actual identity and evidence")
