# Validation Criteria: Feature 2.3 — Knowledge Retrieval Verification & Tests (`tests/test_clinic_rag.py`)

## 1. Success Definition
Feature 2.3 is successfully validated when:
1. `tests/test_clinic_rag.py` executes against `test_clinic_kb` on Qdrant Cloud and passes 100% of test cases without failures or skipped assertions.
2. Colloquial Egyptian clinical queries (fasting, doctors, pricing, follow-up, insurance) achieve cosine similarity >= 0.40 and retrieve accurate department facts.
3. Medical guardrails and emergency protocols (chest pain, prohibition of drug prescriptions) are successfully retrieved.
4. Category filtering and prompt context formatting limits (< 1200 characters) are verified.
5. Median semantic retrieval time complies with the voice agent latency budget (< 150ms).
6. Zero regressions across the existing test suite (all database tests pass).
7. Code quality and linting checks pass cleanly via `ruff`.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification (Embedding & Formatter Units)
- [x] **Embedding Dimension & Non-Zero Vectors**:
  - Verify that `embedding_service.embed_query` and `embed_documents` produce vectors of length 384 with valid non-zero float values.
- [x] **Context Truncation Boundary**:
  - Verify `get_context_for_query` enforces strict character bounds (`max_chars=1200`) and properly prefixes sections.

### Tier 2: Integration Verification (Qdrant Cloud & Colloquial Clinical Queries)
- [x] **Document Ingestion into Test Collection**:
  - Test fixture successfully provisions `test_clinic_kb` on Qdrant Cloud and ingests all chunks from `knowledge_base/clinic_kb.md`.
- [x] **Egyptian Dialect Retrieval**:
  - Verify fasting query: `"هو أنا لازم أكون صايم قبل تحليل السكر وسونار البطن؟"` matches `lab_radiology`.
  - Verify pediatric query: `"عايز أعرف دكتور الأطفال بيبقى موجود امتى وتكلفة الكشف كام؟"` matches pediatric doctor and fee.
  - Verify 14-day consultation query: `"لو كشفت النهاردة، الاستشارة المجانية مدتها قد إيه؟"` matches `pricing`.
  - Verify insurance query: `"هل العيادات بتقبل كارت تأمين أكسا أو ميتلايف؟"` matches `insurance`.
- [x] **Medical Safety & Emergency Protocol Retrieval**:
  - Verify chest pain query retrieves emergency escalation (Hotline 123).
  - Verify medication request query retrieves strict diagnostic and prescription prohibition guardrails.

### Tier 3: Error & Edge-Case Verification (Unrelated & Boundary Queries)
- [x] **Completely Unrelated Queries**:
  - Query with irrelevant topic (e.g. `"سعر بيتزا مارجريتا حجم كبير"`) returns low relevance score or empty hits when `score_threshold=0.5` is set.
- [x] **Category Filter Isolation**:
  - Verify searching with `category="insurance"` returns exclusively hits where `hit["category"] == "insurance"`.

### Tier 4: Regression Checks
- [x] **Zero Regressions Across Existing Database Suite**:
  - Run `tests/test_database.py` and confirm all 6 atomic concurrency and capacity tests continue to pass (100% pass rate).

### Tier 5: Build, Lint & Type Checks
- [x] **Code Styling & Quality**:
  - Run `.venv\Scripts\ruff.exe check tests/test_clinic_rag.py` and confirm 0 lint warnings or syntax issues.

### Tier 6: Manual or Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: This feature consists of an automated test suite and vector database retrieval verification without frontend UI or visual components.

### Tier 7: API / CLI / Application Checks
- [x] **CLI Ingestion Verification**:
  - Run `.venv\Scripts\python.exe scripts/ingest_clinic_knowledge.py --kb-path knowledge_base/clinic_kb.md --test-query "مواعيد عيادة الأطفال ورسوم الكشف"` and verify exit code 0 and successful retrieval output.

---

## 3. Automated Execution Commands

```powershell
# 1. Run the new Clinic RAG test suite against Qdrant Cloud
.venv\Scripts\pytest.exe tests/test_clinic_rag.py -v

# 2. Run lint and code formatting check
.venv\Scripts\ruff.exe check tests/test_clinic_rag.py

# 3. Run regression suite for database and existing tests
.venv\Scripts\pytest.exe tests/test_database.py -v

# 4. Run CLI verification command
.venv\Scripts\python.exe scripts/ingest_clinic_knowledge.py --test-query "مواعيد عيادة الأطفال ورسوم الكشف"
```
