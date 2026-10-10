"""
Analytics Data Aggregation, KPI Telemetry & Historical Call Seeder.

Provides statistical aggregation for voice latency (STT/LLM/TTS), SLA compliance,
time-series volume bucketing (hourly/daily), sentiment and tool invocation analytics,
and automated multi-day call session seeding for rich dashboard visualizations.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from src.agent.session_manager import (
    CallSession,
    CallStatus,
    MessageRole,
    SessionManager,
)

logger = logging.getLogger(__name__)

# Constitutional SLA Thresholds (from spec/tech.md)
SLA_BUDGET_TOTAL_MS: float = 800.0
SLA_BUDGET_STT_MS: float = 200.0
SLA_BUDGET_LLM_MS: float = 300.0
SLA_BUDGET_TTS_MS: float = 250.0


# ==============================================================================
# 1. 7-Day Time-Distributed Analytics Call Seeder
# ==============================================================================

def seed_analytics_call_sessions(
    storage_dir: str | Path | None = None,
    min_threshold: int = 10,
) -> list[CallSession]:
    """
    Generate realistic, time-distributed mock call sessions spanning the last 7 days.
    Triggered when stored call records are fewer than min_threshold to ensure
    analytics charts render rich, production-grade visual trends immediately.
    
    Args:
        storage_dir: Storage directory for persisted JSON call records.
        min_threshold: Minimum sessions required before seeding is skipped.
        
    Returns:
        List of newly seeded CallSession objects.
    """
    mgr = SessionManager(storage_dir=storage_dir or "data/calls")
    existing = mgr.load_all_persisted_sessions()
    
    if len(existing) >= min_threshold:
        return existing

    seeded: list[CallSession] = []
    now = datetime.now(timezone.utc)

    # Scenarios template pool
    scenarios = [
        {
            "lang": "ar",
            "name": "أحمد الشمري",
            "phone": "+966501112233",
            "order_id": "ORD-7801",
            "sentiment": "positive",
            "tool": "check_order_status",
            "tool_args": {"order_id": "ORD-7801"},
            "tool_res": {"order_id": "ORD-7801", "status": "out_for_delivery", "courier": "خالد"},
            "user_text": "مرحباً، أود معرفة أين وصل طلبي رقم 7801؟",
            "agent_text": "أهلاً بك يا أحمد. طلبك في الطريق مع الكابتن خالد وسيصلك خلال 10 دقائق.",
            "escalated": False,
        },
        {
            "lang": "en",
            "name": "David Miller",
            "phone": "+14155553819",
            "order_id": None,
            "sentiment": "positive",
            "tool": "book_reservation",
            "tool_args": {"date": "2026-10-12", "time": "19:30", "party_size": 2},
            "tool_res": {"reservation_id": "RES-5102", "table": "Patio #4", "status": "confirmed"},
            "user_text": "Hi, I'd like to book a table for 2 tomorrow evening around 7:30 PM.",
            "agent_text": "Certainly David! I have reserved patio table #4 for you tomorrow at 7:30 PM. Reference RES-5102.",
            "escalated": False,
        },
        {
            "lang": "ar",
            "name": "فاطمة القحطاني",
            "phone": "+966542223344",
            "order_id": None,
            "sentiment": "neutral",
            "tool": "search_knowledge_base",
            "tool_args": {"query": "قائمة طعام خالية من الجلوتين"},
            "tool_res": {"query": "قائمة خالية من الجلوتين", "results_count": 3},
            "user_text": "هل لديكم خيارات بيتزا خالية من الجلوتين في فرع التحلية؟",
            "agent_text": "نعم يا فاطمة، تتوفر لدينا بيتزا مارغريتا بعجينة خالية من الجلوتين بالإضافة لسلطات الكينوا.",
            "escalated": False,
        },
        {
            "lang": "en",
            "name": "Emma Watson",
            "phone": "+12125559812",
            "order_id": "ORD-9204",
            "sentiment": "negative",
            "tool": "escalate_to_human",
            "tool_args": {"reason": "Missing items in delivery"},
            "tool_res": {"escalated": True, "department": "Customer Relations"},
            "user_text": "My food arrived cold and half the order is missing! I demand to speak to a supervisor.",
            "agent_text": "I truly apologize for this bad experience Emma. Transferring you immediately to a duty supervisor.",
            "escalated": True,
        },
        {
            "lang": "ar",
            "name": "سعد الدوسري",
            "phone": "+966567778899",
            "order_id": "ORD-3312",
            "sentiment": "positive",
            "tool": "check_order_status",
            "tool_args": {"order_id": "ORD-3312"},
            "tool_res": {"order_id": "ORD-3312", "status": "delivered"},
            "user_text": "السلام عليكم، هل تم تسليم الطلب بالاستقبال؟",
            "agent_text": "وعليكم السلام يا سعد، نعم تم تأكيد التسليم في الاستقبال قبل دقيقتين. بالهناء والعافية!",
            "escalated": False,
        },
        {
            "lang": "en",
            "name": "Robert Chen",
            "phone": "+14155554499",
            "order_id": None,
            "sentiment": "neutral",
            "tool": "search_knowledge_base",
            "tool_args": {"query": "outdoor seating and pets"},
            "tool_res": {"query": "pet friendly patio", "results_count": 2},
            "user_text": "Hello, do you allow small dogs on your outdoor terrace?",
            "agent_text": "Yes Robert! Our outdoor terrace welcomes pets, and we even offer fresh water bowls upon request.",
            "escalated": False,
        },
    ]

    # Generate calls distributed over the past 7 days across lunch (12-15) and dinner (19-22) hours
    call_idx = 1
    for day_offset in range(6, -1, -1):
        target_date = now - timedelta(days=day_offset)
        
        # 2 to 3 calls per day
        daily_call_count = 3 if day_offset in (0, 1, 5, 6) else 2
        for i in range(daily_call_count):
            sc = scenarios[(call_idx - 1) % len(scenarios)]
            
            # Select rush hour hour: Lunch (12:00-14:30) or Dinner (19:00-22:00)
            hour = 13 if i == 0 else (20 if i == 1 else 14)
            minute = (i * 19 + day_offset * 7) % 55
            call_time = target_date.replace(hour=hour, minute=minute, second=15)
            
            # Simulate realistic SLA-aligned latency (mostly <800ms, occasionally breach for realistic analytics)
            is_sla_breach = (call_idx % 9 == 0)
            if is_sla_breach:
                stt_lat = 210.0 + (call_idx % 20)
                llm_lat = 380.0 + (call_idx % 40)
                tts_lat = 290.0 + (call_idx % 30)
                tot_lat = stt_lat + llm_lat + tts_lat
            else:
                stt_lat = 140.0 + (call_idx % 45)
                llm_lat = 220.0 + (call_idx % 55)
                tts_lat = 180.0 + (call_idx % 40)
                tot_lat = stt_lat + llm_lat + tts_lat

            session_id = f"call-seed-{day_offset}d-{i+1:02d}-{uuid.uuid4().hex[:6]}"
            session = mgr.create_session(
                session_id=session_id,
                room_name=f"restaurant-room-{sc['lang']}-{call_idx:03d}",
                participant_identity=f"caller-{call_idx:03d}",
                language=sc["lang"],
                customer_phone=sc["phone"],
            )
            session.start_time = call_time
            session.context.customer_name = sc["name"]
            session.context.sentiment = sc["sentiment"]
            session.context.order_id = sc["order_id"]
            session.context.escalated = sc["escalated"]
            if sc["escalated"]:
                session.context.escalation_reason = "Customer requested human supervisor"
                session.context.escalation_department = "Support Desk"

            # Add turns
            session.add_turn(
                role=MessageRole.USER,
                content=sc["user_text"],
                stt_latency_ms=stt_lat,
            )
            session.add_turn(
                role=MessageRole.ASSISTANT,
                content=sc["agent_text"],
                latency_ms=tot_lat,
                llm_latency_ms=llm_lat,
                tts_latency_ms=tts_lat,
            )
            if sc["tool"]:
                session.add_turn(
                    role=MessageRole.TOOL,
                    content=str(sc["tool_res"]),
                    tool_name=sc["tool"],
                    tool_arguments=sc["tool_args"],
                    tool_result=sc["tool_res"],
                )

            duration = 45.0 + (call_idx * 7) % 65
            session.end_time = session.start_time + timedelta(seconds=duration)
            session.status = CallStatus.ESCALATED if sc["escalated"] else CallStatus.ENDED
            session.metrics.duration_seconds = duration

            mgr.save_session(session.session_id)
            seeded.append(session)
            call_idx += 1

    logger.info(f"Successfully seeded {len(seeded)} time-distributed analytics calls across 7 days")
    return seeded


# ==============================================================================
# 2. Filtering Utilities
# ==============================================================================

def filter_by_time_range(
    sessions: list[CallSession],
    time_range: str = "7d",
    reference_time: datetime | None = None,
) -> list[CallSession]:
    """
    Filter call sessions by a rolling time window.
    
    Args:
        sessions: Source list of CallSession objects.
        time_range: Window string: '24h', '7d', '30d', or 'all'.
        reference_time: Optional reference datetime (defaults to UTC now).
        
    Returns:
        Filtered list of CallSession objects within the specified window.
    """
    if time_range == "all":
        return sessions

    now = reference_time or datetime.now(timezone.utc)
    
    if time_range == "24h":
        cutoff = now - timedelta(hours=24)
    elif time_range == "7d":
        cutoff = now - timedelta(days=7)
    elif time_range == "30d":
        cutoff = now - timedelta(days=30)
    else:
        cutoff = now - timedelta(days=7)

    return [s for s in sessions if s.start_time >= cutoff]


def filter_analytics_sessions(
    sessions: list[CallSession],
    time_range: str = "7d",
    language: str | None = None,
    status: str | None = None,
) -> list[CallSession]:
    """
    Apply combined filtering for analytics views: time range, language, and call status.
    """
    # 1. Time range filter
    filtered = filter_by_time_range(sessions, time_range=time_range)

    # 2. Language filter
    if language and language.lower() != "all":
        target_lang = language.lower()
        filtered = [s for s in filtered if (s.context.language or "en").lower() == target_lang]

    # 3. Status filter
    if status and status.lower() != "all":
        target_status = status.lower()
        if target_status == "escalated":
            filtered = [s for s in filtered if s.context.escalated or s.status == CallStatus.ESCALATED]
        elif target_status == "completed":
            filtered = [s for s in filtered if s.status == CallStatus.ENDED and not s.context.escalated]
        elif target_status == "active":
            filtered = [s for s in filtered if s.status not in (CallStatus.ENDED, CallStatus.ESCALATED)]

    return filtered


# ==============================================================================
# 3. KPI & Statistical Aggregators
# ==============================================================================

def calculate_analytics_kpis(sessions: list[CallSession]) -> dict[str, Any]:
    """
    Compute executive summary KPIs from a list of call sessions.
    
    Returns:
        Dict containing total_calls, avg_latency_ms, p95_latency_ms,
        sla_compliance_rate, escalation_rate, avg_duration_seconds,
        total_duration_minutes, total_turns, and sla_breach_count.
    """
    if not sessions:
        return {
            "total_calls": 0,
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "p50_latency_ms": 0.0,
            "sla_compliance_rate": 100.0,
            "escalation_rate": 0.0,
            "avg_duration_seconds": 0.0,
            "total_duration_minutes": 0.0,
            "total_turns": 0,
            "sla_breach_count": 0,
            "sla_pass_count": 0,
        }

    total_calls = len(sessions)
    escalated_count = sum(1 for s in sessions if s.context.escalated or s.status == CallStatus.ESCALATED)
    escalation_rate = (escalated_count / total_calls) * 100.0 if total_calls > 0 else 0.0

    durations = [s.metrics.duration_seconds for s in sessions if s.metrics.duration_seconds > 0]
    avg_duration_seconds = float(np.mean(durations)) if durations else 0.0
    total_duration_minutes = float(sum(durations)) / 60.0 if durations else 0.0

    # Extract all measured assistant turn latencies
    assistant_latencies: list[float] = []
    total_turns_count = 0
    for s in sessions:
        total_turns_count += len(s.messages)
        for m in s.messages:
            if m.role == MessageRole.ASSISTANT and m.latency_ms is not None and m.latency_ms > 0:
                assistant_latencies.append(m.latency_ms)

    if assistant_latencies:
        avg_latency = float(np.mean(assistant_latencies))
        p95_latency = float(np.percentile(assistant_latencies, 95))
        p50_latency = float(np.percentile(assistant_latencies, 50))
        sla_pass = sum(1 for lat in assistant_latencies if lat < SLA_BUDGET_TOTAL_MS)
        sla_breach = len(assistant_latencies) - sla_pass
        sla_rate = (sla_pass / len(assistant_latencies)) * 100.0
    else:
        avg_latency = 0.0
        p95_latency = 0.0
        p50_latency = 0.0
        sla_pass = 0
        sla_breach = 0
        sla_rate = 100.0

    return {
        "total_calls": total_calls,
        "avg_latency_ms": round(avg_latency, 1),
        "p95_latency_ms": round(p95_latency, 1),
        "p50_latency_ms": round(p50_latency, 1),
        "sla_compliance_rate": round(sla_rate, 1),
        "escalation_rate": round(escalation_rate, 1),
        "avg_duration_seconds": round(avg_duration_seconds, 1),
        "total_duration_minutes": round(total_duration_minutes, 1),
        "total_turns": total_turns_count,
        "sla_breach_count": sla_breach,
        "sla_pass_count": sla_pass,
    }


def aggregate_latency_breakdown(sessions: list[CallSession]) -> dict[str, Any]:
    """
    Decompose voice latency into constituent pipeline layers: STT, LLM, TTS, and Total.
    """
    stt_vals: list[float] = []
    llm_vals: list[float] = []
    tts_vals: list[float] = []
    tot_vals: list[float] = []
    turn_records: list[dict[str, Any]] = []

    for s in sessions:
        for m in s.messages:
            if m.stt_latency_ms is not None and m.stt_latency_ms > 0:
                stt_vals.append(m.stt_latency_ms)
            if m.role == MessageRole.ASSISTANT:
                if m.llm_latency_ms is not None and m.llm_latency_ms > 0:
                    llm_vals.append(m.llm_latency_ms)
                if m.tts_latency_ms is not None and m.tts_latency_ms > 0:
                    tts_vals.append(m.tts_latency_ms)
                if m.latency_ms is not None and m.latency_ms > 0:
                    tot_vals.append(m.latency_ms)
                    turn_records.append({
                        "session_id": s.session_id,
                        "timestamp": m.timestamp,
                        "stt_ms": m.stt_latency_ms or 0.0,
                        "llm_ms": m.llm_latency_ms or 0.0,
                        "tts_ms": m.tts_latency_ms or 0.0,
                        "total_ms": m.latency_ms,
                        "is_sla_compliant": m.latency_ms < SLA_BUDGET_TOTAL_MS,
                    })

    return {
        "avg_stt_ms": round(float(np.mean(stt_vals)), 1) if stt_vals else 0.0,
        "avg_llm_ms": round(float(np.mean(llm_vals)), 1) if llm_vals else 0.0,
        "avg_tts_ms": round(float(np.mean(tts_vals)), 1) if tts_vals else 0.0,
        "avg_total_ms": round(float(np.mean(tot_vals)), 1) if tot_vals else 0.0,
        "targets": {
            "stt_target_ms": SLA_BUDGET_STT_MS,
            "llm_target_ms": SLA_BUDGET_LLM_MS,
            "tts_target_ms": SLA_BUDGET_TTS_MS,
            "total_target_ms": SLA_BUDGET_TOTAL_MS,
        },
        "all_turns": turn_records,
    }


def aggregate_daily_volume(sessions: list[CallSession]) -> list[dict[str, Any]]:
    """
    Group sessions by calendar day with completed vs escalated call volume counts.
    """
    if not sessions:
        return []

    data: dict[str, dict[str, int]] = {}
    for s in sessions:
        date_str = s.start_time.strftime("%Y-%m-%d")
        if date_str not in data:
            data[date_str] = {"total": 0, "completed": 0, "escalated": 0}
        data[date_str]["total"] += 1
        if s.context.escalated or s.status == CallStatus.ESCALATED:
            data[date_str]["escalated"] += 1
        else:
            data[date_str]["completed"] += 1

    sorted_dates = sorted(data.keys())
    result = []
    for d in sorted_dates:
        result.append({
            "date": d,
            "total": data[d]["total"],
            "completed": data[d]["completed"],
            "escalated": data[d]["escalated"],
        })
    return result


def aggregate_hourly_volume(sessions: list[CallSession]) -> list[dict[str, Any]]:
    """
    Aggregate calls across 24 hourly buckets (00:00 to 23:00) with peak rush hour flags.
    """
    hourly_counts = {h: 0 for h in range(24)}
    for s in sessions:
        hourly_counts[s.start_time.hour] += 1

    result = []
    for h in range(24):
        # Peak restaurant rush hours: Lunch (12:00-15:00) & Dinner (19:00-22:00)
        is_peak = (12 <= h <= 15) or (19 <= h <= 22)
        result.append({
            "hour": h,
            "hour_label": f"{h:02d}:00",
            "count": hourly_counts[h],
            "is_peak": is_peak,
        })
    return result


def aggregate_sentiment_distribution(sessions: list[CallSession]) -> dict[str, int]:
    """
    Count customer sentiments across filtered calls (positive, neutral, negative).
    """
    dist = {"positive": 0, "neutral": 0, "negative": 0}
    for s in sessions:
        sentiment = (s.context.sentiment or "neutral").lower()
        if sentiment in dist:
            dist[sentiment] += 1
        else:
            dist["neutral"] += 1
    return dist


def aggregate_tool_invocations(sessions: list[CallSession]) -> list[dict[str, Any]]:
    """
    Aggregate and rank tool calls made across all sessions.
    """
    counts: dict[str, int] = {}
    total_tool_calls = 0

    for s in sessions:
        for m in s.messages:
            if m.role == MessageRole.TOOL and m.tool_name:
                t_name = m.tool_name
                counts[t_name] = counts.get(t_name, 0) + 1
                total_tool_calls += 1

    result = []
    for name, cnt in sorted(counts.items(), key=lambda item: item[1], reverse=True):
        pct = (cnt / total_tool_calls * 100.0) if total_tool_calls > 0 else 0.0
        result.append({
            "tool_name": name,
            "count": cnt,
            "percentage": round(pct, 1),
        })
    return result


def aggregate_language_distribution(sessions: list[CallSession]) -> dict[str, int]:
    """
    Count distribution of Arabic vs English sessions.
    """
    dist = {"ar": 0, "en": 0}
    for s in sessions:
        lang = (s.context.language or "en").lower()
        dist[lang] = dist.get(lang, 0) + 1
    return dist
