# Portfolio governance preview (0.5 candidate)

Owner-authorized isolated upgrade, 2026-11-25. Base 7192084850c72a9caa7c50a93f7903f9485e4618 (accepted 0.4.5). No installation, deployment, registry switch, external model API, daemon, database, or visual interface. Reuse existing PLAN/TASK/intake/report authority. Candidate is not independently accepted.

Use the new CLI from the candidate worktree:
- portfolio overview ROOT: document-derived project and task counts; no fabricated progress percentages.
- portfolio backlog ROOT: exact links vs possible mentions, declared review/deployment/closure states; completed claims need separate evidence and approval. Unlinked legacy entries are not closed automatically.
- portfolio dependencies ROOT: declared dependency graph, missing references, cycles, active tasks sharing declared parallel_resources; no authorization inferred from lack of conflict.
- portfolio lessons ROOT [--query TEXT]: repeated Rn families are recurrence signals, not shared root causes; explicit root_cause_key and approved lesson captures are searchable.
- portfolio advise ROOT --query TEXT: relevant previous work and lesson suggestions; lexical matching is only a navigation hint.
- portfolio resources ROOT: declared unique resource_scope, token_usage, duration_seconds, cost_amount/cost_currency; no estimates for missing records, no cross-currency totals.
- portfolio link ROOT --project GOVERNANCE --id IDEA-ID --target TASK-ID --expected-sha SHA --approve: explicit relationship in existing authoritative intake, CAS guarded.
- portfolio record-lesson ROOT --project OWNER --id LESSON-ID --cause ROOT-CAUSE-KEY --task-ids TASK-ID --lesson TEXT --prevention TEXT --evidence TEXT --expected-sha SHA --approve: new source report in reports/lessons; capture is unverified, no execution authority. New file expected SHA is SHA256 of empty content. Task IDs must have known matching owner. No implicit overwrite.

Existing task or plan frontmatter can include intake_ids, depends_on and parallel_resources (JSON array or simple legacy flow array); tasks can include root_cause_key and resource measurement fields. Metadata absent from older records stays unknown. Explicit link insertion retains original captured text and hash; no automatic final resolution. Do not treat a report as proof of independent acceptance. No changes to existing problem, plan, review or release gates. Before implementation, run advise against the task intent, inspect actual sources and decide applicability; the candidate SKILL.md supplies an explicit operating rule, while automated enforcement in existing execution entrypoints is a separate future step.

Limitations: current preview cannot automatically measure external tokens/cost, assign owners to legacy records, infer undeclared file conflicts, verify semantic recurrence, or replace independent review. The CLI is available but not yet a mandatory preflight in existing workflows. A future explicit completion workflow needs scope-level evidence and human approval; the current backlog is a derived read-only projection.
