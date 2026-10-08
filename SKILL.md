---
name: driftlock
description: Govern documentation in small through large multi-agent projects using progressive L0/L1/L2 indexes, deterministic freshness checks, dependency propagation, context budgets, and archive isolation. Use when creating, auditing, reorganizing, validating, compacting, or archiving project docs; detecting stale status or contract files after code changes; establishing a project map; controlling docs/workroom/task/report sprawl; or preserving unresolved user feedback without turning every observation into a task. Also use for multi-project context routing, safe local-only Git work, idea/problem/plan intake without task switching, and governance diagnostics.
---

# Driftlock

Keep current knowledge small and navigable while preserving history outside the
default AI context. Upgrade the existing project structure in place; never
create a competing documentation source of truth.

## Operating Sequence

1. Read the project collaboration rules.
2. Find the single L0 `project_entry` document.
3. Read only its ordered `startup` files.
4. Route the task to the narrowest matching L1 branch via `read_when`.
5. Load deeper contracts or runbooks only when that branch requires them.
6. Exclude archive roots unless the task explicitly investigates history.
7. When unresolved feedback matters, route to the project's authoritative problem/issue intake instead of guessing from chat history or inflating the task board.

If no valid L0 exists, treat the project as unmanaged. Run `discover`; do not
guess which status file is authoritative.

## R5 strict terminal-closure attestation format

For terminal Problem resolved transitions, do not supply an ordinary review
narrative, even if it has a PASS verdict in YAML. Prepare a dedicated
acceptance-only Markdown attestation, independently reviewed and committed
to HEAD, with exactly four fields: task_id, verdict: PASS,
review_status: accepted, and candidate_commit (full 40-char SHA).
Only an empty body or one exact heading is permitted:
# Independent review, # Review outcome,
# Independent acceptance attestation, or
# Independent review: followed by the exact task_id.

The tool checks the attestation content, tracked HEAD identity, TASK closure,
candidate SHA and review metadata, but cannot prove independence or
veracity merely from the file. The operator must verify reviewer provenance
separately, and only explicit approved transitions change Problem state.
If the source review includes historical FAIL attempts, keep those in a
different tracked detailed report. Do not copy them into closure attestation.
This intentionally fails closed instead of trying to understand arbitrary
human prose or model-generated status text.

## R4 closure report authority and shared rework verification

For terminal Problem closure, a report containing historical FAIL/REJECTED/
BLOCKED verdicts is not an acceptable *closure evidence report*, even when
its frontmatter says PASS. Use a concise independent acceptance-only record
with exact task_id and candidate SHA instead; never select a positive word
from a contradictory document.

Both task.check and context.check use the same predecessor-identity gate.
Versioned tasks cannot proceed when a parent is missing, duplicated, or
explicitly belongs to another project. Older undeclared lineage remains a
visible reconciliation warning, not an automatic historical task rewrite.

## R3 remaining independent-review gates

Every governed current TASK with a rework suffix must resolve a unique
authoritative predecessor of the same project; merely matching the predecessor
name pattern is not sufficient. Treat missing or ambiguous lineage as blocked.

A terminal Problem closure report cannot say PASS in metadata while stating
FAIL, rejected, or not independently verified in a Markdown body, including
line-broken conclusions. Ask for an unambiguous verified report instead.

Git read-only commands are not automatically inert: repository fsmonitor
settings can execute helper programs and status can refresh its index. Both
the legacy five-command Driftlock checker and governance readers override
these settings with safe subprocess arguments and environment. Doctor checks
internal freshness but never invokes a project-provided handoff script.
Unknown document result states or conflicting exit codes block the diagnosis.

## R2 release-safety repair scope

R2 found a few more false-acceptance paths even after R1 tests passed.
Never infer accepted review status from a single PASS word: reject ambiguous,
duplicated or conflicting conclusions in a tracked report, and require
explicit independent source verification. A reviewed TASK must also satisfy
the complete versioned lifecycle and candidate contract; Git state alone
cannot confer merge/deploy permission.

Company overview is read-only for records owned by other projects and must
apply the *owning* TASK's remote requirement, not its own permissive default.
The conservative doctor result is review_required until external authority
guards are separately run and freshness is verified. Versioned review and
TASK-closure checks are not equivalent to release authorization.

POSIX file writes use pinned parent directory descriptors, inode-checked locks
and atomic replacements. This assumes the repository's owning OS identity
is trusted; it is not a hardened multiuser service against same-UID malicious
actors. Native Windows file security requires separate validation.

## R1 lifecycle and evidence hardening

Do not close a problem from a plausible filename or a positive word.
The report must be a committed, unchanged structured Review record with
exact task_id and candidate_commit, verdict PASS, review_status accepted.
The TASK itself must be closed with Review PASS. Preserve old Gate/task
association text on every problem-board update.

The read-only doctor command does not execute arbitrary project checkers.
Run authoritative legacy handoff guards separately; report freshness
STALE/UNVERIFIED as review_required rather than passing silently.
Project-wide governance can read cross-project but cannot edit a different
project's formal PLAN. New TASK IDs are locally serialized across all
worktrees and branch records, not across independent clones.

## Reuse the current AI; do not add model configuration

The current assistant/executor interprets new messages directly; Driftlock
does not invoke a second Luna/Sol model, require API keys or configure model
budgets. This only proposes semantic meaning: scripts enforce project identity,
Git consistency, revision guards and task lifecycle. Read
references/ai-operator-contract.md before handling conversational feedback.

Call intake triage for the current project when user feedback may belong to
a Problem, Idea, Research item or existing Plan. It returns source context
without changing TASK, creating records or claiming semantic certainty.
The operator must not pass --approve based on inferred user intent.

## Conversation, task and project boundary

New discussion topics, questions, feature ideas or bug reports never silently
switch the active execution task, change handoff, grant deployment authority or
create a formal TASK. Read references/governance-intake-and-context.md before
handling mid-task feedback and references/governance-planning-and-identity.md
before changing a Plan, project identity, prefix or long-term Skill rules.
The host AI interprets the user's intent and can propose a classification;
the CLI never pretends to passively capture conversations.

## Commands

Resolve the directory containing this `SKILL.md` once as `<skill-root>`. Run
the standard-library CLI from that absolute skill root, not from the target
project's current working directory:

```bash
python3 <skill-root>/scripts/driftlock.py discover <project-root>
python3 <skill-root>/scripts/driftlock.py check <project-root>
python3 <skill-root>/scripts/driftlock.py impact <project-root> [--since COMMIT]
python3 <skill-root>/scripts/driftlock.py verify <project-root> --doc DOC_ID --status-effect initial|changed|unchanged
python3 <skill-root>/scripts/driftlock.py archive-plan <project-root>
python3 <skill-root>/scripts/driftlock.py project list <project-root>
python3 <skill-root>/scripts/driftlock.py project status <project-root> --project governance
python3 <skill-root>/scripts/driftlock.py context check <project-root> --project intelligence
python3 <skill-root>/scripts/driftlock.py intake propose <project-root> --project governance --kind idea --text "new idea"
python3 <skill-root>/scripts/driftlock.py task check <project-root> --project governance --id TASK-171
python3 <skill-root>/scripts/driftlock.py plan list <project-root> --project governance
python3 <skill-root>/scripts/driftlock.py git audit <project-root> --project governance
python3 <skill-root>/scripts/driftlock.py doctor check <project-root> --project governance
python3 <skill-root>/scripts/driftlock.py intake triage <project-root> --project governance --text "user report"
python3 <skill-root>/scripts/driftlock.py problem list <project-root> --project governance
python3 <skill-root>/scripts/driftlock.py problem candidates <project-root> --project governance --text "observed issue"
python3 <skill-root>/scripts/driftlock.py problem reconcile <project-root> --project governance
python3 <skill-root>/scripts/driftlock.py plan validate <project-root> --project governance
python3 <skill-root>/scripts/driftlock.py skill status <project-root> --installed /root/.codex/skills/driftlock
python3 <skill-root>/scripts/driftlock.py task reservations <project-root> --project governance
```

Use `--format json` for agents and automation.

- `discover`, `check`, `impact`, and `archive-plan` are always read-only.
- Among original freshness commands, verify alone writes the lock atomically.
- The optional governance intake record command is a separate, explicitly
  approved writer into a configured authoritative intake file.
- All inspection commands remain read-only, including problem reconcile, plan
  validate, Git audit and installed Skill status.
- Additional explicit writers are problem transition, plan transition and
  serialized task ID reservation. They always require --approve and an
  expected SHA-256 snapshot; they neither authorize TASK execution nor deploy.
- Semantic matching is advisory: no classifier or keyword score can declare a
  user-reported observation a verified defect.
- An existing Company Control task/problem record always remains authoritative;
  never create parallel mutable states.
- Never call `verify` until an AI or human has reviewed the real code,
  configuration, child documents, and contracts.
- Do not verify relevant uncommitted paths. Unrelated dirty paths are allowed.
- In a non-Git project, require explicit `--allow-hash-only` and report the
  reduced assurance.
- Treat malformed index or lock input as structured errors. A read-only command
  must never emit a Python traceback for user-controlled project metadata.

## Freshness And Propagation

Treat lifecycle (`active`, `superseded`, `archived`) as authored metadata.
Treat `CURRENT`, `STALE`, `REVIEW_REQUIRED`, and `UNVERIFIED` as computed state.
Never write computed state back into Markdown.

`check` includes both direct freshness and the mechanically propagated
`REVIEW_REQUIRED` state. Use `impact` when the task also needs the minimal
update queue, propagation reasons, or a `--since` baseline.

Propagate changes according to declared edges:

- `link_only`: validate identity/path only.
- `summary`: review the parent summary.
- `status_only`: wait for explicit `status_effect`; propagate only `changed`.
- `contract`: review parents and all declared `depends_on` consumers.

Dates never override hash or dependency evidence.

## Safety Boundaries

- Do not automatically create authority, semantic summaries, task status,
  blockers, problem records, or next actions. Follow the project's collaboration
  rules before writing semantic intake.
- Do not move, delete, merge, compress, or rewrite documents without a separate
  authorized migration task.
- Do not use text similarity alone to merge documents.
- Keep archive files out of startup, active children, `depends_on`, and
  `watch_paths`.
- Commit the lock file for cross-machine and cross-agent reproducibility.
- Never hand-merge a conflicted lock; retain one valid side and re-run `verify`
  for affected documents.
- Recommend `.gitattributes` with LF rules so raw-byte SHA-256 remains stable
  across platforms.

Exit code `1` means ordinary stale/review state. Git hooks and CI wrappers must
map it to success. Only exit codes `2` and `3` may block.

## References

- Read `references/index-schema-v2.md` before creating indexes, implementing a
  checker, or interpreting errors.
- Read `references/migration-playbook.md` before reorganizing an existing
  project or generating its first lock.
- Read `references/four-layer-architecture.md` when selecting L0/L1/L2/archive
  boundaries.
- Read `references/placement-checklist.md` before adding or moving documents.
- Read `references/project-adaptation.md` when sizing the hierarchy or context
  budgets.
- Read `references/task-system-boundaries.md` when tasks live in WCP, GitHub,
  Jira, Linear, or repository task files.
- Read `references/problem-register-and-feedback.md` when user feedback,
  screenshots, defects, UX complaints, or historical issues need a durable
  current intake path without automatically becoming tasks.
- Read `references/task-identity-and-naming.md` when repository-native tasks
  need stable identities for child scopes, rework rounds, or historical
  traceability.
- Read `references/task-lifecycle-and-status.md` when task state needs to
  distinguish implementation, review, integration, deployment, rework, or final
  closure semantics.
