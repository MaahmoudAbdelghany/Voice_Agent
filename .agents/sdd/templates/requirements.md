# Requirements: Feature X.Y — <Feature Title>

> Decisions and behaviours, not implementation micro-details. Every requirement must be testable and map to at least one check in `validation.md`.

## 1. Functional Requirements
| ID | Requirement | Validated by (validation.md tier / check) |
|:---|:---|:---|
| R1 | The system must … | Tier 1 – … |
| R2 | … | … |

## 2. Non-Functional Requirements
| ID | Requirement (latency budget, safety, PII, cost, accessibility, Arabic UX…) | Validated by |
|:---|:---|:---|
| NFR1 | … | … |

## 3. Constraints (must NOT do / change)
- C1: Must respect `spec/tech.md` invariant "<name>".
- C2: Must not modify <module/behaviour> outside scope.

## 4. Dependencies & Assumptions
- Depends on: Feature X.Y (done), external services, env vars (names only, never values).
- Assumptions (flag clearly; each must be confirmed or accepted at Gate 1).

