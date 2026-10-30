# Requirements Specification: Feature 4.3 — Hybrid RAG Upgrade (`src/rag/hybrid_retriever.py`)

> Traces to parent requirement R4 (R4.1–R4.3) and Architectural Invariant 1 (< 400ms tool budget) in `spec/features/feature-400-enterprise-ai-architecture-and-resilience/requirements.md` and `spec/tech.md`.

---

## 1. Functional Requirements

### R1: Structure-Aware Markdown Chunking (`src/rag/ingestion.py`)
- **R1.1 (Table Row Chunking)**: When parsing a Markdown section containing a table (`| ... |`), the ingestion pipeline must decompose the table into self-contained row-level chunks rather than indexing the entire multi-row table as a single monolithic block.
- **R1.2 (Self-Contained Row Context)**: Each table-row chunk must include:
  1. The parent section title.
  2. Each non-empty cell paired with its corresponding column header (e.g., `اسم الطبيب: ... — التخصص: ... — سعر الكشف: ...`).
  3. Metadata fields `source`, `section`, `category`, and `chunk_type="table_row"`.
- **R1.3 (Atomic FAQ Preservation)**: Caller FAQ sections (`### س ...` or Q&A pairs) must remain intact as single atomic chunks (`chunk_type="faq"`) so a question is never separated from its answer.
- **R1.4 (Long Prose Boundary Splitting)**: Non-table, non-FAQ sections whose body exceeds `rag_chunk_max_chars` (default 800 characters) must be split along paragraph or bullet boundaries, with each resulting chunk retaining the section title prefix and `chunk_type="section"`.
- **R1.5 (Deterministic Chunk Identity)**: Each generated chunk must produce a stable, deterministic point identifier when upserted so repeated ingestion of unchanged content is idempotent.

### R2: Sparse BM25 Keyword Engine (`BM25Index`)
- **R2.1 (Pure-Python Okapi BM25)**: The system must provide an in-memory Okapi BM25 index (`BM25Index`) with configurable parameters $k_1$ (default `1.5`) and $b$ (default `0.75`) using standard inverse document frequency (IDF) weighting.
- **R2.2 (Bilingual Normalization & Tokenization)**: Both indexed chunks and incoming search queries must be normalized via `normalize_query()` (stripping Arabic diacritics/tatweel, unifying `أ/إ/آ → ا`, `ى → ي`, `ة → ه`, converting Arabic-Indic digits `٠-٩ → 0-9`, lowercasing Latin text, and stripping punctuation) before tokenization.
- **R2.3 (Stop-Word & Filler Filtering)**: Tokenization must filter out common Arabic and English stop words and conversational fillers (e.g., `هل`, `عايز`, `اعرف`, `ممكن`, `في`, `من`, `على`, `بكام`, `سعر`, `كام`, `what`, `is`, `the`) while preserving clinical terms, abbreviations (`cbc`, `hba1c`, `esr`, `crp`, `dexa`, `ecg`), doctor names, and numbers (`123`, `19876`, `350`).
- **R2.4 (Category Pre-Filtering)**: When a `category` filter is supplied, `BM25Index.search()` must restrict scoring strictly to chunks whose metadata `category` matches the requested category.

### R3: Reciprocal Rank Fusion (RRF) & Score Calibration
- **R3.1 (Dual Retrieval Execution)**: For every search query (when `hybrid_search_enabled=True`), `HybridKnowledgeRetriever.search()` must execute both Dense Vector search (Qdrant) and Sparse Keyword search (`BM25Index`) over a candidate pool of `max(limit * hybrid_candidate_multiplier, 10)` items per leg.
- **R3.2 (RRF Ranking Formula)**: Candidate lists from Dense and BM25 retrieval must be merged and ordered using Reciprocal Rank Fusion with smoothing constant $k = 60$ (configurable via `hybrid_rrf_k`):
  $$\text{RRF\_score}(d) = \sum_{m \in \{\text{dense}, \text{bm25}\}} \frac{1}{k + \text{rank}_m(d)}$$
  where $\text{rank}_m(d) \ge 1$ is the 1-based rank of document $d$ in retrieval leg $m$.
- **R3.3 (Provenance Metadata)**: Every returned hit dictionary must include:
  - `id`, `text`, `category`, `section`, `source` (backward-compatible fields).
  - `score`: Calibrated relevance score in `[0.0, 1.0]`.
  - `rrf_score`: Raw RRF score rounded to 6 decimal places.
  - `dense_score`: Cosine similarity score from Qdrant (`0.0` if matched by BM25 only).
  - `bm25_score`: Raw Okapi BM25 score (`0.0` if matched by Dense only).
  - `match_sources`: List of contributing legs (`["dense", "bm25"]`, `["dense"]`, or `["bm25"]`).
- **R3.4 (Score Calibration & Threshold Compatibility)**:
  - The calibrated `score` field must remain in `[0.0, 1.0]` so downstream callers (`ClinicKnowledgeSearchTool` with `score_threshold=0.35` and `tests/test_clinic_rag.py` with `score_threshold=0.60`) work without breaking.
  - Chunks corroborated by both Dense and BM25 legs or matching specific domain entities in BM25 must receive a calibrated score boost (capped at `1.0`), whereas out-of-domain queries with zero informative BM25 token matches and dense similarity below `score_threshold` must be filtered out.

### R4: Exact Clinical Entity Recall (Parent R4.3)
- **R4.1 (Lab & Radiology Abbreviations)**: Queries containing English or Arabic test codes/names (e.g., `CBC`, `HbA1c`, `Lipid Profile`, `ESR`, `CRP`, `DEXA Scan`, `CT with Contrast`, `تحليل صورة دم كاملة`, `السكر التراكمي`) must retrieve the exact corresponding test row chunk in the top results.
- **R4.2 (Doctor Names & Fees)**: Queries for a specific physician in the 10-doctor table (e.g., `د. عمرو خالد النجار`, `د. ياسمين عادل إبراهيم`, `د. هالة مصطفى رضوان`, `د. طارق عبد الرحمن سليمان`) must retrieve that specific doctor's schedule and fee row chunk as the top result so the 220-character spoken summary includes their exact shift and examination fee.
- **R4.3 (Insurance & Hotlines)**: Queries mentioning specific insurance providers (`AXA`, `MetLife`, `Bupa`, `NextCare`, `أكسا`, `ميتلايف`) or hotlines (`19876`, `123`) must rank the matching chunk at the top.

### R5: Synchronization, Tool Wiring & Fallback Behavior
- **R5.1 (Automatic Corpus Synchronization)**:
  - Calling `upsert_chunks()` or `recreate_collection()` on `HybridKnowledgeRetriever` must update both the Qdrant collection and the in-memory `BM25Index`.
  - If `HybridKnowledgeRetriever.search()` is called when `BM25Index` is empty but the underlying Qdrant collection already contains points, the retriever must lazily populate `BM25Index` by scrolling the Qdrant collection once.
- **R5.2 (Drop-In Compatibility & Tool Wiring)**:
  - `HybridKnowledgeRetriever` must implement the complete public interface of `QdrantKnowledgeRetriever` (`search`, `upsert_chunks`, `recreate_collection`, `get_context_for_query`, `collection_name`, `client`, `embeddings`).
  - `ClinicKnowledgeSearchTool` (`src/tools/knowledge_search.py`) and `KnowledgeIngestionPipeline` (`src/rag/ingestion.py`) must use `hybrid_retriever` by default when `settings.hybrid_search_enabled` is `True`.
- **R5.3 (Kill Switch & Graceful Degradation)**:
  - Setting `hybrid_search_enabled=False` in `Settings` must bypass BM25/RRF and execute standard dense-only Qdrant search.
  - If the BM25 leg raises an unexpected error during `search()`, the retriever must log a warning and fail open to dense vector results without failing the call.

---

## 2. Non-Functional Requirements

- **NFR1 (Retrieval Latency Budget)**: Total hybrid retrieval latency (local FastEmbed query embedding + in-memory Qdrant dense search + in-memory BM25 search + RRF fusion) must have a median latency **< 100ms** (and strictly within the **< 400ms** tool execution timeout defined in `spec/tech.md` Invariant 1); the BM25 + RRF step alone must execute in **< 5ms** for up to 500 chunks.
- **NFR2 (Zero External Runtime Dependencies)**: The BM25 index and RRF fusion must be implemented in standard Python without adding new third-party packages to `pyproject.toml`.
- **NFR3 (Offline Testability)**: All unit and integration tests for Hybrid RAG must run deterministically using local in-memory Qdrant (`:memory:`) without requiring Qdrant Cloud or external LLM API keys.
- **NFR4 (Voice Synthesis Readiness)**: Every table-row chunk produced by structure-aware chunking must convert cleanly via `clean_markdown_for_speech()` into natural Arabic/English text under 250 characters without orphaned pipe characters (`|`) or missing headers.

---

## 3. Constraints

- **C1**: Do not break or alter the public method signatures of `QdrantKnowledgeRetriever` in `src/rag/retriever.py` or `ClinicKnowledgeSearchTool` in `src/tools/knowledge_search.py`.
- **C2**: Preserve the degraded-mode embedding guard in `ClinicKnowledgeSearchTool.execute()` (`is_semantic == False` returns `error="embeddings_unavailable"`), as verified by existing `tests/test_knowledge_search.py`.
- **C3**: All new configuration parameters (`hybrid_search_enabled`, `hybrid_rrf_k`, `hybrid_bm25_k1`, `hybrid_bm25_b`, `hybrid_candidate_multiplier`, `rag_chunk_max_chars`) must reside in `src/config.py` with sensible defaults so existing `.env` files load without modification.
- **C4**: Do not implement ingestion prompt-injection sanitization (`src/rag/sanitizer.py`) or XML context wrapping (`<retrieved_context>`) in this feature; those belong strictly to **Feature 4.4**.
