# Technical Constitution & Architectural Invariants — Voice AI Agent

## 1. Technology Stack

| Layer | Technology | Version / Model | Justification / Role |
|:---|:---|:---|:---|
| **Voice Transport** | LiveKit Cloud / LiveKit Agents | SDK >= 0.8.0 | WebRTC low-latency streaming audio, room session orchestration |
| **Speech-to-Text (STT)** | Deepgram | `nova-3` | Streaming transcription, punctuation, multilingual (Arabic & English) |
| **LLM Reasoning** | Groq Cloud | `llama-3.3-70b-versatile` | High-throughput token generation (>300 t/s) for voice latency SLA |
| **Text-to-Speech (TTS)** | ElevenLabs | `eleven_turbo_v2_5` | Streaming natural vocal synthesis with sub-250ms first-chunk playback |
| **VAD / Barge-In** | Silero VAD | v4 | Client/Server-side instant speech cutoff when user interrupts |
| **Vector DB (RAG)** | Qdrant | Cloud / In-Memory (>=1.9) | Low-latency vector search for menu, allergens, and policies |
| **Embeddings** | FastEmbed | `paraphrase-multilingual-MiniLM-L12-v2` | Lightweight multilingual onnx embeddings without PyTorch dependency |
| **Configuration** | Pydantic Settings | >= 2.2.0 | Centralized typed configuration loaded from `.env` |
| **Admin UI** | Streamlit + Plotly | >= 1.35.0 | Operational dashboard for call logs, audio playback, metrics |
| **Testing** | Pytest + Pytest-AsyncIO | >= 8.0.0 | Unit, integration, and voice pipeline simulation testing |
| **DevOps** | Docker + Docker Compose + AWS ECS | Multi-stage | Containerization and scalable cloud worker deployment |

## 2. Architectural Invariants & Rules

1. **Voice Latency Budget**:
   - Total voice turnaround (Caller stops speaking -> Agent first audio frame): **< 800ms target**.
   - STT Interim & Final transcription: **< 200ms**.
   - LLM Time-to-First-Token (TTFT): **< 300ms** via Groq.
   - TTS Streaming synthesis first-chunk: **< 250ms**.

2. **Barge-In (Interruption Handling)**:
   - When caller voice activity is detected by Silero VAD while TTS is playing, speech playback must immediately cancel and LLM generation must abort.

3. **Tool Execution Integrity**:
   - All tools must use strict Pydantic schemas for input validation.
   - Tools must fail gracefully (never crash the audio pipeline or disconnect the WebRTC room).
   - Tool outputs must provide human-sounding, concise strings suitable for speech synthesis.

4. **Session State & Memory Separation**:
   - Session manager must track call metadata, latency breakdown (STT, LLM, TTS), token counts, and tool invocations.
   - Sliding memory window prevents context overflow during extended calls.

5. **Security & Secrets**:
   - Zero hardcoded credentials. All API keys loaded via `src/config.py` from `.env`.
   - Automatic clock skew compensation applied for LiveKit JWT token generation.
