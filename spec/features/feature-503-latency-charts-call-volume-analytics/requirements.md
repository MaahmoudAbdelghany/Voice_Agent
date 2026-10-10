# Requirements Specification: Feature 5.3 — Latency Charts & Call Volume Analytics

## 1. Functional Requirements

### R1: Data Aggregation & Historical Seeding
- **R1.1**: The system must ingest all persisted call sessions from `data/calls/*.json` and active sessions from `SessionManager`.
- **R1.2**: If the total count of valid sessions is less than 10, the system must automatically seed realistic, time-distributed mock sessions spanning the past 7 days across lunch and dinner peak hours.
- **R1.3**: The system must support aggregating turn-level telemetry: `latency_ms`, `stt_latency_ms`, `llm_latency_ms`, and `tts_latency_ms`.

### R2: Executive KPI Metrics
- **R2.1**: The page must display top-level KPI cards:
  - Total Calls count.
  - Average End-to-End Latency (ms) with SLA adherence indicator.
  - SLA Compliance Rate (`% of assistant turns < 800ms`).
  - Human Escalation Rate (`% of calls transferred to supervisor`).
  - Average Call Duration (seconds/minutes).
- **R2.2**: KPI cards must include contextual subtext or delta badges (e.g., Target: < 800ms).

### R3: Latency Telemetry & SLA Budget Tracking
- **R3.1**: The system must compute and render an SLA Compliance breakdown comparing turns meeting the < 800ms budget vs turns exceeding it.
- **R3.2**: The page must render a Latency Distribution chart (Histogram or Boxplot) visualizing p50 (median), p90, and p95 latencies across assistant turns.
- **R3.3**: The chart must visually annotate the 800ms constitutional threshold line for instant visual compliance auditing.

### R4: Sub-Component Turnaround Breakdown
- **R4.1**: The system must present a component breakdown chart for:
  - Deepgram STT (Constitutional SLA: < 200ms).
  - Groq LLM TTFT (Constitutional SLA: < 300ms).
  - ElevenLabs TTS First-Chunk (Constitutional SLA: < 250ms).
- **R4.2**: The chart must allow comparing average component latencies alongside their SLA targets.

### R5: Call Volume & Peak Concurrency Trends
- **R5.1**: The page must display a daily call volume timeline over the selected date range.
- **R5.2**: The page must render an hourly traffic distribution chart (00:00 to 23:00) identifying peak rush hours (e.g. 12:00-14:00 and 19:00-22:00).
- **R5.3**: Volume trends must distinguish between normal completed calls and escalated calls.

### R6: Customer Sentiment & Outcome Distribution
- **R6.1**: The system must calculate and render a Customer Sentiment chart (Positive, Neutral, Negative) in a donut/pie visualization.
- **R6.2**: The page must show call outcomes (Completed vs Escalated vs Active).

### R7: Domain AI Tool Utilization
- **R7.1**: The page must extract all tool calls (`check_order_status`, `book_reservation`, `search_knowledge_base`, `escalate_to_human`) across filtered sessions.
- **R7.2**: The page must render a horizontal bar chart of tool execution counts and percentages.

### R8: Interactive Multi-Criteria Slicers & Filters
- **R8.1**: The sidebar must provide a Date Range selector:
  - Today (Last 24 Hours)
  - Last 7 Days (Default)
  - Last 30 Days
  - All Time
- **R8.2**: The sidebar must provide a Language filter (`All`, `Arabic`, `English`).
- **R8.3**: All charts and KPI metrics must dynamically re-aggregate immediately when filters change.

---

## 2. Non-Functional Requirements

### NFR1: Performance & Responsive Render
- Metric calculations and chart generation must execute in **< 1.0 second** for up to 1,000 call sessions.
- Calculations must leverage caching where applicable to prevent redundant re-computations during widget interactions.

### NFR2: Visual Excellence & Theme Consistency
- All Plotly visualizations must match the application design system defined in `assets/style.css`:
  - Background: Transparent / Dark `#12151c` / `#1a1d24`.
  - Color Palette: Primary Indigo `#6366f1`, Emerald Green `#10b981` (for SLA pass), Coral Red `#ef4444` (for SLA breach / escalation), Amber `#f59e0b`.
  - Typography: Clean sans-serif with readable axis labels and responsive tooltips.

### NFR3: Bilingual & RTL Support
- Every chart title, axis, legend, KPI label, and filter option must be fully localized in both English and Arabic via `src/dashboard/i18n.py`.
- In Arabic mode, layout and metric texts must follow right-to-left (RTL) reading conventions.

### NFR4: Resilience & Defensive Degradation
- If no call records match the filter, the page must display an informative, pleasant warning message rather than crashing or rendering blank/broken charts.
- Missing or `None` latency values on individual turns must be handled gracefully without causing math errors.

---

## 3. Constraints

- **C1**: Must run completely within the existing Streamlit (`streamlit>=1.35.0`), Pandas (`pandas>=2.2.0`), and Plotly (`plotly>=5.22.0`) dependencies without introducing heavy new external packages.
- **C2**: Must not modify the underlying `CallSession` or `SessionManager` data models in ways that break `01_calls.py` or the LiveKit voice agent.
- **C3**: Read-only operations on disk: Analytics computations must not corrupt or overwrite real historical call JSON files in `data/calls/`.
