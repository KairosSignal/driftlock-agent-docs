# Driftlock Next — Plans, Project Identity and Long-term Maintenance

## Distinct identities

Project ID: stable business capability (amazon, intelligence, brand, brain, etc).
Repository: where code currently lives; multiple projects may share a repo.
Task ID: immutable authorized work identity.

The Company Control task tracker remains the source of TASK authorization.
New project prefixes such as AMZ, INT, BI, KB, IC and GOV may be used for new
tasks, but old TASK-171 and other IDs remain unchanged.

Driftlock validates project prefixes but does not allocate sequential TASK IDs.
Do not independently compute max + 1 across several AIs or offline branches;
use a serialized authoritative allocator in the existing task system.

## Document lifecycle

Idea: an uncommitted direction or feature thought.
Problem: a reported or verified defect in the existing problem intake.
Research: questions and evidence; not a verified business conclusion.
Plan: a design proposal or approved architecture path; not execution permission.
ADR: a durable design decision; existing decision files remain authoritative.
TASK: approved scope, executor, tests, Review and release gates.
Report: historical implementation and review evidence.

Before writing a new plan, find an existing plan with the same goal, check
affected contracts and prepare a proposed diff. Approved designs should be
superseded with recorded rationale, not silently rewritten. Unknown legacy
plan status must remain unknown rather than guessed from file timestamps.

## No duplicate systems

Driftlock coordinates external trackers, Git and the Company Control by links
and read-only adapters. It must not create another mutable TASK state store.
Brand research, patents and market intelligence remain specialized Skills or
applications; the governance Skill only routes to them.

## Self-improvement

For every real defect in AI collaboration, retain the original user wording,
actual task context, observed mistake, desired behavior and unsafe side effects.
Classify the cause as AI interpretation, missing rules, script behavior or
stale authority; fix the smallest proper layer and add a regression test.

Keep one installable Driftlock Skill with optional internal modules. New
functions must not break the original discover/check/impact/verify/archive-plan
commands. Local-only development is valid. Installing the new Skill, pushing
GitHub and touching production are separate authorized actions.
