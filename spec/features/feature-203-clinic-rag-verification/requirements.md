# Requirements Specification: Feature 2.3 — Knowledge Retrieval Verification & Tests

## 1. Functional Requirements

### FR1: Test Collection Provisioning & Ingestion
- The test suite must initialize a dedicated test collection `test_clinic_kb` on Qdrant Cloud (using credentials from `.env`).
- The test suite must ingest and vectorize all chunks from `knowledge_base/clinic_kb.md` into `test_clinic_kb`.
- The production collection `clinic_kb` must remain completely untouched.

### FR2: Egyptian Colloquial Clinical Queries Retrieval
- **FR2.1 (Lab & Fasting Guidelines)**:
  - Query: `"هو أنا لازم أكون صايم قبل تحليل السكر وسونار البطن؟"`
  - Expected: Top result must belong to `lab_radiology` and contain fasting guidelines (e.g., 6–8 hours for ultrasound, 8–10 hours for fasting blood sugar) with cosine similarity >= 0.40.
- **FR2.2 (Pediatric Doctor & Pricing)**:
  - Query: `"عايز أعرف دكتور الأطفال بيبقى موجود امتى وتكلفة الكشف كام؟"`
  - Expected: Top hits must reference pediatric doctor schedules (د. طارق الحسين / عيادة الأطفال) and consultation fees (كشف: 250 ج) with cosine similarity >= 0.40.
- **FR2.3 (Follow-up & Free Consultation Rule)**:
  - Query: `"لو كشفت النهاردة، الاستشارة المجانية مدتها قد إيه وممكن أعملها إزاي؟"`
  - Expected: Top result must belong to `pricing` and state the 14-day consultation policy (استشارة مجانية واحدة خلال 14 يوماً) with cosine similarity >= 0.40.
- **FR2.4 (Insurance Coverage & Network)**:
  - Query: `"هل العيادات بتقبل كارت تأمين أكسا أو ميتلايف؟"`
  - Expected: Top result must belong to `insurance` and confirm acceptance of AXA and MetLife along with co-payment rules.

### FR3: Medical Safety Guardrails & Emergency Escalation Retrieval
- **FR3.1 (Emergency Protocol Recall)**:
  - Query: `"عندي ألم حاد ومفاجئ في الصدر ومش قادر أتنفس، هل دي حالة طوارئ؟"`
  - Expected: Top result must belong to `safety_guardrails` and contain emergency escalation instructions directing the caller immediately to Hotline 123 (الإسعاف) or nearest emergency room, with score >= 0.40.
- **FR3.2 (Prohibition of Over-the-Phone Diagnosis)**:
  - Query: `"هل مسموح إعطاء استشارة علاجية أو تشخيص طبي ووصف أدوية هاتفياً؟"`
  - Expected: Top result must belong to `safety_guardrails` and contain strict medical guardrails forbidding medication prescription or medical diagnosis over the phone, with score >= 0.40.

### FR4: Category Filtering & Scoped Search
- When a search is initiated with `category="lab_radiology"`, every returned chunk must strictly have `hit["category"] == "lab_radiology"`.
- When a search is initiated with `category="insurance"`, every returned chunk must strictly have `hit["category"] == "insurance"`.

### FR5: Context String Assembly & Truncation
- Calling `get_context_for_query` with a clinical query must return non-empty formatted context.
- The returned context length must never exceed the specified `max_chars` parameter (default 1200 characters).

---

## 2. Non-Functional Requirements

### NFR1: Retrieval Latency SLA
- The semantic search duration (embedding query + vector search) must complete in `< 150ms` per query.

### NFR2: Semantic Similarity Confidence
- All relevant clinical domain queries must return a top-1 score `>= 0.40` cosine similarity.

### NFR3: Test Execution Stability
- The test suite must run idempotently without leaving lingering orphaned collections or duplicate records on repeated runs.

---

## 3. Constraints

- **C1 (Zero Mock Fabrication)**: Tests must validate against the real `knowledge_base/clinic_kb.md` and live Qdrant Cloud collection `test_clinic_kb`.
- **C2 (No Hardcoded Secrets)**: Qdrant URL and API Key must be resolved securely via `src.config.settings` from `.env`.
- **C3 (Production Isolation)**: The test collection name must strictly be isolated to `test_clinic_kb`.
