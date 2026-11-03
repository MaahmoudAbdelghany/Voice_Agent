# Requirements Specification: Feature 4.9 — Architecture Decision Records (ADRs) & Diagram-as-Code (`spec/adr/`, `spec/architecture.md`)

> Parent spec: `spec/features/feature-400-enterprise-ai-architecture-and-resilience/` (Group 7, step 7.4).

---

## 1. Functional Requirements

### R1: ADR Set (`spec/adr/`)
- **R1.1**: Exactly 9 ADR files must exist, numbered `001`–`009`, with the file names defined in `plan.md` §2.
- **R1.2**: Each ADR must be written in Arabic, wrapped for RTL rendering (`<div dir="rtl" align="right">`). Technical terms, file paths, model IDs, and config keys stay in English inside backticks.
- **R1.3**: Each ADR must begin with a Metadata block containing: **Status** (`Accepted` / `Superseded` / `Proposed`), **Date** (ISO `YYYY-MM-DD`), **Related Feature** (e.g. `Feature 4.3`), and **Code References** (list of backticked repo paths and `Settings` config keys).
- **R1.4**: Each ADR must contain the 4 sections with these exact headings:
  - `## السياق (Context)`
  - `## القرار (Decision)`
  - `## البدائل المرفوضة (Alternatives Rejected)`
  - `## العواقب (Consequences)`
- **R1.5**: "Alternatives Rejected" must list at least **2** concrete alternatives, each with a rejection reason.
- **R1.6**: "Consequences" must state both positive and negative consequences (trade-offs).
- **R1.7**: ADRs must document the **as-built** system: numeric values (thresholds, timeouts, budgets, model IDs) must match `src/config.py` defaults.
- **R1.8**: ADR 003 must explicitly record that OpenAI was rejected as fallback in favor of Gemini `gemini-2.0-flash`, with the reasons.
- **R1.9**: ADR 007 must link to `spec/security/threat_model.md` rather than duplicate it.

### R2: ADR Index & Template
- **R2.1**: `spec/adr/README.md` must contain a table listing all 9 ADRs with columns: number, title (linked), status, related feature.
- **R2.2**: `spec/adr/template.md` must contain the Metadata block and the 4 section headings from R1.4 with placeholder guidance.

### R3: Architecture Document (`spec/architecture.md`)
- **R3.1**: Written in Arabic (RTL) prose; diagram labels use English technical terms.
- **R3.2**: Must contain exactly 6 Mermaid code blocks:
  1. System Context (`flowchart`/`graph`)
  2. Container/Components of `src/` (`flowchart`/`graph`)
  3. Booking call lifecycle (`sequenceDiagram`)
  4. Circuit Breaker + 4 degradation tiers (`stateDiagram-v2`)
  5. Booking workflow state machine (`stateDiagram-v2`)
  6. Clinic DB entities (`erDiagram`)
- **R3.3**: Built components rendered with solid lines; planned components (Phases 5, 6, 8) rendered with dashed lines, a dedicated `classDef planned`, and a `[Planned]` label.
- **R3.4**: State/ER diagrams must reflect real code: circuit breaker states from `src/ai_core/circuit_breaker.py`, workflow states from `src/ai_core/workflow.py`, entities and relations from `src/db/models.py`.
- **R3.5**: Must include a **Technical Debt** section listing legacy restaurant artifacts (`src/tools/order_status.py`, `src/tools/reservation.py`, `src/tools/legacy_schemas.py` and their tests), excluded from diagrams.
- **R3.6**: Must link to the ADR index and to each ADR where the related component appears.

### R4: Docs-Drift Test (`tests/test_architecture_docs.py`)
- **R4.1**: Fails if any of the 9 ADR files is missing or absent from `README.md`.
- **R4.2**: Fails if any ADR lacks a Metadata field (R1.3) or one of the 4 English heading markers `(Context)`, `(Decision)`, `(Alternatives Rejected)`, `(Consequences)`.
- **R4.3**: Fails if any backticked repo path listed under Code References does not exist on disk.
- **R4.4**: Fails if any config key listed under Code References is not a field of `src.config.Settings`.
- **R4.5**: Fails if `architecture.md` does not contain exactly 6 Mermaid blocks with the required diagram types (R3.2) or lacks `classDef planned`.
- **R4.6**: Failure messages must name the offending file and item.

### R5: CI Workflow (`.github/workflows/docs.yml`)
- **R5.1**: Triggers on `pull_request` and `push` to `main`/`master` for paths `spec/**`, `src/**`, `tests/test_architecture_docs.py`, `.github/workflows/docs.yml`, plus `workflow_dispatch`.
- **R5.2**: Uses the same toolchain as `evals.yml` (`astral-sh/setup-uv`, Python 3.11, `uv sync`).
- **R5.3**: Runs only `uv run pytest tests/test_architecture_docs.py -v` and `uv run ruff check tests/test_architecture_docs.py`; requires no secrets.

### R6: Spec Alignment
- **R6.1**: `feature-400.../plan.md` fallback-provider line updated to Gemini `gemini-2.0-flash`, with a reference to ADR 003.
- **R6.2**: `implementation_plan.md` phase list re-numbered to match `spec/roadmap.md` (Phase 4 = Enterprise AI Core, Phase 5 = Voice, Phase 6 = LLMOps, Phase 7 = Dashboard, Phase 8 = Deployment).
- **R6.3**: `spec/tech.md` gains a short "Architecture Documentation" section linking to `spec/architecture.md` and `spec/adr/README.md`.
- **R6.4**: `spec/roadmap.md` marks Feature 4.9 complete **only after** validation is approved.

---

## 2. Non-Functional Requirements
- **NFR1 (Renderability)**: All Mermaid blocks must render on GitHub's native Mermaid renderer; labels with special characters are quoted; no HTML tags inside labels.
- **NFR2 (Readability)**: Each ADR is concise (target ≤ ~150 lines); RTL wrapper applied consistently.
- **NFR3 (Test speed)**: `tests/test_architecture_docs.py` runs in < 5 seconds, with no network access and no API keys.
- **NFR4 (Style)**: Test file passes `ruff check` with repo config (line-length 100, py310).
- **NFR5 (Maintainability)**: Adding a future ADR requires only: copying `template.md`, adding a row to `README.md`, and (optionally) extending the expected list in the test.

---

## 3. Constraints
- **C1**: No changes to application code under `src/`.
- **C2**: No deletion or modification of legacy restaurant files or their tests.
- **C3**: No new dependencies in `pyproject.toml` (test uses stdlib + pytest + existing `src.config`).
- **C4**: No Node/mermaid-cli tooling introduced.
- **C5**: Must not modify `.github/workflows/evals.yml`.
- **C6**: ADRs must not contain secrets, API keys, or real patient data.
