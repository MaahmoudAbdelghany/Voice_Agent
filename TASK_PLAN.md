# Task Execution Plan — Voice Agent

- [x] **Step 1: Project Foundation & Configuration Setup** <!-- id: 0 -->
  - Create `.gitignore`, `.env.example`, and `pyproject.toml` with pinned dependencies.
  - Implement centralized configuration in `src/config.py` using `pydantic-settings`.
  - Validate environment loading and directory structure.

- [x] **Step 2: RAG Knowledge Base Engine (Qdrant + FastEmbed)** <!-- id: 1 -->
  - Implement embedding helper in `src/rag/embeddings.py` using `fastembed`.
  - Implement Qdrant vector store connection & hybrid search in `src/rag/retriever.py`.
  - Create rich restaurant domain knowledge base (menu, ingredients, allergens, FAQs, delivery rules) in `knowledge_base/restaurant_kb.md`.
  - Implement ingestion pipeline in `src/rag/ingestion.py` and CLI script in `scripts/ingest_knowledge.py`.

- [ ] **Step 3: Agent Tools & Domain Execution Logic** <!-- id: 2 -->
  - Implement RAG knowledge search tool in `src/tools/knowledge_search.py`.
  - Implement order status & live delivery tracking tool in `src/tools/order_status.py`.
  - Implement table reservation & booking tool in `src/tools/reservation.py`.
  - Implement human escalation & handoff tool in `src/tools/human_handoff.py`.

- [ ] **Step 4: Real-Time LiveKit Voice Agent Core** <!-- id: 3 -->
  - Create agent prompt templates and persona in `src/agent/prompts.py`.
  - Implement call session state manager and event emitter in `src/agent/session_manager.py`.
  - Implement `src/agent/voice_agent.py` using LiveKit Agents pipeline (Deepgram STT + Groq LLM + ElevenLabs TTS + Silero VAD + Tools).
  - Create test script `scripts/test_call.py` for interactive terminal/console simulation.

- [ ] **Step 5: Streamlit Admin & Analytics Dashboard** <!-- id: 4 -->
  - Build main dashboard app in `src/dashboard/app.py` with custom styling.
  - Build Call Logs & Transcripts viewer in `src/dashboard/pages/01_calls.py`.
  - Build Analytics & Performance page in `src/dashboard/pages/02_analytics.py`.
  - Build Knowledge Base Management & Ingestion page in `src/dashboard/pages/03_knowledge.py`.
  - Build Settings & Prompt Playground page in `src/dashboard/pages/04_settings.py`.

- [ ] **Step 6: Automated Testing Suite** <!-- id: 5 -->
  - Implement unit tests for RAG retriever and embeddings in `tests/test_rag.py`.
  - Implement unit tests for order, reservation, and search tools in `tests/test_tools.py`.
  - Implement agent session orchestration tests in `tests/test_agent.py`.
  - Run `pytest` and ensure all tests pass.

- [ ] **Step 7: Production Containerization & AWS Deployment Assets** <!-- id: 6 -->
  - Create production multi-stage `Dockerfile` and `docker-compose.yml`.
  - Create AWS ECS task definition `infra/ecs-task-definition.json` and deployment guide.
  - Create comprehensive `README.md` with setup, architecture, and live run instructions.
