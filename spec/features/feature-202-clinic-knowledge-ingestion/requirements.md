# Requirements: Feature 2.2 — Vector Store Ingestion & CLI Pipeline for `clinic_kb` Collection

## 1. Functional Requirements

### FR-1: Clinical Domain Category Classification
- **FR-1.1**: The ingestion pipeline MUST classify parsed chunks into one of the following healthcare domain categories based on title and content:
  - `specialties`: Clinical departments, scopes of care, and medical services.
  - `doctors`: Attending physicians, consultants, specialists, and academic credentials.
  - `pricing`: Examination and consultation fees, 14-day follow-up rules, and payment options.
  - `lab_radiology`: Diagnostic laboratory tests, radiology, ultrasound, and patient preparation rules (fasting, hydration).
  - `insurance`: Contracted private health insurance networks, co-payment rates, and approval protocols.
  - `booking_queue`: Queue number assignment, shift arrival window, cancellation, and rescheduling terms.
  - `safety_guardrails`: Emergency triage (123), prohibition of diagnosis/prescription, and red-flag symptoms.
  - `faqs`: Common patient questions and conversational responses.
  - `general`: Clinic branches, address, working hours, and central hotlines.
- **FR-1.2**: Classification MUST support both Arabic and English keywords.

### FR-2: Markdown Parsing & Chunk Preservation
- **FR-2.1**: The parser MUST preserve markdown tables without splitting rows across different chunks.
- **FR-2.2**: Each chunk MUST retain metadata containing `source` (filename), `section` (header title), and `category`.

### FR-3: Qdrant Indexing & Collection Management
- **FR-3.1**: Ingestion MUST index chunks into the collection specified by `settings.qdrant_collection` (default `clinic_kb`).
- **FR-3.2**: The pipeline MUST support a `--recreate` flag allowing clean re-indexing without lingering or stale vectors.

### FR-4: Dedicated CLI Runner (`scripts/ingest_clinic_knowledge.py`)
- **FR-4.1**: The CLI tool MUST provide flags:
  - `--kb-path`: Path to markdown file (default `knowledge_base/clinic_kb.md`).
  - `--recreate`: Boolean flag to recreate collection before ingestion.
  - `--test-query`: Verification search query executed immediately after ingestion.
- **FR-4.2**: The CLI tool MUST output an ingestion summary:
  - Total chunks parsed and indexed.
  - Breakdown count of chunks per category.
  - Immediate verification search results with cosine similarity score and matched text snippet.

---

## 2. Non-Functional Requirements (NFR)

- **NFR-1 (Ingestion Speed)**: Ingestion of `clinic_kb.md` MUST complete in under 15 seconds including embedding generation.
- **NFR-2 (Console UTF-8 Resilience)**: CLI runner output MUST print Arabic text cleanly on Windows PowerShell/CMD without `UnicodeEncodeError`.
- **NFR-3 (Regression Immunity)**: Ingestion pipeline updates MUST NOT break existing restaurant ingestion tests or regression test suite.

---

## 3. Constraints

- MUST use existing `FastEmbed` multilingual embeddings (`paraphrase-multilingual-MiniLM-L12-v2`, 384d).
- MUST NOT introduce external heavy dependencies (e.g. LangChain, LlamaIndex).
- MUST ensure all 142 existing tests continue to pass.
