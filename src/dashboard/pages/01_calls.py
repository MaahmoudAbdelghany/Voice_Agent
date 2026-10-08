"""
Voice Call Logs, Audio Playback & Transcript Viewer Page.

Provides complete supervisory inspection into all live and persisted voice interactions,
multi-criteria search and filtering, audio playback with synthetic fallback,
and turn-by-turn chat transcripts with per-turn latency telemetry and tool execution traces.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import streamlit as st

from src.agent.session_manager import CallSession, CallStatus, MessageRole
from src.config import settings
from src.dashboard.calls_data import (
    filter_call_sessions,
    load_all_call_sessions,
    resolve_call_audio,
    seed_demo_calls,
)
from src.dashboard.i18n import t

# ==============================================================================
# 1. Page Configuration
# ==============================================================================
st.set_page_config(
    page_title="Voice Agent — Call Logs | سجلات المكالمات",
    page_icon="📞",
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
        .header-container, .audio-header, .chat-meta {
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
        label=t("language_selector_label", lang),
        options=list(lang_options.values()),
        index=current_index,
        key="calls_lang_radio",
    )
    new_lang = "en" if "English" in selected_lang_label else "ar"
    if new_lang != st.session_state.lang:
        st.session_state.lang = new_lang
        st.rerun()

    st.markdown("---")
    st.markdown(f"### 🔍 {t('filter_status_label', lang)}")
    
    # Status Filter
    status_display_map = {
        "all": t("filter_status_all", lang),
        "active": t("filter_status_active", lang),
        "ended": t("filter_status_ended", lang),
        "escalated": t("filter_status_escalated", lang),
    }
    selected_status_display = st.selectbox(
        label=t("filter_status_label", lang),
        options=list(status_display_map.values()),
        index=0,
    )
    # Reverse lookup key
    selected_status = next(k for k, v in status_display_map.items() if v == selected_status_display)

    # Language Filter
    lang_display_map = {
        "all": t("filter_lang_all", lang),
        "ar": t("filter_lang_ar", lang),
        "en": t("filter_lang_en", lang),
    }
    selected_lang_filter_display = st.selectbox(
        label=t("filter_lang_label", lang),
        options=list(lang_display_map.values()),
        index=0,
    )
    selected_lang_filter = next(k for k, v in lang_display_map.items() if v == selected_lang_filter_display)

    # Search Query
    search_query = st.text_input(
        label=t("filter_search_label", lang),
        placeholder=t("filter_search_placeholder", lang),
    )

    st.markdown("---")
    # Quick action: Seed Demo Calls
    if st.button(f"🌱 {t('btn_reseed_demo', lang)}", use_container_width=True):
        seed_demo_calls()
        st.success(t("btn_reseed_success", lang))
        st.rerun()

# ==============================================================================
# 4. Data Loading & Filtering Pipeline
# ==============================================================================
all_sessions = load_all_call_sessions(auto_seed=True)
filtered_sessions = filter_call_sessions(
    sessions=all_sessions,
    status=selected_status,
    language=selected_lang_filter,
    search_query=search_query,
)

# ==============================================================================
# 5. Header Banner & KPI Summary
# ==============================================================================
st.markdown(
    f"""
    <div class="header-container">
        <div class="header-title-box">
            <h1>📞 {t('calls_page_title', lang)}</h1>
            <p>{t('calls_page_subtitle', lang)}</p>
        </div>
        <div>
            <div class="live-badge">
                <div class="pulse-dot"></div>
                <span>{len(filtered_sessions)} / {len(all_sessions)} {t('col_turns', lang)}</span>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Metric summary tiles
col1, col2, col3, col4 = st.columns(4)

total_calls_count = len(filtered_sessions)
active_count = sum(1 for s in filtered_sessions if s.status not in (CallStatus.ENDED, CallStatus.ESCALATED))
escalated_count = sum(1 for s in filtered_sessions if s.context.escalated or s.status == CallStatus.ESCALATED)
latencies = [s.metrics.average_latency_ms for s in filtered_sessions if s.metrics.average_latency_ms > 0]
avg_lat = round(sum(latencies) / len(latencies), 1) if latencies else 0.0

with col1:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{t('kpi_total_calls', lang)}</div>
            <div class="kpi-value" style="color: #A78BFA;">{total_calls_count}</div>
            <div class="kpi-subtext">📊 {t('filter_status_all', lang)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col2:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{t('kpi_active_calls', lang)}</div>
            <div class="kpi-value" style="color: #60A5FA;">{active_count}</div>
            <div class="kpi-subtext">📡 {t('filter_status_active', lang)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col3:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{t('kpi_handoff_rate', lang)}</div>
            <div class="kpi-value" style="color: {'#EF4444' if escalated_count > 0 else '#34D399'};">{escalated_count}</div>
            <div class="kpi-subtext">🚨 {t('filter_status_escalated', lang)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col4:
    lat_color = "#34D399" if avg_lat < 800 else "#FBBF24"
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{t('kpi_turn_latency', lang)}</div>
            <div class="kpi-value" style="color: {lat_color};">{avg_lat} ms</div>
            <div class="kpi-subtext">⚡ {t('kpi_turn_latency_sub', lang)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)

# ==============================================================================
# 6. Master Call History Table
# ==============================================================================
if not filtered_sessions:
    st.info(f"ℹ️ {t('no_calls_found_msg', lang)}")
else:
    # Build tabular view
    table_rows = []
    for s in filtered_sessions:
        # Determine status pill
        status_val = s.status.value.upper()
        if s.context.escalated or s.status == CallStatus.ESCALATED:
            status_display = "🚨 ESCALATED"
        elif s.status == CallStatus.ENDED:
            status_display = "✅ COMPLETED"
        else:
            status_display = "📡 ACTIVE"

        start_str = s.start_time.strftime("%Y-%m-%d %H:%M:%S")
        cust_display = s.context.customer_name or s.context.customer_phone or "Anonymous"
        lang_display = "🇸🇦 AR" if (s.context.language or "").lower() == "ar" else "🇺🇸 EN"
        dur_display = f"{int(s.metrics.duration_seconds)}s"
        avg_l = f"{round(s.metrics.average_latency_ms)}ms" if s.metrics.average_latency_ms > 0 else "N/A"

        table_rows.append({
            t("col_session_id", lang): s.session_id,
            t("col_timestamp", lang): start_str,
            t("col_customer", lang): cust_display,
            t("col_status", lang): status_display,
            t("col_language", lang): lang_display,
            t("col_duration", lang): dur_display,
            t("col_turns", lang): len(s.messages),
            t("col_tools", lang): s.metrics.total_tool_calls,
            t("col_avg_latency", lang): avg_l,
        })

    st.dataframe(
        table_rows,
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("---")

    # ==========================================================================
    # 7. Deep-Dive Call Inspector
    # ==========================================================================
    st.markdown(f"### 🔎 {t('detail_header_title', lang)}")
    
    # Session Selector
    session_options = {
        s.session_id: f"{s.session_id} • {s.context.customer_name or s.context.customer_phone or 'Unknown'} • [{s.status.value.upper()}]"
        for s in filtered_sessions
    }
    
    selected_session_id = st.selectbox(
        label=t("detail_select_prompt", lang),
        options=list(session_options.keys()),
        format_func=lambda sid: session_options.get(sid, sid),
        key="selected_call_session",
    )

    selected_session: Optional[CallSession] = next(
        (s for s in filtered_sessions if s.session_id == selected_session_id), None
    )

    if selected_session:
        # Escalation Alert Banner
        if selected_session.context.escalated or selected_session.status == CallStatus.ESCALATED:
            esc_reason = selected_session.context.escalation_reason or "Customer requested direct supervisor assistance"
            esc_dept = selected_session.context.escalation_department or "Customer Care"
            st.markdown(
                f"""
                <div class="escalation-banner">
                    <span style="font-size: 1.5rem;">🚨</span>
                    <div>
                        <div>{t('detail_escalated_banner', lang)}</div>
                        <div style="font-size: 0.85rem; opacity: 0.9; margin-top: 3px;">
                            <strong>{t('detail_escalation_dept', lang)}:</strong> {esc_dept} &nbsp;|&nbsp; 
                            <strong>{t('detail_escalation_reason', lang)}:</strong> {esc_reason}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # Overview Metadata Columns
        meta_col1, meta_col2 = st.columns([1, 1])

        with meta_col1:
            st.markdown(f"#### 👤 {t('detail_customer_card_title', lang)}")
            cust_name = selected_session.context.customer_name or "N/A"
            cust_phone = selected_session.context.customer_phone or "N/A"
            order_ref = selected_session.context.order_id or "N/A"
            sentiment_val = selected_session.context.sentiment.capitalize()
            
            pills_html = f"""
            <div>
                <span class="slot-pill">👤 <strong>{t('detail_customer_name', lang)}:</strong> {cust_name}</span>
                <span class="slot-pill">📱 <strong>{t('detail_customer_phone', lang)}:</strong> {cust_phone}</span>
                <span class="slot-pill">📦 <strong>{t('detail_order_id', lang)}:</strong> {order_ref}</span>
                <span class="slot-pill">🎭 <strong>{t('detail_sentiment', lang)}:</strong> {sentiment_val}</span>
            </div>
            """
            st.markdown(pills_html, unsafe_allow_html=True)

            if selected_session.context.allergies or selected_session.context.dietary_preferences:
                allergies_str = ", ".join(selected_session.context.allergies + selected_session.context.dietary_preferences)
                st.markdown(
                    f"""<div style="margin-top: 6px;"><span class="slot-pill" style="border-color: #FBBF24; color: #FDE68A;">
                    🥗 <strong>{t('detail_allergies', lang)}:</strong> {allergies_str}</span></div>""",
                    unsafe_allow_html=True,
                )

            if selected_session.context.reservation_draft:
                res_draft = selected_session.context.reservation_draft
                res_str = f"Date: {res_draft.get('date', 'N/A')} {res_draft.get('time', '')} | Guests: {res_draft.get('party_size') or res_draft.get('guests', 'N/A')} | Table: {res_draft.get('table', 'Confirmed')}"
                st.markdown(
                    f"""<div style="margin-top: 6px;"><span class="slot-pill" style="border-color: #60A5FA; color: #93C5FD;">
                    📅 <strong>{t('detail_reservation', lang)}:</strong> {res_str}</span></div>""",
                    unsafe_allow_html=True,
                )

        with meta_col2:
            st.markdown(f"#### 🔊 {t('audio_player_title', lang)}")
            audio_source, is_demo = resolve_call_audio(selected_session.session_id)
            
            audio_badge_class = "demo-audio-tag" if is_demo else "real-audio-tag"
            audio_badge_text = t("audio_player_demo_badge", lang) if is_demo else t("audio_player_real_badge", lang)
            
            st.markdown(
                f"""
                <div class="audio-card">
                    <div class="audio-header">
                        <span style="font-weight: 600; font-size: 0.9rem;">{selected_session.session_id}.wav</span>
                        <span class="{audio_badge_class}">{audio_badge_text}</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if isinstance(audio_source, (bytes, bytearray)):
                st.audio(audio_source, format="audio/wav")
            else:
                st.audio(str(audio_source))

        st.markdown("<br>", unsafe_allow_html=True)

        # ======================================================================
        # 8. Interactive Chat Transcript View
        # ======================================================================
        st.markdown(f"### 💬 {t('transcript_section_title', lang)}")
        
        if not selected_session.messages:
            st.info(t("empty_transcript_msg", lang))
        else:
            for idx, msg in enumerate(selected_session.messages):
                ts_str = msg.timestamp.strftime("%H:%M:%S")
                
                # Turn direction logic: Arabic text receives RTL direction
                is_msg_ar = any("\u0600" <= c <= "\u06FF" for c in msg.content)
                text_dir = 'dir="rtl" style="text-align: right;"' if is_msg_ar else 'dir="ltr"'

                if msg.role == MessageRole.USER:
                    st.markdown(
                        f"""
                        <div class="chat-turn chat-turn-user" {text_dir}>
                            <div class="chat-meta">
                                <span>👤 <strong>{t('role_caller', lang)}</strong></span>
                                <span>•</span>
                                <span>{ts_str}</span>
                                {f'<span class="turn-tag">STT: {round(msg.stt_latency_ms)}ms</span>' if msg.stt_latency_ms else ''}
                            </div>
                            <div class="chat-bubble chat-bubble-user">
                                {msg.content}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                elif msg.role == MessageRole.ASSISTANT:
                    # Collect latency badges
                    lat_badges = []
                    if msg.latency_ms:
                        lat_badges.append(f'<span class="turn-tag" style="color: #34D399;">Total: {round(msg.latency_ms)}ms</span>')
                    if msg.llm_latency_ms:
                        lat_badges.append(f'<span class="turn-tag">LLM: {round(msg.llm_latency_ms)}ms</span>')
                    if msg.tts_latency_ms:
                        lat_badges.append(f'<span class="turn-tag">TTS: {round(msg.tts_latency_ms)}ms</span>')
                    if msg.interrupted:
                        lat_badges.append(f'<span class="turn-tag turn-interrupted">{t("interrupted_badge", lang)}</span>')

                    badge_html = " ".join(lat_badges)

                    st.markdown(
                        f"""
                        <div class="chat-turn chat-turn-assistant" {text_dir}>
                            <div class="chat-meta">
                                <span>🎙️ <strong>{t('role_assistant', lang)}</strong></span>
                                <span>•</span>
                                <span>{ts_str}</span>
                                {badge_html}
                            </div>
                            <div class="chat-bubble chat-bubble-assistant">
                                {msg.content}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                elif msg.role == MessageRole.TOOL:
                    tool_label = msg.tool_name or "tool"
                    with st.expander(f"⚙️ {t('role_tool', lang)}: `{tool_label}`", expanded=False):
                        if msg.tool_arguments:
                            st.caption(f"**{t('tool_args_title', lang)}:**")
                            st.json(msg.tool_arguments)
                        if msg.tool_result:
                            st.caption(f"**{t('tool_result_title', lang)}:**")
                            st.json(msg.tool_result)
                        elif msg.content:
                            st.write(msg.content)

# ==============================================================================
# 9. Global Footer
# ==============================================================================
st.markdown(
    f"""
    <div class="footer-text">
        {t('footer_text', lang)}
    </div>
    """,
    unsafe_allow_html=True,
)
