# Post-Validation Review: Feature X.Y — <Feature Title>

## 1. Validation Results Summary
- Automated tests: <N passed, 0 failed> (`<command>`)
- Regression (full suite): <N passed, 0 failed>
- Lint: <clean / issues>
- Manual / visual: <pending human / verified + how>
- Tiers marked N/A: <list + justification present? yes/no>

## 2. The 5 Core Questions
| # | Question | Verdict | Evidence |
|:---|:---|:---|:---|
| 1 | Does it work? | ✅ / ❌ | … |
| 2 | Does it match the spec (all R/NFR/C, no scope creep)? | ✅ / ❌ | … |
| 3 | Does it respect the architecture (`tech.md` invariants, ADRs)? | ✅ / ❌ | … |
| 4 | Is the diff free of unrelated changes? | ✅ / ❌ | … |
| 5 | Is existing behaviour unbroken? | ✅ / ❌ | … |

## 3. Deep Review (if run)
| Lens | Findings | Severity | Action (fixed / backlog / accepted) |
|:---|:---|:---|:---|

## 4. Spec Sync
- Spec files changed during implementation/review: <list or "none">
- Drift found and fixed: <list or "none">

## 5. Verdict
- **Status**: APPROVED-PENDING-HUMAN | REVISION NEEDED
- **Proposed commit message**: `feat(<scope>): implement Feature X.Y <title>`
- **Next step**: Gate 2 — waiting for human approval to commit & push.

