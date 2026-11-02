<div dir="rtl" align="right">

# ملخص مواصفات الميزة 4.8: مجموعة التقييم الذهبية وبوابة RAGAS في التكامل المستمر (Golden Evaluation Suite & RAGAS CI Gate)

تم إعداد ملفات المواصفات الثلاثة الخاصة بـ **Feature 4.8** بناءً على إجاباتك وقرارات التصميم المتفق عليها:
- خطة التنفيذ: [`plan.md`](file:///d:/AI%20Projects/Voice_Agent_For_Clinics/Voice_Agent/spec/features/feature-408-golden-evaluation-suite-ragas-ci-gate/plan.md)
- المتطلبات الوظيفية وغير الوظيفية: [`requirements.md`](file:///d:/AI%20Projects/Voice_Agent_For_Clinics/Voice_Agent/spec/features/feature-408-golden-evaluation-suite-ragas-ci-gate/requirements.md)
- معايير التحقق والاختبار (7 مستويات): [`validation.md`](file:///d:/AI%20Projects/Voice_Agent_For_Clinics/Voice_Agent/spec/features/feature-408-golden-evaluation-suite-ragas-ci-gate/validation.md)

---

## 1. ملخص خطة التنفيذ (`plan.md`)

### الهدف ولماذا (Objective & Why)
بناء **محرك تقييم قياسي متكامل وبوابة CI صارمة (Fail-Closed)** في `src/ai_core/evals.py` و`tests/evals/` و`.github/workflows/evals.yml` لمنع أي تراجع في دقة الاسترجاع أو أمان الحواجز الطبية أو دقة اختيار الأدوات قبل دمج أي تعديل في الكود:
1. **قاعدة البيانات الذهبية (`tests/evals/golden_dataset.json` — 52 سيناريو واقعي للعيادات المصرية)**:
   - تغطي 4 فئات إلزامية مستندة إلى [`clinic_kb.md`](file:///d:/AI%20Projects/Voice_Agent_For_Clinics/Voice_Agent/knowledge_base/clinic_kb.md):
     - **الاستفسارات الروتينية (`routine_inquiry`)**: مواعيد العمل، الفروع، أسعار الكشف والاستشارة، قاعدة الـ 14 يوماً للاستشارة، شركات التأمين (أكسا، ميتلايف، بوبا، ميدنت)، وتعليمات التحضير للتحاليل والأشعة (سكر صائم 8 ساعات، دهون 10-12 ساعة، تراكمي وصورة دم بدون صيام، سونار الحوض بامتلاء المثانة).
     - **حجز وإدارة المواعيد (`booking_management`)**: الاستعلام عن مواعيد الأطباء (`check_doctor_availability`)، حجز كشف جديد أو استشارة (`book_appointment`)، والاستعلام أو التأجيل أو الإلغاء (`manage_appointment`).
     - **هجمات حقن الأوامر (`adversarial_injection`)**: محاولات تجاوز التعليمات بالعربية والإنجليزية، كسر وسوم XML، وحقن الأوامر المباشر وغير المباشر.
     - **فخاخ التشخيص الطبي والطوارئ الحرجة (`medical_safety_trap`)**: أعراض الطوارئ الحمراء (ألم الصدر، ضيق التنفس، الاشتباه في جلطة أو سكتة، نزيف حاد، حرارة الرضع أقل من 3 أشهر) وطلبات وصف الأدوية والجرعات.
2. **محرك مقاييس RAGAS المزدوج ونموذج الحكم `gpt-4o-mini` (`src/ai_core/evals.py`)**:
   - يحسب المقاييس الأربعة بدون الحاجة لمكتبات PyTorch الثقيلة:
     - **Faithfulness (`>= 0.90`)**: أمانة الإجابة والتزامها التام بالسياق المسترجع وعدم اختلاق أسعار أو معلومات غير موثقة.
     - **Context Recall (`>= 0.85`)**: استرجاع كافة الحقائق المرجعية المطلوبة من قاعدة المعرفة عبر `HybridRetriever`.
     - **Context Precision (`>= 0.80`)**: دقة ترتيب المقاطع المسترجعة (`Average Precision @ K`) بحيث تأتي المقاطع الصحيحة في المراتب الأولى.
     - **Answer Relevancy (`>= 0.85`)**: مدى ارتباط الإجابة دلالياً ولفظياً بسؤال المريض.
   - يدعم وضعين عبر واجهة `RAGASJudge`:
     - **`LiteLLMRAGASJudge` (`openai/gpt-4o-mini` بدرجة حرارة `0.0`)**: يعمل عند تفعيل `eval_use_live_judge=True` أو `EVAL_LIVE_JUDGE=1` في الـ CI، ويلتزم بقاعدة **Fail-Closed** (`EvalJudgeError`) إذا فشل الاتصال أو غاب المفتاح أو عاد JSON غير صالح.
     - **`DeterministicRAGASJudge`**: حكم حتمي سريع يدمج مطابقة الحقائق والأرقام العربية مع التشابه الدلالي عبر `FastEmbed` لتشغيل الاختبارات محلياً وفي الـ CI بسرعة فائقة (`< 30 ثانية`).
3. **بوابة GitHub Actions (`.github/workflows/evals.yml`)**:
   - تعمل تلقائياً عند فتح طلبات السحب (PRs) التي تمس ملفات الـ Prompts أو `src/ai_core/**` أو `src/rag/**` أو `knowledge_base/**` أو `src/config.py`، وتنشر جدول نتائج Markdown في `$GITHUB_STEP_SUMMARY` وتمنع الدمج عند فشل أي عتبة.

---

## 2. ملخص المتطلبات (`requirements.md`)

- **R1 (قاعدة البيانات الذهبية `golden_dataset.json`)**:
  - توفير 52 سيناريو مهيكل (`GoldenEvalCase`) يشمل السؤال، السياق المرجعي، الإجابة المرجعية، الأداة المتوقعة (`expected_tool`)، التخصص المتوقع (`expected_specialty`)، علم التصعيد (`expected_escalate`)، وقرار الحاجز الأمني (`expected_guardrail_action`).
- **R2 (التطابق الحرفي للحقول المهيكلة `>= 95%`)**:
  - التحقق الحتمي من تطابق الأداة المختارة والتخصص وعلم التصعيد، مع اشتراط نسبة نجاح إجمالية لا تقل عن **`95%`** (`eval_structured_exact_match_threshold = 0.95`).
- **R3 (مقاييس RAGAS الأربعة وقاعدة Fail-Closed)**:
  - تحقيق الحدود الدنيا الإلزامية: `Faithfulness >= 0.90`، `Context Recall >= 0.85`، `Context Precision >= 0.80`، و`Answer Relevancy >= 0.85`.
  - إلقاء استثناء `EvalJudgeError` فوراً عند تعطل نموذج الحكم الحي لمنع تمرير التعديلات بصمت.
- **R4 (إعدادات `src/config.py` وبوابة `.github/workflows/evals.yml`)**:
  - تخزين جميع العتبات وإعدادات نموذج الحكم في [`src/config.py`](file:///d:/AI%20Projects/Voice_Agent_For_Clinics/Voice_Agent/src/config.py) وفق القيد المعماري `C4`، وتجهيز محرك `src/ai_core/evals.py` ليُعاد استخدامه في **Feature 6.3** (التقييم المستمر لـ 10% من مكالمات الإنتاج).

---

## 3. ملخص معايير التحقق (`validation.md`)

تم تصميم التحقق باستخدام القدرات الفعلية للمشروع (`uv`, `pytest`, `ruff`) عبر 7 مستويات:
1. **Tier 1 (اختبارات الوحدة)**: التحقق من صحة مخطط `golden_dataset.json` (52 سيناريو عبر الفئات الأربع)، منطق حساب التطابق الحرفي للحقول المهيكلة، وحساسية مقاييس RAGAS الأربعة لكشف الهلاوس السعرية وترتيب المقاطع.
2. **Tier 2 (اختبارات التكامل)**: تمرير الـ 52 سيناريو عبر المكونات الفعلية (`InputGuardrail` + `HybridRetriever` على `clinic_kb.md` + `OutputGuardrail`) والتأكد من تخطي جميع العتبات (`Exact Match >= 95%`, `Faithfulness >= 0.90`, `Recall >= 0.85`, `Precision >= 0.80`, `Relevancy >= 0.85`)، بالإضافة إلى اختبار `LiteLLMRAGASJudge` (`gpt-4o-mini`) وصحة ملف `.github/workflows/evals.yml`.
3. **Tier 3 (الحالات الحدية والأخطاء)**: اختبار قاعدة **Fail-Closed** عند انقطاع أو خطأ نموذج الحكم `gpt-4o-mini`، واختبار رفض البوابة عند هبوط أي مقياس عن الحد الأدنى، والتحقق من صد 100% من هجمات الحقن وفخاخ التشخيص والطوارئ.
4. **Tier 4 (فحص عدم الانحدار Regression)**: تشغيل جميع اختبارات المراحل 1 إلى 4 للتأكد من عدم تأثر أي ميزة سابقة.
5. **Tier 5 (فحص الكود والأنماط)**: `uv run ruff check` و`uv run ruff format --check`.
6. **Tier 6 (التحقق اليدوي/البصري)**: `Not Applicable` مع مبرر تقني (محرك تقييم خلفي وبوابة CI بدون واجهة مستخدم رسومية).
7. **Tier 7 (فحص الـ CLI المباشر)**: أمر تشغيل مباشر عبر `uv run python -c ...` لتشغيل التقييم الكامل وطباعة جدول نتائج Markdown.

</div>

