"""
Knowledge Base Ingestion Pipeline.

Parses markdown domain knowledge files, applies header-aware semantic chunking,
attaches rich metadata, and indexes chunks into the Qdrant vector store.
"""

import logging
import re
from pathlib import Path
from typing import Any

from src.rag.retriever import retriever

logger = logging.getLogger(__name__)


class KnowledgeIngestionPipeline:
    """
    Splits, transforms, and ingests markdown knowledge documents into Qdrant.
    """

    def __init__(self, target_retriever=None):
        self.retriever = target_retriever or retriever

    def _infer_category(self, section_title: str, text: str) -> str:
        """Categorize chunk for filtered vector lookups supporting English and Egyptian Arabic."""
        lower_title = section_title.lower()
        lower_text = text.lower()

        # Healthcare: Safety & Emergency guardrails
        safety_keywords = [
            "safety", "emergency", "guardrail", "red-flag", "triage", "ambulance", "123", "١٢٣",
            "سلامة", "سلامه", "طوارئ", "طوارىء", "إسعاف", "اسعاف", "محاذير", "تحذير",
            "حظر", "حظر التشخيص", "روشتة", "روشته", "أعراض حمراء", "اعراض حمراء", "خط الطوارئ", "خط الطوارىء",
        ]

        # Healthcare: Caller FAQs
        faq_keywords = [
            "faq", "frequently", "caller", "أسئلة شائعة", "اسئلة شائعة", "أسئلة", "اسئلة", "استفسارات",
        ]

        # Healthcare: Health Insurance & Co-payments
        insurance_keywords = [
            "insurance", "network", "co-payment", "co-pay", "approval", "pre-authorization",
            "bupa", "axa", "metlife", "allianz", "nextcare", "prime health", "care plus", "globemed",
            "تأمين", "تامين", "شبكات التأمين", "شبكات التامين", "شركات التأمين", "شركات التامين",
            "أكسا", "اكسا", "ميتلايف", "بوبا", "مصر للتأمين", "مصر للتامين", "كارنيه", "تحمل",
            "نسبة تحمل", "نسبه تحمل", "موافقة مسبقة", "موافقه مسبقه", "تحويل طبي",
        ]

        # Healthcare: Lab & Radiology Diagnostic Tests & Prep
        lab_radiology_keywords = [
            "lab", "radiology", "x-ray", "ultrasound", "sonar", "fasting", "dexa", "urine", "stool",
            "blood", "test", "fbs", "ppbs", "hba1c", "cbc", "esr", "crp", "creatinine", "lipid",
            "تحاليل", "تحليل", "معمل", "أشعة", "اشعة", "اشعه", "سونار", "رنين", "مقطعية", "مقطعيه",
            "صيام", "صائم", "فاطر", "تراكمي", "بول", "براز", "عينة", "عينه", "وظائف كبد", "وظائف كلى",
            "وظائف الكبد", "وظائف الكلى", "سكر صائم", "سكر فاطر", "دهون", "كوليسترول", "رسم قلب", "هولتر",
        ]

        # Healthcare: Booking, Queue, Shifts & Attendance
        booking_queue_keywords = [
            "queue", "shift", "turn", "reschedule", "attendance", "cancellation", "appointment",
            "طابور", "نمرة", "نمره", "رقم الكشف", "شيفت", "شفت", "أسبقية", "اسبقية", "حضور",
            "تأخير", "تاخير", "إلغاء", "الغاء", "تعديل الموعد", "إعادة جدولة", "اعادة جدولة",
            "مواعيد الحضور", "كود حجز",
        ]

        # Healthcare: Pricing & Consultation Policy
        pricing_keywords = [
            "pricing", "fee", "cost", "consultation", "payment", "installment", "cash", "visa",
            "valu", "souhoola", "aman", "forsa", "follow-up",
            "سعر", "أسعار", "اسعار", "كشف", "استشارة", "استشاره", "رسوم", "14 يوم", "١٤ يوم",
            "طرق الدفع", "وسائل الدفع", "نظم الدفع", "كاش", "فيزا", "ماستركارد", "تقسيط",
            "فاليو", "سهولة", "سهوله", "أمان", "امان", "فرصة", "فرصه", "إعادة كشف", "اعادة كشف",
        ]

        # Healthcare: Doctors & Consultants
        doctors_keywords = [
            "doctor", "physician", "consultant", "specialist", "faculty", "staff",
            "أطباء", "اطباء", "طبيب", "دكتور", "د.", "استشاري", "استشارية", "استشاريه",
            "أخصائي", "أخصائية", "اخصائي", "اخصائية", "اخصائيه", "جدول الأطباء", "جدول الاطباء",
            "درجات علمية", "درجه علميه", "دكتوراه", "زمالة", "بورد",
        ]

        # Healthcare: General Clinic Info & Branches
        general_clinic_keywords = [
            "branch", "address", "location", "hours", "hotline", "knowledge base", "operational",
            "معلومات عامة", "معلومات عامه", "فروع", "فرع", "مواعيد العمل", "المركز الرئيسي",
            "المعادي", "مدينة نصر", "مدينه نصر", "التجمع", "الدقي", "المهندسين", "الشيخ زايد",
            "الخط الساخن", "19876", "واتساب", "تليفون", "الدليل التشغيلي", "قاعدة المعرفة",
        ]

        # Healthcare: Specialties & Clinical Services
        specialties_keywords = [
            "specialties", "department", "clinic", "cardiology", "orthopedic", "pediatric",
            "internal medicine", "dentist", "obstetric", "gynecology", "dermatology",
            "ophthalmology", "ent", "neurology",
            "تخصصات", "الأقسام", "اقسام", "عيادة", "عيادات",
            "قلب", "أوعية", "اوعية", "عظام", "مفاصل", "أطفال", "اطفال", "مبتسرين",
            "حديثي الولادة", "حديثي الولاده", "باطنة", "باطنه", "جهاز هضمي", "كبد",
            "أسنان", "اسنان", "نساء وتوليد", "نساء", "توليد", "جلدية", "جلديه", "ليزر",
            "عيون", "أنف وأذن", "انف واذن", "مخ وأعصاب", "مخ واعصاب",
        ]

        # Legacy restaurant keywords
        menu_keywords = [
            "menu", "shawarma", "grill", "mezza", "salad", "dessert", "beverage",
            "منيو", "قائمة الطعام", "شاورما", "مشاوي", "مقبلات", "سلطات", "حلويات", "مشروبات",
            "ساندوتش", "سندوتش", "وجبات", "وجبة", "فتة", "عصائر",
        ]
        allergen_keywords = [
            "allergen", "dietary", "vegan", "vegetarian", "gluten", "halal", "nut",
            "حساسية", "مسببات", "دايت", "نباتي", "جلوتين", "حلال", "مكسرات", "ألبان", "بيض", "ثومية", "تومية",
        ]
        delivery_keywords = [
            "delivery", "shipping", "توصيل", "دليفري", "أوردر", "اوردر", "شحن",
        ]
        reservation_keywords = [
            "table", "party", "walk-in", "ترابيزة", "ترابيزات", "طاولة", "طاولات", "عيد ميلاد", "أفراح",
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
        elif any(k in lower_title for k in faq_keywords) or bool(re.match(r"^س\s*\d+", lower_title)) or lower_title.startswith("س:"):
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
        Parses a Markdown file using header-based section splitting.
        Preserves Markdown tables and list contexts within sections.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Knowledge base file not found: {file_path}")

        content = file_path.read_text(encoding="utf-8")

        # Split by level 2 and 3 headers (## and ###)
        header_pattern = re.compile(r"^(#{2,3}\s+.+)$", re.MULTILINE)
        splits = header_pattern.split(content)

        chunks: list[dict[str, Any]] = []

        # If content has header splits:
        if len(splits) > 1:
            for i in range(1, len(splits), 2):
                header = splits[i].strip()
                body = splits[i + 1].strip() if (i + 1) < len(splits) else ""
                
                # Clean header formatting: '## 2. Menu' -> '2. Menu'
                cleaned_title = re.sub(r"^#{2,3}\s*", "", header).strip()
                combined_chunk = f"{cleaned_title}\n\n{body}".strip()

                if len(combined_chunk) > 20:  # ignore empty or tiny headers
                    category = self._infer_category(cleaned_title, body)
                    chunks.append({
                        "text": combined_chunk,
                        "metadata": {
                            "source": file_path.name,
                            "section": cleaned_title,
                            "category": category,
                        }
                    })
        else:
            # Fallback for plain text or markdown without subheadings
            category = self._infer_category("General", content)
            chunks.append({
                "text": content.strip(),
                "metadata": {
                    "source": file_path.name,
                    "section": "General",
                    "category": category,
                }
            })

        logger.info(f"Parsed {len(chunks)} knowledge chunks from {file_path.name}")
        return chunks

    def ingest_file(self, file_path: Path) -> int:
        """
        Parse and index a single Markdown file into Qdrant.
        
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
