<div dir="rtl" align="right">

# ADR-003: بوابة النماذج متعددة المستويات (Groq + Gemini Fallback) وقاطع الدائرة و4 درجات تدهور

## البيانات الوصفية (Metadata)
- **Status**: Accepted
- **Date**: 2026-11-02
- **Related Feature**: Feature 4.1
- **Code References**:
  - المسارات البرمجية (Files):
    - `src/ai_core/gateway.py`
    - `src/ai_core/circuit_breaker.py`
    - `src/config.py`
  - مفاتيح الإعدادات (Config Keys in `src.config.Settings`):
    - `groq_model`
    - `llm_stage_model`
    - `gemini_fallback_model`
    - `llm_ttft_timeout_s`
    - `llm_request_timeout_s`
    - `voice_max_tokens`
    - `stage_max_tokens`
    - `circuit_breaker_failure_threshold`
    - `circuit_breaker_window_s`
    - `circuit_breaker_cooldown_s`

---

## السياق (Context)
تتطلب المحادثة الصوتية الفورية زمن استجابة كلي أقل من `800ms`، بحيث لا يتجاوز زمن أول توكن للنموذج اللغوي (`TTFT`) حاجز `300ms` في الحالات الطبيعية. الاعتماد على مزوّد سحابي واحد يعرّض العيادة لخطر انقطاع المكالمات عند حدوث أخطاء `429 Rate Limit` أو `5xx` أو بطء مفاجئ في الشبكة.

في المسودات الأولية لخطة المشروع (`feature-400`)، طُرح اسم OpenAI (`gpt-4o-mini`) كمزوّد احتياطي، لكن عند البناء الفعلي (`As-Built`) تبيّنت الحاجة إلى مزوّد احتياطي يتمتع بنافذة سياق واسعة، وسرعة تدفق عالية، وتكلفة أقل لكل مليون توكن، ودعم ممتاز للعامية المصرية عبر LiteLLM.

---

## القرار (Decision)
اعتمدنا معمارية **بوابة النماذج (`ModelGateway`)** في `src/ai_core/gateway.py` مع **قاطع الدائرة (`CircuitBreaker`)** في `src/ai_core/circuit_breaker.py`:

1. **النموذج الأساسي ونموذج المراحل الخفيفة (Groq Cloud)**:
   - حوار المريض الصوتي (`Stage.DIALOGUE`): يستخدم `groq_model = "llama-3.3-70b-versatile"` بسقف مخرجات صارم `voice_max_tokens = 150`.
   - تصنيف النية واستخراج الكيانات (`Stage.CLASSIFICATION`، `Stage.EXTRACTION`): يستخدم `llm_stage_model = "llama-3.1-8b-instant"` بسقف `stage_max_tokens = 256`.
2. **النموذج الاحتياطي المعتمد (Google Gemini `gemini-2.0-flash`)**:
   - اعتماد `gemini_fallback_model = "gemini-2.0-flash"` عبر طبقة تجريد `LiteLLMProvider` كمزوّد ثانوي مستقل تماماً عن البنية التحتية لـ Groq.
3. **قاطع الدائرة (`CircuitBreaker`) ومهلة TTFT**:
   - مهلة زمن أول توكن `llm_ttft_timeout_s = 3.5` ثانية ومهلة الطلب الكلي `llm_request_timeout_s = 10.0` ثوانٍ.
   - يفتح قاطع الدائرة (`BreakerState.OPEN`) بعد `circuit_breaker_failure_threshold = 5` إخفاقات بنية تحتية متتالية ضمن نافذة `circuit_breaker_window_s = 60.0` ثانية، فيحوّل الطلبات فوراً (`< 1ms`) إلى Gemini لمدة تهدئة `circuit_breaker_cooldown_s = 60.0` ثانية قبل إرسال طلب استكشافي واحد في حالة `BreakerState.HALF_OPEN`.
   - أخطاء التحقق الدلالي أو البرمجي (`ValueError`، `ValidationError`) لا تُحتسب ضد قاطع الدائرة عبر دالة `classify_error`.
4. **سلسلة التدهور الرشيق رباعية المستويات (`DegradationTier`)**:
   - `TIER_1_PRIMARY`: Groq (`llama-3.3-70b-versatile` / `llama-3.1-8b-instant`).
   - `TIER_2_BACKUP`: Google Gemini (`gemini-2.0-flash`).
   - `TIER_3_SEARCH_ONLY`: إرجاع مقتطف موثّق مباشرة من قاعدة المعرفة (`clinic_kb.md`) بدون استدعاء LLM.
   - `TIER_4_HUMAN_ESCALATION`: تحويل فوري لموظف الاستقبال البشري مع رسالة صوتية مهذبة بالعامية المصرية؛ **لا تنقطع المكالمة أبداً**.

---

## البدائل المرفوضة (Alternatives Rejected)
1. **استخدام OpenAI (`gpt-4o-mini`) كمزوّد احتياطي للاستنتاج الفوري**:
   - *سبب الرفض*: تم رفض OpenAI في مسار التوليد الاحتياطي لصالح `gemini-2.0-flash` لثلاثة أسباب: (أ) تكلفة Gemini أقل بنسبة ~33% في التوكنات المدخلة والمخرجة (`$0.10 / $0.40` مقابل `$0.15 / $0.60` لكل مليون توكن)، (ب) زمن استجابة التوليد التدفقّي (TTFT) في `gemini-2.0-flash` أسرع ومناسب لميزانية الصوت، و(ج) تخصيص `gpt-4o-mini` ليكون حَكَم التقييم المستقل في RAGAS CI (راجع ADR-006) حتى لا يكون الحَكَم من نفس عائلة نماذج التوليد الأساسي أو الاحتياطي.
2. **إعادة المحاولة المتكررة على نفس المزوّد (Exponential Backoff Retries)**:
   - *سبب الرفض*: في المكالمات الصوتية الفورية، تؤدي إعادة المحاولة مع الانتظار التدريجي إلى صمت طويل على الخط يدفع المريض لإغلاق الهاتف. الفشل السريع (`Fail-Fast`) والتحويل الفوري لمزوّد مستقل هو الخيار الوحيد المتوافق مع SLA الصوت.
3. **الاعتماد على مزوّد واحد دون سلسلة تدهور (Single Provider without Degradation)**:
   - *سبب الرفض*: أي عطل في Groq سيؤدي إلى سقوط كامل لخدمة الرد الآلي للعيادة.

---

## العواقب (Consequences)
### الإيجابيات (Positive)
- توافرية عالية جداً؛ حتى لو تعطل Groq وGemini معاً، يستمر النظام بالرد من قاعدة المعرفة (`TIER_3_SEARCH_ONLY`) أو التحويل للاستقبال (`TIER_4_HUMAN_ESCALATION`).
- فصل تام بين نماذج التوليد على المسار الحرج (Groq + Gemini) ونموذج التحكيم في الاختبارات (`gpt-4o-mini`).

### السلبيات والمقايضات (Negative / Trade-offs)
- ضرورة إدارة مفتاحي API (`GROQ_API_KEY` و`GEMINI_API_KEY`) في بيئة الإنتاج.
- احتمال وجود اختلاف طفيف في صياغة الجمل العامية بين `llama-3.3-70b-versatile` و`gemini-2.0-flash` عند حدوث التحويل التلقائي (تُخفف حدته عبر توحيد برومبت النظام وحواجز المخرجات).

</div>
