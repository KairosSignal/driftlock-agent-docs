# Driftlock

[![Tests](https://github.com/KairosSignal/driftlock-agent-docs/actions/workflows/test.yml/badge.svg)](https://github.com/KairosSignal/driftlock-agent-docs/actions/workflows/test.yml)

Driftlock is an agent skill and a dependency-free Python CLI for keeping
project documentation aligned with code as a repository changes.

It detects documentation drift deterministically, propagates review impact
through declared dependencies, routes agents through layered indexes, and keeps
archives outside the default context.

## See It in 14 Seconds

![Driftlock animated terminal demo](assets/driftlock-demo.svg)

A change to `src/auth/session.py` makes the authentication contract `STALE` and
propagates `REVIEW_REQUIRED` only through its declared summary chain. The
unrelated billing contract stays `CURRENT` and out of the update queue.

## Why

Long-running projects often accumulate multiple status files, duplicated
architecture notes, stale handoffs, and large archives. An AI agent can then
read the wrong document, repeat completed work, or spend most of its context on
history.

Driftlock makes freshness deterministic. Markdown documents declare their
identity and relationships in a small JSON index block. The CLI records reviewed
content hashes in `.driftlock.lock.json` and reports computed states:

- `CURRENT`
- `STALE`
- `REVIEW_REQUIRED`
- `UNVERIFIED`

## Features

- Progressive L0/L1/L2 documentation indexes
- One project entry point for agent routing
- SHA-256 freshness checks for documents and watched code paths
- Dependency propagation for summaries, status, and contracts
- Git-aware verification with dirty-path protection
- Read-only discovery and archive planning
- Archive isolation from startup context and active dependency graphs
- Optional problem-register pattern that preserves unresolved feedback without
  converting every observation into an authorized task
- Recommended task-lifecycle semantics that distinguish review acceptance,
  integration, deployment, rework, and final closure without imposing a universal
  tracker schema
- Structured JSON output for agents and CI
- Standard-library Python with no runtime dependencies

## Problem Intake Without Task Sprawl

Driftlock distinguishes unresolved observations from authorized work. A project
may keep user feedback, screenshots, UX complaints, or historical defects in an
external issue tracker or in a repository-native current problem register. The
register is optional; the requirement is one authoritative intake path.

A problem record does **not** authorize implementation. Historical feedback
should normally start as `needs_revalidation`, then become `confirmed`,
`obsolete`, `parked`, or linked to an authoritative task after current evidence
is checked. Large registers should stay out of default startup context and be
loaded only when the current task touches the affected area.

See `references/problem-register-and-feedback.md` for the recommended states,
minimum fields, task boundary, deduplication rules, and a Driftlock index
example.

## Driftlock 0.5.0 — evidence-linked portfolio governance

The optional portfolio CLI adds derived project and backlog views, typed
relationships, task dependency analysis, evidence-linked lessons, targeted
recall, and approved rule promotion. It reuses existing project records and
review gates rather than adding a database or background service.

See [portfolio governance](references/portfolio-governance-preview.md) for
commands, requirements and limitations.

## Historical development notes

## Driftlock Unified 0.4.5 — R5 explicit acceptance-attestation protocol

R5 independently reviewed v0.4.4 (69e5ef4) and reported FAIL:
Markdown _FAIL_ / __FAIL__ still bypassed outcome-word parsing.

v0.4.5 does **not** attempt another natural-language classifier. Terminal
Problem closure now requires a dedicated, tracked, unchanged acceptance-only
attestation with **exactly four scalar metadata fields** and a short fixed
heading (or no body). Arbitrary Markdown body content is denied, including
negative/positive prose, emphasis, tables or alternate verdicts.

The four fields are exactly:
- task_id: exact authoritative closed TASK identifier
- verdict: PASS
- review_status: accepted
- candidate_commit: exact 40-character lowercase candidate SHA

Example:

    ---
    task_id: TASK-200
    verdict: PASS
    review_status: accepted
    candidate_commit: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    ---
    # Independent acceptance attestation

The report must be HEAD-committed and match the current local file. It is a
closure *protocol artifact*, not a substitute for independent source review.
Rich reviewer notes and historical FAIL records remain in separate tracked
reports and must be independently checked before acceptance is authorized.

A reviewer saying PASS in a Git file alone cannot cryptographically prove
independence or factual correctness. An operator must verify review provenance
and explicitly authorize transition. No model inferred acceptance from prose.
Existing approvals are not migrated or rewritten automatically.

No installed Skill, Company Control authority, Amazon service or production
environment is touched by this candidate. Independent R6 review is required.

## Driftlock Unified 0.4.4 — R4 minimal acceptance-gate repair candidate

R4 independently reviewed Skill 938dd761 / Company Control a551ac6
and returned FAIL. This isolated candidate fixes R4's two incomplete gates:

- For **terminal Problem resolution only**, a dedicated HEAD-committed review
  report must contain an exact structured PASS but no standalone negative
  outcome token anywhere in its Markdown body. This intentionally refuses
  reports discussing historical FAIL results; write a short clean acceptance
  record instead. This is a fail-closed protocol, not a free-text sentiment
  classifier. It prevents punctuation, Markdown layout and multiline variants
  from creating an alternative terminal verdict.
- Current TASK context and task.check call the same identity-aware rework
  predecessor gate. Missing, duplicate and wrong-owner references block both
  paths. Historical records without an explicit rework_of declaration are
  reported as legacy review warnings, without rewriting old records.
- Adds adversarial tests for negative outcome variants, R1/R10 absence,
  project-owner mismatch, positive closure and legacy compatibility.
- Retains v0.4.3 Git safety boundaries. No current task switch,
  installation, GitHub publication, production deployment or remote API run.

This candidate requires independent R5 review; the previous R4 report remains
an immutable separate audit artifact.

## Driftlock Unified 0.4.3 — R3 final-gate repair candidate

R3 independent review of Skill 9f7ae14 and Company Control a551ac6 was FAIL,
with three remaining HIGH issues and one MEDIUM check-schema issue.

This isolated revision:
- Rejects multi-line Markdown FAIL/rejected review conclusions and split
  phrases indicating the reviewed candidate is not independently verified;
  requires structured, HEAD-committed PASS and exact TASK/commit identity.
- Runs predecessor existence, uniqueness and ownership checks in current
  context in addition to task checks, covering correctly named R1 and R10
  predecessors that are absent from the actual authoritative repository.
- Disables Git optional writes, fsmonitor hooks and unsafe inherited repo
  execution options in BOTH the original five-command checker and new
  governance operations, including the doctor subprocess.
- Validates doctor result-state vocabulary and agreement between check
  results and exit codes. UNKNOWN/BLOCKED document states cannot be treated
  as a clean pass.
- Adds read-only security configuration and negative lifecycle regression
  tests, with no change to existing business or deployment authority.

This version remains a candidate. It cannot authorize installation, release
or deployment merely because its unit tests pass. Actual Windows operation,
same-UID hostile filesystem races and distributed clones remain explicitly
outside the local guarantees.

## Driftlock Unified 0.4.2 — R2 focused security repair candidate

R2 independent review of 531c779 (Skill) and a551ac6 (Company Control)
was FAIL: three HIGH fixed, seven partial, plus two new findings.
This separate worktree addresses the cited R2 edge cases without touching
frozen R2 inputs. It is still a *candidate*, NOT cleared for installation.

- Structured PASS reviews with duplicate or contradictory verdicts and
  explicit negative text cannot close a problem.
- Versioned TASK lifecycle and rework lineage produce the same hard failures
  from task.check and context.check; no implied release from Review PASS.
- Company aggregation cannot edit other projects' formal plans or weaken
  the owning project's remote policy.
- Doctor validates the complete built-in check schema and uses exit 1 for
  review_required. It never runs the external handoff automatically.
- Git checks are read-only with optional locks disabled.
- Quoted task IDs on local branches are included in number reservations.
- POSIX authoritative writes are pinned to verified directory descriptors;
  lock files are checked for regular inode identity. All cooperating PLAN
  writers serialize through a graph-level lock and reject unhealthy graphs.
  Same-UID hostile filesystem mutation and native Windows security require
  separate platform threat-model verification before release.
- References now reflect the actual handoff procedure.

## Previous 0.4.1 Candidate (failed R2)

The predecessor v0.4.0 candidate failed independent Review with ten HIGH and
three MEDIUM findings. This local R1 repair hardens the existing code:

- Problem closure requires a tracked, committed, unchanged structured PASS
  report with exact TASK and candidate SHA plus matching accepted review state.
  A positive word in failed or unrelated prose is never sufficient.
- Problem updates preserve existing Gate and multi-TASK context.
- Scoped project reads/writes enforce record ownership and normalized aliases.
  Company-wide overview permissions cannot edit another project's formal PLAN.
- TASK Review, release permissions, candidate state and Git are checked
  independently. Legacy identifiers are preserved and reported as such.
- Read-only doctor never automatically executes project-provided scripts.
  Run the authoritative Company Control handoff separately. Stale documents
  produce review_required rather than silently reporting all current.
- The prefix allocator scans local registered worktrees plus committed TASK
  records in local branches; the Git-common-dir ledger is still only a local
  guarantee. Task reservations do not authorize construction.
- Portable locking removes unconditional fcntl imports. POSIX ledger parents
  reject symlinks. Actual Windows smoke remains required before release.
- PLAN transitions validate the resulting graph before any authorized write.
- Skill install comparison uses the complete runtime/contract manifest.
- Company Control uses independent project pointers, corrected aliases and
  five additional Driftlock-managed planning/intake documents.

This remains an uninstalled, unpublished candidate, awaiting independent R2
Review. There is no additional model API invocation or deployment.

## Previous 0.4.0 Candidate (failed R1)

This candidate reuses the current AI for natural-language interpretation.
No separate AI model, API key, prompt-router configuration or unattended agent
is involved. See references/ai-operator-contract.md for correct behavior when
a user interrupts construction with a question, new idea or feedback.

Task-ID reservations are synchronized across worktrees sharing one Git common
directory. This is a local-host guarantee, NOT distributed global uniqueness.
Independent clones must reconcile with their authoritative Company Control
before assigning an actual construction TASK. Reservation metadata is stored
in Git's shared metadata and needs an independent backup.

Adds end-to-end governance operations for company-scale local-only engineering,
without replacing existing Company Control TASK and Problem Register authority.

Production-grade deterministic operations included in this development candidate:

- Read the existing markdown Problem Register, propose similar-issue matches
  without silently merging, capture new feedback into its existing table,
  reconcile related TASK states and apply authorized lifecycle transitions.
- Validate formal PLAN status and dependency/supersedes graph, trace consumers
  and perform explicitly approved, exact-hash status changes.
- Reserve project-prefixed TASK IDs with single-filesystem locking; reservation
  never grants construction approval and is not a distributed allocator.
- Audit Git worktrees/branches, unique unmerged commits and remote divergence.
- Detect installed Skill version drift and diagnose cross-project handoffs.
- Apply a local-only remote policy only when explicitly configured.

Use commands such as:

    python3 scripts/driftlock.py problem reconcile /path/to/company --project governance
    python3 scripts/driftlock.py problem candidates /path/to/company --project governance --text "observed bug"
    python3 scripts/driftlock.py plan validate /path/to/company --project governance
    python3 scripts/driftlock.py task reserve /path/to/company --project governance --expected-sha CURRENT_HASH --approve
    python3 scripts/driftlock.py skill status /path/to/company --installed /root/.codex/skills/driftlock

Writer commands require explicit authorization, IDs, provenance and/or version
hashes. Semantic interpretation and verification evidence remain human/AI-assisted
under existing project rules. The new CLI never pushes, deploys, deletes or
changes an active TASK pointer.

See tests/test_end_to_end.py and references for supported state transitions.

Adds opt-in multi-project governance with one installable Skill, preserving the
original five CLI commands and unchanged index schema/lock format.

Use the existing scripts/driftlock.py entry point:

    python3 scripts/driftlock.py project list /path/to/control
    python3 scripts/driftlock.py doctor check /path/to/control
    python3 scripts/driftlock.py git audit /path/to/control
    python3 scripts/driftlock.py intake propose /path/to/control --kind idea --text "new idea"

For multi-project routing, adapt examples/company-control/projects.json into
the target project's .driftlock/projects.json. Use --project when multiple
logical projects are registered.

For durable user-authorized intake, configure idea/problem/research paths,
then run intake record with --project, --kind, --text, --id, --source,
--expected-sha (SHA-256 of the current file, empty file if none) and --approve.
It atomically appends unverified input and returns the actual path/hash.
It does not create TASKs, switch context, deploy, push, or execute paid calls.

See references/governance-intake-and-context.md and
references/governance-planning-and-identity.md.

The local candidate has NOT replaced the installed Codex Skill and has NOT
been published to GitHub. Deployment/installation remain separate actions.

## Previous Release: 0.2.2

`0.2.2` adds recommended task lifecycle/status semantics so repository-native
projects can distinguish implementation, review acceptance, integration,
deployment, rework, and final closure. It also adds a concrete repository
problem-register adoption checklist while preserving the rule that problem intake
does not authorize implementation.

There is no index-schema change and no breaking CLI command change from `0.2.1`.

## Agent Compatibility

Driftlock is not tied to one model or coding agent:

- Any agent with shell access can run the Python CLI.
- Agents that support `SKILL.md` packages can load the repository as a skill.
- Agents without a skill system can use `SKILL.md` as project instructions and
  call `scripts/driftlock.py` directly.
- Humans and CI can use the same CLI without an agent.

`agents/openai.yaml` provides optional OpenAI/Codex interface metadata. The core
skill and CLI do not import or depend on OpenAI libraries.

## Install

Clone the repository into the skill or instruction directory used by your
agent:

```bash
git clone https://github.com/KairosSignal/driftlock-agent-docs.git
```

Then either register the cloned directory as the `driftlock` skill or run the
CLI from it. Consult your agent's documentation for its skill discovery
directory.

### Codex

Ask Codex to install the public skill:

```text
Install the Driftlock skill from https://github.com/KairosSignal/driftlock-agent-docs
```

Or clone it into the Codex skills directory:

```bash
git clone https://github.com/KairosSignal/driftlock-agent-docs.git \
  ~/.codex/skills/driftlock
```

Restart Codex after installation so the skill is discovered.

## Use With An Agent

For any agent, ask it to read `SKILL.md` and use the bundled CLI:

```text
Read the Driftlock SKILL.md, audit this repository's documentation, and report
the minimum updates needed. Do not read archives unless required.
```

### Codex

Invoke the skill explicitly:

```text
Use $driftlock to audit this repository's documentation and report the minimum
updates needed. Do not read archives unless required.
```

The skill also triggers for documentation audits, reorganization, freshness
validation, archive isolation, project-map creation, and task/report sprawl.

## CLI

Requirements:

- Python 3.9 or newer
- Git 2.25 or newer for commit-aware verification
- Linux, macOS, or Windows

Git is optional only in explicit hash-only mode. Without Git, `verify` requires
`--allow-hash-only` and reports reduced assurance.

Run the CLI directly from the skill directory:

```bash
python3 scripts/driftlock.py discover /path/to/project
python3 scripts/driftlock.py check /path/to/project
python3 scripts/driftlock.py impact /path/to/project --since HEAD~1
python3 scripts/driftlock.py verify /path/to/project \
  --doc project-entry --status-effect initial
python3 scripts/driftlock.py archive-plan /path/to/project
```

Add `--format json` for automation.

`discover`, `check`, `impact`, and `archive-plan` are read-only. `verify` is the
only writing command, and it writes only `.driftlock.lock.json` atomically.

CLI JSON reports and generated lock files include `tool_version`. The current
release line is `0.2.2`.

## File Format

Driftlock uses its own v0.2 format:

- `.driftlock.lock.json` stores verified document state.
- `driftlock-index` is the Markdown metadata fence.
- `scripts/driftlock.py` is the only CLI implementation.

The target repository is always selected at runtime with `project_root`; none of these identifiers are a target-project name.

## Runnable Demo

Run the bundled example from any checkout:

```bash
python3 examples/run_demo.py
```

The demo creates a temporary Git repository, verifies four documents to
`CURRENT`, changes authentication code, and checks that only the authentication
contract and its summary chain enter the update queue. It also demonstrates the
CI contract: exit code `1` is ordinary stale state, while only `2` and `3`
block.

## Minimal Index

Every managed Markdown file contains one fenced `driftlock-index` block with
strict JSON. A minimal L0 entry looks like this:

````markdown
```driftlock-index
{
  "schema_version": 2,
  "id": "project-entry",
  "authority_key": "project.entry",
  "level": 0,
  "role": "project_entry",
  "lifecycle_status": "active",
  "startup": [
    "docs/current/status.md",
    "docs/current/task-board.md"
  ],
  "startup_budget": {
    "max_files": 5,
    "max_characters": 12000
  },
  "archive_roots": [
    "docs/archive"
  ]
}
```
````

Use `discover` first when a repository has no valid L0 entry. It reports
candidates without inventing authority or moving files.

## Recommended Workflow

1. Run `discover` to understand the existing documentation.
2. Establish one L0 entry and narrow L1 branches.
3. Identify the authoritative task system and, when needed, the authoritative
   unresolved-problem/feedback intake. Do not make the task board serve both roles.
4. Add indexes and explicit dependency edges.
5. Review each document and run `verify`.
6. Commit `.driftlock.lock.json` with the reviewed documents.
7. Run `check` in agent workflows or CI.

Driftlock never automatically rewrites semantic content, assigns authority,
moves documents, or deletes archives. Those remain explicit human or agent
decisions.

## Exit Codes

| Code | Meaning |
|---:|---|
| `0` | Current and structurally valid |
| `1` | Ordinary stale, review-required, or unverified state |
| `2` | Structural error or refused verification |
| `3` | Argument, Git, permission, JSON, or filesystem failure |

CI wrappers should treat `0` and `1` as non-blocking and block only on `2` or
`3`.

## Test

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

## License

MIT
### Portfolio governance
See [portfolio governance](references/portfolio-governance-preview.md) for the optional CLI and strict evidence boundaries.
