---
name: sdd-validation
description: Defines and executes Spec-Driven Development validation. Use in SPEC mode when writing a feature's validation.md (called by sdd-feature-spec), and in EXECUTE mode after implementation to run every check and record evidence (called by sdd-implement). Covers unit, integration, error/edge-case, regression, build/lint/type, manual/visual, and API/CLI tiers, using only the project's real tools, with strict rules against fabricated tests and a technical justification required for every Not Applicable tier.
---

# sdd-validation — Prove Success With Real Evidence

Shared rules: [`.agents/sdd/conventions.md`](../../sdd/conventions.md) (real commands are in §9).

> **Validation is broader than testing.** Tests are one form of evidence. Validation defines what counts as complete proof that each requirement was really met.

```text
Requirement → What does success mean? → What evidence proves it? → Tests / Manual / API / CLI / Lint / Regression
```

---

## Mode A — SPEC (write `validation.md`)

### A1. Discover real capabilities first
Inspect `pyproject.toml`, `uv.lock`, `.github/workflows/*.yml`, `tests/`, `scripts/`:
- Test runner (`pytest` + `pytest-asyncio`, `asyncio_mode = auto`), package manager (`uv`), linter (`ruff`), type checker (none configured today), entry points (LiveKit worker, Streamlit dashboard, `scripts/*.py`), CI gates (`evals.yml`, `docs.yml`).
- Never require a tool or framework that isn't in the repo. Adding one is a tech-stack change → `sdd-replan`.

### A2. Choose tiers (only when applicable)
| Tier | Use when | Focus |
|:---|:---|:---|
| 1 Unit | Isolated logic: parsers, schemas, pure functions, rules | Known input → expected output, no I/O |
| 2 Integration | Components collaborate (Tool → Repo → DB, Gateway → Cache → LLM, Session → Metrics) | End-to-end data flow and state mutations |
| 3 Error & Edge | Always consider | Abnormal input, outages, timeouts, boundaries, graceful fallback phrases |
| 4 Regression | **Mandatory** whenever existing files, schemas, tables, or core services change | Full suite green |
| 5 Build/Lint/Type | Always (lint); type = N/A until configured | `uv run ruff check .` |
| 6 Manual/Visual | UI, audio, voice UX, dashboard, Arabic phrasing | Exact launch command, steps, what to see/hear |
| 7 API/CLI/App | Exposed entry points, scripts, workers | Real command or request → live output |
| + Golden evals | Changes to `src/ai_core/**`, `src/rag/**`, prompts, models | `uv run pytest tests/evals/test_golden_evals.py -v` with RAGAS thresholds from `tech.md` |

### A3. Write the file
Use [`templates/validation.md`](../../sdd/templates/validation.md). Requirements:
- A **traceability table**: every R/NFR in `requirements.md` → check IDs; every check → a requirement.
- Each check is concrete: test path/name, input, expected result, or exact command plus expected output.
- Latency/cost NFRs from `tech.md` (e.g. tool timeout < 400 ms, voice turn < 800 ms) get a measurable check when the feature touches that path.

---

## Mode B — EXECUTE (after implementation)

1. Run the targeted tests for the feature, then the **full suite** (`uv run pytest -v`), then lint (`uv run ruff check .`), then golden evals if applicable.
2. Run Tier 7 commands that can be run non-interactively. Never run commands that place real calls, send real SMS/WhatsApp, or spend significant paid API budget without asking the human first.
3. Tier 6 (manual) checks: prepare exact instructions for the human. Don't claim them as passed.
4. Fill in **§5 Execution Results** in `validation.md`: ✅ / ❌ / ⏭ N/A per check, with evidence (counts, key output lines). Tick the checkboxes that genuinely passed.
5. Any ❌ → fix the code (or the spec, if the spec was wrong, following the no-drift rule) and re-run. Don't hand over to review with red checks unless the human accepts a documented exception.

---

## Strict Rules ⚖️

### Rule 1 — Never fabricate a tier
No hollow, contrived, or mock-only tests written just to fill a tier. A pure string helper doesn't get a fake DB integration test. Over-mocking that hides the real behaviour under test counts as fabrication.

### Rule 2 — Not Applicable needs a technical justification
```markdown
### Tier 2: Integration Verification
- **Status**: Not Applicable
- **Technical Justification**: This feature is an isolated regex utility with no inter-component calls, no DB access, and no state mutation.
```
Forbidden: "not needed", "not required", "N/A".

### Rule 3 — Only real, discovered commands
Use the exact syntax configured in the repo (`uv run …`). Never invent scripts. If a command fails because it doesn't exist, fix the spec, not the evidence.

### Rule 4 — Evidence or it didn't happen
Never report a check as passed without having run it in this session and seen the output.

