# Technical Constitution & Architectural Invariants — Voice AI Agent (Egyptian Clinics)

## 1. Technology Stack

| Layer | Technology | Version / Model | Justification / Role |
|:---|:---|:---|:---|
| **Voice Transport** | LiveKit Cloud / LiveKit Agents | SDK >= 1.7.0 | WebRTC low-latency streaming audio, room session orchestration |
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
| **Admin UI & Ops API** | FastAPI + Streamlit + Plotly | FastAPI >= 0.115 / Streamlit >= 1.35 | Clean REST operational boundary (shift apologies, queue ops) + RTL receptionist portal |
| **WhatsApp Notifications** | Pluggable Adapter + Meta WhatsApp Cloud API (`httpx`) | Graph API v21+ + `MockOutbox` | Direct official utility templates (confirmation, reminder, doctor apology) with zero BSP markup |
| **Background Scheduling** | DB Transactional Outbox + Async Worker | SQLAlchemy 2.0 + `asyncio` | Crash-safe reminder & bulk-apology dispatch without `Redis`/`Celery` infra cost in MVP |
| **Testing** | Pytest + Pytest-AsyncIO | >= 8.0.0 | Unit, database integration, WhatsApp outbox, and voice pipeline simulation testing |
| **LLM Trace Logging** | Langfuse (self-hosted) + OpenTelemetry | Latest OSS | Hierarchical traces/spans with tokens, cost & latency; patient data never leaves clinic infra |
| **Evaluation (CI Gate)** | RAGAS + Golden Dataset | Judge: `gpt-4o-mini` | Faithfulness, Context Recall/Precision, Answer Relevancy in CI on prompt/model PRs |
| **PII Redaction** | Microsoft Presidio + Regional Regex | Custom `EG` / `SA` / `AE` recognizers | Mask `E.164` & local mobile numbers (`+20`, `+966`, `+971`) and national IDs before tracing |
| **Safety Classifier** | Llama Guard | Async sampled (off hot path) | Secondary injection/abuse detection without breaking the 800ms budget |
| **DevOps (MVP -> Scale)** | Docker Compose on AWS EC2 -> AWS ECS Fargate | Multi-stage `12-Factor` + ECR/SSM/S3 | Low-cost single-host EC2 production launch (~$15-$25/mo) with zero-code path to ECS + RDS |
| **Post-MVP Scale Stack** | Prometheus/Grafana, Keycloak/Entra OIDC, Locust | Deferred to Phase 9 | Scheduled post-MVP once multi-clinic call volume justifies dedicated ops containers |

---

## 2. Architectural Invariants & Rules

### 1. Voice Latency Budget (< 800ms Target)
- Total voice turnaround (Caller stops speaking -> Agent first audio frame): **< 800ms**.
- STT Interim & Final transcription: **< 200ms**.
- LLM Time-to-First-Token (TTFT): **< 300ms** via Groq.
- TTS Streaming synthesis first chunk: **< 250ms**.
- Tool execution timeout (**< 400ms** filler threshold):
  - **Read tools** (`check_doctor_availability`, `search_clinic_knowledge`, appointment `lookup`): must abort at **400ms** and yield a friendly localized conversational filler.
  - **Write tools** (`book_appointment`, appointment `cancel` / `reschedule`, `transfer_to_receptionist`): must yield a friendly localized conversational filler at **400ms** while continuing execution shielded (`asyncio.shield`) up to a hard cap of **3,000ms** (`write_tool_hard_cap_ms`), escalating to the human receptionist if the 3s hard cap is exceeded so a committed booking is never misreported as failed.
- **Zero Synchronous External Messaging on Voice Path**: Voice tools must NEVER call `Meta WhatsApp Cloud API` synchronously during a call turn; they only insert rows into `NotificationOutbox` inside the local DB transaction (`< 5ms`).

### 2. Clinic Shift Window, Doctor Exceptions & Capacity Invariant (Atomic Booking)
- Appointments are booked within defined doctor shift windows (e.g. 18:00–21:00) on dates that have **no active `DoctorScheduleException`**.
- Bookings must execute inside an **atomic database transaction**:
  1. Verify active doctor, active shift existence, **absence of a `DoctorScheduleException` for `(doctor_id, appointment_date)`**, and `current_bookings_count < max_capacity`.
  2. Increment queue number (`نمرة الحجز`), persist the `Appointment` record, and enqueue confirmation + pre-shift reminder jobs in `NotificationOutbox` atomically.
  3. Prevent double-booking / race conditions when concurrent calls occur.
- When a doctor apologizes for a shift (`DoctorScheduleException`):
  1. The shift is immediately closed to new voice bookings, and `check_doctor_availability` surfaces the apology plus the next date/shift with actual open capacity.
  2. Existing confirmed appointments for that shift transition atomically to `cancelled_by_doctor` (never silently auto-moved into a potentially full future shift), pending reminders are cancelled, and apology WhatsApp notifications containing the next available shift are enqueued in `NotificationOutbox`.
- Visit types must explicitly differentiate between:
  - `examination` (كشف جديد - full fee & slot count)
  - `consultation` (استشارة / إعادة - discounted/free follow-up within eligibility window).

### 3. Regional Profile & Confirmed WhatsApp Contact Invariant (`EG` / `SA` / `AE`)
- All persisted patient and notification phone numbers are normalized to canonical **`E.164` format** (`+20...` Egypt default, `+966...` Saudi Arabia, `+971...` UAE) via a country-aware validator driven by `src/config.py` (`clinic_country_code`, currency, timezone, dialect profile).
- **Session Identity vs. Contact Phone Separation**:
  - `CallerSessionContext.caller_phone` (when present from PSTN/SIP/room metadata) remains the immutable audit identity of the call session.
  - `whatsapp_phone` + `whatsapp_confirmed: bool` captures the patient's confirmed contact number for WhatsApp notifications (allowing callers on landlines, browser WebRTC, or family phones to provide/confirm their WhatsApp number after explicit digit-group read-back).
  - Outbound WhatsApp messages are dispatched **only** when `whatsapp_confirmed=True`.

### 4. Medical Safety & Liability Guardrails (Zero Medical Hallucination)
- **Strict Prohibition**: The Voice Agent must NEVER provide medical diagnoses, suggest specific drug dosages, or offer medical treatment prescriptions.
- When a caller reports urgent or life-threatening symptoms (e.g. chest pain, severe bleeding, difficulty breathing), the agent must immediately instruct the caller to seek emergency care and trigger the `transfer_to_receptionist` tool.
- All pricing, preparation rules (e.g. fasting before blood tests), and doctor credentials must strictly originate from verified database or RAG sources.

### 5. Barge-In (Interruption Handling)
- When caller voice activity is detected by Silero VAD while TTS is playing, speech playback must immediately cancel and LLM generation must abort.

### 6. Tool Execution, Modular Providers & Error Resilience
- All tools and operational API endpoints must use strict Pydantic v2 schemas for input/output validation.
- External integrations (LLM Gateway, WhatsApp Provider, Vector Store) sit behind clean Python interfaces (`Protocol` / Adapter pattern) so providers (`Meta Cloud API` vs `MockOutbox` vs regional BSPs) can be swapped via `.env` without modifying domain or workflow code.
- Tools and background outbox workers must fail gracefully with bounded exponential backoff and idempotency keys (`idempotency_key` per notification event) so duplicate WhatsApp messages are never sent on retry.

### 7. Session State & Privacy Separation
- Session manager tracks call metadata, latency breakdown (STT, LLM, TTS), token counts, and tool invocations.
- Patient health records and contact numbers (`caller_phone`, `whatsapp_phone`) are redacted across `EG`/`SA`/`AE` patterns before trace export, with zero credentials hardcoded.
- LiveKit JWT clock skew compensation remains active to prevent token expiry.

### 8. Observability & Telemetry Hygiene
- Every conversational turn produces a hierarchical trace (`trace_id`, nested spans with `parent_span_id`) covering guardrails, cache, routing, LLM, tools, and TTS, exported asynchronously (`< 1ms` hot-path overhead).
- Metric labels (when Prometheus is enabled in Phase 9) must be bounded enumerations only — never `phone`, `whatsapp_phone`, `call_id`, `patient_id`, or raw text.

### 9. FinOps & Infrastructure Cost Discipline
- `max_tokens` per voice turn: **150**. Token budget per call: **8,000**.
- Daily LLM spend cap: **$10** with an alert at **80%**; on breach, the cost circuit breaker degrades to Tier 3 (search-only) / Tier 4 (receptionist).
- Model tiers are bound deterministically to workflow stages (`8B` for classification/extraction, `70B` for dialogue) — no LLM call is used to choose an LLM.
- MVP cloud infrastructure avoids idle managed-cluster overhead by running stateless `12-Factor` containers (`voice-worker`, `ops-api-scheduler`, `dashboard`, `postgres`, `qdrant`) via `Docker Compose` on a single `AWS EC2` instance with `AWS SSM` secrets and automated `S3` backups, preserving 1:1 container compatibility for Phase 9 `ECS Fargate + RDS` migration.

### 10. Untrusted Content Handling (OWASP LLM Top 10)
- Caller utterances and retrieved RAG chunks are wrapped in explicit XML delimiters and treated strictly as data, never as instructions.
- Knowledge documents are sanitized at ingestion time to strip hidden/embedded instructions (indirect prompt injection).
- LLM output is untrusted: it may only populate typed Pydantic fields (Literal/Enum where possible) and must never reach `eval`, `subprocess`, or raw SQL.
- Secrets and credentials are never placed in prompt context. A formal threat model is maintained in `spec/security/threat_model.md`.

### 11. Identity & Operational Access Control
- Patient `caller` sessions may only invoke allowlisted inquiry, booking, appointment-management, and receptionist-escalation tools; administrative mutations (such as recording a doctor apology) are exposed exclusively on authenticated `FastAPI` staff endpoints, never as caller LLM tools.
- Multi-branch cryptographic tenant isolation and external OIDC SSO (`Keycloak` / `Entra ID`) are scheduled in Phase 9 for multi-branch hospital groups.

---

## 3. Architecture Documentation & Decision Records (ADRs)

- **System Architecture & C4 Diagrams (`Diagram-as-Code`)**: [`spec/architecture.md`](./architecture.md)
- **Architecture Decision Records Index (ADRs 001–012)**: [`spec/adr/README.md`](./adr/README.md)
- **OWASP LLM Top 10 Threat Model**: [`spec/security/threat_model.md`](./security/threat_model.md)
