# Project Mission — Voice AI Agent for Egyptian Polyclinics & Medical Centers

## 1. Product (WHAT)
**Voice AI Medical Receptionist (مساعد العيادة الصوتي الذكي)** is an enterprise-grade, ultra-low-latency conversational voice assistant designed specifically for Egyptian polyclinics, medical centers, and specialized healthcare practices. Operating over real-time WebRTC audio streams, the agent communicates fluently in professional, polite Egyptian Arabic (العامية المصرية المهذبة والمرحبة) alongside Modern Standard Arabic and English, managing incoming patient phone calls with human-like responsiveness, contextual memory, and database execution.

## 2. Problem Statement (WHY)
Egyptian clinics and healthcare centers face severe communication bottlenecks during peak operating hours:
- High telephone call drop rates resulting in missed patient bookings and lost clinic revenue.
- Front-desk receptionist overload handling repetitive questions about doctor schedules, specialty availability, fees, and preparation guidelines.
- Disorganized patient queues and booking disputes due to manual, paper-based, or fragmented scheduling.
- Patient frustration with long hold times or rigid legacy IVR phone trees.

## 3. Target Users (WHO)
- **Patients & Callers (المرضى والمراجعون)**: Individuals seeking rapid inquiry about doctor availability, booking examination appointments, checking queue/shift hours, managing existing appointments, or requesting directions and clinic fees.
- **Clinic Administrators & Receptionists (إدارة العيادة وموظفو الاستقبال)**: Healthcare staff benefiting from automated triage, instant handoff for urgent cases, a unified booking database, and real-time call analytics.
- **Doctors & Medical Specialists (الأطباء والاستشاريون)**: Physicians with predictable patient queues, controlled shift capacities, and zero manual scheduling distractions.

## 4. Core Value Proposition & Goals
- **Sub-Second Voice Latency (<800ms)**: Streaming STT, high-speed LLM reasoning, and streaming TTS deliver seamless, natural conversational turns without awkward pauses.
- **Egyptian Clinic Shift Scheduling**: Native support for clinic shift windows (e.g. 6:00 PM – 9:00 PM) with first-come first-served queue numbers (نمرة الحجز) and shift capacity caps.
- **Relational Booking Integrity**: Direct connection to an ACID-compliant database to prevent double bookings, track patient visits (new examination vs consultation/follow-up), and record cancellations.
- **Grounded Medical Knowledge & Strict Guardrails**: Accurate answers regarding specialties, doctor credentials, examination fees, accepted health insurance, and pre-visit instructions (e.g. fasting), paired with a **strict ban on medical diagnosis or drug prescriptions**.
- **Human Receptionist Escalation**: Immediate transfer and alert mechanism to front-desk staff whenever a patient requests human assistance or presents emergency/complex symptoms.

## 5. Scope & Boundaries
### In Scope (MVP & Production):
- Real-time WebRTC streaming voice pipeline (LiveKit, Deepgram STT, Groq Llama 3.3, ElevenLabs TTS, Silero VAD).
- Async Relational Database (SQLite for local dev / PostgreSQL for production) with tables for `Specialties`, `Doctors`, `DoctorSchedules`, `Appointments`, and `Patients`.
- Specialized Clinic Tools:
  - `check_doctor_availability`: Query upcoming shift dates, hours, and remaining capacity by doctor or specialty.
  - `book_appointment`: Reserve a confirmed queue slot for a patient (new examination or follow-up).
  - `manage_appointment`: Query, reschedule, or cancel existing bookings by caller phone number.
  - `search_clinic_knowledge`: RAG retrieval for clinic policies, fees, tests, insurances, and address.
  - `transfer_to_receptionist`: Escalate to front-desk staff with summary and live dashboard notification.
- Streamlit Clinical Dashboard for live call monitoring, audio playback, appointment logs, and latency KPIs.
- Containerization and production AWS deployment specs.

### Out of Scope:
- Direct over-the-phone medical diagnosis, triage of life-threatening emergencies (routed immediately to emergency hotlines/reception), or prescription advice.
- Direct credit card processing over audio (deferred to clinic arrival or external SMS payment links).
- Direct bi-directional integration with complex proprietary hospital EHR/EMR systems (e.g. Epic/Cerner) during the MVP phase.
