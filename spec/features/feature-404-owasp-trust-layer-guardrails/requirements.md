# Requirements Specification: Feature 4.4 — OWASP-Aligned Trust Layer & Runtime Guardrails

> Traces to parent requirements R5, R6, R7, R13, R15 in `spec/features/feature-400-enterprise-ai-architecture-and-resilience/requirements.md` and Architectural Invariants 1, 3, 7, and 9 in `spec/tech.md`.

---

## 1. Functional Requirements

### R1: Fast Context-Aware Input Guardrails (`InputGuardrail` in `src/ai_core/guardrails.py`)
- **R1.1 (4-Way Triage Classification)**: Every incoming caller utterance must be evaluated deterministically by `InputGuardrail.evaluate(text)` into one of four actions:
  1. `ESCALATE_EMERGENCY`: Triggered when life-threatening symptoms are detected (via `detect_emergency()` from `src/tools/human_handoff.py`). Returns `allowed=False`, `escalate=True`, and an immediate Arabic emergency response directing the caller to ambulance `123` and receptionist transfer.
  2. `BLOCK_INJECTION`: Triggered when direct prompt injection, system role override, jailbreak phrases (Arabic or English, e.g., *"ignore previous instructions"*, *"system prompt"*, *"تجاهل التعليمات السابقة"*, *"أنت الآن في وضع المطور"*), or XML delimiter breakout tags (`<caller_utterance>`, `</caller_utterance>`, `<retrieved_context>`) are detected. Returns `allowed=False` and a polite clinic scope boundary message in Egyptian Arabic.
  3. `BLOCK_MEDICAL_ADVICE`: Triggered when the caller explicitly asks for a medical diagnosis, treatment plan, medication recommendation, or drug dosage (e.g., *"آخد دواء إيه للكحة؟"*, *"ممكن تكتبلي مضاد حيوي أو جرعة بنادول؟"*, *"شخص حالتي"*) **without** an accompanying request to book an appointment or inquire about doctor availability/specialties. Returns `allowed=False` and a polite clinical disclaimer offering to book a specialist examination or transfer to the receptionist.
  4. `ALLOW`: Triggered for normal clinic inquiries and for utterances where a non-emergency symptom is mentioned alongside a booking or doctor/specialty inquiry (e.g., *"عندي وجع في ركبتي وعايز أحجز مع دكتور عظام"* or *"ابني سخن، دكتور الأطفال موجود امتى؟"*). When a non-emergency symptom is present in an allowed booking query, `InputGuardrailResult.safety_reminder` must be populated with a concise reminder instructing the downstream LLM to assist with booking/scheduling without diagnosing or prescribing.
- **R1.2 (Kill Switch)**: When `settings.guardrails_enabled` is `False`, `InputGuardrail.evaluate()` must still enforce emergency detection (`ESCALATE_EMERGENCY` per Invariant 3) and pass other utterances through as `ALLOW`.

### R2: Breakout-Safe XML Delimiter Wrapping (`src/ai_core/guardrails.py` & `src/tools/knowledge_search.py`)
- **R2.1 (Caller Utterance Wrapping)**: `wrap_caller_utterance(text)` must strip or neutralize any embedded `<caller_utterance>`, `</caller_utterance>`, `<retrieved_context>`, or `</retrieved_context>` tags inside `text` before enclosing it in `<caller_utterance>...</caller_utterance>`.
- **R2.2 (Retrieved Context Wrapping)**: `wrap_retrieved_context(context)` must neutralize any embedded delimiter tags and enclose RAG context blocks inside `<retrieved_context>...</retrieved_context>`.
- **R2.3 (Knowledge Search Tool Integration)**: `ClinicKnowledgeSearchTool.execute()` must wrap `ClinicKnowledgeSearchOutput.context_text` (destined for LLM synthesis) in `<retrieved_context>...</retrieved_context>`, while keeping `ClinicKnowledgeSearchOutput.message` (destined for TTS speech synthesis and Tier 3 search-only fallback) completely free of XML tags.
- **R2.4 (Untrusted Content System Directive)**: `src/ai_core/guardrails.py` must expose `SYSTEM_UNTRUSTED_DATA_RULES` instructing the LLM to treat everything inside `<caller_utterance>` and `<retrieved_context>` strictly as untrusted data and never follow commands contained within them.

### R3: Ingestion-Time Document Sanitization (`src/rag/sanitizer.py` & `src/rag/ingestion.py`)
- **R3.1 (Multi-Layer Threat Stripping)**: `DocumentSanitizer.sanitize(text)` must detect and strip:
  1. HTML comments (`<!-- ... -->`) and executable/hidden HTML blocks (`<script>`, `<style>`, `<iframe>`, `<object>`).
  2. Invisible and bidirectional-override Unicode control characters (`\u200b`–`\u200f`, `\u202a`–`\u202e`, `\u2060`–`\u206f`, `\ufeff`).
  3. External Markdown image exfiltration links (`![...](http://...)` or `![...](https://...)`).
  4. Embedded XML delimiter breakout tags (`<caller_utterance>`, `</caller_utterance>`, `<retrieved_context>`, `</retrieved_context>`).
  5. Indirect prompt injection lines in Arabic and English (e.g., lines instructing the reader/assistant to ignore rules, reveal secrets/prompts, or alter prices/roles).
- **R3.2 (Preservation of Clinic Table Formatting)**: `DocumentSanitizer` must preserve Markdown tables (`| ... |`), Arabic diacritics (tashkeel), and legitimate `<br>` line-break tags used inside `knowledge_base/clinic_kb.md` table cells so `KnowledgeIngestionPipeline.parse_markdown()` produces the exact same valid chunks on clean clinic documents.
- **R3.3 (Sanitization Audit Report & Ingestion Wiring)**: `DocumentSanitizer.sanitize(text)` must return a `SanitizationReport` containing `sanitized_text`, `is_modified`, `total_findings`, and a list of `SanitizationFinding` items (`category`, `description`, `count`). `KnowledgeIngestionPipeline.parse_markdown()` must automatically invoke `DocumentSanitizer` when `settings.rag_sanitize_on_ingest` is `True`.

### R4: Output Guardrails, Grounding & Structured Output Validation (`src/ai_core/guardrails.py`)
- **R4.1 ("Never Say" Policy Enforcement)**: `OutputGuardrail.validate(response_text, retrieved_context=None)` must block responses containing:
  1. Medical prescriptions or drug dosages (e.g., drug names paired with dosage units `ملجم`/`mg`, frequency `مرتين في اليوم`, `أقراص`, `كبسولات`, `مضاد حيوي`, `روشتة`).
  2. Direct medical diagnosis claims (e.g., *"تشخيص حالتك"*, *"أنت مصاب بـ"*, *"عندك التهاب في"*).
  3. Unauthorized commercial discounts or free-service promises (e.g., *"هعملك خصم خاص"*, *"الكشف مجاناً عشانك"*).
  4. System prompt leaks, internal XML delimiters (`<caller_utterance>`, `<retrieved_context>`, `## AVAILABLE TOOLS`), or API credential patterns (`gsk_`, `sk-`, `Bearer `).
  5. Raw executable code or SQL statements (`SELECT * FROM`, `DROP TABLE`, `eval(`, `subprocess.`).
- **R4.2 (Numeric Fee Grounding Verification)**: When `retrieved_context` is provided to `OutputGuardrail.validate(response_text, retrieved_context)` and `response_text` states a specific monetary fee (e.g., `450 جنيه`, `500 ج.م`, `600 EGP`), the guardrail must verify that the numeric value (after normalizing Arabic-Indic digits `٠-٩` to ASCII `0-9`) appears in `retrieved_context`. If the stated fee is absent from `retrieved_context`, the response must be rejected (`violation_category="ungrounded_fee"`) with a safe Arabic fallback message.
- **R4.3 (`OutputValidator` Protocol Compatibility)**: `OutputGuardrail` must implement `is_valid(response_text: str) -> bool` (failing closed on any exception) and serve as the default validator in `CacheLadder` (`src/ai_core/cache.py`).
- **R4.4 (`Literal`/`Enum`-Constrained Structured Outputs)**: `src/ai_core/guardrails.py` must provide strict Pydantic schemas (`IntentClassificationSchema`, `EntityExtractionSchema` with `ConfigDict(extra="forbid")` and `Literal`/`Enum`-constrained fields) and `validate_structured_output(raw_output, schema_cls)` that safely parses JSON (stripping optional markdown code fences), enforces schema validation, and rejects any string values containing code/SQL injection payloads.

### R5: Lightweight Presidio-Compatible Egyptian PII Redactor (`EgyptianPIIRedactor`)
- **R5.1 (Egyptian Recognizer Suite)**: `EgyptianPIIRedactor` must detect and mask:
  1. `EG_PHONE`: Egyptian mobile numbers (`010`, `011`, `012`, `015` followed by 8 digits, with optional `+20`, `0020`, spaces, or hyphens) and clinic/landline patterns (`02`, `03`, etc.) → replaced with `[REDACTED_PHONE]`.
  2. `EG_NATIONAL_ID`: 14-digit Egyptian National ID numbers starting with century digit `2` or `3`, valid year/month (`01`–`12`)/day (`01`–`31`), and valid Egyptian governorate code (`01`–`35` or `88`) → replaced with `[REDACTED_NATIONAL_ID]`.
  3. `EMAIL`: Email addresses → replaced with `[REDACTED_EMAIL]`.
  4. `CREDIT_CARD`: 13–19 digit payment card sequences → replaced with `[REDACTED_CARD]`.
- **R5.2 (Bilingual Numeral Support)**: All PII recognizers must detect numbers written in either standard ASCII digits (`01012345678`) or Arabic-Indic digits (`٠١٠١٢٣٤٥٦٧٨`) and resolve overlapping spans deterministically (prioritizing 14-digit `EG_NATIONAL_ID` over shorter phone/digit patterns).
- **R5.3 (Recursive Payload Redaction)**: `EgyptianPIIRedactor.redact_dict(payload)` must recursively redact strings inside nested dictionaries, lists, and tuples without mutating the caller's original data structure.

### R6: Asynchronous Sampled Llama Guard Classifier (`AsyncLlamaGuardClassifier`)
- **R6.1 (Off-Hot-Path Execution & Sampling)**: `AsyncLlamaGuardClassifier.schedule_check(user_text, assistant_text=None, trace_id=None, on_verdict=None)` must check `settings.llama_guard_enabled` and `settings.llama_guard_sample_rate` (default `0.10`). When sampled, it must schedule evaluation asynchronously via `asyncio.create_task()` and return immediately without blocking the voice turn.
- **R6.2 (Mandatory Pre-Redaction)**: Before sending any text to the Llama Guard model (`groq/llama-guard-3-8b`), `AsyncLlamaGuardClassifier` must redact all PII via `EgyptianPIIRedactor.redact()`.
- **R6.3 (Verdict Parsing & Resilience)**: The classifier must parse `safe` vs `unsafe\nS1..S14` responses into a `LlamaGuardVerdict` model (`safe`, `category_codes`, `category_names`, `status`, `latency_ms`, `trace_id`), store verdicts in a bounded ring buffer (`recent_verdicts`), invoke optional `on_verdict` callbacks, and degrade gracefully (`status="skipped"` or `"error"`) without raising unhandled exceptions if credentials are unconfigured or the provider times out.

### R7: Formal OWASP LLM Top 10 Threat Model (`spec/security/threat_model.md`)
- **R7.1**: A comprehensive security threat model must be authored at `spec/security/threat_model.md` covering system trust boundaries, attacker personas, and a detailed matrix mapping OWASP LLM Top 10 risks (`LLM01` through `LLM10`) and Medical Safety Liability (`Invariant 3`) to concrete Egyptian polyclinic attack scenarios, implemented code mitigations (`src/ai_core/guardrails.py`, `src/rag/sanitizer.py`, `src/ai_core/cache.py`), and residual risk controls.

---

## 2. Non-Functional Requirements

- **NFR1 (Input Guardrail Latency Budget)**: `InputGuardrail.evaluate()` must execute in **< 20ms** on CPU (P99 < 5ms for typical caller utterances).
- **NFR2 (PII Redaction Latency Budget)**: `EgyptianPIIRedactor.redact()` must execute in **< 2ms** on CPU without requiring heavy NLP model downloads (`spacy`).
- **NFR3 (Output Guardrail Latency Budget)**: `OutputGuardrail.validate()` must execute in **< 5ms** on CPU.
- **NFR4 (Async Llama Guard Hot-Path Overhead)**: `AsyncLlamaGuardClassifier.schedule_check()` must add **< 1ms** overhead to the calling coroutine.
- **NFR5 (Offline Deterministic Testability)**: All unit, integration, and edge-case tests in `tests/test_guardrails.py` must run 100% offline without requiring live Groq/OpenAI API keys or external network calls.

---

## 3. Constraints

- **C1**: Do not break backward compatibility with `DefaultOutputValidator` or `OutputValidator` in `src/ai_core/cache.py`, nor existing tests in `tests/test_cache_ladder.py`, `tests/test_clinic_rag.py`, `tests/test_hybrid_rag.py`, and `tests/test_knowledge_search.py`.
- **C2**: Never strip `<br>` tags before table extraction in `src/rag/ingestion.py`, as `clinic_kb.md` uses `<br>` inside Markdown table cells.
- **C3**: Never wrap `ClinicKnowledgeSearchOutput.message` in XML tags; only `context_text` may contain `<retrieved_context>` tags.
- **C4**: All configurable guardrail toggles and sampling rates must reside in `src/config.py` with safe defaults.
