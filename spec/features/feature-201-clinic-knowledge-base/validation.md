# Validation Criteria: Feature 2.1 — Egyptian Clinic Knowledge Base Document

## 1. Success Definition
Feature 2.1 is successful when:
1. `knowledge_base/clinic_kb.md` is authored, fully populated, and verified to contain all 9 required domain sections without placeholders or missing data.
2. The document demonstrates high semantic density, structured tables, and bilingual terminology across all clinical specialties and lab/imaging prep instructions.
3. Doctor names, specialties, and examination fees in `knowledge_base/clinic_kb.md` are 100% consistent with `scripts/seed_clinic_db.py`.
4. Medical safety guardrails and emergency redirection to hotline `123` are prominently documented.
5. All 142 existing regression tests in the repository continue to pass without regression.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification (Content & Structure Verification)
- [x] **Section Completeness Verification**:
  - Verify existence and headings for all 9 sections:
    1. Overview & Branches
    2. Medical Specialties
    3. Doctors & Credentials
    4. Pricing & Follow-up Rules
    5. Lab & Radiology Prep
    6. Health Insurance
    7. Shift Booking & Queue Etiquette
    8. Medical Safety Guardrails
    9. Egyptian Arabic FAQs
- [x] **Document Length & Density**:
  - Verify document contains at least 2,500 words (verified: 3,802 words) and comprehensive clinical detail suitable for RAG chunking.
- [x] **Markdown Table & Formatting Integrity**:
  - Verify all markdown tables (specialties, fees, lab preparation, insurance) parse cleanly without broken pipes or unclosed tags.

### Tier 2: Integration Verification (Cross-Reference Consistency)
- [x] **Database Seeder Entity Alignment**:
  - Verify all 5 core specialties from `scripts/seed_clinic_db.py` (Cardiology, Orthopedics, Pediatrics, Internal Medicine, Dentistry) are fully represented with matching names.
  - Verify examination fees (e.g. 500, 450, 400, 350, 300, 250 EGP) match the database profiles.
  - Verify consultation validity window (14 days) is clearly stated.

### Tier 3: Error & Edge-Case Verification (Medical Safety & Guardrails)
- [x] **Zero-Diagnosis & Emergency Disclaimers**:
  - Verify presence of explicit statements prohibiting telephone prescription and medical diagnosis.
  - Verify presence of emergency symptoms triage (chest pain, stroke signs, severe dyspnea) with immediate hotline `123` redirection.
- [x] **Preparation Instructions Specificity**:
  - Verify exact fasting hours are documented for blood tests (fasting sugar: 8h, lipids: 10-12h).
  - Verify full bladder instruction is documented for pelvic ultrasound.

### Tier 4: Regression Checks
- [x] **Zero Regression Across Existing Modules**:
  - Run the full project test suite (`pytest tests/`) and confirm all 142 existing tests pass cleanly (100% pass rate).

### Tier 5: Build, Lint & Type Checks
- [x] **UTF-8 & Formatting Integrity**:
  - Verify file is valid UTF-8 without byte order mark (BOM) or corrupted Arabic characters.

### Tier 6: Manual / Visual Verification
- [x] **Egyptian Colloquial Tone & Human Inspection**:
  - Inspect Section 9 FAQs to ensure phrasing is natural, warm, and authentic Egyptian Arabic (e.g. "أهلاً بحضرتك", "يا فندم", "منور العيادة", "تحت أمرك").

### Tier 7: API / CLI / Application Checks
- **Status**: Not Applicable
- **Technical Justification**: This feature delivers an authoritative markdown knowledge base document rather than an executable application service or HTTP endpoint. Downstream vector ingestion and retrieval CLI checks will be validated in Feature 2.2 and Feature 2.3.

---

## 3. Automated Execution Commands

```powershell
# 1. Verify document presence, section headers, and word count
.venv\Scripts\python.exe -c "
from pathlib import Path
p = Path('knowledge_base/clinic_kb.md')
assert p.exists(), 'File missing'
text = p.read_text(encoding='utf-8')
words = len(text.split())
print(f'Total words: {words}')
assert words >= 2500, f'Word count too low: {words}'
for sec in range(1, 10):
    assert f'## {sec}.' in text, f'Missing section {sec}'
print('All 9 sections present and word count verified!')
"

# 2. Run full regression test suite
.venv\Scripts\pytest.exe -v
```
