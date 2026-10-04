"""
Voice AI Agent — Main Operations Dashboard.

Production Streamlit dashboard entry point with modern dark theme,
bilingual support (EN/AR), real-time service health monitoring, and KPI telemetry.
"""

import os
from pathlib import Path
import streamlit as st

from src.config import settings
from src.dashboard.i18n import t
from src.dashboard.health import check_services_health

# 1. Page Configuration (Must be first Streamlit call)
st.set_page_config(
    page_title="Voice Agent Ops | لوحة تحكم الوكيل الصوتي",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 2. State & Language Initialization
if "lang" not in st.session_state:
    st.session_state.lang = "en"

# 3. Load & Inject Custom Design System CSS
CSS_PATH = Path(__file__).parent / "assets" / "style.css"
if CSS_PATH.exists():
    with open(CSS_PATH, "r", encoding="utf-8") as f:
        custom_css = f.read()
    st.markdown(f"<style>{custom_css}</style>", unsafe_allow_html=True)

# Apply RTL layout if Arabic is selected
is_arabic = st.session_state.lang == "ar"
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
        .header-container {
            flex-direction: row-reverse;
        }
        .service-health-card {
            flex-direction: row-reverse;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

lang = st.session_state.lang


# 4. Sidebar Controls & System Telemetry
with st.sidebar:
    st.markdown(f"### ⚙️ {t('sidebar_settings_title', lang)}")
    
    # Language Toggle Selector
    lang_options = {"en": "English 🇺🇸", "ar": "العربية 🇸🇦"}
    current_index = 0 if lang == "en" else 1
    selected_lang_label = st.radio(
        label=t("language_selector_label", lang),
        options=list(lang_options.values()),
        index=current_index,
        key="lang_radio",
    )
    
    # Update session state language based on selection
    new_lang = "en" if "English" in selected_lang_label else "ar"
    if new_lang != st.session_state.lang:
        st.session_state.lang = new_lang
        st.rerun()

    st.markdown("---")
    st.markdown(f"### ℹ️ {t('sidebar_info_title', lang)}")
    st.markdown(f"**{t('sidebar_agent_persona', lang)}:** `{settings.agent_name}`")
    st.markdown(f"**{t('sidebar_restaurant_name', lang)}:** `{settings.restaurant_name}`")
    st.markdown(f"**{t('sidebar_version', lang)}:** `v0.1.0-prod`")
    
    st.markdown("---")
    if st.button(f"🔄 {t('sidebar_refresh_btn', lang)}", use_container_width=True):
        st.rerun()


# 5. Header Banner & Live Status Pulse
st.markdown(
    f"""
    <div class="header-container">
        <div class="header-title-box">
            <h1>🎙️ {t('app_title', lang)}</h1>
            <p>{t('app_subtitle', lang)}</p>
        </div>
        <div>
            <div class="live-badge">
                <div class="pulse-dot"></div>
                <span>{t('agent_status_ready', lang)}</span>
            </div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# 6. Top Overview KPI Cards
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{t('kpi_turn_latency', lang)}</div>
            <div class="kpi-value" style="color: #34D399;">680 ms</div>
            <div class="kpi-subtext">⚡ {t('kpi_turn_latency_sub', lang)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col2:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{t('kpi_active_calls', lang)}</div>
            <div class="kpi-value" style="color: #60A5FA;">3</div>
            <div class="kpi-subtext">📡 {t('kpi_active_calls_sub', lang)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col3:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{t('kpi_total_calls', lang)}</div>
            <div class="kpi-value" style="color: #A78BFA;">142</div>
            <div class="kpi-subtext">📊 {t('kpi_total_calls_sub', lang)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col4:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{t('kpi_handoff_rate', lang)}</div>
            <div class="kpi-value" style="color: #FBBF24;">2.8%</div>
            <div class="kpi-subtext">🎯 {t('kpi_handoff_rate_sub', lang)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("<br>", unsafe_allow_html=True)


# 7. Real-Time Service Health & Provider Connectivity
st.markdown(f"### 🛡️ {t('health_section_title', lang)}")
st.caption(t('health_section_desc', lang))

services_health = check_services_health()
health_cols = st.columns(2)

services_list = list(services_health.items())
for idx, (svc_key, svc_info) in enumerate(services_list):
    col_target = health_cols[idx % 2]
    with col_target:
        st.markdown(
            f"""
            <div class="service-health-card">
                <div>
                    <div class="service-name">{t(svc_info['name_key'], lang)}</div>
                    <div class="service-details">{t(svc_info['sub_key'], lang)} • {svc_info['details']}</div>
                </div>
                <div class="{svc_info['badge_class']}">
                    {t(svc_info['badge_key'], lang)}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)


# 8. Operational Navigation Modules
st.markdown(f"### 🚀 {t('nav_section_title', lang)}")
st.caption(t('nav_section_desc', lang))

nav1, nav2, nav3, nav4 = st.columns(4)

with nav1:
    st.markdown(
        f"""
        <div class="nav-card">
            <div class="nav-card-icon">📞</div>
            <div class="nav-card-title">{t('nav_calls_title', lang)}</div>
            <div class="nav-card-desc">{t('nav_calls_desc', lang)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with nav2:
    st.markdown(
        f"""
        <div class="nav-card">
            <div class="nav-card-icon">📊</div>
            <div class="nav-card-title">{t('nav_analytics_title', lang)}</div>
            <div class="nav-card-desc">{t('nav_analytics_desc', lang)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with nav3:
    st.markdown(
        f"""
        <div class="nav-card">
            <div class="nav-card-icon">📚</div>
            <div class="nav-card-title">{t('nav_knowledge_title', lang)}</div>
            <div class="nav-card-desc">{t('nav_knowledge_desc', lang)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with nav4:
    st.markdown(
        f"""
        <div class="nav-card">
            <div class="nav-card-icon">⚙️</div>
            <div class="nav-card-title">{t('nav_settings_title', lang)}</div>
            <div class="nav-card-desc">{t('nav_settings_desc', lang)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# 9. Global Footer
st.markdown(
    f"""
    <div class="footer-text">
        {t('footer_text', lang)}
    </div>
    """,
    unsafe_allow_html=True,
)
