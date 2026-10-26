# Product Roadmap — Voice AI Agent for Egyptian Polyclinics

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
- [ ] **Feature 4.3**: Hybrid RAG Upgrade (`src/rag/hybrid_retriever.py` with Dense Vector Qdrant + BM25 via Reciprocal Rank Fusion & structure-aware chunking).
- [ ] **Feature 4.4**: OWASP-Aligned Trust Layer & Runtime Guardrails (`src/ai_core/guardrails.py`, `src/rag/sanitizer.py`, `spec/security/threat_model.md` — <20ms regex injection & medical diagnosis filter, XML delimiters for untrusted caller/RAG content, ingestion-time document sanitization, Literal/Enum-constrained outputs, Presidio with Egyptian recognizers pre-trace, async sampled Llama Guard).
- [ ] **Feature 4.5**: Deterministic State Machine, Idempotency Keys & Write Safety Gates (`src/ai_core/workflow.py`, `src/tools/gates.py` for atomic booking and shift caps).
- [ ] **Feature 4.6**: Hierarchical LLM Trace Logging (`src/ai_core/tracing.py` — self-hosted Langfuse + OpenTelemetry-compatible nested spans, `contextvars` async isolation, async batch export <1ms overhead, W3C `traceparent` propagation).
- [ ] **Feature 4.7**: FinOps Token Budgets & Cost Circuit Breaker (`src/ai_core/finops.py` — 8,000 tokens/call budget, $10/day cap with 80% alert, degrade to Tier 3 search-only / receptionist on breach).
- [ ] **Feature 4.8**: Golden Evaluation Suite & RAGAS CI Gate (`tests/evals/`, `.github/workflows/evals.yml` — Faithfulness >= 0.90, Context Recall >= 0.85, Context Precision >= 0.80, Answer Relevancy >= 0.85 + exact-match on structured fields, `gpt-4o-mini` judge, triggered on prompt/model PRs).
- [ ] **Feature 4.9**: Architecture Decision Records (ADRs) & Diagram-as-Code (`spec/adr/`, `spec/architecture.md`).

### Phase 5: Real-Time LiveKit Voice Agent Core & Medical Persona 🎙️
*Goal: Build the real-time WebRTC audio pipeline tuned for polite Egyptian Arabic, medical safety guardrails, and rapid tool calling.*

- [ ] **Feature 5.1**: Egyptian Clinic Assistant Persona, System Prompts & Medical Guardrails (`src/agent/prompts.py`).
- [ ] **Feature 5.2**: Medical Call Session State & Metric Tracking (`src/agent/session_manager.py`).
- [ ] **Feature 5.3**: LiveKit Voice Pipeline Worker registering all clinic tools (`src/agent/voice_agent.py`).
- [ ] **Feature 5.4**: CLI Simulated Call Runner for clinic booking scenarios (`scripts/test_call.py`).
- [ ] **Feature 5.5**: Automated Voice Orchestration & Guardrail Test Suite (`tests/test_agent.py`).

### Phase 6: LLMOps Production Operations, Identity & Reliability 📈
*Goal: Keep the live system observable, continuously evaluated, access-controlled, and within SLA once real patients depend on it — Prometheus/Grafana telemetry, online sampled evaluation, SSO/RBAC with multi-branch isolation, load testing, and a formal SLI/SLO/SLA contract.*

- [ ] **Feature 6.1**: Prometheus Metrics Exporter (`src/ops/metrics.py` — Counters for calls/tokens/cost/errors, Gauge for active calls, Histograms for per-turn latency; bounded labels only, never `phone`/`call_id`).
- [ ] **Feature 6.2**: Grafana Dashboards & Alertmanager Rules (`infra/observability/` — calls/min, P95 per turn, infra vs semantic error rate, daily token cost, cache hit ratio, alerts on SLO and 80% budget).
- [ ] **Feature 6.3**: Online Sampled Evaluation (`src/ops/online_eval.py` — async RAGAS on 10% of production traces + sampled Llama Guard, results pushed back to Langfuse).
- [ ] **Feature 6.4**: SSO (OAuth2/OIDC JWT) & RBAC (`src/auth/` — pluggable IdP: Keycloak local / Microsoft Entra ID prod; roles `admin`, `receptionist`, `doctor`, `viewer`).
- [ ] **Feature 6.5**: Multi-Branch Tenant Isolation & Role-Scoped Tools (`tenant_id`/`branch_id` in Qdrant payloads and DB tables via migration, pre-retrieval filtering from verified token, fixed `caller` role with tool allowlist).
- [ ] **Feature 6.6**: Load & Stress Testing (`tests/load/` — Locust for API/text path + LiveKit `lk load-test` for voice path at 50 concurrent calls).
- [ ] **Feature 6.7**: SLI/SLO/SLA Contract & Autoscaling Policy (`spec/sla.md` — SLO P95 <= 800ms/turn & 99.9% uptime; SLA P95 <= 1.2s & 99.5% monthly up to 50 concurrent calls; scale on active calls per task, not CPU).

### Phase 7: Clinic Admin & Analytics Dashboard 📊
*Goal: Adapt Streamlit dashboard for clinic operations: live calls, patient bookings table, queue monitoring, and receptionist handoffs.*

> Note: Existing spec folders `spec/features/feature-501..503-*` belong to this phase and keep their original names.

- [ ] **Feature 7.1**: Main Clinic Portal, Arabic RTL Theme & Health Monitor (`src/dashboard/app.py`).
- [ ] **Feature 7.2**: Patient Call Logs, Audio Playback & Transcript Viewer (`src/dashboard/pages/01_calls.py`).
- [ ] **Feature 7.3**: Appointments & Queue Management Page (`src/dashboard/pages/02_appointments.py`).
- [ ] **Feature 7.4**: Latency Breakdown & Call Volume Analytics (`src/dashboard/pages/03_analytics.py`).
- [ ] **Feature 7.5**: Receptionist Escalations & Live Alerts Drawer (`src/dashboard/pages/04_escalations.py`).

### Phase 8: Production Containerization & Cloud Deployment 📦
*Goal: Package the polyclinic voice agent, database, and LLMOps stack for scalable cloud deployment.*

- [ ] **Feature 8.1**: Multi-stage production `Dockerfile` & `docker-compose.yml` (App + PostgreSQL + Qdrant + Redis + Langfuse + Prometheus + Grafana).
- [ ] **Feature 8.2**: AWS ECS Fargate task definition, autoscaling on active-calls custom metric & deployment automation scripts (`infra/`).
- [ ] **Feature 8.3**: End-to-end simulated clinic call flow verification (`tests/test_e2e.py`).
