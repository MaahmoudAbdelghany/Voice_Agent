# Requirements Specification: Feature 4.2 — 3-Tier Caching Ladder

> Traces to parent requirements R3 (R3.1–R3.3) and NFR1 in `feature-400-.../requirements.md`.

## 1. Functional Requirements

### R1: Ladder Entry Point
- **R1.1**: `CacheLadder.lookup(query, scope)` must check Tier 1 (exact) then Tier 2 (semantic) and return a `CacheResult`; it must never raise.
- **R1.2**: `CacheScope` carries `category` (optional), `language` (`ar`|`en`, default `ar`), and optional `specialty`.
- **R1.3**: Global and per-tier kill switches (`cache_enabled`, `cache_exact_enabled`, `cache_semantic_enabled`) must be honoured; disabled → `BYPASS` with reason `disabled` (global) or the tier is skipped.

### R2: Tier 1 — Exact Hash Cache
- **R2.1**: Queries must be normalized before hashing: remove tashkeel and tatweel; unify `أ/إ/آ → ا`, `ى → ي`, `ة → ه`; convert Arabic-Indic digits to ASCII; remove punctuation (Arabic and Latin); collapse whitespace; lowercase Latin text.
- **R2.2**: Key = SHA-256 of `normalized_query | category | language | kb_version`.
- **R2.3**: Storage via a `CacheBackend` protocol; default `InMemoryLRUBackend` with per-entry TTL and `cache_max_entries` cap (least-recently-used evicted).
- **R2.4**: Expired entries must never be returned.

### R3: Tier 2 — Metadata-Scoped Semantic Cache
- **R3.1**: Uses a dedicated Qdrant collection (`cache_semantic_collection`, default `semantic_cache`), never the KB collection.
- **R3.2**: Search must be filtered (pre-scoring) by **exact** `category`, `language`, and `kb_version`; a hit requires cosine similarity ≥ `cache_semantic_threshold` (default 0.97) and an unexpired `expires_at`.
- **R3.3**: Tier 2 is skipped when `scope.category` is `None`, when the category is not in the cache allowlist, or when `embedding_service.is_semantic` is `False` (reason `embedding_fallback`, warning logged once).
- **R3.4**: A Tier 2 hit must be promoted into Tier 1 for the same normalized query.
- **R3.5**: Tier 2 (embedding + search) is bounded by `cache_semantic_timeout_ms` (default 50ms); the synchronous embedding runs off the event loop. Timeout → `MISS` with `bypass_reason=timeout`.

### R4: Tier 3 — Prompt Prefix Cache
- **R4.1**: `PromptPrefixBuilder` must produce messages ordered: static instructions → tool schemas → few-shot examples → dynamic context (date/time, caller/session data, retrieved context) → conversation history.
- **R4.2**: The static prefix must be byte-identical across calls with different dynamic context, and `prefix_hash` (SHA-256 of the static prefix) must be stable.
- **R4.3**: The builder must reject dynamic placeholders (e.g. `{current_datetime}`) inside static sections.

### R5: Cacheability Policy (privacy — parent R3.2)
- **R5.1**: Only categories in `cache_allowed_categories` (default: `general`, `specialties`, `pricing`, `lab_radiology`, `insurance`, `faqs`) are cacheable. `doctors`, `booking_queue`, `safety_guardrails`, and unknown categories are not.
- **R5.2**: Lookup **and** store must be bypassed when the query contains: an Egyptian mobile number, a 14-digit national ID, any run of ≥ 6 digits, or personal-reference words (e.g. حجزي، ميعادي، نمرتي، اسمي، رقمي، كشفي / my appointment, my booking, my number, my name).
- **R5.3**: Lookup and store must be bypassed when `detect_emergency(query)` is true.
- **R5.4**: A response must not be stored if: it has `tool_calls`; its `degradation_tier` is `TIER_3_SEARCH_ONLY` or `TIER_4_HUMAN_ESCALATION`; it is `truncated`; it is empty/whitespace; or it contains phone/ID patterns.

### R6: Guardrail-Gated Writes (parent R3.3)
- **R6.1**: `store()` must pass the response through an injectable `OutputValidator`; only `True` results are written.
- **R6.2**: The default validator must reject responses containing drug/dosage/prescription wording, diagnosis statements, or discount/promise wording (AR + EN word lists).
- **R6.3**: Fail-closed: if the validator raises, nothing is stored.

### R7: TTL & Invalidation
- **R7.1**: TTL is resolved per category from `cache_ttl_by_category` (default `pricing`/`insurance` = 6h, other allowed categories = 24h), otherwise `cache_default_ttl_s`.
- **R7.2**: `kb_version` = first 12 hex chars of SHA-256 of `cache_kb_path` file content, computed at ladder init; if the file is missing, `kb_version="unknown"` and a warning is logged.
- **R7.3**: Changing the KB content must make all previous entries unreachable (new `kb_version`) without manual action.
- **R7.4**: `invalidate(category=None)` removes all entries (or only those of the given category) from both tiers and returns the count removed.

### R8: Failure Behaviour
- **R8.1**: Fail-open: any backend, Qdrant, embedding, or timeout error during lookup results in `MISS`/`BYPASS` — never an exception and never a blocked call.
- **R8.2**: `schedule_store()` must run `store()` as a background task so the caller is not delayed; errors are logged and counted, never raised.

### R9: Observability
- **R9.1**: `CacheResult` fields: `hit`, `tier` (`EXACT`|`SEMANTIC`|`MISS`|`BYPASS`), `text`, `similarity`, `latency_ms`, `bypass_reason`, `kb_version`.
- **R9.2**: In-process counters per tier: hits, misses, bypasses (by reason), stores, store_rejected, errors; exposed via `snapshot()` along with current Tier 1 size and `kb_version`.

### R10: Gateway Helper
- **R10.1**: `cached_generate(gateway, cache, messages, scope, **kwargs)` must: extract the latest user message as the query; on hit return text without calling the gateway; on miss call `gateway.agenerate(Stage.DIALOGUE, ...)`, then `schedule_store()` the result; return `CachedTurnResult(text, cache, gateway)`.
- **R10.2**: The helper must not modify `ModelGateway` or its `GatewayResult` contract.

---

## 2. Non-Functional Requirements
- **NFR1 (Hit latency)**: Tier 1 hit < 5ms; Tier 2 hit < 30ms (excluding first model load).
- **NFR2 (Miss overhead)**: Total lookup overhead on miss ≤ `cache_semantic_timeout_ms` + 5ms; with Tier 2 skipped < 5ms.
- **NFR3 (Privacy)**: Query and response text, phone numbers, and IDs must never appear in logs at any level — only tier, category, language, reason, similarity, timings.
- **NFR4 (Concurrency)**: Safe under concurrent async lookups/stores (no corrupted LRU state).
- **NFR5 (Offline testability)**: All automated tests run without network, real API keys, or Qdrant Cloud (in-memory Qdrant + fake embedder).
- **NFR6 (Determinism)**: No LLM call is made to decide category, cacheability, or validity.

---

## 3. Constraints
- **C1**: Do not modify `src/ai_core/gateway.py`, `src/agent/voice_agent.py`, or `src/agent/prompts.py` (wiring → 5.3; prompt rewrite → 5.1).
- **C2**: No new runtime dependency (Qdrant client + FastEmbed already present; no Redis).
- **C3**: All thresholds, TTLs, switches, collection name, and KB path live in `src/config.py` with defaults so the existing `.env` loads unchanged.
- **C4**: `cache_semantic_threshold` must be validated to `0.90 ≤ x ≤ 1.0`.
- **C5**: The cache must not write to the `clinic_kb` collection or alter KB ingestion.
- **C6 (Carried to 5.1)**: Feature 5.1 must structure `prompts.py` so `current_datetime` and other dynamic data appear only in the dynamic tail produced by `PromptPrefixBuilder`.
