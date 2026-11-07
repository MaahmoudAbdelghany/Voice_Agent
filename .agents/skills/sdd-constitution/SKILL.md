---
name: sdd-constitution
description: Creates or regenerates the project constitution (spec/mission.md, spec/tech.md, spec/roadmap.md, and optionally spec/architecture.md) for Spec-Driven Development. Use in greenfield projects by interviewing the human, or in brownfield/legacy projects by reverse-engineering the existing codebase, README, TODOs, git history and archived plans. Use when the user says "create the constitution", "adopt SDD in this project", "regenerate the specs", or when spec/ is missing.
---

# sdd-constitution — Mission, Tech Stack, Roadmap

Shared rules: [`.agents/sdd/conventions.md`](../../sdd/conventions.md).

> The constitution is the agreement on key decisions, between the human and the agent and among the humans. It is a **living document**. Later changes go through `sdd-replan`.

## Pick the Mode
- **Greenfield**: no meaningful code yet → interview-driven.
- **Brownfield**: existing code → discover first, then interview only for gaps.
- **Refresh**: `spec/` exists but has drifted → brownfield discovery compared against current `spec/`, output a drift report, then use `sdd-replan` mode C to apply it.

Work on branch `replan/constitution` (conventions §4). **Never refactor or rewrite application code in this skill.**

---

## Step 1 — Discover (brownfield / refresh)
Read and summarise, separating **verified facts** (with file references) from **assumptions**:
- `README.md`, `pyproject.toml`, `uv.lock`, `.env.example` (variable names only), `.github/workflows/`.
- Source tree layout (`src/…`), entry points, tests, scripts, data/knowledge folders.
- `git log --oneline -50` for history and completed work.
- TODO/FIXME comments, issue lists, and any archived plans (`spec/archive/`), used **only as input** for the roadmap.

## Step 2 — Interview (3–8 questions, each with a recommended answer)
Ask only what the code and documents can't tell you:
- Mission tone, target audience, the problem it solves, and what is explicitly out of scope.
- Tech-stack preferences and constraints (company standards, hosting, budget, compliance such as patient data/PII).
- Non-negotiable invariants (latency budgets, safety rules, data residency).
- Roadmap granularity: **small phases, each feature reviewable in one sitting** (recommended).

## Step 3 — Write the Constitution
| File | Content |
|:---|:---|
| `spec/mission.md` | **Product** (what), **Problem** (why), **Target users** (who), **Core goal**, **Scope** (MVP in/out), success metrics, tone |
| `spec/tech.md` | Stack table (layer · technology · version · role), **architectural invariants** (numbered, testable rules), folder conventions, testing & validation stack with the real commands, deployment |
| `spec/roadmap.md` | Living-document header with the SDD loop, phases with goals, and `- [ ] **Feature X.Y**: title (main paths)` lines in small steps. Brownfield: already-built work is `- [x]` |
| `spec/architecture.md` | Optional: C4/Mermaid component diagram, data flows, links to ADRs in `spec/adr/` |

Don't create extra files (flows.md, test.md, …) unless the human asks. Keep one source of truth.

## Step 4 — Self-Check
- [ ] Every stack row matches what is really installed (brownfield) or what the human chose (greenfield).
- [ ] Every invariant is concrete and verifiable (numbers, rules), not a slogan.
- [ ] The roadmap's next item is small and has clear prerequisites.
- [ ] Facts vs assumptions are marked; all assumptions are listed for the human.

## Step 5 — 🛑 Human Review
Present in Egyptian Arabic: a summary of each file, assumptions, and open questions. Apply corrections **through the agent**, keeping all three files consistent. After explicit approval: commit `docs(spec): establish project constitution`, then ask before merging to `main`.
Next step: `sdd-feature-spec` for the first unchecked roadmap item.

