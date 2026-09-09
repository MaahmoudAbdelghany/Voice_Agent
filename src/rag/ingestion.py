"""
Knowledge Base Ingestion Pipeline.

Parses markdown domain knowledge files, applies header-aware semantic chunking,
attaches rich metadata, and indexes chunks into the Qdrant vector store.
"""

from typing import List, Dict, Any, Optional
import os
import re
import logging
from pathlib import Path
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
        
        menu_keywords = [
            "menu", "shawarma", "grill", "mezza", "salad", "dessert", "beverage", "price",
            "منيو", "قائمة", "شاورما", "مشاوي", "مقبلات", "سلطات", "حلويات", "مشروبات",
            "ساندوتش", "سندوتش", "وجبات", "وجبة", "فتة", "اسعار", "أسعار", "عصائر"
        ]
        allergen_keywords = [
            "allergen", "dietary", "vegan", "vegetarian", "gluten", "halal", "nut",
            "حساسية", "مسببات", "دايت", "نباتي", "جلوتين", "حلال", "مكسرات", "ألبان", "بيض", "ثومية", "تومية"
        ]
        delivery_keywords = [
            "delivery", "order", "shipping", "fee", "tracking", "cancel",
            "توصيل", "دليفري", "أوردر", "اوردر", "طلب", "تتبع", "إلغاء", "الغاء", "شحن", "رسوم", "مصاريف"
        ]
        reservation_keywords = [
            "reservation", "booking", "table", "party", "walk-in",
            "حجز", "ترابيزة", "ترابيزات", "طاولة", "طاولات", "حجوزات", "عيد ميلاد", "أفراح"
        ]
        faq_keywords = ["faq", "question", "أسئلة", "اسئلة", "شائعة", "استفسارات", "سؤال"]
        catering_keywords = ["cater", "event", "بوفيه", "حفلات", "عزومات", "ايفنت", "شركات"]

        # Prioritize title-based categorization for accurate section boundaries
        if any(k in lower_title for k in delivery_keywords):
            return "delivery"
        elif any(k in lower_title for k in reservation_keywords):
            return "reservations"
        elif any(k in lower_title for k in allergen_keywords):
            return "allergens"
        elif any(k in lower_title for k in catering_keywords):
            return "catering"
        elif any(k in lower_title for k in faq_keywords):
            return "faqs"
        elif any(k in lower_title for k in menu_keywords):
            return "menu"
        # Fallback to body text keyword matching
        elif any(k in lower_text for k in allergen_keywords):
            return "allergens"
        elif any(k in lower_text for k in delivery_keywords):
            return "delivery"
        elif any(k in lower_text for k in reservation_keywords):
            return "reservations"
        return "general"

    def parse_markdown(self, file_path: Path) -> List[Dict[str, Any]]:
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

        chunks: List[Dict[str, Any]] = []
        current_section = "Overview"
        
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
