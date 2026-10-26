"""
Text Normalization and Key Generation Utilities for 3-Tier Caching Ladder.

Provides deterministic Arabic and English text normalization, SHA-256 cache key
generation, and Knowledge Base version hashing.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Arabic diacritics (tashkeel/harakat) and tatweel/kashida
_TASHKEEL_REGEX = re.compile(r"[\u064B-\u0652\u0670]")
_TATWEEL_REGEX = re.compile(r"\u0640")

# Arabic-Indic digits to ASCII digits translation table
_ARABIC_INDIC_TRANS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Punctuation to strip (Arabic and Latin punctuation & symbols)
_PUNCTUATION_REGEX = re.compile(r"[؟،؛!?:.,;\-_'\"`~()[\]{}<>/\\|+=*&^%$#@~]")

# Multiple whitespace collapsing regex
_WHITESPACE_REGEX = re.compile(r"\s+")


def normalize_query(text: str) -> str:
    """
    Apply medium Arabic and English normalization:
    1. Lowercase Latin characters.
    2. Strip Arabic tashkeel (diacritics) and tatweel (kashida).
    3. Unify Alef variants (أ / إ / آ / ٱ -> ا).
    4. Unify Alif Maqsura to Ya (ى -> ي).
    5. Unify Ta Marbuta to Ha (ة -> ه).
    6. Convert Arabic-Indic numerals (٠-٩) to ASCII digits (0-9).
    7. Strip punctuation and symbols.
    8. Collapse redundant whitespaces into a single space and strip.

    Args:
        text: Raw input query from user or STT transcript.

    Returns:
        Normalized canonical query string.
    """
    if not text:
        return ""

    # 1. Lowercase
    s = text.lower()

    # 2. Strip diacritics and tatweel
    s = _TASHKEEL_REGEX.sub("", s)
    s = _TATWEEL_REGEX.sub("", s)

    # 3. Unify Alef variants
    s = re.sub(r"[إأآٱ]", "ا", s)

    # 4. Unify Alif Maqsura (ى -> ي)
    s = s.replace("ى", "ي")

    # 5. Unify Ta Marbuta (ة -> ه)
    s = s.replace("ة", "ه")

    # 6. Convert Arabic-Indic numerals to standard ASCII digits
    s = s.translate(_ARABIC_INDIC_TRANS)

    # 7. Strip punctuation
    s = _PUNCTUATION_REGEX.sub(" ", s)

    # 8. Collapse whitespace and strip
    s = _WHITESPACE_REGEX.sub(" ", s).strip()

    return s


def build_exact_key(
    normalized_query: str,
    category: str | None,
    language: str,
    kb_version: str,
) -> str:
    """
    Generate deterministic 64-character SHA-256 hash key for Tier 1 Exact Cache.

    Format: normalized_query | category | language | kb_version
    """
    cat = (category or "").strip().lower()
    lang = (language or "ar").strip().lower()
    kb_v = (kb_version or "unknown").strip()

    composite = f"{normalized_query}|{cat}|{lang}|{kb_v}"
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()


def compute_kb_version(kb_path: str | Path) -> str:
    """
    Compute a 12-character hex SHA-256 digest of the clinic knowledge base file.
    If the file does not exist, return 'unknown' and log a warning.
    """
    path = Path(kb_path)
    if not path.exists() or not path.is_file():
        logger.warning(
            f"Knowledge base file not found at '{path}'. Caching will use kb_version='unknown'."
        )
        return "unknown"

    try:
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        return digest[:12]
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error computing knowledge base version for '{path}': {e}")
        return "unknown"
