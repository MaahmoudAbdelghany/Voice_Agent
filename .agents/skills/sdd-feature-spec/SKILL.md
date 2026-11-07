---
name: sdd-feature-spec
description: FEATURE MODE planning in Spec-Driven Development, for a single feature. Phase mode (sdd-phase) is the default; use this skill when the user explicitly wants a single feature ("spec only feature X.Y", "small feature", "one feature at a time"), for sensitive areas (security/PII, DB schema or booking writes, state machine, payments), or for a small ad-hoc idea outside a phase. sdd-phase also reuses its Step 6 quality rules. Runs the clean-slate check, estimates feature size, interviews the human with 3-6 questions (each with a recommended answer), writes plan.md, requirements.md and validation.md, then stops at Gate 1. Never writes application code.
---

# sdd-feature-spec — Plan a Feature (ends at Gate 1)

Shared rules: read [`.agents/sdd/conventions.md`](../../sdd/conventions.md) first (sources of truth, numbering, git, gates, language, right level of detail).

> **The agent is the muscle, the spec is the brain.** This skill produces the brain. It never writes application code.

---

## Inputs
- **Mode `next`** (default, no description given): take the first unchecked `- [ ] Feature X.Y` in `spec/roadmap.md`.
- **Mode `new`** (the human describes something not on the roadmap): `[FEATURE DESCRIPTION]`.

## Step 1 — Clean Slate
Run the Clean-Slate Checklist (conventions §7). If the working tree is dirty or the branch is wrong, report it and ask the human what to do. Do not stash, discard, or switch branches on your own.

## Step 2 — Load Context From Disk (never from memory)
Read, in this order:
1. `spec/mission.md` — what / why / who / scope.
2. `spec/tech.md` — stack and **architectural invariants** (latency budget, safety, PII, etc.).
3. `spec/roadmap.md` — completed items, current phase, next item.
4. `spec/architecture.md` and relevant `spec/adr/*.md`, `spec/security/threat_model.md` when the feature touches those areas.
5. The 1–2 most recent feature folders in `spec/features/` — to match established style and conventions.
6. Relevant source files the feature will touch (read, don't edit).
7. Open items in `spec/backlog/` related to this feature.

Do **not** read `spec/archive/` for decisions.

## Step 3 — Confirm Prerequisites
Verify all prerequisite roadmap items are checked and that the code they promised actually exists. If not, stop and report the gap.

## Step 4 — Estimate Size (agent decides, human can override)
Estimate and state your reasoning in one line:

| Size | Typical signals | What happens |
|:---|:---|:---|
| **Small** | 1–2 execution groups, one module, no new dependency, no invariant touched | One feature folder. In `new` mode: add as next item in the most fitting phase of `roadmap.md`. |
| **Medium** | 3–5 groups, a few modules, maybe one new dependency | One feature folder, implement group by group. |
| **Big** | >5 groups, several independent deliverables, new subsystem, or needs a constitution change (`tech.md` / `mission.md`) | Do **not** write one giant spec. Propose a breakdown into a new phase (or several features) and hand the roadmap change to `sdd-replan` (mode B). After that is approved, spec only the **first** feature of the breakdown. |

## Step 5 — Spec Interview (always)
Ask **3–6 focused questions**, one topic each, every question with a **recommended answer** first. Use the `ask_question` tool when available. Cover only what is genuinely open:
- Scope boundaries (in / out).
- Key technical decisions and trade-offs (e.g. latency vs fidelity, library choice).
- Conflicts you detected with the constitution or existing code.
- How success will be validated (which tiers, manual steps, real commands).
- Your size estimate, if it is not obvious.

Anything already answered by the roadmap, constitution or ADRs → **don't ask**. Decide it and record it in the `Decisions` table of `plan.md` with its source.
Never guess on real ambiguity; ask.

## Step 6 — Write the Three Spec Files
Create `spec/features/feature-<phase><nn>-<slug>/` (numbering rules: conventions §3) using the templates:
1. `plan.md` ← [`templates/plan.md`](../../sdd/templates/plan.md)
2. `requirements.md` ← [`templates/requirements.md`](../../sdd/templates/requirements.md)
3. `validation.md` ← follow the **`sdd-validation` skill in spec mode** (read `.agents/skills/sdd-validation/SKILL.md`) and [`templates/validation.md`](../../sdd/templates/validation.md)

Quality bar:
- Every R/NFR maps to at least one validation check, and every check maps back to a requirement.
- Constraints list the `tech.md` invariants this feature must respect.
- Execution groups are small and each ends in a testable state.
- Right level of detail (conventions §8): intent, constraints, decisions. No variable names.
- In `new` mode for Small/Medium: add the roadmap line `- [ ] **Feature X.Y**: <title> (<main paths>)` in the right phase.

Optional: `summary_ar.md` — a short summary in Egyptian Arabic for the human.

## Step 7 — Self-Check Before Presenting
- [ ] No application code was written or edited.
- [ ] The three files exist and cross-reference each other consistently.
- [ ] Open questions are empty, or explicitly listed for the human.
- [ ] The roadmap change (if any) is limited to adding or renaming this one feature line.

## Step 8 — 🛑 GATE 1: Human Spec Review
Present in **Egyptian Arabic**:
- The size estimate and why.
- The key decisions and trade-offs (the `Decisions` table).
- Assumptions and risks.
- Links to the three files.

Then **stop**. Spec changes requested by the human → update all affected spec files consistently (requirements ↔ validation ↔ plan) and present again.
Only an explicit approval word (conventions §5) unlocks `sdd-implement`. Recommend committing the spec on the phase branch (`docs(spec): add Feature X.Y spec`) and starting implementation in a fresh context.

