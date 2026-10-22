# Validation Criteria: Feature 3.5 — Clinic Knowledge Search Tool (`src/tools/knowledge_search.py`)

## 1. Success Definition
The feature is complete when: FastEmbed loads the real multilingual model (`is_semantic=True`); the Qdrant Cloud `clinic_kb` collection is rebuilt with real embeddings; `search_clinic_knowledge` returns grounded, markdown-free, length-bounded answers for core clinic questions, no hits for out-of-domain questions, the safety escalation flag for emergency/diagnosis questions, and safe failures for fallback embeddings, timeouts, and Qdrant errors; it is registered in `TOOL_REGISTRY` (restaurant entry removed); and unit, integration, edge-case, regression, lint, CLI, and latency checks pass.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Scope**: pure helpers and tool branching with an in-test **stub retriever** (a tiny class returning fixed hit dicts) and a stub embeddings object exposing `is_semantic`. No network.
- **Test cases** (`tests/test_knowledge_search.py`):
  - `test_clean_markdown_for_speech`: table pipes/separators, `**`, `#`, `<br>`, `---` removed; whitespace collapsed.
  - `test_spoken_message_trimmed_to_250`: long top hit → message ≤ 250 chars, ends on a sentence/clause boundary.
  - `test_context_text_bounded_1200`: several long hits → `context_text` ≤ 1200 and contains `[section]` headers in score order.
  - `test_category_validation`: valid category (any case) passed to retriever; unknown category → retriever called with `category=None`.
  - `test_fallback_embeddings_guard`: `is_semantic=False` → `success=False`, `error="embeddings_unavailable"`, retriever **not** called.
  - `test_safety_flag_emergency` / `test_safety_flag_diagnosis` / `test_no_safety_flag_for_normal_hits`: FR-4.1–4.3 messages and flag.
  - `test_embedding_service_is_semantic_false_on_load_failure`: `EmbeddingService` with an invalid model name → `is_semantic is False`.

### Tier 2: Integration Verification
- **Scope**: tool → `QdrantKnowledgeRetriever` → **real FastEmbed** → **Qdrant Cloud** using a dedicated `test_clinic_tool_kb` collection recreated from `clinic_kb.md` (module fixture; skipped with an explicit reason if `is_semantic` is False, so failures are never masked as passes in CI output).
- **Test cases**:
  - `test_fees_question`: "الكشف عند دكتور الأطفال بكام؟" → `found=True`, combined chunks mention `أطفال` and a fee.
  - `test_fasting_question`: "لازم أكون صايم قبل تحليل السكر؟" → top hit category `lab_radiology` or `faqs`.
  - `test_insurance_question`: "بتقبلوا تأمين أكسا؟" → a hit with category `insurance` or `faqs`.
  - `test_emergency_question_sets_flag`: "عندي ألم جامد في صدري ومش قادر أتنفس" → `escalation_recommended=True`, message contains `123`.
  - `test_out_of_domain_not_found`: "سعر بيتزا مارجريتا عائلي" at default threshold → `found=False`.
  - `test_category_filter_strict`: `category="insurance"` → all chunks have category `insurance`.
  - `test_sync_and_async_execution`: both entrypoints return `ToolResult` with the same `found` after `warm_up()`.
  - `test_registry_dispatch` (`tests/test_tools.py`): `execute_tool("search_clinic_knowledge", {...})` → `success=True`, `data["found"] is True`; registry contains `search_clinic_knowledge` with the 3.1 schemas and no `search_restaurant_knowledge`.

### Tier 3: Error & Edge-Case Verification
- **Test cases**:
  - `test_empty_query_direct_call`: `"   "` → `error="empty_query"`.
  - `test_schema_rejects_short_and_long_query`: `execute_tool` with 1-char / 501-char query → `success=False` (schema validation), no exception.
  - `test_no_hits_message_is_clinic_specific`: stub returns `[]` → `found=False`, message has no restaurant words (`مطعم`, `الطعام`).
  - `test_retriever_exception_graceful`: stub raises → `error="search_failed"`.
  - `test_async_timeout`: stub sleeps 1s, tool `timeout_s=0.05` → `error="timeout"`, returns in < 0.5s.
  - `test_ingest_cli_refuses_fallback`: run CLI `main()` with patched `is_semantic=False` → `SystemExit` non-zero, `recreate_collection`/`upsert_chunks` not called.
  - `test_deprecated_aliases_importable`: legacy names import and resolve to the clinic implementation.

### Tier 4: Regression Checks
- `tests/test_clinic_rag.py` (Feature 2.3) — expected to go from **6 failed → passing** after the environment fix + real embeddings; any remaining failure is reported with scores, not silently "fixed" by editing assertions.
- `tests/test_tools.py` (modified), `tests/test_medical_schemas.py`, `tests/test_doctor_availability.py`, `tests/test_appointment_booking.py`, `tests/test_manage_appointment.py`, `tests/test_database.py`, `tests/test_clinic_repository.py`.
- **Known pre-existing legacy failures (not regressions)**: `tests/test_rag.py` (restaurant KB file missing), `tests/test_database_engine.py` (see 3.4 baseline), `tests/test_agent.py` (livekit DLL; if the VC++ install makes it collectable, its restaurant-tool assertions are legacy Phase-5 debt — reported, not fixed here).

### Tier 5: Build, Lint & Type Checks
- `uv run ruff check src/tools/knowledge_search.py src/tools/__init__.py src/rag/embeddings.py scripts/ingest_clinic_knowledge.py tests/test_knowledge_search.py tests/test_tools.py`
- `uv run ruff format --check src/tools/knowledge_search.py src/rag/embeddings.py tests/test_knowledge_search.py`
- Build: `uv run python -c "import src.tools"` imports cleanly.
- Type checking: **Not Applicable** — no type checker (mypy/pyright) is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- **Human environment step (D1)**: supervisor installs *Microsoft Visual C++ Redistributable 2015–2022 x64* (`https://aka.ms/vs/17/release/vc_redist.x64.exe`), then confirms:
  ```powershell
  uv run python -c "from src.rag.embeddings import embedding_service as e; print('is_semantic =', e.is_semantic)"
  ```
  **Expected**: `is_semantic = True` and no `DLL load failed` warning.
- No UI/audio output otherwise; spoken messages are printed in Tier 7 for the supervisor to read.

### Tier 7: API / CLI / Application Checks
- **Re-ingestion (FR-7.1)** against Qdrant Cloud:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/ingest_clinic_knowledge.py --recreate --test-query "الكشف بكام عند دكتور القلب؟"
  ```
  **Expected**: 43 chunks upserted; top hit category `doctors`/`pricing`/`specialties`/`faqs` with a realistic score (well below 0.99).
- **Live tool calls via the dispatcher**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python -c "from src.tools import execute_tool as e; [print(q, '->', (r:=e('search_clinic_knowledge',{'query':q})).success, r.data and r.data.get('found'), r.data and r.data.get('escalation_recommended'), '|', r.message) for q in ['لازم أكون صايم قبل تحليل السكر؟','بتقبلوا تأمين أكسا؟','عندي ألم جامد في صدري ومش قادر أتنفس','سعر بيتزا مارجريتا']]"
  ```
  **Expected**: fasting → found with lab guidance; insurance → found; chest pain → found + `escalation_recommended=True` + `123` in message; pizza → `found=False` with polite clinic message.
- **Latency (NFR-1)**: scratch timing script — `warm_up()` then 10 warm `execute` calls over mixed queries; report median and max (target median < 400ms).

---

## 3. Automated Execution Commands

```powershell
# 0. Environment sanity (after VC++ install)
uv run python -c "from src.rag.embeddings import embedding_service as e; print(e.is_semantic)"

# 1. Feature tests
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_knowledge_search.py tests/test_tools.py -v

# 2. Lint and format
uv run ruff check src/tools/knowledge_search.py src/tools/__init__.py src/rag/embeddings.py scripts/ingest_clinic_knowledge.py tests/test_knowledge_search.py tests/test_tools.py
uv run ruff format --check src/tools/knowledge_search.py src/rag/embeddings.py tests/test_knowledge_search.py

# 3. Regression
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_clinic_rag.py tests/test_medical_schemas.py tests/test_doctor_availability.py tests/test_appointment_booking.py tests/test_manage_appointment.py tests/test_database.py tests/test_clinic_repository.py -v
```
