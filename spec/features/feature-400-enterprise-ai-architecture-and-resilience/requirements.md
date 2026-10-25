# Requirements Specification: Feature 400 — Enterprise AI Architecture & Resilience Engine

## 1. Functional Requirements

### R1: Multi-Tier Model Gateway & Circuit Breakers
- **R1.1**: The system must route LLM requests through a centralized Model Gateway abstraction supporting primary (Groq `llama-3.3-70b-versatile`) and secondary fallback (OpenAI `gpt-4o-mini` / Claude) providers.
- **R1.2**: The gateway must enforce a Time-to-First-Token (TTFT) timeout of 3.5 seconds on the primary provider.
- **R1.3**: The circuit breaker must trip open after 5 consecutive request failures (timeouts, HTTP 429, or HTTP 5xx) within a 60-second window, instantly routing 100% of traffic to the secondary provider for at least 60 seconds without waiting for primary timeouts.
- **R1.4**: The circuit breaker must enter a `HALF_OPEN` state after the cooldown to test primary health with a single probe request before resuming normal traffic.
- **R1.5**: Model tiers must be bound deterministically to workflow stages: `llama-3.1-8b-instant` for intent classification and entity extraction; `llama-3.3-70b-versatile` for caller-facing dialogue. No LLM call may be used to select a model.
- **R1.6**: Every caller-facing generation must enforce `max_tokens=150`.

### R2: 4-Tier Graceful Degradation Chain
- **R2.1**: The system must execute a deterministic 4-tier fallback hierarchy:
  1. **Tier 1 (Primary)**: High-speed LLM generation via Groq.
  2. **Tier 2 (Secondary Failover)**: Independent backup provider (OpenAI/Claude).
  3. **Tier 3 (Search-Only Deterministic)**: In the event of total LLM provider failure, serve exact pre-indexed clinic FAQ/policy excerpts directly from Qdrant/cache without generation.
  4. **Tier 4 (Human Escalation)**: For unhandled errors or emergency symptoms, immediately escalate to clinic receptionist staff.
- **R2.2**: Every response must include a `degradation_tier` indicator (`TIER_1_PRIMARY`, `TIER_2_BACKUP`, `TIER_3_SEARCH_ONLY`, `TIER_4_HUMAN_ESCALATION`) for downstream dashboard visibility.

### R3: 3-Tier Caching Ladder
- **R3.1**: Incoming queries must traverse a 3-tier caching ladder before reaching any LLM provider:
  - **Tier 1 (Exact Hash Cache)**: Normalize input text and check SHA-256 hash in fast in-memory/Redis storage with sub-5ms response time.
  - **Tier 2 (Metadata-Scoped Semantic Cache)**: Embed query and search Qdrant cache with a strict cosine similarity threshold of $\ge 0.97$, strictly filtered by clinic specialty/category.
  - **Tier 3 (Prompt Prefix Cache)**: Structure all system prompts statically first (instructions, schemas, few-shots) and append dynamic caller context strictly at the end to maximize provider KV-cache hits.
- **R3.2**: The cache must ONLY store safe, public clinic answers (operating hours, fees, general policies). Personalized queries (patient appointments, specific medical history) must NEVER be cached or returned from cache.
- **R3.3**: Responses must only be written to Tier 1 and Tier 2 caches after successfully passing Output Guardrails.

### R4: Hybrid Search Retrieval (Dense + Sparse BM25 via RRF)
- **R4.1**: Knowledge base retrieval must execute dual parallel queries: dense vector cosine search in Qdrant and sparse BM25 keyword search.
- **R4.2**: Results must be merged using Reciprocal Rank Fusion (RRF) with a standard smoothing constant ($k=60$) to return the top 5 most relevant chunks.
- **R4.3**: Hybrid search must guarantee precise matching for exact clinic entities, including doctor names, specialized lab tests (e.g. CBC, Lipid Profile, HbA1c), and price figures.

### R5: Fast Runtime Input Guardrails
- **R5.1**: All incoming user utterances must pass through lightweight (<20ms CPU) deterministic regex and heuristic filters prior to LLM invocation.
- **R5.2**: The input guardrail must detect and block prompt injection patterns (e.g., "ignore previous instructions", "you are now in admin mode").
- **R5.3**: The input guardrail must immediately identify explicit requests for medical diagnosis or prescription (e.g., "what medicine should I take for chest pain?") and trigger polite clinical disclaimers with receptionist transfer.

### R6: Pre-Trace PII Redaction
- **R6.1**: The system must detect Egyptian phone numbers (`010/011/012/015...`), Egyptian National IDs (14 digits), and sensitive personal identifiers using Microsoft Presidio with custom Egyptian recognizers.
- **R6.2**: Sensitive identifiers must be masked (e.g., `[REDACTED_PHONE]`) before payloads are dispatched to third-party model providers and before saving to persistent trace logs (Langfuse).

### R7: Output Guardrails & Grounding Verification
- **R7.1**: Output text from the LLM must be verified before streaming to TTS against a strict "Never say" list (no improvised discounts, no unauthorized promises, no prescription of drugs).
- **R7.2**: Factual answers regarding clinic fees, preparation rules, and doctor schedules must be checked for citation grounding against retrieved knowledge chunks.

### R8: Deterministic State Machine & Write Safety Gates
- **R8.1**: All state-mutating operations (`book_appointment`, `cancel_appointment`, `reschedule_appointment`) must be governed by a deterministic state machine rather than unconstrained agent autonomy.
- **R8.2**: A hard Python code gate must validate business invariants before executing database writes:
  - Doctor shift exists and is active.
  - Target appointment time falls strictly within doctor shift hours.
  - Current confirmed bookings count is strictly less than shift `max_capacity`.
- **R8.3**: If any condition fails, the state gate must reject the write in code with a clear Arabic explanation without modifying database state.

### R9: Booking Idempotency
- **R9.1**: Every booking request must compute a deterministic `Idempotency-Key` (SHA-256 hash of `patient_phone + doctor_id + shift_id + appointment_date`).
- **R9.2**: If a request with an existing idempotency key is received within a 24-hour window, the system must return the existing confirmed booking details without incrementing queue numbers or writing duplicate records.

### R10: Session-Injected Caller Identity
- **R10.1**: The LLM tool-calling schema for booking and appointment management must omit caller identity fields (`patient_phone`, `patient_id`).
- **R10.2**: The backend tool execution layer must inject the caller's verified session phone number server-side, preventing parameter spoofing or confused-deputy attacks.

### R11: Hierarchical Trace Logging & Cost Accounting
- **R11.1**: Every conversational turn must generate a unique `trace_id`, composed of nested spans each carrying `span_id` and `parent_span_id` (OpenTelemetry-compatible).
- **R11.2**: Spans must cover input guardrails, cache tiers, stage router, LLM calls, tool executions, and output guardrails, and log: PII-masked input/output, prompt tokens, completion tokens, estimated cost, latency (incl. TTFT), and degradation tier. Token and cost totals must roll up to the trace.
- **R11.3**: Traces must be exported to a self-hosted Langfuse instance; no trace data may be sent to third-party SaaS.
- **R11.4**: Concurrent async calls must be isolated via `contextvars`; cross-service calls must propagate the W3C `traceparent` header.
- **R11.5**: Export must be asynchronous (in-memory buffer + background flush). If Langfuse is unavailable, the tracer must degrade to a no-op without affecting the call.

### R12: CI/CD Golden Evaluation Dataset & RAGAS Gate
- **R12.1**: The system must maintain a version-controlled `golden_dataset.json` containing at least 50 realistic Egyptian clinic conversational turns (with reference contexts and answers) across:
  - Routine inquiries (hours, fees, insurance).
  - Appointment bookings and cancellations.
  - Adversarial prompt injection attempts (direct and indirect via documents).
  - Urgent symptom and medical diagnosis trap queries.
- **R12.2**: Structured fields (selected tool, specialty, escalation flag) must be graded by deterministic exact match with a minimum 95% pass rate.
- **R12.3**: Free-text answers must be graded with RAGAS using `gpt-4o-mini` as judge, with aggregate thresholds: Faithfulness ≥ 0.90, Context Recall ≥ 0.85, Context Precision ≥ 0.80, Answer Relevancy ≥ 0.85.
- **R12.4**: A GitHub Actions workflow must run the evaluation on every PR that modifies prompts, model configuration, or RAG components, and block merge on failure.

### R13: OWASP-Aligned Untrusted Content Handling
- **R13.1**: Caller utterances and retrieved RAG chunks must be wrapped in explicit XML delimiters (e.g. `<caller_utterance>`, `<retrieved_context>`) with system rules instructing the model to treat enclosed content strictly as data.
- **R13.2**: Knowledge documents must be sanitized at ingestion time to remove hidden or embedded instructions (indirect prompt injection) before indexing.
- **R13.3**: LLM outputs that drive actions must populate typed Pydantic fields constrained by `Literal`/`Enum` where possible; LLM text must never be passed to `eval`, `subprocess`, or raw SQL.
- **R13.4**: Secrets and credentials must never be included in prompt context.
- **R13.5**: A threat model mapping OWASP LLM Top 10 risks to clinic-specific attack scenarios and mitigations must be maintained in `spec/security/threat_model.md`.

### R14: FinOps Token Budgets & Cost Circuit Breaker
- **R14.1**: Each call must enforce a cumulative token budget (default 8,000 tokens); on exhaustion the agent must politely wrap up or escalate to the receptionist.
- **R14.2**: The system must accumulate daily estimated spend and emit an alert at 80% of the daily cap (default $10).
- **R14.3**: On reaching the daily cap, a cost circuit breaker must degrade new LLM requests to Tier 3 (search-only) or Tier 4 (receptionist) without dropping calls.
- **R14.4**: Tool payloads must be pruned to essential fields before being appended to the conversation state.

### R15: Asynchronous Safety Classification
- **R15.1**: Llama Guard must run asynchronously on a configurable sample of turns, off the voice hot path, and record verdicts on the corresponding trace.

---

## 2. Non-Functional Requirements

### NFR1: Voice Latency Overhead
- Total latency overhead introduced by the AI Core layer (Input Guardrails + Cache Check + Intent Routing) must remain **< 50ms** on cache miss.
- On cache hit (Tier 1 or Tier 2), total response latency must be **< 30ms**, completely bypassing LLM generation.

### NFR2: Availability & Fault Tolerance
- Effective system uptime must achieve **99.9%** availability across LLM provider outages by leveraging circuit breakers and the 4-tier degradation chain.

### NFR3: Booking Reliability & Atomicity
- Execution reliability of booking workflows must be **100% deterministic**; race conditions, duplicate bookings, and overcapacity allocations must be mathematically eliminated by database transactions and state gates.

### NFR4: Privacy & Compliance
- Zero raw personal identification data (phone, national ID) leaked into distributed tracing stores or public LLM training data.

### NFR5: Tracing Overhead
- Trace instrumentation must add **< 1ms** of overhead per request on the hot path.

---

## 3. Constraints & Invariants

- **C1 (Code > Prompts)**: Business, security, and financial rules (shift limits, fees, booking validation) must be enforced in deterministic Python code, NEVER solely in natural language system prompts.
- **C2 (Declarative Configuration)**: System prompts, model IDs, temperature, similarity thresholds, and circuit breaker limits must reside in versioned configuration files (YAML/Pydantic), completely decoupled from imperative Python code.
- **C3 (Zero Medical Hallucination Invariant)**: In accordance with `spec/tech.md` Invariant 3, under no circumstances shall the system provide medical diagnoses or prescribe medications.
- **C4 (Configurable LLMOps Thresholds)**: Token budgets, daily cost cap, alert ratio, RAGAS thresholds, Llama Guard sampling rate, and Langfuse connection settings must reside in `src/config.py`.
- **C5 (Scope Boundary)**: Prometheus/Grafana metrics, online sampled evaluation, SSO/RBAC, tenant isolation, load testing, and SLA are out of scope for this feature (Phase 6).
