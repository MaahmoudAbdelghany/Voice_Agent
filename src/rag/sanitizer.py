"""
Ingestion-Time Knowledge Base Document Sanitizer (OWASP LLM01).

Provides surgical multi-layer sanitization of Markdown knowledge documents
before chunking and vector/BM25 indexing to neutralize indirect prompt injection,
hidden HTML comments, invisible/BiDi-override Unicode characters, external image
exfiltration links, and XML delimiter breakout tags while preserving legitimate
Markdown tables and <br> line breaks.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# 1. HTML comments: <!-- ... -->
_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")

# 2. Dangerous HTML blocks (<script>, <style>, <iframe>, <object>, <embed>)
_DANGEROUS_HTML_BLOCK_RE = re.compile(
    r"<\s*(script|style|iframe|object|embed)\b[^>]*>[\s\S]*?<\s*/\s*\1\s*>",
    re.IGNORECASE,
)

# Standalone dangerous HTML tags (excluding <br> / <br/>)
_DANGEROUS_HTML_TAG_RE = re.compile(
    r"<\s*/?\s*(script|style|iframe|object|embed|meta|link|form|input)\b[^>]*>",
    re.IGNORECASE,
)

# 3. Invisible and BiDi-override Unicode characters (Zero-width, RLO/LRO, BOM)
_INVISIBLE_UNICODE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")

# 4. External Markdown image exfiltration links: ![alt](http://... or https://...)
_MD_IMAGE_EXFIL_RE = re.compile(r"!\[[^\]]*\]\(\s*https?://[^)]+\)", re.IGNORECASE)

# 5. XML delimiter breakout tags reserved for trust boundaries
_XML_DELIMITER_TAG_RE = re.compile(
    r"<\s*/?\s*(caller_utterance|retrieved_context|system_instructions|system)\s*>",
    re.IGNORECASE,
)

# 6. Bilingual indirect prompt injection patterns (English & Arabic)
_INDIRECT_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above|system)\s+"
        r"(?:instructions|rules|prompts|directives)[^\n|]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:system\s+override|system\s+prompt|developer\s+mode|admin\s+override)\s*:"
        r"[^\n|]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"you\s+are\s+now\s+in\s+(?:developer|admin|unrestricted|jailbreak)\s+mode[^\n|]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"new\s+system\s+instruction\s*:[^\n|]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:تجاهل|انسى|ألغِ|الغي)\s+(?:كل\s+|جميع\s+)?(?:التعليمات|الأوامر|القواعد)\s+"
        r"(?:السابقة|السابقه|النظام)[^\n|]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:أنت|انت)\s+الآن\s+في\s+وضع\s+(?:المطور|الأدمن|الادمن|غير\s+مقيد)[^\n|]*",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:تعليمات\s+نظام\s+جديدة|تجاوز\s+النظام)\s*:[^\n|]*",
        re.IGNORECASE,
    ),
]


class SanitizationFinding(BaseModel):
    """Record of a specific threat category stripped during document sanitization."""

    category: str = Field(description="Threat category identifier.")
    description: str = Field(description="Human-readable description of stripped content.")
    count: int = Field(default=1, ge=1, description="Number of occurrences stripped.")


class SanitizationReport(BaseModel):
    """Structured audit report returned by DocumentSanitizer."""

    sanitized_text: str = Field(description="Cleaned document text safe for chunking and indexing.")
    is_modified: bool = Field(default=False, description="True if any threat pattern was stripped.")
    total_findings: int = Field(
        default=0, ge=0, description="Total number of threat occurrences stripped."
    )
    findings: list[SanitizationFinding] = Field(
        default_factory=list,
        description="Breakdown of findings by threat category.",
    )


class DocumentSanitizer:
    """
    Surgical multi-layer sanitizer for clinic knowledge base documents.

    Strips:
    1. HTML comments (<!-- ... -->)
    2. Executable/hidden HTML blocks (<script>, <style>, <iframe>, <object>)
    3. Invisible & BiDi-override Unicode characters (Zero-width, RLO/LRO)
    4. External Markdown image exfiltration links (![...](https://...))
    5. Reserved XML boundary breakout tags (<caller_utterance>, <retrieved_context>)
    6. Bilingual indirect prompt injection instructions

    Preserves:
    - Markdown headers, bullet lists, and tables (| ... |)
    - Legitimate <br> line-break tags inside table cells
    - Arabic diacritics (tashkeel) and standard punctuation
    """

    def sanitize(self, text: str) -> SanitizationReport:
        """
        Inspect and sanitize raw markdown or chunk text, returning a SanitizationReport.
        """
        if not text:
            return SanitizationReport(
                sanitized_text="",
                is_modified=False,
                total_findings=0,
                findings=[],
            )

        working = text
        findings: list[SanitizationFinding] = []

        # 1. Strip HTML comments
        working, count = _HTML_COMMENT_RE.subn("", working)
        if count > 0:
            findings.append(
                SanitizationFinding(
                    category="html_comment",
                    description="Stripped hidden HTML comment block(s)",
                    count=count,
                )
            )

        # 2. Strip dangerous HTML blocks & tags (preserving <br>)
        working, block_count = _DANGEROUS_HTML_BLOCK_RE.subn("", working)
        working, tag_count = _DANGEROUS_HTML_TAG_RE.subn("", working)
        html_total = block_count + tag_count
        if html_total > 0:
            findings.append(
                SanitizationFinding(
                    category="dangerous_html",
                    description="Stripped executable or hidden HTML tag(s)/block(s)",
                    count=html_total,
                )
            )

        # 3. Strip invisible & BiDi-override Unicode characters
        working, uni_count = _INVISIBLE_UNICODE_RE.subn("", working)
        if uni_count > 0:
            findings.append(
                SanitizationFinding(
                    category="invisible_unicode",
                    description="Stripped zero-width or bidirectional-override Unicode characters",
                    count=uni_count,
                )
            )

        # 4. Strip external Markdown image exfiltration links
        working, img_count = _MD_IMAGE_EXFIL_RE.subn("", working)
        if img_count > 0:
            findings.append(
                SanitizationFinding(
                    category="markdown_exfiltration",
                    description="Stripped external Markdown image exfiltration link(s)",
                    count=img_count,
                )
            )

        # 5. Strip XML delimiter breakout tags
        working, xml_count = _XML_DELIMITER_TAG_RE.subn("", working)
        if xml_count > 0:
            findings.append(
                SanitizationFinding(
                    category="xml_delimiter_breakout",
                    description="Stripped reserved XML trust-boundary delimiter tag(s)",
                    count=xml_count,
                )
            )

        # 6. Strip indirect prompt injection directives
        inj_count = 0
        for pattern in _INDIRECT_INJECTION_PATTERNS:
            working, c = pattern.subn("", working)
            inj_count += c

        if inj_count > 0:
            findings.append(
                SanitizationFinding(
                    category="indirect_prompt_injection",
                    description="Stripped embedded indirect prompt injection instruction(s)",
                    count=inj_count,
                )
            )

        # Clean up excessive blank lines left behind by stripped blocks (preserving table lines)
        if findings:
            working = re.sub(r"\n{3,}", "\n\n", working)

        total = sum(f.count for f in findings)
        if total > 0:
            logger.warning(
                "DocumentSanitizer stripped %d threat occurrence(s) across %d category(ies): %s",
                total,
                len(findings),
                [f.category for f in findings],
            )

        return SanitizationReport(
            sanitized_text=working,
            is_modified=total > 0,
            total_findings=total,
            findings=findings,
        )

    def sanitize_text(self, text: str) -> str:
        """Convenience wrapper returning only the sanitized string."""
        return self.sanitize(text).sanitized_text


# Global singleton instance
document_sanitizer = DocumentSanitizer()

__all__ = [
    "DocumentSanitizer",
    "SanitizationFinding",
    "SanitizationReport",
    "document_sanitizer",
]
