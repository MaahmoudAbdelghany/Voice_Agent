# Feature Requirements: Feature 5.2 — Call Logs, Audio Playback & Transcript Viewer

## 1. Overview
The Call Logs, Audio Playback & Transcript Viewer (`src/dashboard/pages/01_calls.py`) provides supervisory visibility into every voice interaction handled by the Voice AI Agent. It bridges real-time call telemetry with actionable post-call analytics and audio evaluation.

---

## 2. Functional Requirements

### FR-502.1: Call History Table & Multi-Criteria Filtering
- **FR-502.1.1**: Render a summary table of all recorded and active voice calls loaded from disk (`data/calls/`) and memory.
- **FR-502.1.2**: Each table row must display:
  - Session ID (compact / truncated display with full tooltip).
  - Timestamp (formatted in local time with ISO tooltip).
  - Customer Info (Name and/or Phone number).
  - Status (`Active`, `Ended`, `Escalated`).
  - Language (`Arabic`, `English`).
  - Duration (in seconds or mm:ss format).
  - Turn Count & Tool Invocations.
  - Average Turn Latency (in milliseconds, color-coded against the < 800ms SLA).
- **FR-502.1.3**: Provide filtering controls:
  - Filter by Status: `All`, `Active`, `Ended`, `Escalated`.
  - Filter by Language: `All`, `Arabic`, `English`.
  - Text search: filter across Session ID, Customer Name, Phone, and Order ID.
- **FR-502.1.4**: Allow the user to select an individual call from the list or a dropdown selector to inspect its deep-dive details.

### FR-502.2: Detailed Call Inspector & Context Card
- **FR-502.2.1**: When a session is selected, display an overview header containing:
  - Customer identity & phone number.
  - Call room name & participant ID.
  - Extracted business slots (Order ID, reservation draft, dietary preferences, detected customer sentiment).
  - Escalation alert banner with department and reason if `escalated == True`.
- **FR-502.2.2**: Display KPI summary tiles for the selected call: Duration, Average Latency, Max Latency, Interruption Count, Total Tool Calls.

### FR-502.3: Audio Playback Engine & Fallback
- **FR-502.3.1**: Check `data/calls/audio/<session_id>.wav` or `.mp3` for recorded call audio.
- **FR-502.3.2**: If a physical recording file exists, embed an HTML5 / Streamlit native audio player (`st.audio`) allowing play, pause, seek, and volume adjustment.
- **FR-502.3.3**: If no recording file exists, generate or provide a lightweight synthetic voice sample demo (e.g. standard generated sine/tone greeting or sample WAV bytes) with an explicit notice badge (*"Demo Synthetic Audio Sample"*), ensuring the UI never crashes or displays a broken media element.

### FR-502.4: Interactive Chat Bubble Transcript & Tool Visualizer
- **FR-502.4.1**: Display conversation turns as modern chat bubbles:
  - Caller turns: styled with user avatar/bubble, aligned to user side, displaying transcribed text.
  - Assistant turns: styled with agent avatar/bubble, displaying vocal response text.
  - Timestamp on each bubble.
- **FR-502.4.2**: Per-turn Latency Telemetry:
  - Display latency metrics badge on assistant turns showing Total Latency, STT Latency (Deepgram), LLM TTFT (Groq), and TTS Synthesis Latency (ElevenLabs).
  - Mark interrupted turns clearly with a warning badge (`⚡ Interrupted / تم المقاطعة`).
- **FR-502.4.3**: Tool Execution Callouts:
  - When a tool is executed during a turn (`role == TOOL` or attached tool metadata), render an expandable card showing:
    - Tool Name (e.g., `check_order_status`, `search_knowledge_base`, `book_reservation`, `escalate_to_human`).
    - Input parameters (formatted JSON).
    - Execution result / return payload (formatted JSON).

### FR-502.5: Auto-Seeding Realistic Demo Sessions
- **FR-502.5.1**: If `data/calls/` contains zero session files on initial load, automatically seed at least 4 realistic restaurant calls:
  1. *Arabic Shawarma Delivery Inquiry*: Order tracking and delivery ETA inquiry.
  2. *English Table Reservation*: Booking for 4 guests on Friday evening.
  3. *Arabic Dietary & Allergy Inquiry*: Checking gluten-free options via RAG.
  4. *Escalated Customer Complaint*: Late delivery requiring human supervisor handoff.
- **FR-502.5.2**: Provide a manual button in the sidebar (*"Seed Sample Calls"* / *"توليد مكالمات تجريبية"*) to regenerate demo data at any time.

### FR-502.6: Bilingual & RTL Support
- **FR-502.6.1**: Full translation of all UI labels, filters, column headers, tool names, and badges via `src/dashboard/i18n.py`.
- **FR-502.6.2**: Respect `st.session_state.lang` set in `app.py`, adapting text direction (`dir="rtl"`) for Arabic interfaces.
- **FR-502.6.3**: Render Arabic transcript speech bubbles with right-aligned text and Cairo font.

---

## 3. Non-Functional Requirements (NFR)

- **NFR-502.1 (Performance)**: Page render and call filtering must execute within < 1.0 second for up to 100 persisted calls.
- **NFR-502.2 (Visual Excellence)**: Adhere strictly to the dark slate and glassmorphism design system (`style.css`), utilizing cohesive badges and subtle hover animations.
- **NFR-502.3 (Resilience & Zero Regressions)**: Malformed JSON session files or empty transcript arrays must be ignored or flagged cleanly without crashing the page.
- **NFR-502.4 (Security & Privacy)**: Display phone numbers with optional masking (e.g., `+966 50 *** 1234`) for data protection.

---

## 4. Constraints
- Compatible with Streamlit multi-page structure under `src/dashboard/pages/`.
- Must utilize existing `CallSession`, `TurnMessage`, `CallMetrics` schemas from `src.agent.session_manager`.
- Zero external heavy JavaScript dependencies; pure Streamlit + CSS.
