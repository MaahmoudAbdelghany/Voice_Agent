<div dir="rtl" align="right">

# ADR-006: مجموعة التقييم الذهبية وبوابة RAGAS في CI مع حَكَم من عائلة نماذج مختلفة

## البيانات الوصفية (Metadata)
- **Status**: Accepted
- **Date**: 2026-11-02
- **Related Feature**: Feature 4.8
- **Code References**:
  - المسارات البرمجية (Files):
    - `src/ai_core/evals.py`
    - `tests/evals/golden_dataset.json`
    - `tests/evals/test_golden_evals.py`
    - `.github/workflows/evals.yml`
  - مفاتيح الإعدادات (Config Keys in `src.config.Settings`):
    - `eval_judge_model`
    - `eval_use_live_judge`
    - `eval_faithfulness_threshold`
    - `eval_context_recall_threshold`
    - `eval_context_precision_threshold`
    - `eval_answer_relevancy_threshold`
    - `eval_structured_exact_match_threshold`
    - `eval_golden_dataset_path`
    - `eval_judge_timeout_s`

---

## السياق (Context)
أي تعديل على برومبت النظام أو إعدادات الاسترجاع الهجين (`Hybrid RAG`) أو حواجز الحماية قد يسبب انحداراً دلالياً صامتاً (`Silent Semantic Regression`): كأن يهلوس المساعد بسعر كشف غير موجود في قاعدة المعرفة، أو يفشل في تحويل مريض يعاني من ألم حاد في الصدر إلى الطوارئ، بينما تظل اختبارات الوحدات التقليدية خضراء.

لذلك نحتاج إلى بوابة تقييم آلية في CI تجمع بين **المطابقة الحتمية الصارمة للحقول المهيكلة** و**مقاييس RAGAS الرباعية** لفصل أخطاء الاسترجاع عن أخطاء التوليد.

---

## القرار (Decision)
اعتمدنا منظومة التقييم الذهبية (`GoldenEvaluationRunner`) في `src/ai_core/evals.py` ومجموعة البيانات `tests/evals/golden_dataset.json` وبوابة CI في `.github/workflows/evals.yml`:

1. **مجموعة البيانات الذهبية (`52` سيناريو طبي مصري في `golden_dataset.json`)**:
   - موزعة على أربع فئات إلزامية (`GoldenCaseCategory`): استفسارات روتينية (`routine_inquiry`)، إدارة الحجوزات (`booking_management`)، هجمات الحقن العدائية (`adversarial_injection`)، وفخاخ السلامة الطبية والطوارئ (`medical_safety_trap`).
2. **التقييم المزدوج (Structured Exact-Match + RAGAS Quartet)**:
   - **المطابقة الحتمية (`eval_structured_exact_match_threshold = 0.95`)**: مطابقة صارمة للأداة المتوقعة (`expected_tool`)، والتخصص (`expected_specialty`)، وقرار التصعيد (`expected_escalate`)، وقرار حاجز الحماية (`expected_guardrail_action`).
   - **عتبات مقاييس RAGAS الرباعية**:
     - الأمانة وعدم الهلوسة (`eval_faithfulness_threshold = 0.90`)، مع عقوبة صارمة عند ظهور أي رقم (سعر، ساعات صيام، هاتف) غير موجود في السياق المسترجع عبر `_extract_canonical_numbers`.
     - استدعاء السياق (`eval_context_recall_threshold = 0.85`).
     - دقة السياق (`eval_context_precision_threshold = 0.80`).
     - صلة الإجابة بالسؤال (`eval_answer_relevancy_threshold = 0.85`).
3. **حَكَم من عائلة نماذج مختلفة (`eval_judge_model = "openai/gpt-4o-mini"`) مع وضع حتمي للـ CI**:
   - اختيار `openai/gpt-4o-mini` كحَكَم تقييم (`LiteLLMRAGASJudge` بمهلة `eval_judge_timeout_s = 10.0` ثوانٍ و`temperature=0.0`) لأنه ينتمي لعائلة مختلفة تماماً عن نماذج التوليد في النظام (Groq Llama 3.3 وGoogle Gemini)، مما يمنع انحياز النموذج لتفضيل مخرجات عائلته (`Self-Preference Bias`).
   - دعم الحَكَم الحتمي السريع (`DeterministicRAGASJudge` عندما `eval_use_live_judge = False`) لضمان تشغيل حتمي ومجاني في البيئات التي لا يتوفر فيها مفتاح OpenAI.

---

## البدائل المرفوضة (Alternatives Rejected)
1. **استخدام نفس نموذج التوليد (`llama-3.3-70b-versatile`) كحَكَم للتقييم**:
   - *سبب الرفض*: تثبت الأدبيات الهندسية أن النماذج اللغوية تنحاز لمنح درجات أعلى لمخرجاتها أو مخرجات نفس العائلة، مما يخفي حالات الهلوسة الدقيقة.
2. **الاعتماد على LLM-as-a-Judge فقط دون فحوصات المطابقة الحتمية للأرقام والأدوات**:
   - *سبب الرفض*: قد يمنح الحَكَم اللغوي درجة عالية لإجابة تبدو بليغة بالعامية المصرية حتى لو أخطأت في سعر الكشف (`350` بدل `400` جنيه) أو نسيت تفعيل `expected_escalate` في حالة طوارئ.
3. **تشغيل تقييم RAGAS الحي على كل Commit في كل ملف من المستودع**:
   - *سبب الرفض*: يرفع التكلفة ويبطئ CI؛ لذلك جرى تقييد `.github/workflows/evals.yml` بمسارات محددة (`src/ai_core/**`، `src/rag/**`، `src/agent/**`، `src/tools/**`، `knowledge_base/**`).

---

## العواقب (Consequences)
### الإيجابيات (Positive)
- كشف فوري لمصدر أي تراجع في الجودة: انخفاض `Context Recall` يعني مشكلة في `Hybrid RAG`، بينما انخفاض `Faithfulness` يعني مشكلة في البرومبت أو التوليد.
- نشر بطاقة نتائج Markdown مفصّلة تلقائياً في ملخص GitHub Actions (`GITHUB_STEP_SUMMARY`) مع كل تشغيل.

### السلبيات والمقايضات (Negative / Trade-offs)
- أي إضافة لطبيب جديد أو تغيير في أسعار `clinic_kb.md` يتطلب تحديث السيناريوهات المقابلة في `tests/evals/golden_dataset.json` للحفاظ على دقة المرجع الذهبي.

</div>
