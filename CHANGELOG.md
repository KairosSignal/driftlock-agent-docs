# Driftlock Changelog

## 0.4.3 — R3 gate-closure candidate (2026-10-08)

Independent R3 audited Skill 9f7ae14 / Company a551ac6: FAIL.
Addressed three documented HIGH: multiline failure report acceptance,
missing real rework predecessor in current context, and Git fsmonitor /
optional-index-write execution via legacy and new readers.
Also tightened doctor result state and exit-code consistency; added new
isolated regression tests. Not yet independently accepted, installed,
published, integrated or deployed.


## 0.4.2 — independent R2 focused repair candidate (2026-10-08)

R2 audited frozen Skill 531c779 / Company Control a551ac6 and returned FAIL.
This uninstalled candidate repairs the documented R2 HIGH/PARTIAL paths:
conflicting review verdicts, company alias cross-project PLAN write, incomplete
new-TASK lifecycle checks, quoted branch TASK IDs, owner-specific Git policy,
doctor schema/return codes, false read-only script references and PLAN graph
serialization. POSIX authoritative writers now use pinned directory file
descriptors; all writes remain guarded by CAS and explicit approval.
Add real temporary filesystem and concurrent negative tests. Windows and
hostile same-UID filesystem racing are not claimed fully validated.

## 0.4.1 — independent review R1 repair candidate (2026-10-08)

R1 reviewed a7671f4 (Driftlock) and e78a770 (Company Control): FAIL.
This local R1 repair addresses ten HIGH and three MEDIUM findings with
adversarial tests. Independent R2 is required before any release action.

- Exact, committed structured review acceptance tied to TASK and candidate.
- Fail-closed project identity, Git, TASK, rework and lifecycle validation.
- No arbitrary project code execution inside read-only doctor.
- Preserve Problem Register task/Gate associations.
- Read all worktrees and local branch TASK IDs before local allocation.
- Safe symlink parents and portable filesystem locks.
- Validate PLAN successor graph before authorized writing.
- Full install runtime manifest comparison and legacy identifier tolerance.
- Company Control alias fix and five newly managed Driftlock document nodes.

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
