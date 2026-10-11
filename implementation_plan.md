# Production Voice Agent (Egyptian Polyclinics & Medical Centers) — Implementation Plan

## 1. Overview & Business Goal
Build a scalable, real-time, production-grade **Voice AI Agent** serving **Egyptian Polyclinics & Medical Centers**.
The agent can:
- Listen to callers in real-time, transcribing spoken Egyptian Arabic and English with **Deepgram STT** (`nova-3`, sub-200ms latency).
- Understand patient intent, retrieve medical center guidelines using **RAG (Qdrant Vector DB)**, and reason via **Groq Cloud (Llama 3.3 70B)**.
- Query real-time doctor availability and weekly shift windows via an **Async Relational Database** (SQLite locally / PostgreSQL in production).
- Execute transactional tool calls:
  - Check Doctor Availability & Shift Hours (`check_doctor_availability`).
  - Book Patient Appointments with automated queue numbers (`book_appointment`).
  - Look up, reschedule, or cancel existing appointments (`manage_appointment`).
  - Clinic Information & Policy Search (`search_clinic_knowledge`).
  - Escalate urgent/complex calls to the human front-desk receptionist (`transfer_to_receptionist`).
- Synthesize natural Egyptian spoken responses with **ElevenLabs TTS** (`eleven_turbo_v2_5`).
- Support seamless caller interruptions using **Silero VAD** via **LiveKit Agents**.
- Provide a full **Streamlit Clinical Admin & Analytics Dashboard** for live call logs, audio playback, appointments management, and latency observability.
- Containerized and scalable for production deployment on **AWS ECS Fargate**.

---

## 2. Tech Stack & Architecture

| Component | Technology | Role |
|:---|:---|:---|
| **Voice Infrastructure** | LiveKit Cloud / LiveKit Agents SDK | WebRTC media routing, session orchestration, barge-in |
| **Speech-to-Text (STT)** | Deepgram (`nova-3`, `ar`) | Real-time streaming transcription tuned for Egyptian dialect |
| **LLM Reasoning** | Groq Cloud (`llama-3.3-70b-versatile`) | Ultra-fast token generation & tool calling (<300ms TTFT) |
| **Text-to-Speech (TTS)** | ElevenLabs (`eleven_turbo_v2_5`) | Low-latency, natural vocal synthesis |
| **VAD / Interruption** | Silero VAD | Real-time voice activity detection for instant cut-off |
| **Relational Database** | Async SQLAlchemy + SQLite / PostgreSQL | ACID bookings, doctors, specialties, shift capacities |
| **Vector DB (RAG)** | Qdrant Cloud / In-Memory (`FastEmbed`) | Specialties, fees, insurances, prep instructions |
| **Agent Orchestration** | LiveKit Agents Python SDK | Multi-tool routing, memory, state management |
| **Admin Dashboard** | Streamlit + Plotly | Call logs, appointment queue, live analytics, prompt config |
| **DevOps / Cloud** | Docker, Docker Compose, AWS ECS | Multi-stage containerization, CI/CD, cloud deployment |

---

## 3. Spec-Driven Development (SDD) & Phased Roadmap

### **Spec-Driven Governance (spec/)**
- [x] `spec/mission.md`: Egyptian polyclinic mission, target users, scope, and boundaries.
- [x] `spec/tech.md`: Tech stack, architectural invariants, database layer, medical guardrails.
- [x] `spec/roadmap.md`: Living product roadmap & feature specifications.

### **Phase 1: Project Foundation & Async Database Layer**
- [x] Step 1.1: Pivot project specifications to Egyptian Polyclinics.
- [x] Step 1.2: Align `implementation_plan.md` and `TASK_PLAN.md`.
- [x] Step 1.3: Update `src/config.py` with clinic parameters and database URL settings.
- [x] Step 1.4: Implement Async SQLAlchemy session manager (`src/db/session.py`).
- [ ] Step 1.5: Define relational models (`Specialty`, `Doctor`, `DoctorSchedule`, `Patient`, `Appointment`).
- [ ] Step 1.6: Build database repository & seed script with realistic Egyptian clinic data.
- [ ] Step 1.7: Write and run automated unit tests for database transactions.

### **Phase 2: Egyptian Clinic Knowledge Base Engine (Qdrant RAG)**
- [ ] Step 2.1: Author rich Egyptian clinic knowledge base (`knowledge_base/clinic_kb.md`).
- [ ] Step 2.2: Build CLI ingestion pipeline for `clinic_kb` collection.
- [ ] Step 2.3: Verify vector embeddings and search with unit tests.

### **Phase 3: Clinic Domain Execution Tools**
- [ ] Step 3.1: Define strongly-typed Pydantic schemas in `src/tools/schemas.py`.
- [ ] Step 3.2: Implement doctor availability tool (`src/tools/doctor_availability.py`).
- [ ] Step 3.3: Implement appointment booking tool (`src/tools/appointment_booking.py`).
- [ ] Step 3.4: Implement appointment query, reschedule & cancellation tool (`src/tools/manage_appointment.py`).
- [ ] Step 3.5: Adapt clinic knowledge search tool (`src/tools/knowledge_search.py`).
- [ ] Step 3.6: Adapt receptionist escalation tool (`src/tools/human_handoff.py`).
- [ ] Step 3.7: Write and run unit tests for all medical tools.

### **Phase 4: Real-Time LiveKit Voice Agent Core & Medical Persona**
- [ ] Step 4.1: Author Egyptian medical receptionist persona & system prompts with guardrails.
- [ ] Step 4.2: Update call session manager & metrics tracking.
- [ ] Step 4.3: Wire LiveKit voice worker with registered clinic tools.
- [ ] Step 4.4: Update CLI call simulation runner for clinic scenarios.
- [ ] Step 4.5: Write and run agent pipeline and guardrail tests.

### **Phase 5: Clinic Admin & Analytics Dashboard**
- [ ] Step 5.1: Update main dashboard portal, RTL theme & clinic branding.
- [ ] Step 5.2: Update call logs, audio playback & transcript viewer.
- [ ] Step 5.3: Build appointments & queue management view.
- [ ] Step 5.4: Adapt latency & call analytics.
- [ ] Step 5.5: Build receptionist escalations alert drawer.

### **Phase 6: Production Containerization & Cloud Deployment**
- [ ] Step 6.1: Multi-stage Dockerfile and docker-compose.yml.
- [ ] Step 6.2: AWS ECS Fargate task definition & deployment automation scripts.
- [ ] Step 6.3: End-to-end simulated call verification.

---

## 4. Verification & Testing Strategy
- Unit tests for database models, CRUD operations, and concurrent capacity limits.
- Integration tests for medical tool invocation (availability checks, bookings, cancellations).
- Local voice loop simulation using LiveKit Agent CLI console & WebRTC playground.
- Streamlit dashboard verification for live appointment queues and latency breakdowns.
