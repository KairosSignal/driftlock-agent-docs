"""Record authority scopes: physical paths are not project identity."""
import re
from .common import fail

ALIASES = {
    "company_control":"governance", "company control":"governance",
    "incident controller":"incident_controller", "incident-controller":"incident_controller",
    "external intelligence":"intelligence", "amazon agent":"amazon_agent",
    "brand intelligence":"brand_intelligence",
    "amazon":"amazon_agent",
}
PREFIX_PROJECT = {
    "AMZ":"amazon_agent", "INT":"intelligence",
    "BI":"brand_intelligence", "KB":"kairos_brain", "IC":"incident_controller",
    "GOV":"governance",
}

def canonical(raw):
    if not isinstance(raw,str):
        return None
    return ALIASES.get(raw.strip().lower(),raw.strip().lower().replace(" ","_").replace("-","_"))

def owner(meta,kind):
    field="current_project" if kind=="task" else "project_id"
    explicit=canonical(meta.get(field))
    if explicit:
        return explicit
    ident=meta.get("task_id" if kind=="task" else "plan_id")
    if isinstance(ident,str):
        prefix=ident.split("-",1)[0]
        inferred=PREFIX_PROJECT.get(prefix)
        if inferred:return inferred
    return None

def require_owner(meta, project, kind):
    # Company Control's governance overview is an explicitly authorized
    # cross-project aggregator. Per-project reads/writes are strict.
    if project["id"] in ("governance","company"):return
    actual=owner(meta,kind)
    if actual is None:
        fail("RECORD_OWNER_UNKNOWN", "Legacy record must be explicitly reconciled before a scoped edit")
    if actual!=project["id"]:
        fail("PROJECT_OWNER_MISMATCH",f"{kind} belongs to {actual}, not {project['id']}")

def visible(meta,project,kind,only_project_count=None):
    if project["id"] in ("governance","company"):
        return True
    actual=owner(meta,kind)
    # Fallback to legacy single-project mode only when no registry split exists.
    if only_project_count == 1 and actual is None:
        return True
    return actual==project["id"]
