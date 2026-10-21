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
- [ ] **Feature 3.3**: Appointment Booking Tool with atomic queue number assignment (`src/tools/appointment_booking.py`).
- [ ] **Feature 3.4**: Appointment Query, Cancellation & Rescheduling Tool (`src/tools/manage_appointment.py`).
- [ ] **Feature 3.5**: Clinic Knowledge Search Tool (`src/tools/knowledge_search.py`).
- [ ] **Feature 3.6**: Human Receptionist Escalation Tool with Dashboard Alert (`src/tools/human_handoff.py`).
- [ ] **Feature 3.7**: Automated Unit & Integration Tests for Medical Tools (`tests/test_clinic_tools.py`).

### Phase 4: Enterprise AI Architecture & Resilience Engine 🛡️
*Goal: Harden the AI system into an enterprise-grade, fault-tolerant platform based on production AI system design principles: Model Routing, 3-Tier Caching, Trust & Guardrail Layer, Deterministic Safety Gates, Circuit Breakers, and Golden Evals.*

- [ ] **Feature 4.1**: Model Gateway, Multi-Tier Routing & Circuit Breaker (`src/ai_core/gateway.py` with Groq primary, OpenAI fallback, 3.5s TTFT timeout).
- [ ] **Feature 4.2**: 3-Tier Caching Ladder (`src/ai_core/cache.py` with Tier 1 Exact Hash, Tier 2 Metadata-Scoped Semantic Cache >= 0.97, Tier 3 Prompt Prefix Caching).
- [ ] **Feature 4.3**: Hybrid RAG Upgrade (`src/rag/hybrid_retriever.py` with Dense Vector Qdrant + BM25 via Reciprocal Rank Fusion & structure-aware chunking).
- [ ] **Feature 4.4**: Trust Layer & Runtime Guardrails (`src/ai_core/guardrails.py` with <20ms CPU injection & medical diagnosis filter, pre-trace PII masking).
- [ ] **Feature 4.5**: Deterministic State Machine, Idempotency Keys & Write Safety Gates (`src/ai_core/workflow.py`, `src/tools/gates.py` for atomic booking and shift caps).
- [ ] **Feature 4.6**: Observability, Distributed Tracing (`trace_id`, latency, token accounting) & CI/CD Golden Evaluation Suite (`src/ai_core/tracing.py`, `tests/evals/`).
- [ ] **Feature 4.7**: Architecture Decision Records (ADRs) & Diagram-as-Code (`spec/adr/`, `spec/architecture.md`).

### Phase 5: Real-Time LiveKit Voice Agent Core & Medical Persona 🎙️
*Goal: Build the real-time WebRTC audio pipeline tuned for polite Egyptian Arabic, medical safety guardrails, and rapid tool calling.*

- [ ] **Feature 5.1**: Egyptian Clinic Assistant Persona, System Prompts & Medical Guardrails (`src/agent/prompts.py`).
- [ ] **Feature 5.2**: Medical Call Session State & Metric Tracking (`src/agent/session_manager.py`).
- [ ] **Feature 5.3**: LiveKit Voice Pipeline Worker registering all clinic tools (`src/agent/voice_agent.py`).
- [ ] **Feature 5.4**: CLI Simulated Call Runner for clinic booking scenarios (`scripts/test_call.py`).
- [ ] **Feature 5.5**: Automated Voice Orchestration & Guardrail Test Suite (`tests/test_agent.py`).

### Phase 6: Clinic Admin & Analytics Dashboard 📊
*Goal: Adapt Streamlit dashboard for clinic operations: live calls, patient bookings table, queue monitoring, and receptionist handoffs.*

- [ ] **Feature 6.1**: Main Clinic Portal, Arabic RTL Theme & Health Monitor (`src/dashboard/app.py`).
- [ ] **Feature 6.2**: Patient Call Logs, Audio Playback & Transcript Viewer (`src/dashboard/pages/01_calls.py`).
- [ ] **Feature 6.3**: Appointments & Queue Management Page (`src/dashboard/pages/02_appointments.py`).
- [ ] **Feature 6.4**: Latency Breakdown & Call Volume Analytics (`src/dashboard/pages/03_analytics.py`).
- [ ] **Feature 6.5**: Receptionist Escalations & Live Alerts Drawer (`src/dashboard/pages/04_escalations.py`).

### Phase 7: Production Containerization & Cloud Deployment 📦
*Goal: Package the polyclinic voice agent and database for scalable cloud deployment.*

- [ ] **Feature 7.1**: Multi-stage production `Dockerfile` & `docker-compose.yml` (App + PostgreSQL + Qdrant + Redis).
- [ ] **Feature 7.2**: AWS ECS Fargate task definition & deployment automation scripts (`infra/`).
- [ ] **Feature 7.3**: End-to-end simulated clinic call flow verification (`tests/test_e2e.py`).
