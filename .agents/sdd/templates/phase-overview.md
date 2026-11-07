# Phase Overview: Phase N — <Phase Title>

- **Phase branch**: `phase/<N>-<slug>`
- **Roadmap section**: `spec/roadmap.md` → Phase N
- **Execution mode**: Phase mode (default) | Feature-by-feature (sensitive areas)
- **Status**: Draft → Approved (Phase Gate 1) → Implementing → Validated → Approved (Phase Gate 2) → Merged

---

## 1. Phase Goal & Why
Which mission goal this phase serves and what it delivers for clinics/patients once complete.

## 2. Features in This Phase
| Order | Roadmap ID | Folder | Size | Status | Depends on |
|:---|:---|:---|:---|:---|:---|
| 1 | Feature N.1 | `spec/features/feature-…/` | S/M | ✅ Done / ⏳ Spec ready / 🆕 New | — |
| 2 | Feature N.2 | … | … | … | Feature N.1 |

Merge/split decisions made during the interview: …

## 3. Shared Decisions (apply to all features)
| # | Decision | Source (human answer / tech.md / ADR / agent default) | Rationale |
|:---|:---|:---|:---|
| P1 | … | … | … |

## 4. Cross-Feature Architecture & Data Flow
How the features connect (Mermaid welcome), shared modules, interfaces between features, `tech.md` invariants that apply phase-wide.

## 5. Phase-Level Integration Validation
Checks that only make sense once all features exist (end-to-end flow across features). Same tier rules as `sdd-validation`.
- [ ] PI.1 — <end-to-end scenario> → <expected>
- [ ] PI.2 — Full suite: `uv run pytest -v`
- [ ] PI.3 — Lint: `uv run ruff check .`
- [ ] PI.4 — Golden evals (if `src/ai_core/**`, `src/rag/**`, prompts, or models change): `uv run pytest tests/evals/test_golden_evals.py -v`

## 6. Risks & Stop Conditions
| Risk | Mitigation |
|:---|:---|

Stop and ask the human if: a feature stays red after 2 fix attempts, or a fix needs a change to intent, scope, or a `tech.md` invariant.

## 7. Execution Log (filled by the orchestrator)
| Feature | Subagent result | Validation | Local commit | Notes |
|:---|:---|:---|:---|:---|

