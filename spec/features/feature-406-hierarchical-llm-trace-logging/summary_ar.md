<div dir="rtl" align="right">

# ملخص مواصفات الميزة 4.6: التتبع الهرمي لنماذج اللغة وحساب التكلفة (`Hierarchical LLM Trace Logging`)

تم إعداد ملفات المواصفات الثلاثة الخاصة بـ **Feature 4.6** في المجلد [`spec/features/feature-406-hierarchical-llm-trace-logging/`](file:///d:/AI%20Projects/Voice_Agent_For_Clinics/Voice_Agent/spec/features/feature-406-hierarchical-llm-trace-logging/):
- [`plan.md`](file:///d:/AI%20Projects/Voice_Agent_For_Clinics/Voice_Agent/spec/features/feature-406-hierarchical-llm-trace-logging/plan.md)
- [`requirements.md`](file:///d:/AI%20Projects/Voice_Agent_For_Clinics/Voice_Agent/spec/features/feature-406-hierarchical-llm-trace-logging/requirements.md)
- [`validation.md`](file:///d:/AI%20Projects/Voice_Agent_For_Clinics/Voice_Agent/spec/features/feature-406-hierarchical-llm-trace-logging/validation.md)

---

## 1. ملخص خطة العمل (`plan.md`)

- **الهدف الأساسي**: بناء محرك تتبع هرمي (`src/ai_core/tracing.py`) فائق السرعة (**أقل من 1 مللي ثانية** على المسار الساخن للمكالمة) متوافق مع معايير **OpenTelemetry (`W3C traceparent`)** ومنصة **Langfuse المستضافة ذاتياً (Self-Hosted)**.
- **أهم القرارات المعمارية (بناءً على اختياراتك)**:
  1. **تصدير غير متزامن خفيف الوزن عبر `httpx`**: استخدام بروتوكول REST الخاص بـ Langfuse (`/api/public/ingestion`) ومعرفات W3C القياسية (`trace_id` من 32 حرفاً سداسياً عشرياً و`span_id` من 16 حرفاً) بدون إضافة مكتبات خارجية ثقيلة في `pyproject.toml`.
  2. **الدمج التلقائي الشفاف (Auto-Instrumentation)**: ربط تلقائي داخل المكونات الأساسية (`ModelGateway`، `CacheLadder`، `InputGuardrail`، `OutputGuardrail`، `AppointmentWorkflowStateMachine`، `HybridRetriever`) بحيث تسجل Spans فرعية تلقائياً عند وجود `trace_scope` نشط في `contextvars`، وتتحول إلى `No-Op` عند عدم وجوده لعدم كسر أي اختبارات سابقة.
  3. **تنقية البيانات الشخصية المصرية (PII Redaction) في الخلفية**: يتم إخفاء أرقام الهواتف المصرية والرقم القومي المكون من 14 رقماً عبر `EgyptianPIIRedactor.redact_dict()` أثناء عملية الـ Flush غير المتزامنة، مما يحافظ على زمن المسار الساخن (< 0.1ms) ويضمن عدم تسرب أي بيانات خام.
  4. **سجل دائري في الذاكرة (`Ring Buffer`) + تصدير دفعي (`Batch Export`)**: الاحتفاظ بآخر 200 Trace منقّاة في `tracer.recent_traces` مع دالة `await tracer.flush()` لسهولة الفحص في الاختبارات ولوحة تحكم Streamlit، بالإضافة إلى الإرسال الدفعي لـ Langfuse عند تفعيله.

---

## 2. ملخص المتطلبات (`requirements.md`)

- **المتطلبات الوظيفية**:
  - **R1 (شجرة التتبع الهرمية)**: توليد `trace_id` فريد لكل دورة محادثة (`trace_scope`) وربط جميع الـ Spans الفرعية عبر `span_id` و`parent_span_id` مع تصنيف نوع المرحلة (`SpanKind`) وحالتها (`SpanStatus`).
  - **R2 (التجميع التلقائي للتوكنز والتكلفة والكمون)**: تجميع `total_prompt_tokens`، `total_completion_tokens`، `total_tokens`، والتكلفة التقديرية بالدولار (`total_cost_usd` من جدول أسعار النماذج في `src/config.py`)، و`ttft_ms`، ومستوى التدهور `degradation_tier`، وتصنيف الأخطاء (`INFRASTRUCTURE` مقابل `SEMANTIC` مقابل `SECURITY_BLOCK`).
  - **R3 (عزل التزامن عبر `contextvars` ودعم `traceparent`)**: ضمان عدم تداخل المكالمات المتزامنة (`asyncio.gather`)، ودعم توليد وقراءة ترويسة W3C `traceparent` (`00-<trace_id>-<span_id>-01`).
  - **R4 (إخفاء الـ PII المصري قبل التصدير)**: تنقية كافة المدخلات والمخرجات والخصائص من أرقام الهواتف والرقم القومي قبل الحفظ في الـ Ring Buffer أو الإرسال إلى Langfuse.
  - **R5 (التصدير إلى Langfuse والاعتمادية)**: إرسال الدفعات إلى `/api/public/ingestion`، والتحول الآمن إلى `No-Op` في حال تعطل خادم Langfuse دون التأثير على المكالمة، وربط نتائج فحص `AsyncLlamaGuardClassifier` بالـ Trace عبر `trace_id`.
- **المتطلبات غير الوظيفية والقيود**:
  - زمن العبء على المسار الساخن (Hot-Path Overhead) **أقل من 1 مللي ثانية**.
  - عدم إضافة اعتماديات ثقيلة، والحفاظ على التوافق الكامل (100%) مع اختبارات المراحل 1 إلى 4.

---

## 3. ملخص معايير التحقق (`validation.md`)

- **المستوى 1 (Unit Verification)**: اختبار توليد وقراءة `traceparent`، تسلسل `parent_span_id` متعدد المستويات، دقة حساب تكلفة التوكنز (`estimate_llm_cost_usd`)، واختبار الأداء (< 1ms على المسار الساخن).
- **المستوى 2 (Integration Verification)**: اختبار التكامل التلقائي عبر `InputGuardrail -> CacheLadder -> ModelGateway -> OutputGuardrail` داخل `trace_scope`، والتحقق من تنقية الـ PII المصري، وبنية حزمة Langfuse عبر `httpx.MockTransport`، وربط نتيجة `AsyncLlamaGuardClassifier`.
- **المستوى 3 (Error & Edge-Case Verification)**: اختبار 20 مهمة غير متزامنة في نفس الوقت (`asyncio.gather`) لإثبات عزل `contextvars`، واختبار تعطل/انتهاء مهلة Langfuse (HTTP 503 / Timeout) دون كسر التدفق.
- **المستوى 4 و 5 و 7 (Regression, Lint & CLI Checks)**: تشغيل جميع اختبارات المراحل السابقة للتأكد من عدم وجود أي تراجع (Zero Regressions)، وفحص الكود عبر `ruff check` و`ruff format`، واختبار دخاني مباشر عبر سطر الأوامر (CLI).

---

🛑 **بانتظار مراجعتك واعتمادك (Mandatory Gate)**:
يرجى مراجعة المواصفات وإبلاغي بالموافقة (مثل: **"اعتمد"** أو **"go ahead"**) للبدء في كتابة الكود وتنفيذ الميزة 4.6.

</div>
