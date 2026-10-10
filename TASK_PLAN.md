# Voice Agent — Task Plan

## Spec-Driven Development (SDD) Constitution & Governance
- [x] spec/mission.md — Product Mission, Problem, Target Users & Scope
- [x] spec/tech.md — Tech Constitution, Architecture Invariants & SLA Budgets
- [x] spec/roadmap.md — Product Roadmap & Phased Feature Tracker
- [x] .agents/skills/skill for working on the next feature/SKILL.md — Pre-implementation SDD Feature Validation & 3-Tier Testing Skill

## Phase 1: Project Foundation & Configuration
- [x] pyproject.toml — dependencies and packaging configuration (Hatchling)
- [x] .gitignore & .env.example — environment templates & security exclusions
- [x] src/config.py — centralized settings with Pydantic BaseSettings
- [x] README.md — project overview and architecture documentation

## Phase 2: RAG Knowledge Base Engine (Qdrant + FastEmbed)
- [x] knowledge_base/restaurant_kb.md — rich restaurant domain knowledge base
- [x] src/rag/embeddings.py — FastEmbed multilingual embedding service (paraphrase-multilingual-MiniLM-L12-v2)
- [x] src/rag/retriever.py — Qdrant vector store connection & hybrid search
- [x] src/rag/ingestion.py — markdown header-aware chunking pipeline
- [x] scripts/ingest_knowledge.py — CLI ingestion & retrieval verification script
- [x] tests/test_rag.py — unit tests for embeddings, retriever, and ingestion

## Phase 3: Agent Tools & Domain Execution Logic
- [x] src/tools/schemas.py — Pydantic schemas for tool inputs and outputs
- [x] src/tools/knowledge_search.py — RAG knowledge search tool for menu and policies
- [x] src/tools/order_status.py — order lookup & live delivery tracking tool
- [x] src/tools/reservation.py — table booking & availability reservation tool
- [x] src/tools/human_handoff.py — human supervisor escalation & handoff tool
- [x] src/tools/__init__.py — tool registry and exports
- [x] tests/test_tools.py — unit tests for all domain execution tools

## Phase 4: Real-Time LiveKit Voice Agent Core
- [x] src/agent/prompts.py — persona, system prompts, and conversation guidelines
- [x] src/agent/session_manager.py — call session state, turn memory, and context tracking
- [x] src/agent/voice_agent.py — LiveKit pipeline (Deepgram STT + Groq LLM + ElevenLabs TTS + Silero VAD + Tools)
- [x] scripts/test_call.py — CLI voice agent simulation runner
- [x] tests/test_agent.py — session orchestration and agent pipeline tests

- [x] src/dashboard/app.py — main Streamlit dashboard entry point & styling
- [x] spec/features/feature-502-call-logs-transcript-viewer/ — Feature 5.2 Plan, Requirements & 3-Tier Validation Specification
- [x] Step 5.2.1: src/dashboard/calls_data.py, i18n & CSS — data layer, demo seeder, audio resolver & styles
- [x] Step 5.2.2: src/dashboard/pages/01_calls.py — call logs, audio playback & transcript viewer page
- [x] Step 5.2.3: tests/test_calls_page.py — 3-Tier automated validation suite
- [x] spec/features/feature-503-latency-charts-call-volume-analytics/ — Feature 5.3 Plan, Requirements & 3-Tier Validation Specification
- [ ] Step 5.3.1: src/dashboard/analytics_data.py, i18n & CSS — data aggregator, 7-day seeder, translations & styles
- [ ] Step 5.3.2: src/dashboard/pages/02_analytics.py — executive KPI cards, Plotly latency breakdown & volume charts
- [ ] Step 5.3.3: tests/test_analytics_page.py — 3-Tier automated validation suite & regression checks
- [ ] src/dashboard/pages/03_knowledge.py — knowledge base management & live ingestion UI
- [ ] src/dashboard/pages/04_settings.py — prompt playground & runtime configuration

## Phase 6: Production Containerization & AWS Deployment
- [ ] Dockerfile — multi-stage production container build
- [ ] docker-compose.yml — local multi-container orchestration
- [ ] infra/ecs-task-definition.json — AWS ECS Fargate task definition
- [ ] infra/deploy.sh — AWS deployment automation script
- [ ] tests/test_e2e.py — end-to-end simulated call flow verification


finaly i want make our conversation in arabic