---
name: sdd-implement
description: Implements an approved feature spec in the Spec-Driven Development loop. Used in feature mode after Gate 1 approval ("implement", "go ahead", "اعتمد", "كمل" on a feature spec, or "implement group N of Feature X.Y"), and by the sdd-phase orchestrator inside each fresh per-feature subagent (in that case: no commit, no review, report back to the orchestrator). Re-reads plan.md, requirements.md and validation.md from disk, implements execution group by execution group, keeps spec and code in sync, then runs sdd-validation (execute mode) and, in feature mode, sdd-review up to Gate 2.
---

# sdd-implement — Build From the Spec (runs until Gate 2)

Shared rules: [`.agents/sdd/conventions.md`](../../sdd/conventions.md).

## Preconditions (stop if any fail)
- The feature spec exists in `spec/features/feature-<id>-<slug>/` and the human gave an explicit approval (Gate 1 in feature mode, or Phase Gate 1 in phase mode).
- You are on the correct `phase/<N>-<slug>` branch (conventions §4). If not, report and ask.
- The working tree contains only expected changes (ideally the committed spec).

## Step 1 — Load Context From Disk
Read `plan.md`, `requirements.md`, `validation.md` of the feature, plus `spec/tech.md` (invariants). Read the source files listed in "Expected Files / Areas Affected". Do not rely on the earlier conversation; the spec is the contract.

## Step 2 — Implement by Execution Group
For each group in `plan.md` §7, in order (or only the groups the human named):
1. Implement only what the group and the requirements ask. **No scope creep**: an extra idea goes to `sdd-research-backlog`, not into the code.
2. Respect every constraint and `tech.md` invariant (centralised config in `src/config.py`, latency budgets, PII redaction before tracing, deterministic write gates, etc.).
3. Write or extend the tests listed in `validation.md` for this group. Tests must exercise real behaviour (no hollow tests; see `sdd-validation` Rule 1).
4. Run the group's targeted tests (`uv run pytest tests/<file>.py -v`) and fix failures before moving on.
5. Preserve existing comments and docstrings that you did not intentionally change.

> For risky areas (security, booking/DB writes, state machine, payments, PII), prefer **one group at a time** with a short report between groups. The human may ask for this explicitly.

## Step 3 — Keep Spec and Code in Sync (no drift)
If you discover during implementation that the spec is wrong, incomplete, or impossible:
- **Small and obvious** (e.g. a file path, an extra helper inside scope): update `plan.md` / `requirements.md` / `validation.md` accordingly, and list the change in your report.
- **Changes intent, scope, or an invariant**: stop, explain in Egyptian Arabic, propose the spec change, and wait for the human.

Never leave code that the spec doesn't describe, or spec items the code silently skipped.

## Step 4 — Validate and Review (automatic, no stop in between)
1. Run the **`sdd-validation` skill in execute mode** (read `.agents/skills/sdd-validation/SKILL.md`).
2. **Feature mode**: run the **`sdd-review` skill** (read `.agents/skills/sdd-review/SKILL.md`), which ends at **Gate 2**.
   **Phase mode (running as an `sdd-phase` subagent)**: skip `sdd-review`. Return your report to the orchestrator. If validation is still red after 2 fix attempts, or a fix needs a change to intent, scope, or a `tech.md` invariant, stop and report instead of improvising.

## Step 5 — Report (in Egyptian Arabic)
Part of the Gate 2 message produced by `sdd-review`:
- What was done per execution group, and **why** (link it to R-IDs).
- Spec changes made during implementation.
- Any manual checks (Tier 6) the human must perform, with exact commands.

Do **not** commit, push, or tick the roadmap here. That happens after Gate 2 in `sdd-review`.

