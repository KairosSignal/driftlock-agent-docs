# Driftlock Changelog

## 0.4.0 — integrated governance candidate (2026-10-08)

- The current AI handles interpretation; no secondary model API or model
  configuration.
- Added read-only grounded conversation triage without task switching.
- Git upstream policies now fail closed when not explicitly configured.
- Closing a problem checks a real linked review report rather than accepting
  a made-up evidence-path string; semantic truth still requires human judgment.
- Local task reservations now share a Git-common-dir ledger across worktrees.


- Existing markdown Problem Register adapter: read/candidates/capture/authorized
  transition/reconcile existing TASKs without duplicated problem storage.
- Governed PLAN validation including dependency graph cycles, supersedes,
  read-only backlink trace and approved status transitions.
- Locally serialized task prefix ID reservations; never new task authorization.
- Read-only Git branch risk inventory with local unique-commit checks.
- Explicit source-versus-installed Skill version comparison.
- Realistic Company Control integration is developed in its own worktree; the
  live worktree and installed v0.2.2 Skill remain unchanged.
- Regression suite expanded for new state and safety boundaries.

## 0.3.0 — initial local candidate (2026-10-08)

- Original five documentation freshness commands preserved.
- Added opt-in project registry and per-project active TASK pointers.
- Added project/context/task/plan/Git/doctor inspections.
- Added non-interrupting conversation intent proposal.
- Added authorized intake recording with idempotent IDs, SHA-256 compare-and-swap,
  and guarded writes into only a configured authoritative intake.
- Added local-only Git policy alongside strict remote validation.
- Added multi-project and failure-mode regression tests.
- No installed Skill replacement or GitHub publication is implied.
