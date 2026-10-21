# Voice Agent (Egyptian Polyclinics) — Task Plan

## Spec-Driven Development (SDD) Constitution & Governance Pivot
- [x] Step 1.1: Pivot project specifications to Egyptian Polyclinics (`spec/mission.md`, `spec/tech.md`, `spec/roadmap.md`)
- [x] Step 1.2: Align `implementation_plan.md` and `TASK_PLAN.md` in workspace root

## Phase 1: Foundation & Async Relational Database Layer
- [x] Step 1.3: Update `src/config.py` with clinic parameters and database settings
- [x] Step 1.4: Implement Async SQLAlchemy engine & base session in `src/db/session.py`
- [x] Step 1.5: Define relational models in `src/db/models.py` (`Specialty`, `Doctor`, `DoctorSchedule`, `Patient`, `Appointment`)
- [x] Step 1.6: Build database repository & seeding script with realistic Egyptian clinic data in `src/db/repository.py` & `scripts/seed_clinic_db.py`
- [x] Step 1.7: Write and run automated unit tests for database transactions & capacity management in `tests/test_database.py`

## Phase 2: Egyptian Clinic Knowledge Base Engine (Qdrant RAG)
- [x] Step 2.1: Author rich Egyptian clinic knowledge base in `knowledge_base/clinic_kb.md`
- [x] Step 2.2: Build CLI ingestion script for `clinic_kb` collection in `scripts/ingest_clinic_knowledge.py`
- [x] Step 2.3: Verify vector embeddings and search with unit tests in `tests/test_clinic_rag.py`

## Phase 3: Clinic Domain Execution Tools
- [x] Step 3.1: Define strongly-typed Pydantic schemas in `src/tools/schemas.py`
- [x] Step 3.2: Implement doctor availability tool in `src/tools/doctor_availability.py`
- [x] Step 3.3: Implement appointment booking tool with atomic queue assignment in `src/tools/appointment_booking.py`
- [ ] Step 3.4: Implement appointment query, reschedule & cancellation tool in `src/tools/manage_appointment.py`
- [ ] Step 3.5: Adapt clinic knowledge search tool in `src/tools/knowledge_search.py`
- [ ] Step 3.6: Adapt receptionist escalation tool with dashboard notification in `src/tools/human_handoff.py`
- [ ] Step 3.7: Write and run unit tests for all medical tools in `tests/test_clinic_tools.py`

## Phase 4: Real-Time LiveKit Voice Agent Core & Medical Persona
- [ ] Step 4.1: Author Egyptian medical receptionist persona & system prompts with strict guardrails in `src/agent/prompts.py`
- [ ] Step 4.2: Update call session manager & metrics tracking in `src/agent/session_manager.py`
- [ ] Step 4.3: Wire LiveKit voice pipeline worker with registered clinic tools in `src/agent/voice_agent.py`
- [ ] Step 4.4: Update CLI call simulation runner for clinic scenarios in `scripts/test_call.py`
- [ ] Step 4.5: Write and run agent pipeline and guardrail tests in `tests/test_agent.py`

## Phase 5: Clinic Admin & Analytics Dashboard
- [ ] Step 5.1: Update main dashboard portal, RTL theme & clinic branding in `src/dashboard/app.py`
- [ ] Step 5.2: Update call logs, audio playback & transcript viewer in `src/dashboard/pages/01_calls.py`
- [ ] Step 5.3: Build appointments & queue management view in `src/dashboard/pages/02_appointments.py`
- [ ] Step 5.4: Adapt latency & call analytics in `src/dashboard/pages/03_analytics.py`
- [ ] Step 5.5: Build receptionist escalations alert drawer in `src/dashboard/pages/04_escalations.py`

## Phase 6: Production Containerization & Cloud Deployment
- [ ] Step 6.1: Multi-stage Dockerfile and docker-compose.yml with PostgreSQL and Qdrant
- [ ] Step 6.2: AWS ECS Fargate task definition & deployment automation scripts
- [ ] Step 6.3: End-to-end simulated call verification in `tests/test_e2e.py`