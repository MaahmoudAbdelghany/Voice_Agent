<div dir="rtl" align="right">

# المعمارية الهندسية الشاملة والمخططات ككود (System Architecture & Diagram-as-Code)

يمثّل هذا المستند المرجع المعماري الرسمي لنظام **المساعد الصوتي الذكي ومنظومة إشعارات الواتساب للعيادات والمراكز الطبية في مصر والسعودية والإمارات (Voice AI Medical Receptionist & WhatsApp Operations Platform)** وفق منهجية **C4 Model** ومبدأ **المخططات ككود (Diagram-as-Code)**.

- للاطلاع على التبرير الهندسي والبدائل المرفوضة لكل قرار معماري، راجع [**فهرس سجلات القرارات المعمارية (`spec/adr/README.md`)**](./adr/README.md).
- للاطلاع على نموذج التهديدات الأمنية وضوابط OWASP LLM Top 10، راجع [**`spec/security/threat_model.md`**](./security/threat_model.md).

---

## دليل الترميز البصري في المخططات (Built vs. Planned Legend)

التزاماً بمبدأ **الكود هو مصدر الحقيقة (As-Built Source of Truth)**:
- **المكوّنات المبنية فعلياً (Phases 1–5 & Core Admin Dashboard)**: تُرسم **بخط متصل (`Solid Line`)** وتعمل حالياً في المستودع مع تغطية اختبارية كاملة.
- **المكوّنات المخطط لاستكمالها في مراحل الـ MVP والتوسع القادمة (Phases 6–9)**: تُرسم **بخط متقطع (`Dashed Line`)** وتُميَّز بالصنف البصري `classDef planned` مع الوسم الصريح `[Planned]`.

---

## 1. مخطط سياق النظام — المستوى الأول (C4 Level 1: System Context)

يوضّح هذا المخطط موقع المساعد الصوتي الذكي ومنظومة الواتساب وعلاقتهما بالمرضى (في مصر والسعودية والإمارات)، وموظفي الاستقبال، والمزوّدين السحابيين (`Meta WhatsApp Cloud API`، `Groq`، `Deepgram`، `ElevenLabs`).

- القرارات المرتبطة: [ADR-003 (Model Gateway & Gemini Fallback)](./adr/003-multi-tier-model-gateway.md)، [ADR-004 (Self-Hosted Langfuse)](./adr/004-self-hosted-langfuse-tracing.md)، [ADR-006 (RAGAS CI Gate)](./adr/006-ragas-ci-evaluation.md)، [ADR-010 (E.164 & WhatsApp Contact Separation)](./adr/010-e164-and-whatsapp-contact-separation.md)، [ADR-011 (WhatsApp Adapter & DB Outbox)](./adr/011-whatsapp-adapter-and-db-outbox.md)، [ADR-012 (Lean AWS EC2 to ECS Deployment)](./adr/012-lean-aws-ec2-to-ecs-deployment.md).

```mermaid
flowchart TB
    classDef built fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20
    classDef planned fill:#fff8e1,stroke:#f57f17,stroke-width:2px,stroke-dasharray: 5 5,color:#e65100
    classDef actor fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1
    classDef external fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px,color:#4a148c

    Caller["Patient / Caller (EG / SA / AE — Arabic & English)"]:::actor
    Receptionist["Clinic Receptionist & Admin Staff"]:::actor
    Developer["AI Engineer / GitHub PR"]:::actor

    subgraph ClinicPlatform["Regional Polyclinic Voice AI & WhatsApp MVP Platform (AWS EC2 -> ECS)"]
        VoiceWorker["LiveKit WebRTC Voice Worker + Silero VAD + ClinicTurnEngine (Built - Phase 5)"]:::built
        AICore["Enterprise AI Core, Hybrid RAG, Guardrails & Clinic Tools (Built - Phases 1-4)"]:::built
        OpsOutbox["FastAPI Ops Service + DB NotificationOutbox Worker [Planned - Phase 7]"]:::planned
        AdminUI["Streamlit Clinic Portal + 1-Click Doctor Apology (Built Core / [Planned - Phase 8])"]:::built
        Langfuse["Self-Hosted Langfuse Trace Server (ADR-004)"]:::built
        Observability["Prometheus + Grafana + OIDC SSO [Planned - Phase 9 Post-MVP]"]:::planned
    end

    subgraph CloudProviders["External AI, Voice & Messaging Providers"]
        Deepgram["Deepgram Nova-3 STT / ElevenLabs Turbo v2.5 TTS (Phase 5)"]:::external
        Groq["Groq Cloud: Llama-3.3-70B & Llama-3.1-8B + Llama Guard 3 (ADR-003, ADR-005)"]:::external
        Gemini["Google Gemini: gemini-2.0-flash Backup LLM (ADR-003)"]:::external
        MetaWA["Meta WhatsApp Cloud API: Official Utility Templates [Planned - Phase 7] (ADR-011)"]:::external
        OpenAIJudge["OpenAI: gpt-4o-mini RAGAS CI Judge Only (ADR-006)"]:::external
    end

    Caller <-->|"Real-time Voice / Text Simulation"| VoiceWorker
    VoiceWorker <-->|"Streaming STT / TTS < 800ms"| Deepgram
    VoiceWorker <-->|"Utterance & Grounded Response"| AICore
    AICore <-->|"Primary Inference < 300ms TTFT"| Groq
    AICore -.->|"Failover on Circuit Breaker Open"| Gemini
    AICore -->|"Async PII-Redacted Spans < 1ms"| Langfuse
    AICore -.->|"Enqueue Confirmation / Reminder in DB Outbox [Planned]"| OpsOutbox
    OpsOutbox -.->|"Send Receipt, Reminder & Doctor Apology [Planned]"| MetaWA
    MetaWA -.->|"WhatsApp Utility Messages (E.164)"| Caller
    AICore -.->|"Metrics & Online Evals [Planned - Phase 9]"| Observability
    Receptionist <-->|"Live Queue, Escalations & 1-Click Doctor Apology"| AdminUI
    AdminUI <-->|"Read Appointments, Calls & Escalations"| AICore
    AdminUI -.->|"POST /api/v1/shifts/{id}/apology [Planned]"| OpsOutbox
    Developer -->|"Pull Request -> Golden Evals CI"| OpenAIJudge
```

---

## 2. مخطط الحاويات والمكوّنات البرمجية — المستوى الثاني والثالث (C4 Level 2/3: Containers & `src/` Components)

يوضّح هذا المخطط البنية الداخلية للحزم البرمجية المبنية حالياً في `src/` (`src/agent/`، `src/ai_core/`، `src/rag/`، `src/tools/`، `src/db/`، `src/dashboard/`، `src/config.py`) والحزمتين المخططتين للإطلاق الأول (`src/api/`، `src/notifications/`).

- القرارات المرتبطة: [ADR-001](./adr/001-hybrid-search-rrf.md)، [ADR-002](./adr/002-deterministic-gates-vs-prompt-rules.md)، [ADR-003](./adr/003-multi-tier-model-gateway.md)، [ADR-004](./adr/004-self-hosted-langfuse-tracing.md)، [ADR-005](./adr/005-finops-budgets-and-stage-routing.md)، [ADR-007](./adr/007-owasp-trust-layer.md)، [ADR-008](./adr/008-three-tier-cache-ladder.md)، [ADR-009](./adr/009-state-machine-over-agent-loop.md)، [ADR-010](./adr/010-e164-and-whatsapp-contact-separation.md)، [ADR-011](./adr/011-whatsapp-adapter-and-db-outbox.md)، [ADR-012](./adr/012-lean-aws-ec2-to-ecs-deployment.md).

```mermaid
flowchart TB
    classDef built fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20
    classDef planned fill:#fff8e1,stroke:#f57f17,stroke-width:2px,stroke-dasharray: 5 5,color:#e65100
    classDef storage fill:#e0f7fa,stroke:#006064,stroke-width:2px,color:#004d40

    Config["src/config.py: Typed Pydantic Settings + Regional Country Profile [Planned - Phase 6]"]:::built

    subgraph AgentLayer["src/agent/ — LiveKit Voice Pipeline & Turn Orchestration (Phase 5)"]
        VoiceAgent["voice_agent.py, prompts.py, messages.py & scenarios.py: ClinicVoiceAgent, GatewayBackedLLM, Silero VAD"]:::built
        TurnEngine["turn_engine.py & session_manager.py: ClinicTurnEngine, VerifiedCallerIdentity, SessionManager"]:::built
    end

    subgraph AICoreLayer["src/ai_core/ — Enterprise AI Core & Resilience (Phase 4)"]
        Guardrails["guardrails.py: InputGuardrail, OutputGuardrail, Regional PIIRedactor, AsyncLlamaGuardClassifier (ADR-007)"]:::built
        Cache["cache.py & text_normalizer.py: CacheLadder (Tier 1 LRU, Tier 2 Semantic >= 0.97, Tier 3 Prefix) (ADR-008)"]:::built
        FinOps["finops.py: FinOpsController (8k Call Budget, $10 Daily Cap, Tool Pruner) (ADR-005)"]:::built
        Gateway["gateway.py & circuit_breaker.py: ModelGateway, Stage Router (8B/70B), CircuitBreaker (ADR-003)"]:::built
        Workflow["workflow.py: AppointmentWorkflowStateMachine (max_steps=6 + WhatsApp Confirm [Planned - Phase 6]) (ADR-009)"]:::built
        Tracing["tracing.py: HierarchicalTracer & AsyncTraceExporter (W3C traceparent) (ADR-004)"]:::built
        Evals["evals.py: GoldenEvaluationRunner & RAGAS Judges (ADR-006)"]:::built
    end

    subgraph ToolsLayer["src/tools/ — Clinic Domain Tools & Safety Gates (Phase 3, 4.5 & 6)"]
        Gates["gates.py: DeterministicWriteGate, IdempotencyStore, CallerSessionContext + E.164 WhatsApp Separation [Planned - Phase 6]"]:::built
        BookingTool["appointment_booking.py: AppointmentBookingTool"]:::built
        ManageTool["manage_appointment.py: ManageAppointmentTool"]:::built
        AvailTool["doctor_availability.py: DoctorAvailabilityTool (+ Exception & Next-Slot Check [Planned - Phase 6])"]:::built
        KBTool["knowledge_search.py: ClinicKnowledgeSearchTool"]:::built
        HandoffTool["human_handoff.py: ReceptionistHandoffTool"]:::built
    end

    subgraph OpsNotifyLayer["src/api/ & src/notifications/ — Clinic Ops API & WhatsApp Outbox [Planned - Phase 7]"]
        OpsAPI["src/api/app.py: FastAPI Shift Apology & Queue Endpoints [Planned - Phase 7]"]:::planned
        OutboxScheduler["src/notifications/scheduler.py & outbox.py: Transactional Outbox & Reminder Worker [Planned - Phase 7]"]:::planned
        WAProvider["src/notifications/providers.py: WhatsAppProvider Protocol (MetaCloud + MockOutbox) [Planned - Phase 7]"]:::planned
    end

    subgraph RAGLayer["src/rag/ — Hybrid Knowledge Engine (Phase 2 & 4.3)"]
        Sanitizer["sanitizer.py & ingestion.py: DocumentSanitizer & Structure-Aware Chunker (ADR-001, ADR-007)"]:::built
        HybridRet["hybrid_retriever.py: HybridKnowledgeRetriever (Dense Qdrant + BM25Index + RRF k=60) (ADR-001)"]:::built
    end

    subgraph DBLayer["src/db/ — Async Relational Layer (Phase 1 & Phases 6-7)"]
        Repo["repository.py & session.py: ClinicRepository & AsyncSession"]:::built
        Models["models.py: Specialty, Doctor, DoctorSchedule, Patient, Appointment, Escalation (+ Exception & Outbox [Planned])"]:::built
    end

    subgraph DataStores["Data & Telemetry Stores (AWS EC2 Compose MVP -> ECS/RDS Phase 9)"]
        SQLitePG[("SQLite (Local) / PostgreSQL [Planned - Phase 8 AWS EC2]")]:::storage
        QdrantStore[("Qdrant Vector DB: clinic_kb & semantic_cache")]:::storage
    end

    VoiceAgent --> TurnEngine
    TurnEngine --> Guardrails
    Guardrails --> Cache
    Cache --> FinOps
    FinOps --> Gateway
    TurnEngine --> Workflow
    Workflow --> Gates
    Gates --> BookingTool
    Gates --> ManageTool
    TurnEngine --> AvailTool
    TurnEngine --> KBTool
    TurnEngine --> HandoffTool
    KBTool --> HybridRet
    Sanitizer --> HybridRet
    HybridRet <--> QdrantStore
    Cache <--> QdrantStore
    BookingTool --> Repo
    ManageTool --> Repo
    AvailTool --> Repo
    HandoffTool --> Repo
    OpsAPI -.-> Repo
    OpsAPI -.-> OutboxScheduler
    OutboxScheduler -.-> Repo
    OutboxScheduler -.-> WAProvider
    Repo --> Models
    Models <--> SQLitePG
    TurnEngine -.-> Tracing
    Guardrails -.-> Tracing
    Cache -.-> Tracing
    Gateway -.-> Tracing
    Workflow -.-> Tracing
    Config -.-> AgentLayer
    Config -.-> AICoreLayer
    Config -.-> OpsNotifyLayer
```

---

## 3. مخطط التتابع الزمني لدورة مكالمة حجز كاملة (Sequence Diagram: End-to-End Booking Call Lifecycle)

يوضّح هذا المخطط المسار الزمني الكامل لطلب مريض حجز موعد جديد عبر `ClinicTurnEngine`، بدءاً من فحص حواجز الحماية، مروراً بالكاش وبوابة FinOps وبوابة النماذج، ثم آلة الحالة المحدودة وبوابة الشروط المسبقة ومفتاح عدم التكرار، وصولاً إلى المعاملة الذرية في قاعدة البيانات وتصدير أثر التتبع المنقّى من البيانات الشخصية.

- القرارات المرتبطة: [ADR-002](./adr/002-deterministic-gates-vs-prompt-rules.md)، [ADR-003](./adr/003-multi-tier-model-gateway.md)، [ADR-004](./adr/004-self-hosted-langfuse-tracing.md)، [ADR-005](./adr/005-finops-budgets-and-stage-routing.md)، [ADR-007](./adr/007-owasp-trust-layer.md)، [ADR-008](./adr/008-three-tier-cache-ladder.md)، [ADR-009](./adr/009-state-machine-over-agent-loop.md).

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Patient Caller
    participant Engine as ClinicTurnEngine (turn_engine.py)
    participant Guard as Input/OutputGuardrail (guardrails.py)
    participant Cache as CacheLadder (cache.py)
    participant FinOps as FinOpsController (finops.py)
    participant GW as ModelGateway (gateway.py)
    participant FSM as AppointmentWorkflowStateMachine (workflow.py)
    participant Gate as DeterministicWriteGate & IdempotencyStore (gates.py)
    participant DB as ClinicRepository / Async DB (repository.py)
    participant Trace as HierarchicalTracer (tracing.py)

    Caller->>Engine: Spoken Arabic booking request + VerifiedCallerIdentity
    Engine->>Guard: InputGuardrail.check() (< 20ms CPU)
    Guard-->>Engine: Allowed + wrapped in <caller_utterance> XML delimiter
    Engine->>Cache: Lookup query in CacheLadder (tenant & branch scoped)
    Cache-->>Engine: BYPASS (personal booking intent is never cached)
    Engine->>GW: generate_turn(session_id, stage=DIALOGUE, caller_tools)
    GW->>FinOps: check_budget(session_id, stage=DIALOGUE)
    FinOps-->>GW: ALLOWED (clamped max_tokens <= 150, < 8k call budget, < $10 daily cap)
    GW-->>Engine: Primary Groq llama-3.3-70b-versatile emits book_appointment tool call
    Engine->>FSM: async_execute_tool -> execute(action=BOOK, slots, caller_session_scope)
    FSM->>FSM: INIT -> SLOT_COLLECTION (verify name, session phone, doctor, date)
    FSM->>Gate: PRECONDITION_GATE: verify_booking()
    Gate->>DB: Query active Doctor, DoctorSchedule & current_bookings_count
    DB-->>Gate: Shift active & current_bookings < max_capacity
    Gate-->>FSM: GateVerdict(allowed=True, schedule_id, fee)
    FSM->>Gate: IDEMPOTENCY_CHECK: lookup SHA-256(book:phone:doctor_id:schedule_id:date)
    Gate-->>FSM: Miss (not a duplicate retry)
    FSM->>DB: ATOMIC_EXECUTION: assign queue_number & insert Appointment
    DB-->>FSM: Confirmed Appointment (booking_code, queue_number)
    FSM->>Gate: Store result in IdempotencyStore (TTL 24h)
    FSM-->>Engine: WorkflowExecutionResult(terminal_state=COMPLETED)
    Engine->>FinOps: prune_tool_payload() & sync_session_snapshot()
    Engine->>GW: Post-tool spoken confirmation synthesis
    GW-->>Engine: Grounded Egyptian Arabic confirmation
    Engine->>Guard: OutputGuardrail.validate(arabic_response, grounding)
    Guard-->>Engine: Safe grounded confirmation
    Engine-->>Caller: Stream sentence chunks (queue_number + booking_code)
    Engine-)Trace: Async span export after EgyptianPIIRedactor.redact_dict() (< 1ms hot-path)
```

---

## 4. مخطط حالة قاطع الدائرة ومستويات التدهور الأربعة (State Diagram: Circuit Breaker & 4-Tier Graceful Degradation)

يمثّل هذا المخطط حالات `BreakerState` الفعلية في `src/ai_core/circuit_breaker.py` (`CLOSED`، `OPEN`، `HALF_OPEN`) وكيف تتكامل مع مستويات التدهور الأربعة `DegradationTier` في `src/ai_core/gateway.py` وقاطع التكلفة في `src/ai_core/finops.py`.

- القرارات المرتبطة: [ADR-003 (Multi-Tier Model Gateway)](./adr/003-multi-tier-model-gateway.md)، [ADR-005 (FinOps Cost Breaker)](./adr/005-finops-budgets-and-stage-routing.md).

```mermaid
stateDiagram-v2
    [*] --> CLOSED

    state "BreakerState.CLOSED (Normal)" as CLOSED
    state "BreakerState.OPEN (Fail-Fast < 1ms)" as OPEN
    state "BreakerState.HALF_OPEN (Single Probe)" as HALF_OPEN

    state "TIER_1_PRIMARY: Groq (llama-3.3-70b / llama-3.1-8b)" as TIER1
    state "TIER_2_BACKUP: Google Gemini (gemini-2.0-flash)" as TIER2
    state "TIER_3_SEARCH_ONLY: Grounded KB Snippet (No LLM)" as TIER3
    state "TIER_4_HUMAN_ESCALATION: Receptionist Transfer" as TIER4

    CLOSED --> TIER1: Request allowed
    CLOSED --> OPEN: 5 infra failures in 60s window (429 / 5xx / TTFT > 3.5s)
    OPEN --> HALF_OPEN: Cooldown elapsed (60s)
    HALF_OPEN --> CLOSED: Probe request succeeds
    HALF_OPEN --> OPEN: Probe request fails

    OPEN --> TIER2: Instant failover to backup provider
    TIER1 --> TIER2: Single-turn timeout or 5xx error
    TIER1 --> TIER3: FinOps call budget (8,000 tokens) or $10 daily cap exceeded
    TIER2 --> TIER3: Backup provider also unavailable or breaker OPEN
    TIER3 --> TIER4: No grounded KB snippet found or caller needs booking write
```

---

## 5. مخطط حالة سير عمل المواعيد الحتمي (State Diagram: `AppointmentWorkflowStateMachine`)

يمثّل هذا المخطط حالات `WorkflowState` الثماني المعتمدة في `src/ai_core/workflow.py` لإدارة عمليات `BOOK` و`CANCEL` و`RESCHEDULE` و`LOOKUP` مع سقف الخطوات الصارم (`workflow_max_steps = 6`).

- القرارات المرتبطة: [ADR-002 (Deterministic Write Gates & Idempotency)](./adr/002-deterministic-gates-vs-prompt-rules.md)، [ADR-009 (State Machine over Agent Loop)](./adr/009-state-machine-over-agent-loop.md).

```mermaid
stateDiagram-v2
    [*] --> INIT

    state "INIT: Inject CallerSessionContext phone" as INIT
    state "SLOT_COLLECTION: Validate mandatory fields & dates" as SLOT_COLLECTION
    state "PRECONDITION_GATE: DeterministicWriteGate check" as PRECONDITION_GATE
    state "IDEMPOTENCY_CHECK: SHA-256 IdempotencyStore lookup" as IDEMPOTENCY_CHECK
    state "ATOMIC_EXECUTION: Async DB transaction" as ATOMIC_EXECUTION
    state "COMPLETED: Confirmed / Replayed response" as COMPLETED
    state "REJECTED_BY_GATE: Shift full / invalid + next_available_slot" as REJECTED_BY_GATE
    state "ESCALATED: Transfer to human receptionist" as ESCALATED

    INIT --> REJECTED_BY_GATE: Session phone spoofing detected
    INIT --> SLOT_COLLECTION: Identity verified

    SLOT_COLLECTION --> SLOT_COLLECTION: Missing required slot (prompt caller, zero DB writes)
    SLOT_COLLECTION --> PRECONDITION_GATE: All required slots valid (BOOK / CANCEL / RESCHEDULE)
    SLOT_COLLECTION --> ATOMIC_EXECUTION: Action is LOOKUP

    PRECONDITION_GATE --> REJECTED_BY_GATE: Doctor inactive, shift full, past date, or not found
    PRECONDITION_GATE --> IDEMPOTENCY_CHECK: GateVerdict allowed (BOOK / RESCHEDULE)
    PRECONDITION_GATE --> ATOMIC_EXECUTION: GateVerdict allowed (CANCEL)

    IDEMPOTENCY_CHECK --> COMPLETED: Key hit in IdempotencyStore (idempotent_replay=True)
    IDEMPOTENCY_CHECK --> ATOMIC_EXECUTION: Key miss (first execution)

    ATOMIC_EXECUTION --> COMPLETED: Transaction committed & key stored
    ATOMIC_EXECUTION --> REJECTED_BY_GATE: Concurrent capacity race lost at DB commit
    ATOMIC_EXECUTION --> ESCALATED: Unexpected database error or step budget (> 6) exhausted

    COMPLETED --> [*]
    REJECTED_BY_GATE --> [*]
    ESCALATED --> [*]
```

---

## 6. مخطط علاقات كيانات قاعدة بيانات العيادة (ER Diagram: Clinic Relational Models)

يمثّل هذا المخطط الجداول الستة المبنية فعلياً في `src/db/models.py` (`specialties`، `doctors`، `doctor_schedules`، `patients`، `appointments`، `escalations`) بالإضافة إلى الجدولين والحقول المخططة للإطلاق الأول (`doctor_schedule_exceptions` `[Planned - Phase 6]`، و`notification_outbox` `[Planned - Phase 7]`).

- القرارات المرتبطة: [ADR-002 (Deterministic Write Gates & Atomic Queue Assignment)](./adr/002-deterministic-gates-vs-prompt-rules.md)، [ADR-010 (E.164 & WhatsApp Contact Separation)](./adr/010-e164-and-whatsapp-contact-separation.md)، [ADR-011 (WhatsApp Adapter & DB Outbox)](./adr/011-whatsapp-adapter-and-db-outbox.md).

```mermaid
erDiagram
    SPECIALTIES ||--o{ DOCTORS : "has doctors (CASCADE)"
    DOCTORS ||--o{ DOCTOR_SCHEDULES : "has shifts (CASCADE)"
    DOCTORS ||--o{ DOCTOR_SCHEDULE_EXCEPTIONS : "logs apologies [Planned Phase 6]"
    DOCTOR_SCHEDULES ||--o{ DOCTOR_SCHEDULE_EXCEPTIONS : "cancels date [Planned Phase 6]"
    DOCTORS ||--o{ APPOINTMENTS : "attends (CASCADE)"
    DOCTOR_SCHEDULES ||--o{ APPOINTMENTS : "allocates slots (CASCADE)"
    PATIENTS ||--o{ APPOINTMENTS : "books (CASCADE)"
    APPOINTMENTS ||--o{ NOTIFICATION_OUTBOX : "triggers WhatsApp [Planned Phase 7]"

    SPECIALTIES {
        int id PK
        string code UK
        string name_ar
        string name_en
        text description
    }

    DOCTORS {
        int id PK
        int specialty_id FK
        string name_ar
        string name_en
        string title
        float examination_fee
        float consultation_fee
        boolean is_active
    }

    DOCTOR_SCHEDULES {
        int id PK
        int doctor_id FK
        int day_of_week "0=Saturday..6=Friday"
        time start_time
        time end_time
        int max_capacity "default=20"
        boolean is_active
    }

    DOCTOR_SCHEDULE_EXCEPTIONS {
        int id PK
        int doctor_id FK "Planned Phase 6"
        int schedule_id FK "Planned Phase 6"
        date exception_date "indexed"
        string reason
        datetime created_at
    }

    PATIENTS {
        int id PK
        string name
        string phone "E.164 indexed (+20/+966/+971)"
        string whatsapp_phone "Planned Phase 6"
        boolean whatsapp_confirmed "Planned Phase 6"
        string gender
        datetime created_at
    }

    APPOINTMENTS {
        int id PK
        string booking_code UK
        int patient_id FK
        int doctor_id FK "UQ uq_doctor_date_queue"
        int schedule_id FK
        date appointment_date "UQ uq_doctor_date_queue"
        int queue_number "UQ uq_doctor_date_queue"
        string visit_type "examination | consultation"
        string status "confirmed | cancelled | cancelled_by_doctor | completed"
        float fee
        text notes
        datetime created_at
    }

    NOTIFICATION_OUTBOX {
        int id PK
        int appointment_id FK "Planned Phase 7"
        string recipient_phone "E.164"
        string event_type "booking_confirmation | reminder | doctor_apology"
        string idempotency_key UK
        string status "pending | sent | failed | cancelled"
        datetime scheduled_at "indexed"
        int retry_count
        datetime sent_at
    }

    ESCALATIONS {
        int id PK
        string ticket_id UK
        string session_id "indexed"
        string caller_name
        string caller_phone "indexed"
        text reason
        text summary
        string department "reception | emergency"
        string urgency "low | medium | high | critical"
        string status "queued | in_progress | resolved"
        int estimated_wait_seconds
        datetime created_at
        datetime updated_at
        datetime acknowledged_at
        datetime resolved_at
    }
```

---

## 7. بروتوكول إشعارات الواتساب واعتذار الطبيب وطوبولوجيا النشر السحابي (`Phases 6–8 MVP`)

- **عزل الواتساب عن المسار الصوتي الحرج ([ADR-011](./adr/011-whatsapp-adapter-and-db-outbox.md))**: تكتفي معاملة الحجز أو الإلغاء الصوتية بإدراج صفوف في جدول `notification_outbox` خلال أقل من `5ms`، بينما يتولى العامل الخلفي المستقل إرسال قوالب `Meta WhatsApp Cloud API` الرسمية (تأكيد فوري عقب الحجز + تذكير قبل الشيفت بـ `24` ساعة أو `3` ساعات لحجوزات نفس اليوم).
- **سير عمل اعتذار الطبيب بضغطة زر (`FastAPI` + `Streamlit`)**: عند تسجيل اعتذار طبيب عن تاريخ محدد، تنفذ خدمة `FastAPI` معاملة ذرية تُنشئ سجل `doctor_schedule_exceptions` لإغلاق الشيفت فوراً أمام المتصلين الجدد، وتحوّل حجوزات اليوم المؤكدة إلى `cancelled_by_doctor` دون ترحيل قسري يكسر سعة الشيفت القادم، وتلغي التذكيرات المعلقة، وتجدول رسائل اعتذار واتساب تتضمن أقرب شيفت قادم للطبيب به أماكن شاغرة فعلياً.
- **طوبولوجيا النشر السحابي الاقتصادي القابل للتوسع ([ADR-012](./adr/012-lean-aws-ec2-to-ecs-deployment.md))**: تُغلَّف مكوّنات النظام في حاويات `12-Factor` عديمة الحالة (`voice-worker`، `ops-api-scheduler`، `dashboard`، `postgres`، `qdrant`) تُبنى عبر `GitHub Actions` وتُدفع إلى `AWS ECR`، وتعمل في الإطلاق الأول على عقدة `AWS EC2` موفرة مع أسرار `AWS SSM` ونسخ احتياطي يومي على `Amazon S3`، مع جاهزية الانتقال الصفري لنفس الصور إلى `AWS ECS Fargate + RDS` في `Phase 9`.

</div>
