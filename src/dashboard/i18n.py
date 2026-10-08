"""
Internationalization (i18n) Module for Voice Agent Dashboard.

Supports English (en) and Arabic (ar) with clean fallback and structured dictionary keys.
"""

from typing import Dict, Any

TRANSLATIONS: Dict[str, Dict[str, str]] = {
    "en": {
        # App Header
        "app_title": "Voice AI Agent Operations",
        "app_subtitle": "Restaurant Customer Service & Real-Time Voice Intelligence",
        "agent_status_ready": "Agent Pipeline Active",
        "agent_status_offline": "Agent Pipeline Paused",
        
        # KPI Cards
        "kpi_turn_latency": "Turn Latency (Avg)",
        "kpi_turn_latency_sub": "SLA Budget: < 800ms",
        "kpi_active_calls": "Active Voice Calls",
        "kpi_active_calls_sub": "Live WebRTC Sessions",
        "kpi_total_calls": "Calls Handled Today",
        "kpi_total_calls_sub": "100% Automated Logging",
        "kpi_handoff_rate": "Human Escalation",
        "kpi_handoff_rate_sub": "Target: < 5%",
        
        # Service Health Section
        "health_section_title": "Cloud Infrastructure & Subsystem Health",
        "health_section_desc": "Real-time connectivity and credential verification for connected AI providers.",
        "service_livekit": "LiveKit Cloud",
        "service_livekit_sub": "WebRTC Media Server & Room Worker",
        "service_qdrant": "Qdrant Vector DB",
        "service_qdrant_sub": "RAG Domain Knowledge Index",
        "service_groq": "Groq Cloud (Llama 3.3)",
        "service_groq_sub": "Ultra-Low Latency LLM Reasoning",
        "service_elevenlabs": "ElevenLabs TTS",
        "service_elevenlabs_sub": "Streaming Neural Voice Synthesis",
        "service_deepgram": "Deepgram STT",
        "service_deepgram_sub": "Nova-3 Streaming Multilingual ASR",
        
        # Status Badges
        "status_operational": "Operational",
        "status_degraded": "Degraded / Local",
        "status_unconfigured": "Not Configured",
        "status_offline": "Offline",
        
        # Quick Navigation
        "nav_section_title": "Operations & Analytics Modules",
        "nav_section_desc": "Access detailed call recordings, latency telemetry, RAG knowledge base, and agent configuration.",
        "nav_calls_title": "Call Logs & Audio",
        "nav_calls_desc": "Review live transcripts, caller intent tags, tool execution traces, and listen to synthesized call audio.",
        "nav_analytics_title": "Latency & Metrics",
        "nav_analytics_desc": "Interactive Plotly analytics for STT, LLM, and TTS latency breakdowns, peak call hours, and volume trends.",
        "nav_knowledge_title": "Knowledge Base & Menu",
        "nav_knowledge_desc": "Manage restaurant menus, dietary ingredients, branch policies, and trigger on-demand vector ingestion.",
        "nav_settings_title": "Prompts & Settings",
        "nav_settings_desc": "Live prompt engineering playground, temperature adjustments, voice ID selection, and system environment config.",
        
        # Sidebar & Controls
        "sidebar_settings_title": "Dashboard Preferences",
        "language_selector_label": "Interface Language / لغة العرض",
        "sidebar_info_title": "System Information",
        "sidebar_agent_persona": "Persona",
        "sidebar_restaurant_name": "Restaurant",
        "sidebar_version": "Dashboard Version",
        "sidebar_refresh_btn": "Refresh Live Health",
        
        # Call Logs & Transcripts (Feature 5.2)
        "calls_page_title": "Voice Call Logs & Audio Recordings",
        "calls_page_subtitle": "Inspect real-time conversation transcripts, audio playback, tool executions, and latency metrics.",
        "filter_status_label": "Call Status",
        "filter_status_all": "All Statuses",
        "filter_status_active": "Active Calls",
        "filter_status_ended": "Completed",
        "filter_status_escalated": "Escalated",
        "filter_lang_label": "Call Language",
        "filter_lang_all": "All Languages",
        "filter_lang_ar": "Arabic",
        "filter_lang_en": "English",
        "filter_search_label": "Search (ID, Phone, Name, Order)",
        "filter_search_placeholder": "Type order ID, phone, or caller name...",
        "btn_reseed_demo": "Seed Sample Calls",
        "btn_reseed_success": "Demo calls generated successfully!",
        "col_session_id": "Session ID",
        "col_timestamp": "Time",
        "col_customer": "Customer",
        "col_status": "Status",
        "col_language": "Language",
        "col_duration": "Duration",
        "col_turns": "Turns",
        "col_avg_latency": "Avg Latency",
        "col_tools": "Tools",
        "detail_select_prompt": "Select Call to Inspect",
        "detail_header_title": "Call Deep-Dive Inspection",
        "detail_escalated_banner": "⚠️ Escalated Call: Transferred to Human Supervisor",
        "detail_customer_card_title": "Customer & Context Profile",
        "detail_customer_name": "Customer Name",
        "detail_customer_phone": "Phone Number",
        "detail_order_id": "Order Reference",
        "detail_sentiment": "Sentiment",
        "detail_allergies": "Allergies & Dietary",
        "detail_reservation": "Reservation Draft",
        "detail_escalation_reason": "Escalation Reason",
        "detail_escalation_dept": "Department",
        "audio_player_title": "Call Audio Recording",
        "audio_player_demo_badge": "Demo Audio Preview (Simulated Tone)",
        "audio_player_real_badge": "Recorded Call Audio",
        "transcript_section_title": "Turn-by-Turn Conversation Transcript",
        "role_caller": "Caller",
        "role_assistant": "AI Voice Agent",
        "role_tool": "Tool Execution",
        "interrupted_badge": "⚡ Interrupted",
        "turn_latency": "Turn Latency",
        "tool_args_title": "Input Arguments",
        "tool_result_title": "Execution Output",
        "empty_transcript_msg": "No conversation turns recorded for this session.",
        "no_calls_found_msg": "No calls matching the current filters.",
        
        # Footer
        "footer_text": "Production Voice AI Agent Platform • Built with LiveKit, Deepgram, Groq, ElevenLabs & Qdrant",
    },
    "ar": {
        # App Header
        "app_title": "مركز عمليات المساعد الصوتي الذكي",
        "app_subtitle": "خدمة عملاء المطاعم والتوصيل بالذكاء الاصطناعي الصوتي الفوري",
        "agent_status_ready": "خط المعالجة الصوتي نشط وجاهز",
        "agent_status_offline": "خط المعالجة الصوتي متوقف مؤقتاً",
        
        # KPI Cards
        "kpi_turn_latency": "متوسط زمن الاستجابة",
        "kpi_turn_latency_sub": "المستهدف القياسي: أقل من 800ms",
        "kpi_active_calls": "المكالمات الصوتية النشطة",
        "kpi_active_calls_sub": "جلسات WebRTC المباشرة",
        "kpi_total_calls": "إجمالي مكالمات اليوم",
        "kpi_total_calls_sub": "تسجيل وأرشفة آلية 100%",
        "kpi_handoff_rate": "نسبة التحويل لمشرف بشري",
        "kpi_handoff_rate_sub": "المستهدف: أقل من 5%",
        
        # Service Health Section
        "health_section_title": "حالة البنية التحتية والأنظمة الفرعية",
        "health_section_desc": "فحص لحظي مباشر للاتصال ومفاتيح الربط لمزودي خدمات الذكاء الاصطناعي.",
        "service_livekit": "خادم LiveKit السحابي",
        "service_livekit_sub": "خادم بث الصوت WebRTC وإدارة الجلسات",
        "service_qdrant": "قاعدة بيانات Qdrant الشعاعية",
        "service_qdrant_sub": "فهرس استرجاع المعرفة وقوائم الطعام",
        "service_groq": "خادم Groq السحابي (Llama 3.3)",
        "service_groq_sub": "استدلال فائق السرعة للنموذج اللغوي",
        "service_elevenlabs": "توليد الصوت ElevenLabs TTS",
        "service_elevenlabs_sub": "تحويل النص إلى كلام صوتي طبيعي متدفق",
        "service_deepgram": "التعرف الصوتي Deepgram STT",
        "service_deepgram_sub": "نموذج Nova-3 للتعرف اللحظي متعدد اللغات",
        
        # Status Badges
        "status_operational": "يعمل بكفاءة",
        "status_degraded": "محدود / محلي",
        "status_unconfigured": "غير مهيأ",
        "status_offline": "غير متصل",
        
        # Quick Navigation
        "nav_section_title": "أقسام العمليات والتحليلات",
        "nav_section_desc": "الوصول السريع لسجلات المكالمات، تحليلات زمن الاستجابة، قاعدة المعرفة، وإعدادات الوكيل.",
        "nav_calls_title": "سجلات المكالمات والتسجيلات",
        "nav_calls_desc": "استعراض النصوص الحية، نوايا المتصلين، مسار استدعاء الأدوات، والاستماع للتسجيل الصوتي.",
        "nav_analytics_title": "تحليلات الأداء والأزمنة",
        "nav_analytics_desc": "مخططات بيانية تفاعلية لتوزيع أزمنة STT و LLM و TTS، ساعات الذروة، وحجم المكالمات.",
        "nav_knowledge_title": "قاعدة المعرفة وقائمة الطعام",
        "nav_knowledge_desc": "إدارة قوائم الطعام، المكونات، مسببات الحساسية، وسياسات الفروع، وتحديث الفهرس الشعاعي.",
        "nav_settings_title": "مختبر التعليمات والإعدادات",
        "nav_settings_desc": "تعديل وتجربة التوجيهات الفورية (Prompts)، ضبط درجات الحرارة، واختيار هوية الصوت.",
        
        # Sidebar & Controls
        "sidebar_settings_title": "تفضيلات لوحة التحكم",
        "language_selector_label": "لغة العرض / Interface Language",
        "sidebar_info_title": "معلومات النظام",
        "sidebar_agent_persona": "هوية المساعد",
        "sidebar_restaurant_name": "اسم المطعم",
        "sidebar_version": "إصدار اللوحة",
        "sidebar_refresh_btn": "تحديث فحص الحالة الآن",
        
        # Call Logs & Transcripts (Feature 5.2)
        "calls_page_title": "سجلات المكالمات والتسجيلات الصوتية",
        "calls_page_subtitle": "متابعة وتدقيق نصوص المحادثات الحية، الاستماع للتسجيلات، تتبع استدعاء الأدوات وأزمنة الاستجابة.",
        "filter_status_label": "حالة المكالمة",
        "filter_status_all": "جميع الحالات",
        "filter_status_active": "مكالمات جارية",
        "filter_status_ended": "مكتملة بنجاح",
        "filter_status_escalated": "محولة لمشرف",
        "filter_lang_label": "لغة المكالمة",
        "filter_lang_all": "جميع اللغات",
        "filter_lang_ar": "العربية",
        "filter_lang_en": "الإنجليزية",
        "filter_search_label": "بحث (المعرف، الهاتف، الاسم، الطلب)",
        "filter_search_placeholder": "اكتب رقم الطلب، الهاتف، أو اسم المتصل...",
        "btn_reseed_demo": "توليد مكالمات تجريبية",
        "btn_reseed_success": "تم توليد المكالمات التجريبية بنجاح!",
        "col_session_id": "معرّف الجلسة",
        "col_timestamp": "التوقيت",
        "col_customer": "العميل",
        "col_status": "الحالة",
        "col_language": "اللغة",
        "col_duration": "المدة",
        "col_turns": "الأدوار",
        "col_avg_latency": "متوسط الاستجابة",
        "col_tools": "الأدوات",
        "detail_select_prompt": "اختر المكالمة المراد تدقيقها",
        "detail_header_title": "تفاصيل وتدقيق المكالمة",
        "detail_escalated_banner": "⚠️ مكالمة مصعدة: تم تحويلها لمشرف بشري",
        "detail_customer_card_title": "ملف العميل وسياق المكالمة",
        "detail_customer_name": "اسم المتصل",
        "detail_customer_phone": "رقم الهاتف",
        "detail_order_id": "رقم الطلب",
        "detail_sentiment": "انطباع المتصل",
        "detail_allergies": "الحساسية والتفضيلات",
        "detail_reservation": "بيانات الحجز",
        "detail_escalation_reason": "سبب التصعيد",
        "detail_escalation_dept": "القسم المحول إليه",
        "audio_player_title": "التسجيل الصوتي للمكالمة",
        "audio_player_demo_badge": "عينة صوتية تجريبية (نغمة محاكاة)",
        "audio_player_real_badge": "تسجيل صوتي فعلي للمكالمة",
        "transcript_section_title": "نص المحادثة خطوة بخطوة",
        "role_caller": "المتصل",
        "role_assistant": "الوكيل الصوتي الذكي",
        "role_tool": "استدعاء أداة",
        "interrupted_badge": "⚡ تمت المقاطعة",
        "turn_latency": "زمن الدور",
        "tool_args_title": "المدخلات المرسلة",
        "tool_result_title": "المخرجات والنتيجة",
        "empty_transcript_msg": "لا توجد أدوار مسجلة لهذه الجلسة.",
        "no_calls_found_msg": "لا توجد مكالمات مطابقة لمعايير الفلترة الحالية.",
        
        # Footer
        "footer_text": "منصة الوكيل الصوتي للإنتاج • مبنية بتقنيات LiveKit و Deepgram و Groq و ElevenLabs و Qdrant",
    },
}


def t(key: str, lang: str = "en") -> str:
    """
    Retrieve localized string for a given key.
    
    Args:
        key: Translation key identifier.
        lang: Target language ('en' or 'ar'). Defaults to 'en'.
        
    Returns:
        Translated string, or key if translation is missing.
    """
    selected_lang = lang if lang in TRANSLATIONS else "en"
    catalog = TRANSLATIONS.get(selected_lang, {})
    return catalog.get(key, TRANSLATIONS["en"].get(key, key))
