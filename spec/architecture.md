<div dir="rtl" align="right">

# المعمارية الهندسية الشاملة والمخططات ككود (System Architecture & Diagram-as-Code)

يمثّل هذا المستند المرجع المعماري الرسمي لنظام **المساعد الصوتي الذكي للعيادات والمراكز الطبية المصرية (Voice AI Medical Receptionist)** وفق منهجية **C4 Model** ومبدأ **المخططات ككود (Diagram-as-Code)**.

- للاطلاع على التبرير الهندسي والبدائل المرفوضة لكل قرار معماري، راجع [**فهرس سجلات القرارات المعمارية (`spec/adr/README.md`)**](./adr/README.md).
- للاطلاع على نموذج التهديدات الأمنية وضوابط OWASP LLM Top 10، راجع [**`spec/security/threat_model.md`**](./security/threat_model.md).

---

## دليل الترميز البصري في المخططات (Built vs. Planned Legend)

التزاماً بمبدأ **الكود هو مصدر الحقيقة (As-Built Source of Truth)**:
- **المكوّنات المبنية فعلياً (Phases 1–4 & Initial Dashboard)**: تُرسم **بخط متصل (`Solid Line`)** وتعمل حالياً في المستودع مع تغطية اختبارية كاملة.
- **المكوّنات المخطط لاستكمالها في المراحل القادمة (Phases 5, 6, 8)**: تُرسم **بخط متقطع (`Dashed Line`)** وتُميَّز بالصنف البصري `classDef planned` مع الوسم الصريح `[Planned]`.

---

## 1. مخطط سياق النظام — المستوى الأول (C4 Level 1: System Context)

يوضّح هذا المخطط موقع المساعد الصوتي الذكي للعيادة وعلاقته بالمرضى، وموظفي الاستقبال، والمزوّدين السحابيين، ومنظومة الرصد والتقييم.

- القرارات المرتبطة: [ADR-003 (Model Gateway & Gemini Fallback)](./adr/003-multi-tier-model-gateway.md)، [ADR-004 (Self-Hosted Langfuse)](./adr/004-self-hosted-langfuse-tracing.md)، [ADR-006 (RAGAS CI Gate)](./adr/006-ragas-ci-evaluation.md).

```mermaid
flowchart TB
    classDef built fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20
    classDef planned fill:#fff8e1,stroke:#f57f17,stroke-width:2px,stroke-dasharray: 5 5,color:#e65100
    classDef actor fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1
    classDef external fill:#f3e5f5,stroke:#6a1b9a,stroke-width:2px,color:#4a148c

    Caller["Patient / Caller (Egyptian Arabic & English)"]:::actor
    Receptionist["Clinic Receptionist & Admin Staff"]:::actor
    Developer["AI Engineer / GitHub PR"]:::actor

    subgraph ClinicPlatform["Egyptian Polyclinic Voice AI Platform"]
        VoiceWorker["LiveKit WebRTC Voice Worker + Silero VAD [Planned - Phase 5]"]:::planned
        AICore["Enterprise AI Core, Hybrid RAG, Guardrails & Clinic Tools (Built - Phases 1-4)"]:::built
        AdminUI["Streamlit Clinic Admin Dashboard (Built Core / Phase 7 Expansion)"]:::built
        Langfuse["Self-Hosted Langfuse Trace Server (ADR-004)"]:::built
        Observability["Prometheus + Grafana + SSO/RBAC [Planned - Phase 6]"]:::planned
    end

    subgraph CloudProviders["External AI & Media Providers"]
        Deepgram["Deepgram Nova-3 STT / ElevenLabs Turbo v2.5 TTS [Planned - Phase 5]"]:::planned
        Groq["Groq Cloud: Llama-3.3-70B & Llama-3.1-8B + Llama Guard 3 (ADR-003, ADR-005)"]:::external
        Gemini["Google Gemini: gemini-2.0-flash Backup LLM (ADR-003)"]:::external
        OpenAIJudge["OpenAI: gpt-4o-mini RAGAS CI Judge Only (ADR-006)"]:::external
    end

    Caller <-->|"Real-time Voice / Text Simulation"| VoiceWorker
    VoiceWorker <-->|"Streaming STT / TTS < 800ms"| Deepgram
    VoiceWorker <-->|"Utterance & Grounded Response"| AICore
    AICore <-->|"Primary Inference < 300ms TTFT"| Groq
    AICore -.->|"Failover on Circuit Breaker Open"| Gemini
    AICore -->|"Async PII-Redacted Spans < 1ms"| Langfuse
    AICore -.->|"Metrics & Online Evals [Planned]"| Observability
    Receptionist <-->|"Live Queue, Escalations & Analytics"| AdminUI
    AdminUI <-->|"Read Appointments, Calls & Escalations"| AICore
    Developer -->|"Pull Request -> Golden Evals CI"| OpenAIJudge
```

---

## 2. مخطط الحاويات والمكوّنات البرمجية — المستوى الثاني والثالث (C4 Level 2/3: Containers & `src/` Components)

يوضّح هذا المخطط البنية الداخلية للحزم البرمجية في `src/` (`src/ai_core/`، `src/rag/`، `src/tools/`، `src/db/`، `src/config.py`) وكيفية تفاعلها مع مخازن البيانات.

- القرارات المرتبطة: [ADR-001](./adr/001-hybrid-search-rrf.md)، [ADR-002](./adr/002-deterministic-gates-vs-prompt-rules.md)، [ADR-003](./adr/003-multi-tier-model-gateway.md)، [ADR-004](./adr/004-self-hosted-langfuse-tracing.md)، [ADR-005](./adr/005-finops-budgets-and-stage-routing.md)، [ADR-007](./adr/007-owasp-trust-layer.md)، [ADR-008](./adr/008-three-tier-cache-ladder.md)، [ADR-009](./adr/009-state-machine-over-agent-loop.md).

```mermaid
flowchart TB
    classDef built fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20
    classDef planned fill:#fff8e1,stroke:#f57f17,stroke-width:2px,stroke-dasharray: 5 5,color:#e65100
    classDef storage fill:#e0f7fa,stroke:#006064,stroke-width:2px,color:#004d40

    Config["src/config.py: Typed Pydantic Settings"]:::built

    subgraph AgentLayer["src/agent/ — Voice Pipeline Layer"]
        VoiceAgent["voice_agent.py & session_manager.py [Planned - Phase 5 Wiring]"]:::planned
    end

    subgraph AICoreLayer["src/ai_core/ — Enterprise AI Core & Resilience (Phase 4)"]
        Guardrails["guardrails.py: InputGuardrail, OutputGuardrail, EgyptianPIIRedactor, AsyncLlamaGuardClassifier (ADR-007)"]:::built
        Cache["cache.py & text_normalizer.py: CacheLadder (Tier 1 LRU, Tier 2 Semantic >= 0.97, Tier 3 Prefix) (ADR-008)"]:::built
        FinOps["finops.py: FinOpsController (8k Call Budget, $10 Daily Cap, Tool Pruner) (ADR-005)"]:::built
        Gateway["gateway.py & circuit_breaker.py: ModelGateway, Stage Router (8B/70B), CircuitBreaker (ADR-003)"]:::built
        Workflow["workflow.py: AppointmentWorkflowStateMachine (max_steps=6) (ADR-009)"]:::built
        Tracing["tracing.py: HierarchicalTracer & AsyncTraceExporter (W3C traceparent) (ADR-004)"]:::built
        Evals["evals.py: GoldenEvaluationRunner & RAGAS Judges (ADR-006)"]:::built
    end

    subgraph ToolsLayer["src/tools/ — Clinic Domain Tools & Safety Gates (Phase 3 & 4.5)"]
        Gates["gates.py: DeterministicWriteGate, IdempotencyStore, CallerSessionContext (ADR-002)"]:::built
        BookingTool["appointment_booking.py: AppointmentBookingTool"]:::built
        ManageTool["manage_appointment.py: ManageAppointmentTool"]:::built
        AvailTool["doctor_availability.py: DoctorAvailabilityTool"]:::built
        KBTool["knowledge_search.py: ClinicKnowledgeSearchTool"]:::built
        HandoffTool["human_handoff.py: ReceptionistEscalationTool"]:::built
    end

    subgraph RAGLayer["src/rag/ — Hybrid Knowledge Engine (Phase 2 & 4.3)"]
        Sanitizer["sanitizer.py & ingestion.py: DocumentSanitizer & Structure-Aware Chunker (ADR-001, ADR-007)"]:::built
        HybridRet["hybrid_retriever.py: HybridKnowledgeRetriever (Dense Qdrant + BM25Index + RRF k=60) (ADR-001)"]:::built
    end

    subgraph DBLayer["src/db/ — Async Relational Layer (Phase 1)"]
        Repo["repository.py & session.py: ClinicRepository & AsyncSession"]:::built
        Models["models.py: Specialty, Doctor, DoctorSchedule, Patient, Appointment, Escalation"]:::built
    end

    subgraph DataStores["Data & Telemetry Stores"]
        SQLitePG[("SQLite (Local) / PostgreSQL [Planned Phase 8 ECS]")]:::storage
        QdrantStore[("Qdrant Vector DB: clinic_kb & semantic_cache")]:::storage
    end

    VoiceAgent -.-> Guardrails
    Guardrails --> Cache
    Cache --> FinOps
    FinOps --> Gateway
    Gateway --> Workflow
    Workflow --> Gates
    Gates --> BookingTool
    Gates --> ManageTool
    Gateway --> AvailTool
    Gateway --> KBTool
    Gateway --> HandoffTool
    KBTool --> HybridRet
    Sanitizer --> HybridRet
    HybridRet <--> QdrantStore
    Cache <--> QdrantStore
    BookingTool --> Repo
    ManageTool --> Repo
    AvailTool --> Repo
    HandoffTool --> Repo
    Repo --> Models
    Models <--> SQLitePG
    Guardrails -.-> Tracing
    Cache -.-> Tracing
    Gateway -.-> Tracing
    Workflow -.-> Tracing
    Config -.-> AICoreLayer
```

---

## 3. مخطط التتابع الزمني لدورة مكالمة حجز كاملة (Sequence Diagram: End-to-End Booking Call Lifecycle)

يوضّح هذا المخطط المسار الزمني الكامل لطلب مريض حجز موعد جديد، بدءاً من فحص حواجز الحماية، مروراً بالكاش وبوابة FinOps وبوابة النماذج، ثم آلة الحالة المحدودة وبوابة الشروط المسبقة ومفتاح عدم التكرار، وصولاً إلى المعاملة الذرية في قاعدة البيانات وتصدير أثر التتبع المنقّى من البيانات الشخصية.

- القرارات المرتبطة: [ADR-002](./adr/002-deterministic-gates-vs-prompt-rules.md)، [ADR-003](./adr/003-multi-tier-model-gateway.md)، [ADR-004](./adr/004-self-hosted-langfuse-tracing.md)، [ADR-005](./adr/005-finops-budgets-and-stage-routing.md)، [ADR-007](./adr/007-owasp-trust-layer.md)، [ADR-008](./adr/008-three-tier-cache-ladder.md)، [ADR-009](./adr/009-state-machine-over-agent-loop.md).

```mermaid
sequenceDiagram
    autonumber
    actor Caller as Patient Caller
    participant Guard as Input/OutputGuardrail (guardrails.py)
    participant Cache as CacheLadder (cache.py)
    participant FinOps as FinOpsController (finops.py)
    participant GW as ModelGateway (gateway.py)
    participant FSM as AppointmentWorkflowStateMachine (workflow.py)
    participant Gate as DeterministicWriteGate & IdempotencyStore (gates.py)
    participant DB as ClinicRepository / Async DB (repository.py)
    participant Trace as HierarchicalTracer (tracing.py)

    Caller->>Guard: Spoken Arabic booking request (with CallerSessionContext phone)
    Guard->>Guard: Check injection, emergency & medical ban (< 20ms CPU)
    Guard->>Guard: Wrap in <caller_utterance> XML delimiter
    Guard->>Cache: Lookup query in CacheabilityPolicy
    Cache-->>Guard: BYPASS (personal booking intent is never cached)
    Guard->>FinOps: check_budget(session_id, stage=DIALOGUE)
    FinOps-->>GW: ALLOWED (clamped max_tokens <= 150, < 8k call budget, < $10 daily cap)
    GW->>GW: Primary Groq llama-3.3-70b-versatile emits book_appointment tool call
    GW->>FSM: execute(action=BOOK, slots, session_phone)
    FSM->>FSM: INIT -> SLOT_COLLECTION (verify name, session phone, doctor, date)
    FSM->>Gate: PRECONDITION_GATE: check_booking_preconditions()
    Gate->>DB: Query active Doctor, DoctorSchedule & current_bookings_count
    DB-->>Gate: Shift active & current_bookings < max_capacity
    Gate-->>FSM: GateVerdict(allowed=True, schedule_id, fee)
    FSM->>Gate: IDEMPOTENCY_CHECK: lookup SHA-256(book:phone:doctor_id:schedule_id:date)
    Gate-->>FSM: Miss (not a duplicate retry)
    FSM->>DB: ATOMIC_EXECUTION: assign queue_number & insert Appointment
    DB-->>FSM: Confirmed Appointment (booking_code, queue_number)
    FSM->>Gate: Store result in IdempotencyStore (TTL 24h)
    FSM-->>GW: WorkflowExecutionResult(terminal_state=COMPLETED)
    GW->>FinOps: prune_tool_payload() & record_usage(prompt_tokens, completion_tokens)
    GW->>Guard: OutputGuardrail.validate(arabic_response)
    Guard-->>Caller: Polite Egyptian Arabic confirmation + queue number
    GW-)Trace: Async span export after EgyptianPIIRedactor.redact_dict() (< 1ms hot-path)
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

يمثّل هذا المخطط الجداول الستة الفعلية في `src/db/models.py` (`specialties`، `doctors`، `doctor_schedules`، `patients`، `appointments`، `escalations`) وعلاقات المفاتيح الأجنبية وقيد التفرد الذري `uq_doctor_date_queue`.

- القرارات المرتبطة: [ADR-002 (Deterministic Write Gates & Atomic Queue Assignment)](./adr/002-deterministic-gates-vs-prompt-rules.md).

```mermaid
erDiagram
    SPECIALTIES ||--o{ DOCTORS : "has doctors (CASCADE)"
    DOCTORS ||--o{ DOCTOR_SCHEDULES : "has shifts (CASCADE)"
    DOCTORS ||--o{ APPOINTMENTS : "attends (CASCADE)"
    DOCTOR_SCHEDULES ||--o{ APPOINTMENTS : "allocates slots (CASCADE)"
    PATIENTS ||--o{ APPOINTMENTS : "books (CASCADE)"

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

    PATIENTS {
        int id PK
        string name
        string phone "indexed"
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
        string status "confirmed | cancelled | completed"
        float fee
        text notes
        datetime created_at
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

## 7. سجل الديون التقنية المستبعدة من المخططات (Technical Debt — Legacy Restaurant Artifacts)

بموجب القرار الهندسي المتفق عليه (السؤال الخامس والقيود `C2`)، يحتوي المستودع على بقايا قديمة من النموذج الأولي السابق (نموذج المطعم) تم الإبقاء عليها مؤقتاً لعدم كسر اختبارات التوافق الرجعي، ولكنها **مستبعدة تماماً من معمارية العيادة الطبية ومن المخططات أعلاه**:

| الملف البرمجي أو الاختبار | الوصف | خطة المعالجة المستقبلية |
|:---|:---|:---|
| `src/tools/order_status.py` | أداة قديمة للاستعلام عن حالة طلبات المطعم | تُحذف في تنظيف ما قبل الإطلاق النهائي بعد إزالة الاختبارات المرتبطة بها |
| `src/tools/reservation.py` | أداة قديمة لحجز طاولات المطعم (حلّت محلها `src/tools/appointment_booking.py`) | تُحذف مع `order_status.py` |
| `src/tools/legacy_schemas.py` | مخططات Pydantic القديمة لأدوات المطعم (حلّت محلها `src/tools/schemas.py`) | تُحذف بعد ترحيل أي إشارات متبقية في اختبارات التوافق |
| `tests/test_order_status.py` و`tests/test_reservation.py` و`tests/test_tools.py` | اختبارات وحدات قديمة تختبر أدوات المطعم المذكورة أعلاه | تُستبدل بالكامل باختبارات `tests/test_clinic_tools.py` و`tests/test_agent.py` في المرحلة الخامسة |

</div>
