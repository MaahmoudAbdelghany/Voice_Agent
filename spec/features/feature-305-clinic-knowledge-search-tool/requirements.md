# Requirements: Feature 3.5 — Clinic Knowledge Search Tool (`src/tools/knowledge_search.py`)

## 1. Overview
Requirements for the `search_clinic_knowledge` tool, the embeddings degraded-mode guard, and re-ingestion of the `clinic_kb` collection with real embeddings.

---

## 2. Functional Requirements

### FR-1: Input
- **FR-1.1**: The tool accepts the fields of `ClinicKnowledgeSearchInput`: `query`, `limit` (default 3), `score_threshold` (default 0.35), `category` (optional).
- **FR-1.2**: The query is stripped; an empty/whitespace query (when called directly, bypassing the schema) returns `success=False`, `error="empty_query"` and asks the caller to repeat the question.
- **FR-1.3**: `category` is honored only if it is one of: `general`, `specialties`, `doctors`, `pricing`, `lab_radiology`, `insurance`, `booking_queue`, `safety_guardrails`, `faqs` (case-insensitive). Any other value is ignored (search all categories) and logged at WARNING without failing.

### FR-2: Embeddings Degraded-Mode Guard
- **FR-2.1**: `EmbeddingService.is_semantic` returns `True` only when the real FastEmbed model is loaded; `False` when the hash fallback is in use.
- **FR-2.2**: If `is_semantic` is `False`, the tool performs **no** vector search and returns `success=False`, `error="embeddings_unavailable"`, `found=False`, with a polite message saying the information is not available right now and offering transfer to reception.
- **FR-2.3**: `scripts/ingest_clinic_knowledge.py` exits with a non-zero code and a clear error **before** any upsert/recreate when `is_semantic` is `False`.

### FR-3: Retrieval & Results
- **FR-3.1**: Hits come from `QdrantKnowledgeRetriever.search` with the given `limit`, `score_threshold`, and validated category.
- **FR-3.2**: No hits → `success=True`, `found=False`, `error=None`, polite message that no confirmed information was found, offering transfer to reception. The message must not reference restaurant concepts.
- **FR-3.3**: Hits → `success=True`, `found=True`; `data` contains `ClinicKnowledgeSearchOutput` fields: `query`, `found`, `total_results`, `chunks` (each `KnowledgeChunk` with `id`, `content`, `score`, `section`, `metadata.category`, `metadata.source`), `context_text`, `message`.
- **FR-3.4**: `context_text` joins hits as `[section]\n<cleaned text>` blocks in score order, never exceeding 1200 characters (at least the first block is included, truncated if needed).
- **FR-3.5**: `message` is built from the top hit, markdown-cleaned (remove table pipes/separators, `**`, `#`, `<br>`, `---`), whitespace-collapsed, and trimmed at a sentence/clause boundary to ≤ 250 characters.

### FR-4: Safety Escalation Flag
- **FR-4.1**: If any returned hit has category `safety_guardrails`, `data["escalation_recommended"]` is `True`; otherwise `False` (always present).
- **FR-4.2**: Emergency content (hit text mentions `123`, `إسعاف`, or `طوارئ`): message tells the caller to call the ambulance **123** / go to the nearest emergency department immediately, and offers transfer to reception.
- **FR-4.3**: Other safety content (diagnosis / prescription ban): message politely states the assistant cannot give medical advice over the phone and offers booking with a doctor or transfer to reception.
- **FR-4.4**: The tool never calls `transfer_to_receptionist` itself.

### FR-5: Latency Guard & Warm-up
- **FR-5.1**: `aexecute` / `async_search_clinic_knowledge` enforce a 400ms budget; on timeout → `success=False`, `error="timeout"`, short filler message; never raises.
- **FR-5.2**: `warm_up()` loads the embedding model (and runs one dummy embed) and returns `is_semantic`.

### FR-6: Registry, Callables & Compatibility
- **FR-6.1**: `search_clinic_knowledge` (sync) and `async_search_clinic_knowledge` (async) return `ToolResult`; `ClinicKnowledgeSearchTool` with singleton `clinic_knowledge_search_tool`.
- **FR-6.2**: `TOOL_REGISTRY["search_clinic_knowledge"]` uses `ClinicKnowledgeSearchInput` / `ClinicKnowledgeSearchOutput` with a clinic description; `search_restaurant_knowledge` is removed from the registry.
- **FR-6.3**: Deprecated aliases remain importable from `src.tools.knowledge_search` (and `src.tools`) so legacy imports do not break: `KnowledgeSearchTool`, `knowledge_search_tool`, `search_knowledge`, `async_search_knowledge`, `search_restaurant_knowledge`, `async_search_restaurant_knowledge` → point to the clinic implementation.

### FR-7: Re-ingestion
- **FR-7.1**: After the environment fix, the Qdrant Cloud `clinic_kb` collection is recreated from `knowledge_base/clinic_kb.md` with real embeddings (43 chunks expected).

### FR-8: Error Handling
- **FR-8.1**: Any unexpected retriever/Qdrant exception → `success=False`, `error="search_failed"`, polite retry/transfer message; no unhandled exceptions.

---

## 3. Non-Functional Requirements
- **NFR-1 (Latency)**: warm `execute` median < 400ms against Qdrant Cloud (measured and reported over 10 runs).
- **NFR-2 (Spoken Egyptian Arabic)**: messages are short, polite, TTS-friendly, no markdown symbols.
- **NFR-3 (Privacy)**: the raw query is logged at DEBUG only (it may contain symptoms/health info); INFO logs contain only length, category, and hit count.
- **NFR-4 (Retrieval quality)**: with real embeddings, out-of-domain queries (e.g. food/car questions) do not return hits at the default threshold, and core clinic questions (fees, fasting, insurance, emergency) return a relevant top hit.

---

## 4. Constraints
- **C-1**: No changes to the 3.1 schemas (`ClinicKnowledgeSearchInput`, `ClinicKnowledgeSearchOutput`, `KnowledgeChunk`).
- **C-2**: No behavioural change to `QdrantKnowledgeRetriever` or `KnowledgeIngestionPipeline` chunking/categorization; `EmbeddingService` change is additive only.
- **C-3**: Do not edit `knowledge_base/clinic_kb.md`, `src/agent/*`, or other legacy restaurant tools.
- **C-4**: Never generate facts not present in retrieved chunks; never give diagnosis or drug advice.
- **C-5**: Never upsert fallback (non-semantic) vectors into any Qdrant collection.
