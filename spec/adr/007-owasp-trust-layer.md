<div dir="rtl" align="right">

# ADR-007: طبقة الثقة المتوافقة مع OWASP وحواجز الحماية الفورية وتنقية PII والمصنّف غير المتزامن

## البيانات الوصفية (Metadata)
- **Status**: Accepted
- **Date**: 2026-11-02
- **Related Feature**: Feature 4.4
- **Code References**:
  - المسارات البرمجية (Files):
    - `src/ai_core/guardrails.py`
    - `src/rag/sanitizer.py`
    - `src/rag/ingestion.py`
    - `spec/security/threat_model.md`
  - مفاتيح الإعدادات (Config Keys in `src.config.Settings`):
    - `guardrails_enabled`
    - `pii_redaction_enabled`
    - `rag_sanitize_on_ingest`
    - `llama_guard_enabled`
    - `llama_guard_model`
    - `llama_guard_sample_rate`
    - `llama_guard_timeout_s`
    - `emergency_phone`

---

## السياق (Context)
يواجه المساعد الصوتي الطبي مخاطر أمنية وقانونية مزدوجة موثّقة بالتفصيل في نموذج التهديدات الرسمي [`spec/security/threat_model.md`](../security/threat_model.md):
1. **المسؤولية الطبية والقانونية (Invariant 3)**: يُحظر قطعياً تقديم أي تشخيص طبي أو وصف دواء أو جرعة علاجية عبر الهاتف، ويجب تحويل أعراض الطوارئ فوراً إلى رقم الإسعاف المصري (`emergency_phone = "123"`) وموظف الاستقبال.
2. **تهديدات OWASP LLM Top 10**: الحقن المباشر للبرومبت (`LLM01`)، والحقن غير المباشر عبر مستندات المعرفة، وتسريب البيانات الشخصية المصرية (`LLM06`).
3. **قيد الزمن الصوتي (`< 800ms`)**: لا يمكن وضع مصنّف LLM ثقيل للحماية بالتوازي المتزامن قبل كل دورة صوتية دون كسر ميزانية الاستجابة.

---

## القرار (Decision)
اعتمدنا معمارية دفاع متدرجة رباعية الطبقات في `src/ai_core/guardrails.py` و`src/rag/sanitizer.py`:

1. **حواجز الإدخال والإخراج الفورية على المعالج (`InputGuardrail` و`OutputGuardrail` — `< 20ms CPU`)**:
   - تفحص `InputGuardrail` كلام المتصل في أقل من `20ms` وتصنّفه إلى أربع إجراءات حتمية (`InputAction`):
     - `ESCALATE_EMERGENCY`: عند رصد أعراض طوارئ حرجة، توجه المريض فوراً للاتصال بالإسعاف (`123`) وتحوّله للاستقبال.
     - `BLOCK_INJECTION`: عند رصد محاولات تجاوز التعليمات أو كسر وسوم XML أو حقن SQL/Code.
     - `BLOCK_MEDICAL_ADVICE`: عند طلب تشخيص أو وصفة دوائية أو جرعة (مع التمييز الذكي لطلبات الحجز المشروعة التي يذكر فيها المريض عرضه عبر `GuardrailCategory.BOOKING_WITH_SYMPTOMS`).
     - `ALLOW`: السماح بالمرور للمسار الطبيعي.
   - تفحص `OutputGuardrail` رد النموذج للتأكد من عدم تسرب نصيحة طبية أو اسم دواء أو سعر غير مؤصل في السياق المسترجع.
2. **العزل بوسوم XML وتطهير المستندات عند الإدخال (`DocumentSanitizer`)**:
   - تغليف كلام المتصل داخل `<caller_utterance>` والسياق المسترجع داخل `<retrieved_context>` بعد تهريب أي وسوم يحاول المهاجم إغلاقها عبر `escape_xml_delimiters`.
   - تطهير ملفات المعرفة وقت الفهرسة (`rag_sanitize_on_ingest = True`) عبر `DocumentSanitizer` لإزالة التعليقات المخفية، ومحارف Unicode غير المرئية (`Zero-Width`)، وتعليمات الحقن غير المباشر.
3. **تنقية البيانات الشخصية المصرية المتوافقة مع Presidio (`EgyptianPIIRedactor` — `< 2ms CPU`)**:
   - عندما يكون `pii_redaction_enabled = True`، يتم إخفاء أرقام المحمول المصرية (`010/011/012/015` بصيغها العربية والإنجليزية) والرقم القومي المصري المكون من 14 رقماً (مع التحقق من قرن الميلاد والمحافظة) قبل كتابة أي أثر في سجلات التتبع.
4. **التصنيف الأمني بالعينات خارج المسار الحرج (`AsyncLlamaGuardClassifier`)**:
   - تشغيل `llama_guard_model = "groq/llama-guard-3-8b"` بشكل غير متزامن في الخلفية على عينة نسبتها `llama_guard_sample_rate = 0.10` (10%) وبمهلة `llama_guard_timeout_s = 3.0` ثوانٍ دون حجز أو تأخير رد المريض الصوتي.

> لتحليل التهديدات التفصيلي ومصفوفة ضوابط OWASP LLM01–LLM10، يُرجع إلى [`spec/security/threat_model.md`](../security/threat_model.md).

---

## البدائل المرفوضة (Alternatives Rejected)
1. **تشغيل Llama Guard بشكل متزامن (Synchronous Blocking) على كل دورة صوتية**:
   - *سبب الرفض*: يضيف من `150ms` إلى `350ms` لكل دورة قبل بدء استدعاء نموذج الحوار الأساسي، مما يستنزف ميزانية الـ `800ms` الصوتية بالكامل.
2. **حظر أي جملة تذكر عرضاً مرضياً بإطلاق (Naive Keyword Blocking on Symptoms)**:
   - *سبب الرفض*: يمنع المريض الطبيعي من قول *"عندي وجع في ركبتي وعايز أحجز دكتور عظام"*؛ لذلك صممنا تمييز `BOOKING_WITH_SYMPTOMS` للسماح بالحجز مع منع التشخيص.
3. **الاعتماد على حزمة Microsoft Presidio الكاملة مع نموذج spaCy NLP الثقيل على المسار الحرج**:
   - *سبب الرفض*: نماذج spaCy الكبيرة تستهلك مئات الميجابايتات ولا تدعم بنية الرقم القومي المصري وأرقام الهواتف المكتوبة بالأرقام الهندية العربية (`٠١٠...`) بنفس سرعة ودقة محركات `PatternRecognizer` المخصصة لدينا (`< 2ms`).

---

## العواقب (Consequences)
### الإيجابيات (Positive)
- حماية فورية (`< 20ms`) ضد المسؤولية الطبية وهجمات الحقن دون إبطاء المحادثة الصوتية.
- توافق كامل مع متطلبات الخصوصية المصرية عبر إخفاء الهواتف والرقم القومي قبل التتبع.

### السلبيات والمقايضات (Negative / Trade-offs)
- تتطلب أنماط التعابير النمطية (`Regex`) في `InputGuardrail` صيانة دورية وتقييماً مستمراً عبر مجموعة السيناريوهات العدائية في `golden_dataset.json` (راجع ADR-006).

</div>
