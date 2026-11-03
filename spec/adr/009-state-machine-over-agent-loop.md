<div dir="rtl" align="right">

# ADR-009: آلة الحالة المحدودة الحتمية (FSM) لسير عمل الحجز بدل حلقات الوكيل المفتوحة

## البيانات الوصفية (Metadata)
- **Status**: Accepted
- **Date**: 2026-11-02
- **Related Feature**: Feature 4.5
- **Code References**:
  - المسارات البرمجية (Files):
    - `src/ai_core/workflow.py`
    - `src/tools/gates.py`
    - `src/tools/appointment_booking.py`
    - `src/tools/manage_appointment.py`
  - مفاتيح الإعدادات (Config Keys in `src.config.Settings`):
    - `workflow_max_steps`
    - `enforce_session_caller_identity`

---

## السياق (Context)
تخضع أنظمة الوكلاء متعددة الخطوات لقانون الموثوقية المركبة (**Compound Reliability Law**): إذا كانت دقة النموذج اللغوي في اتخاذ القرار الصحيح في الخطوة الواحدة `95%`، فإن موثوقية إتمام سير عمل مكون من 10 خطوات حرة تنخفض إلى:
$$0.95^{10} \approx 59.8\%$$
في عيادة طبية، يعني ذلك فشل نحو 40% من محاولات الحجز أو الإلغاء أو استنزاف ميزانية التوكن وزمن الاستجابة في حلقات تفكير مفتوحة (`ReAct / Open-Ended Agent Loops`).

---

## القرار (Decision)
اعتمدنا **آلة الحالة المحدودة الحتمية (`AppointmentWorkflowStateMachine`)** في `src/ai_core/workflow.py` لإدارة جميع عمليات المواعيد (`WorkflowAction`: `BOOK`، `CANCEL`، `RESCHEDULE`، `LOOKUP`):

1. **مسار الحالات الثماني المحددة (`WorkflowState`)**:
   - تنتقل المعاملة حصرياً عبر حالات مضبوطة برمجياً:
     `INIT` $\rightarrow$ `SLOT_COLLECTION` $\rightarrow$ `PRECONDITION_GATE` $\rightarrow$ `IDEMPOTENCY_CHECK` $\rightarrow$ `ATOMIC_EXECUTION` $\rightarrow$ (`COMPLETED` | `REJECTED_BY_GATE` | `ESCALATED`).
2. **التوقف الآمن عند نقص الخانات (`SLOT_COLLECTION`)**:
   - إذا نقصت أي معلومة إلزامية (اسم المريض، رقم الهاتف المصري، اسم الطبيب، أو التاريخ)، تتوقف الآلة عند حالة `SLOT_COLLECTION` وتعيد سؤالاً عربياً مصرياً محدداً للمريض دون إجراء أي اتصال بقاعدة البيانات.
3. **سقف ميزانية الخطوات الصارم (`workflow_max_steps = 6`)**:
   - يسجّل كل انتقال حالة في `WorkflowStepTrace`. إذا تجاوز التنفيذ `workflow_max_steps = 6` خطوات لأي سبب، يطلق النظام استثناء `_StepBudgetExhaustedError` وينتقل فوراً إلى الحالة النهائية `WorkflowState.ESCALATED` لتحويل المريض إلى موظف الاستقبال البشري.

---

## البدائل المرفوضة (Alternatives Rejected)
1. **حلقة وكيل حر مفتوحة النهاية (Unconstrained ReAct / Autonomous Agent Loop)**:
   - *سبب الرفض*: عرضة للدوران اللانهائي عند غموض مدخلات المريض، وتراكم زمن استجابة يتجاوز سقف `800ms`، وصعوبة التنبؤ بسلوكها أو اختبارها حتمياً.
2. **شجرة الرد الآلي الجامدة بالضغط على الأزرار (Legacy DTMF IVR Tree — "اضغط 1 للحجز...")**:
   - *سبب الرفض*: تجربة مستخدم سيئة للغاية هي السبب الرئيسي لبناء المساعد الصوتي الذكي؛ آلة الحالة لدينا تجمع بين فهم اللغة الطبيعية بالعامية المصرية (`parse_colloquial_date`، `parse_visit_type`) وانضباط التنفيذ الحتمي خلف الكواليس.
3. **تنفيذ الحجز بخطوة واحدة مباشرة من الأداة دون فصل مراحل جمع الخانات والبوابة وعدم التكرار**:
   - *سبب الرفض*: يجعل تتبع سبب الفشل في سجلات التتبع (`WorkflowStepTrace`) صعباً، ويخلط بين أخطاء نقص البيانات وأخطاء امتلاء الشيفت.

---

## العواقب (Consequences)
### الإيجابيات (Positive)
- موثوقية حتمية (`100%` في مسار الانتقال البرمجي بعد استخراج الخانات) وسهولة تامة في اختبار كل حالة انتقال في `tests/test_workflow_gates.py`.
- استحالة حدوث حلقات لا نهائية بفضل سقف `workflow_max_steps = 6`.

### السلبيات والمقايضات (Negative / Trade-offs)
- إضافة نوع جديد من الإجراءات (مثلاً: حجز فحص معملي مستقل عن جدول الأطباء مستقبلاً) يتطلب تعريف مسار انتقال صريح في `AppointmentWorkflowStateMachine` بدلاً من الاكتفاء بإضافة وصف أداة في البرومبت.

</div>
