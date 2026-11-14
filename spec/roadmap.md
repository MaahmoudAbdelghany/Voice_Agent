# Product Roadmap — Voice AI Agent & WhatsApp Operations for Polyclinics (Egypt, KSA & UAE)

## Overview
This roadmap is a **Living Document** under Spec-Driven Development (SDD). Each milestone progresses through:
`Specification (Plan + Requirements + Validation) -> Human Review -> Implementation -> Validation -> Commit & Push -> Replanning`.

---

## Phased Milestones

### Phase 1: Project Foundation & Async Database Layer 🏛️
*Goal: Establish environment configuration for polyclinics and build a robust, async relational database for doctors, specialties, schedules, and patient appointments.*

- [x] **Feature 1.1**: Spec Constitution & Governance Pivot (`spec/mission.md`, `spec/tech.md`, `spec/roadmap.md`).
- [x] **Feature 1.2**: Configuration & Database Engine (`src/config.py`, Async SQLAlchemy with SQLite / PostgreSQL connection).
- [x] **Feature 1.3**: Relational Models & Schemas (`Specialty`, `Doctor`, `DoctorSchedule`, `Patient`, `Appointment`).
- [x] **Feature 1.4**: Database Seeder & Repository Layer (Realistic Egyptian doctors, specialties, shift hours, and capacity management).
- [x] **Feature 1.5**: Automated Database & Concurrency Test Suite (`tests/test_database.py`).

### Phase 2: Egyptian Clinic Knowledge Base Engine (Qdrant RAG) 📚
*Goal: Provide instant, grounded semantic search for specialty questions, clinic services, test preparation, doctor credentials, and insurance.*

- [x] **Feature 2.1**: Egyptian Clinic Knowledge Base document (`knowledge_base/clinic_kb.md`).
- [x] **Feature 2.2**: Vector Store Ingestion & CLI Pipeline for `clinic_kb` collection (`scripts/ingest_clinic_knowledge.py`).
- [x] **Feature 2.3**: Knowledge Retrieval Verification & Tests (`tests/test_clinic_rag.py`).

### Phase 3: Clinic Domain Execution Tools 🛠️
*Goal: Implement strongly-typed, voice-friendly tools for live appointment booking, schedule lookup, appointment management, and receptionist transfer.*

- [x] **Feature 3.1**: Pydantic schemas for medical tool inputs and outputs (`src/tools/schemas.py`).
- [x] **Feature 3.2**: Doctor Availability & Shift Lookup Tool (`src/tools/doctor_availability.py`).
- [x] **Feature 3.3**: Appointment Booking Tool with atomic queue number assignment (`src/tools/appointment_booking.py`).
- [x] **Feature 3.4**: Appointment Query, Cancellation & Rescheduling Tool (`src/tools/manage_appointment.py`).
- [x] **Feature 3.5**: Clinic Knowledge Search Tool (`src/tools/knowledge_search.py`).
- [x] **Feature 3.6**: Human Receptionist Escalation Tool with Dashboard Alert (`src/tools/human_handoff.py`).
- [x] **Feature 3.7**: Automated Unit & Integration Tests for Medical Tools (`tests/test_clinic_tools.py`).

### Phase 4: Enterprise AI Architecture, Resilience & Design-Time LLMOps 🛡️
*Goal: Harden the AI system into an enterprise-grade, fault-tolerant platform based on production AI system design principles — Stage-Based Model Routing, 3-Tier Caching, OWASP-aligned Trust Layer, Deterministic Safety Gates, Circuit Breakers — and bake in design-time LLMOps from Day 1: hierarchical trace logging, FinOps token budgets, and RAGAS-gated CI evaluation.*

- [x] **Feature 4.1**: Model Gateway, Stage-Based Model Routing & Circuit Breaker (`src/ai_core/gateway.py` — `llama-3.1-8b-instant` for classification/extraction, `llama-3.3-70b-versatile` for dialogue, Google Gemini fallback via LiteLLM, 3.5s TTFT timeout, `max_tokens=150` per voice turn).
- [x] **Feature 4.2**: 3-Tier Caching Ladder (`src/ai_core/cache.py` with Tier 1 Exact Hash, Tier 2 Metadata-Scoped Semantic Cache >= 0.97, Tier 3 Prompt Prefix Caching).
- [x] **Feature 4.3**: Hybrid RAG Upgrade (`src/rag/hybrid_retriever.py` with Dense Vector Qdrant + BM25 via Reciprocal Rank Fusion & structure-aware chunking).
- [x] **Feature 4.4**: OWASP-Aligned Trust Layer & Runtime Guardrails (`src/ai_core/guardrails.py`, `src/rag/sanitizer.py`, `spec/security/threat_model.md` — <20ms regex injection & medical diagnosis filter, XML delimiters for untrusted caller/RAG content, ingestion-time document sanitization, Literal/Enum-constrained outputs, Presidio with Egyptian recognizers pre-trace, async sampled Llama Guard).
- [x] **Feature 4.5**: Deterministic State Machine, Idempotency Keys & Write Safety Gates (`src/ai_core/workflow.py`, `src/tools/gates.py` for atomic booking and shift caps).
- [x] **Feature 4.6**: Hierarchical LLM Trace Logging (`src/ai_core/tracing.py` — self-hosted Langfuse + OpenTelemetry-compatible nested spans, `contextvars` async isolation, async batch export <1ms overhead, W3C `traceparent` propagation).
- [x] **Feature 4.7**: FinOps Token Budgets & Cost Circuit Breaker (`src/ai_core/finops.py` — 8,000 tokens/call budget, $10/day cap with 80% alert, degrade to Tier 3 search-only / receptionist on breach).
- [x] **Feature 4.8**: Golden Evaluation Suite & RAGAS CI Gate (`tests/evals/`, `.github/workflows/evals.yml` — Faithfulness >= 0.90, Context Recall >= 0.85, Context Precision >= 0.80, Answer Relevancy >= 0.85 + exact-match on structured fields, `gpt-4o-mini` judge, triggered on prompt/model PRs).
- [x] **Feature 4.9**: Architecture Decision Records (ADRs) & Diagram-as-Code (`spec/adr/`, `spec/architecture.md`).

### Phase 5: Real-Time LiveKit Voice Agent Core & Medical Persona 🎙️
*Goal: Build the real-time WebRTC audio pipeline tuned for polite Egyptian Arabic, medical safety guardrails, and rapid tool calling.*

- [x] **Feature 5.1**: Egyptian Clinic Assistant Persona, System Prompts & Medical Guardrails (`src/agent/prompts.py`, `src/agent/messages.py`).
- [x] **Feature 5.2**: Medical Call Session State & Metric Tracking (`src/agent/session_manager.py`).
- [x] **Feature 5.3**: Legacy Restaurant Purge & Codebase Sanitization (`src/tools/`, `src/agent/`, `src/dashboard/`, `src/config.py`).
- [x] **Feature 5.4**: LiveKit Voice Pipeline Worker & Clinic Turn Engine registering all clinic tools (`src/agent/voice_agent.py`, `src/agent/turn_engine.py`, `scripts/generate_token.py`).
- [x] **Feature 5.5**: CLI Simulated Call Runner & Clinic Scenarios (`scripts/test_call.py`, `src/agent/scenarios.py`).
- [x] **Feature 5.6**: Automated Voice Orchestration & Guardrail Test Suite (`tests/test_agent.py`).

### Phase 6: Regional Readiness, Confirmed WhatsApp Contact & Doctor Schedule Exceptions 🌍
*Goal: Prepare the booking and availability engine for Egypt (default), Saudi Arabia, and UAE via canonical `E.164` phones, separate session caller identity from confirmed WhatsApp contact numbers, and support emergency doctor shift exceptions.*

- [ ] **Feature 6.1**: Regional Clinic Profile & `E.164` Multi-Country Phone Engine (`src/config.py`, `src/db/schemas.py`, `src/ai_core/guardrails.py` — supporting Egypt `+20` default, KSA `+966`, UAE `+971`, configurable currency/timezone/dialect, and regional PII redaction).
- [ ] **Feature 6.2**: Confirmed WhatsApp Contact Phone Separation in Voice Booking Flow (`src/db/models.py`, `src/tools/schemas.py`, `src/tools/gates.py`, `src/ai_core/workflow.py`, `src/agent/prompts.py` — `whatsapp_phone` + `whatsapp_confirmed` with explicit digit-group read-back confirmation).
- [ ] **Feature 6.3**: Doctor Schedule Exceptions & Next-Available-Slot Lookup (`src/db/models.py`, `src/db/repository.py`, `src/tools/doctor_availability.py`, `src/tools/gates.py` — `DoctorScheduleException` model blocking bookings on cancelled shifts and surfacing the next shift with open capacity during voice inquiries).

### Phase 7: Modular WhatsApp Notifications, Outbox Scheduler & Doctor Apology Workflow 💬
*Goal: Deliver instant post-booking receipts, automated pre-shift reminders, and bulk doctor-apology notifications with next-available-slot guidance via Meta WhatsApp Cloud API at minimum cost and zero voice-path latency.*

- [ ] **Feature 7.1**: Pluggable WhatsApp Provider Layer & Localized Utility Templates (`src/notifications/providers.py`, `src/notifications/templates.py` — `WhatsAppProvider` Protocol, official direct `MetaCloudWhatsAppProvider` via async `httpx`, and local `MockOutboxProvider` for dev/demos).
- [ ] **Feature 7.2**: Transactional Notification Outbox & Async Reminder Worker (`src/db/models.py`, `src/notifications/outbox.py`, `src/notifications/scheduler.py` — DB-backed `NotificationOutbox` with idempotency keys and exponential backoff, instant booking confirmation + configurable `24h` / `3h` pre-shift reminders, zero `Redis`/`Celery` overhead).
- [ ] **Feature 7.3**: Clinic Operations FastAPI & Atomic Doctor Apology Orchestrator (`src/api/app.py`, `src/api/routes/shifts.py`, `src/notifications/apology_service.py` — close shift via `DoctorScheduleException`, transition affected bookings to `cancelled_by_doctor`, cancel pending reminders, compute next open shift, and enqueue WhatsApp apologies).

### Phase 8: Receptionist Clinic Portal & Cost-Optimized AWS MVP Deployment 🚀
*Goal: Equip clinic receptionists with an RTL operational portal including 1-click doctor apology handling and WhatsApp outbox visibility, and ship a lean, 12-Factor containerized AWS EC2 production deployment.*

> Note: Existing historical spec folders `spec/features/feature-501..503-*` remain preserved on disk as reference context for dashboard pages.

- [ ] **Feature 8.1**: RTL Receptionist Portal, Live Queue, WhatsApp Outbox & 1-Click Doctor Apology (`src/dashboard/app.py`, `src/dashboard/pages/` — call logs, daily appointments queue, receptionist escalations, WhatsApp status monitor, and 1-click shift apology wired to `FastAPI`).
- [ ] **Feature 8.2**: Multi-Stage `12-Factor` Dockerization & Compose Stack (`Dockerfile`, `docker-compose.yml` — clean container boundaries for `voice-worker`, `ops-api-scheduler`, `dashboard`, `postgres`, and `qdrant`, portable between single-host EC2 and ECS Fargate).
- [ ] **Feature 8.3**: Lean AWS EC2 Production Pipeline, SSM Secrets, S3 Backups & E2E Smoke Suite (`.github/workflows/deploy.yml`, `infra/aws-mvp/`, `tests/test_e2e_mvp.py` — `AWS ECR` image push, `SSM Parameter Store` secrets, automated `PostgreSQL` backups to `S3`, and full booking -> reminder -> doctor apology end-to-end verification).

### Phase 9: Post-MVP Enterprise Scale, Multi-Branch Isolation & Observability 📈
*Goal: Scale the platform for multi-branch hospital groups once MVP clinic ROI is proven — full Prometheus/Grafana telemetry, online sampled evaluation, OIDC SSO/RBAC, cryptographic tenant isolation, 50-call load testing, and AWS ECS Fargate + RDS migration.*

- [ ] **Feature 9.1**: Prometheus Metrics Exporter & Grafana/Alertmanager Dashboards (`src/ops/metrics.py`, `infra/observability/` — bounded labels only, P95 latency & budget alerts).
- [ ] **Feature 9.2**: Online Sampled Evaluation (`src/ops/online_eval.py` — async RAGAS on 10% of production traces + sampled Llama Guard pushed to Langfuse).
- [ ] **Feature 9.3**: OIDC SSO & RBAC (`src/auth/` — pluggable Keycloak local / Microsoft Entra ID prod; roles `admin`, `receptionist`, `doctor`, `viewer`).
- [ ] **Feature 9.4**: Multi-Branch Tenant Isolation & Role-Scoped Tools (`tenant_id`/`branch_id` pre-retrieval filtering across Qdrant and PostgreSQL).
- [ ] **Feature 9.5**: 50-Call Load Testing, Formal SLI/SLO/SLA Contract & AWS ECS Fargate + RDS Migration (`tests/load/`, `spec/sla.md`, `infra/ecs/`).
