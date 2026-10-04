# Feature Requirements: Feature 5.1 — Main Dashboard Entry & Design System

## 1. Overview
The Main Dashboard Entry (`src/dashboard/app.py`) serves as the administrative command center for the Voice AI Agent platform. It establishes visual excellence, runtime health visibility, and bilingual accessibility.

---

## 2. Functional Requirements

### FR-501.1: Design System & Visual Hierarchy
- **FR-501.1.1**: The dashboard must render in a modern dark theme with custom CSS styling (`#0E1117` base, dark slate card containers, glassmorphism blur effects, and rounded borders).
- **FR-501.1.2**: Provide visual indicator badges for status (e.g., green for operational/online, yellow for degraded/mocked, red for offline/unconfigured).
- **FR-501.1.3**: Display KPI metric cards with icons, numerical values, and comparative indicators (e.g., average latency target < 800ms).

### FR-501.2: Bilingual Localization (EN / AR)
- **FR-501.2.1**: Provide a language selection toggle in the sidebar allowing the operator to switch between English (`en`) and Arabic (`ar`).
- **FR-501.2.2**: When Arabic is selected, the layout and text alignment must adapt to Right-To-Left (RTL) via CSS direction rules.
- **FR-501.2.3**: All UI titles, headers, metric labels, service names, and button texts must translate accurately without untranslated raw keys.

### FR-501.3: Real-Time Service Health Check
- **FR-501.3.1**: Inspect the connectivity and configuration status of core services:
  - **LiveKit Voice Server**: URL and API Key presence.
  - **Qdrant Vector Database**: Host connectivity or in-memory vector store availability.
  - **Groq Cloud LLM**: API key configuration.
  - **ElevenLabs TTS**: API key configuration.
  - **Deepgram STT**: API key configuration.
- **FR-501.3.2**: Health checks must execute defensively without blocking dashboard load or raising unhandled exceptions if an external service is unreachable.

### FR-501.4: Overview KPIs & Quick Navigation
- **FR-501.4.1**: Display key voice agent operational metrics:
  - Average Turn Latency (Target < 800ms)
  - Active Call Sessions
  - Total Calls Today
  - Human Escalation Rate (%)
- **FR-501.4.2**: Render navigation cards directing administrators to subsequent phases:
  - 📞 Call Logs & Transcripts (`pages/01_calls.py`)
  - 📊 Latency & Metrics Analytics (`pages/02_analytics.py`)
  - 📚 Knowledge Base & Menu Ingestion (`pages/03_knowledge.py`)
  - ⚙️ Prompt Playground & Settings (`pages/04_settings.py`)

---

## 3. Non-Functional Requirements (NFR)
- **NFR-501.1 (Performance)**: Page initial load time must be < 1.5 seconds under standard local runtime.
- **NFR-501.2 (Responsive Layout)**: Dashboard layout must use Streamlit's `layout="wide"` and gracefully scale on desktop (1920x1080) and laptop (1366x768) resolutions.
- **NFR-501.3 (Resilience)**: Missing environment variables or offline cloud APIs must be displayed gracefully with descriptive warning badges rather than crashing the Streamlit app.

---

## 4. Constraints
- Must use Streamlit >= 1.35.0 compatible API (`st.set_page_config`, `st.columns`, `st.metric`).
- No external heavy frontend framework dependencies (pure Streamlit + Vanilla CSS).
- Does not modify existing backend agent core files (`src/agent/`, `src/rag/`, `src/tools/`).
