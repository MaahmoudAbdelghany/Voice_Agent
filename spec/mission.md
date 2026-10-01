# Project Mission — Voice AI Agent for Restaurant & Food Delivery

## 1. Product (WHAT)
**Voice AI Agent** is an enterprise-grade, ultra-low-latency conversational voice assistant designed for restaurants and food delivery services. It operates over real-time WebRTC audio streams, handling incoming phone calls and audio interactions with human-like responsiveness, contextual memory, and domain tool execution.

## 2. Problem Statement (WHY)
Restaurants and food delivery operations suffer from high peak-hour call volumes, resulting in:
- Missed customer orders and reservation inquiries.
- Inconsistent answers regarding menu items, allergens, and branch policies.
- High operational overhead and staff burnout during busy rush hours.
- Slow legacy IVR phone trees that frustrate customers.

## 3. Target Users (WHO)
- **Callers / Customers**: Hungry customers seeking fast menu recommendations, order delivery status updates, table reservations, or human assistance.
- **Restaurant Operators & Managers**: Staff needing reduced phone load and an operational dashboard for call monitoring, transcripts, and analytics.

## 4. Core Value Proposition & Goals
- **Sub-Second Voice Latency**: Sub-500ms conversational turn turnaround via streaming STT, high-speed LLM reasoning, and streaming TTS.
- **Natural Voice Barge-In**: Real-time voice activity detection (VAD) allowing callers to interrupt the AI naturally.
- **Domain Tools Execution**: Grounded actions for menu search (RAG), live order tracking, table booking, and seamless supervisor handoff.
- **Bilingual Capability**: Native support for Arabic and English customer interactions.

## 5. Scope & Boundaries
### In Scope (Current & Planned MVP):
- Real-time WebRTC voice pipeline (LiveKit, Deepgram STT, Groq Llama 3.3, ElevenLabs TTS, Silero VAD).
- Local / Cloud RAG Knowledge Base powered by Qdrant and FastEmbed multilingual embeddings.
- Structured execution tools: `search_knowledge_base`, `check_order_status`, `book_reservation`, `escalate_to_human`.
- Call session memory, turn-taking state management, and metrics collection.
- Streamlit administrative dashboard for live logs, metrics, prompt engineering, and KB management.
- Docker multi-stage containerization and AWS ECS Fargate deployment specs.

### Out of Scope:
- Direct credit card processing over voice (PCI-DSS compliance deferred to external payment links/SMS).
- Multi-tenant enterprise RBAC (Single restaurant branch / franchise model for initial release).
