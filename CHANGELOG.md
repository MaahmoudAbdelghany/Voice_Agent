# Changelog

All notable changes to the Voice AI Agent for Egyptian Polyclinics & Medical Centers.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Features reference [`spec/roadmap.md`](spec/roadmap.md).

## [Unreleased]

### Phase 5 — Real-Time LiveKit Voice Agent Core & Medical Persona

Egyptian polyclinics now have a complete real-time voice receptionist capable of answering patient calls in polite Egyptian Arabic or English, checking doctor shift availability, booking/cancelling/rescheduling queue-numbered appointments, answering grounded clinic and lab preparation questions, and escalating medical emergencies immediately to human receptionists. Every live call traverses strict safety guardrails, verified caller identity checks, FinOps cost caps, and PII-redacted session logging. Known limitations: each call uses a single configured language (`ar` default or `en` via token/SIP metadata; automatic mid-call language switching is tracked in the research backlog), and production multi-branch SSO/RBAC and 50-call load testing are scheduled next in Phase 6.

#### Added
- **Feature 5.1 — Egyptian Clinic Persona, System Prompts & Medical Guardrails**: Patients are greeted in warm, natural Egyptian Arabic by a clinic receptionist persona that answers clearly in 1–2 spoken sentences, refuses any medical diagnosis or drug prescription requests, and directs emergencies to `123` and front-desk staff ([spec](spec/features/feature-511-clinic-persona-system-prompts/plan.md)).
- **Feature 5.2 — Medical Call Session State & Metric Tracking**: Clinic administrators gain per-call tracking of appointment bookings, queue numbers, interruptions (barge-in), turn-by-turn latencies, and FinOps token usage, saved to disk with Egyptian phone numbers and national IDs automatically masked ([spec](spec/features/feature-512-medical-call-session-state-metrics/plan.md)).
- **Feature 5.4 — LiveKit Voice Pipeline Worker & Clinic Turn Engine**: Callers can speak with the clinic assistant in real time over LiveKit WebRTC/SIP audio (Deepgram STT, ElevenLabs TTS, Silero VAD instant barge-in). Read inquiries respond within a `400ms` tool budget, while appointment bookings emit a polite spoken hold phrase at `400ms` and complete safely in the background up to `3s` so patients are never told a committed booking failed ([spec](spec/features/feature-514-livekit-voice-worker/plan.md)).
- **Feature 5.5 — CLI Simulated Call Runner & Clinic Scenarios**: Developers and clinic QA teams can run 6 end-to-end call scenarios (`booking`, `manage`, `knowledge`, `emergency`, `guardrail`, `unverified-booking`) offline in seconds or test live LLM conversations and interactive terminal calls from a single CLI command ([spec](spec/features/feature-515-cli-simulated-call-runner/plan.md)).
- **Feature 5.6 — Automated Voice Orchestration & Guardrail Test Suite**: Added a fast (`<15s`), deterministic 19-test voice orchestration suite verifying live call routing, barge-in safety, tool timeouts, cache isolation, budget degradation, and medical safety guardrails ([spec](spec/features/feature-516-voice-orchestration-test-suite/plan.md)).

#### Removed
- **Feature 5.3 — Legacy Restaurant Purge & Codebase Sanitization**: Removed all legacy restaurant tools, schemas, configuration aliases, synthetic dashboard demo calls, and restaurant terminology so the assistant, admin dashboard, and tool registry operate exclusively as a medical polyclinic platform with a clean empty state ([spec](spec/features/feature-513-legacy-restaurant-purge/plan.md)).

#### Security
- **Verified Caller Identity & Unverified Write Protection**: Caller phone numbers are trusted only from telephony SIP headers or signed LiveKit tokens (`scripts/generate_token.py --phone`), never from spoken audio; unverified callers can ask about doctors and clinic services, while booking/cancellation requests are handed off to a human receptionist before touching the database ([review](spec/phases/phase-5-livekit-voice-core/phase-review.md)).
- **Deep-Review Hardening**: Added HTML escaping on call transcripts in the admin dashboard, production LiveKit secret enforcement, Arabic-Indic (`٠-٩`) and grouped phone/National ID redaction across logs, traces, and caches, and tenant/branch cache isolation ([review](spec/phases/phase-5-livekit-voice-core/phase-review.md)).
