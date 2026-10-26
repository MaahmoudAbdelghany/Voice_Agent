# Validation Criteria: Feature 4.2 — 3-Tier Caching Ladder (`src/ai_core/cache.py`)

## 1. Success Definition
The feature is complete when: normalized repeats of a public clinic question hit Tier 1 in < 5ms; paraphrases within the same `category` + `language` + `kb_version` hit Tier 2 only at cosine ≥ 0.97 and are promoted to Tier 1; personal, emergency, non-allowlisted, tool-call, Tier 3/4, truncated, or validator-rejected content is **never** read from or written to the cache; changing the KB file invalidates all prior entries; any cache failure degrades to a MISS without raising; `PromptPrefixBuilder` produces a byte-stable static prefix; `cached_generate()` skips the gateway on hits and stores in the background on misses; and unit, integration, edge-case, regression, lint, and CLI checks pass — all automated tests offline.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Scope**: pure helpers and isolated components. Files: `tests/test_cache_normalizer.py`, `tests/test_prompt_prefix.py`, unit section of `tests/test_cache_ladder.py`.
- **Normalizer** (`test_cache_normalizer.py`):
  - `test_strips_tashkeel_and_tatweel`: `"مَوَاعِيـــد"` → `"مواعيد"`.
  - `test_unifies_alef_ya_ta_marbuta`: `"إمتى الأشعة"` and `"امتي الاشعه"` normalize identically.
  - `test_arabic_indic_digits`: `"٣٠٠ جنيه"` → `"300 جنيه"`.
  - `test_strips_punctuation_and_whitespace`: `"  سعر   الكشف؟!  "` → `"سعر الكشف"`.
  - `test_lowercases_english`: `"Clinic HOURS?"` → `"clinic hours"`.
  - `test_exact_key_changes_with_scope`: same query, different `category` / `language` / `kb_version` → different keys; same inputs → same key (64-hex).
  - `test_kb_version_from_file`: temp file → 12-hex value; content change → different value; missing file → `"unknown"`.
- **Policy**:
  - `test_allowlist_categories`: allowed for `pricing`, `faqs`…; rejected for `doctors`, `booking_queue`, `safety_guardrails`, `"xyz"`.
  - `test_deny_phone_id_digits`: `"رقمي 01012345678"`, 14-digit ID, `"123456"` → `personal_query`.
  - `test_deny_personal_words_ar_en`: `"ميعادي امتى"`, `"عايز ألغي حجزي"`, `"when is my appointment"` → `personal_query`.
  - `test_deny_emergency`: `"عندي ألم جامد في صدري"` → `emergency`.
  - `test_response_rules`: rejects `tool_calls` non-empty, `TIER_3_SEARCH_ONLY`, `TIER_4_HUMAN_ESCALATION`, `truncated=True`, `"   "`, response containing a phone number.
- **Default validator**:
  - `test_validator_rejects_medical_and_discount`: dosage/drug (`"خد بنادول مرتين"`), diagnosis (`"غالباً عندك التهاب"`), discount (`"هعملك خصم"`) → False; plain fee answer → True.
- **LRU backend** (fake clock):
  - `test_lru_ttl_expiry`, `test_lru_evicts_least_recently_used` (max 3 entries), `test_lru_get_refreshes_recency`.
- **Config**:
  - `test_threshold_validation`: 0.85 → `ValidationError`; 0.97 default OK; TTL map keys outside `ALLOWED_CATEGORIES` → `ValidationError`.
- **Prefix builder** (`test_prompt_prefix.py`):
  - `test_static_prefix_byte_stable`: two builds with different datetime/caller context → identical static messages and `prefix_hash`.
  - `test_order_static_then_dynamic_then_history`.
  - `test_rejects_placeholder_in_static`: static text containing `{current_datetime}` → `ValueError`.
  - `test_prefix_hash_changes_when_static_changes`.

### Tier 2: Integration Verification
- **Scope**: `CacheLadder` + `InMemoryLRUBackend` + `SemanticCacheStore` on **in-memory Qdrant** (`QdrantClient(":memory:")`) + deterministic fake embedder (controllable vectors / `is_semantic`) + fake gateway. File: `tests/test_cache_ladder.py`.
- `test_miss_then_store_then_exact_hit`: lookup → `MISS`; `store()` → True; lookup with spelling variant (`"سعر الكشف؟"` vs `"سعر الكشف"`) → `EXACT`, same text.
- `test_semantic_hit_above_threshold_and_promotion`: fake embedder gives cosine 0.98 for paraphrase → `SEMANTIC`, `similarity ≥ 0.97`; second lookup of same paraphrase → `EXACT`.
- `test_semantic_miss_below_threshold`: cosine 0.95 → `MISS`.
- `test_semantic_category_isolation`: stored under `pricing`, identical vector queried under `insurance` → `MISS`.
- `test_language_isolation`: stored `ar`, queried `en` → `MISS` on both tiers.
- `test_kb_version_invalidation`: store; rebuild ladder with changed KB file → `MISS` on both tiers.
- `test_invalidate_category_and_all`: returns counts; affected entries miss, others still hit.
- `test_no_category_skips_tier2`: `category=None` → Tier 1 only (fake Qdrant search **not called**).
- `test_cached_generate_hit_skips_gateway`: pre-stored answer → fake gateway call count 0, `CachedTurnResult.cache.tier == EXACT`.
- `test_cached_generate_miss_calls_gateway_and_stores`: fake gateway returns `TIER_1_PRIMARY` text → after awaiting background task, next lookup hits.
- `test_cached_generate_does_not_store_tier3_or_tool_calls`.
- `test_snapshot_counters`: after scripted sequence → expected hits/misses/bypasses/stores/store_rejected, `tier1_size`, `kb_version`.
- `test_concurrent_lookups_and_stores`: 50 concurrent mixed operations → no exception, consistent LRU size ≤ max.

### Tier 3: Error & Edge-Case Verification
- `test_embedding_fallback_disables_tier2`: `is_semantic=False` → `bypass_reason=embedding_fallback` for Tier 2, Tier 1 still works; warning logged once across multiple lookups.
- `test_semantic_timeout_returns_miss`: fake embedder sleeps 200ms, timeout 50ms → `MISS`, `bypass_reason=timeout`, elapsed < 120ms.
- `test_qdrant_error_fail_open`: search raises → `MISS`, `bypass_reason=backend_error`, no exception.
- `test_backend_error_fail_open`: Tier 1 backend raises → lookup still returns a `CacheResult`.
- `test_validator_exception_fail_closed`: validator raises → `store()` returns False, nothing written.
- `test_expired_semantic_entry_ignored`: `expires_at` in the past (fake clock) → `MISS`.
- `test_empty_and_whitespace_query`: `""`, `"   "`, `"؟؟"` → `BYPASS` `empty_query`.
- `test_disabled_switches`: `cache_enabled=False` → `BYPASS disabled`; `cache_semantic_enabled=False` → Tier 2 not called.
- `test_schedule_store_errors_never_raise`.
- `test_no_text_in_logs`: `caplog` at DEBUG during lookup/store with a query containing a phone number → no query text, response text, or digits sequence in any record.
- `test_tier1_hit_latency`: 1,000 Tier 1 hits, p95 < 5ms.
- `test_tier2_hit_latency_with_fake_embedder`: p95 < 30ms on in-memory Qdrant (embedding cost excluded via fake).

### Tier 4: Regression Checks
- Must still pass: `tests/test_circuit_breaker.py`, `tests/test_model_gateway.py`, `tests/test_medical_schemas.py`, `tests/test_doctor_availability.py`, `tests/test_appointment_booking.py`, `tests/test_manage_appointment.py`, `tests/test_knowledge_search.py`, `tests/test_human_handoff.py`, `tests/test_clinic_tools.py`, `tests/test_tools.py`, `tests/test_database.py`, `tests/test_clinic_repository.py`, `tests/test_session_manager.py`, `tests/test_prompts.py`.
- `Settings()` loads with the existing `.env` unchanged (all new fields defaulted).
- `clinic_kb` collection untouched: `tests/test_clinic_rag.py` / `tests/test_knowledge_search.py` behaviour unchanged.
- **Known pre-existing legacy failures (not regressions)**: `tests/test_rag.py`, `tests/test_database_engine.py`, `tests/test_agent.py` (Phase 5 debt). Baseline recorded before implementation and compared after.

### Tier 5: Build, Lint & Type Checks
- `uv run ruff check src/ai_core src/config.py tests/test_cache_normalizer.py tests/test_cache_ladder.py tests/test_prompt_prefix.py scripts/cache_smoke.py scripts/cache_calibration.py`
- `uv run ruff format --check src/ai_core tests/test_cache_normalizer.py tests/test_cache_ladder.py tests/test_prompt_prefix.py scripts/cache_smoke.py scripts/cache_calibration.py`
- Build/import: `uv sync` (no new dependency added); `uv run python -c "from src.ai_core import get_cache_ladder, CacheLadder, CacheScope, CacheTier, PromptPrefixBuilder, cached_generate"`.
- Type checking: **Not Applicable** — no type checker (mypy/pyright) is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable (UI/audio) — the feature is a backend library with no dashboard view or audio output.
- Supervisor review instead: read the `scripts/cache_calibration.py` report and confirm that dissimilar pairs (e.g. pediatric fee vs dental fee) score clearly below 0.97 and that the bypass reasons printed by `cache_smoke.py` match expectations.

### Tier 7: API / CLI / Application Checks
- **Smoke run (real FastEmbed model, in-memory Qdrant, no API keys needed)**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/cache_smoke.py
  ```
  **Expected**: (1) `"سعر كشف الأطفال كام؟"` → MISS → stored; (2) `"سعر كشف الاطفال كام"` → EXACT; (3) paraphrase → SEMANTIC (if similarity ≥ 0.97) or MISS with printed similarity; (4) `"ميعادي امتى؟"` → BYPASS `personal_query`; (5) `"عندي ألم في صدري"` → BYPASS `emergency`; (6) category `doctors` → BYPASS `category_not_allowed`; final `snapshot()` printed.
- **Calibration report**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/cache_calibration.py
  ```
  **Expected**: table of similarity scores for similar and dissimilar Arabic/English pairs; no config modified.
- **Optional live helper (requires `GROQ_API_KEY`)**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/cache_smoke.py --live --prompt "مواعيد العيادة إيه؟" --category general
  ```
  **Expected**: first call `cache=MISS`, gateway `TIER_1_PRIMARY`; second call `cache=EXACT`, gateway not called, latency < 5ms.

---

## 3. Automated Execution Commands

```powershell
# 0. Baseline before implementation (record pass/fail)
$env:PYTHONIOENCODING="utf-8"; uv run pytest -q

# 1. Feature tests
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_cache_normalizer.py tests/test_cache_ladder.py tests/test_prompt_prefix.py -v

# 2. Lint and format
uv run ruff check src/ai_core src/config.py tests/test_cache_normalizer.py tests/test_cache_ladder.py tests/test_prompt_prefix.py scripts/cache_smoke.py scripts/cache_calibration.py
uv run ruff format --check src/ai_core tests/test_cache_normalizer.py tests/test_cache_ladder.py tests/test_prompt_prefix.py scripts/cache_smoke.py scripts/cache_calibration.py

# 3. Build / import
uv sync
uv run python -c "from src.ai_core import get_cache_ladder, CacheLadder, CacheScope, CacheTier, PromptPrefixBuilder, cached_generate"

# 4. Regression
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_circuit_breaker.py tests/test_model_gateway.py tests/test_medical_schemas.py tests/test_doctor_availability.py tests/test_appointment_booking.py tests/test_manage_appointment.py tests/test_knowledge_search.py tests/test_human_handoff.py tests/test_clinic_tools.py tests/test_tools.py tests/test_database.py tests/test_clinic_repository.py tests/test_session_manager.py tests/test_prompts.py -v
```
