# Validation Criteria: Feature 2.2 — Vector Store Ingestion & CLI Pipeline for `clinic_kb` Collection

## 1. Success Definition
Feature 2.2 is successful when:
1. `src/rag/ingestion.py` accurately categorizes clinical sections into `specialties`, `doctors`, `pricing`, `lab_radiology`, `insurance`, `booking_queue`, `safety_guardrails`, `faqs`, and `general`.
2. `scripts/ingest_clinic_knowledge.py` executes cleanly via CLI, indexing all chunks from `knowledge_base/clinic_kb.md` into the Qdrant `clinic_kb` collection.
3. The CLI tool prints an informative breakdown of chunks per category and executes a verification query returning relevant clinical snippets with high similarity scores (> 0.50).
4. Zero regressions across the entire project test suite (142/142 tests passing).
5. Code style and lint checks pass cleanly via `ruff check`.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification (Parser & Category Classifier)
- [x] **Clinical Category Classifier**:
  - Verify that medical titles map accurately to categories (e.g. "معمل التحاليل" -> `lab_radiology`, "شركات التأمين" -> `insurance`, "قائمة الأطباء" -> `doctors`, "محاذير السلامة" -> `safety_guardrails`).
  - Verify backward compatibility for legacy restaurant categories if called.
- [x] **Markdown Table & Chunk Preservation**:
  - Verify `parse_markdown` extracts non-empty chunks with intact headers and metadata (`source`, `section`, `category`).

### Tier 2: Integration Verification (Vector Ingestion & Search)
- [x] **Full Document Ingestion**:
  - Ingest `knowledge_base/clinic_kb.md` and confirm that all extracted chunks (>= 10 chunks) are upserted into Qdrant.
- [x] **Category-Filtered Retrieval Verification**:
  - Execute filtered vector search (e.g. query with `category="lab_radiology"`) and assert matched points belong strictly to that category.

### Tier 3: Error & Edge-Case Verification (Resilience & Flags)
- [x] **Missing File Handling**:
  - Verify CLI runner exits gracefully with error code 1 when pointing to a non-existent file path.
- [x] **Collection Recreation (`--recreate`)**:
  - Verify that running with `--recreate` cleanly clears previous vectors without duplicate accumulation.

### Tier 4: Regression Checks
- [x] **Zero Regression Across Existing Modules**:
  - Run the full project test suite (`pytest tests/`) and confirm all 142 existing tests pass cleanly (100% pass rate).

### Tier 5: Build, Lint & Type Checks
- [x] **Lint & Code Style**:
  - Run `uv run ruff check scripts/ingest_clinic_knowledge.py src/rag/ingestion.py` and confirm zero lint issues.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: This feature consists of backend vector database ingestion and a CLI script without frontend GUI components.

### Tier 7: API / CLI / Application Checks
- [x] **CLI Execution Run**:
  - Execute `python scripts/ingest_clinic_knowledge.py --recreate` in terminal.
  - Assert exit code 0, positive chunk count displayed, category breakdown printed, and sample verification hits rendered.

---

## 3. Automated Execution Commands

```powershell
# 1. Run CLI ingestion script with recreation and sample query
.venv\Scripts\python.exe scripts/ingest_clinic_knowledge.py --recreate --test-query "هل لازم أكون صايم قبل تحليل السكر وسونار البطن؟"

# 2. Run full regression test suite
.venv\Scripts\pytest.exe -v

# 3. Check code style and linting
uv run ruff check scripts/ingest_clinic_knowledge.py src/rag/ingestion.py
```
