# Project Mission — Voice AI Agent & WhatsApp Operations Platform for Polyclinics (Egypt, KSA & UAE)

## 1. Product (WHAT)
**Voice AI Medical Receptionist & Clinic Operations Platform (مساعد العيادة الصوتي الذكي ومنظومة إشعارات الواتساب)** is a lean, high-performance, cost-optimized conversational voice assistant and automated patient communication system built for polyclinics, medical centers, and specialized healthcare practices across **Egypt (default launch profile), Saudi Arabia (KSA), and the United Arab Emirates (UAE)**.

Guided by a **Forward Deployed AI Engineering (FDE) MVP philosophy** — solving real clinic bottlenecks at the lowest operational cost, highest responsiveness, and clean modular maintainability — the platform delivers value across three pillars:
1. **AI Product**: Real-time WebRTC voice receptionist speaking natural Egyptian Arabic (default), Gulf-ready Arabic, and English with `<800ms` turnaround.
2. **Internal Clinic Process Optimization**: 1-click receptionist operations (`FastAPI` + `Streamlit`) for live shift queues and instant doctor absence/apology handling without manual phone marathons.
3. **Patient Customer Experience**: Confirmed WhatsApp contact numbers during booking, instant WhatsApp booking receipts, automated pre-appointment WhatsApp reminders, and proactive WhatsApp apology + next-available-slot notifications when a doctor cancels a shift.

## 2. Problem Statement (WHY)
Polyclinics and medical centers across Egypt and the GCC face severe operational and patient-service bottlenecks:
- High telephone call drop rates during peak hours resulting in missed bookings and lost clinic revenue.
- Front-desk receptionist overload answering repetitive inquiries about doctor shift schedules, remaining capacity, and fees.
- High patient no-show rates and confusion over queue numbers or shift times due to lack of automated WhatsApp confirmations and pre-visit reminders.
- Operational chaos when a physician apologizes for an emergency absence: receptionists must manually call 15–30 booked patients one by one to apologize and explain the next available shift.

## 3. Target Users (WHO)
- **Patients & Callers (المرضى والمراجعون — مصر، السعودية، الإمارات)**: Individuals calling to ask about doctor schedules, book appointments with their name and confirmed WhatsApp contact number, receive automated WhatsApp reminders, or get notified immediately with the next available shift if their doctor apologizes.
- **Clinic Administrators & Receptionists (إدارة العيادة وموظفو الاستقبال)**: Front-desk staff managing daily shift queues, handling escalated urgent calls, and triggering 1-click doctor shift apologies that automatically close the shift and notify affected patients via WhatsApp.
- **Doctors & Medical Specialists (الأطباء والاستشاريون)**: Physicians with predictable shift queues, enforced shift capacities, and zero manual rescheduling friction when unexpected schedule changes occur.

## 4. Core Value Proposition & Goals
- **Sub-Second Voice Latency (`<800ms`) & Cost-Efficient Routing**: Streaming STT, stage-routed Groq LLMs (`8B` for classification/extraction, `70B` for dialogue), 3-tier caching, and streaming TTS.
- **Multi-Country Regional Readiness (`EG` / `SA` / `AE`)**: Standardized `E.164` phone handling (`+20`, `+966`, `+971`), configurable currency (`EGP`, `SAR`, `AED`), timezone, and dialect profile — pre-configured for Egypt out of the box and switchable via configuration without code rewrites.
- **Confirmed WhatsApp Contact & Zero-Infrastructure Outbox**: Separation of session caller identity from the patient's confirmed WhatsApp contact number, backed by a database `Transactional Outbox` and direct `Meta WhatsApp Cloud API` integration (zero middleman markup, zero `Redis`/`Celery` server overhead in MVP).
- **Automated Doctor Apology & Capacity-Safe Next-Slot Guidance**: Instant `DoctorScheduleException` enforcement that blocks new voice bookings on cancelled shifts, marks affected bookings as `cancelled_by_doctor`, cancels pending reminders, and sends WhatsApp apologies containing the doctor's actual next available shift with open capacity.
- **Grounded Medical Knowledge & Strict Guardrails**: Verified answers for specialties, fees, insurance, and lab preparation, paired with a **strict ban on medical diagnosis or drug prescriptions** and immediate human escalation for emergencies.
- **Lean AWS MVP Deployment (`EC2 -> ECS`)**: Clean `12-Factor` Docker containers running at minimal monthly cost on a single `AWS EC2` host in MVP (`ECR` + `SSM` + `S3` backups), ready to lift-and-shift to `AWS ECS Fargate + RDS` as clinic volume scales.

## 5. Scope & Boundaries
### In Scope (Lean Production MVP):
- Real-time WebRTC streaming voice pipeline (`LiveKit`, `Deepgram STT`, `Groq Llama 3.3/3.1`, `ElevenLabs TTS`, `Silero VAD`).
- Async Relational Database (`SQLite` local / `PostgreSQL` production) covering `Specialties`, `Doctors`, `DoctorSchedules`, `DoctorScheduleExceptions`, `Patients`, `Appointments`, `Escalations`, and `NotificationOutbox`.
- Configurable Regional Profiles (`EG` default, `SA`, `AE`) with `E.164` phone validation and PII redaction.
- Specialized Clinic Voice Tools:
  - `check_doctor_availability`: Query doctor shifts, fees, remaining slots, and active shift exceptions (automatically surfacing the next open shift if today's shift was cancelled).
  - `book_appointment`: Collect patient name + confirm WhatsApp contact number via read-back, assign an atomic queue slot (`نمرة الحجز`), and enqueue WhatsApp confirmation + pre-shift reminder (`24h` / `3h` before shift).
  - `manage_appointment`: Lookup, reschedule, or cancel appointments while keeping pending WhatsApp reminders synchronized.
  - `search_clinic_knowledge`: Hybrid RAG (`Qdrant` + `BM25`) for clinic policies, fees, lab prep, insurance, and directions.
  - `transfer_to_receptionist`: Immediate escalation to front-desk staff with live dashboard alert.
- Modular WhatsApp Notification Layer (`WhatsAppProvider` adapter with official direct `Meta WhatsApp Cloud API` + local `MockOutboxProvider` for dev/UAT).
- Operational `FastAPI` service + RTL `Streamlit` Receptionist Portal with live call logs, appointment queue, WhatsApp outbox status, and 1-click Doctor Shift Apology workflow.
- Multi-stage `12-Factor` Docker Compose stack and cost-optimized `AWS EC2` CI/CD deployment (`ECR`, `SSM`, `S3` backups).

### Deferred to Post-MVP Enterprise Scale (`Phase 9`) & Out of Scope:
- **Post-MVP Enterprise Scale (`Phase 9`)**: Heavy observability/identity infrastructure (`Prometheus + Grafana`, `Keycloak / Entra ID SSO`, `Online Sampled RAGAS`, multi-branch tenant isolation, 50-call load test, and `AWS ECS Fargate + RDS` cluster migration) deferred until multi-clinic expansion.
- **Strictly Out of Scope**:
  - Over-the-phone medical diagnosis, drug prescriptions, or clinical advice.
  - Interactive two-way WhatsApp free-text chatbot conversations in MVP (outbound utility notifications only in MVP; rebooking confirmation happens via quick voice call or reception).
  - Direct credit-card capture over audio or deep legacy hospital HIS/ERP bidirectional sync during MVP.
