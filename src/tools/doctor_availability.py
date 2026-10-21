"""
Doctor Availability & Shift Lookup Tool for Egyptian Polyclinics.

Provides strongly-typed, low-latency queries for:
1. Specific doctor shift availability, remaining queue capacity, and pricing.
2. Automated 7-day lookahead recommendation when requested shifts are full or off-duty.
3. Specialty-wide doctor discovery (up to 3 available physicians per day).
4. Egyptian Arabic & English phonetic/orthographic fuzzy matching with disambiguation.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import logging
import re
from collections.abc import Sequence
from zoneinfo import ZoneInfo

from src.db.models import Doctor, Specialty
from src.db.repository import ClinicRepository
from src.db.schemas import DayOfWeek, DoctorAvailabilityRead
from src.db.session import get_async_session
from src.tools.schemas import (
    DoctorAvailabilityOutput,
    ToolResult,
    parse_colloquial_date,
)

logger = logging.getLogger(__name__)

# Egyptian local timezone
CAIRO_TZ = ZoneInfo("Africa/Cairo")

# Arabic titles to strip for clean name matching
_TITLES_PATTERN = re.compile(
    r"^(?:أ\.د\.|ا\.د\.|استاذ دكتور|أستاذ دكتور|أستاذ|استاذ|استشاري(?:ة)?|استشاريه|أخصائي(?:ة)?|اخصائي(?:ه)?|دكتور(?:ة)?|دكتوره|د\.|dr\.?)\s*",
    re.IGNORECASE,
)

# Arabic diacritics (tashkeel) and tatweel
_DIACRITICS = re.compile(r"[\u064B-\u0652\u0640]")


def get_cairo_today() -> dt.date:
    """Return today's date in Egyptian local time (Africa/Cairo)."""
    return dt.datetime.now(tz=CAIRO_TZ).date()


def normalize_text_ar(text: str | None) -> str:
    """
    Normalize Arabic text for resilient phonetic & orthographic matching.
    Strips titles, diacritics, unifies hamza variants, and collapses spaces.
    """
    if not text:
        return ""
    # Strip diacritics & tatweel
    s = _DIACRITICS.sub("", text.strip().lower())
    # Strip common doctor titles before punctuation removal
    s = _TITLES_PATTERN.sub("", s).strip()
    # Remove punctuation
    s = re.sub(r"[^\w\s]", " ", s)
    # Strip standalone 'د ' or 'dr ' if remaining
    s = re.sub(r"^(?:د|dr)\s+", "", s).strip()
    # Unify hamzas
    s = re.sub(r"[أإآ]", "ا", s)
    # Unify taa marbuta / haa
    s = re.sub(r"ة", "ه", s)
    # Unify alif maqsura / yaa
    s = re.sub(r"ى", "ي", s)
    # Collapse whitespaces
    return re.sub(r"\s+", " ", s).strip()


def match_specialty(query: str, specialties: Sequence[Specialty]) -> Specialty | None:
    """
    Match user query to a Specialty by code, Arabic name, or English name.
    Supports partial and alias matching (e.g. 'باطنة' -> 'الباطنة والجهاز الهضمي').
    """
    clean_q = normalize_text_ar(query)
    raw_q_lower = query.strip().lower()

    # 1. Exact code match
    for spec in specialties:
        if spec.code.lower() == raw_q_lower or spec.code.lower().replace("_", " ") == raw_q_lower:
            return spec

    # 2. Exact or substring matching on Arabic/English names
    best_match: Specialty | None = None
    for spec in specialties:
        norm_spec_ar = normalize_text_ar(spec.name_ar)
        norm_spec_en = spec.name_en.lower()

        if clean_q == norm_spec_ar or raw_q_lower == norm_spec_en:
            return spec

        # Substring / token matching
        if clean_q and (clean_q in norm_spec_ar or norm_spec_ar in clean_q):
            best_match = spec
            break
        if raw_q_lower and (raw_q_lower in norm_spec_en or norm_spec_en in raw_q_lower):
            best_match = spec
            break

    # 3. Common colloquial aliases
    alias_map = {
        "باطنه": "internal_medicine",
        "باطنة": "internal_medicine",
        "جهاز هضمي": "internal_medicine",
        "كبد": "internal_medicine",
        "سكر": "internal_medicine",
        "ضغط": "internal_medicine",
        "اطفال": "pediatrics",
        "أطفال": "pediatrics",
        "حديثي الولاده": "pediatrics",
        "حديثي الولادة": "pediatrics",
        "عظام": "orthopedics",
        "مفاصل": "orthopedics",
        "كسور": "orthopedics",
        "نساء": "obstetrics_gynecology",
        "ولاده": "obstetrics_gynecology",
        "ولادة": "obstetrics_gynecology",
        "نساء وتوليد": "obstetrics_gynecology",
        "حمل": "obstetrics_gynecology",
        "اسنان": "dentistry",
        "أسنان": "dentistry",
    }
    for alias, code in alias_map.items():
        if alias in clean_q or clean_q in alias:
            for spec in specialties:
                if spec.code == code:
                    return spec

    return best_match


def match_doctors(query: str, doctors: Sequence[Doctor]) -> list[Doctor]:
    """
    Match user query to Doctor entities using Arabic/English fuzzy and partial search.
    Returns all matching doctors (could be multiple if names are ambiguous).
    """
    clean_q = normalize_text_ar(query)
    raw_q_lower = query.strip().lower()

    if not clean_q and not raw_q_lower:
        return []

    matched: list[Doctor] = []
    for doc in doctors:
        norm_doc_ar = normalize_text_ar(doc.name_ar)
        norm_doc_en = doc.name_en.lower() if doc.name_en else ""

        # Exact normalized match
        if clean_q == norm_doc_ar or raw_q_lower == norm_doc_en:
            matched.append(doc)
            continue

        # Substring match (e.g. 'الشريف' in 'احمد محمود الشريف')
        if clean_q and clean_q in norm_doc_ar:
            matched.append(doc)
            continue

        # Substring in English
        if raw_q_lower and raw_q_lower in norm_doc_en:
            matched.append(doc)
            continue

        # Token-level overlap (e.g. 'احمد الشريف')
        q_tokens = [t for t in clean_q.split() if len(t) > 2]
        if q_tokens and all(tok in norm_doc_ar for tok in q_tokens):
            matched.append(doc)

    return matched


class DoctorAvailabilityTool:
    """
    Execution tool for checking clinic doctor schedules, remaining slots,
    and pricing with 7-day lookahead and specialty aggregation.
    """

    def __init__(self, session_factory=None):
        self.session_factory = session_factory

    async def aexecute(
        self,
        doctor_name_or_id: str | None = None,
        specialty: str | None = None,
        date: dt.date | str | None = None,
    ) -> ToolResult:
        """
        Asynchronously check doctor availability or specialty shift status.
        """
        # Validate input existence
        if not doctor_name_or_id and not specialty:
            return ToolResult(
                success=False,
                message="يرجى توضيح اسم الطبيب أو التخصص المطلوب للاستعلام عن المواعيد المتاحة.",
                error="Missing both doctor and specialty",
            )

        # Resolve target date using Cairo timezone as default
        cairo_today = get_cairo_today()
        target_date: dt.date
        try:
            if date is None or date == "":
                target_date = cairo_today
            elif isinstance(date, dt.date):
                target_date = date
            elif isinstance(date, dt.datetime):
                target_date = date.date()
            else:
                target_date = parse_colloquial_date(str(date), today=cairo_today)
        except (ValueError, TypeError, KeyError) as exc:
            logger.warning(f"Failed to parse date '{date}': {exc}")
            target_date = cairo_today

        try:
            async with get_async_session(self.session_factory) as session:
                repo = ClinicRepository(session)

                # Fetch all active specialties and doctors for lookup
                all_specialties = await repo.get_specialties(active_only=True)
                all_doctors = await repo.get_doctors(active_only=True)

                # -------------------------------------------------------------
                # 1. Specific Doctor Lookup (by ID or Name)
                # -------------------------------------------------------------
                if doctor_name_or_id:
                    matched_doctor: Doctor | None = None
                    raw_ident = doctor_name_or_id.strip()

                    # Check if numeric doctor_id
                    if raw_ident.isdigit():
                        doc_id = int(raw_ident)
                        matched_doctor = await repo.get_doctor_by_id(doc_id)
                        if not matched_doctor or not matched_doctor.is_active:
                            return ToolResult(
                                success=False,
                                message=f"عذراً، لم نتمكن من العثور على طبيب بالرقم {doc_id}.",
                                error="Doctor ID not found",
                            )
                    else:
                        candidates = match_doctors(raw_ident, all_doctors)

                        # If specialty was also provided, narrow down candidates
                        if specialty and len(candidates) > 1:
                            target_spec = match_specialty(specialty, all_specialties)
                            if target_spec:
                                filtered = [
                                    c for c in candidates if c.specialty_id == target_spec.id
                                ]
                                if filtered:
                                    candidates = filtered

                        if not candidates:
                            # Suggest available specialties
                            spec_list = "، ".join([s.name_ar for s in all_specialties[:4]])
                            return ToolResult(
                                success=False,
                                message=(
                                    f"عذراً، لم نتمكن من العثور على الطبيب '{raw_ident}'. "
                                    f"التخصصات المتاحة بالعيادة تشمل: {spec_list}."
                                ),
                                error="Doctor name not found",
                            )

                        if len(candidates) > 1:
                            # Ambiguous match -> return candidates and ask caller
                            cand_data = [
                                {
                                    "doctor_id": doc.id,
                                    "name_ar": doc.name_ar,
                                    "specialty_name_ar": (
                                        doc.specialty.name_ar if doc.specialty else ""
                                    ),
                                    "title": doc.title,
                                }
                                for doc in candidates
                            ]
                            names_str = "، و".join(
                                [
                                    f"{doc.name_ar} ({doc.specialty.name_ar if doc.specialty else ''})"
                                    for doc in candidates
                                ]
                            )
                            return ToolResult(
                                success=False,
                                message=(
                                    f"يوجد أكثر من طبيب بهذا الاسم: {names_str}. "
                                    f"هل تقصد دكتوراً معيناً منهم؟"
                                ),
                                data={"candidates": cand_data},
                                error="Ambiguous doctor name",
                            )

                        matched_doctor = candidates[0]

                    # Check availability for the matched doctor on target_date
                    avail = await repo.get_doctor_availability(matched_doctor.id, target_date)
                    specialty_name = (
                        matched_doctor.specialty.name_ar if matched_doctor.specialty else ""
                    )

                    if avail.has_shift and avail.is_available:
                        msg = (
                            f"{matched_doctor.name_ar} ({specialty_name}) متاح يوم {avail.day_name_ar} "
                            f"الموافق {target_date.strftime('%Y-%m-%d')} من الساعة {avail.formatted_shift}. "
                            f"متبقي {avail.remaining_capacity} أماكن حجز، وسعر الكشف {int(avail.examination_fee)} جنيه."
                        )
                        output = DoctorAvailabilityOutput(
                            doctor_id=matched_doctor.id,
                            doctor_name_ar=matched_doctor.name_ar,
                            specialty_name_ar=specialty_name,
                            target_date=target_date.isoformat(),
                            day_name_ar=avail.day_name_ar,
                            has_shift=True,
                            shift_hours=avail.formatted_shift,
                            remaining_capacity=avail.remaining_capacity,
                            is_available=True,
                            examination_fee=avail.examination_fee,
                            consultation_fee=avail.consultation_fee,
                            message=msg,
                        )
                        return ToolResult(success=True, message=msg, data=output.model_dump())

                    # Not available or no shift on target_date -> Look ahead 7 days
                    next_slot: DoctorAvailabilityRead | None = None
                    for offset in range(1, 8):
                        next_d = target_date + dt.timedelta(days=offset)
                        slot = await repo.get_doctor_availability(matched_doctor.id, next_d)
                        if slot.has_shift and slot.is_available:
                            next_slot = slot
                            break

                    reason = (
                        f"شفت {matched_doctor.name_ar} يوم {avail.day_name_ar} الموافق {target_date.strftime('%Y-%m-%d')} مكتمل العدد بالكامل"
                        if avail.has_shift
                        else f"{matched_doctor.name_ar} ليس لديه شفت عمل يوم {avail.day_name_ar} الموافق {target_date.strftime('%Y-%m-%d')}"
                    )

                    if next_slot:
                        full_msg = (
                            f"عذراً، {reason}. "
                            f"أقرب موعد متاح هو يوم {next_slot.day_name_ar} الموافق {next_slot.target_date.strftime('%Y-%m-%d')} "
                            f"من الساعة {next_slot.formatted_shift} (متبقي {next_slot.remaining_capacity} أماكن)، "
                            f"وسعر الكشف {int(next_slot.examination_fee)} جنيه. تحب أحجزلك فيه؟"
                        )
                        out = DoctorAvailabilityOutput(
                            doctor_id=matched_doctor.id,
                            doctor_name_ar=matched_doctor.name_ar,
                            specialty_name_ar=specialty_name,
                            target_date=target_date.isoformat(),
                            day_name_ar=avail.day_name_ar,
                            has_shift=avail.has_shift,
                            shift_hours=avail.formatted_shift,
                            remaining_capacity=avail.remaining_capacity,
                            is_available=False,
                            examination_fee=avail.examination_fee,
                            consultation_fee=avail.consultation_fee,
                            message=full_msg,
                        )
                        payload = out.model_dump()
                        payload["next_available"] = {
                            "target_date": next_slot.target_date.isoformat(),
                            "day_name_ar": next_slot.day_name_ar,
                            "shift_hours": next_slot.formatted_shift,
                            "remaining_capacity": next_slot.remaining_capacity,
                            "examination_fee": next_slot.examination_fee,
                        }
                        return ToolResult(success=True, message=full_msg, data=payload)
                    else:
                        no_slot_msg = (
                            f"عذراً، {reason}، ولا توجد مواعيد متاحة للطبيب خلال الـ 7 أيام القادمة. "
                            f"يمكنك التواصل مع موظف الاستقبال لتنسيق موعد بديل."
                        )
                        out = DoctorAvailabilityOutput(
                            doctor_id=matched_doctor.id,
                            doctor_name_ar=matched_doctor.name_ar,
                            specialty_name_ar=specialty_name,
                            target_date=target_date.isoformat(),
                            day_name_ar=avail.day_name_ar,
                            has_shift=avail.has_shift,
                            shift_hours=avail.formatted_shift,
                            remaining_capacity=0,
                            is_available=False,
                            examination_fee=avail.examination_fee,
                            consultation_fee=avail.consultation_fee,
                            message=no_slot_msg,
                        )
                        return ToolResult(success=True, message=no_slot_msg, data=out.model_dump())

                # -------------------------------------------------------------
                # 2. Specialty-Wide Query (when doctor_name_or_id is not provided)
                # -------------------------------------------------------------
                matched_spec = match_specialty(specialty or "", all_specialties)
                if not matched_spec:
                    spec_names = "، ".join([s.name_ar for s in all_specialties])
                    return ToolResult(
                        success=False,
                        message=(
                            f"عذراً، لم نتمكن من العثور على التخصص المطلوب '{specialty}'. "
                            f"التخصصات المسجلة بالعيادة هي: {spec_names}."
                        ),
                        error="Specialty not found",
                    )

                spec_doctors = [
                    d for d in all_doctors if d.specialty_id == matched_spec.id and d.is_active
                ]
                day_of_week = DayOfWeek.from_date(target_date)
                day_name_ar = day_of_week.label_ar()

                available_docs: list[DoctorAvailabilityOutput] = []
                for doc in spec_doctors:
                    av = await repo.get_doctor_availability(doc.id, target_date)
                    if av.has_shift and av.is_available:
                        available_docs.append(
                            DoctorAvailabilityOutput(
                                doctor_id=doc.id,
                                doctor_name_ar=doc.name_ar,
                                specialty_name_ar=matched_spec.name_ar,
                                target_date=target_date.isoformat(),
                                day_name_ar=day_name_ar,
                                has_shift=True,
                                shift_hours=av.formatted_shift,
                                remaining_capacity=av.remaining_capacity,
                                is_available=True,
                                examination_fee=av.examination_fee,
                                consultation_fee=av.consultation_fee,
                                message=f"{doc.name_ar} من {av.formatted_shift} (كشف: {int(av.examination_fee)} ج.م)",
                            )
                        )
                        if len(available_docs) >= 3:
                            break

                if available_docs:
                    doc_summaries = "، و".join(
                        [
                            f"{d.doctor_name_ar} من الساعة {d.shift_hours} وسعر الكشف {int(d.examination_fee)} جنيه"
                            for d in available_docs
                        ]
                    )
                    spec_msg = (
                        f"الأطباء المتاحون في تخصص {matched_spec.name_ar} يوم {day_name_ar} "
                        f"الموافق {target_date.strftime('%Y-%m-%d')}: {doc_summaries}. "
                        f"تحب تحجز مع أي طبيب منهم؟"
                    )
                    return ToolResult(
                        success=True,
                        message=spec_msg,
                        data={"doctors": [d.model_dump() for d in available_docs]},
                    )

                # No doctors available in this specialty on target_date -> Look ahead 7 days
                next_found_date: dt.date | None = None
                next_found_doc: DoctorAvailabilityRead | None = None
                for offset in range(1, 8):
                    check_d = target_date + dt.timedelta(days=offset)
                    for doc in spec_doctors:
                        av = await repo.get_doctor_availability(doc.id, check_d)
                        if av.has_shift and av.is_available:
                            next_found_date = check_d
                            next_found_doc = av
                            break
                    if next_found_doc:
                        break

                if next_found_doc and next_found_date:
                    fallback_msg = (
                        f"عذراً، لا يوجد أطباء متاحون في تخصص {matched_spec.name_ar} يوم {day_name_ar} "
                        f"الموافق {target_date.strftime('%Y-%m-%d')}. "
                        f"أقرب موعد متاح هو يوم {next_found_doc.day_name_ar} الموافق {next_found_date.strftime('%Y-%m-%d')} "
                        f"مع {next_found_doc.doctor_name_ar} من الساعة {next_found_doc.formatted_shift} "
                        f"(سعر الكشف {int(next_found_doc.examination_fee)} جنيه). تحب أحجزلك فيه؟"
                    )
                    return ToolResult(
                        success=True,
                        message=fallback_msg,
                        data={
                            "doctors": [],
                            "next_available": {
                                "doctor_id": next_found_doc.doctor_id,
                                "doctor_name_ar": next_found_doc.doctor_name_ar,
                                "target_date": next_found_date.isoformat(),
                                "day_name_ar": next_found_doc.day_name_ar,
                                "shift_hours": next_found_doc.formatted_shift,
                                "examination_fee": next_found_doc.examination_fee,
                            },
                        },
                    )
                else:
                    empty_spec_msg = (
                        f"عذراً، لا توجد مواعيد متاحة في تخصص {matched_spec.name_ar} خلال الـ 7 أيام القادمة. "
                        f"يمكنك التواصل مع موظف الاستقبال لتنسيق موعد مناسب."
                    )
                    return ToolResult(
                        success=True,
                        message=empty_spec_msg,
                        data={"doctors": []},
                    )

        except Exception as exc:
            logger.exception("Error in doctor availability lookup")
            return ToolResult(
                success=False,
                message="عذراً، حدث خطأ أثناء فحص المواعيد المتاحة. هل يمكنك إعادة المحاولة؟",
                error=str(exc),
            )

    def execute(
        self,
        doctor_name_or_id: str | None = None,
        specialty: str | None = None,
        date: dt.date | str | None = None,
    ) -> ToolResult:
        """
        Synchronous execution entrypoint. Handles running event loops safely.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                fut = executor.submit(
                    lambda: asyncio.run(
                        self.aexecute(
                            doctor_name_or_id=doctor_name_or_id,
                            specialty=specialty,
                            date=date,
                        )
                    )
                )
                return fut.result()
        else:
            return asyncio.run(
                self.aexecute(
                    doctor_name_or_id=doctor_name_or_id,
                    specialty=specialty,
                    date=date,
                )
            )


# Global singleton instance
doctor_availability_tool = DoctorAvailabilityTool()


async def async_check_doctor_availability(
    doctor_name_or_id: str | None = None,
    specialty: str | None = None,
    date: dt.date | str | None = None,
) -> ToolResult:
    """Convenience async wrapper for LiveKit Voice Agent and LLM tool calling."""
    return await doctor_availability_tool.aexecute(
        doctor_name_or_id=doctor_name_or_id,
        specialty=specialty,
        date=date,
    )


def check_doctor_availability(
    doctor_name_or_id: str | None = None,
    specialty: str | None = None,
    date: dt.date | str | None = None,
) -> ToolResult:
    """Convenience sync wrapper for testing and synchronous dispatchers."""
    return doctor_availability_tool.execute(
        doctor_name_or_id=doctor_name_or_id,
        specialty=specialty,
        date=date,
    )
