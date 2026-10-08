# Driftlock Next — Conversation Intake, Context and Authority

## Core rule

An unexpected topic in the conversation is not permission to change the active task.
The host AI proposes classification, but only a real authorized tool call can make
a durable record. The Skill cannot passively observe other conversations.

Keep two separate contexts:

- Execution context: authorized project/task, branch, SHA, Review and release gates.
- Conversation context: the current question, observation, new idea or investigation.

Discussion does not change execution context. Recording does not create a TASK.

## Routing guidance for the AI

| Intent | Default response | Task switch |
|---|---|---|
| Question | Answer with relevant evidence | No |
| Observation / feedback | Explain uncertainty and optionally suggest intake | No |
| Idea | Compare against existing plans, optionally record | No |
| Research | Investigate within authorized read-only scope | No |
| Planning | Draft/update design under existing authority | No |
| Execute | Verify explicit scope and permissions | Not automatically |
| Switch | Locate the requested TASK and validate live Git | Only if explicit |

The intake proposal CLI does NOT hallucinate intent from keywords. Without an
explicit classification it returns needs_clarification. The caller AI must
distinguish user observation, AI interpretation, verified evidence and user
decision. If uncertain, ask before making durable changes.

## Existing authority takes precedence

Company Control TASK metadata owns lifecycle and permissions; Git owns current
branch and commit; runtime owns deployment facts; the current approved PLAN owns
design authority; an existing Problem Register owns unresolved feedback.
Driftlock governs freshness and consistency, not a second truth database.

The project registry maps logical project IDs to existing files. It can include
an active_task pointer per project without changing a global handoff file.
If an existing tools/handoff.py guard is present, doctor calls it independently.
A new diagnostic must not silently overrule its verdict.

## Durable idea / problem / research capture

When recording is requested, first look for duplicates and identify the existing
authoritative intake. Never convert a casual question into a work item.

Use intake propose for read-only classification. For approved persistence, use
intake record with an explicit project, mapped kind, original text, stable ID,
source and SHA-256 expected file version, plus approve.

The record is quoted as captured_unverified. Same ID and content replay safely;
same ID with different content conflicts. A concurrent file change fails rather
than overwriting other input. An unconfigured kind refuses the write. The command
returns a real path and resulting hash or returns an error.

The managed document will become stale until its semantic change is reviewed.
Never run verify simply to make warnings disappear.

## Git policy

local_only: no remote upstream needed; branch, clean state and candidate still
checked.

remote_tracked: upstream required and divergence examined.

remote_publish_required: remote publication required by the project's release gate.

Missing explicit policy on legacy handoffs does not excuse missing upstream;
doctor also reports the old handoff check.

The CLI never pushes, merges, deploys, changes active pointers, starts paid calls
or deletes branches.
