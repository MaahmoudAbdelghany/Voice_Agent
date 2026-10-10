"""
Voice Latency & Operational Analytics Page.

Provides executive KPI summary cards, constitutional SLA tracking (<800ms),
sub-component turnaround breakdowns (STT/LLM/TTS), daily & hourly rush-hour traffic curves,
customer sentiment distribution, and AI tool execution analytics.
"""

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.analytics_data import (
    SLA_BUDGET_LLM_MS,
    SLA_BUDGET_STT_MS,
    SLA_BUDGET_TOTAL_MS,
    SLA_BUDGET_TTS_MS,
    aggregate_daily_volume,
    aggregate_hourly_volume,
    aggregate_language_distribution,
    aggregate_latency_breakdown,
    aggregate_sentiment_distribution,
    aggregate_tool_invocations,
    calculate_analytics_kpis,
    filter_analytics_sessions,
    seed_analytics_call_sessions,
)
from src.dashboard.calls_data import load_all_call_sessions
from src.dashboard.i18n import t

# ==============================================================================
# 1. Page Configuration
# ==============================================================================
st.set_page_config(
    page_title="Voice Agent — Analytics & Latency | تحليلات الأداء",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==============================================================================
# 2. State & Localization Management
# ==============================================================================
if "lang" not in st.session_state:
    st.session_state.lang = "en"

lang = st.session_state.lang
is_arabic = lang == "ar"

# Inject Custom Design System CSS
CSS_PATH = Path(__file__).parent.parent / "assets" / "style.css"
if CSS_PATH.exists():
    with open(CSS_PATH, "r", encoding="utf-8") as f:
        custom_css = f.read()
    st.markdown(f"<style>{custom_css}</style>", unsafe_allow_html=True)

# RTL text alignment for Arabic mode
if is_arabic:
    st.markdown(
        """
        <style>
        .block-container {
            direction: rtl;
            text-align: right;
        }
        .stMarkdown, p, span, h1, h2, h3, h4, label {
            text-align: right !important;
            font-family: 'Cairo', sans-serif !important;
        }
        .header-container, .chart-header {
            flex-direction: row-reverse;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

# ==============================================================================
# 3. Sidebar Filtering & Controls
# ==============================================================================
with st.sidebar:
    st.markdown(f"### ⚙️ {t('sidebar_settings_title', lang)}")
    
    # Language Switcher
    lang_options = {"en": "English 🇺🇸", "ar": "العربية 🇸🇦"}
    current_index = 0 if lang == "en" else 1
    selected_lang_label = st.radio(
        label=t("sidebar_language_label", lang),
        options=list(lang_options.values()),
        index=current_index,
        key="analytics_lang_toggle",
    )
    new_lang = "en" if "English" in selected_lang_label else "ar"
    if new_lang != st.session_state.lang:
        st.session_state.lang = new_lang
        st.rerun()

    st.markdown("---")
    st.markdown(f"### 🔍 {t('filter_section_title', lang)}")

    # Time Range Selector
    time_range_labels = {
        "24h": t("time_range_24h", lang),
        "7d": t("time_range_7d", lang),
        "30d": t("time_range_30d", lang),
        "all": t("time_range_all", lang),
    }
    selected_range_key = st.selectbox(
        label=t("filter_time_range_label", lang),
        options=list(time_range_labels.keys()),
        format_func=lambda k: time_range_labels[k],
        index=1,  # Default to 7d
    )

    # Status Selector
    status_labels = {
        "all": t("status_opt_all", lang),
        "completed": t("status_opt_completed", lang),
        "escalated": t("status_opt_escalated", lang),
        "active": t("status_opt_active", lang),
    }
    selected_status_key = st.selectbox(
        label=t("filter_status_label", lang),
        options=list(status_labels.keys()),
        format_func=lambda k: status_labels[k],
        index=0,
    )

    # Language Slicer
    lang_filter_labels = {
        "all": t("filter_lang_all", lang),
        "ar": t("filter_lang_ar", lang),
        "en": t("filter_lang_en", lang),
    }
    selected_lang_filter = st.selectbox(
        label=t("filter_language_label", lang),
        options=list(lang_filter_labels.keys()),
        format_func=lambda k: lang_filter_labels[k],
        index=0,
    )

    st.markdown("---")
    if st.button(f"🔄 {t('refresh_button', lang)}", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ==============================================================================
# 4. Data Loading & Seeding
# ==============================================================================
raw_sessions = load_all_call_sessions(auto_seed=True)

# Ensure historical curves are rich if records < 10
if len(raw_sessions) < 10:
    seed_analytics_call_sessions()
    raw_sessions = load_all_call_sessions(auto_seed=False)

# Filter sessions according to sidebar criteria
sessions = filter_analytics_sessions(
    raw_sessions,
    time_range=selected_range_key,
    language=selected_lang_filter,
    status=selected_status_key,
)

# Calculate aggregated KPIs
kpis = calculate_analytics_kpis(sessions)


# ==============================================================================
# 5. Header Banner
# ==============================================================================
status_badge_html = f"""
<div class="live-badge">
    <div class="pulse-dot"></div>
    <span>{kpis['total_calls']} {t('analytics_kpi_total_calls', lang)}</span>
</div>
"""

st.markdown(
    f"""
    <div class="header-container">
        <div class="header-title-box">
            <h1>📊 {t('analytics_page_title', lang)}</h1>
            <p>{t('analytics_page_subtitle', lang)}</p>
        </div>
        <div>
            {status_badge_html}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ==============================================================================
# 6. Executive KPI Summary Cards
# ==============================================================================
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric(
        label=t("analytics_kpi_total_calls", lang),
        value=f"{kpis['total_calls']}",
        delta=f"{kpis['total_turns']} {t('col_turns', lang)}",
    )

with col2:
    is_sla_met = kpis["avg_latency_ms"] < SLA_BUDGET_TOTAL_MS
    delta_str = f"Target < {int(SLA_BUDGET_TOTAL_MS)}ms"
    st.metric(
        label=t("analytics_kpi_avg_latency", lang),
        value=f"{kpis['avg_latency_ms']} ms",
        delta=delta_str if is_sla_met else f"⚠️ +{round(kpis['avg_latency_ms'] - SLA_BUDGET_TOTAL_MS, 1)}ms",
        delta_color="normal" if is_sla_met else "inverse",
    )

with col3:
    st.metric(
        label=t("analytics_kpi_sla_rate", lang),
        value=f"{kpis['sla_compliance_rate']}%",
        delta=f"{kpis['sla_pass_count']} Pass / {kpis['sla_breach_count']} Breach",
        delta_color="normal" if kpis["sla_compliance_rate"] >= 90.0 else "inverse",
    )

with col4:
    st.metric(
        label=t("analytics_kpi_escalation", lang),
        value=f"{kpis['escalation_rate']}%",
        delta=t("kpi_handoff_rate_sub", lang),
        delta_color="normal" if kpis["escalation_rate"] <= 10.0 else "inverse",
    )

with col5:
    duration_min = round(kpis["total_duration_minutes"], 1)
    st.metric(
        label=t("analytics_kpi_duration", lang),
        value=f"{int(kpis['avg_duration_seconds'])}s",
        delta=f"{duration_min} min {t('col_duration', lang)}",
    )

st.markdown("<div style='margin-bottom: 1.5rem;'></div>", unsafe_allow_html=True)


# If no data matches the filter, display graceful notice
if not sessions:
    st.warning(f"⚠️ {t('analytics_no_data_warn', lang)}")
    st.stop()


# ==============================================================================
# Helper: Dark Plotly Layout Generator
# ==============================================================================
def create_dark_layout(title: str) -> dict[str, Any]:
    return {
        "title": {
            "text": f"<b>{title}</b>",
            "font": {"family": "Cairo, Inter, sans-serif", "size": 14, "color": "#F0F6FC"},
            "x": 0.02,
        },
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(22, 27, 34, 0.45)",
        "font": {"family": "Cairo, Inter, sans-serif", "color": "#8B949E", "size": 11},
        "margin": {"l": 35, "r": 30, "t": 45, "b": 35},
        "legend": {
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1.0,
            "font": {"size": 11, "color": "#E2E8F0"},
        },
        "xaxis": {
            "gridcolor": "rgba(255, 255, 255, 0.06)",
            "zerolinecolor": "rgba(255, 255, 255, 0.12)",
        },
        "yaxis": {
            "gridcolor": "rgba(255, 255, 255, 0.06)",
            "zerolinecolor": "rgba(255, 255, 255, 0.12)",
        },
    }


# ==============================================================================
# 7. Section 1: Constitutional Voice Latency Telemetry
# ==============================================================================
st.markdown(f"### ⚡ {t('sec_sla_breakdown_title', lang)}")
st.markdown(f"<p class='chart-subtitle'>{t('sec_sla_breakdown_desc', lang)}</p>", unsafe_allow_html=True)

lat_col1, lat_col2 = st.columns(2)
lat_data = aggregate_latency_breakdown(sessions)

with lat_col1:
    # Component breakdown vs SLA budget
    comp_labels = [
        t("chart_stt_bar", lang),
        t("chart_llm_bar", lang),
        t("chart_tts_bar", lang),
        t("chart_total_bar", lang),
    ]
    measured_vals = [
        lat_data["avg_stt_ms"],
        lat_data["avg_llm_ms"],
        lat_data["avg_tts_ms"],
        lat_data["avg_total_ms"],
    ]
    target_vals = [
        SLA_BUDGET_STT_MS,
        SLA_BUDGET_LLM_MS,
        SLA_BUDGET_TTS_MS,
        SLA_BUDGET_TOTAL_MS,
    ]

    fig_comp = go.Figure()
    fig_comp.add_trace(go.Bar(
        name=t("col_avg_latency", lang),
        x=comp_labels,
        y=measured_vals,
        marker_color=["#38BDF8", "#818CF8", "#A78BFA", "#10B981"],
        text=[f"{v}ms" for v in measured_vals],
        textposition="auto",
    ))
    fig_comp.add_trace(go.Bar(
        name=t("chart_sla_target_label", lang),
        x=comp_labels,
        y=target_vals,
        marker_color="rgba(245, 158, 11, 0.35)",
        marker_line={"color": "#F59E0B", "width": 1.5},
        text=[f"<{int(v)}ms" for v in target_vals],
        textposition="outside",
    ))
    fig_comp.update_layout(
        create_dark_layout(t("chart_component_latency_title", lang)),
        barmode="group",
        height=320,
        yaxis_title="Milliseconds (ms)",
    )
    st.plotly_chart(fig_comp, use_container_width=True)

with lat_col2:
    # Distribution of turn turnaround times
    turn_latencies = [t_rec["total_ms"] for t_rec in lat_data["all_turns"]]
    if turn_latencies:
        fig_dist = px.histogram(
            x=turn_latencies,
            nbins=18,
            color_discrete_sequence=["#6366F1"],
            opacity=0.85,
        )
        fig_dist.add_vline(
            x=SLA_BUDGET_TOTAL_MS,
            line_width=2.5,
            line_dash="dash",
            line_color="#EF4444",
            annotation_text=f"SLA Ceiling ({int(SLA_BUDGET_TOTAL_MS)}ms)",
            annotation_position="top right",
            annotation_font={"color": "#F87171", "size": 10},
        )
        fig_dist.update_layout(
            create_dark_layout(t("chart_latency_dist_title", lang)),
            height=320,
            xaxis_title="Turn Latency (ms)",
            yaxis_title="Turns Count",
            showlegend=False,
        )
        st.plotly_chart(fig_dist, use_container_width=True)
    else:
        st.info("No turn-level latencies available for the selected range.")


# ==============================================================================
# 8. Section 2: Traffic Volume & Rush-Hour Concurrency
# ==============================================================================
st.markdown(f"### 📈 {t('sec_volume_trends_title', lang)}")
st.markdown(f"<p class='chart-subtitle'>{t('sec_volume_trends_desc', lang)}</p>", unsafe_allow_html=True)

vol_col1, vol_col2 = st.columns(2)

daily_data = aggregate_daily_volume(sessions)
hourly_data = aggregate_hourly_volume(sessions)

with vol_col1:
    if daily_data:
        df_daily = pd.DataFrame(daily_data)
        fig_daily = go.Figure()
        fig_daily.add_trace(go.Bar(
            name=t("status_opt_completed", lang),
            x=df_daily["date"],
            y=df_daily["completed"],
            marker_color="#10B981",
        ))
        fig_daily.add_trace(go.Bar(
            name=t("status_opt_escalated", lang),
            x=df_daily["date"],
            y=df_daily["escalated"],
            marker_color="#EF4444",
        ))
        fig_daily.update_layout(
            create_dark_layout(t("chart_daily_volume_title", lang)),
            barmode="stack",
            height=320,
            xaxis_title="Date",
            yaxis_title="Total Calls",
        )
        st.plotly_chart(fig_daily, use_container_width=True)
    else:
        st.info("No daily traffic data available.")

with vol_col2:
    if hourly_data:
        df_hourly = pd.DataFrame(hourly_data)
        colors = ["#F59E0B" if is_p else "#6366F1" for is_p in df_hourly["is_peak"]]
        
        fig_hourly = go.Figure()
        fig_hourly.add_trace(go.Bar(
            x=df_hourly["hour_label"],
            y=df_hourly["count"],
            marker_color=colors,
            text=df_hourly["count"],
            textposition="auto",
        ))
        fig_hourly.update_layout(
            create_dark_layout(t("chart_hourly_volume_title", lang)),
            height=320,
            xaxis_title="Hour of Day (UTC)",
            yaxis_title="Call Volume",
            showlegend=False,
        )
        st.plotly_chart(fig_hourly, use_container_width=True)
    else:
        st.info("No hourly traffic data available.")


# ==============================================================================
# 9. Section 3: Conversational & Domain AI Intelligence
# ==============================================================================
st.markdown(f"### 🤖 {t('sec_conversational_insights_title', lang)}")
st.markdown(f"<p class='chart-subtitle'>{t('sec_conversational_insights_desc', lang)}</p>", unsafe_allow_html=True)

conv_col1, conv_col2, conv_col3 = st.columns(3)

# 1. Customer Sentiment
sent_data = aggregate_sentiment_distribution(sessions)
with conv_col1:
    sent_labels = [
        t("chart_sentiment_pos", lang),
        t("chart_sentiment_neu", lang),
        t("chart_sentiment_neg", lang),
    ]
    sent_vals = [
        sent_data["positive"],
        sent_data["neutral"],
        sent_data["negative"],
    ]
    fig_sent = go.Figure(data=[go.Pie(
        labels=sent_labels,
        values=sent_vals,
        hole=0.55,
        marker={"colors": ["#10B981", "#3B82F6", "#EF4444"]},
        textinfo="percent+label",
    )])
    fig_sent.update_layout(
        create_dark_layout(t("chart_sentiment_title", lang)),
        height=280,
        showlegend=False,
    )
    st.plotly_chart(fig_sent, use_container_width=True)

# 2. Tool Invocations
tool_data = aggregate_tool_invocations(sessions)
with conv_col2:
    if tool_data:
        df_tools = pd.DataFrame(tool_data)
        fig_tools = go.Figure(go.Bar(
            x=df_tools["count"],
            y=df_tools["tool_name"],
            orientation="h",
            marker_color="#8B5CF6",
            text=df_tools["count"],
            textposition="auto",
        ))
        fig_tools.update_layout(
            create_dark_layout(t("chart_tools_title", lang)),
            height=280,
            yaxis={"autorange": "reversed"},
            xaxis_title="Calls Count",
            showlegend=False,
        )
        st.plotly_chart(fig_tools, use_container_width=True)
    else:
        st.info("No AI tool invocations recorded in this period.")

# 3. Language Distribution
lang_data = aggregate_language_distribution(sessions)
with conv_col3:
    lang_labels = ["العربية (Arabic)", "English"]
    lang_vals = [lang_data["ar"], lang_data["en"]]
    fig_lang = go.Figure(data=[go.Pie(
        labels=lang_labels,
        values=lang_vals,
        hole=0.55,
        marker={"colors": ["#06B6D4", "#EC4899"]},
        textinfo="percent+label",
    )])
    fig_lang.update_layout(
        create_dark_layout(t("chart_language_title", lang)),
        height=280,
        showlegend=False,
    )
    st.plotly_chart(fig_lang, use_container_width=True)


# ==============================================================================
# 10. Footer Notice
# ==============================================================================
st.markdown("---")
st.markdown(
    f"""
    <div style="text-align: center; color: var(--text-secondary); font-size: 0.85rem; padding: 1rem 0;">
        {t('footer_text', lang)}
    </div>
    """,
    unsafe_allow_html=True,
)
