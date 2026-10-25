# Technical Constitution & Architectural Invariants — Voice AI Agent (Egyptian Clinics)

## 1. Technology Stack

| Layer | Technology | Version / Model | Justification / Role |
|:---|:---|:---|:---|
| **Voice Transport** | LiveKit Cloud / LiveKit Agents | SDK >= 0.8.0 | WebRTC low-latency streaming audio, room session orchestration |
| **Speech-to-Text (STT)** | Deepgram | `nova-3` | Streaming transcription, punctuation, Egyptian Arabic (`ar`) & English |
| **LLM Reasoning** | Groq Cloud | `llama-3.3-70b-versatile` | High-throughput token generation (>300 t/s) for sub-second voice SLA |
| **LLM Stage Routing** | Groq Cloud | `llama-3.1-8b-instant` | Lightweight model bound to classification / extraction nodes (FinOps) |
| **LLM Fallback** | Google Gemini (via LiteLLM) | `gemini-2.0-flash` | Secondary provider behind circuit breaker |
| **Text-to-Speech (TTS)** | ElevenLabs | `eleven_turbo_v2_5` | Streaming natural vocal synthesis with sub-250ms first-chunk playback |
| **VAD / Barge-In** | Silero VAD | v4 | Client/Server-side instant speech cutoff when caller interrupts |
| **Relational Database** | Async SQLAlchemy + SQLite / PostgreSQL | >= 2.0.0 | ACID booking transactions, shift capacity, doctors & appointment state |
| **Vector DB (RAG)** | Qdrant | In-Memory / Cloud (>=1.9) | Low-latency vector search for specialties, clinic policies, fees, tests |
| **Embeddings** | FastEmbed | `paraphrase-multilingual-MiniLM-L12-v2` | Lightweight multilingual ONNX embeddings without PyTorch dependency |
| **Configuration** | Pydantic Settings | >= 2.2.0 | Centralized typed configuration loaded from `.env` |
| **Admin UI** | Streamlit + Plotly | >= 1.35.0 | Operational dashboard for call logs, appointments, audio playback, metrics |
| **Testing** | Pytest + Pytest-AsyncIO | >= 8.0.0 | Unit, database integration, and voice pipeline simulation testing |
| **LLM Trace Logging** | Langfuse (self-hosted) + OpenTelemetry | Latest OSS | Hierarchical traces/spans with tokens, cost & latency; patient data never leaves clinic infra |
| **Metrics & Alerting** | Prometheus + Grafana + Alertmanager | Latest | Calls/min, P95 per turn, error rate, daily token cost, budget & SLO alerts |
| **Evaluation** | RAGAS + Golden Dataset | Judge: `gpt-4o-mini` | Faithfulness, Context Recall/Precision, Answer Relevancy in CI and on 10% of production traces |
| **PII Redaction** | Microsoft Presidio | Custom Egyptian recognizers | Mask phone numbers & 14-digit national IDs before tracing |
| **Safety Classifier** | Llama Guard | Async sampled (off hot path) | Secondary injection/abuse detection without breaking the 800ms budget |
| **Identity (SSO)** | OAuth2 / OIDC (JWT) | Keycloak local / Entra ID prod | Staff authentication; roles `admin`, `receptionist`, `doctor`, `viewer` |
| **Load Testing** | Locust + LiveKit `lk load-test` | Latest | API/text path and voice path stress tests at 50 concurrent calls |
| **CI/CD** | GitHub Actions | - | RAGAS golden-eval gate on prompt/model PRs |
| **DevOps** | Docker + Docker Compose + AWS ECS | Multi-stage | Containerization and scalable cloud worker deployment |

---

## 2. Architectural Invariants & Rules

### 1. Voice Latency Budget (< 800ms Target)
- Total voice turnaround (Caller stops speaking -> Agent first audio frame): **< 800ms**.
- STT Interim & Final transcription: **< 200ms**.
- LLM Time-to-First-Token (TTFT): **< 300ms** via Groq.
- TTS Streaming synthesis first chunk: **< 250ms**.
- Tool execution timeout: **< 400ms**. Any database or RAG tool taking longer must abort and yield a friendly conversational filler.

### 2. Clinic Shift Window & Capacity Invariant (Atomic Booking)
- Appointments are booked within defined doctor shift windows (e.g. 18:00–21:00).
- Bookings must execute inside an **atomic database transaction**:
  1. Verify active shift existence and check that `current_bookings_count < max_capacity`.
  2. Increment queue number and persist the `Appointment` record.
  3. Prevent double-booking / race conditions when concurrent calls occur.
- Visit types must explicitly differentiate between:
  - `examination` (كشف جديد - full fee & slot count)
  - `consultation` (استشارة / إعادة - discounted/free follow-up within eligibility window).

### 3. Medical Safety & Liability Guardrails (Zero Medical Hallucination)
- **Strict Prohibition**: The Voice Agent must NEVER provide medical diagnoses, suggest specific drug dosages, or offer medical treatment prescriptions.
- When a caller reports urgent or life-threatening symptoms (e.g. chest pain, severe bleeding, difficulty breathing), the agent must immediately instruct the caller to seek emergency care and trigger the `transfer_to_receptionist` tool.
- All pricing, preparation rules (e.g. fasting before blood tests), and doctor credentials must strictly originate from verified database or RAG sources.

### 4. Barge-In (Interruption Handling)
- When caller voice activity is detected by Silero VAD while TTS is playing, speech playback must immediately cancel and LLM generation must abort.

### 5. Tool Execution & Error Resilience
- All tools must use strict Pydantic schemas for input validation.
- Tools must fail gracefully (never crash the audio pipeline or disconnect the WebRTC room).
- Tool outputs must provide human-sounding, concise strings in Egyptian Arabic suitable for speech synthesis.

### 6. Session State & Privacy Separation
- Session manager tracks call metadata, latency breakdown (STT, LLM, TTS), token counts, and tool invocations.
- Patient health records and sensitive contact details must be handled securely with zero credentials hardcoded.
- LiveKit JWT clock skew compensation remains active to prevent token expiry.

### 7. Observability & Telemetry Hygiene
- Every conversational turn produces a hierarchical trace (`trace_id`, nested spans with `parent_span_id`) covering guardrails, cache, routing, LLM, tools, and TTS.
- Trace export must be asynchronous (in-memory buffer + background flush) with **< 1ms** overhead on the hot path; traces are PII-masked before export.
- Prometheus labels must be bounded enumerations only (e.g. `model`, `stage`, `status`, `degradation_tier`). Never use `phone`, `call_id`, `patient_id`, or raw text as labels.
- Errors are counted in two classes: infrastructure (5xx, timeouts, 429) and semantic (schema validation failures, step-budget exhaustion).

### 8. FinOps Budgets
- `max_tokens` per voice turn: **150**. Token budget per call: **8,000**.
- Daily spend cap: **$10** with an alert at **80%**; on breach, the cost circuit breaker degrades to Tier 3 (search-only) / Tier 4 (receptionist).
- Model tiers are bound deterministically to workflow stages (8B for classification/extraction, 70B for dialogue) — no LLM call is used to choose an LLM.
- All budget and threshold values live in `src/config.py`.

### 9. Untrusted Content Handling (OWASP LLM Top 10)
- Caller utterances and retrieved RAG chunks are wrapped in explicit XML delimiters and treated strictly as data, never as instructions.
- Knowledge documents are sanitized at ingestion time to strip hidden/embedded instructions (indirect prompt injection).
- LLM output is untrusted: it may only populate typed Pydantic fields (Literal/Enum where possible) and must never reach `eval`, `subprocess`, or raw SQL.
- Secrets and credentials are never placed in prompt context. A formal threat model is maintained in `spec/security/threat_model.md`.

### 10. Identity & Tenant Isolation
- `tenant_id` / `branch_id` and roles are derived only from a cryptographically verified token or the LiveKit room/session — never from user-supplied parameters.
- Vector search applies tenant/branch and role filters **before** similarity scoring (pre-retrieval filtering).
- Every tool is bound to an allowlist of roles; the patient `caller` role may only invoke clinic booking/inquiry/escalation tools.

### 11. Reliability Contract (SLI -> SLO -> SLA)
- **SLO (internal)**: P95 voice turn latency **<= 800ms**, uptime **99.9%**.
- **SLA (contractual)**: P95 voice turn latency **<= 1.2s**, monthly uptime **99.5%**, up to **50 concurrent calls**.
- Autoscaling is driven by active calls per task (custom metric), not CPU utilization.
- Load testing (Locust + `lk load-test`) is a mandatory gate before UAT / go-live.
