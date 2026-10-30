"""
Knowledge Base Ingestion Pipeline.

Parses markdown domain knowledge files, applies structure-aware semantic chunking
(table rows, atomic FAQs, and boundary-split prose), attaches rich metadata,
and indexes chunks into the Qdrant vector store and BM25 index.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from src.config import settings
from src.rag.retriever import retriever

logger = logging.getLogger(__name__)


def _extract_tables(text: str) -> list[tuple[int, int, list[str], list[list[str]]]]:
    """
    Find Markdown tables in text.
    Returns list of tuples: (start_line_idx, end_line_idx, headers, rows).
    """
    lines = text.splitlines()
    tables: list[tuple[int, int, list[str], list[list[str]]]] = []
    i = 0
    n = len(lines)

    while i < n - 1:
        line = lines[i].strip()
        next_line = lines[i + 1].strip() if i + 1 < n else ""
        if (
            line.startswith("|")
            and line.endswith("|")
            and "|" in line[1:-1]
            and bool(re.match(r"^\|?[-:\s|]+\|?$", next_line))
        ):
            headers = [
                re.sub(r"[*_`]", "", c).replace("<br>", " ").strip() for c in line.split("|")[1:-1]
            ]
            rows: list[list[str]] = []
            j = i + 2
            while j < n and lines[j].strip().startswith("|") and lines[j].strip().endswith("|"):
                row_cells = [
                    re.sub(r"[*_`]", "", c).replace("<br>", " ").strip()
                    for c in lines[j].split("|")[1:-1]
                ]
                if any(row_cells):
                    rows.append(row_cells)
                j += 1
            if rows:
                tables.append((i, j, headers, rows))
            i = j
        else:
            i += 1

    return tables


def _split_prose_blocks(text: str, max_chars: int) -> list[str]:
    """
    Split long prose text into chunks <= max_chars along paragraph or bullet boundaries.
    """
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return [cleaned] if cleaned else []

    paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0

    for p in paragraphs:
        if len(p) > max_chars:
            # Paragraph itself exceeds max_chars; split on bullet lines or line breaks
            bullet_lines = [b.strip() for b in p.splitlines() if b.strip()]
            b_chunk: list[str] = []
            b_len = 0
            for bl in bullet_lines:
                if b_len + len(bl) > max_chars and b_chunk:
                    chunks.append("\n".join(b_chunk))
                    b_chunk = [bl]
                    b_len = len(bl)
                else:
                    b_chunk.append(bl)
                    b_len += len(bl) + 1
            if b_chunk:
                chunks.append("\n".join(b_chunk))
        elif current_len + len(p) > max_chars and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = [p]
            current_len = len(p)
        else:
            current_chunk.append(p)
            current_len += len(p) + 2

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks


class KnowledgeIngestionPipeline:
    """
    Splits, transforms, and ingests markdown knowledge documents into Qdrant & BM25.
    """

    def __init__(self, target_retriever=None):
        self._retriever = target_retriever

    @property
    def retriever(self) -> Any:
        """Resolve target retriever lazily on access."""
        if self._retriever is None:
            if settings.hybrid_search_enabled:
                from src.rag.hybrid_retriever import hybrid_retriever

                self._retriever = hybrid_retriever
            else:
                self._retriever = retriever
        return self._retriever

    @retriever.setter
    def retriever(self, val: Any) -> None:
        self._retriever = val

    def _infer_category(self, section_title: str, text: str) -> str:
        """Categorize chunk for filtered vector lookups supporting English and Egyptian Arabic."""
        lower_title = section_title.lower()
        lower_text = text.lower()

        # Healthcare: Safety & Emergency guardrails
        safety_keywords = [
            "safety",
            "emergency",
            "guardrail",
            "red-flag",
            "triage",
            "ambulance",
            "123",
            "١٢٣",
            "سلامة",
            "سلامه",
            "طوارئ",
            "طوارىء",
            "إسعاف",
            "اسعاف",
            "محاذير",
            "تحذير",
            "حظر",
            "حظر التشخيص",
            "روشتة",
            "روشته",
            "أعراض حمراء",
            "اعراض حمراء",
            "خط الطوارئ",
            "خط الطوارىء",
        ]

        # Healthcare: Caller FAQs
        faq_keywords = [
            "faq",
            "frequently",
            "caller",
            "أسئلة شائعة",
            "اسئلة شائعة",
            "أسئلة",
            "اسئلة",
            "استفسارات",
        ]

        # Healthcare: Health Insurance & Co-payments
        insurance_keywords = [
            "insurance",
            "network",
            "co-payment",
            "co-pay",
            "approval",
            "pre-authorization",
            "bupa",
            "axa",
            "metlife",
            "allianz",
            "nextcare",
            "prime health",
            "care plus",
            "globemed",
            "تأمين",
            "تامين",
            "شبكات التأمين",
            "شبكات التامين",
            "شركات التأمين",
            "شركات التامين",
            "أكسا",
            "اكسا",
            "ميتلايف",
            "بوبا",
            "مصر للتأمين",
            "مصر للتامين",
            "كارنيه",
            "تحمل",
            "نسبة تحمل",
            "نسبه تحمل",
            "موافقة مسبقة",
            "موافقه مسبقه",
            "تحويل طبي",
        ]

        # Healthcare: Lab & Radiology Diagnostic Tests & Prep
        lab_radiology_keywords = [
            "lab",
            "radiology",
            "x-ray",
            "ultrasound",
            "sonar",
            "fasting",
            "dexa",
            "urine",
            "stool",
            "blood",
            "test",
            "fbs",
            "ppbs",
            "hba1c",
            "cbc",
            "esr",
            "crp",
            "creatinine",
            "lipid",
            "تحاليل",
            "تحليل",
            "معمل",
            "أشعة",
            "اشعة",
            "اشعه",
            "سونار",
            "رنين",
            "مقطعية",
            "مقطعيه",
            "صيام",
            "صائم",
            "فاطر",
            "تراكمي",
            "بول",
            "براز",
            "عينة",
            "عينه",
            "وظائف كبد",
            "وظائف كلى",
            "وظائف الكبد",
            "وظائف الكلى",
            "سكر صائم",
            "سكر فاطر",
            "دهون",
            "كوليسترول",
            "رسم قلب",
            "هولتر",
        ]

        # Healthcare: Booking, Queue, Shifts & Attendance
        booking_queue_keywords = [
            "queue",
            "shift",
            "turn",
            "reschedule",
            "attendance",
            "cancellation",
            "appointment",
            "طابور",
            "نمرة",
            "نمره",
            "رقم الكشف",
            "شيفت",
            "شفت",
            "أسبقية",
            "اسبقية",
            "حضور",
            "تأخير",
            "تاخير",
            "إلغاء",
            "الغاء",
            "تعديل الموعد",
            "إعادة جدولة",
            "اعادة جدولة",
            "مواعيد الحضور",
            "كود حجز",
        ]

        # Healthcare: Pricing & Consultation Policy
        pricing_keywords = [
            "pricing",
            "fee",
            "cost",
            "consultation",
            "payment",
            "installment",
            "cash",
            "visa",
            "valu",
            "souhoola",
            "aman",
            "forsa",
            "follow-up",
            "سعر",
            "أسعار",
            "اسعار",
            "كشف",
            "استشارة",
            "استشاره",
            "رسوم",
            "14 يوم",
            "١٤ يوم",
            "طرق الدفع",
            "وسائل الدفع",
            "نظم الدفع",
            "كاش",
            "فيزا",
            "ماستركارد",
            "تقسيط",
            "فاليو",
            "سهولة",
            "سهوله",
            "أمان",
            "امان",
            "فرصة",
            "فرصه",
            "إعادة كشف",
            "اعادة كشف",
        ]

        # Healthcare: Doctors & Consultants
        doctors_keywords = [
            "doctor",
            "physician",
            "consultant",
            "specialist",
            "faculty",
            "staff",
            "أطباء",
            "اطباء",
            "طبيب",
            "دكتور",
            "د.",
            "استشاري",
            "استشارية",
            "استشاريه",
            "أخصائي",
            "أخصائية",
            "اخصائي",
            "اخصائية",
            "اخصائيه",
            "جدول الأطباء",
            "جدول الاطباء",
            "درجات علمية",
            "درجه علميه",
            "دكتوراه",
            "زمالة",
            "بورد",
        ]

        # Healthcare: General Clinic Info & Branches
        general_clinic_keywords = [
            "branch",
            "address",
            "location",
            "hours",
            "hotline",
            "knowledge base",
            "operational",
            "معلومات عامة",
            "معلومات عامه",
            "فروع",
            "فرع",
            "مواعيد العمل",
            "المركز الرئيسي",
            "المعادي",
            "مدينة نصر",
            "مدينه نصر",
            "التجمع",
            "الدقي",
            "المهندسين",
            "الشيخ زايد",
            "الخط الساخن",
            "19876",
            "واتساب",
            "تليفون",
            "الدليل التشغيلي",
            "قاعدة المعرفة",
        ]

        # Healthcare: Specialties & Clinical Services
        specialties_keywords = [
            "specialties",
            "department",
            "clinic",
            "cardiology",
            "orthopedic",
            "pediatric",
            "internal medicine",
            "dentist",
            "obstetric",
            "gynecology",
            "dermatology",
            "ophthalmology",
            "ent",
            "neurology",
            "تخصصات",
            "الأقسام",
            "اقسام",
            "عيادة",
            "عيادات",
            "قلب",
            "أوعية",
            "اوعية",
            "عظام",
            "مفاصل",
            "أطفال",
            "اطفال",
            "مبتسرين",
            "حديثي الولادة",
            "حديثي الولاده",
            "باطنة",
            "باطنه",
            "جهاز هضمي",
            "كبد",
            "أسنان",
            "اسنان",
            "نساء وتوليد",
            "نساء",
            "توليد",
            "جلدية",
            "جلديه",
            "ليزر",
            "عيون",
            "أنف وأذن",
            "انف واذن",
            "مخ وأعصاب",
            "مخ واعصاب",
        ]

        # Legacy restaurant keywords
        menu_keywords = [
            "menu",
            "shawarma",
            "grill",
            "mezza",
            "salad",
            "dessert",
            "beverage",
            "منيو",
            "قائمة الطعام",
            "شاورما",
            "مشاوي",
            "مقبلات",
            "سلطات",
            "حلويات",
            "مشروبات",
            "ساندوتش",
            "سندوتش",
            "وجبات",
            "وجبة",
            "فتة",
            "عصائر",
        ]
        allergen_keywords = [
            "allergen",
            "dietary",
            "vegan",
            "vegetarian",
            "gluten",
            "halal",
            "nut",
            "حساسية",
            "مسببات",
            "دايت",
            "نباتي",
            "جلوتين",
            "حلال",
            "مكسرات",
            "ألبان",
            "بيض",
            "ثومية",
            "تومية",
        ]
        delivery_keywords = [
            "delivery",
            "shipping",
            "توصيل",
            "دليفري",
            "أوردر",
            "اوردر",
            "شحن",
        ]
        reservation_keywords = [
            "table",
            "party",
            "walk-in",
            "ترابيزة",
            "ترابيزات",
            "طاولة",
            "طاولات",
            "عيد ميلاد",
            "أفراح",
        ]
        catering_keywords = ["cater", "بوفيه", "حفلات", "عزومات", "ايفنت"]

        # 1. Prioritize title-based categorization for accurate section boundaries
        if any(k in lower_title for k in safety_keywords):
            return "safety_guardrails"
        elif any(k in lower_title for k in delivery_keywords):
            return "delivery"
        elif any(k in lower_title for k in reservation_keywords):
            return "reservations"
        elif any(k in lower_title for k in allergen_keywords):
            return "allergens"
        elif any(k in lower_title for k in catering_keywords):
            return "catering"
        elif any(k in lower_title for k in menu_keywords):
            return "menu"
        elif (
            any(k in lower_title for k in faq_keywords)
            or bool(re.match(r"^س\s*\d+", lower_title))
            or lower_title.startswith("س:")
        ):
            return "faqs"
        elif any(k in lower_title for k in insurance_keywords):
            return "insurance"
        elif any(k in lower_title for k in lab_radiology_keywords):
            return "lab_radiology"
        elif any(k in lower_title for k in booking_queue_keywords):
            return "booking_queue"
        elif any(k in lower_title for k in pricing_keywords):
            return "pricing"
        elif any(k in lower_title for k in doctors_keywords):
            return "doctors"
        elif any(k in lower_title for k in general_clinic_keywords):
            return "general"
        elif any(k in lower_title for k in specialties_keywords):
            return "specialties"

        # 2. Fallback to body text keyword matching
        if any(k in lower_text for k in safety_keywords):
            return "safety_guardrails"
        elif any(k in lower_text for k in delivery_keywords):
            return "delivery"
        elif any(k in lower_text for k in allergen_keywords):
            return "allergens"
        elif any(k in lower_text for k in reservation_keywords):
            return "reservations"
        elif any(k in lower_text for k in menu_keywords):
            return "menu"
        elif any(k in lower_text for k in faq_keywords):
            return "faqs"
        elif any(k in lower_text for k in insurance_keywords):
            return "insurance"
        elif any(k in lower_text for k in lab_radiology_keywords):
            return "lab_radiology"
        elif any(k in lower_text for k in booking_queue_keywords):
            return "booking_queue"
        elif any(k in lower_text for k in pricing_keywords):
            return "pricing"
        elif any(k in lower_text for k in doctors_keywords):
            return "doctors"
        elif any(k in lower_text for k in specialties_keywords):
            return "specialties"
        return "general"

    def parse_markdown(self, file_path: Path) -> list[dict[str, Any]]:
        """
        Parses a Markdown file using structure-aware semantic chunking.

        Rules:
        1. Markdown tables are decomposed into self-contained row-level chunks
           ([Section Title] — Header1: Val1 — Header2: Val2 ...).
        2. Caller FAQs (س/ج) are kept intact as atomic chunks.
        3. Long prose sections exceeding settings.rag_chunk_max_chars are split
           along paragraph/bullet boundaries while preserving section header context.
        4. Every chunk receives a deterministic unique UUID for idempotency.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Knowledge base file not found: {file_path}")

        content = file_path.read_text(encoding="utf-8")
        max_chars = settings.rag_chunk_max_chars

        # Split by level 2 and 3 headers (## and ###)
        header_pattern = re.compile(r"^(#{2,3}\s+.+)$", re.MULTILINE)
        splits = header_pattern.split(content)

        raw_sections: list[tuple[str, str]] = []
        if len(splits) > 1:
            for i in range(1, len(splits), 2):
                header = splits[i].strip()
                body = splits[i + 1].strip() if (i + 1) < len(splits) else ""
                cleaned_title = re.sub(r"^#{2,3}\s*", "", header).strip()
                raw_sections.append((cleaned_title, body))
        else:
            raw_sections.append(("General", content.strip()))

        chunks: list[dict[str, Any]] = []

        for cleaned_title, body in raw_sections:
            category = self._infer_category(cleaned_title, body)

            # Check if this is an FAQ section
            is_faq = (
                category == "faqs"
                or cleaned_title.startswith(("س ", "س:"))
                or bool(re.match(r"^س\s*\d+", cleaned_title))
            )

            if is_faq:
                # Keep FAQ atomic as single chunk
                full_text = f"{cleaned_title}\n\n{body}".strip()
                if len(full_text) > 10:
                    chunk_id = str(
                        uuid.uuid5(
                            uuid.NAMESPACE_DNS,
                            f"{file_path.name}:{cleaned_title}:faq:{len(chunks)}:{full_text[:60]}",
                        )
                    )
                    chunks.append(
                        {
                            "id": chunk_id,
                            "text": full_text,
                            "metadata": {
                                "source": file_path.name,
                                "section": cleaned_title,
                                "category": category,
                                "chunk_type": "faq",
                            },
                        }
                    )
                continue

            # Check for Markdown tables
            tables = _extract_tables(body)
            if tables:
                lines = body.splitlines()
                last_end = 0

                for t_idx, (start_idx, end_idx, headers, rows) in enumerate(tables):
                    # Check leading prose before table
                    if start_idx > last_end:
                        leading_prose = "\n".join(lines[last_end:start_idx]).strip()
                        if len(leading_prose) > 40:
                            prose_pieces = _split_prose_blocks(leading_prose, max_chars)
                            for p_idx, piece in enumerate(prose_pieces):
                                piece_text = f"{cleaned_title}\n\n{piece}".strip()
                                chunk_id = str(
                                    uuid.uuid5(
                                        uuid.NAMESPACE_DNS,
                                        f"{file_path.name}:{cleaned_title}:section:{len(chunks)}:{piece_text[:60]}",
                                    )
                                )
                                chunks.append(
                                    {
                                        "id": chunk_id,
                                        "text": piece_text,
                                        "metadata": {
                                            "source": file_path.name,
                                            "section": cleaned_title,
                                            "category": category,
                                            "chunk_type": "section",
                                        },
                                    }
                                )

                    # Process table rows into self-contained row-level chunks
                    for r_idx, row in enumerate(rows):
                        pairs = []
                        for h, val in zip(headers, row):
                            if val and val != "-":
                                pairs.append(f"{h}: {val}")
                        row_content = " — ".join(pairs)
                        row_text = f"{cleaned_title}\n{row_content}".strip()
                        chunk_id = str(
                            uuid.uuid5(
                                uuid.NAMESPACE_DNS,
                                f"{file_path.name}:{cleaned_title}:table_row:{len(chunks)}:{row_text[:60]}",
                            )
                        )
                        chunks.append(
                            {
                                "id": chunk_id,
                                "text": row_text,
                                "metadata": {
                                    "source": file_path.name,
                                    "section": cleaned_title,
                                    "category": category,
                                    "chunk_type": "table_row",
                                },
                            }
                        )

                    last_end = end_idx

                # Check trailing prose after last table
                if last_end < len(lines):
                    trailing_prose = "\n".join(lines[last_end:]).strip()
                    if len(trailing_prose) > 40:
                        prose_pieces = _split_prose_blocks(trailing_prose, max_chars)
                        for p_idx, piece in enumerate(prose_pieces):
                            piece_text = f"{cleaned_title}\n\n{piece}".strip()
                            chunk_id = str(
                                uuid.uuid5(
                                    uuid.NAMESPACE_DNS,
                                    f"{file_path.name}:{cleaned_title}:section:{len(chunks)}:{piece_text[:60]}",
                                )
                            )
                            chunks.append(
                                {
                                    "id": chunk_id,
                                    "text": piece_text,
                                    "metadata": {
                                        "source": file_path.name,
                                        "section": cleaned_title,
                                        "category": category,
                                        "chunk_type": "section",
                                    },
                                }
                            )
                continue

            # Standard prose section (no tables, non-FAQ)
            if len(body) <= max_chars:
                combined_chunk = f"{cleaned_title}\n\n{body}".strip()
                if len(combined_chunk) > 20:
                    chunk_id = str(
                        uuid.uuid5(
                            uuid.NAMESPACE_DNS,
                            f"{file_path.name}:{cleaned_title}:section:{len(chunks)}:{combined_chunk[:60]}",
                        )
                    )
                    chunks.append(
                        {
                            "id": chunk_id,
                            "text": combined_chunk,
                            "metadata": {
                                "source": file_path.name,
                                "section": cleaned_title,
                                "category": category,
                                "chunk_type": "section",
                            },
                        }
                    )
            else:
                prose_pieces = _split_prose_blocks(body, max_chars)
                for p_idx, piece in enumerate(prose_pieces):
                    piece_text = f"{cleaned_title}\n\n{piece}".strip()
                    if len(piece_text) > 20:
                        chunk_id = str(
                            uuid.uuid5(
                                uuid.NAMESPACE_DNS,
                                f"{file_path.name}:{cleaned_title}:section:{len(chunks)}:{piece_text[:60]}",
                            )
                        )
                        chunks.append(
                            {
                                "id": chunk_id,
                                "text": piece_text,
                                "metadata": {
                                    "source": file_path.name,
                                    "section": cleaned_title,
                                    "category": category,
                                    "chunk_type": "section",
                                },
                            }
                        )

        logger.info(f"Parsed {len(chunks)} structure-aware knowledge chunks from {file_path.name}")
        return chunks

    def ingest_file(self, file_path: Path) -> int:
        """
        Parse and index a single Markdown file into Qdrant & BM25.

        Args:
            file_path: Path to knowledge markdown document.

        Returns:
            Number of points indexed.
        """
        chunks = self.parse_markdown(file_path)
        return self.retriever.upsert_chunks(chunks)

    def ingest_directory(self, dir_path: Path) -> int:
        """
        Index all markdown (.md) documents within a directory.

        Args:
            dir_path: Path to directory containing knowledge files.

        Returns:
            Total points indexed across all files.
        """
        total = 0
        for md_file in dir_path.glob("*.md"):
            total += self.ingest_file(md_file)
        return total


# Singleton pipeline instance
ingestion_pipeline = KnowledgeIngestionPipeline()
