# Validation Criteria: Feature 4.3 — Hybrid RAG Upgrade (`src/rag/hybrid_retriever.py`)

## 1. Success Definition
Feature 4.3 is complete and verified when:
1. `KnowledgeIngestionPipeline.parse_markdown()` splits Markdown tables in `knowledge_base/clinic_kb.md` (10 doctors, 11 lab tests, 6 radiology exams) into self-contained row-level chunks preserving section titles and column headers, splits long prose sections (`> 800` chars) on paragraph/bullet boundaries, and keeps FAQ items (`س/ج`) atomic.
2. `BM25Index` indexes normalized Arabic/English tokens (via `normalize_query`), filters stop words, supports category filtering, and scores exact clinical terms (`CBC`, `HbA1c`, `DEXA`, `د. عمرو خالد النجار`, `350 ج`, `AXA`) in `< 5ms`.
3. `reciprocal_rank_fusion()` merges Dense Vector (Qdrant) and Sparse Keyword (`BM25Index`) results using $k=60$, attaches `rrf_score`, `dense_score`, `bm25_score`, and `match_sources`, and calibrates `score` in `[0.0, 1.0]`.
4. `HybridKnowledgeRetriever` wraps `QdrantKnowledgeRetriever` as a drop-in replacement, auto-synchronizes `BM25Index` on `upsert_chunks()`, `recreate_collection()`, and lazy Qdrant `scroll()`, and powers `ClinicKnowledgeSearchTool` by default (`hybrid_search_enabled=True`).
5. All unit, integration, edge-case, regression, lint, and CLI verification checks pass offline without regressions.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Scope**: Pure functions and isolated logic in `src/rag/ingestion.py` and `src/rag/hybrid_retriever.py`. File: `tests/test_hybrid_rag.py`.
- **Structure-Aware Chunking (`parse_markdown`)**:
  - [ ] `test_table_row_chunking_preserves_headers`: Parsing `clinic_kb.md` produces dedicated `chunk_type="table_row"` chunks for each of the 10 doctors, 11 lab tests, and 6 radiology procedures, with column headers paired with row values and the parent section title included.
  - [ ] `test_faq_chunks_remain_atomic`: Caller FAQ sections (`### س 1` .. `### س 10`) are parsed with `chunk_type="faq"` and keep both the question (`س`) and full answer (`ج`) in a single chunk.
  - [ ] `test_long_prose_splits_on_boundaries`: A synthetic Markdown section exceeding `rag_chunk_max_chars` splits cleanly on paragraph/bullet boundaries, with every sub-chunk prefixed by the section title.
- **BM25 Tokenization & Scoring (`BM25Index`, `tokenize_for_bm25`)**:
  - [ ] `test_tokenize_for_bm25_normalizes_arabic_and_removes_stopwords`: Unifies Alef/Ya/Ta-Marbuta, converts Arabic-Indic digits (`٣٥٠` → `350`), lowercases English (`HbA1c` → `hba1c`), strips stop words (`هل`, `عايز`, `سعر`, `كام`), and retains domain tokens (`cbc`, `hba1c`, `dexa`, `النجار`, `350`).
  - [ ] `test_bm25_exact_abbreviation_and_doctor_ranking`: Over a sample corpus, queries for `"CBC"`, `"HbA1c"`, `"DEXA"`, and `"د. عمرو خالد النجار"` rank the exact matching document #1 with `bm25_score > 0`.
  - [ ] `test_bm25_category_filtering`: `BM25Index.search(query, category="lab_radiology")` returns only chunks matching `category="lab_radiology"`.
- **Reciprocal Rank Fusion (`reciprocal_rank_fusion`)**:
  - [ ] `test_rrf_math_k60_and_dual_match_promotion`: A chunk appearing at rank 1 in Dense and rank 1 in BM25 receives $\text{rrf\_score} = \frac{1}{61} + \frac{1}{61} \approx 0.032787$, outranking single-leg hits, and carries `match_sources == ["dense", "bm25"]`.
  - [ ] `test_rrf_calibrated_score_within_unit_interval`: All fused hits have `0.0 <= hit["score"] <= 1.0` and include `rrf_score`, `dense_score`, `bm25_score`, `dense_rank`, and `bm25_rank`.

### Tier 2: Integration Verification
- **Scope**: End-to-end collaboration between `KnowledgeIngestionPipeline`, `HybridKnowledgeRetriever` (with in-memory Qdrant + FastEmbed + `BM25Index`), and `ClinicKnowledgeSearchTool`. File: `tests/test_hybrid_rag.py`.
- [ ] `test_hybrid_exact_lab_codes_cbc_and_hba1c`: Querying `"شروط تحليل CBC صورة دم كاملة"` and `"تحليل HbA1c السكر التراكمي"` retrieves the exact corresponding lab test row chunk as the #1 hit (`category == "lab_radiology"`), confirming "لا يشترط الصيام".
- [ ] `test_hybrid_exact_radiology_dexa_and_ct`: Querying `"تحضير فحص DEXA Scan كثافة العظام"` retrieves the DEXA Scan row chunk (`24 ساعة`, `الكالسيوم`) in top results.
- [ ] `test_hybrid_specific_doctor_row_retrieval_and_voice_summary`: Querying `"مواعيد وسعر كشف د. عمرو خالد النجار"` or `"د. ياسمين عادل إبراهيم"` via `ClinicKnowledgeSearchTool` returns `found=True` and includes the exact doctor's shift hours and fee (`350` / `230`) inside the 220-character spoken `message` (proving row chunking fixed the table truncation problem).
- [ ] `test_hybrid_lazy_sync_from_existing_qdrant_collection`: When a new `HybridKnowledgeRetriever` instance is attached to an already-populated Qdrant collection (with an initially empty `BM25Index`), the first `.search()` lazily scrolls Qdrant, populates `BM25Index`, and returns hybrid matches (`"bm25"` in `match_sources`).
- [ ] `test_recreate_collection_clears_bm25_index`: Calling `recreate_collection()` clears both Qdrant points and `BM25Index` documents.

### Tier 3: Error & Edge-Case Verification
- **Scope**: Abnormal inputs, kill switches, out-of-domain queries, and failure resilience. File: `tests/test_hybrid_rag.py`.
- [ ] `test_out_of_domain_query_with_price_stopword_rejected`: Query `"سعر وجبة بيتزا مارجريتا حجم عائلي وخصم التوصيل"` at `score_threshold=0.60` (and via `ClinicKnowledgeSearchTool`) does NOT produce false-positive BM25 hits on `"سعر"` / `"خصم"` and returns `found=False` / empty high-confidence hits.
- [ ] `test_hybrid_kill_switch_falls_back_to_dense_only`: With `hybrid_search_enabled=False`, `HybridKnowledgeRetriever.search()` skips BM25 and returns dense-only results (`match_sources == ["dense"]`).
- [ ] `test_bm25_exception_fails_open_to_dense`: If `bm25_index.search()` raises an unexpected `RuntimeError`, `HybridKnowledgeRetriever.search()` logs a warning and still returns the Qdrant dense results without crashing.
- [ ] `test_empty_and_punctuation_only_queries`: Queries `""`, `"   "`, and `"؟؟؟"` return `[]` safely without division-by-zero or index errors.
- [ ] `test_hybrid_retrieval_latency_sla`: Median latency across 5 representative Arabic/English clinical queries is `< 100ms` (and BM25 + RRF overhead is `< 5ms`).

### Tier 4: Regression Checks
- **Scope**: Existing RAG, tool, caching, and gateway test suites must pass without regressions.
- [ ] `tests/test_clinic_rag.py`: All existing colloquial Arabic retrieval, category isolation, out-of-domain, context assembly, and latency tests pass with the upgraded structure-aware chunking.
- [ ] `tests/test_knowledge_search.py`: All unit and integration tests for `ClinicKnowledgeSearchTool` (including `test_fallback_embeddings_guard`, `test_emergency_question_sets_flag`, `test_out_of_domain_not_found`) pass.
- [ ] `tests/test_cache_normalizer.py`, `tests/test_cache_ladder.py`, `tests/test_prompt_prefix.py`, `tests/test_circuit_breaker.py`, `tests/test_model_gateway.py`, `tests/test_clinic_tools.py`, `tests/test_database.py`: All pass without regression.

### Tier 5: Build, Lint & Type Checks
- [ ] **Lint Check**:
  ```powershell
  uv run ruff check src/rag src/tools/knowledge_search.py src/config.py scripts/ingest_clinic_knowledge.py tests/test_hybrid_rag.py tests/test_clinic_rag.py tests/test_knowledge_search.py
  ```
- [ ] **Format Check**:
  ```powershell
  uv run ruff format --check src/rag/hybrid_retriever.py src/rag/ingestion.py tests/test_hybrid_rag.py
  ```
- [ ] **Import & Package Check**:
  ```powershell
  uv run python -c "from src.rag import BM25Index, HybridKnowledgeRetriever, hybrid_retriever, reciprocal_rank_fusion"
  ```
- **Type Checking**:
  - **Status**: Not Applicable
  - **Technical Justification**: No static type checker (`mypy` or `pyright`) is installed or configured in `pyproject.toml` (`[project.optional-dependencies].dev` contains only `pytest`, `pytest-asyncio`, and `ruff`).

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: Feature 4.3 is a backend retrieval and chunking upgrade in `src/rag/` with no Streamlit UI layout changes or browser visual components. Interactive verification is performed via the CLI ingestion and retrieval runner in Tier 7.

### Tier 7: API / CLI / Application Checks
- [ ] **CLI Knowledge Ingestion & Hybrid Query Verification**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/ingest_clinic_knowledge.py --recreate --test-query "د. عمرو خالد النجار ومواعيد عيادة الأسنان وتحليل HbA1c"
  ```
  - **Expected Output**:
    - Reports structure-aware chunks parsed across all 9 clinic categories.
    - Upserts all chunks into Qdrant and synchronizes the BM25 index.
    - Displays top hybrid search hits with calibrated `score`, `rrf_score`, `dense_score`, `bm25_score`, and `match_sources`.

---

## 3. Automated Execution Commands

```powershell
# 1. Run new Hybrid RAG unit, integration, and edge-case test suite
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_hybrid_rag.py -v

# 2. Run existing RAG and Knowledge Search Tool regression suites
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_clinic_rag.py tests/test_knowledge_search.py -v

# 3. Run full Phase 1-4 regression suite
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_cache_normalizer.py tests/test_cache_ladder.py tests/test_prompt_prefix.py tests/test_circuit_breaker.py tests/test_model_gateway.py tests/test_clinic_tools.py tests/test_database.py -v

# 4. Run Ruff linter & import verification
uv run ruff check src/rag src/tools/knowledge_search.py src/config.py scripts/ingest_clinic_knowledge.py tests/test_hybrid_rag.py
uv run python -c "from src.rag import BM25Index, HybridKnowledgeRetriever, hybrid_retriever, reciprocal_rank_fusion"

# 5. Run CLI ingestion & hybrid retrieval verification
$env:PYTHONIOENCODING="utf-8"; uv run python scripts/ingest_clinic_knowledge.py --recreate --test-query "مواعيد وسعر كشف د. عمرو خالد النجار وتحليل CBC"
```
