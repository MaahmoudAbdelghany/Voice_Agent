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

- [ ] **Feature 3.1**: Pydantic schemas for medical tool inputs and outputs (`src/tools/schemas.py`).
- [ ] **Feature 3.2**: Doctor Availability & Shift Lookup Tool (`src/tools/doctor_availability.py`).
- [ ] **Feature 3.3**: Appointment Booking Tool with atomic queue number assignment (`src/tools/appointment_booking.py`).
- [ ] **Feature 3.4**: Appointment Query, Cancellation & Rescheduling Tool (`src/tools/manage_appointment.py`).
- [ ] **Feature 3.5**: Clinic Knowledge Search Tool (`src/tools/knowledge_search.py`).
- [ ] **Feature 3.6**: Human Receptionist Escalation Tool with Dashboard Alert (`src/tools/human_handoff.py`).
- [ ] **Feature 3.7**: Automated Unit & Integration Tests for Medical Tools (`tests/test_clinic_tools.py`).

### Phase 4: Real-Time LiveKit Voice Agent Core & Medical Persona 🎙️
*Goal: Build the real-time WebRTC audio pipeline tuned for polite Egyptian Arabic, medical safety guardrails, and rapid tool calling.*

- [ ] **Feature 4.1**: Egyptian Clinic Assistant Persona, System Prompts & Medical Guardrails (`src/agent/prompts.py`).
- [ ] **Feature 4.2**: Medical Call Session State & Metric Tracking (`src/agent/session_manager.py`).
- [ ] **Feature 4.3**: LiveKit Voice Pipeline Worker registering all clinic tools (`src/agent/voice_agent.py`).
- [ ] **Feature 4.4**: CLI Simulated Call Runner for clinic booking scenarios (`scripts/test_call.py`).
- [ ] **Feature 4.5**: Automated Voice Orchestration & Guardrail Test Suite (`tests/test_agent.py`).

### Phase 5: Clinic Admin & Analytics Dashboard 📊
*Goal: Adapt Streamlit dashboard for clinic operations: live calls, patient bookings table, queue monitoring, and receptionist handoffs.*

- [ ] **Feature 5.1**: Main Clinic Portal, Arabic RTL Theme & Health Monitor (`src/dashboard/app.py`).
- [ ] **Feature 5.2**: Patient Call Logs, Audio Playback & Transcript Viewer (`src/dashboard/pages/01_calls.py`).
- [ ] **Feature 5.3**: Appointments & Queue Management Page (`src/dashboard/pages/02_appointments.py`).
- [ ] **Feature 5.4**: Latency Breakdown & Call Volume Analytics (`src/dashboard/pages/03_analytics.py`).
- [ ] **Feature 5.5**: Receptionist Escalations & Live Alerts Drawer (`src/dashboard/pages/04_escalations.py`).

### Phase 6: Production Containerization & Cloud Deployment 📦
*Goal: Package the polyclinic voice agent and database for scalable cloud deployment.*

- [ ] **Feature 6.1**: Multi-stage production `Dockerfile` & `docker-compose.yml` (App + PostgreSQL + Qdrant).
- [ ] **Feature 6.2**: AWS ECS Fargate task definition & deployment automation scripts (`infra/`).
- [ ] **Feature 6.3**: End-to-end simulated clinic call flow verification (`tests/test_e2e.py`).
