# Validation Criteria: Feature 4.8 — Golden Evaluation Suite & RAGAS CI Gate (`src/ai_core/evals.py`, `tests/evals/`, `.github/workflows/evals.yml`)

## 1. Success Definition
Feature 4.8 is complete and verified when:
1. `tests/evals/golden_dataset.json` contains **52 realistic Egyptian clinic scenarios** (>= 50 required) spanning routine inquiries, appointment bookings/cancellations, adversarial prompt injections, and urgent medical diagnosis traps, all validated against `GoldenEvalCase`.
2. `src/ai_core/evals.py` computes structured exact-match accuracy (`tool`, `specialty`, `escalate`) and the 4 RAGAS metrics (`faithfulness`, `context_recall`, `context_precision`, `answer_relevancy`), supporting both `DeterministicRAGASJudge` and `LiteLLMRAGASJudge` (`openai/gpt-4o-mini` at `temperature=0.0`).
3. `GoldenEvaluationRunner` runs all 52 golden scenarios through the real `InputGuardrail`, `HybridRetriever` (indexed on `knowledge_base/clinic_kb.md`), clinic router, and `OutputGuardrail`, achieving:
   - Structured Exact-Match Pass Rate **`>= 95%`** (`>= 0.95`)
   - Aggregate Faithfulness **`>= 0.90`**
   - Aggregate Context Recall **`>= 0.85`**
   - Aggregate Context Precision **`>= 0.80`**
   - Aggregate Answer Relevancy **`>= 0.85`**
4. `LiteLLMRAGASJudge` strictly **fails closed** (`EvalJudgeError`) when the judge API is unavailable, times out, lacks an API key, or returns invalid JSON.
5. `.github/workflows/evals.yml` is configured with path triggers on prompt/model/RAG PRs, executes the evaluation gate, and outputs the Markdown scorecard to `$GITHUB_STEP_SUMMARY`.
6. All unit, integration, edge-case, regression, lint, and CLI checks pass with zero regressions across Phases 1–4.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Scope**: Isolated unit tests for `GoldenEvalCase` schema validation, structured exact-match scoring, individual RAGAS metric calculations (`faithfulness`, `context_recall`, `context_precision`, `answer_relevancy`), and Markdown report generation. File: `tests/evals/test_golden_evals.py`.
- [x] `test_golden_dataset_schema_and_category_distribution`: Verifies `tests/evals/golden_dataset.json` loads cleanly into `GoldenEvalCase` objects, contains `>= 50` unique scenarios (52 scenarios), and covers all 4 mandatory categories (`routine_inquiry`, `booking_management`, `adversarial_injection`, `medical_safety_trap`).
- [x] `test_structured_exact_match_grading_logic`: Verifies that exact-match passes only when `tool`, `specialty`, and `escalate` all match expected values, and fails when any single field diverges.
- [x] `test_ragas_metrics_reward_grounded_and_penalize_hallucinated_answers`: Verifies that a grounded Arabic clinic response citing the exact fee (`350 جنيه`) and shift hours from retrieved context scores `>= 0.90` on `faithfulness` and `>= 0.85` on `answer_relevancy`, whereas an ungrounded response inventing a fake fee (`999 جنيه`) or off-topic answer drops below threshold.
- [x] `test_context_recall_and_precision_rank_sensitivity`: Verifies that `context_recall` accurately reflects the fraction of `reference_contexts` retrieved and `context_precision` rewards placing the relevant chunk at rank #1 over rank #3.

### Tier 2: Integration Verification
- **Scope**: End-to-end execution of `GoldenEvaluationRunner` over `tests/evals/golden_dataset.json` using the real `InputGuardrail`, `HybridRetriever` (ingesting `knowledge_base/clinic_kb.md`), `OutputGuardrail`, and `LiteLLMRAGASJudge` (with mocked `litellm.acompletion` verifying `gpt-4o-mini` prompt/JSON contract). File: `tests/evals/test_golden_evals.py`.
- [x] `test_full_golden_dataset_meets_exact_match_and_ragas_thresholds`: Runs all 52 golden scenarios through `ClinicEvalPipeline` and `GoldenEvaluationRunner`, asserting `total_cases >= 50`, `structured_exact_match_rate >= 0.95`, `faithfulness >= 0.90`, `context_recall >= 0.85`, `context_precision >= 0.80`, `answer_relevancy >= 0.85`, and `summary.passed is True`.
- [x] `test_litellm_gpt4o_mini_judge_integration_and_markdown_report`: Verifies `LiteLLMRAGASJudge` dispatches `openai/gpt-4o-mini` with `temperature=0.0`, parses structured JSON metric scores, and produces a valid RTL-friendly Markdown report via `format_eval_report_markdown()`.
- [x] `test_github_actions_workflow_structure_and_triggers`: Parses `.github/workflows/evals.yml` and verifies `pull_request` / `push` path filters (`src/ai_core/**`, `src/rag/**`, `knowledge_base/**`, `tests/evals/**`), `pytest tests/evals/test_golden_evals.py` execution step, and `$GITHUB_STEP_SUMMARY` reporting.

### Tier 3: Error & Edge-Case Verification
- **Scope**: Fail-closed behavior when the `gpt-4o-mini` judge is unavailable or returns malformed output, threshold breach detection, and adversarial/safety trap interception. File: `tests/evals/test_golden_evals.py`.
- [x] `test_live_judge_unavailable_or_timeout_fails_closed`: Verifies that when `eval_use_live_judge=True` and `litellm.acompletion` raises a connection/timeout error, lacks an API key, or returns invalid JSON, `LiteLLMRAGASJudge` raises `EvalJudgeError` (fails closed) rather than silently passing.
- [x] `test_suite_fails_gate_when_any_ragas_or_exact_match_threshold_breached`: Verifies that if aggregate `faithfulness`, `context_recall`, `context_precision`, `answer_relevancy`, or `structured_exact_match_rate` falls below the configured threshold in `Settings`, `EvalSuiteSummary.passed` is `False` and `failed_checks` lists the exact breached metric(s).
- [x] `test_adversarial_and_emergency_cases_100_percent_intercepted`: Verifies that 100% of `adversarial_injection` and `medical_safety_trap` cases in `golden_dataset.json` are intercepted by `InputGuardrail` and routed to safe refusal or emergency receptionist escalation (`escalate=True` on emergencies/medical traps).

### Tier 4: Regression Checks
- **Scope**: Existing Phase 1–4 test suites must continue to pass without regression after adding `src/ai_core/evals.py` and evaluation settings in `src/config.py`.
- [x] `tests/test_finops.py`, `tests/test_tracing.py`, `tests/test_workflow_gates.py`, `tests/test_guardrails.py`, `tests/test_hybrid_rag.py`, `tests/test_cache_ladder.py`, `tests/test_model_gateway.py`, `tests/test_circuit_breaker.py`: Verify all Phase 4 AI Core tests pass 100%.
- [x] `tests/test_database.py`, `tests/test_appointment_booking.py`, `tests/test_manage_appointment.py`, `tests/test_doctor_availability.py`, `tests/test_clinic_tools.py`: Verify all Phase 1–3 database and medical tool tests pass 100%.

### Tier 5: Build, Lint & Type Checks
- [x] **Lint Check**:
  ```powershell
  uv run ruff check src/ai_core/evals.py src/ai_core/__init__.py src/config.py tests/evals/
  ```
- [x] **Format Check**:
  ```powershell
  uv run ruff format --check src/ai_core/evals.py src/ai_core/__init__.py src/config.py tests/evals/
  ```
- [x] **Import & Public API Check**:
  ```powershell
  uv run python -c "from src.ai_core.evals import GoldenEvalCase, GoldenCaseCategory, RAGASScores, CaseEvalResult, EvalSuiteSummary, EvalJudgeError, RAGASJudge, DeterministicRAGASJudge, LiteLLMRAGASJudge, ClinicEvalPipeline, GoldenEvaluationRunner, format_eval_report_markdown, load_golden_dataset"
  ```
- **Type Checking**:
  - **Status**: Not Applicable
  - **Technical Justification**: No static type checker (`mypy` or `pyright`) is installed or configured in `pyproject.toml` (`[project.optional-dependencies].dev` contains only `pytest`, `pytest-asyncio`, and `ruff`).

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: Feature 4.8 is an automated evaluation engine, golden benchmark dataset, and GitHub Actions CI gate (`src/ai_core/evals.py`, `tests/evals/`, `.github/workflows/evals.yml`) with no interactive Streamlit UI or visual frontend components.

### Tier 7: API / CLI / Application Checks
- [x] **Live CLI Execution of Golden Evaluation Suite & Markdown Report Generation**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python -c "import asyncio`nfrom src.ai_core.evals import GoldenEvaluationRunner, format_eval_report_markdown`nrunner = GoldenEvaluationRunner()`nsummary = asyncio.run(runner.run_suite())`nassert summary.passed, f'Gate failed: {summary.failed_checks}'`nprint(format_eval_report_markdown(summary))"
  ```

---

## 3. Automated Execution Commands

```powershell
# 1. Run Feature 4.8 Golden Evaluation & RAGAS CI Gate test suite
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/evals/test_golden_evals.py -v

# 2. Run Phase 4 AI Core regression suites
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_finops.py tests/test_tracing.py tests/test_workflow_gates.py tests/test_guardrails.py tests/test_hybrid_rag.py tests/test_cache_ladder.py tests/test_model_gateway.py tests/test_circuit_breaker.py -v

# 3. Run Phase 1-3 Database & Medical Tools regression suites
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_database.py tests/test_appointment_booking.py tests/test_manage_appointment.py tests/test_doctor_availability.py tests/test_clinic_tools.py -v

# 4. Run Ruff linter & format checks
uv run ruff check src/ai_core/evals.py src/ai_core/__init__.py src/config.py tests/evals/
uv run ruff format --check src/ai_core/evals.py src/ai_core/__init__.py src/config.py tests/evals/
```

