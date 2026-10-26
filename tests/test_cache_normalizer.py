"""
Unit tests for text_normalizer.py (Feature 4.2).
"""

from pathlib import Path

from src.ai_core.text_normalizer import (
    build_exact_key,
    compute_kb_version,
    normalize_query,
)


def test_strips_tashkeel_and_tatweel():
    raw = "مَوَاعِيـــدُ الْعِيَادَةِ"
    expected = "مواعيد العياده"
    assert normalize_query(raw) == expected


def test_unifies_alef_ya_ta_marbuta():
    q1 = "إمتى الأشعة؟"
    q2 = "امتي الاشعه"
    assert normalize_query(q1) == normalize_query(q2)
    assert normalize_query(q1) == "امتي الاشعه"


def test_arabic_indic_digits():
    raw = "سعر كشف الباطنة ٣٠٠ جنيه في عيادة ١"
    expected = "سعر كشف الباطنه 300 جنيه في عياده 1"
    assert normalize_query(raw) == expected


def test_strips_punctuation_and_whitespace():
    raw = "   سعر    الكشف؟!   (شامل الاستشارة)...   "
    expected = "سعر الكشف شامل الاستشاره"
    assert normalize_query(raw) == expected


def test_lowercases_english():
    raw = "  What are the CLINIC Hours?! "
    expected = "what are the clinic hours"
    assert normalize_query(raw) == expected


def test_empty_and_whitespace_only():
    assert normalize_query("") == ""
    assert normalize_query("    ") == ""
    assert normalize_query("؟،؛!") == ""


def test_exact_key_changes_with_scope():
    norm = "سعر كشف الاطفال"

    key1 = build_exact_key(norm, category="pricing", language="ar", kb_version="v100")
    key2 = build_exact_key(norm, category="specialties", language="ar", kb_version="v100")
    key3 = build_exact_key(norm, category="pricing", language="en", kb_version="v100")
    key4 = build_exact_key(norm, category="pricing", language="ar", kb_version="v200")
    key1_repeat = build_exact_key(norm, category="pricing", language="ar", kb_version="v100")

    assert len(key1) == 64
    assert key1 == key1_repeat
    assert key1 != key2
    assert key1 != key3
    assert key1 != key4


def test_kb_version_from_file(tmp_path: Path):
    test_file = tmp_path / "clinic_kb.md"
    test_file.write_text("# Knowledge Base v1", encoding="utf-8")

    v1 = compute_kb_version(test_file)
    assert len(v1) == 12
    assert all(c in "0123456789abcdef" for c in v1)

    # Content change produces different digest
    test_file.write_text("# Knowledge Base v2 with new prices", encoding="utf-8")
    v2 = compute_kb_version(test_file)
    assert len(v2) == 12
    assert v1 != v2

    # Non-existent file returns 'unknown'
    missing = tmp_path / "does_not_exist.md"
    assert compute_kb_version(missing) == "unknown"
