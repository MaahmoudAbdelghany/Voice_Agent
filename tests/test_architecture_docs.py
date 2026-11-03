"""
Automated Architecture Documentation & ADR Drift Guard (Feature 4.9).

Verifies that:
1. All 9 Architecture Decision Records (`spec/adr/001..009-*.md`) exist and are
   indexed in `spec/adr/README.md`, alongside `spec/adr/template.md`.
2. Every ADR includes the mandatory Metadata fields (`Status`, `Date`,
   `Related Feature`, `Code References`), the 4 bilingual section headings
   (`(Context)`, `(Decision)`, `(Alternatives Rejected)`, `(Consequences)`),
   and at least 2 numbered rejected alternatives.
3. Every repository file path listed under an ADR's `Code References` exists on disk.
4. Every configuration key listed under an ADR's `Code References` is an actual
   field on `src.config.Settings` (`Settings.model_fields`).
5. `spec/architecture.md` exists, contains the RTL wrapper, includes the
   Technical Debt section and links to all 9 ADRs, defines `classDef planned`,
   and contains exactly 6 Mermaid diagrams matching the required C4 diagram types.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = REPO_ROOT / "spec" / "adr"
ARCH_DOC = REPO_ROOT / "spec" / "architecture.md"

EXPECTED_ADR_FILES: tuple[str, ...] = (
    "001-hybrid-search-rrf.md",
    "002-deterministic-gates-vs-prompt-rules.md",
    "003-multi-tier-model-gateway.md",
    "004-self-hosted-langfuse-tracing.md",
    "005-finops-budgets-and-stage-routing.md",
    "006-ragas-ci-evaluation.md",
    "007-owasp-trust-layer.md",
    "008-three-tier-cache-ladder.md",
    "009-state-machine-over-agent-loop.md",
)

REQUIRED_METADATA_MARKERS: tuple[str, ...] = (
    "**Status**:",
    "**Date**:",
    "**Related Feature**:",
    "**Code References**:",
)

REQUIRED_SECTION_MARKERS: tuple[str, ...] = (
    "(Context)",
    "(Decision)",
    "(Alternatives Rejected)",
    "(Consequences)",
)

REPO_PATH_PREFIXES: tuple[str, ...] = (
    "src/",
    "tests/",
    "spec/",
    "knowledge_base/",
    ".github/",
    "scripts/",
)


def _extract_code_references_block(adr_text: str, adr_name: str) -> str:
    """Return the text of the Metadata / Code References block prior to the first `---`."""
    match = re.search(
        r"\*\*Code References\*\*:(.*?)(?:\n---|\n##\s)",
        adr_text,
        flags=re.DOTALL,
    )
    assert match is not None, (
        f"[{adr_name}] Missing or malformed '**Code References**:' block before first section."
    )
    return match.group(1)


def _extract_references_from_block(block: str) -> tuple[list[str], list[str]]:
    """
    Parse backticked items inside the Code References block into:
    - `repo_paths`: items starting with a known repository directory prefix or file extension
    - `config_keys`: snake_case identifiers under the Config Keys subsection
    """
    files_part = block
    config_part = ""
    if "Config Keys" in block:
        parts = block.split("Config Keys", maxsplit=1)
        files_part = parts[0]
        config_part = parts[1]

    raw_file_tokens = re.findall(r"`([^`]+)`", files_part)
    repo_paths = [
        token.strip()
        for token in raw_file_tokens
        if token.strip().startswith(REPO_PATH_PREFIXES)
        or token.strip().endswith((".py", ".md", ".json", ".yml", ".yaml", ".toml"))
    ]

    raw_cfg_tokens = re.findall(r"`([^`]+)`", config_part)
    config_keys = [
        token.strip()
        for token in raw_cfg_tokens
        if token.strip() != "src.config.Settings"
        and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token.strip())
    ]
    return repo_paths, config_keys


def _extract_mermaid_blocks(markdown_text: str) -> list[str]:
    """Extract the inner contents of all ```mermaid ... ``` fenced code blocks."""
    return [
        m.group(1).strip()
        for m in re.finditer(r"```mermaid\s*\n(.*?)```", markdown_text, flags=re.DOTALL)
    ]


def test_adr_directory_index_and_template_exist() -> None:
    """Verify `spec/adr/README.md`, `spec/adr/template.md`, and all 9 ADR files exist."""
    assert ADR_DIR.is_dir(), f"Missing ADR directory at {ADR_DIR}"

    readme_path = ADR_DIR / "README.md"
    template_path = ADR_DIR / "template.md"
    assert readme_path.is_file(), f"Missing ADR index file: {readme_path}"
    assert template_path.is_file(), f"Missing ADR template file: {template_path}"

    readme_text = readme_path.read_text(encoding="utf-8")
    template_text = template_path.read_text(encoding="utf-8")

    for marker in REQUIRED_SECTION_MARKERS:
        assert marker in template_text, (
            f"[spec/adr/template.md] Missing required section marker '{marker}'."
        )

    for adr_filename in EXPECTED_ADR_FILES:
        adr_path = ADR_DIR / adr_filename
        assert adr_path.is_file(), f"Missing expected ADR file: spec/adr/{adr_filename}"
        assert adr_filename in readme_text, (
            f"[spec/adr/README.md] ADR '{adr_filename}' is not indexed in README.md."
        )


@pytest.mark.parametrize("adr_filename", EXPECTED_ADR_FILES)
def test_adr_structure_metadata_and_sections(adr_filename: str) -> None:
    """Verify each ADR has RTL formatting, metadata headers, 4 sections, and >= 2 alternatives."""
    adr_path = ADR_DIR / adr_filename
    assert adr_path.is_file(), f"Missing ADR file: spec/adr/{adr_filename}"
    text = adr_path.read_text(encoding="utf-8")

    assert 'dir="rtl"' in text, f"[{adr_filename}] Missing Arabic RTL wrapper (<div dir=\"rtl\">)."

    for meta_marker in REQUIRED_METADATA_MARKERS:
        assert meta_marker in text, (
            f"[{adr_filename}] Missing required metadata field '{meta_marker}'."
        )

    for section_marker in REQUIRED_SECTION_MARKERS:
        heading_pattern = rf"^##\s+.*{re.escape(section_marker)}"
        assert re.search(heading_pattern, text, flags=re.MULTILINE) is not None, (
            f"[{adr_filename}] Missing required section heading containing '{section_marker}'."
        )

    alt_match = re.search(
        r"##\s+.*\(Alternatives Rejected\)(.*?)(?:\n---|\n##\s)",
        text,
        flags=re.DOTALL,
    )
    assert alt_match is not None, (
        f"[{adr_filename}] Could not isolate '(Alternatives Rejected)' section body."
    )
    numbered_items = re.findall(r"^\s*\d+\.\s+", alt_match.group(1), flags=re.MULTILINE)
    assert len(numbered_items) >= 2, (
        f"[{adr_filename}] '(Alternatives Rejected)' must list at least 2 numbered alternatives; "
        f"found {len(numbered_items)}."
    )


@pytest.mark.parametrize("adr_filename", EXPECTED_ADR_FILES)
def test_adr_code_references_exist_on_disk_and_in_settings(adr_filename: str) -> None:
    """Verify every file path and Settings config key in ADR Code References is real."""
    adr_path = ADR_DIR / adr_filename
    text = adr_path.read_text(encoding="utf-8")
    block = _extract_code_references_block(text, adr_filename)
    repo_paths, config_keys = _extract_references_from_block(block)

    assert len(repo_paths) >= 1, (
        f"[{adr_filename}] Code References must list at least one repository file path."
    )
    assert len(config_keys) >= 1, (
        f"[{adr_filename}] Code References must list at least one Settings config key."
    )

    for rel_path in repo_paths:
        target = REPO_ROOT / rel_path
        assert target.exists(), (
            f"[{adr_filename}] Referenced file path '{rel_path}' does not exist at {target}."
        )

    settings_fields = set(Settings.model_fields.keys())
    for key in config_keys:
        assert key in settings_fields, (
            f"[{adr_filename}] Referenced config key '{key}' does not exist in "
            f"src.config.Settings.model_fields."
        )


def test_adr_003_documents_gemini_fallback_and_openai_rejection() -> None:
    """Verify R1.8: ADR-003 explicitly documents Gemini fallback and why OpenAI was rejected."""
    adr_003 = (ADR_DIR / "003-multi-tier-model-gateway.md").read_text(encoding="utf-8")
    assert "gemini-2.0-flash" in adr_003, (
        "[003-multi-tier-model-gateway.md] Must reference as-built 'gemini-2.0-flash' fallback."
    )
    assert "OpenAI" in adr_003, (
        "[003-multi-tier-model-gateway.md] Must explicitly record OpenAI rejection in alternatives."
    )


def test_adr_007_links_to_threat_model() -> None:
    """Verify R1.9: ADR-007 links to `spec/security/threat_model.md`."""
    adr_007 = (ADR_DIR / "007-owasp-trust-layer.md").read_text(encoding="utf-8")
    assert "threat_model.md" in adr_007, (
        "[007-owasp-trust-layer.md] Must reference 'spec/security/threat_model.md'."
    )


def test_architecture_doc_mermaid_diagrams_and_technical_debt() -> None:
    """Verify `spec/architecture.md` has 6 valid Mermaid diagrams, planned styling, and debt log."""
    assert ARCH_DOC.is_file(), f"Missing architecture document: {ARCH_DOC}"
    text = ARCH_DOC.read_text(encoding="utf-8")

    assert 'dir="rtl"' in text, "[spec/architecture.md] Missing Arabic RTL wrapper."
    assert "classDef planned" in text, (
        "[spec/architecture.md] Missing 'classDef planned' visual styling for unbuilt components."
    )
    assert "[Planned" in text, (
        "[spec/architecture.md] Missing '[Planned]' label on unbuilt future phase components."
    )
    assert "Technical Debt" in text, (
        "[spec/architecture.md] Missing 'Technical Debt' section for legacy restaurant files."
    )
    for legacy_file in (
        "src/tools/order_status.py",
        "src/tools/reservation.py",
        "src/tools/legacy_schemas.py",
    ):
        assert legacy_file in text, (
            f"[spec/architecture.md] Technical Debt section must list '{legacy_file}'."
        )

    for adr_filename in EXPECTED_ADR_FILES:
        assert adr_filename in text, (
            f"[spec/architecture.md] Must link to '{adr_filename}'."
        )

    blocks = _extract_mermaid_blocks(text)
    assert len(blocks) == 6, (
        f"[spec/architecture.md] Expected exactly 6 Mermaid diagram blocks, found {len(blocks)}."
    )

    first_tokens = [block.splitlines()[0].strip().split()[0] for block in blocks if block]
    expected_types = [
        ("flowchart", "graph"),
        ("flowchart", "graph"),
        ("sequenceDiagram",),
        ("stateDiagram-v2", "stateDiagram"),
        ("stateDiagram-v2", "stateDiagram"),
        ("erDiagram",),
    ]
    for idx, (actual_type, allowed) in enumerate(zip(first_tokens, expected_types), start=1):
        assert actual_type in allowed, (
            f"[spec/architecture.md] Diagram #{idx} has type '{actual_type}', "
            f"expected one of {allowed}."
        )
