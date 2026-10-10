# Product Roadmap — Voice AI Agent

## Overview
This roadmap is a **Living Document** under Spec-Driven Development (SDD). Each milestone progresses through:
`Specification (Plan + Requirements + Validation) -> Human Review -> Implementation -> Validation -> Commit & Push -> Replanning`.

---

## Completed Milestones

### Phase 1: Project Foundation & Configuration ✅
- [x] Package management & dependencies (`pyproject.toml`, Hatchling).
- [x] Environment configuration & type safety (`src/config.py`, Pydantic Settings).
- [x] Security hygiene (`.gitignore`, `.env.example`).

### Phase 2: RAG Knowledge Base Engine (Qdrant + FastEmbed) ✅
- [x] Multilingual embedding service (`src/rag/embeddings.py`).
- [x] Qdrant vector store connection & hybrid search (`src/rag/retriever.py`).
- [x] Markdown header-aware chunking pipeline (`src/rag/ingestion.py`).
- [x] Restaurant domain knowledge base (`knowledge_base/restaurant_kb.md`).
- [x] CLI ingestion verification script (`scripts/ingest_knowledge.py`).
- [x] Comprehensive unit tests (`tests/test_rag.py`).

### Phase 3: Agent Tools & Domain Execution Logic ✅
- [x] Pydantic schemas for inputs and outputs (`src/tools/schemas.py`).
- [x] Knowledge retrieval tool (`src/tools/knowledge_search.py`).
- [x] Order status & tracking tool with mock DB (`src/tools/order_status.py`).
- [x] Table reservation tool with availability checks (`src/tools/reservation.py`).
- [x] Human escalation & supervisor handoff (`src/tools/human_handoff.py`).
- [x] Tool registry exports & unit tests (`tests/test_tools.py`).

### Phase 4: Real-Time LiveKit Voice Agent Core ✅
- [x] Restaurant assistant persona & system prompt engineering (`src/agent/prompts.py`).
- [x] Session state management, turn history, and metrics (`src/agent/session_manager.py`).
- [x] LiveKit voice worker pipeline (Deepgram + Groq + ElevenLabs + Silero VAD) (`src/agent/voice_agent.py`).
- [x] Automatic LiveKit clock-skew compensation for JWT authentication.
- [x] CLI voice agent simulation runner (`scripts/test_call.py`).
- [x] Agent pipeline and session orchestration tests (`tests/test_agent.py`).

---

## Active & Upcoming Milestones

### Phase 5: Streamlit Admin & Analytics Dashboard 🚀 (CURRENT FOCUS)
*Goal: Provide a rich, real-time web portal for monitoring calls, viewing latency breakdowns, testing knowledge retrieval, and updating prompt configurations.*

- [x] **Feature 5.1**: Main Dashboard Entry & Design System (`src/dashboard/app.py`) ✅
- [x] **Feature 5.2**: Call Logs, Audio Playback & Transcript Viewer (`src/dashboard/pages/01_calls.py`) ✅
- [x] **Feature 5.3**: Latency Charts & Call Volume Analytics (`src/dashboard/pages/02_analytics.py`) ✅
- **Feature 5.4**: Knowledge Base Management & Live Ingestion UI (`src/dashboard/pages/03_knowledge.py`)
- **Feature 5.5**: Prompt Playground & Runtime Configuration (`src/dashboard/pages/04_settings.py`)

### Phase 6: Production Containerization & AWS Deployment 📦 (UPCOMING)
*Goal: Package the agent and dashboard for production deployment on scalable cloud infrastructure.*

- **Feature 6.1**: Multi-stage production `Dockerfile` & `docker-compose.yml`.
- **Feature 6.2**: AWS ECS Fargate task definition (`infra/ecs-task-definition.json`) & deployment script (`infra/deploy.sh`).
- **Feature 6.3**: End-to-end simulated call flow verification (`tests/test_e2e.py`).
