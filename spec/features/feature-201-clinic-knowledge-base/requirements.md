# Requirements: Feature 2.1 — Egyptian Clinic Knowledge Base Document

## 1. Functional Requirements

### FR-1: Clinic Profile & Administrative Grounding
- **FR-1.1**: The document MUST define the clinic brand as **مجمع عيادات النور التخصصي** (Al-Nour Specialized Clinics) with central hotline `19876` and WhatsApp/mobile `01012345678`.
- **FR-1.2**: The document MUST detail all 5 operational branches across Greater Cairo: Maadi (المعادي - المركز الرئيسي), Nasr City (مدينة نصر), New Cairo (التجمع الخامس), Dokki (الدقي), and Sheikh Zayed (الشيخ زايد).
- **FR-1.3**: The document MUST specify operating hours: Saturday to Thursday (9:00 AM – 11:00 PM) and Friday (2:00 PM – 10:00 PM).

### FR-2: Medical Specialties & Clinical Departments
- **FR-2.1**: The document MUST cover all core clinical specialties:
  - Cardiology & Vascular Medicine (أمراض القلب والأوعية الدموية)
  - Orthopedic Surgery & Joints (جراحة العظام والمفاصل)
  - Pediatrics & Neonatology (طب الأطفال وحديثي الولادة)
  - Internal Medicine & Gastroenterology (الباطنة والجهاز الهضمي)
  - Dentistry & Oral Surgery (طب وجراحة الفم والأسنان)
  - Dermatology & Cosmetology (الجلدية والتجميل)
  - Ophthalmology (طب وجراحة العيون)
  - ENT / Ear, Nose & Throat (الأنف والأذن والحنجرة)
  - Obstetrics & Gynecology (النساء والتوليد)
  - Neurology (المخ والأعصاب)
- **FR-2.2**: Each specialty section MUST list typical symptoms treated, diagnostic procedures offered, and clinic equipment.

### FR-3: Doctor Roster & Pricing Consistency
- **FR-3.1**: Doctor profiles, credentials (Professors, Consultants, Specialists), and examination/consultation fees MUST align with `scripts/seed_clinic_db.py`.
- **FR-3.2**: The document MUST explicitly state the **14-day consultation (إعادة كشف / استشارة) validity window** from the original examination date.
- **FR-3.3**: Payment methods MUST be detailed: Cash (كاش), Credit/Debit cards (فيزا وماستركارد), Meeza (ميزة), and installment services (ValU, Souhoola).

### FR-4: Diagnostic Lab & Radiology Preparation Guidelines
- **FR-4.1**: The document MUST define patient preparation instructions for blood tests:
  - Fasting Blood Sugar (سكر صائم): 8 hours fasting (water permitted).
  - Lipid Profile (دهون وكوليسترول): 10–12 hours fasting.
  - Complete Blood Count (CBC / صورة دم كاملة): No fasting required.
  - HbA1c (السكر التراكمي): No fasting required.
  - Liver / Kidney Function (وظائف كبد وكلى): 6–8 hours fasting.
- **FR-4.2**: The document MUST define imaging preparation:
  - Abdominal Ultrasound (سونار بطن): 6–8 hours fasting, avoid fatty foods.
  - Pelvic Ultrasound (سونار حوض): Full urinary bladder (drink 1 liter water 1 hour prior, do not void).
  - X-Ray & MRI: Removal of metallic accessories, safety screening for metal implants/pacemakers.

### FR-5: Health Insurance & Corporate Networks
- **FR-5.1**: The document MUST detail accepted insurance providers: MetLife, AXA, Bupa, Misr Insurance, Gig, MedNet, Allianz, NextCare, Prime Health.
- **FR-5.2**: The document MUST state required documentation: Valid digital/plastic insurance card, national ID, and original referral or medical claim form.
- **FR-5.3**: Co-payment (نسبة التحمل) guidelines MUST be explained (typically 0% to 20% according to patient policy tier).

### FR-6: Shift Booking & Queue Etiquette
- **FR-6.1**: The document MUST explain the clinic queue mechanism: First-come first-served queue numbers (نمرة الحجز) within the doctor's shift window.
- **FR-6.2**: Recommendation for patients to arrive 15 to 30 minutes before the shift starting hour.
- **FR-6.3**: Cancellation and rescheduling policies (at least 2 hours prior to shift commencement).

### FR-7: Medical Safety & Liability Guardrails
- **FR-7.1**: The document MUST state a strict prohibition on medical diagnosis or drug prescriptions over the telephone.
- **FR-7.2**: The document MUST define red-flag emergency symptoms requiring immediate ambulance dispatch (`123`) or urgent hospital emergency room visits:
  - Severe acute chest pain or pressure radiating to left arm/jaw.
  - Sudden facial drooping, arm weakness, or slurred speech (stroke signs).
  - Severe difficulty breathing or choking.
  - Heavy uncontrolled bleeding or acute traumatic injury.

### FR-8: Egyptian Dialect Caller FAQs
- **FR-8.1**: The document MUST include realistic caller questions phrased in colloquial Egyptian Arabic paired with helpful, structured responses.

---

## 2. Non-Functional Requirements (NFR)

- **NFR-1 (Semantic Density & Structure)**: The document MUST follow standard markdown heading hierarchies (`#`, `##`, `###`) and structured tables to ensure clean text chunking (300–500 tokens) during vector ingestion.
- **NFR-2 (Bilingual Terminology)**: Clinical terms MUST be provided in both Arabic and English to support multilingual search queries.
- **NFR-3 (Zero Hallucination)**: All numerical values, hours, and fees MUST be strictly factual and mutually consistent.

---

## 3. Constraints

- MUST NOT contain placeholder text, "lorem ipsum", or unpopulated table cells.
- MUST NOT prescribe medications or specify dosages.
- MUST reside in `knowledge_base/clinic_kb.md`.
