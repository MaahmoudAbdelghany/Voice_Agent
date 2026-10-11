# Technical Constitution & Architectural Invariants — Voice AI Agent (Egyptian Clinics)

## 1. Technology Stack

| Layer | Technology | Version / Model | Justification / Role |
|:---|:---|:---|:---|
| **Voice Transport** | LiveKit Cloud / LiveKit Agents | SDK >= 0.8.0 | WebRTC low-latency streaming audio, room session orchestration |
| **Speech-to-Text (STT)** | Deepgram | `nova-3` | Streaming transcription, punctuation, Egyptian Arabic (`ar`) & English |
| **LLM Reasoning** | Groq Cloud | `llama-3.3-70b-versatile` | High-throughput token generation (>300 t/s) for sub-second voice SLA |
| **Text-to-Speech (TTS)** | ElevenLabs | `eleven_turbo_v2_5` | Streaming natural vocal synthesis with sub-250ms first-chunk playback |
| **VAD / Barge-In** | Silero VAD | v4 | Client/Server-side instant speech cutoff when caller interrupts |
| **Relational Database** | Async SQLAlchemy + SQLite / PostgreSQL | >= 2.0.0 | ACID booking transactions, shift capacity, doctors & appointment state |
| **Vector DB (RAG)** | Qdrant | In-Memory / Cloud (>=1.9) | Low-latency vector search for specialties, clinic policies, fees, tests |
| **Embeddings** | FastEmbed | `paraphrase-multilingual-MiniLM-L12-v2` | Lightweight multilingual ONNX embeddings without PyTorch dependency |
| **Configuration** | Pydantic Settings | >= 2.2.0 | Centralized typed configuration loaded from `.env` |
| **Admin UI** | Streamlit + Plotly | >= 1.35.0 | Operational dashboard for call logs, appointments, audio playback, metrics |
| **Testing** | Pytest + Pytest-AsyncIO | >= 8.0.0 | Unit, database integration, and voice pipeline simulation testing |
| **DevOps** | Docker + Docker Compose + AWS ECS | Multi-stage | Containerization and scalable cloud worker deployment |

---

## 2. Architectural Invariants & Rules

### 1. Voice Latency Budget (< 800ms Target)
- Total voice turnaround (Caller stops speaking -> Agent first audio frame): **< 800ms**.
- STT Interim & Final transcription: **< 200ms**.
- LLM Time-to-First-Token (TTFT): **< 300ms** via Groq.
- TTS Streaming synthesis first chunk: **< 250ms**.
- Tool execution timeout: **< 400ms**. Any database or RAG tool taking longer must abort and yield a friendly conversational filler.

### 2. Clinic Shift Window & Capacity Invariant (Atomic Booking)
- Appointments are booked within defined doctor shift windows (e.g. 18:00–21:00).
- Bookings must execute inside an **atomic database transaction**:
  1. Verify active shift existence and check that `current_bookings_count < max_capacity`.
  2. Increment queue number and persist the `Appointment` record.
  3. Prevent double-booking / race conditions when concurrent calls occur.
- Visit types must explicitly differentiate between:
  - `examination` (كشف جديد - full fee & slot count)
  - `consultation` (استشارة / إعادة - discounted/free follow-up within eligibility window).

### 3. Medical Safety & Liability Guardrails (Zero Medical Hallucination)
- **Strict Prohibition**: The Voice Agent must NEVER provide medical diagnoses, suggest specific drug dosages, or offer medical treatment prescriptions.
- When a caller reports urgent or life-threatening symptoms (e.g. chest pain, severe bleeding, difficulty breathing), the agent must immediately instruct the caller to seek emergency care and trigger the `transfer_to_receptionist` tool.
- All pricing, preparation rules (e.g. fasting before blood tests), and doctor credentials must strictly originate from verified database or RAG sources.

### 4. Barge-In (Interruption Handling)
- When caller voice activity is detected by Silero VAD while TTS is playing, speech playback must immediately cancel and LLM generation must abort.

### 5. Tool Execution & Error Resilience
- All tools must use strict Pydantic schemas for input validation.
- Tools must fail gracefully (never crash the audio pipeline or disconnect the WebRTC room).
- Tool outputs must provide human-sounding, concise strings in Egyptian Arabic suitable for speech synthesis.

### 6. Session State & Privacy Separation
- Session manager tracks call metadata, latency breakdown (STT, LLM, TTS), token counts, and tool invocations.
- Patient health records and sensitive contact details must be handled securely with zero credentials hardcoded.
- LiveKit JWT clock skew compensation remains active to prevent token expiry.
