<div dir="rtl" align="right">

# ADR-004: التتبع الهرمي المستضاف ذاتياً عبر Langfuse وOpenTelemetry لحماية سيادة بيانات المرضى

## البيانات الوصفية (Metadata)
- **Status**: Accepted
- **Date**: 2026-11-02
- **Related Feature**: Feature 4.6
- **Code References**:
  - المسارات البرمجية (Files):
    - `src/ai_core/tracing.py`
    - `src/ai_core/guardrails.py`
    - `src/config.py`
  - مفاتيح الإعدادات (Config Keys in `src.config.Settings`):
    - `tracing_enabled`
    - `langfuse_enabled`
    - `langfuse_host`
    - `langfuse_public_key`
    - `langfuse_secret_key`
    - `tracing_batch_size`
    - `tracing_flush_interval_s`
    - `tracing_http_timeout_s`
    - `tracing_max_queue_size`
    - `tracing_ring_buffer_size`

---

## السياق (Context)
في نظام ذكاء اصطناعي طبي متعدد الخطوات (حواجز حماية ← كاش ← توجيه مراحل ← LLM ← أدوات ← قاعدة بيانات)، لا يكفي رمز الحالة `HTTP 200` لكشف الأعطال الصامتة؛ إذ يجب معرفة زمن وتكلفة ومدخلات ومخرجات كل خطوة داخل كل دورة محادثة.

غير أن إرسال سجلات المحادثات الطبية إلى منصات تتبع سحابية خارجية (SaaS) ينتهك مبدأ **سيادة بيانات المرضى وخصوصيتها**، كما أن التصدير الشبكي المتزامن على المسار الصوتي يهدد ميزانية زمن الاستجابة (`< 800ms`).

---

## القرار (Decision)
قمنا ببناء محرك **التتبع الهرمي (`HierarchicalTracer`)** في `src/ai_core/tracing.py` المتوافق مع OpenTelemetry ومصدّر **Langfuse المستضاف ذاتياً (`AsyncTraceExporter`)**:

1. **بنية الشجرة الهرمية وعزل السياق (`contextvars`)**:
   - توليد `trace_id` بطول 128-بت (32 محرفاً ست عشرياً) و`span_id` / `parent_span_id` بطول 64-بت متوافقة مع معيار W3C Trace Context v1 (`00-<trace_id>-<span_id>-01`) عبر `format_traceparent` و`parse_traceparent`.
   - عزل كامل بين المكالمات المتزامنة باستخدام `contextvars` عبر `trace_scope` و`span_scope` والمزخرف `@traced_span`.
2. **التنقية الإلزامية للبيانات الشخصية قبل الحفظ أو التصدير**:
   - تمرير كافة المدخلات والمخرجات والبيانات الوصفية عبر `EgyptianPIIRedactor.redact_dict` لتنقية أرقام الهواتف المصرية والرقم القومي (14 رقماً) قبل دخولها إلى الذاكرة الدائرية (`tracing_ring_buffer_size = 200`) أو طابور التصدير.
3. **التصدير غير المتزامن على دفعات (`< 1ms` على المسار الحرج)**:
   - تسجيل الـ Span على المسار الصوتي يتم في الذاكرة فقط في أقل من `1ms`.
   - يقوم `AsyncTraceExporter` بسحب الأحداث في الخلفية من طابور بسعة `tracing_max_queue_size = 1000` وإرسالها على دفعات بحجم `tracing_batch_size = 20` كل `tracing_flush_interval_s = 2.0` ثانية وبمهلة `tracing_http_timeout_s = 2.0` ثانية إلى خادم Langfuse المحلي (`langfuse_host = "http://localhost:3000"`).
   - عند تعطيل Langfuse (`langfuse_enabled = False`) أو توقف خادمه، يستمر النظام بالعمل الطبيعي دون أي استثناء أو تأثير على المكالمة (`No-Op Degradation`).

---

## البدائل المرفوضة (Alternatives Rejected)
1. **منصات التتبع السحابية المستضافة خارجياً (مثل LangSmith SaaS أو Helicone Cloud)**:
   - *سبب الرفض*: تتطلب إرسال نصوص محادثات المرضى وبيانات المواعيد إلى خوادم طرف ثالث خارج البنية التحتية للعيادة، مما يتعارض مع متطلبات الخصوصية الطبية وسيادة البيانات.
2. **التصدير الشبكي المتزامن (Synchronous HTTP Trace Logging) أثناء دورة المحادثة**:
   - *سبب الرفض*: يضيف من `50ms` إلى `300ms` لكل Span، ويعرّض المكالمة الصوتية للتوقف إذا تباطأ خادم التتبع.
3. **الاعتماد على سجلات النص المسطحة (`stdout` / `logging` التقليدي) فقط**:
   - *سبب الرفض*: يستحيل من خلالها إعادة بناء شجرة الاستدعاءات المتداخلة (`parent_span_id`) أو تجميع التوكنات والتكلفة بالدولار وزمن TTFT لكل دورة محادثة عند وجود عشرات المكالمات المتزامنة.

---

## العواقب (Consequences)
### الإيجابيات (Positive)
- بقاء جميع آثار المحادثات داخل البنية التحتية للعيادة مع تنقية تلقائية لبيانات الهوية المصرية.
- حمل شبه معدوم (`< 1ms`) على المسار الصوتي الفوري، وتجميع تلقائي للتكلفة والتوكنات وتصنيف الأخطاء (`INFRASTRUCTURE` مقابل `SEMANTIC`).

### السلبيات والمقايضات (Negative / Trade-offs)
- عند امتلاء طابور التصدير في حالات الضغط القصوى (`> 1000` حدث قيد الانتظار مع توقف Langfuse)، يتم إسقاط أقدم أحداث التتبع (`Drop-Oldest`) للحفاظ على ذاكرة التطبيق وسلامة المكالمات الحية.
- تتطلب بيئة الإنتاج الكاملة تشغيل حاوية Langfuse ضمن Docker Compose (المرحلة 8).

</div>
