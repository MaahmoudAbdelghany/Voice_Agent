# Validation Criteria: Feature 5.3 — Latency Charts & Call Volume Analytics

## 1. Success Definition
Feature 5.3 is declared successful when:
1. `src/dashboard/analytics_data.py` correctly calculates aggregate KPIs (total calls, mean/p95 latency, SLA adherence %, escalation rate) and aggregates time-series and categorical data for Plotly visualizations.
2. The automatic time-distribution seeder generates valid, realistic call records distributed over the last 7 days when local records are fewer than 10.
3. `src/dashboard/pages/02_analytics.py` renders cleanly without Streamlit runtime errors, presenting executive KPI cards and responsive, dark-themed Plotly charts for latency breakdown, volume trends, sentiment, and tool usage.
4. Language toggling between Arabic (RTL) and English updates all chart titles, axis labels, legends, and metric headers seamlessly.
5. Automated 3-tier tests (`tests/test_analytics_page.py`) pass with 100% success, and existing tests pass with zero regressions.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification (التحقق المعزول)
- **Scope**: `src/dashboard/analytics_data.py` mathematical calculations, percentile formulas, and grouping pipelines.
- **Test Cases**:
  - `test_calculate_kpis_empty`: Verifies safe default metrics (0 calls, 0.0 latency, 100% SLA) when input session list is empty.
  - `test_calculate_kpis_with_sessions`: Validates exact arithmetic for average latency, p95 latency, SLA compliance rate (<800ms), and escalation rate on known datasets.
  - `test_aggregate_latency_breakdown`: Confirms correct average decomposition into STT, LLM, and TTS milliseconds.
  - `test_aggregate_hourly_and_daily_volume`: Verifies correct time bucketing (24-hour distribution and daily grouping).
  - `test_aggregate_tool_invocations`: Verifies counting and ranking of tool names from session turns.
  - `test_aggregate_sentiment_distribution`: Confirms positive, neutral, and negative sentiment counts.
  - `test_seed_analytics_calls`: Verifies generation of time-distributed sessions across multiple days with realistic timestamps and latency metrics.

### Tier 2: Integration Verification (تحقق التكامل بين المكونات)
- **Scope**: End-to-end Streamlit page execution via `streamlit.testing.v1.AppTest`.
- **Test Cases**:
  - `test_analytics_page_renders_without_errors`: Launches `02_analytics.py` via `AppTest` and asserts no unhandled exceptions.
  - `test_analytics_page_filters_interaction`: Simulates user changing the date range selector (Last 24 Hours, Last 7 Days, All Time) and language toggle, asserting that page re-computes without error.
  - `test_analytics_page_renders_charts`: Asserts that Plotly chart elements (`st.plotly_chart`) and metric elements (`st.metric`) are present in the component tree.

### Tier 3: Error & Edge-Case Verification (تحقق الحالات الشاذة والحدودية)
- **Scope**: Defensive behavior under abnormal data conditions.
- **Test Cases**:
  - `test_zero_calls_graceful_display`: When no call sessions exist and seeding is disabled, page displays informative warning banners without crashing.
  - `test_sessions_with_null_latencies`: Turns missing `latency_ms`, `stt_latency_ms`, or `tts_latency_ms` are safely ignored by the aggregators without throwing `TypeError`.
  - `test_extreme_sla_breach`: Validates correct handling and alerting when 100% of calls breach the 800ms SLA budget.
  - `test_single_call_session`: Verifies percentile calculations (e.g., p95) do not crash when dataset size is N=1.

### Tier 4: Regression Checks (تحقق منع الانحدار)
- **Scope**: Verification that prior features remain intact.
- **Execution**: Run complete test suite:
  - `tests/test_calls_page.py` (Feature 5.2)
  - `tests/test_tools.py` (Phase 3)
  - `tests/test_agent.py` (Phase 4)
  - `tests/test_rag.py` (Phase 2)

### Tier 5: Build, Lint & Type Checks (تحقق البناء وتكامل الأنماط)
- **Scope**: Syntax validity and coding standards.
- **Execution**: Run `ruff check` on newly created and modified files (`src/dashboard/analytics_data.py`, `src/dashboard/pages/02_analytics.py`, `tests/test_analytics_page.py`).

### Tier 6: Manual / Visual Verification (التحقق اليدوي والبصري)
- **Scope**: Human review of UI layout, dark-theme harmony, chart responsiveness, and Arabic RTL typography.
- **Steps**:
  1. Launch Streamlit dashboard: `streamlit run src/dashboard/app.py`.
  2. Navigate to `02_analytics` via sidebar.
  3. Verify executive KPI cards (Calls, Latency, SLA %, Escalations).
  4. Inspect the Component Latency Breakdown chart (STT, LLM, TTS targets).
  5. Inspect the Hourly Traffic and Daily Call Volume charts.
  6. Inspect Customer Sentiment and AI Tool invocation charts.
  7. Toggle language to Arabic and verify text alignment, labels, and RTL rendering.

### Tier 7: API / CLI / Application Checks (تحقق واجهات التطبيق المباشرة)
- **Status**: Not Applicable
- **Technical Justification**: Feature 5.3 is strictly an administrative web analytics visualization interface and data aggregation utility inside Streamlit. It does not introduce standalone CLI subcommands (unlike `scripts/test_call.py`) or external REST/gRPC endpoints. Operational verification is fully provided via Tier 2 (AppTest) and Tier 6 (Streamlit UI).

---

## 3. Automated Execution Commands

```powershell
# 1. Run Feature 5.3 Automated 3-Tier Test Suite
pytest tests/test_analytics_page.py -v

# 2. Run Full Regression Suite
pytest tests/ -v

# 3. Lint & Code Quality Verification
ruff check src/dashboard/analytics_data.py src/dashboard/pages/02_analytics.py tests/test_analytics_page.py

# 4. Manual UI Verification Launch Command
streamlit run src/dashboard/app.py
```
