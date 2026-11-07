---
name: sdd-research-backlog
description: Captures an idea, research question, tech-debt item, or risk that comes up mid-feature, without interrupting the current branch's scope or touching the roadmap. Use when the user says "research X", "note this for later", "add to backlog", "what if we used Y instead", or when sdd-implement or sdd-review finds out-of-scope work. Writes spec/backlog/<date>-<slug>.md and indexes it, so sdd-replan can schedule it later.
---

# sdd-research-backlog — Don't Lose Good Ideas, Don't Derail the Feature

Shared rules: [`.agents/sdd/conventions.md`](../../sdd/conventions.md).

## When
- A good idea or open question appears in the middle of a feature (e.g. "should we use PostgreSQL instead of SQLite in production?").
- `sdd-implement` resists scope creep by sending the extra idea here.
- `sdd-review` or a deep review finds a low-severity issue to handle later.

## Steps
1. **Stay in scope**: do not modify application code, the roadmap, or the current feature spec.
2. If it is research: discuss and explore with the human (read code and docs, search the web if needed). Ask 1–4 questions, each with a recommended answer. Record which recommendations the human accepted, changed, or rejected. A changed mind is valuable context; keep it.
3. Write `spec/backlog/<YYYY-MM-DD>-<kebab-slug>.md` from [`templates/backlog-item.md`](../../sdd/templates/backlog-item.md).
4. Add a line to `spec/backlog/README.md` (create it if missing):
   ```markdown
   | Date | Item | Type | Status | Raised during |
   |:---|:---|:---|:---|:---|
   | 2026-11-05 | [Postgres for production](2026-11-05-postgres-production.md) | Research | Open | Feature 5.3 |
   ```
5. Commit with the current work when convenient (`docs(backlog): …`). It is safe on the phase branch because it changes no intent.
6. Tell the human (in Egyptian Arabic) where it was saved. To schedule it later, use `sdd-replan` mode B, which links the backlog file from the roadmap line and sets the Status to `Scheduled`.

## Rules
- The backlog is not the roadmap. Nothing here is a commitment until replanning schedules it.
- One file per topic. Update the existing file instead of duplicating it.

