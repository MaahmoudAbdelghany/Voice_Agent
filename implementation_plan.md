# Production Voice Agent (Restaurant & Food Delivery) — Implementation Plan

## 1. Overview & Business Goal
Build a scalable, real-time, production-grade **Voice AI Agent** for **Restaurant & Food Delivery Customer Service**.
The agent can:
- Listen to callers in real-time, transcribing speech with **Deepgram STT** (sub-200ms latency).
- Understand customer intent, retrieve knowledge using **RAG (Qdrant Vector DB)**, and reason via **Groq Cloud (Llama 3.3 70B)**.
- Execute tool calls: Menu Inquiries, Real-time Order Tracking & Status, Table Reservations, and Human Handoff.
- Respond back with natural speech synthesis using **ElevenLabs TTS**.
- Handle voice barge-in/interruptions seamlessly using **Silero VAD** via **LiveKit Agents**.
- Provide a full **Streamlit Admin & Analytics Dashboard** for live call logs, audio playback, metrics, and prompt management.
- Containerized and scalable for production deployment on **AWS**.

---

## 2. Tech Stack & Architecture

| Component | Technology | Role |
|:---|:---|:---|
| **Voice Infrastructure** | LiveKit Cloud / LiveKit Agents SDK | WebRTC media routing, session orchestration, barge-in |
| **Speech-to-Text (STT)** | Deepgram (`nova-3`) | Real-time streaming transcription |
| **LLM Reasoning** | Groq Cloud (`llama-3.3-70b-versatile`) | Ultra-fast token generation & tool calling |
| **Text-to-Speech (TTS)** | ElevenLabs (`eleven_turbo_v2_5`) | Low-latency, natural vocal synthesis |
| **VAD / Interruption** | Silero VAD | Real-time voice activity detection for instant cut-off |
| **Vector DB (RAG)** | Qdrant Cloud (`FastEmbed` / `bge-small-en-v1.5`) | Menu items, dietary info, branch policies, FAQs |
| **Agent Orchestration** | LangChain / Python AsyncIO | Multi-tool routing, memory, state management |
| **Admin Dashboard** | Streamlit | Call logs, metrics, live analytics, prompt configuration |
| **DevOps / Cloud** | Docker, Docker Compose, AWS ECS Fargate | Containerization, CI/CD, scalable worker nodes |

---

## 3. Phased Implementation Roadmap

### **Phase 1: Project Foundation & Core Environment Setup**
- [ ] Initialize Python environment (`pyproject.toml`, `.gitignore`, `.env.example`).
- [ ] Configure centralized settings via `Pydantic BaseSettings` in `src/config.py`.
- [ ] Verify environment variables and credentials loading.

### **Phase 2: RAG Knowledge Base Engine (Qdrant + FastEmbed)**
- [ ] Implement embedding generator (`src/rag/embeddings.py`).
- [ ] Build Qdrant vector store connection & hybrid search retriever (`src/rag/retriever.py`).
- [ ] Create restaurant domain knowledge base (menu, ingredients, allergens, operating hours, delivery policies) in `knowledge_base/`.
- [ ] Build automated ingestion pipeline (`src/rag/ingestion.py` and `scripts/ingest_knowledge.py`).

### **Phase 3: Agent Tools & Domain Logic**
- [x] Build Knowledge Retrieval tool (`src/tools/knowledge_search.py`).
- [x] Build Order Status & Tracking tool with mock order database (`src/tools/order_status.py`).
- [x] Build Table Reservation & Booking tool (`src/tools/reservation.py`).
- [ ] Build Human Escalation & Handoff tool (`src/tools/human_handoff.py`).

### **Phase 4: Real-Time LiveKit Voice Agent Pipeline**
- [ ] Define persona & system prompts in `src/agent/prompts.py`.
- [ ] Build session state manager in `src/agent/session_manager.py`.
- [ ] Implement the LiveKit voice worker (`src/agent/voice_agent.py`) integrating Deepgram STT + Groq LLM + ElevenLabs TTS + Silero VAD + Registered Tools.
- [ ] Build local CLI console runner (`scripts/test_call.py`) for end-to-end testing.

### **Phase 5: Streamlit Admin & Analytics Dashboard**
- [ ] Build main dashboard entry point (`src/dashboard/app.py`).
- [ ] Build Call Logs & Transcripts page (`src/dashboard/pages/01_calls.py`).
- [ ] Build Metrics & Analytics page (`src/dashboard/pages/02_analytics.py`).
- [ ] Build Knowledge Base Management page (`src/dashboard/pages/03_knowledge.py`).
- [ ] Build Settings & Prompt Playground page (`src/dashboard/pages/04_settings.py`).

### **Phase 6: Automated Testing, Containerization & Production Deployment**
- [ ] Write unit & integration test suite (`tests/`).
- [ ] Create multi-stage `Dockerfile` and `docker-compose.yml`.
- [ ] Create AWS ECS task definition and deployment scripts (`infra/`).
- [ ] End-to-end verification and documentation (`README.md`).

---

## 4. Verification & Testing Strategy
- Unit tests for embeddings, Qdrant retriever, and each agent tool function.
- Local voice loop verification using LiveKit Agent CLI console & WebRTC playground.
- Real-time tool invocation testing (order tracking, reservation booking, menu lookup).
- Streamlit dashboard validation for call analytics and dynamic prompt updates.
