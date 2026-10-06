---
name: validation
description: Guides the specification and execution of Spec-Driven Development (SDD) validation. Defines how feature success will be demonstrated using real project capabilities across unit, integration, error/edge-case, regression, build/lint/type, manual/visual, and API/CLI verification, with strict rules against fabricating testing tiers and requiring technical justifications for non-applicable tiers.
---

# SDD Validation Skill (`validation`)

> **"Define how success will be demonstrated using the project's real capabilities."**  
> **Validation is broader than Testing**: Tests are merely one form of evidence. Validation defines what constitutes complete proof of feature success.

```text
Requirement
     ↓
What does success mean?
     ↓
Validation
     ↓
What evidence proves it?
     ↓
Tests / Manual / API / CLI / Build / Lint / Type / Regression
```

---

## 1. Core Principles & Philosophy

### 1.1 Validation > Testing
- **Specification** states *what* must happen.
- **Requirement** defines the expected capability or behavior.
- **Validation** asks: *How do we prove to a human and to the system that this requirement was genuinely fulfilled?*
- Evidence may be a combination of:
  `Unit Tests + Integration Flow + Manual UI Inspection + CLI Output Check + Build Pass`.

### 1.2 "Using the Project's Real Capabilities"
- **Strict Invariant**: Never specify or require testing tools or frameworks that do not actually exist in the repository.
- Inspect the codebase first:
  - What test runner is installed? (e.g., `pytest`, `vitest`, `jest`, `cargo test`)
  - What package/runtime manager is used? (e.g., `uv`, `poetry`, `npm`, `pnpm`)
  - What linters, formatters, and type checkers are configured? (e.g., `ruff`, `mypy`, `eslint`, `tsc`)
  - What CLI or UI entry points exist? (e.g., `streamlit`, `FastAPI`, CLI scripts)
- Base all validation steps exclusively on **actual capabilities discovered in the repository**.

---

## 2. Verification Types (When Applicable)

Include each of the following verification categories **only when applicable** to the feature:

### 1. Unit Verification (التحقق المعزول)
- **Scope**: Isolated functions, algorithms, mathematical logic, pure transformers, input parsers, and schemas.
- **Focus**: Verifying that a single unit responds correctly to known inputs without external dependencies or side effects.
- *Rule*: Only applicable when the feature introduces or modifies isolated logic units.

### 2. Integration Verification (تحقق التكامل بين المكونات)
- **Scope**: Multi-component collaboration and end-to-end flows.
- **Focus**: Interaction between components (e.g., `Router -> Service -> Storage`, or `Tool -> LLM -> Session State`).
- *Rule*: Proves that the end-to-end data flow and state mutations succeed across component boundaries.

### 3. Error & Edge-Case Verification (تحقق الحالات الشاذة والحدودية)
- **Scope**: Abnormal inputs, missing data, service outages, boundary limits, and unexpected states.
- **Focus**:
  - `Normal Case`: System behaves as expected under ideal conditions.
  - `Abnormal Case`: System handles invalid payloads gracefully without unhandled exceptions or crashes.
  - `Boundary Case`: System enforces min/max thresholds, zero-length strings, timeouts, and rate limits.
- *Rule*: Verifies resilience and defensive degradation.

### 4. Regression Checks (تحقق منع الانحدار أو كسر الميزات السابقة)
- **Scope**: Existing behavior and surrounding modules.
- **Focus**: Proving that new additions or refactoring did not break existing features.
- *Rule*: Mandatory whenever editing existing files, schemas, database tables, or core services.

### 5. Build, Lint & Type Checks (تحقق البناء وتكامل الأنواع والأنماط)
- **Scope**: Repository-wide health and static analysis.
- **Focus**:
  - `Build`: Does the project still compile / bundle without errors?
  - `Lint`: Does the code satisfy repository styling rules (e.g., `ruff check`)?
  - `Type Checks`: Are type annotations sound and free of errors (e.g., `mypy`)?
- *Rule*: Uses existing repository scripts and configurations.

### 6. Manual or Visual Verification (التحقق اليدوي والبصري)
- **Scope**: User interfaces, layout aesthetics, animations, responsive breakpoints, audio playback, and human perception.
- **Focus**: Steps for a human supervisor to interact directly with the running application.
- *Rule*: Clearly state the steps: launch command, URL to open, actions to perform, and visual/auditory expectations.

### 7. API / CLI / Application Checks (تحقق واجهات التطبيق المباشرة)
- **Scope**: Exposed entry points (REST/WebRTC/gRPC APIs, CLI subcommands, application runners).
- **Focus**: Running actual commands or sending actual payloads to observe live responses.
- *Rule*: Proves the feature functions as an operational application, not just in mock memory.

---

## 3. Strict Rules & Invariants ⚖️

### ⚠️ Rule 1: Do Not Fabricate a Testing Tier
- **Strict Prohibition**: Never invent artificial, hollow, or contrived tests simply to satisfy a checklist or pretend all tiers are covered.
- If a feature is a pure string helper, do NOT fabricate an integration test involving an artificial database or API call.

### ⚖️ Rule 2: Explicit Exemption with Technical Justification
- If any verification type is genuinely not applicable to the feature, you **MUST** mark it:
  `Status: Not Applicable`
- You **MUST** provide a concrete **Technical Justification** explaining *why* it does not apply.
- *Weak / Forbidden justification*: `"We don't need it"` or `"Not required"`.
- *Strong / Compliant justification*:
  ```markdown
  ### Integration Verification
  - **Status**: Not Applicable
  - **Technical Justification**: This feature consists exclusively of an isolated regex parsing utility with zero inter-service communication, no database interaction, and no persistent state mutations.
  ```

### 💻 Rule 3: Use Actual Discovered Commands
- Always discover and use the exact CLI syntax configured in the project.
- *Examples*:
  - If project uses `uv`: `uv run pytest tests/... -v`
  - If project has npm scripts: `npm run test`, `npm run lint`
  - If project has a custom runner: `python scripts/...`
- Never guess or use generic commands that fail when executed.

---

## 4. Standard Specification Template (`validation.md`)

When creating `spec/features/feature-XXX-<feature-name>/validation.md`, use this structure:

```markdown
# Validation Criteria: Feature XXX — <Feature Name>

## 1. Success Definition
Brief statement defining what evidence will prove this feature is completely successful.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- [ ] Test cases, inputs, and expected outputs for isolated logic.

### Tier 2: Integration Verification
- [ ] Multi-component flow validation (or marked Not Applicable with technical justification).

### Tier 3: Error & Edge-Case Verification
- [ ] Malformed input, timeouts, fallback behavior, boundary values.

### Tier 4: Regression Checks
- [ ] Verification that existing suite passes without regressions.

### Tier 5: Build, Lint & Type Checks
- [ ] Project static analysis and compile commands.

### Tier 6: Manual / Visual Verification
- [ ] Exact manual checklist and browser/terminal interactions.

### Tier 7: API / CLI / Application Checks
- [ ] Live execution commands or endpoint requests.

---

## 3. Automated Execution Commands
\`\`\`powershell
# Actual discovered commands to run
<discovered_command_1>
<discovered_command_2>
\`\`\`
```
